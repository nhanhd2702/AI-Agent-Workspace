"""Tests for Agent Registry & Department Management API (F02).

Covers:
- Brief tests: duplicate name -> 409, cannot delete busy or system agent -> 400.
- Full CRUD for Agent and Department entities.
- System prompt length limit (<= 4000) and name syntax validation.
- Skill attachment (idempotent, 0..20 limit) and detachment (both route variants).
- Model configuration routing and parameter validation (temperature, max_tokens).
- Department deletion safety check (blocked when containing agents).
- Auth token enforcement on /api/v1/agents and /api/v1/departments.
"""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.db.models import Agent, AgentSkill, Department, Skill, Task, SubTask, TaskStatus
from app.db.session import init_db
from app.main import create_app


@pytest.fixture
def client_with_db(tmp_path: Path) -> TestClient:
    """Fixture providing initialized FastAPI test client with seeded database and auth header."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="test-secret-token")
    app = create_app(settings)
    client = TestClient(app, headers={"X-Local-Auth-Token": "test-secret-token"})
    client.app_settings = settings  # type: ignore[attr-defined]
    return client


# --- 1. Brief Specific Tests ---

def test_duplicate_agent_name_returns_409(client_with_db: TestClient):
    """From brief: duplicate agent name must return 409 Conflict."""
    payload = {
        "name": "ContentWriter",
        "display_name": "Dup",
        "description": "Test",
        "role": "Writer",
        "department_id": "dept-content",
        "system_prompt": "Prompt",
    }
    resp = client_with_db.post("/api/v1/agents", json=payload)
    assert resp.status_code == 409
    body = resp.json()
    assert "detail" in body
    assert "ContentWriter" in body["detail"]


def test_cannot_delete_busy_or_system_agent(client_with_db: TestClient):
    """From brief: system agent (e.g. agent-commander) cannot be deleted (400 Bad Request)."""
    assert client_with_db.delete("/api/v1/agents/agent-commander").status_code == 400


# --- 2. Auth Enforcement Tests ---

def test_agents_and_departments_require_auth(tmp_path: Path):
    """Endpoints under /api/v1/agents and /api/v1/departments reject unauthenticated requests with 401."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="auth-required-token")
    client = TestClient(create_app(settings))

    # Without token
    assert client.get("/api/v1/agents").status_code == 401
    assert client.get("/api/v1/departments").status_code == 401

    # With invalid token
    bad_headers = {"X-Local-Auth-Token": "wrong-token"}
    assert client.get("/api/v1/agents", headers=bad_headers).status_code == 401
    assert client.get("/api/v1/departments", headers=bad_headers).status_code == 401


# --- 3. Agent CRUD Operations ---

