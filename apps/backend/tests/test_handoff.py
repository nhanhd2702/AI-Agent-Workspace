"""Comprehensive tests for Agent-to-Agent Handoff Protocol (Task 2.4 / F05.2).

Covers:
- Loop detection: self-handoff (A -> A) and ping-pong cycles (A -> B -> A -> B) -> HandoffLoopError
- Depth limit: max_depth=5 guard boundary (4 -> 5 works; 5 -> 6 -> HandoffLimitError)
- Input contract validation: missing required keys -> HandoffContractError
- Structured Phiếu bước shared memory packaging in task.task_metadata
- Immutable TurnLog persistence with secret masking
- Cross-task artifact validation & missing entities -> 404 / 422
- End-to-end API POST /api/v1/tasks/{task_id}/handoff (auth, 200, 404, 409, 422, WS broadcast)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.db.models import Agent, Artifact, Project, Task, TaskStatus, TurnLog
from app.db.session import init_db, seed_defaults
from app.main import create_app
from app.orchestrator.handoff import (
    HandoffContractError,
    HandoffError,
    HandoffLimitError,
    HandoffLoopError,
    HandoffManager,
    HandoffNotFoundError,
    HandoffRecord,
)


@pytest.fixture
def db_session(tmp_path: Path):
    """Provide an isolated, seeded SQLite session for unit tests."""
    db_path = tmp_path / "test_handoff_unit.db"
    factory = init_db(db_path, cache=False)
    with factory() as session:
        seed_defaults(session)
    with factory() as session:
        yield session


@pytest.fixture
def client_env(tmp_path: Path):
    """Provide a configured TestClient with valid auth token and seeded database."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "handoff_app.db"
    settings = AppSettings(
        workspace_dir=workspace,
        db_path=db_path,
        local_auth_token="secret-local-token-999",
    )
    app = create_app(settings=settings)
    client = TestClient(app, headers={"X-Local-Auth-Token": "secret-local-token-999"})
    return app, client, settings


# ============================================================================
# Brief Spec Tests & Loop/Depth Guard Tests
# ============================================================================

def test_handoff_blocks_depth_over_5_and_loops(db_session):
    """Brief-specified test: blocks repeated cycle and depth > 5."""
    mgr = HandoffManager(max_depth=5)
    with pytest.raises(HandoffLoopError):
        mgr.validate_chain(
            ["DeepResearcher", "ContentWriter", "DeepResearcher"],
            next_agent="ContentWriter",
        )
    with pytest.raises(HandoffLimitError):
        mgr.validate_chain(["A", "B", "C", "D", "E"], next_agent="F")


def test_self_handoff_and_ping_pong_cycles(db_session):
    """Self-handoff (immediate) and alternating ping-pong cycles are strictly blocked."""
    mgr = HandoffManager(max_depth=5)

    # 1. Immediate self-handoff
    with pytest.raises(HandoffLoopError, match="Self-handoff is not allowed"):
        mgr.validate_chain(["DeepResearcher"], next_agent="DeepResearcher")

    # 2. Case-insensitive self-handoff
    with pytest.raises(HandoffLoopError, match="Self-handoff is not allowed"):
        mgr.validate_chain(["deepresearcher"], next_agent="DeepResearcher")

    # 3. Simple ping-pong cycle: A -> B -> A -> B
    with pytest.raises(HandoffLoopError, match="Handoff cycle detected"):
        mgr.validate_chain(["A", "B", "A"], next_agent="B")

    # 4. Multi-agent ping-pong cycle: A -> B -> C -> B -> C
    with pytest.raises(HandoffLoopError, match="Handoff cycle detected"):
        mgr.validate_chain(["A", "B", "C", "B"], next_agent="C")


