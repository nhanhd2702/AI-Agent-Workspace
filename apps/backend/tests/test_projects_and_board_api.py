"""Tests for Projects API, Task Board listing, FSM state transitions, and Turn/Audit Logs (Task 2.6)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.db.models import Task, TaskAuditLog, TaskStatus, TurnLog
from app.main import create_app


@pytest.fixture
def env(tmp_path: Path):
    """Create isolated FastAPI app, TestClient, and seeded DB session factory."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="board-test-secret-token")
    app = create_app(settings)
    client = TestClient(app, headers={"X-Local-Auth-Token": "board-test-secret-token"})
    return client, app, settings


def test_projects_and_board_endpoints_require_auth(tmp_path: Path):
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="strict-token-123")
    client = TestClient(create_app(settings))

    assert client.get("/api/v1/projects").status_code == 401
    assert client.post("/api/v1/projects", json={"name": "Test"}).status_code == 401
    assert client.get("/api/v1/tasks").status_code == 401
    assert client.patch("/api/v1/tasks/t1/state", json={"target_state": "running"}).status_code == 401
    assert client.get("/api/v1/tasks/t1/logs").status_code == 401


def test_projects_crud_and_task_summary(env):
    client, app, _ = env

    # Seeded default project exists
    list_resp = client.get("/api/v1/projects")
    assert list_resp.status_code == 200
    projects = list_resp.json()["data"]
    assert any(p["id"] == "proj-default" for p in projects)

    # Create a new project
    create_resp = client.post(
        "/api/v1/projects",
        json={
            "name": "Chiến dịch Q4",
            "description": "Kế hoạch ra mắt sản phẩm với api_key=sk-secretkey1234567890",
            "tags": ["marketing", "q4"],
            "defaultDepartmentId": "dept-content",
        },
    )
    assert create_resp.status_code == 201
    proj = create_resp.json()["data"]
    assert proj["name"] == "Chiến dịch Q4"
    assert "sk-secretkey1234567890" not in (proj["description"] or "")
    assert "***REDACTED***" in (proj["description"] or "")
    assert proj["created_at"].endswith("+00:00")

    # Duplicate explicit ID returns 409
    dup_resp = client.post(
        "/api/v1/projects",
        json={"id": proj["id"], "name": "Duplicate ID"},
    )
    assert dup_resp.status_code == 409

    # Add a task under the new project and check summary
    with app.state.session_factory() as db:
        db.add(
            Task(
                id="task-proj-1",
                project_id=proj["id"],
                title="Viết landing page",
                status=TaskStatus.RUNNING,
                assigned_agent_id="agent-content-writer",
            )
        )
        db.commit()

    get_resp = client.get(f"/api/v1/projects/{proj['id']}")
    assert get_resp.status_code == 200
    detail = get_resp.json()["data"]
    assert detail["task_count"] == 1
    assert detail["status_summary"]["running"] == 1


def test_list_tasks_filtering_and_agent_name(env):
    client, app, _ = env

    with app.state.session_factory() as db:
        db.add(
            Task(
                id="task-board-1",
                project_id="proj-default",
                title="Kịch bản TikTok",
                status=TaskStatus.PENDING,
                assigned_agent_id="agent-content-writer",
                task_metadata={"api_key": "AIzaSySecretKey1234567890"},
            )
        )
        db.add(
            Task(
                id="task-board-2",
                project_id="proj-default",
                title="Nghiên cứu đối thủ",
                status=TaskStatus.WAITING_REVIEW,
                assigned_agent_id="agent-deep-researcher",
            )
        )
        db.commit()

    # All tasks
    resp = client.get("/api/v1/tasks")
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert len(items) == 2

    t1 = next(item for item in items if item["id"] == "task-board-1")
    assert t1["agent_name"] == "ContentWriter"
    assert t1["agentName"] == "ContentWriter"
    assert t1["created_at"].endswith("+00:00")
    assert "AIzaSySecretKey1234567890" not in str(t1["metadata"])

    # Filter by status
    filtered = client.get("/api/v1/tasks", params={"status": "waiting_review"})
    assert filtered.status_code == 200
    filtered_items = filtered.json()["data"]
    assert len(filtered_items) == 1
    assert filtered_items[0]["id"] == "task-board-2"
    assert filtered_items[0]["agent_name"] == "DeepResearcher"


def test_patch_task_state_valid_and_invalid_transitions_with_ws_broadcast(env):
    client, app, _ = env

    with app.state.session_factory() as db:
        db.add(
            Task(
                id="task-fsm-1",
                project_id="proj-default",
                title="FSM Board Task",
                status=TaskStatus.PENDING,
            )
        )
        db.commit()

    # Connect WebSocket to verify task_status broadcast
    with client.websocket_connect(
        "/ws/tasks/task-fsm-1?token=board-test-secret-token"
    ) as ws:
        connected_frame = ws.receive_json()
        assert connected_frame["event"] == "connected"

        # Valid transition: pending -> running
        r_ok = client.patch(
            "/api/v1/tasks/task-fsm-1/state",
            json={"target_state": "running", "actor": "user", "reason": "Bắt đầu chạy"},
        )
        assert r_ok.status_code == 200
        assert r_ok.json()["data"]["status"] == "running"

        ws_event = ws.receive_json()
        assert ws_event["event"] == "task_status"
        assert ws_event["task_id"] == "task-fsm-1"
        assert ws_event["status"] == "running"

    # Invalid transition: running -> pending must return 409 and NOT change DB status
    r_bad = client.patch(
        "/api/v1/tasks/task-fsm-1/state",
        json={"target_state": "pending", "actor": "user"},
    )
    assert r_bad.status_code == 409
    assert "Cannot transition task" in r_bad.json()["detail"]

    with app.state.session_factory() as db:
        task_in_db = db.get(Task, "task-fsm-1")
        assert task_in_db is not None
        assert task_in_db.status == TaskStatus.RUNNING


