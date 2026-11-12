"""BaseWorkerAgent and Lazy Skill Loading (Task 2.3 / F02.2)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import inspect
from pathlib import Path
import time
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Agent, AgentSkill, Skill, Task, TurnLog
from app.llm.router import LlmRouter
from datetime import datetime, timezone
import uuid


class SkillPathError(ValueError):
    """Raised when a skill file path attempts directory traversal or leaves allowed directories."""


@dataclass
class WorkerResult:
    """Structured result returned by a worker agent after executing a subtask."""

    subtask_id: str
    agent_id: str
    status: str = "completed"
    output: Any = None
    content: str = ""
    model_used: Optional[str] = None
    tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    skills_loaded: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "subtask_id": self.subtask_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "output": self.output,
            "content": self.content,
            "model_used": self.model_used,
            "tokens": self.tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "skills_loaded": list(self.skills_loaded),
            "error": self.error,
        }


class BaseWorkerAgent:
    """Worker agent wrapping an Agent ORM record, LlmRouter, and lazy skill loader."""

    def __init__(
        self,
        agent: Agent,
        llm_router: Optional[LlmRouter] = None,
        session_factory: Optional[sessionmaker[Session]] = None,
        db: Optional[Session] = None,
        allowed_skill_dirs: Optional[Iterable[Path | str]] = None,
        executor_fn: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.agent = agent
        self.llm_router = llm_router or LlmRouter()
        self.session_factory = session_factory
        self.db = db
        self.executor_fn = executor_fn

        if allowed_skill_dirs is not None:
            self.allowed_skill_dirs = [Path(d).resolve() for d in allowed_skill_dirs]
        else:
            settings = get_settings()
            self.allowed_skill_dirs = [
                (settings.workspace_dir / "skills").resolve(),
                (Path.cwd() / "skills").resolve(),
            ]

        # Lazy skill cache: intentionally empty at __init__ so tokens are only
        # loaded when load_skill() is explicitly invoked during execution.
        self._loaded_skills: dict[str, str] = {}

    @property
    def loaded_skills(self) -> dict[str, str]:
        """Return a shallow copy of currently cached skill instructions."""
        return dict(self._loaded_skills)

    def _validate_and_resolve_skill_path(self, raw_path: str) -> Optional[Path]:
        """Validate that raw_path cannot escape allowed_skill_dirs.

        Raises:
            SkillPathError: If null bytes, relative traversal ('..'), or an absolute
                path outside allowed_skill_dirs is detected.
        """
        if "\x00" in raw_path:
            raise SkillPathError("Skill path contains invalid null byte")

        candidate = Path(raw_path)
        if candidate.is_absolute():
            resolved = candidate.resolve()
            if not any(resolved.is_relative_to(allowed) for allowed in self.allowed_skill_dirs):
                raise SkillPathError(
                    f"Skill path '{raw_path}' is outside allowed skill directories"
                )
            return resolved

        # Relative path: check against allowed_skill_dirs and reject any escape
        valid_candidates: list[Path] = []
        for allowed in self.allowed_skill_dirs:
            resolved = (allowed / candidate).resolve()
            if not resolved.is_relative_to(allowed):
                raise SkillPathError(
                    f"Skill path traversal detected: '{raw_path}' escapes '{allowed}'"
                )
            valid_candidates.append(resolved)

        for path_option in valid_candidates:
            if path_option.exists() and path_option.is_file():
                return path_option

        return valid_candidates[0] if valid_candidates else None

    def _lookup_skill(self, skill_id: str, db: Optional[Session]) -> Optional[Skill]:
        if db is None:
            return None
        skill = db.get(Skill, skill_id)
        if skill is None:
            skill = (
                db.query(Skill)
                .filter(func.lower(Skill.name) == skill_id.lower())
                .first()
            )
        return skill

    def load_skill(self, skill_id: str, db: Optional[Session] = None) -> str:
        """Lazily load skill instructions from Skill record / SKILL.md when invoked.

        Validates that any filesystem path stays inside allowed_skill_dirs and
        returns a clean fallback string if the SKILL.md file is absent or optional.
        """
        if skill_id in self._loaded_skills:
            return self._loaded_skills[skill_id]

        skill: Optional[Skill] = None
        if db is not None:
            skill = self._lookup_skill(skill_id, db)
        elif self.db is not None:
            skill = self._lookup_skill(skill_id, self.db)
        elif self.session_factory is not None:
            with self.session_factory() as temp_db:
                skill = self._lookup_skill(skill_id, temp_db)

        if skill is None:
            fallback = f"Skill '{skill_id}': no additional instructions registered."
            self._loaded_skills[skill_id] = fallback
            return fallback

        raw_path = getattr(skill, "file_path", None) or getattr(skill, "skill_md_path", None)
        if raw_path:
            resolved_path = self._validate_and_resolve_skill_path(str(raw_path))
            if resolved_path is not None and resolved_path.exists() and resolved_path.is_file():
                text = resolved_path.read_text(encoding="utf-8")
                self._loaded_skills[skill_id] = text
                return text

        if skill.content and skill.content.strip():
            self._loaded_skills[skill_id] = skill.content
            return skill.content

        fallback = (
            f"Skill '{skill.name}' ({skill.id}): "
            f"{skill.description or 'No additional instructions.'}"
        )
        self._loaded_skills[skill_id] = fallback
        return fallback

    def _resolve_requested_skill_ids(
        self,
        subtask: Any,
        context: dict[str, Any],
        db: Optional[Session],
    ) -> list[str]:
        """Collect skill IDs explicitly requested on the subtask or matching attached skills."""
        skill_ids: list[str] = []

        if isinstance(subtask, dict):
            meta = subtask.get("metadata") or {}
            raw_ids = subtask.get("skill_ids") or meta.get("skill_ids") or []
            instruction = str(subtask.get("instruction", ""))
        else:
            meta = getattr(subtask, "metadata", None) or {}
            raw_ids = getattr(subtask, "skill_ids", None) or meta.get("skill_ids") or []
            instruction = str(getattr(subtask, "instruction", ""))

        for sid in raw_ids:
            if sid and sid not in skill_ids:
                skill_ids.append(str(sid))

        for sid in context.get("skill_ids") or []:
            if sid and sid not in skill_ids:
                skill_ids.append(str(sid))

        # Optional: if attached skills are mentioned in instruction or explicitly requested
        if db is not None and self.agent is not None:
            attached = (
                db.query(AgentSkill)
                .filter(AgentSkill.agent_id == self.agent.id, AgentSkill.is_active.is_(True))
                .all()
            )
            load_all = bool(meta.get("load_attached_skills", False))
            instr_lower = instruction.lower()
            for link in attached:
                if link.skill_id in skill_ids:
                    continue
                if load_all:
                    skill_ids.append(link.skill_id)
                elif link.skill and (
                    link.skill.name.lower() in instr_lower
                    or link.skill_id.lower() in instr_lower
                ):
                    skill_ids.append(link.skill_id)

        return skill_ids

    async def execute(
        self,
        subtask: Any,
        context: Optional[dict[str, Any]] = None,
        db_session_factory: Optional[sessionmaker[Session]] = None,
    ) -> WorkerResult:
        """Execute a subtask with lazy skill injection and LlmRouter accounting."""
        t0 = time.perf_counter()
        ctx = dict(context or {})
        factory = db_session_factory or self.session_factory
        db_lock: Optional[asyncio.Lock] = ctx.get("db_lock")
        task_id: Optional[str] = ctx.get("task_id")

        if isinstance(subtask, dict):
            subtask_id = str(subtask.get("id", "subtask"))
            instruction = str(subtask.get("instruction", ""))
        else:
            subtask_id = str(getattr(subtask, "id", "subtask"))
            instruction = str(getattr(subtask, "instruction", ""))

        # 1. Lazy Skill Loading (only load skills relevant to this invocation)
        loaded_skill_texts: list[tuple[str, str]] = []

        async def _load_skills_with_session(session: Optional[Session]) -> None:
            requested_ids = self._resolve_requested_skill_ids(subtask, ctx, session)
            for sid in requested_ids:
                text = self.load_skill(sid, db=session)
                loaded_skill_texts.append((sid, text))

        if factory is not None:
            if db_lock is not None:
                async with db_lock:
                    with factory() as s:
                        await _load_skills_with_session(s)
            else:
                with factory() as s:
                    await _load_skills_with_session(s)
        else:
            await _load_skills_with_session(self.db)

        # 2. Custom executor hook if provided
        if self.executor_fn is not None:
            sig = inspect.signature(self.executor_fn)
            if len(sig.parameters) <= 1:
                raw = self.executor_fn(subtask)
            else:
                raw = self.executor_fn(subtask, ctx)
            if inspect.isawaitable(raw):
                raw = await raw

            duration_ms = max(1, int((time.perf_counter() - t0) * 1000))
            if isinstance(raw, WorkerResult):
                raw.duration_ms = raw.duration_ms or duration_ms
                if not raw.skills_loaded:
                    raw.skills_loaded = [sid for sid, _ in loaded_skill_texts]
                return raw
            return WorkerResult(
                subtask_id=subtask_id,
                agent_id=self.agent.id,
                status="completed",
                output=raw,
                content=str(raw) if raw is not None else "",
                duration_ms=duration_ms,
                skills_loaded=[sid for sid, _ in loaded_skill_texts],
            )

        # 3. Build LLM prompt messages with lazily injected skill instructions
        system_prompt = (
            self.agent.system_prompt
            or f"You are {self.agent.display_name} ({self.agent.role})."
        )
        if loaded_skill_texts:
            skill_blocks = "\n\n".join(
                f"### Skill: {sid}\n{text}" for sid, text in loaded_skill_texts
            )
            system_prompt = f"{system_prompt}\n\n{skill_blocks}"

        user_prompt = instruction
        dep_outputs = ctx.get("dependency_outputs")
        if isinstance(dep_outputs, dict) and dep_outputs:
            deps_str = "\n".join(f"- {k}: {v}" for k, v in dep_outputs.items())
            user_prompt = f"{instruction}\n\nPrevious step outputs:\n{deps_str}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # 4. Enforce quota & invoke LlmRouter without holding DB lock across network I/O
        if factory is not None:
            async def _enforce_quota() -> None:
                with factory() as s:
                    self.llm_router.quota_service.enforce_quota(s)

            if db_lock is not None:
                async with db_lock:
                    await _enforce_quota()
            else:
                await _enforce_quota()

            llm_resp = await self.llm_router.complete(
                agent=self.agent,
                messages=messages,
                db=None,
                task_id=task_id,
                temperature=self.agent.temperature,
                max_tokens=self.agent.max_tokens,
            )

            async def _record_usage() -> None:
                from app.orchestrator.dispatcher import mask_secrets

                with factory() as s:
                    turn_log_id: Optional[str] = None
                    if llm_resp.fallback_triggered and task_id and s.get(Task, task_id):
                        cnt = s.query(TurnLog).filter_by(task_id=task_id).count()
                        fb_turn = TurnLog(
                            id=f"turn-{uuid.uuid4().hex[:12]}",
                            task_id=task_id,
                            agent_id=self.agent.id if s.get(Agent, self.agent.id) else None,
                            turn_number=cnt + 1,
                            action="fallback_model",
                            tool="llm_router",
                            input_payload=mask_secrets({
                                "primary": self.agent.default_model,
                                "fallback": self.agent.fallback_model,
                                "error_history": llm_resp.provider_error_history,
                            }),
                            output_payload=mask_secrets({
                                "selected_model": llm_resp.model_used,
                                "status": "switched",
                            }),
                            tokens=llm_resp.total_tokens,
                            status="completed",
                            created_at=datetime.now(timezone.utc),
                        )
                        s.add(fb_turn)
                        s.commit()
                        s.refresh(fb_turn)
                        turn_log_id = fb_turn.id

                    self.llm_router.quota_service.record_cost(
                        db=s,
                        task_id=task_id,
                        agent_id=self.agent.id,
                        model=llm_resp.model_used,
                        input_tokens=llm_resp.input_tokens,
                        output_tokens=llm_resp.output_tokens,
                        cost_usd=llm_resp.cost_usd,
                        is_estimated=llm_resp.is_estimated,
                        turn_log_id=turn_log_id,
                    )

            if db_lock is not None:
                async with db_lock:
                    await _record_usage()
            else:
                await _record_usage()
        else:
            llm_resp = await self.llm_router.complete(
                agent=self.agent,
                messages=messages,
                db=self.db,
                task_id=task_id,
                temperature=self.agent.temperature,
                max_tokens=self.agent.max_tokens,
            )

        duration_ms = max(1, int((time.perf_counter() - t0) * 1000))
        return WorkerResult(
            subtask_id=subtask_id,
            agent_id=self.agent.id,
            status="completed",
            output={"content": llm_resp.content, "model_used": llm_resp.model_used},
            content=llm_resp.content,
            model_used=llm_resp.model_used,
            tokens=llm_resp.total_tokens,
            input_tokens=llm_resp.input_tokens,
            output_tokens=llm_resp.output_tokens,
            cost_usd=llm_resp.cost_usd,
            duration_ms=duration_ms,
            skills_loaded=[sid for sid, _ in loaded_skill_texts],
        )