def test_depth_limit_boundary(db_session):
    """Verify depth limit boundary: 4 nodes + 5th works; 5 nodes + 6th raises HandoffLimitError."""
    mgr = HandoffManager(max_depth=5)

    # Chain of 4 + 5th node -> 5 nodes allowed
    res = mgr.validate_chain(["A", "B", "C", "D"], next_agent="E")
    assert res == ["A", "B", "C", "D", "E"]

    # Chain of 5 + 6th node -> raises HandoffLimitError
    with pytest.raises(HandoffLimitError, match="depth limit reached"):
        mgr.validate_chain(["A", "B", "C", "D", "E"], next_agent="F")


def test_valid_non_looping_escalation(db_session):
    """Valid transitions (including re-visiting an agent via a different directed edge) succeed."""
    mgr = HandoffManager(max_depth=5)

    # Clean linear chain
    assert mgr.validate_chain(["A", "B"], next_agent="C") == ["A", "B", "C"]

    # Escalation: A -> B -> A -> C (edge A->C was never traversed before)
    assert mgr.validate_chain(["A", "B", "A"], next_agent="C") == ["A", "B", "A", "C"]

    # Empty chain accepts first node
    assert mgr.validate_chain([], next_agent="DeepResearcher") == ["DeepResearcher"]


# ============================================================================
# Input Contract Validation Tests
# ============================================================================

def test_target_agent_input_contract_validation(db_session):
    """Validate target agent's required input_contract keys and artifact constraints."""
    mgr = HandoffManager(max_depth=5)

    target_agent = db_session.query(Agent).filter_by(name="ContentWriter").first()
    assert target_agent is not None

    # 1. No contract configured -> passes cleanly
    target_agent.config = None
    mgr.validate_input_contract(target_agent, payload={}, artifact_ids=[])

    # 2. List contract configured on target_agent
    target_agent.config = {"input_contract": ["brief", "target_audience"]}

    # Missing both
    with pytest.raises(HandoffContractError, match="missing required keys"):
        mgr.validate_input_contract(target_agent, payload={"topic": "AI"}, artifact_ids=[])

    # Missing target_audience
    with pytest.raises(HandoffContractError, match="target_audience"):
        mgr.validate_input_contract(
            target_agent,
            payload={"brief": "Write 500 words on AI agents"},
            artifact_ids=[],
        )

    # Whitespace-only or blank required key rejected
    with pytest.raises(HandoffContractError, match="missing required keys"):
        mgr.validate_input_contract(
            target_agent,
            payload={"brief": "   ", "target_audience": "B2B Tech"},
            artifact_ids=[],
        )

    # All keys present
    mgr.validate_input_contract(
        target_agent,
        payload={"brief": "Full brief", "target_audience": "B2B Tech"},
        artifact_ids=[],
    )

    # 3. Dict contract requiring artifacts
    target_agent.config = {
        "input_contract": {
            "required_keys": ["summary"],
            "require_artifacts": True,
            "min_artifacts": 2,
        }
    }

    # Missing summary
    with pytest.raises(HandoffContractError, match="summary"):
        mgr.validate_input_contract(target_agent, payload={}, artifact_ids=["art-1", "art-2"])

    # Artifact count too low
    with pytest.raises(HandoffContractError, match="expected at least 2 artifacts"):
        mgr.validate_input_contract(
            target_agent,
            payload={"summary": "Market analysis complete"},
            artifact_ids=["art-1"],
        )

    # Duplicate artifact IDs cannot bypass min_artifacts=2
    with pytest.raises(HandoffContractError, match="expected at least 2 artifacts"):
        mgr.validate_input_contract(
            target_agent,
            payload={"summary": "Market analysis complete"},
            artifact_ids=["art-1", "art-1"],
        )

    # Valid with 2 distinct artifacts
    mgr.validate_input_contract(
        target_agent,
        payload={"summary": "Market analysis complete"},
        artifact_ids=["art-1", "art-2"],
    )

    # Safely coerces malformed min_artifacts without crashing
    target_agent.config = {
        "input_contract": {
            "min_artifacts": "not-an-int",
        }
    }
    mgr.validate_input_contract(target_agent, payload={}, artifact_ids=[])


# ============================================================================
# DB Execution & Phiếu Bước / TurnLog Persistence Tests
# ============================================================================