def test_create_and_get_agent(client_with_db: TestClient):
    """Create a new custom agent and retrieve it by ID and in list."""
    payload = {
        "name": "TikTokScriptAgent",
        "display_name": "Chuyên gia Kịch bản TikTok",
        "description": "Chuyển hóa bài viết thành kịch bản video 60s chuẩn hook 3 giây đầu",
        "role": "Sáng tạo nội dung ngắn",
        "department_id": "dept-content",
        "primary_model": "gemini-2.5-flash",
        "fallback_model": "claude-3-5-sonnet",
        "system_prompt": "Bạn là chuyên gia biên kịch video ngắn.",
        "temperature": 0.8,
        "max_tokens": 2048,
    }
    resp = client_with_db.post("/api/v1/agents", json=payload)
    assert resp.status_code == 201
    res_data = resp.json()
    assert res_data["status"] == "success"
    agent_data = res_data["data"]
    assert agent_data["name"] == "TikTokScriptAgent"
    assert agent_data["display_name"] == "Chuyên gia Kịch bản TikTok"
    assert agent_data["department_id"] == "dept-content"
    assert agent_data["default_model"] == "gemini-2.5-flash"
    assert agent_data["fallback_model"] == "claude-3-5-sonnet"
    assert agent_data["temperature"] == 0.8
    assert agent_data["max_tokens"] == 2048
    assert agent_data["is_system"] is False
    assert agent_data["skills_count"] == 0

    agent_id = agent_data["id"]

    # GET by ID
    get_resp = client_with_db.get(f"/api/v1/agents/{agent_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["id"] == agent_id

    # GET list
    list_resp = client_with_db.get("/api/v1/agents")
    assert list_resp.status_code == 200
    all_agents = list_resp.json()["data"]
    # 12 seeded + 1 created = 13
    assert len(all_agents) == 13
    assert any(a["id"] == agent_id for a in all_agents)


def test_list_agents_filtering(client_with_db: TestClient):
    """Filter agents by department_id and status."""
    # Filter by department_id
    resp_dept = client_with_db.get("/api/v1/agents?department_id=dept-content")
    assert resp_dept.status_code == 200
    content_agents = resp_dept.json()["data"]
    assert len(content_agents) >= 3
    assert all(a["department_id"] == "dept-content" for a in content_agents)

    # Filter by status
    resp_status = client_with_db.get("/api/v1/agents?status=idle")
    assert resp_status.status_code == 200
    idle_agents = resp_status.json()["data"]
    assert len(idle_agents) >= 12


def test_update_agent_fields(client_with_db: TestClient):
    """Update agent metadata and configurations."""
    update_payload = {
        "display_name": "Content Writer Pro",
        "description": "Updated description",
        "temperature": 0.5,
    }
    resp = client_with_db.put("/api/v1/agents/agent-content-writer", json=update_payload)
    assert resp.status_code == 200
    updated = resp.json()["data"]
    assert updated["display_name"] == "Content Writer Pro"
    assert updated["description"] == "Updated description"
    assert updated["temperature"] == 0.5

    # Update name to duplicate -> 409
    dup_resp = client_with_db.put("/api/v1/agents/agent-content-writer", json={"name": "Commander"})
    assert dup_resp.status_code == 409


def test_delete_custom_agent_success(client_with_db: TestClient):
    """Create a non-system agent and delete it successfully."""
    create_resp = client_with_db.post(
        "/api/v1/agents",
        json={
            "name": "TemporaryAgent",
            "display_name": "Temp Agent",
            "role": "Tester",
            "department_id": "dept-office",
        },
    )
    assert create_resp.status_code == 201
    temp_id = create_resp.json()["data"]["id"]

    # Delete
    del_resp = client_with_db.delete(f"/api/v1/agents/{temp_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "success"

    # Confirm 404 on subsequent get
    assert client_with_db.get(f"/api/v1/agents/{temp_id}").status_code == 404


# --- 4. Validation & Constraint Handling ---

def test_system_prompt_over_4000_chars_rejected(client_with_db: TestClient):
    """System prompt exceeding 4000 chars is rejected with 422."""
    payload = {
        "name": "LongPromptAgent",
        "display_name": "Long Prompt Agent",
        "role": "Tester",
        "system_prompt": "A" * 4001,
    }
    resp = client_with_db.post("/api/v1/agents", json=payload)
    assert resp.status_code == 422


def test_agent_invalid_department_returns_404(client_with_db: TestClient):
    """Specifying nonexistent department_id returns 404."""
    payload = {
        "name": "InvalidDeptAgent",
        "display_name": "Invalid Dept Agent",
        "role": "Tester",
        "department_id": "dept-nonexistent",
    }
    resp = client_with_db.post("/api/v1/agents", json=payload)
    assert resp.status_code == 404
    assert "dept-nonexistent" in resp.json()["detail"]


def test_agent_name_syntax_validation(client_with_db: TestClient):
    """Agent name with invalid characters (spaces, hyphens, symbols) is rejected with 422."""
    payload = {
        "name": "Invalid Name With Spaces",
        "display_name": "Invalid Name",
        "role": "Tester",
    }
    resp = client_with_db.post("/api/v1/agents", json=payload)
    assert resp.status_code == 422


# --- 5. Busy Agent Deletion Safety ---

def test_cannot_delete_agent_with_running_task(client_with_db: TestClient):
    """Agent assigned to a running Task cannot be deleted (400 Bad Request)."""
    # Create an agent
    create_resp = client_with_db.post(
        "/api/v1/agents",
        json={"name": "BusyWorker1", "display_name": "Busy Worker 1", "role": "Worker"},
    )
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["data"]["id"]

    # Directly create a running task in DB
    settings: AppSettings = client_with_db.app_settings  # type: ignore[attr-defined]
    SessionLocal = init_db(settings.resolved_db_path)
    with SessionLocal() as db:
        task = Task(
            id="task-busy-01",
            project_id="proj-default",
            title="Active Task",
            status=TaskStatus.RUNNING,
            assigned_agent_id=agent_id,
        )
        db.add(task)
        db.commit()

    # Attempt deletion -> should fail with 400
    del_resp = client_with_db.delete(f"/api/v1/agents/{agent_id}")
    assert del_resp.status_code == 400
    assert "task-busy-01" in del_resp.json()["detail"]

    # Mark task as completed
    with SessionLocal() as db:
        t = db.get(Task, "task-busy-01")
        t.status = TaskStatus.COMPLETED
        db.commit()

    # Now deletion must succeed
    assert client_with_db.delete(f"/api/v1/agents/{agent_id}").status_code == 200


def test_cannot_delete_agent_with_waiting_review_subtask(client_with_db: TestClient):
    """Agent assigned to a waiting_review SubTask cannot be deleted (400 Bad Request)."""
    create_resp = client_with_db.post(
        "/api/v1/agents",
        json={"name": "BusyWorker2", "display_name": "Busy Worker 2", "role": "Worker"},
    )
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["data"]["id"]

    settings: AppSettings = client_with_db.app_settings  # type: ignore[attr-defined]
    SessionLocal = init_db(settings.resolved_db_path)
    with SessionLocal() as db:
        task = Task(
            id="task-master-02",
            project_id="proj-default",
            title="Master Task",
            status=TaskStatus.PENDING,
        )
        db.add(task)
        db.flush()

        subtask = SubTask(
            id="subtask-busy-02",
            task_id="task-master-02",
            agent_id=agent_id,
            title="SubTask waiting review",
            status="waiting_review",
        )
        db.add(subtask)
        db.commit()

    del_resp = client_with_db.delete(f"/api/v1/agents/{agent_id}")
    assert del_resp.status_code == 400
    assert "subtask-busy-02" in del_resp.json()["detail"]


# --- 6. Model Configuration Routing ---

def test_agent_model_config_update(client_with_db: TestClient):
    """PUT /api/v1/agents/{id}/model-config updates model routing and hyperparameters."""
    payload = {
        "primary_model": "gpt-4o",
        "fallback_model": "claude-3-5-sonnet",
        "temperature": 0.3,
        "max_tokens": 8192,
    }
    resp = client_with_db.put("/api/v1/agents/agent-content-writer/model-config", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["default_model"] == "gpt-4o"
    assert data["fallback_model"] == "claude-3-5-sonnet"
    assert data["temperature"] == 0.3
    assert data["max_tokens"] == 8192


def test_agent_model_config_validation(client_with_db: TestClient):
    """Invalid temperature (> 2.0 or < 0.0) or invalid max_tokens (< 1) returns 422."""
    bad_temp = {"temperature": 2.5}
    assert client_with_db.put("/api/v1/agents/agent-content-writer/model-config", json=bad_temp).status_code == 422

    bad_tokens = {"max_tokens": 0}
    assert client_with_db.put("/api/v1/agents/agent-content-writer/model-config", json=bad_tokens).status_code == 422


# --- 7. Skills Attachment & Detachment ---

def test_skills_attach_idempotent_and_detach(client_with_db: TestClient):
    """Attach skill to agent idempotently, then detach via both path and body variants."""
    settings: AppSettings = client_with_db.app_settings  # type: ignore[attr-defined]
    SessionLocal = init_db(settings.resolved_db_path)
    with SessionLocal() as db:
        db.add(Skill(id="skill-test-01", name="TestSkill1", description="Test skill 1"))
        db.add(Skill(id="skill-test-02", name="TestSkill2", description="Test skill 2"))
        db.commit()

    # Attach skill 1
    attach_resp = client_with_db.post(
        "/api/v1/agents/agent-content-writer/skills",
        json={"skill_id": "skill-test-01", "custom_params": {"level": "advanced"}},
    )
    assert attach_resp.status_code == 200
    assert attach_resp.json()["status"] == "success"

    # Attach same skill again (Idempotent 200)
    attach_dup_resp = client_with_db.post(
        "/api/v1/agents/agent-content-writer/skills",
        json={"skill_id": "skill-test-01"},
    )
    assert attach_dup_resp.status_code == 200

    # Attach skill 2 via query param
    attach_q_resp = client_with_db.post(
        "/api/v1/agents/agent-content-writer/skills?skill_id=skill-test-02"
    )
    assert attach_q_resp.status_code == 200

    # Check agent skills count
    agent_info = client_with_db.get("/api/v1/agents/agent-content-writer").json()["data"]
    assert agent_info["skills_count"] == 2
    assert "skill-test-01" in agent_info["skill_ids"]
    assert "skill-test-02" in agent_info["skill_ids"]

    # Detach skill 1 via DELETE /api/v1/agents/{id}/skills/{skill_id}
    del_skill_resp = client_with_db.delete("/api/v1/agents/agent-content-writer/skills/skill-test-01")
    assert del_skill_resp.status_code == 200
    assert del_skill_resp.json()["status"] == "success"

    # Detach skill 2 via DELETE /api/v1/agents/{id}/skills with JSON body
    del_skill2_resp = client_with_db.request(
        "DELETE",
        "/api/v1/agents/agent-content-writer/skills",
        json={"skill_id": "skill-test-02"},
    )
    assert del_skill2_resp.status_code == 200

    # Also test query parameter variant of DELETE /api/v1/agents/{id}/skills?skill_id=...
    # Attach skill 2 again
    client_with_db.post("/api/v1/agents/agent-content-writer/skills?skill_id=skill-test-02")
    # Detach via query param
    del_skill2_q_resp = client_with_db.delete(
        "/api/v1/agents/agent-content-writer/skills?skill_id=skill-test-02"
    )
    assert del_skill2_q_resp.status_code == 200

    # Verify both detached
    agent_info_after = client_with_db.get("/api/v1/agents/agent-content-writer").json()["data"]
    assert agent_info_after["skills_count"] == 0


def test_skills_max_20_limit_enforced(client_with_db: TestClient):
    """Enforce rule: agent cannot have more than 20 skills."""
    settings: AppSettings = client_with_db.app_settings  # type: ignore[attr-defined]
    SessionLocal = init_db(settings.resolved_db_path)
    with SessionLocal() as db:
        for i in range(25):
            db.add(Skill(id=f"skill-limit-{i:02d}", name=f"SkillLimit{i:02d}"))
        db.commit()

    # Attach 20 skills
    for i in range(20):
        resp = client_with_db.post(
            "/api/v1/agents/agent-deep-researcher/skills",
            json={"skill_id": f"skill-limit-{i:02d}"},
        )
        assert resp.status_code == 200

    # 21st skill should fail with 400 Bad Request
    overflow_resp = client_with_db.post(
        "/api/v1/agents/agent-deep-researcher/skills",
        json={"skill_id": "skill-limit-20"},
    )
    assert overflow_resp.status_code == 400
    assert "20" in overflow_resp.json()["detail"]


def test_attach_missing_skill_returns_404(client_with_db: TestClient):
    """Attaching nonexistent skill returns 404."""
    resp = client_with_db.post(
        "/api/v1/agents/agent-content-writer/skills",
        json={"skill_id": "skill-nonexistent"},
    )
    assert resp.status_code == 404


# --- 8. Department CRUD & Isolation ---

def test_departments_crud_and_safety(client_with_db: TestClient):
    """Test Department CRUD, name conflict (409), and deletion blocking when containing agents."""
    # 1. List departments (5 seeded)
    list_resp = client_with_db.get("/api/v1/departments")
    assert list_resp.status_code == 200
    depts = list_resp.json()["data"]
    assert len(depts) == 5

    # 2. Create new department
    create_payload = {
        "name": "Đội Mobile App",
        "description": "Phát triển ứng dụng di động",
        "icon": "smartphone",
        "color": "#10B981",
    }
    create_resp = client_with_db.post("/api/v1/departments", json=create_payload)
    assert create_resp.status_code == 201
    created_dept = create_resp.json()["data"]
    dept_id = created_dept["id"]
    assert created_dept["name"] == "Đội Mobile App"

    # 3. Duplicate department name -> 409
    dup_resp = client_with_db.post("/api/v1/departments", json=create_payload)
    assert dup_resp.status_code == 409

    # 4. Get by ID
    get_resp = client_with_db.get(f"/api/v1/departments/{dept_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["name"] == "Đội Mobile App"

    # 5. Update department
    update_resp = client_with_db.put(
        f"/api/v1/departments/{dept_id}",
        json={"description": "Mô tả mới cập nhật", "color": "#059669"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["data"]["description"] == "Mô tả mới cập nhật"

    # 6. Delete empty department -> 200 OK
    del_resp = client_with_db.delete(f"/api/v1/departments/{dept_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "success"

    # Subsequent GET -> 404
    assert client_with_db.get(f"/api/v1/departments/{dept_id}").status_code == 404

    # 7. Block deletion of department containing agents
    # dept-content contains ContentWriter, ImageStudio, VideoEditor
    block_del = client_with_db.delete("/api/v1/departments/dept-content")
    assert block_del.status_code == 400
    assert "agent" in block_del.json()["detail"].lower()
