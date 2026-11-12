"""Tests for Human-in-the-Loop (HIL) Review Gates Backend API (Task 2.5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import asyncio
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.db.models import ReviewGate, Task, TaskAuditLog, TaskStatus, TurnLog
from app.db.session import init_db
from app.db.state_machine import TaskStateMachine
from app.main import create_app
from app.orchestrator.graph import OrchestratorGraph
from app.orchestrator.planner import ExecutionPlan, SubTaskNode


@pytest.fixture
def env(tmp_path: Path):
    """Create isolated FastAPI app, TestClient, and seeded DB session factory."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="test-review-token")
    app = create_app(settings)
    client = TestClient(app, headers={"X-Local-Auth-Token": "test-review-token"})
    return client, app, settings


@pytest.fixture
def client_with_db(env):
    client, _, _ = env
    return client


@pytest.fixture
def active_review_id(env) -> str:
    client, app, _ = env
    factory = app.state.session_factory
    task_id = f"task-active-{uuid.uuid4().hex[:8]}"
    review_id = f"rev-active-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    with factory() as db:
        db.add(
            Task(
                id=task_id,
                project_id="proj-default",
                title="Active HIL Task",
                status=TaskStatus.WAITING_REVIEW,
            )
        )
        db.add(
            ReviewGate(
                id=review_id,
                task_id=task_id,
                gate_type="storyboard",
                status="pending",
                expires_at=now + timedelta(hours=24),
                created_at=now,
            )
        )
        db.commit()
    return review_id


@pytest.fixture
def expired_review_id(env) -> str:
    _, app, _ = env
    factory = app.state.session_factory
    task_id = f"task-expired-{uuid.uuid4().hex[:8]}"
    review_id = f"rev-expired-{uuid.uuid4().hex[:8]}"
    past = datetime.now(timezone.utc) - timedelta(hours=25)
    with factory() as db:
        db.add(
            Task(
                id=task_id,
                project_id="proj-default",
                title="Expired HIL Task",
                status=TaskStatus.WAITING_REVIEW,
            )
        )
        db.add(
            ReviewGate(
                id=review_id,
                task_id=task_id,
                gate_type="storyboard",
                status="pending",
                expires_at=past + timedelta(hours=24),
                created_at=past,
            )
        )
        db.commit()
    return review_id


# --- 1. Brief Step 1 Test ---


def test_reject_requires_at_least_5_char_feedback_and_expired_returns_410(
    client_with_db: TestClient, expired_review_id: str, active_review_id: str
):
    r1 = client_with_db.patch(
        f"/api/v1/reviews/{active_review_id}/decide",
        json={"decision": "reject", "feedback_text": "ko"},
    )
    assert r1.status_code == 400
    r2 = client_with_db.patch(
        f"/api/v1/reviews/{expired_review_id}/decide",
        json={"decision": "approve"},
    )
    assert r2.status_code == 410


# --- 2. Auth & Create Review Tests ---


def test_reviews_endpoints_require_local_auth_token(tmp_path: Path):
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="secret-tok")
    client = TestClient(create_app(settings))
    assert client.post("/api/v1/reviews", json={"task_id": "t1"}).status_code == 401
    assert client.get("/api/v1/reviews").status_code == 401
    assert (
        client.patch("/api/v1/reviews/r1/decide", json={"decision": "approve"}).status_code
        == 401
    )