def test_execute_handoff_db_persistence_and_phieu_buoc(db_session, tmp_path):
    """Execute handoff, verify Phiếu bước in task_metadata and TurnLog secret masking."""
    # Setup test task
    task = Task(
        id="task-test-handoff-01",
        project_id="proj-default",
        title="Content Pipeline Task",
        description="From research to copy",
        status=TaskStatus.RUNNING,
        assigned_agent_id="agent-deep-researcher",
        task_metadata={"handoff_chain": ["DeepResearcher"]},
    )
    db_session.add(task)

    # Setup test artifact
    art = Artifact(
        id="art-test-handoff-01",
        task_id=task.id,
        name="research_notes.md",
        file_path=str(tmp_path / "research_notes.md"),
        file_type="markdown",
    )
    db_session.add(art)
    db_session.commit()

    mgr = HandoffManager(max_depth=5, extra_secrets=["custom-secret-pwd-99"])

    raw_payload = {
        "summary": "Phiếu bước 1: Đã tổng hợp 10 báo cáo thị trường",
        "brief": "Triển khai viết bài Facebook",
        "notes": "Use model with api credential sk-proj-supersecretkey123456789 here",
        "api_key": "sk-proj-supersecretkey123456789",
        "token": "Bearer auth-token-secret-xyz",
        "custom": "custom-secret-pwd-99",
    }

    record = mgr.execute_handoff(
        db=db_session,
        task_id=task.id,
        from_agent="DeepResearcher",
        to_agent="ContentWriter",
        payload=raw_payload,
        artifact_ids=[art.id, art.id],
    )

    assert isinstance(record, HandoffRecord)
    assert record.task_id == task.id
    assert record.step_index == 1
    assert record.from_agent == "DeepResearcher"
    assert record.to_agent == "ContentWriter"
    assert record.chain == ["DeepResearcher", "ContentWriter"]
    assert record.artifact_ids == [art.id]
    assert record.status == "transferred"

    # Check Phiếu bước structure
    pb = record.phieu_buoc
    assert pb["task_id"] == task.id
    assert pb["from_agent"] == "DeepResearcher"
    assert pb["to_agent"] == "ContentWriter"
    assert pb["summary"] == "Phiếu bước 1: Đã tổng hợp 10 báo cáo thị trường"
    assert pb["artifact_ids"] == [art.id]
    assert pb["deliverables"] == [f"artifact:{art.id}"]
    assert "created_at" in pb

    # Check that secrets are masked in Phiếu bước payload
    assert "sk-***REDACTED***" in str(pb["payload"])
    assert "***REDACTED***" in str(pb["payload"])
    assert "sk-proj-supersecretkey123456789" not in str(pb["payload"])
    assert "custom-secret-pwd-99" not in str(pb["payload"])

    # Verify task updated in DB
    assert task.assigned_agent_id == "agent-content-writer"

    # Expire and reload task from DB to prove SQLAlchemy JSON mutation detection works
    db_session.expire_all()
    reloaded_task = db_session.get(Task, task.id)
    assert reloaded_task is not None
    assert reloaded_task.task_metadata is not None
    assert reloaded_task.task_metadata["handoff_chain"] == ["DeepResearcher", "ContentWriter"]
    assert len(reloaded_task.task_metadata["handoff_history"]) == 1
    assert reloaded_task.task_metadata["last_handoff"]["to_agent"] == "ContentWriter"

    # Verify TurnLog creation
    turns = (
        db_session.query(TurnLog)
        .filter_by(task_id=task.id, action="handoff")
        .all()
    )
    assert len(turns) == 1
    tlog = turns[0]
    assert tlog.tool == "handoff_manager"
    assert tlog.status == "completed"
    assert tlog.agent_id == "agent-deep-researcher"
    # Ensure TurnLog payloads also masked secrets
    assert "sk-proj-supersecretkey123456789" not in str(tlog.input_payload)
    assert "custom-secret-pwd-99" not in str(tlog.input_payload)


