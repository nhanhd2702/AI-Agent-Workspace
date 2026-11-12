"""Agent Dispatcher, Secret Masking, Concurrency Guard, and Turn Logging (Task 2.3 / F01.3 / F03.3)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import inspect
import re
import time
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from app.agents.base import BaseWorkerAgent, WorkerResult
from app.db.models import Agent, SubTask, Task, TaskStatus, TurnLog
from app.db.state_machine import TaskStateMachine
from app.llm.router import LlmRouter
from app.orchestrator.planner import ExecutionPlan, SubTaskNode

if TYPE_CHECKING:
    from app.api.ws import TaskWebSocketManager


# ============================================================================
# Secret Masking Utility
# ============================================================================

_SECRET_STRING_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # OpenAI / Anthropic style keys (sk-..., sk-proj-..., sk-ant-...)
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "sk-***REDACTED***"),
    # Google / Gemini API keys (AIza...)
    (re.compile(r"\bAIza[0-9A-Za-z_-]{10,}\b"), "AIza***REDACTED***"),
    # Bearer tokens
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer ***REDACTED***"),
    # Slack tokens (xoxb-, xoxp-, xoxa-, etc.)
    (re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{6,}\b"), "xox-***REDACTED***"),
    # GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_)
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{10,}\b"), "gh_***REDACTED***"),
    # Inline key=value or key: value assignments
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|api_?key|secret|local_auth_token|auth_token|access_token|refresh_token|client_secret|private_key)\b(\s*[:=]\s*)(['\"]?)([^\s'\",;}{]+)\3"
        ),
        r"\1\2\3***REDACTED***\3",
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
    """Recursively redact API keys, tokens, and credentials from strings, dicts, and lists."""
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
        if isinstance(node, dict):
            cleaned: dict[Any, Any] = {}
            for k, v in node.items():
                key_str = str(k)
                if _SENSITIVE_DICT_KEY_RE.match(key_str) and isinstance(v, str) and v:
                    cleaned[k] = "***REDACTED***"
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

        self._semaphore = asyncio.Semaphore(max_parallel)
        self._agent_locks: dict[str, asyncio.Lock] = {}
        self._db_lock = asyncio.Lock()

    def _get_agent_lock(self, agent_id: Optional[str]) -> Optional[asyncio.Lock]:
        """Return FIFO asyncio.Lock for a given agent_id, or None for unbound items."""
        if not agent_id:
            return None
        key = str(agent_id).strip().lower()
        if not key:
            return None
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

    async def _broadcast(self, task_id: str, event: dict[str, Any]) -> None:
        if self.ws_manager is None:
            return
        await self.ws_manager.broadcast(task_id, mask_secrets(event))

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

    async def _run_default_worker(
        self,
        node: SubTaskNode,
        context: dict[str, Any],
    ) -> WorkerResult:
        """Instantiate BaseWorkerAgent for node.agent_id and execute via LlmRouter."""
        if self.session_factory is not None:
            async with self._db_lock:
                with self.session_factory() as s:
                    agent_record = self._resolve_agent_record_sync(s, node.agent_id)
        else:
            agent_record = self._resolve_agent_record_sync(None, node.agent_id)

        worker = BaseWorkerAgent(
            agent=agent_record,
            llm_router=self.llm_router,
            session_factory=self.session_factory,
        )
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

    async def _prepare_task_and_subtasks(
        self,
        task_id: str,
        plan: ExecutionPlan,
    ) -> dict[str, str]:
        """Transition Task to RUNNING and ensure SubTask rows exist in SQLite."""
        subtask_db_ids: dict[str, str] = {}
        if self.session_factory is None:
            return subtask_db_ids

        async with self._db_lock:
            with self.session_factory() as s:
                task = s.get(Task, task_id)
                if task is None:
                    return subtask_db_ids

                if task.status in (
                    TaskStatus.PENDING,
                    TaskStatus.PAUSED,
                    TaskStatus.REJECTED,
                ):
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
                        subtask_db_ids[node.id] = existing.id
                        continue

                    candidate_id = self._build_subtask_db_id(task_id, node.id)
                    existing_scoped = s.get(SubTask, candidate_id)
                    if existing_scoped is not None:
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
                        st.result = mask_secrets(
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
        masked_input = mask_secrets(input_payload)
        masked_output = mask_secrets(output_payload)
        masked_error = mask_secrets(error_message) if error_message else None
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

        for wave_idx, wave_node_ids in enumerate(plan.waves):
            wave_nodes = [node_map[nid] for nid in wave_node_ids if nid in node_map]

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
                    node_ctx = {
                        **base_context,
                        "wave_index": wave_idx,
                        "dependency_outputs": dep_outputs,
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
                                mask_secrets(raw_res.error or "Worker returned failed status")
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

                    masked_out = mask_secrets(out_payload)
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
                    err_msg = str(mask_secrets(str(exc)))
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
