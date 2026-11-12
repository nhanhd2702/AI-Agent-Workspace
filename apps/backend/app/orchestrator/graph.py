"""LangGraph SqliteSaver Orchestrator & Crash Recovery (F01.4 / F03).

Provides:
- `recover_interrupted_tasks`: Moves orphaned RUNNING tasks to PAUSED on startup
  with immutable TaskAuditLog records.
- `OrchestratorGraph`: Persistent StateGraph backed by LangGraph `SqliteSaver`
  (`checkpoints.db`), supporting wave-by-wave DAG execution, `interrupt()` at
  Human-in-the-Loop (HIL) review gates, and `Command(resume=...)` across restarts.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Callable, Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, StateSnapshot, interrupt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import SubTask, Task, TaskStatus
from app.db.state_machine import TaskStateMachine
from app.orchestrator.planner import ExecutionPlan


NodeExecutor = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


class OrchestratorState(TypedDict):
    """Serializable LangGraph state persisted in SqliteSaver checkpoints."""

    task_id: str
    task_type: str
    mode: str
    nodes: list[dict[str, Any]]
    waves: list[list[str]]
    current_wave_index: int
    completed_nodes: list[str]
    node_results: dict[str, Any]
    review_decisions: dict[str, Any]
    pending_review_nodes: list[str]
    status: str
    context: dict[str, Any]


def recover_interrupted_tasks(session: Session) -> int:
    """Transition any orphaned RUNNING tasks to PAUSED on server startup.

    Uses TaskStateMachine.transition so every recovery writes an immutable
    TaskAuditLog entry (`actor="system"`, `reason="crash_recovery"`).
    Also pauses any in-flight SubTask records belonging to recovered tasks.
    """
    running_tasks = (
        session.query(Task)
        .filter(Task.status == TaskStatus.RUNNING)
        .order_by(Task.created_at.asc())
        .all()
    )
    recovered_count = 0

    for task in running_tasks:
        try:
            in_flight_subtasks = (
                session.query(SubTask)
                .filter(
                    SubTask.task_id == task.id,
                    SubTask.status.in_(["running", "in_progress", "waiting_review"]),
                )
                .all()
            )
            for subtask in in_flight_subtasks:
                subtask.status = "paused"

            TaskStateMachine.transition(
                session=session,
                task_id=task.id,
                target_state=TaskStatus.PAUSED,
                actor="system",
                reason="crash_recovery",
            )
            recovered_count += 1
        except Exception:
            session.rollback()
            raise

    return recovered_count


def _default_node_executor(node: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fallback node executor used when no custom runner is provided."""
    return {
        "node_id": node["id"],
        "agent_id": node["agent_id"],
        "status": "completed",
        "output": f"Executed '{node['id']}' by {node['agent_id']}",
    }


_APPROVE_STRINGS = frozenset({"approve", "approved", "yes", "true", "ok", "1"})
_REJECT_STRINGS = frozenset({"reject", "rejected", "no", "false", "deny", "denied", "0"})


