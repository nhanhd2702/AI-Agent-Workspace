"""Agent-to-Agent Handoff Protocol & Shared Memory Phiếu Bước (Task 2.4 / F05.2).

Provides:
- HandoffManager for validated agent transitions with loop & depth guards
- Strict input contract validation for receiving agents
- Structured Phiếu bước shared memory packaging in task.task_metadata
- Immutable TurnLog persistence with secret masking
- Domain exceptions: HandoffError, HandoffLimitError, HandoffLoopError,
  HandoffContractError, HandoffNotFoundError
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import Agent, Artifact, Task, TaskStatus, TurnLog
from app.orchestrator.dispatcher import mask_secrets


# ============================================================================
# Exceptions
# ============================================================================

class HandoffError(ValueError):
    """Base exception for all agent handoff failures."""


class HandoffLimitError(HandoffError):
    """Raised when handoff chain depth exceeds the maximum configured limit (default: 5)."""


class HandoffLoopError(HandoffError):
    """Raised when an immediate self-handoff or repeating ping-pong cycle is detected."""


class HandoffContractError(HandoffError):
    """Raised when handoff payload or artifacts violate target agent's input contract."""


class HandoffNotFoundError(LookupError, HandoffError):
    """Raised when task, agent, or artifact entity cannot be resolved."""


# ============================================================================
# Handoff Record Data Structure
# ============================================================================