def test_execute_handoff_not_found_and_cross_task_artifacts(db_session, tmp_path):
    """Missing task, unknown agent, missing artifact, or cross-task artifact raise appropriate errors."""
    mgr = HandoffManager(max_depth=5)

    # 1. Unknown task
    with pytest.raises(HandoffNotFoundError, match="Task 'non-existent-task' not found"):
        mgr.execute_handoff(
            db=db_session,
            task_id="non-existent-task",
            from_agent="DeepResearcher",
            to_agent="ContentWriter",
            payload={},
            artifact_ids=[],
        )

    # Create valid task 1
    t1 = Task(
        id="task-valid-01",
        project_id="proj-default",
        title="Task 1",
        status=TaskStatus.RUNNING,
    )
    # Create valid task 2
    t2 = Task(
        id="task-valid-02",
        project_id="proj-default",
        title="Task 2",
        status=TaskStatus.RUNNING,
    )
    # Artifact on task 2
    art2 = Artifact(
        id="art-belonging-to-task-2",
        task_id=t2.id,
        name="t2.png",
        file_path=str(tmp_path / "t2.png"),
        file_type="image",
    )
    db_session.add_all([t1, t2, art2])
    db_session.commit()

    # 2. Unknown from_agent
    with pytest.raises(HandoffNotFoundError, match="Source agent 'GhostAgent' not found"):
        mgr.execute_handoff(
            db=db_session,
            task_id=t1.id,
            from_agent="GhostAgent",
            to_agent="ContentWriter",
            payload={},
            artifact_ids=[],
        )

    # 3. Unknown to_agent
    with pytest.raises(HandoffNotFoundError, match="Target agent 'UnknownAgent' not found"):
        mgr.execute_handoff(
            db=db_session,
            task_id=t1.id,
            from_agent="DeepResearcher",
            to_agent="UnknownAgent",
            payload={},
            artifact_ids=[],
        )

    # 4. Unknown artifact
    with pytest.raises(HandoffNotFoundError, match="Artifact 'non-existent-art' not found"):
        mgr.execute_handoff(
            db=db_session,
            task_id=t1.id,
            from_agent="DeepResearcher",
            to_agent="ContentWriter",
            payload={},
            artifact_ids=["non-existent-art"],
        )

    # 5. Cross-task artifact violation
    with pytest.raises(HandoffContractError, match="belongs to task 'task-valid-02'"):
        mgr.execute_handoff(
            db=db_session,
            task_id=t1.id,
            from_agent="DeepResearcher",
            to_agent="ContentWriter",
            payload={},
            artifact_ids=[art2.id],
        )


def test_execute_handoff_rejects_terminal_task(db_session):
    """Handoff cannot be executed on COMPLETED or CANCELLED tasks."""
    mgr = HandoffManager(max_depth=5)

    comp_task = Task(
        id="task-completed-term",
        project_id="proj-default",
        title="Completed Task",
        status=TaskStatus.COMPLETED,
    )
    db_session.add(comp_task)
    db_session.commit()

    with pytest.raises(HandoffError, match="terminal task"):
        mgr.execute_handoff(
            db=db_session,
            task_id=comp_task.id,
            from_agent="DeepResearcher",
            to_agent="ContentWriter",
            payload={},
            artifact_ids=[],
        )


# ============================================================================
# API Endpoint Tests: POST /api/v1/tasks/{task_id}/handoff
# ============================================================================

def test_handoff_api_auth_required(client_env):
    """POST /api/v1/tasks/{task_id}/handoff requires valid X-Local-Auth-Token."""
    app, client, settings = client_env

    # 1. No token -> 401
    bad_client = TestClient(app)
    resp = bad_client.post(
        "/api/v1/tasks/any-task/handoff",
        json={"fromAgent": "DeepResearcher", "toAgent": "ContentWriter"},
    )
    assert resp.status_code == 401

    # 2. Invalid token -> 401
    wrong_client = TestClient(app, headers={"X-Local-Auth-Token": "wrong-token"})
    resp = wrong_client.post(
        "/api/v1/tasks/any-task/handoff",
        json={"fromAgent": "DeepResearcher", "toAgent": "ContentWriter"},
    )
    assert resp.status_code == 401