def _parse_bool_or_decision_str(value: Any) -> Optional[bool]:
    """Parse strict boolean or known approve/reject string; return None if unrecognized."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _APPROVE_STRINGS:
            return True
        if normalized in _REJECT_STRINGS:
            return False
    return None


def _parse_review_decision(decision: Any) -> tuple[bool, dict[str, Any]]:
    """Normalize HIL resume payload into (approved, normalized_record), failing closed."""
    if isinstance(decision, bool):
        return decision, {"approved": decision}
    if isinstance(decision, str):
        approved = decision.strip().lower() in _APPROVE_STRINGS
        return approved, {"approved": approved, "decision": decision}
    if isinstance(decision, dict):
        if "approved" in decision:
            parsed = _parse_bool_or_decision_str(decision["approved"])
            approved = bool(parsed) if parsed is not None else False
        else:
            raw_decision = decision.get("decision")
            if isinstance(raw_decision, str):
                approved = raw_decision.strip().lower() in _APPROVE_STRINGS
            elif isinstance(raw_decision, bool):
                approved = raw_decision
            else:
                approved = False
        record = dict(decision)
        record["approved"] = approved
        return approved, record
    return False, {"approved": False, "value": decision}


class OrchestratorGraph:
    """LangGraph StateGraph orchestrator backed by SQLite checkpoint persistence."""

    def __init__(
        self,
        checkpoint_db_path: Optional[Path | str] = None,
        node_executor: Optional[NodeExecutor] = None,
    ) -> None:
        if checkpoint_db_path is None:
            resolved_path = (get_settings().workspace_dir / "checkpoints.db").resolve()
        elif str(checkpoint_db_path) == ":memory:":
            resolved_path = Path(":memory:")
        else:
            resolved_path = Path(checkpoint_db_path).resolve()
            resolved_path.parent.mkdir(parents=True, exist_ok=True)

        self.checkpoint_db_path = resolved_path
        self._node_executor: NodeExecutor = node_executor or _default_node_executor
        self._closed = False

        conn_str = ":memory:" if str(resolved_path) == ":memory:" else str(resolved_path)
        self._conn = sqlite3.connect(conn_str, check_same_thread=False)
        self._checkpointer = SqliteSaver(self._conn)
        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(OrchestratorState)
        builder.add_node("execute_wave", self._execute_wave)
        builder.add_node("review_gate", self._review_gate)
        builder.add_node("advance_wave", self._advance_wave)
        builder.add_node("finalize", self._finalize)

        builder.add_edge(START, "execute_wave")
        builder.add_conditional_edges(
            "execute_wave",
            self._route_after_wave,
            {
                "review_gate": "review_gate",
                "advance_wave": "advance_wave",
                "finalize": "finalize",
            },
        )
        builder.add_conditional_edges(
            "review_gate",
            self._route_after_review,
            {
                "advance_wave": "advance_wave",
                "finalize": "finalize",
            },
        )
        builder.add_edge("advance_wave", "execute_wave")
        builder.add_edge("finalize", END)

        return builder.compile(checkpointer=self._checkpointer)

    def _execute_wave(self, state: OrchestratorState) -> dict[str, Any]:
        waves = state["waves"]
        idx = state["current_wave_index"]
        if idx >= len(waves):
            return {"pending_review_nodes": []}

        node_by_id = {n["id"]: n for n in state["nodes"]}
        completed = list(state.get("completed_nodes", []))
        completed_set = set(completed)
        results = dict(state.get("node_results", {}))
        pending_review: list[str] = []

        for node_id in waves[idx]:
            node = node_by_id[node_id]
            if node_id not in completed_set:
                results[node_id] = self._node_executor(node, dict(state))
                completed.append(node_id)
                completed_set.add(node_id)
            if node.get("requires_review", False):
                pending_review.append(node_id)

        return {
            "completed_nodes": completed,
            "node_results": results,
            "pending_review_nodes": pending_review,
        }

    @staticmethod
    def _route_after_wave(state: OrchestratorState) -> str:
        if state.get("pending_review_nodes"):
            return "review_gate"
        if state["current_wave_index"] + 1 < len(state["waves"]):
            return "advance_wave"
        return "finalize"

    @staticmethod
    def _review_gate(state: OrchestratorState) -> dict[str, Any]:
        pending_ids = list(state.get("pending_review_nodes", []))
        wave_idx = state["current_wave_index"]
        review_payload = {
            "task_id": state["task_id"],
            "wave_index": wave_idx,
            "pending_review_nodes": pending_ids,
            "node_results": {
                nid: state.get("node_results", {}).get(nid) for nid in pending_ids
            },
        }
        raw_decision = interrupt(review_payload)
        approved, decision_record = _parse_review_decision(raw_decision)

        decisions = dict(state.get("review_decisions", {}))
        decisions[str(wave_idx)] = decision_record

        return {
            "review_decisions": decisions,
            "pending_review_nodes": [],
            "status": "running" if approved else "rejected",
        }

    @staticmethod
    def _route_after_review(state: OrchestratorState) -> str:
        if state.get("status") == "rejected":
            return "finalize"
        if state["current_wave_index"] + 1 < len(state["waves"]):
            return "advance_wave"
        return "finalize"

    @staticmethod
    def _advance_wave(state: OrchestratorState) -> dict[str, Any]:
        return {"current_wave_index": state["current_wave_index"] + 1}

    @staticmethod
    def _finalize(state: OrchestratorState) -> dict[str, Any]:
        if state.get("status") == "rejected":
            return {"status": "rejected"}
        return {"status": "completed"}

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("OrchestratorGraph connection is closed")

    def run(
        self,
        plan: ExecutionPlan,
        thread_id: Optional[str] = None,
        initial_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute an ExecutionPlan from wave 0 under the given thread_id."""
        self._ensure_open()
        tid = thread_id or plan.task_id
        initial_state: OrchestratorState = {
            "task_id": plan.task_id,
            "task_type": plan.task_type,
            "mode": plan.mode,
            "nodes": [n.to_dict() for n in plan.nodes],
            "waves": [list(w) for w in plan.waves],
            "current_wave_index": 0,
            "completed_nodes": [],
            "node_results": {},
            "review_decisions": {},
            "pending_review_nodes": [],
            "status": "running",
            "context": dict(initial_context or {}),
        }
        return self._graph.invoke(
            initial_state,
            config={"configurable": {"thread_id": tid}},
        )

    def resume(self, thread_id: str, decision: Any = True) -> dict[str, Any]:
        """Resume an interrupted graph execution from checkpoints.db."""
        self._ensure_open()
        if not self.is_interrupted(thread_id):
            raise ValueError(f"Thread '{thread_id}' is not currently interrupted")
        return self._graph.invoke(
            Command(resume=decision),
            config={"configurable": {"thread_id": thread_id}},
        )

    def get_state(self, thread_id: str) -> StateSnapshot:
        """Retrieve current LangGraph StateSnapshot for thread_id."""
        self._ensure_open()
        return self._graph.get_state(config={"configurable": {"thread_id": thread_id}})

    def is_interrupted(self, thread_id: str) -> bool:
        """Return True when the thread is currently paused at an HIL interrupt()."""
        self._ensure_open()
        snapshot = self.get_state(thread_id)
        if snapshot is None or not snapshot.tasks:
            return False
        return any(bool(getattr(task, "interrupts", None)) for task in snapshot.tasks)

    def close(self) -> None:
        """Close underlying SQLite checkpoint connection cleanly (Windows-safe)."""
        if not self._closed:
            self._closed = True
            self._conn.close()

    def __enter__(self) -> "OrchestratorGraph":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
