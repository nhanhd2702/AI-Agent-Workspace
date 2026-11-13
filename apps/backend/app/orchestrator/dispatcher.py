"""Agent Dispatcher, Secret Masking, Concurrency Guard, and Turn Logging (Task 2.3 / F01.3 / F03.3)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
import re
import time
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from app.agents.base import BaseWorkerAgent, WorkerResult
from app.config import get_settings
from app.db.models import Agent, Artifact, ReviewGate, SubTask, Task, TaskStatus, TurnLog
from app.db.state_machine import TaskStateMachine
from app.llm.router import LlmRouter
from app.orchestrator.planner import ExecutionPlan, SubTaskNode

if TYPE_CHECKING:
    from app.api.ws import TaskWebSocketManager


class TaskDispatchConflictError(RuntimeError):
    """Raised when a task cannot be dispatched from its current lifecycle state."""


# ============================================================================
# Secret Masking Utility
# ============================================================================

_SECRET_KEYS_PATTERN = (
    r"password|passwd|pwd|api_?key|secret|local_auth_token|auth_token|"
    r"access_token|refresh_token|client_secret|private_key|bearer_token|"
    r"x-local-auth-token|authorization"
)

_SECRET_STRING_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # OpenAI / Anthropic style keys (sk-..., sk-proj-..., sk-ant-...)
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "sk-***REDACTED***"),
    # Google / Gemini API keys (AIza...)
    (re.compile(r"\bAIza[0-9A-Za-z_-]{10,}\b"), "AIza***REDACTED***"),
    # Bearer tokens (unquoted or quoted)
    (
        re.compile(r"(?i)\bBearer\s+(['\"]?)([A-Za-z0-9._~+/=-]+)\1"),
        r"Bearer \1***REDACTED***\1",
    ),
    # Slack tokens (xoxb-, xoxp-, xoxa-, etc.)
    (re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{6,}\b"), "xox-***REDACTED***"),
    # GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_)
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{10,}\b"), "gh_***REDACTED***"),
    # Quoted JSON / dict-string / key="value" assignments (supports spaces inside quotes)
    (
        re.compile(
            rf"(?i)(['\"]?)\b({_SECRET_KEYS_PATTERN})\b\1(\s*[:=]\s*)(['\"])([^'\"]*)\4"
        ),
        r"\1\2\1\3\4***REDACTED***\4",
    ),
    # Unquoted key=value or Header: value assignments
    (
        re.compile(
            rf"(?i)(['\"]?)\b({_SECRET_KEYS_PATTERN})\b\1(\s*[:=]\s*)([^\s'\",;}}{{]+)"
        ),
        r"\1\2\1\3***REDACTED***",
    ),
]

_SENSITIVE_DICT_KEY_RE = re.compile(
    r"^(authorization|x-local-auth-token|(.*_)?(api_?key|secret|password|passwd|pwd|private_key|access_token|refresh_token|auth_token|local_auth_token|bearer_token|client_secret))$",
    re.IGNORECASE,
)


def mask_secrets(
    data: Any,
    extra_secrets: Optional[Iterable[str]] = None,
) -> Any:
    """Recursively redact API keys, tokens, and credentials from strings, bytes, dicts, and lists."""
    extra_list = [s for s in (extra_secrets or ()) if isinstance(s, str) and len(s) >= 4]

    def _mask_str(text: str) -> str:
        masked = text
        for pattern, replacement in _SECRET_STRING_PATTERNS:
            masked = pattern.sub(replacement, masked)
        for sec in extra_list:
            if sec in masked:
                masked = masked.replace(sec, "***REDACTED***")
        return masked

    def _walk(node: Any) -> Any:
        if node is None or isinstance(node, (bool, int, float)):
            return node
        if isinstance(node, str):
            return _mask_str(node)
        if isinstance(node, (bytes, bytearray)):
            return _mask_str(bytes(node).decode("utf-8", errors="replace"))
        if isinstance(node, dict):
            cleaned: dict[Any, Any] = {}
            for k, v in node.items():
                key_str = str(k)
                if _SENSITIVE_DICT_KEY_RE.match(key_str) and not isinstance(
                    v, (dict, list, tuple)
                ):
                    if v not in (None, "", b"", bytearray()):
                        cleaned[k] = "***REDACTED***"
                    else:
                        cleaned[k] = v
                else:
                    cleaned[k] = _walk(v)
            return cleaned
        if isinstance(node, (list, tuple)):
            items = [_walk(item) for item in node]
            return tuple(items) if isinstance(node, tuple) else items
        return _mask_str(str(node))

    return _walk(data)


# ============================================================================
# DispatchResult
# ============================================================================


@dataclass
class DispatchResult:
    """Summary of a full DAG dispatch execution."""

    task_id: str
    status: str
    completed_nodes: list[str] = field(default_factory=list)
    failed_nodes: list[str] = field(default_factory=list)
    turn_logs: list[dict[str, Any]] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "completed_nodes": list(self.completed_nodes),
            "failed_nodes": list(self.failed_nodes),
            "turn_logs": list(self.turn_logs),
            "outputs": dict(self.outputs),
            "errors": dict(self.errors),
            "duration_ms": self.duration_ms,
        }


# ============================================================================
# AgentDispatcher
# ============================================================================


class AgentDispatcher:
    """Executes DAG waves with global concurrency cap, per-agent FIFO serialization,
    per-subtask timeout, masked immutable TurnLogs, and real-time WebSocket streaming.
    """

    def __init__(
        self,
        max_parallel: int = 3,
        worker_fn: Optional[Callable[..., Any]] = None,
        timeout_seconds: float = 300.0,
        session_factory: Optional[sessionmaker[Session]] = None,
        ws_manager: Optional["TaskWebSocketManager"] = None,
        llm_router: Optional[LlmRouter] = None,
        extra_secrets: Optional[Iterable[str]] = None,
        yt_client: Optional[Any] = None,
        browser: Optional[Any] = None,
        retriever: Optional[Any] = None,
        brand_profile: Optional[Any] = None,
        workspace_dir: Optional[Path] = None,
    ) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be >= 1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")

        self.max_parallel = max_parallel
        self.worker_fn = worker_fn
        self.timeout_seconds = timeout_seconds
        self.session_factory = session_factory
        self.ws_manager = ws_manager
        self.llm_router = llm_router or LlmRouter()
        self.yt_client = yt_client
        self.browser = browser
        self.retriever = retriever
        self.brand_profile = brand_profile
        self.workspace_dir = workspace_dir
        if extra_secrets is not None:
            self.extra_secrets = [str(s) for s in extra_secrets if s]
        else:
            default_tok = get_settings().local_auth_token
            self.extra_secrets = [default_tok] if default_tok else []

        self._semaphore = asyncio.Semaphore(max_parallel)
        self._agent_locks: dict[str, asyncio.Lock] = {}
        self._canonical_agent_map: dict[str, str] = {}
        self._db_lock = asyncio.Lock()

    @staticmethod
    def _normalize_agent_key(agent_id: str) -> str:
        """Normalize agent handle/id so 'ContentWriter' and 'agent-content-writer' map identically."""
        cleaned = agent_id.strip().lower()
        if cleaned.startswith("agent-"):
            cleaned = cleaned[len("agent-"):]
        return re.sub(r"[-_]", "", cleaned)

    def _populate_agent_map_sync(self, session: Session) -> None:
        """Cache DB Agent id/name -> canonical lowercase Agent.id."""
        for ag_id, ag_name in session.query(Agent.id, Agent.name).all():
            canonical = str(ag_id).strip().lower()
            self._canonical_agent_map[canonical] = canonical
            if ag_name:
                self._canonical_agent_map[str(ag_name).strip().lower()] = canonical
                self._canonical_agent_map[self._normalize_agent_key(str(ag_name))] = canonical
            self._canonical_agent_map[self._normalize_agent_key(str(ag_id))] = canonical

    def _get_agent_lock(self, agent_id: Optional[str]) -> Optional[asyncio.Lock]:
        """Return FIFO asyncio.Lock for a given agent_id, or None for unbound items."""
        if not agent_id:
            return None
        raw = str(agent_id).strip().lower()
        if not raw:
            return None
        key = self._canonical_agent_map.get(raw)
        if key is None:
            norm = self._normalize_agent_key(raw)
            key = self._canonical_agent_map.get(norm, norm or raw)
        if key not in self._agent_locks:
            self._agent_locks[key] = asyncio.Lock()
        return self._agent_locks[key]

    @staticmethod
    def _extract_agent_id(item: Any) -> Optional[str]:
        if isinstance(item, dict):
            val = item.get("agent_id")
            return str(val) if val else None
        val = getattr(item, "agent_id", None)
        return str(val) if val else None

    async def _invoke_callable(
        self,
        fn: Callable[..., Any],
        item: Any,
        context: Optional[dict[str, Any]],
    ) -> Any:
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        accepts_varargs = any(
            p.kind == inspect.Parameter.VAR_POSITIONAL for p in params
        )
        positional_count = sum(
            1
            for p in params
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        )
        if not accepts_varargs and positional_count <= 1:
            result = fn(item)
        else:
            result = fn(item, context or {})

        if inspect.isawaitable(result):
            return await result
        return result

    async def _execute_with_guards(
        self,
        agent_id: Optional[str],
        coro_factory: Callable[[], Any],
    ) -> Any:
        """Acquire per-agent FIFO lock first (so queued tasks do not starve global slots),
        then acquire the global concurrency semaphore and enforce timeout_seconds.
        """
        agent_lock = self._get_agent_lock(agent_id)
        if agent_lock is not None:
            async with agent_lock:
                async with self._semaphore:
                    return await asyncio.wait_for(
                        coro_factory(),
                        timeout=self.timeout_seconds,
                    )
        async with self._semaphore:
            return await asyncio.wait_for(
                coro_factory(),
                timeout=self.timeout_seconds,
            )

    async def run_batch(
        self,
        items: list[Any],
        context: Optional[dict[str, Any]] = None,
    ) -> list[Any]:
        """Run a flat batch of subtasks/items respecting max_parallel and per-agent FIFO."""
        if not items:
            return []

        async def _run_one(item: Any) -> Any:
            agent_id = self._extract_agent_id(item)

            async def _work() -> Any:
                if self.worker_fn is not None:
                    return await self._invoke_callable(self.worker_fn, item, context)
                node = (
                    item
                    if isinstance(item, SubTaskNode)
                    else SubTaskNode(
                        id=str(getattr(item, "id", item)),
                        agent_id=agent_id or "agent-commander",
                        instruction=str(getattr(item, "instruction", item)),
                    )
                )
                return await self._run_default_worker(node, context or {})

            return await self._execute_with_guards(agent_id, _work)

        return list(await asyncio.gather(*(_run_one(item) for item in items)))

    def _mask(self, data: Any) -> Any:
        return mask_secrets(data, extra_secrets=self.extra_secrets)

    async def _broadcast(self, task_id: str, event: dict[str, Any]) -> None:
        if self.ws_manager is None:
            return
        await self.ws_manager.broadcast(task_id, self._mask(event))

    def _resolve_agent_record_sync(self, db: Optional[Session], agent_id: str) -> Agent:
        """Load Agent ORM record from DB or synthesize an in-memory fallback."""
        if db is not None and agent_id:
            agent = db.get(Agent, agent_id)
            if agent is None:
                agent = (
                    db.query(Agent)
                    .filter(func.lower(Agent.name) == agent_id.lower())
                    .first()
                )
            if agent is not None:
                db.expunge(agent)
                return agent

        return Agent(
            id=agent_id or "agent-commander",
            name=agent_id or "Commander",
            display_name=agent_id or "Commander",
            role="Worker Agent",
            default_model="gemini-2.5-flash",
            temperature=0.7,
            max_tokens=4096,
        )

    def _create_specialized_or_base_worker(
        self,
        agent_record: Agent,
        task_type: Optional[str] = None,
    ) -> BaseWorkerAgent:
        if task_type == "general":
            return BaseWorkerAgent(
                agent=agent_record,
                llm_router=self.llm_router,
                session_factory=self.session_factory,
            )

        ag_name = (agent_record.name or "").strip().lower()
        ag_id = (agent_record.id or "").strip().lower()
        key = self._normalize_agent_key(ag_name or ag_id)

        if key in ("deepresearcher", "deep_researcher"):
            try:
                from app.agents.content import DeepResearcherAgent
                return DeepResearcherAgent(
                    agent=agent_record,
                    yt_client=self.yt_client,
                    browser=self.browser,
                    llm=self.llm_router,
                    session_factory=self.session_factory,
                )
            except Exception:
                pass

        if key in ("contentwriter", "content_writer"):
            try:
                from app.agents.content import ContentWriterAgent
                return ContentWriterAgent(
                    agent=agent_record,
                    llm=self.llm_router,
                    brand_profile=self.brand_profile,
                    session_factory=self.session_factory,
                )
            except Exception:
                pass

        if key in ("imagestudio", "image_studio") and self.browser is not None:
            try:
                from app.agents.content import ImageStudioAgent
                return ImageStudioAgent(
                    agent=agent_record,
                    browser=self.browser,
                    llm=self.llm_router,
                    brand_profile=self.brand_profile,
                    session_factory=self.session_factory,
                )
            except Exception:
                pass

        if key in ("funnelsagent", "funnels", "funnel"):
            try:
                from app.agents.funnels import FunnelsAgent
                return FunnelsAgent(
                    agent=agent_record,
                    llm=self.llm_router,
                    brand_profile=self.brand_profile,
                    session_factory=self.session_factory,
                )
            except Exception:
                pass

        if key in ("growthadvisor", "growth_advisor", "growth"):
            try:
                from app.agents.funnels import GrowthAdvisorAgent
                return GrowthAdvisorAgent(
                    agent=agent_record,
                    llm=self.llm_router,
                    session_factory=self.session_factory,
                )
            except Exception:
                pass

        if key in ("uidesigner", "ui_designer", "landing"):
            try:
                from app.agents.funnels import UIDesignerAgent
                return UIDesignerAgent(
                    agent=agent_record,
                    llm=self.llm_router,
                    brand_profile=self.brand_profile,
                    session_factory=self.session_factory,
                )
            except Exception:
                pass

        if key in ("salesagent", "sales"):
            try:
                from app.agents.engagement import SalesAgent
                return SalesAgent(
                    agent=agent_record,
                    llm=self.llm_router,
                    retriever=self.retriever,
                    brand_profile=self.brand_profile,
                    session_factory=self.session_factory,
                )
            except Exception:
                pass

        if key in ("supportagent", "customersupportagent", "support"):
            try:
                from app.agents.engagement import SupportAgent
                return SupportAgent(
                    agent=agent_record,
                    llm=self.llm_router,
                    retriever=self.retriever,
                    brand_profile=self.brand_profile,
                    session_factory=self.session_factory,
                )
            except Exception:
                pass

        return BaseWorkerAgent(
            agent=agent_record,
            llm_router=self.llm_router,
            session_factory=self.session_factory,
        )

    async def _run_default_worker(
        self,
        node: SubTaskNode,
        context: dict[str, Any],
    ) -> WorkerResult:
        """Instantiate appropriate worker or specialized agent for node.agent_id and execute."""
        if self.session_factory is not None:
            async with self._db_lock:
                with self.session_factory() as s:
                    agent_record = self._resolve_agent_record_sync(s, node.agent_id)
        else:
            agent_record = self._resolve_agent_record_sync(None, node.agent_id)

        task_type = context.get("task_type")
        worker = self._create_specialized_or_base_worker(agent_record, task_type=task_type)
        return await worker.execute(
            subtask=node,
            context=context,
            db_session_factory=self.session_factory,
        )

    @staticmethod
    def _resolve_db_fk_ids(
        session: Session,
        task_id: str,
        logical_agent_id: Optional[str],
    ) -> tuple[bool, Optional[str]]:
        """Check Task existence and resolve valid Agent.id for SQLite FK safety."""
        task_exists = session.get(Task, task_id) is not None
        resolved_agent_id: Optional[str] = None
        if logical_agent_id:
            ag = session.get(Agent, logical_agent_id) or (
                session.query(Agent)
                .filter(func.lower(Agent.name) == logical_agent_id.lower())
                .first()
            )
            if ag is not None:
                resolved_agent_id = ag.id
        return task_exists, resolved_agent_id

    @staticmethod
    def _build_subtask_db_id(task_id: str, node_id: str) -> str:
        raw = f"{task_id}-{node_id}"
        if len(raw) <= 64:
            return raw
        suffix = uuid.uuid5(uuid.NAMESPACE_DNS, raw).hex[:12]
        return f"{raw[:51]}-{suffix}"

    NON_DISPATCHABLE_STATUSES = (
        TaskStatus.RUNNING,
        TaskStatus.WAITING_REVIEW,
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
    )

    async def _prepare_task_and_subtasks(
        self,
        task_id: str,
        plan: ExecutionPlan,
    ) -> dict[str, str]:
        """Validate task state, transition to RUNNING, and ensure SubTask rows exist in SQLite."""
        subtask_db_ids: dict[str, str] = {}
        if self.session_factory is None:
            return subtask_db_ids

        async with self._db_lock:
            with self.session_factory() as s:
                self._populate_agent_map_sync(s)
                task = s.get(Task, task_id)
                if task is None:
                    return subtask_db_ids

                current_status = (
                    TaskStatus(task.status)
                    if isinstance(task.status, str)
                    else task.status
                )
                if current_status in self.NON_DISPATCHABLE_STATUSES:
                    raise TaskDispatchConflictError(
                        f"Task '{task_id}' cannot be dispatched from state '{current_status.value}'"
                    )

                TaskStateMachine.transition(
                    session=s,
                    task_id=task_id,
                    target_state=TaskStatus.RUNNING,
                    actor="commander",
                    reason="dispatch_started",
                )

                for idx, node in enumerate(plan.nodes):
                    # Reuse pre-existing SubTask if caller inserted one with id=node.id for this task
                    existing = (
                        s.query(SubTask)
                        .filter(SubTask.task_id == task_id, SubTask.id == node.id)
                        .first()
                    )
                    if existing is not None:
                        if current_status == TaskStatus.APPROVED and existing.status == "completed":
                            subtask_db_ids[node.id] = existing.id
                            continue
                        existing.status = "pending"
                        existing.result = None
                        subtask_db_ids[node.id] = existing.id
                        continue

                    candidate_id = self._build_subtask_db_id(task_id, node.id)
                    existing_scoped = s.get(SubTask, candidate_id)
                    if existing_scoped is not None:
                        if current_status == TaskStatus.APPROVED and existing_scoped.status == "completed":
                            subtask_db_ids[node.id] = existing_scoped.id
                            continue
                        existing_scoped.status = "pending"
                        existing_scoped.result = None
                        subtask_db_ids[node.id] = existing_scoped.id
                        continue

                    _, resolved_agent_id = self._resolve_db_fk_ids(
                        s, task_id, node.agent_id
                    )
                    st = SubTask(
                        id=candidate_id,
                        task_id=task_id,
                        agent_id=resolved_agent_id,
                        title=node.id[:255],
                        instruction=node.instruction,
                        status="pending",
                        depends_on=list(node.depends_on),
                        order_index=idx,
                    )
                    s.add(st)
                    subtask_db_ids[node.id] = candidate_id
                s.commit()

        return subtask_db_ids

    async def _set_subtask_status(
        self,
        subtask_db_id: Optional[str],
        status_value: str,
        result_payload: Optional[Any] = None,
    ) -> None:
        if self.session_factory is None or not subtask_db_id:
            return
        async with self._db_lock:
            with self.session_factory() as s:
                st = s.get(SubTask, subtask_db_id)
                if st is not None:
                    st.status = status_value
                    if result_payload is not None:
                        st.result = self._mask(
                            result_payload
                            if isinstance(result_payload, dict)
                            else {"value": result_payload}
                        )
                    s.commit()

    async def _append_turn_log(
        self,
        task_id: str,
        subtask_db_id: Optional[str],
        logical_agent_id: Optional[str],
        action: str,
        tool: str,
        input_payload: Any,
        output_payload: Any,
        duration_ms: int,
        tokens: int,
        status_value: str,
        error_message: Optional[str] = None,
    ) -> dict[str, Any]:
        """Append an immutable, secret-masked TurnLog row and return its serialized dict."""
        masked_input = self._mask(input_payload)
        masked_output = self._mask(output_payload)
        masked_error = self._mask(error_message) if error_message else None
        now = datetime.now(timezone.utc)
        turn_id = f"turn-{uuid.uuid4().hex[:12]}"
        turn_number = 1
        resolved_agent_id: Optional[str] = None

        if self.session_factory is not None:
            async with self._db_lock:
                with self.session_factory() as s:
                    task_exists, resolved_agent_id = self._resolve_db_fk_ids(
                        s, task_id, logical_agent_id
                    )
                    if task_exists:
                        existing_count = (
                            s.query(TurnLog).filter_by(task_id=task_id).count()
                        )
                        turn_number = existing_count + 1
                        valid_subtask_id = (
                            subtask_db_id
                            if (subtask_db_id and s.get(SubTask, subtask_db_id))
                            else None
                        )
                        row = TurnLog(
                            id=turn_id,
                            task_id=task_id,
                            subtask_id=valid_subtask_id,
                            agent_id=resolved_agent_id,
                            turn_number=turn_number,
                            action=action,
                            tool=tool,
                            input_payload=masked_input,
                            output_payload=masked_output,
                            duration_ms=duration_ms,
                            tokens=tokens,
                            status=status_value,
                            error_message=masked_error,
                            created_at=now,
                        )
                        s.add(row)
                        s.commit()

        return {
            "id": turn_id,
            "task_id": task_id,
            "subtask_id": subtask_db_id,
            "agent_id": resolved_agent_id or logical_agent_id,
            "turn_number": turn_number,
            "action": action,
            "tool": tool,
            "input_payload": masked_input,
            "output_payload": masked_output,
            "duration_ms": duration_ms,
            "tokens": tokens,
            "status": status_value,
            "error_message": masked_error,
            "created_at": now.isoformat(),
        }

    async def _transition_task_final(
        self,
        task_id: str,
        target_status: TaskStatus,
        reason: str,
    ) -> None:
        if self.session_factory is None:
            return
        async with self._db_lock:
            with self.session_factory() as s:
                task = s.get(Task, task_id)
                if task is not None and task.status != target_status:
                    TaskStateMachine.transition(
                        session=s,
                        task_id=task_id,
                        target_state=target_status,
                        actor="commander",
                        reason=reason,
                    )

    async def dispatch(
        self,
        task_id: str,
        plan: ExecutionPlan,
        context: Optional[dict[str, Any]] = None,
    ) -> DispatchResult:
        """Execute an ExecutionPlan wave-by-wave with concurrency, timeout, and streaming."""
        t_start = time.perf_counter()
        base_context = dict(context or {})
        base_context["task_id"] = task_id
        base_context["task_type"] = plan.task_type
        base_context["db_lock"] = self._db_lock

        subtask_db_ids = await self._prepare_task_and_subtasks(task_id, plan)
        await self._broadcast(
            task_id,
            {
                "event": "task_status",
                "task_id": task_id,
                "status": "running",
                "total_waves": len(plan.waves),
            },
        )

        node_map: dict[str, SubTaskNode] = {n.id: n for n in plan.nodes}
        completed_nodes: list[str] = []
        failed_nodes: list[str] = []
        turn_logs: list[dict[str, Any]] = []
        outputs: dict[str, Any] = {}
        errors: dict[str, str] = {}
        accumulated_artifact_ids: list[str] = []

        # Initialize handoff_chain in task metadata with first node agent if absent
        if self.session_factory is not None and plan.nodes and self.worker_fn is None:
            async with self._db_lock:
                with self.session_factory() as s:
                    task_rec = s.get(Task, task_id)
                    if task_rec is not None:
                        meta = dict(task_rec.task_metadata or {})
                        first_ag = self._resolve_agent_record_sync(s, plan.nodes[0].agent_id)
                        if not meta.get("handoff_chain"):
                            meta["handoff_chain"] = [first_ag.name]
                            task_rec.task_metadata = meta
                            s.commit()

        for wave_idx, wave_node_ids in enumerate(plan.waves):
            wave_nodes = [node_map[nid] for nid in wave_node_ids if nid in node_map]

            # Check if all nodes in this wave are already completed in DB (HIL resume case)
            wave_already_completed = False
            if self.session_factory is not None and wave_node_ids:
                async with self._db_lock:
                    with self.session_factory() as s:
                        done_count = 0
                        for nid in wave_node_ids:
                            st_db_id = subtask_db_ids.get(nid)
                            st_row = s.get(SubTask, st_db_id) if st_db_id else None
                            if st_row is not None and st_row.status == "completed":
                                done_count += 1
                                if st_row.result is not None:
                                    outputs[nid] = st_row.result
                                if nid not in completed_nodes:
                                    completed_nodes.append(nid)
                        if done_count == len(wave_node_ids):
                            wave_already_completed = True

            if wave_already_completed:
                continue

            async def _execute_node(node: SubTaskNode) -> tuple[str, bool, Any, dict[str, Any]]:
                st_db_id = subtask_db_ids.get(node.id)
                node_t0 = time.perf_counter()

                async def _guarded_work() -> Any:
                    await self._set_subtask_status(st_db_id, "running")
                    await self._broadcast(
                        task_id,
                        {
                            "event": "turn_started",
                            "task_id": task_id,
                            "subtask_id": node.id,
                            "agent_id": node.agent_id,
                            "wave_index": wave_idx,
                            "instruction": node.instruction,
                        },
                    )
                    dep_outputs = {
                        dep: outputs[dep] for dep in node.depends_on if dep in outputs
                    }

                    # Inter-agent handoff detection and execution
                    if node.depends_on and self.session_factory is not None and self.worker_fn is None:
                        dep_agents = [
                            node_map[dep].agent_id for dep in node.depends_on if dep in node_map
                        ]
                        if dep_agents:
                            src_agent_id = dep_agents[0]
                            tgt_agent_id = node.agent_id
                            async with self._db_lock:
                                with self.session_factory() as s:
                                    src_rec = self._resolve_agent_record_sync(s, src_agent_id)
                                    tgt_rec = self._resolve_agent_record_sync(s, tgt_agent_id)
                                    if src_rec.id.lower() != tgt_rec.id.lower():
                                        try:
                                            from app.orchestrator.handoff import HandoffManager
                                            hm = HandoffManager(
                                                max_depth=5, extra_secrets=self.extra_secrets
                                            )
                                            hm.execute_handoff(
                                                db=s,
                                                task_id=task_id,
                                                from_agent=src_rec.name,
                                                to_agent=tgt_rec.name,
                                                payload={
                                                    "instruction": node.instruction,
                                                    "summary": f"Bàn giao từ {src_rec.name} sang {tgt_rec.name}",
                                                    "dependency_outputs": dep_outputs,
                                                },
                                                artifact_ids=list(accumulated_artifact_ids),
                                            )
                                        except Exception:
                                            pass

                    node_ctx = {
                        **base_context,
                        "wave_index": wave_idx,
                        "dependency_outputs": dep_outputs,
                        "output_dir": (self.workspace_dir or get_settings().workspace_dir) / "artifacts" / task_id,
                    }
                    if self.worker_fn is not None:
                        return await self._invoke_callable(self.worker_fn, node, node_ctx)
                    return await self._run_default_worker(node, node_ctx)

                try:
                    raw_res = await self._execute_with_guards(node.agent_id, _guarded_work)
                    duration_ms = max(1, int((time.perf_counter() - node_t0) * 1000))

                    if isinstance(raw_res, WorkerResult):
                        if raw_res.status == "failed":
                            err_msg = str(
                                self._mask(raw_res.error or "Worker returned failed status")
                            )
                            await self._set_subtask_status(
                                st_db_id, "failed", {"error": err_msg}
                            )
                            log_entry = await self._append_turn_log(
                                task_id=task_id,
                                subtask_db_id=st_db_id,
                                logical_agent_id=node.agent_id,
                                action="execute_subtask",
                                tool="worker_agent",
                                input_payload={
                                    "subtask_id": node.id,
                                    "instruction": node.instruction,
                                },
                                output_payload=None,
                                duration_ms=raw_res.duration_ms or duration_ms,
                                tokens=raw_res.tokens,
                                status_value="failed",
                                error_message=err_msg,
                            )
                            await self._broadcast(
                                task_id,
                                {
                                    "event": "turn_failed",
                                    "task_id": task_id,
                                    "subtask_id": node.id,
                                    "agent_id": node.agent_id,
                                    "status": "failed",
                                    "error": err_msg,
                                    "duration_ms": log_entry["duration_ms"],
                                },
                            )
                            return node.id, False, err_msg, log_entry

                        out_payload = (
                            raw_res.output
                            if raw_res.output is not None
                            else {"content": raw_res.content}
                        )
                        tokens = raw_res.tokens
                        effective_ms = raw_res.duration_ms or duration_ms
                        tool_name = (
                            f"llm:{raw_res.model_used}"
                            if raw_res.model_used
                            else "worker_agent"
                        )
                    else:
                        out_payload = (
                            raw_res
                            if isinstance(raw_res, dict)
                            else {"content": str(raw_res)}
                        )
                        tokens = (
                            int(raw_res.get("tokens", 0))
                            if isinstance(raw_res, dict)
                            else 0
                        )
                        effective_ms = duration_ms
                        tool_name = "worker_fn" if self.worker_fn else "worker_agent"

                    # Persist any generated artifacts to disk and database
                    if hasattr(raw_res, "artifacts") and raw_res.artifacts and self.session_factory is not None:
                        async with self._db_lock:
                            with self.session_factory() as s:
                                ws_dir = self.workspace_dir or get_settings().workspace_dir
                                art_dir = ws_dir / "artifacts" / task_id
                                art_dir.mkdir(parents=True, exist_ok=True)
                                for art_out in raw_res.artifacts:
                                    fname = art_out.filename
                                    content = art_out.content
                                    art_type = art_out.artifact_type or "html"
                                    target_file = art_dir / fname

                                    if art_type == "png" and isinstance(content, str) and Path(content).exists():
                                        src_png = Path(content)
                                        if src_png.resolve() != target_file.resolve():
                                            import shutil
                                            shutil.copyfile(src_png, target_file)
                                    elif isinstance(content, (str, bytes)):
                                        if isinstance(content, bytes):
                                            target_file.write_bytes(content)
                                        else:
                                            target_file.write_text(content, encoding="utf-8")

                                    art_id = f"art-{uuid.uuid4().hex[:12]}"
                                    mime = (
                                        "image/png"
                                        if art_type == "png"
                                        else (
                                            "text/markdown"
                                            if art_type == "markdown"
                                            else "text/html"
                                        )
                                    )
                                    row = Artifact(
                                        id=art_id,
                                        task_id=task_id,
                                        subtask_id=st_db_id,
                                        name=fname,
                                        file_path=str(target_file),
                                        file_type=art_type,
                                        mime_type=mime,
                                        created_at=datetime.now(timezone.utc),
                                    )
                                    s.add(row)
                                    accumulated_artifact_ids.append(art_id)
                                s.commit()

                    masked_out = self._mask(out_payload)
                    await self._set_subtask_status(st_db_id, "completed", masked_out)
                    log_entry = await self._append_turn_log(
                        task_id=task_id,
                        subtask_db_id=st_db_id,
                        logical_agent_id=node.agent_id,
                        action="execute_subtask",
                        tool=tool_name,
                        input_payload={
                            "subtask_id": node.id,
                            "instruction": node.instruction,
                        },
                        output_payload=masked_out,
                        duration_ms=effective_ms,
                        tokens=tokens,
                        status_value="completed",
                    )
                    await self._broadcast(
                        task_id,
                        {
                            "event": "turn_completed",
                            "task_id": task_id,
                            "subtask_id": node.id,
                            "agent_id": node.agent_id,
                            "turn_number": log_entry["turn_number"],
                            "duration_ms": effective_ms,
                            "tokens": tokens,
                            "status": "completed",
                            "output": masked_out,
                        },
                    )
                    return node.id, True, masked_out, log_entry

                except asyncio.TimeoutError:
                    duration_ms = max(1, int((time.perf_counter() - node_t0) * 1000))
                    err_msg = f"SubTask '{node.id}' timed out after {self.timeout_seconds}s"
                    await self._set_subtask_status(
                        st_db_id, "failed", {"error": err_msg}
                    )
                    log_entry = await self._append_turn_log(
                        task_id=task_id,
                        subtask_db_id=st_db_id,
                        logical_agent_id=node.agent_id,
                        action="execute_subtask",
                        tool="worker_fn" if self.worker_fn else "worker_agent",
                        input_payload={
                            "subtask_id": node.id,
                            "instruction": node.instruction,
                        },
                        output_payload=None,
                        duration_ms=duration_ms,
                        tokens=0,
                        status_value="timeout",
                        error_message=err_msg,
                    )
                    await self._broadcast(
                        task_id,
                        {
                            "event": "turn_failed",
                            "task_id": task_id,
                            "subtask_id": node.id,
                            "agent_id": node.agent_id,
                            "status": "timeout",
                            "error": err_msg,
                            "duration_ms": duration_ms,
                        },
                    )
                    return node.id, False, err_msg, log_entry

                except Exception as exc:
                    duration_ms = max(1, int((time.perf_counter() - node_t0) * 1000))
                    err_msg = str(self._mask(str(exc)))
                    await self._set_subtask_status(
                        st_db_id, "failed", {"error": err_msg}
                    )
                    log_entry = await self._append_turn_log(
                        task_id=task_id,
                        subtask_db_id=st_db_id,
                        logical_agent_id=node.agent_id,
                        action="execute_subtask",
                        tool="worker_fn" if self.worker_fn else "worker_agent",
                        input_payload={
                            "subtask_id": node.id,
                            "instruction": node.instruction,
                        },
                        output_payload=None,
                        duration_ms=duration_ms,
                        tokens=0,
                        status_value="failed",
                        error_message=err_msg,
                    )
                    await self._broadcast(
                        task_id,
                        {
                            "event": "turn_failed",
                            "task_id": task_id,
                            "subtask_id": node.id,
                            "agent_id": node.agent_id,
                            "status": "failed",
                            "error": err_msg,
                            "duration_ms": duration_ms,
                        },
                    )
                    return node.id, False, err_msg, log_entry

            wave_outcomes = await asyncio.gather(
                *(_execute_node(node) for node in wave_nodes)
            )
            wave_failed = False
            for nid, ok, payload, log_entry in wave_outcomes:
                turn_logs.append(log_entry)
                if ok:
                    completed_nodes.append(nid)
                    outputs[nid] = payload
                else:
                    failed_nodes.append(nid)
                    errors[nid] = str(payload)
                    wave_failed = True

            if wave_failed:
                await self._transition_task_final(
                    task_id, TaskStatus.FAILED, reason="subtask_failed"
                )
                await self._broadcast(
                    task_id,
                    {
                        "event": "task_status",
                        "task_id": task_id,
                        "status": "failed",
                        "failed_nodes": failed_nodes,
                        "errors": errors,
                    },
                )
                total_ms = max(1, int((time.perf_counter() - t_start) * 1000))
                return DispatchResult(
                    task_id=task_id,
                    status="failed",
                    completed_nodes=completed_nodes,
                    failed_nodes=failed_nodes,
                    turn_logs=turn_logs,
                    outputs=outputs,
                    errors=errors,
                    duration_ms=total_ms,
                )

            # Check HIL review gate after wave completion
            review_nodes = [n.id for n in wave_nodes if n.requires_review]
            if review_nodes:
                if self.session_factory is not None:
                    async with self._db_lock:
                        with self.session_factory() as s:
                            task = s.get(Task, task_id)
                            now_utc = datetime.now(timezone.utc)
                            existing_gate = (
                                s.query(ReviewGate)
                                .filter(
                                    ReviewGate.task_id == task_id,
                                    ReviewGate.status == "pending",
                                )
                                .first()
                            )
                            if existing_gate is None:
                                rev_id = f"rev-{uuid.uuid4().hex[:12]}"
                                rev_row = ReviewGate(
                                    id=rev_id,
                                    task_id=task_id,
                                    gate_type="hil",
                                    status="pending",
                                    expires_at=now_utc + timedelta(hours=24),
                                    created_at=now_utc,
                                )
                                s.add(rev_row)
                                if task is not None:
                                    meta = dict(task.task_metadata or {})
                                    reviews_meta = dict(meta.get("reviews") or {})
                                    reviews_meta[rev_id] = {
                                        "summary": f"Review required for step(s): {', '.join(review_nodes)}",
                                        "payload": {
                                            "pending_nodes": review_nodes,
                                            "wave_index": wave_idx,
                                        },
                                    }
                                    meta["reviews"] = reviews_meta
                                    task.task_metadata = meta
                                s.commit()

                await self._transition_task_final(
                    task_id, TaskStatus.WAITING_REVIEW, reason="hil_review_gate"
                )
                await self._broadcast(
                    task_id,
                    {
                        "event": "task_status",
                        "task_id": task_id,
                        "status": "waiting_review",
                        "pending_review_nodes": review_nodes,
                    },
                )
                total_ms = max(1, int((time.perf_counter() - t_start) * 1000))
                return DispatchResult(
                    task_id=task_id,
                    status="waiting_review",
                    completed_nodes=completed_nodes,
                    failed_nodes=failed_nodes,
                    turn_logs=turn_logs,
                    outputs=outputs,
                    errors=errors,
                    duration_ms=total_ms,
                )

        await self._transition_task_final(
            task_id, TaskStatus.COMPLETED, reason="all_waves_completed"
        )
        await self._broadcast(
            task_id,
            {
                "event": "task_status",
                "task_id": task_id,
                "status": "completed",
                "completed_nodes": completed_nodes,
            },
        )
        total_ms = max(1, int((time.perf_counter() - t_start) * 1000))
        return DispatchResult(
            task_id=task_id,
            status="completed",
            completed_nodes=completed_nodes,
            failed_nodes=failed_nodes,
            turn_logs=turn_logs,
            outputs=outputs,
            errors=errors,
            duration_ms=total_ms,
        )