@dataclass
class HandoffRecord:
    """Immutable outcome record of a successful agent-to-agent handoff."""

    handoff_id: str
    task_id: str
    step_index: int
    from_agent: str
    to_agent: str
    chain: list[str]
    phieu_buoc: dict[str, Any]
    artifact_ids: list[str] = field(default_factory=list)
    status: str = "transferred"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert record to JSON-serializable dictionary."""
        return {
            "handoff_id": self.handoff_id,
            "task_id": self.task_id,
            "step_index": self.step_index,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "chain": list(self.chain),
            "phieu_buoc": dict(self.phieu_buoc),
            "artifact_ids": list(self.artifact_ids),
            "status": self.status,
            "created_at": self.created_at,
        }


# ============================================================================
# Handoff Manager
# ============================================================================

class HandoffManager:
    """Coordinates agent handoffs with loop guards, depth capping, and contract verification."""

    def __init__(
        self,
        max_depth: int = 5,
        extra_secrets: Optional[Iterable[str]] = None,
    ) -> None:
        self.max_depth = max(1, int(max_depth))
        self.extra_secrets = [str(s) for s in (extra_secrets or ()) if s]

    def validate_chain(self, chain: list[str], next_agent: str) -> list[str]:
        """Validate proposed agent handoff against depth limit, self-handoff, and cycle rules.

        Rules:
        1. Max depth: len(chain) cannot be >= max_depth when appending a new node.
        2. Self-handoff: chain[-1] cannot equal next_agent (case-insensitive).
        3. Directed cycle / ping-pong: directed transition (chain[-1] -> next_agent)
           cannot duplicate any already traversed edge in the chain.

        Returns:
            Updated chain with next_agent appended.
        """
        clean_next = next_agent.strip()
        if not clean_next:
            raise HandoffError("Target agent identifier cannot be empty")

        if not chain:
            return [clean_next]

        # 1. Depth limit guard (chain of max_depth cannot take another node)
        if len(chain) >= self.max_depth:
            raise HandoffLimitError(
                f"Handoff chain depth limit reached: maximum {self.max_depth} agents allowed "
                f"(current length {len(chain)}: {' -> '.join(chain)})"
            )

        last_agent = chain[-1].strip()

        # 2. Immediate self-handoff guard
        if last_agent.lower() == clean_next.lower():
            raise HandoffLoopError(
                f"Self-handoff is not allowed: '{last_agent}' cannot hand off to itself."
            )

        # 3. Directed cycle / ping-pong guard (A -> B -> A -> B or multi-hop cycles)
        traversed_edges: set[tuple[str, str]] = set()
        for i in range(len(chain) - 1):
            src = chain[i].strip().lower()
            dst = chain[i + 1].strip().lower()
            traversed_edges.add((src, dst))

        candidate_edge = (last_agent.lower(), clean_next.lower())
        if candidate_edge in traversed_edges:
            raise HandoffLoopError(
                f"Handoff cycle detected: transition '{last_agent}' -> '{clean_next}' "
                f"was already executed in chain: {' -> '.join(chain)}"
            )

        return list(chain) + [clean_next]

    def validate_input_contract(
        self,
        to_agent_record: Agent,
        payload: dict[str, Any],
        artifact_ids: list[str],
    ) -> None:
        """Validate payload and artifacts against the receiving agent's input contract."""
        config = getattr(to_agent_record, "config", None)
        contract = None
        if isinstance(config, dict):
            contract = config.get("input_contract")
        if contract is None:
            contract = getattr(to_agent_record, "input_contract", None)

        if not contract:
            return

        payload_dict = payload if isinstance(payload, dict) else {}
        clean_artifacts = list(dict.fromkeys(artifact_ids or []))

        def _is_missing_or_blank(val: Any) -> bool:
            if val is None:
                return True
            if isinstance(val, str) and not val.strip():
                return True
            return False

        # List/Tuple/Set contract: list of required key strings
        if isinstance(contract, (list, tuple, set)):
            required_keys = [str(k) for k in contract]
            missing_keys = [
                k for k in required_keys if _is_missing_or_blank(payload_dict.get(k))
            ]
            if missing_keys:
                raise HandoffContractError(
                    f"Agent '{to_agent_record.name}' input contract violation: "
                    f"missing required keys: {', '.join(sorted(missing_keys))}"
                )
            return

        # Dict contract: supports required_keys, required_fields, require_artifacts, min_artifacts
        if isinstance(contract, dict):
            required_keys = (
                contract.get("required_keys")
                or contract.get("required_fields")
                or []
            )
            if isinstance(required_keys, (list, tuple, set)):
                missing_keys = [
                    k for k in required_keys if _is_missing_or_blank(payload_dict.get(k))
                ]
                if missing_keys:
                    raise HandoffContractError(
                        f"Agent '{to_agent_record.name}' input contract violation: "
                        f"missing required keys: {', '.join(sorted(missing_keys))}"
                    )

            if contract.get("require_artifacts") and not clean_artifacts:
                raise HandoffContractError(
                    f"Agent '{to_agent_record.name}' input contract violation: "
                    "at least one artifact is required"
                )

            try:
                min_artifacts = int(contract.get("min_artifacts", 0) or 0)
            except (ValueError, TypeError):
                min_artifacts = 0

            if min_artifacts > 0 and len(clean_artifacts) < min_artifacts:
                raise HandoffContractError(
                    f"Agent '{to_agent_record.name}' input contract violation: "
                    f"expected at least {min_artifacts} artifacts, received {len(clean_artifacts)}"
                )

    def _resolve_agent(self, db: Session, identifier: str) -> Optional[Agent]:
        """Resolve Agent by id or case-insensitive name."""
        clean = identifier.strip()
        # 1. Direct match on id
        agent = db.get(Agent, clean)
        if agent:
            return agent

        # 2. Exact match on name
        agent = db.query(Agent).filter(Agent.name == clean).first()
        if agent:
            return agent

        # 3. Case-insensitive match on name
        agent = (
            db.query(Agent)
            .filter(func.lower(Agent.name) == clean.lower())
            .first()
        )
        if agent:
            return agent

        # 4. Case-insensitive match on id
        return (
            db.query(Agent)
            .filter(func.lower(Agent.id) == clean.lower())
            .first()
        )

    def execute_handoff(
        self,
        db: Session,
        task_id: str,
        from_agent: str,
        to_agent: str,
        payload: dict[str, Any],
        artifact_ids: list[str],
    ) -> HandoffRecord:
        """Execute validated handoff, updating Task metadata, assigned agent, and TurnLog."""
        # 1. Resolve and validate Task existence & lifecycle state
        task = db.get(Task, task_id)
        if not task:
            raise HandoffNotFoundError(f"Task '{task_id}' not found")

        if task.status in (
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
            TaskStatus.FAILED,
        ):
            raise HandoffError(
                f"Cannot execute handoff on terminal task '{task_id}' "
                f"with status '{task.status.value}'"
            )

        # 2. Resolve source and target agents
        from_agent_rec = self._resolve_agent(db, from_agent)
        if not from_agent_rec:
            raise HandoffNotFoundError(f"Source agent '{from_agent}' not found")

        to_agent_rec = self._resolve_agent(db, to_agent)
        if not to_agent_rec:
            raise HandoffNotFoundError(f"Target agent '{to_agent}' not found")

        # 3. Validate artifacts existence and ensure they belong to this task
        clean_artifact_ids = list(dict.fromkeys(artifact_ids or []))
        for art_id in clean_artifact_ids:
            art = db.get(Artifact, art_id)
            if not art:
                raise HandoffNotFoundError(f"Artifact '{art_id}' not found")
            if art.task_id != task_id:
                raise HandoffContractError(
                    f"Artifact '{art_id}' belongs to task '{art.task_id}', not '{task_id}'"
                )

        # 4. Resolve existing chain from task metadata and validate new chain
        meta = dict(task.task_metadata or {})
        existing_chain = list(meta.get("handoff_chain") or [])
        if not existing_chain:
            existing_chain = [from_agent_rec.name]
        elif existing_chain[-1].strip().lower() != from_agent_rec.name.strip().lower():
            # If the last recorded agent doesn't match from_agent, check if from_agent
            # is taking over or raising mismatch
            existing_chain.append(from_agent_rec.name)

        new_chain = self.validate_chain(existing_chain, to_agent_rec.name)

        # 5. Validate input contract for target agent
        self.validate_input_contract(to_agent_rec, payload, clean_artifact_ids)

        # 6. Build structured Phiếu bước
        history = list(meta.get("handoff_history") or [])
        step_index = len(history) + 1
        step_id = f"step-{step_index}-{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        handoff_id = f"handoff-{uuid.uuid4().hex[:12]}"

        raw_summary = (
            payload.get("summary")
            or payload.get("brief")
            or payload.get("instruction")
            or f"Phiếu bước {step_index}: Bàn giao từ {from_agent_rec.name} sang {to_agent_rec.name}"
        )
        deliverables = payload.get("deliverables") or [
            f"artifact:{aid}" for aid in clean_artifact_ids
        ]

        masked_payload = mask_secrets(payload, extra_secrets=self.extra_secrets)
        masked_summary = mask_secrets(str(raw_summary), extra_secrets=self.extra_secrets)

        phieu_buoc = {
            "step_id": step_id,
            "step_index": step_index,
            "task_id": task_id,
            "from_agent": from_agent_rec.name,
            "to_agent": to_agent_rec.name,
            "summary": masked_summary,
            "payload": masked_payload,
            "artifact_ids": clean_artifact_ids,
            "deliverables": deliverables,
            "created_at": now_iso,
        }

        # 7. Update Task metadata & assigned agent
        history.append(phieu_buoc)
        meta["handoff_chain"] = new_chain
        meta["handoff_history"] = history
        meta["last_handoff"] = {
            "handoff_id": handoff_id,
            "step_id": step_id,
            "from_agent": from_agent_rec.name,
            "to_agent": to_agent_rec.name,
            "step_index": step_index,
            "created_at": now_iso,
        }

        task.task_metadata = dict(meta)
        flag_modified(task, "task_metadata")
        task.assigned_agent_id = to_agent_rec.id

        if task.status == TaskStatus.PENDING:
            task.status = TaskStatus.RUNNING

        # 8. Create sequential immutable TurnLog entry
        max_turn = (
            db.query(func.max(TurnLog.turn_number))
            .filter(TurnLog.task_id == task_id)
            .scalar()
            or 0
        )

        turn_log = TurnLog(
            id=f"turn-{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            agent_id=from_agent_rec.id,
            turn_number=max_turn + 1,
            action="handoff",
            tool="handoff_manager",
            input_payload=mask_secrets(
                {
                    "from_agent": from_agent_rec.name,
                    "to_agent": to_agent_rec.name,
                    "payload": payload,
                    "artifact_ids": clean_artifact_ids,
                },
                extra_secrets=self.extra_secrets,
            ),
            output_payload=mask_secrets(
                {
                    "handoff_id": handoff_id,
                    "phieu_buoc": phieu_buoc,
                    "chain": new_chain,
                },
                extra_secrets=self.extra_secrets,
            ),
            status="completed",
            created_at=datetime.now(timezone.utc),
        )
        db.add(turn_log)

        try:
            db.commit()
            db.refresh(task)
        except Exception:
            db.rollback()
            raise

        return HandoffRecord(
            handoff_id=handoff_id,
            task_id=task_id,
            step_index=step_index,
            from_agent=from_agent_rec.name,
            to_agent=to_agent_rec.name,
            chain=new_chain,
            phieu_buoc=phieu_buoc,
            artifact_ids=clean_artifact_ids,
            status="transferred",
            created_at=now_iso,
        )