def test_handoff_api_e2e_success_and_ws_broadcast(client_env):
    """POST /api/v1/tasks/{task_id}/handoff succeeds, records TurnLog, and broadcasts to ws_manager."""
    app, client, settings = client_env
    factory = app.state.session_factory

    # Create task
    task_id = "task-api-handoff-success"
    with factory() as db:
        t = Task(
            id=task_id,
            project_id="proj-default",
            title="E2E API Task",
            status=TaskStatus.RUNNING,
            assigned_agent_id="agent-deep-researcher",
            task_metadata={"handoff_chain": ["DeepResearcher"]},
        )
        db.add(t)
        db.commit()

    # Track WS broadcasts
    broadcast_events: list[dict[str, Any]] = []

    class FakeWsManager:
        async def broadcast(self, task_id: str, event: dict[str, Any]) -> None:
            broadcast_events.append({"task_id": task_id, "event": event})

    app.state.ws_manager = FakeWsManager()

    resp = client.post(
        f"/api/v1/tasks/{task_id}/handoff",
        json={
            "fromAgent": "DeepResearcher",
            "toAgent": "ContentWriter",
            "payload": {
                "summary": "Phiếu bước: Bài viết phân tích",
                "brief": "Viết 1 bài chuyên sâu",
                "secret_key": "sk-1234567890123456",
            },
            "artifactIds": [],
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    data = body["data"]
    assert data["task_id"] == task_id
    assert data["step_index"] == 1
    assert data["from_agent"] == "DeepResearcher"
    assert data["to_agent"] == "ContentWriter"
    assert data["chain"] == ["DeepResearcher", "ContentWriter"]
    assert "sk-***REDACTED***" in str(data["phieu_buoc"]["payload"])

    # Verify WS broadcast received the masked handoff event
    assert len(broadcast_events) == 1
    ev = broadcast_events[0]
    assert ev["task_id"] == task_id
    assert ev["event"]["event"] == "handoff"
    assert ev["event"]["type"] == "handoff"
    assert "sk-1234567890123456" not in str(ev["event"])


def test_handoff_api_error_status_codes(client_env):
    """POST /api/v1/tasks/{task_id}/handoff maps domain errors to 404, 409, and 422."""
    app, client, settings = client_env
    factory = app.state.session_factory

    task_id = "task-api-errors"
    with factory() as db:
        t = Task(
            id=task_id,
            project_id="proj-default",
            title="Error Mapping Task",
            status=TaskStatus.RUNNING,
            assigned_agent_id="agent-deep-researcher",
            task_metadata={"handoff_chain": ["DeepResearcher", "ContentWriter", "DeepResearcher"]},
        )
        db.add(t)
        # Configure input contract on ImageStudio
        img_agent = db.query(Agent).filter_by(name="ImageStudio").first()
        if img_agent:
            img_agent.config = {"input_contract": ["layout_spec", "color_palette"]}
        db.commit()

    # 1. 404 for unknown task
    resp = client.post(
        "/api/v1/tasks/non-existent-task/handoff",
        json={"fromAgent": "DeepResearcher", "toAgent": "ContentWriter"},
    )
    assert resp.status_code == 404

    # 2. 409 Conflict for ping-pong cycle (DeepResearcher -> ContentWriter already traversed)
    resp = client.post(
        f"/api/v1/tasks/{task_id}/handoff",
        json={"fromAgent": "DeepResearcher", "toAgent": "ContentWriter"},
    )
    assert resp.status_code == 409
    assert "cycle detected" in resp.json()["detail"]

    # 3. 422 Unprocessable Content for input contract violation
    resp = client.post(
        f"/api/v1/tasks/{task_id}/handoff",
        json={
            "fromAgent": "DeepResearcher",
            "toAgent": "ImageStudio",
            "payload": {"missing_layout": True},
        },
    )
    assert resp.status_code == 422
    assert "input contract violation" in resp.json()["detail"]