def test_get_task_logs_chronological_and_secret_masked(env):
    client, app, _ = env
    t0 = datetime(2026, 11, 12, 10, 0, 0, tzinfo=timezone.utc)

    with app.state.session_factory() as db:
        db.add(
            Task(
                id="task-logs-1",
                project_id="proj-default",
                title="Task With Logs",
                status=TaskStatus.RUNNING,
                assigned_agent_id="agent-content-writer",
            )
        )
        db.add(
            TaskAuditLog(
                id="audit-1",
                task_id="task-logs-1",
                from_status="pending",
                to_status="running",
                actor="user",
                reason="Start with token=board-test-secret-token",
                created_at=t0,
            )
        )
        db.add(
            TurnLog(
                id="turn-1",
                task_id="task-logs-1",
                agent_id="agent-content-writer",
                turn_number=1,
                action="generate_copy",
                tool="llm_router",
                input_payload={"prompt": "Bearer sk-proj-abc1234567890"},
                output_payload={
                    "summary": "Drafted post",
                    "steps": [
                        {"name": "Analyze brief", "status": "completed"},
                        {"name": "Draft hook", "status": "completed"},
                    ],
                },
                duration_ms=420,
                tokens=850,
                status="completed",
                created_at=t0 + timedelta(seconds=5),
            )
        )
        db.commit()

    # Non-existent task -> 404
    assert client.get("/api/v1/tasks/non-existent/logs").status_code == 404

    resp = client.get("/api/v1/tasks/task-logs-1/logs")
    assert resp.status_code == 200
    logs = resp.json()["data"]
    assert len(logs) == 2
    assert logs[0]["log_type"] == "audit"
    assert logs[0]["from_status"] == "pending"
    assert logs[0]["to_status"] == "running"
    assert "board-test-secret-token" not in (logs[0]["reason"] or "")

    assert logs[1]["log_type"] == "turn"
    assert logs[1]["agent_name"] == "ContentWriter"
    assert logs[1]["duration_ms"] == 420
    assert logs[1]["tokens"] == 850
    assert len(logs[1]["steps"]) == 2
    assert "sk-proj-abc1234567890" not in str(logs[1]["input_payload"])
    assert logs[1]["created_at"].endswith("+00:00")


def test_departments_endpoint_returns_agents_and_skill_counts(env):
    client, _, _ = env
    resp = client.get("/api/v1/departments")
    assert resp.status_code == 200
    depts = resp.json()["data"]
    content_dept = next(d for d in depts if d["id"] == "dept-content")
    assert "agents" in content_dept
    assert len(content_dept["agents"]) >= 3
    assert content_dept["created_at"].endswith("+00:00")
    first_agent = content_dept["agents"][0]
    assert "skills_count" in first_agent
    assert "status" in first_agent
    assert first_agent["created_at"].endswith("+00:00")


def test_project_blank_id_422_empty_dept_and_delete_conflict_409(env):
    client, app, _ = env

    # Blank whitespace id -> 422
    blank_resp = client.post(
        "/api/v1/projects",
        json={"id": "   ", "name": "Valid Name"},
    )
    assert blank_resp.status_code == 422

    # Empty default_department_id normalizes cleanly to None
    p_resp = client.post(
        "/api/v1/projects",
        json={"id": "  proj-clean-1  ", "name": "Clean Project", "defaultDepartmentId": "  "},
    )
    assert p_resp.status_code == 201
    created = p_resp.json()["data"]
    assert created["id"] == "proj-clean-1"
    assert created["default_department_id"] is None

    # Empty project can be deleted (200)
    p2_resp = client.post(
        "/api/v1/projects",
        json={"id": "proj-empty-del", "name": "Empty Project"},
    )
    assert p2_resp.status_code == 201
    del_ok = client.delete("/api/v1/projects/proj-empty-del")
    assert del_ok.status_code == 200
    assert del_ok.json()["data"]["deleted"] is True

    # Project with referencing tasks returns 409 Conflict on DELETE
    with app.state.session_factory() as db:
        db.add(
            Task(
                id="task-guard-1",
                project_id="proj-clean-1",
                title="Blocking task",
                status=TaskStatus.PENDING,
            )
        )
        db.commit()

    del_conflict = client.delete("/api/v1/projects/proj-clean-1")
    assert del_conflict.status_code == 409

    # Batched list_projects includes accurate task_count & status_summary
    list_resp = client.get("/api/v1/projects")
    assert list_resp.status_code == 200
    clean_item = next(p for p in list_resp.json()["data"] if p["id"] == "proj-clean-1")
    assert clean_item["task_count"] == 1
    assert clean_item["status_summary"]["pending"] == 1