def test_create_and_list_review_gate_with_24h_utc_expiry(env):
    client, app, _ = env
    factory = app.state.session_factory
    with factory() as db:
        db.add(
            Task(
                id="task-create-rev",
                project_id="proj-default",
                title="Write campaign script",
                status=TaskStatus.RUNNING,
            )
        )
        db.commit()

    resp = client.post(
        "/api/v1/reviews",
        json={
            "task_id": "task-create-rev",
            "gate_type": "storyboard",
            "summary": "Duyệt kịch bản 60s trước khi render",
            "payload": {"scene_count": 6},
        },
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["task_id"] == "task-create-rev"
    assert data["gate_type"] == "storyboard"
    assert data["status"] == "pending"
    assert data["summary"] == "Duyệt kịch bản 60s trước khi render"
    assert data["payload"] == {"scene_count": 6}
    assert data["created_at"].endswith("+00:00")
    assert data["expires_at"].endswith("+00:00")

    created_dt = datetime.fromisoformat(data["created_at"])
    expires_dt = datetime.fromisoformat(data["expires_at"])
    diff_hours = (expires_dt - created_dt).total_seconds() / 3600.0
    assert 23.9 <= diff_hours <= 24.1

    # Task transitioned to WAITING_REVIEW
    with factory() as db:
        t = db.get(Task, "task-create-rev")
        assert t is not None
        assert t.status == TaskStatus.WAITING_REVIEW

    # Duplicate active pending review for same task -> 409
    dup = client.post(
        "/api/v1/reviews",
        json={"task_id": "task-create-rev", "gate_type": "storyboard"},
    )
    assert dup.status_code == 409

    # Nonexistent task -> 404
    missing = client.post(
        "/api/v1/reviews",
        json={"task_id": "task-does-not-exist", "gate_type": "hil"},
    )
    assert missing.status_code == 404

    # List filtered by task_id
    listed = client.get("/api/v1/reviews", params={"task_id": "task-create-rev"})
    assert listed.status_code == 200
    items = listed.json()["data"]
    assert len(items) == 1
    assert items[0]["id"] == data["id"]


# --- 3. Error & Validation Cases ---


def test_decide_error_cases_404_409_400_and_naive_24h_expiry_410(env):
    client, app, _ = env
    factory = app.state.session_factory

    # 404 unknown review
    r404 = client.patch("/api/v1/reviews/rev-missing/decide", json={"decision": "approve"})
    assert r404.status_code == 404

    # Create active review + whitespace reject -> 400
    with factory() as db:
        db.add(
            Task(
                id="task-err-1",
                project_id="proj-default",
                title="Error validation task",
                status=TaskStatus.WAITING_REVIEW,
            )
        )
        db.add(
            ReviewGate(
                id="rev-err-1",
                task_id="task-err-1",
                gate_type="hil",
                status="pending",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
            )
        )
        # Naive timestamp review created >24h ago with expires_at=None -> must return 410
        db.add(
            Task(
                id="task-naive-exp",
                project_id="proj-default",
                title="Naive expired task",
                status=TaskStatus.WAITING_REVIEW,
            )
        )
        db.add(
            ReviewGate(
                id="rev-naive-exp",
                task_id="task-naive-exp",
                gate_type="hil",
                status="pending",
                expires_at=None,
                created_at=(datetime.now(timezone.utc) - timedelta(hours=26)).replace(tzinfo=None),
            )
        )
        db.commit()

    # Whitespace-only feedback on reject -> 400
    r_ws = client.patch(
        "/api/v1/reviews/rev-err-1/decide",
        json={"decision": "reject", "feedback_text": "     "},
    )
    assert r_ws.status_code == 400

    # Missing feedback on reject -> 400
    r_missing = client.patch(
        "/api/v1/reviews/rev-err-1/decide",
        json={"decision": "reject"},
    )
    assert r_missing.status_code == 400

    # Invalid decision -> 400
    r_bad_dec = client.patch(
        "/api/v1/reviews/rev-err-1/decide",
        json={"decision": "unknown"},
    )
    assert r_bad_dec.status_code == 400

    # Approve successfully -> 200
    r_ok = client.patch(
        "/api/v1/reviews/rev-err-1/decide",
        json={"decision": "approve", "feedback_text": "Looks good"},
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["data"]["status"] == "approved"

    # Double decide -> 409 Conflict
    r_double = client.patch(
        "/api/v1/reviews/rev-err-1/decide",
        json={"decision": "approve"},
    )
    assert r_double.status_code == 409

    # Naive >24h review with expires_at=None -> 410 Gone and marked expired
    r_naive_410 = client.patch(
        "/api/v1/reviews/rev-naive-exp/decide",
        json={"decision": "approve"},
    )
    assert r_naive_410.status_code == 410
    with factory() as db:
        rev = db.get(ReviewGate, "rev-naive-exp")
        assert rev is not None
        assert rev.status == "expired"


# --- 4. LangGraph Resume on Approve & Edit + Reject Re-enqueue ---


def test_approve_and_edit_resume_langgraph_checkpoint(env):
    client, app, settings = env
    factory = app.state.session_factory
    cp_db = (settings.workspace_dir / "checkpoints.db").resolve()

    # Test approve resumes wave 1 -> wave 2 to completion
    task_id = "task-lg-approve"
    nodes = [
        SubTaskNode(id="draft", agent_id="ContentWriter", instruction="Write draft", requires_review=True),
        SubTaskNode(id="publish", agent_id="ImageStudio", instruction="Render visual", depends_on=["draft"]),
    ]
    plan = ExecutionPlan(
        task_id=task_id,
        task_type="copywriting",
        nodes=nodes,
        waves=[["draft"], ["publish"]],
        mode="copilot",
    )
    with OrchestratorGraph(checkpoint_db_path=cp_db) as graph:
        paused = graph.run(plan, thread_id=task_id)
        assert "__interrupt__" in paused
        assert graph.is_interrupted(task_id) is True

    with factory() as db:
        db.add(
            Task(
                id=task_id,
                project_id="proj-default",
                title="LangGraph Approve Task",
                status=TaskStatus.RUNNING,
            )
        )
        db.commit()

    rev_resp = client.post(
        "/api/v1/reviews",
        json={"task_id": task_id, "gate_type": "storyboard", "summary": "Approve draft?"},
    )
    assert rev_resp.status_code == 201
    review_id = rev_resp.json()["data"]["id"]

    dec_resp = client.patch(
        f"/api/v1/reviews/{review_id}/decide",
        json={"decision": "approve", "feedback_text": "OK proceed"},
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()["data"]
    assert dec_data["status"] == "approved"
    assert dec_data["graph_resumed"] is True
    assert dec_data["graph_status"] == "completed"

    with OrchestratorGraph(checkpoint_db_path=cp_db) as graph:
        assert graph.is_interrupted(task_id) is False
        state = graph.get_state(task_id)
        assert state.values["status"] == "completed"
        assert state.values["completed_nodes"] == ["draft", "publish"]

    with factory() as db:
        t = db.get(Task, task_id)
        assert t is not None
        assert t.status == TaskStatus.COMPLETED

    # Test edit decision also resumes checkpoint and masks secrets in edited_content
    task_edit_id = "task-lg-edit"
    plan_edit = ExecutionPlan(
        task_id=task_edit_id,
        task_type="copywriting",
        nodes=[
            SubTaskNode(id="w1", agent_id="ContentWriter", instruction="Draft", requires_review=True),
            SubTaskNode(id="w2", agent_id="UIDesigner", instruction="Layout", depends_on=["w1"]),
        ],
        waves=[["w1"], ["w2"]],
        mode="copilot",
    )
    with OrchestratorGraph(checkpoint_db_path=cp_db) as graph:
        paused = graph.run(plan_edit, thread_id=task_edit_id)
        assert "__interrupt__" in paused

    with factory() as db:
        db.add(
            Task(
                id=task_edit_id,
                project_id="proj-default",
                title="LangGraph Edit Task",
                status=TaskStatus.WAITING_REVIEW,
            )
        )
        db.add(
            ReviewGate(
                id="rev-lg-edit",
                task_id=task_edit_id,
                gate_type="copy",
                status="pending",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        )
        db.commit()

    edit_resp = client.patch(
        "/api/v1/reviews/rev-lg-edit/decide",
        json={
            "decision": "edit",
            "edited_content": "Updated script without key sk-live1234567890abcdef",
            "feedback_text": "Edited hook",
        },
    )
    assert edit_resp.status_code == 200
    edit_data = edit_resp.json()["data"]
    assert edit_data["status"] == "edited"
    assert edit_data["graph_resumed"] is True
    assert "sk-live1234567890abcdef" not in str(edit_data["edited_content"])
    assert "REDACTED" in str(edit_data["edited_content"])


def test_reject_increments_turn_number_masks_secrets_and_reenqueues(env):
    client, app, settings = env
    factory = app.state.session_factory
    cp_db = (settings.workspace_dir / "checkpoints.db").resolve()
    task_id = "task-reject-turn"

    plan = ExecutionPlan(
        task_id=task_id,
        task_type="copywriting",
        nodes=[
            SubTaskNode(id="w1", agent_id="ContentWriter", instruction="Draft", requires_review=True),
            SubTaskNode(id="w2", agent_id="UIDesigner", instruction="Build", depends_on=["w1"]),
        ],
        waves=[["w1"], ["w2"]],
        mode="copilot",
    )
    with OrchestratorGraph(checkpoint_db_path=cp_db) as graph:
        paused = graph.run(plan, thread_id=task_id)
        assert "__interrupt__" in paused

    with factory() as db:
        db.add(
            Task(
                id=task_id,
                project_id="proj-default",
                title="Reject Turn Increment Task",
                status=TaskStatus.WAITING_REVIEW,
            )
        )
        db.add(
            TurnLog(
                id="turn-initial-1",
                task_id=task_id,
                turn_number=1,
                action="execute_subtask",
                tool="worker_agent",
                status="completed",
            )
        )
        db.add(
            ReviewGate(
                id="rev-reject-1",
                task_id=task_id,
                gate_type="storyboard",
                status="pending",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        )
        db.commit()

    resp = client.patch(
        "/api/v1/reviews/rev-reject-1/decide",
        json={
            "decision": "reject",
            "feedback_text": "Sửa lại tone giọng và bỏ token sk-supersecret987654321",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "rejected"
    assert data["decision"] == "reject"
    assert data["turn_number"] == 2
    assert data["re_enqueued"] is True
    assert "sk-supersecret987654321" not in data["feedback_text"]
    assert "REDACTED" in data["feedback_text"]

    with factory() as db:
        task = db.get(Task, task_id)
        assert task is not None
        # Re-enqueued cleanly back to RUNNING after REJECTED
        assert task.status == TaskStatus.RUNNING
        assert task.task_metadata is not None
        assert task.task_metadata["turn_number"] == 2
        assert task.task_metadata["re_enqueued"] is True

        turns = (
            db.query(TurnLog)
            .filter(TurnLog.task_id == task_id)
            .order_by(TurnLog.turn_number.asc())
            .all()
        )
        assert len(turns) == 2
        assert turns[-1].turn_number == 2
        assert turns[-1].action == "review_rejected"
        assert "sk-supersecret987654321" not in str(turns[-1].input_payload)
        assert "REDACTED" in str(turns[-1].input_payload)

        audits = (
            db.query(TaskAuditLog)
            .filter(TaskAuditLog.task_id == task_id)
            .order_by(TaskAuditLog.created_at.asc())
            .all()
        )
        transitions = [(a.from_status, a.to_status) for a in audits]
        assert ("waiting_review", "rejected") in transitions
        assert ("rejected", "running") in transitions

    # LangGraph checkpoint recorded rejection and stopped downstream wave
    with OrchestratorGraph(checkpoint_db_path=cp_db) as graph:
        assert graph.is_interrupted(task_id) is False
        state = graph.get_state(task_id)
        assert state.values["status"] == "rejected"


def test_websocket_broadcasts_review_decided_event(env):
    client, app, _ = env
    factory = app.state.session_factory
    task_id = "task-ws-rev"

    with factory() as db:
        db.add(
            Task(
                id=task_id,
                project_id="proj-default",
                title="WS Review Task",
                status=TaskStatus.WAITING_REVIEW,
            )
        )
        db.add(
            ReviewGate(
                id="rev-ws-1",
                task_id=task_id,
                gate_type="hil",
                status="pending",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        )
        db.commit()

    with client.websocket_connect(f"/ws/tasks/{task_id}?token=test-review-token") as ws:
        connected = ws.receive_json()
        assert connected["event"] == "connected"

        resp = client.patch(
            "/api/v1/reviews/rev-ws-1/decide",
            json={"decision": "approve"},
        )
        assert resp.status_code == 200

        event = ws.receive_json()
        assert event["event"] == "review_decided"
        assert event["task_id"] == task_id
        assert event["review_id"] == "rev-ws-1"
        assert event["decision"] == "approve"


# --- 5. Regression Tests for Reviewer Findings ---


def test_task_state_machine_transition_commit_false_rolls_back_atomically(tmp_path: Path):
    """TaskStateMachine.transition(..., commit=False) flushes without committing until caller commits."""
    SessionLocal = init_db(tmp_path / "fsm_atomic.db", cache=False)
    with SessionLocal() as db:
        from app.db.session import seed_defaults

        seed_defaults(db)
        db.add(
            Task(
                id="t-atomic",
                project_id="proj-default",
                title="Atomic FSM test",
                status=TaskStatus.WAITING_REVIEW,
            )
        )
        db.commit()

        TaskStateMachine.transition(
            db, "t-atomic", TaskStatus.REJECTED, actor="user", reason="r1", commit=False
        )
        TaskStateMachine.transition(
            db, "t-atomic", TaskStatus.RUNNING, actor="system", reason="r2", commit=False
        )
        db.rollback()

    with SessionLocal() as db:
        t = db.get(Task, "t-atomic")
        assert t is not None
        assert t.status == TaskStatus.WAITING_REVIEW
        assert db.query(TaskAuditLog).filter_by(task_id="t-atomic").count() == 0


def test_decide_rejects_terminal_task_with_409_and_masks_actor(env):
    client, app, _ = env
    factory = app.state.session_factory
    now = datetime.now(timezone.utc)

    with factory() as db:
        db.add(
            Task(
                id="task-terminal-done",
                project_id="proj-default",
                title="Already completed",
                status=TaskStatus.COMPLETED,
            )
        )
        db.add(
            ReviewGate(
                id="rev-terminal-done",
                task_id="task-terminal-done",
                gate_type="hil",
                status="pending",
                expires_at=now + timedelta(hours=24),
            )
        )
        db.add(
            Task(
                id="task-mask-actor",
                project_id="proj-default",
                title="Actor masking task",
                status=TaskStatus.WAITING_REVIEW,
            )
        )
        db.add(
            ReviewGate(
                id="rev-mask-actor",
                task_id="task-mask-actor",
                gate_type="hil",
                status="pending",
                expires_at=now + timedelta(hours=24),
            )
        )
        db.commit()

    # Terminal task -> 409 Conflict
    r_term = client.patch(
        "/api/v1/reviews/rev-terminal-done/decide",
        json={"decision": "approve"},
    )
    assert r_term.status_code == 409

    # Secret inside actor is masked across ReviewGate, TurnLog, and TaskAuditLog
    r_actor = client.patch(
        "/api/v1/reviews/rev-mask-actor/decide",
        json={
            "decision": "reject",
            "feedback_text": "Cần chỉnh sửa lại nội dung",
            "actor": "user-sk-secretactor1234567890",
        },
    )
    assert r_actor.status_code == 200
    assert "sk-secretactor1234567890" not in str(r_actor.json()["data"]["actor"])

    with factory() as db:
        rev = db.get(ReviewGate, "rev-mask-actor")
        assert rev is not None
        assert rev.actor is not None
        assert "sk-secretactor1234567890" not in rev.actor
        assert "REDACTED" in rev.actor

        turn = db.query(TurnLog).filter_by(task_id="task-mask-actor").first()
        assert turn is not None
        assert "sk-secretactor1234567890" not in str(turn.input_payload)

        audit = db.query(TaskAuditLog).filter_by(task_id="task-mask-actor").first()
        assert audit is not None
        assert "sk-secretactor1234567890" not in audit.actor


def test_decide_reverts_claim_to_pending_if_checkpoint_resume_fails(env, monkeypatch):
    client, app, _ = env
    factory = app.state.session_factory
    now = datetime.now(timezone.utc)

    with factory() as db:
        db.add(
            Task(
                id="task-resume-fail",
                project_id="proj-default",
                title="Resume failure rollback",
                status=TaskStatus.WAITING_REVIEW,
            )
        )
        db.add(
            ReviewGate(
                id="rev-resume-fail",
                task_id="task-resume-fail",
                gate_type="storyboard",
                status="pending",
                expires_at=now + timedelta(hours=24),
            )
        )
        db.commit()

    def boom(*args, **kwargs):
        raise RuntimeError("simulated checkpoint failure")

    monkeypatch.setattr("app.api.reviews._resume_graph_if_interrupted", boom)

    with pytest.raises(RuntimeError, match="simulated checkpoint failure"):
        client.patch(
            "/api/v1/reviews/rev-resume-fail/decide",
            json={"decision": "approve"},
        )

    with factory() as db:
        rev = db.get(ReviewGate, "rev-resume-fail")
        task = db.get(Task, "task-resume-fail")
        assert rev is not None
        assert rev.status == "pending"
        assert rev.decided_at is None
        assert task is not None
        assert task.status == TaskStatus.WAITING_REVIEW
        assert db.query(TaskAuditLog).filter_by(task_id="task-resume-fail").count() == 0


@pytest.mark.asyncio
async def test_concurrent_decide_requests_yield_one_200_and_one_409(tmp_path: Path):
    settings = AppSettings(
        db_path=tmp_path / "custom" / "app.db",
        local_auth_token="test-concurrent-tok",
    )
    app = create_app(settings)
    # Verify checkpoints.db path derives from resolved_db_path.parent when db_path is explicit
    assert app.state.checkpoint_db_path == (tmp_path / "custom" / "checkpoints.db").resolve()

    now = datetime.now(timezone.utc)
    with app.state.session_factory() as db:
        db.add(
            Task(
                id="task-conc-1",
                project_id="proj-default",
                title="Concurrent decide",
                status=TaskStatus.WAITING_REVIEW,
            )
        )
        db.add(
            ReviewGate(
                id="rev-conc-1",
                task_id="task-conc-1",
                gate_type="hil",
                status="pending",
                expires_at=now + timedelta(hours=24),
            )
        )
        db.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-Local-Auth-Token": "test-concurrent-tok"},
    ) as ac:
        r1, r2 = await asyncio.gather(
            ac.patch("/api/v1/reviews/rev-conc-1/decide", json={"decision": "approve"}),
            ac.patch("/api/v1/reviews/rev-conc-1/decide", json={"decision": "approve"}),
        )

    codes = sorted([r1.status_code, r2.status_code])
    assert codes == [200, 409]


@pytest.mark.asyncio
async def test_waiting_request_sees_fresh_snapshot_after_reverted_claim_and_blank_actor_defaults(
    tmp_path: Path, monkeypatch
):
    """[Round 2 Fix] Request waiting on task_lock must drop stale SQLite snapshot after claim revert,
    and whitespace-only actor must fall back to 'user'."""
    import threading

    settings = AppSettings(
        db_path=tmp_path / "round2" / "app.db",
        local_auth_token="test-r2-tok",
    )
    app = create_app(settings)
    now = datetime.now(timezone.utc)
    with app.state.session_factory() as db:
        db.add(
            Task(
                id="task-r2-snap",
                project_id="proj-default",
                title="Snapshot freshness task",
                status=TaskStatus.WAITING_REVIEW,
            )
        )
        db.add(
            ReviewGate(
                id="rev-r2-snap",
                task_id="task-r2-snap",
                gate_type="hil",
                status="pending",
                expires_at=now + timedelta(hours=24),
            )
        )
        db.commit()

    resume_entered = threading.Event()
    allow_resume_finish = threading.Event()
    call_count = 0

    def controlled_resume(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            resume_entered.set()
            assert allow_resume_finish.wait(timeout=3.0)
            raise RuntimeError("transient checkpoint error")
        return None

    monkeypatch.setattr("app.api.reviews._resume_graph_if_interrupted", controlled_resume)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-Local-Auth-Token": "test-r2-tok"},
    ) as ac:
        req_a = asyncio.create_task(
            ac.patch(
                "/api/v1/reviews/rev-r2-snap/decide",
                json={"decision": "approve"},
            )
        )

        # Wait until Request A holds task_lock and has committed status='processing'
        for _ in range(100):
            if resume_entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert resume_entered.is_set()

        # Start Request B while Request A holds task_lock (Request B reads initial_review='processing' and blocks on lock)
        req_b = asyncio.create_task(
            ac.patch(
                "/api/v1/reviews/rev-r2-snap/decide",
                json={"decision": "approve", "actor": "   "},
            )
        )
        await asyncio.sleep(0.05)

        # Release Request A -> fails, reverts 'processing' -> 'pending', releases lock
        allow_resume_finish.set()
        resp_a, resp_b = await asyncio.gather(req_a, req_b)

    assert resp_a.status_code == 500
    assert resp_b.status_code == 200
    assert resp_b.json()["data"]["status"] == "approved"
    assert resp_b.json()["data"]["actor"] == "user"


