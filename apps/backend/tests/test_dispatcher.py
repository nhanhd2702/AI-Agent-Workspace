"""Tests for AgentDispatcher, BaseWorkerAgent, Secret Masking, and WebSocket Streaming (Task 2.3)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.agents.base import BaseWorkerAgent, WorkerResult
from app.config import AppSettings
from app.db.models import (
    Agent,
    AgentSkill,
    Project,
    Skill,
    SubTask,
    Task,
    TaskStatus,
    TurnLog,
)
from app.db.session import init_db, seed_defaults
from app.llm.router import LlmRouter, MockProviderRegistry
from app.main import create_app
from app.orchestrator.dispatcher import (
    AgentDispatcher,
    DispatchResult,
    mask_secrets,
)
from app.orchestrator.planner import ExecutionPlan, SubTaskNode


@pytest.fixture
def db_env(tmp_path: Path):
    """Provide an isolated seeded SQLite sessionmaker and initial session."""
    db_path = tmp_path / "test_dispatcher.db"
    factory = init_db(db_path, cache=False)
    with factory() as session:
        seed_defaults(session)
    return factory, tmp_path


def _create_task(factory, task_id: str = "task-1", mode: str = "autopilot") -> Task:
    with factory() as session:
        task = Task(
            id=task_id,
            project_id="proj-default",
            title="Test Dispatch Task",
            description="Execute a multi-step test workflow",
            status=TaskStatus.PENDING,
            task_metadata={"mode": mode, "task_type": "general"},
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return task


# ============================================================================
# 1. Brief Test: Max 3 Parallel Workers Semaphore
# ============================================================================


@pytest.mark.asyncio
async def test_dispatcher_enforces_max_3_parallel_workers():
    """Brief Step 1 test: 6 parallel items must never exceed 3 active workers."""
    active_peak = 0
    current = 0

    async def fake_worker(sub_task):
        nonlocal active_peak, current
        current += 1
        active_peak = max(active_peak, current)
        await asyncio.sleep(0.05)
        current -= 1
        return {"subtask": sub_task, "ok": True}

    dispatcher = AgentDispatcher(max_parallel=3, worker_fn=fake_worker)
    results = await dispatcher.run_batch([f"st-{i}" for i in range(6)])
    assert active_peak <= 3
    assert active_peak >= 2
    assert len(results) == 6


# ============================================================================
# 2. Per-Agent FIFO Queue Serialization + Cross-Agent Parallelism
# ============================================================================


@pytest.mark.asyncio
async def test_dispatcher_serializes_same_agent_fifo_while_other_agents_run_parallel():
    """Tasks sharing an agent_id execute strictly FIFO sequentially; different agents run concurrently."""
    agent_a_active = 0
    agent_a_peak = 0
    agent_a_order: list[str] = []
    global_active = 0
    global_peak = 0

    async def fake_worker(node: SubTaskNode):
        nonlocal agent_a_active, agent_a_peak, global_active, global_peak
        global_active += 1
        global_peak = max(global_peak, global_active)
        if node.agent_id == "agent-content-writer":
            agent_a_active += 1
            agent_a_peak = max(agent_a_peak, agent_a_active)
            agent_a_order.append(f"start:{node.id}")
            await asyncio.sleep(0.04)
            agent_a_order.append(f"end:{node.id}")
            agent_a_active -= 1
        else:
            await asyncio.sleep(0.04)
        global_active -= 1
        return {"output": f"done-{node.id}"}

    nodes = [
        SubTaskNode(id="a1", agent_id="agent-content-writer", instruction="first"),
        SubTaskNode(id="a2", agent_id="agent-content-writer", instruction="second"),
        SubTaskNode(id="a3", agent_id="agent-content-writer", instruction="third"),
        SubTaskNode(id="b1", agent_id="agent-deep-researcher", instruction="other 1"),
        SubTaskNode(id="c1", agent_id="agent-image-studio", instruction="other 2"),
    ]
    dispatcher = AgentDispatcher(max_parallel=3, worker_fn=fake_worker)
    await dispatcher.run_batch(nodes)

    # Same agent never ran concurrently
    assert agent_a_peak == 1
    # Strict FIFO completion order for agent-content-writer
    assert agent_a_order == [
        "start:a1",
        "end:a1",
        "start:a2",
        "end:a2",
        "start:a3",
        "end:a3",
    ]
    # Different agents still ran concurrently (up to 3)
    assert global_peak >= 2
    assert global_peak <= 3


# ============================================================================
# 3. Wave-by-Wave DAG Execution, DB Persistence, and TurnLogs
# ============================================================================


@pytest.mark.asyncio
async def test_dispatch_executes_waves_updates_db_and_records_turn_logs(db_env):
    """Wave 0 must finish before Wave 1; SubTask, Task, and TurnLog rows are persisted."""
    factory, _ = db_env
    _create_task(factory, task_id="task-dag-1")

    execution_log: list[str] = []

    async def wave_worker(node: SubTaskNode, context: dict[str, Any]):
        execution_log.append(node.id)
        if node.id == "step_final":
            assert "step_a" in context["dependency_outputs"]
            assert "step_b" in context["dependency_outputs"]
        await asyncio.sleep(0.01)
        return WorkerResult(
            subtask_id=node.id,
            agent_id=node.agent_id,
            status="completed",
            content=f"Output for {node.id}",
            model_used="gemini-2.5-flash",
            tokens=120,
            input_tokens=80,
            output_tokens=40,
        )

    nodes = [
        SubTaskNode(id="step_a", agent_id="agent-deep-researcher", instruction="research"),
        SubTaskNode(id="step_b", agent_id="agent-product-analyst", instruction="analyze"),
        SubTaskNode(
            id="step_final",
            agent_id="agent-report-agent",
            instruction="synthesize",
            depends_on=["step_a", "step_b"],
        ),
    ]
    plan = ExecutionPlan(
        task_id="task-dag-1",
        task_type="content_research",
        nodes=nodes,
        waves=[["step_a", "step_b"], ["step_final"]],
        mode="autopilot",
    )

    dispatcher = AgentDispatcher(
        max_parallel=3,
        worker_fn=wave_worker,
        session_factory=factory,
    )
    result = await dispatcher.dispatch(task_id="task-dag-1", plan=plan)

    assert isinstance(result, DispatchResult)
    assert result.status == "completed"
    assert set(result.completed_nodes) == {"step_a", "step_b", "step_final"}
    assert result.failed_nodes == []
    # Wave 0 ran before Wave 1
    assert execution_log.index("step_final") > execution_log.index("step_a")
    assert execution_log.index("step_final") > execution_log.index("step_b")

    with factory() as session:
        task = session.get(Task, "task-dag-1")
        assert task is not None
        assert task.status == TaskStatus.COMPLETED

        subtasks = session.query(SubTask).filter_by(task_id="task-dag-1").all()
        assert len(subtasks) == 3
        assert all(st.status == "completed" for st in subtasks)

        turns = (
            session.query(TurnLog)
            .filter_by(task_id="task-dag-1")
            .order_by(TurnLog.turn_number.asc())
            .all()
        )
        assert len(turns) == 3
        assert [t.turn_number for t in turns] == [1, 2, 3]
        assert all(t.status == "completed" for t in turns)
        assert all(t.tokens == 120 for t in turns)


@pytest.mark.asyncio
async def test_dispatch_pauses_at_waiting_review_in_copilot_mode(db_env):
    """When a node has requires_review=True, dispatch transitions task to WAITING_REVIEW."""
    factory, _ = db_env
    _create_task(factory, task_id="task-hil-1", mode="copilot")

    async def ok_worker(node: SubTaskNode, context: dict[str, Any]):
        return WorkerResult(
            subtask_id=node.id,
            agent_id=node.agent_id,
            status="completed",
            content=f"Done {node.id}",
            tokens=50,
        )

    nodes = [
        SubTaskNode(
            id="draft",
            agent_id="agent-content-writer",
            instruction="write draft",
            requires_review=True,
        ),
        SubTaskNode(
            id="publish",
            agent_id="agent-report-agent",
            instruction="finalize",
            depends_on=["draft"],
        ),
    ]
    plan = ExecutionPlan(
        task_id="task-hil-1",
        task_type="copywriting",
        nodes=nodes,
        waves=[["draft"], ["publish"]],
        mode="copilot",
    )

    dispatcher = AgentDispatcher(max_parallel=3, worker_fn=ok_worker, session_factory=factory)
    result = await dispatcher.dispatch(task_id="task-hil-1", plan=plan)

    assert result.status == "waiting_review"
    assert result.completed_nodes == ["draft"]

    with factory() as session:
        task = session.get(Task, "task-hil-1")
        assert task is not None
        assert task.status == TaskStatus.WAITING_REVIEW


# ============================================================================
# 4. Per-Subtask Timeout Enforcement
# ============================================================================


@pytest.mark.asyncio
async def test_dispatcher_enforces_subtask_timeout_and_releases_semaphore(db_env):
    """Sleeping worker exceeds timeout_seconds, fails cleanly, and releases concurrency slots."""
    factory, _ = db_env
    _create_task(factory, task_id="task-timeout-1")

    async def slow_worker(node: SubTaskNode, context: dict[str, Any]):
        await asyncio.sleep(0.5)
        return {"output": "never reached"}

    nodes = [
        SubTaskNode(id="slow_1", agent_id="agent-content-writer", instruction="sleep"),
        SubTaskNode(id="after_1", agent_id="agent-report-agent", instruction="next", depends_on=["slow_1"]),
    ]
    plan = ExecutionPlan(
        task_id="task-timeout-1",
        task_type="general",
        nodes=nodes,
        waves=[["slow_1"], ["after_1"]],
        mode="autopilot",
    )

    dispatcher = AgentDispatcher(
        max_parallel=1,
        worker_fn=slow_worker,
        timeout_seconds=0.05,
        session_factory=factory,
    )
    result = await dispatcher.dispatch(task_id="task-timeout-1", plan=plan)

    assert result.status == "failed"
    assert "slow_1" in result.failed_nodes
    assert "timeout" in result.errors["slow_1"].lower() or "timed out" in result.errors["slow_1"].lower()
    # Downstream node should not execute after upstream failure
    assert "after_1" not in result.completed_nodes
    # Semaphore slot must have been cleanly released
    assert dispatcher._semaphore._value == 1  # noqa: SLF001

    with factory() as session:
        task = session.get(Task, "task-timeout-1")
        assert task is not None
        assert task.status == TaskStatus.FAILED
        turns = session.query(TurnLog).filter_by(task_id="task-timeout-1").all()
        assert len(turns) == 1
        assert turns[0].status == "timeout"


# ============================================================================
# 5. BaseWorkerAgent & Lazy Skill Loading + Path Traversal Protection
# ============================================================================


@pytest.mark.asyncio
async def test_base_worker_agent_lazy_skill_loading_and_path_traversal(db_env):
    """Skills are NOT loaded on init; loaded only when invoked; traversal paths are rejected."""
    factory, tmp_path = db_env
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    seo_dir = skills_dir / "seo-copy"
    seo_dir.mkdir()
    seo_file = seo_dir / "SKILL.md"
    seo_file.write_text("# SEO Copy Skill\nAlways include strong H1 hooks.", encoding="utf-8")

    # Sensitive file outside allowed skills_dir
    outside_secret = tmp_path / "secret.txt"
    outside_secret.write_text("TOP_SECRET_DATA", encoding="utf-8")

    with factory() as session:
        agent = session.get(Agent, "agent-content-writer")
        assert agent is not None

        skill_ok = Skill(
            id="skill-seo-copy",
            name="seo-copy",
            description="SEO copywriting skill",
            file_path=str(seo_file),
        )
        skill_missing = Skill(
            id="skill-optional",
            name="optional-skill",
            description="Optional fallback description",
            file_path=str(skills_dir / "missing" / "SKILL.md"),
        )
        skill_traversal_rel = Skill(
            id="skill-evil-rel",
            name="evil-rel",
            file_path="../../secret.txt",
        )
        skill_traversal_abs = Skill(
            id="skill-evil-abs",
            name="evil-abs",
            file_path=str(outside_secret),
        )
        session.add_all([skill_ok, skill_missing, skill_traversal_rel, skill_traversal_abs])
        session.flush()
        session.add(
            AgentSkill(
                id="as-1",
                agent_id=agent.id,
                skill_id="skill-seo-copy",
                is_active=True,
            )
        )
        session.commit()
        session.refresh(agent)

    providers = MockProviderRegistry()
    router = LlmRouter(providers=providers)

    with factory() as session:
        agent = session.get(Agent, "agent-content-writer")
        worker = BaseWorkerAgent(
            agent=agent,
            llm_router=router,
            session_factory=factory,
            allowed_skill_dirs=[skills_dir],
        )

        # Lazy guarantee: zero skills loaded at initialization
        assert worker.loaded_skills == {}

        # Path traversal must be rejected cleanly
        with pytest.raises(ValueError, match="traversal|outside|allowed"):
            worker.load_skill("skill-evil-rel", db=session)
        with pytest.raises(ValueError, match="traversal|outside|allowed"):
            worker.load_skill("skill-evil-abs", db=session)

        # Missing optional SKILL.md returns clean fallback text
        fallback_txt = worker.load_skill("skill-optional", db=session)
        assert "Optional fallback description" in fallback_txt

    # Executing a subtask requesting skill-seo-copy triggers lazy load and injects it into LLM prompt
    subtask = SubTaskNode(
        id="write-1",
        agent_id="agent-content-writer",
        instruction="Write a landing headline",
        metadata={"skill_ids": ["skill-seo-copy"]},
    )
    res = await worker.execute(subtask, context={"task_id": "task-none"})
    assert res.status == "completed"
    assert "skill-seo-copy" in res.skills_loaded
    assert "skill-seo-copy" in worker.loaded_skills
    assert len(providers.calls) == 1
    sent_messages = providers.calls[0]["messages"]
    combined_prompt = " ".join(m["content"] for m in sent_messages)
    assert "Always include strong H1 hooks." in combined_prompt


# ============================================================================
# 6. Secret Masking in TurnLogs and WebSocket Payloads
# ============================================================================


def test_mask_secrets_redacts_api_keys_and_tokens():
    """mask_secrets redacts OpenAI/Gemini/Bearer/Slack/GitHub tokens recursively."""
    raw = {
        "api_key": "super-secret-val",
        "prompt": "Use key sk-proj-abc1234567890xyz and AIzaSyD1234567890abcdef",
        "headers": {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"},
        "nested": [
            "ghp_1234567890abcdefghijklmnop",
            "xoxb-12345-67890-abcdef",
            "password=my_secret_pw",
        ],
        "tokens": 150,  # numeric token count must NOT be corrupted
    }
    masked = mask_secrets(raw)
    serialized = str(masked)
    assert "super-secret-val" not in serialized
    assert "sk-proj-abc1234567890xyz" not in serialized
    assert "AIzaSyD1234567890abcdef" not in serialized
    assert "eyJhbGciOiJIUzI1NiJ9.payload.sig" not in serialized
    assert "ghp_1234567890abcdefghijklmnop" not in serialized
    assert "xoxb-12345-67890-abcdef" not in serialized
    assert "my_secret_pw" not in serialized
    assert masked["tokens"] == 150


@pytest.mark.asyncio
async def test_dispatcher_masks_secrets_in_turn_logs_and_ws_broadcast(db_env):
    """Sensitive credentials in worker inputs/outputs are masked in DB TurnLogs and WS broadcasts."""
    factory, _ = db_env
    _create_task(factory, task_id="task-mask-1")

    captured_events: list[dict[str, Any]] = []

    class FakeWsManager:
        async def broadcast(self, task_id: str, event: dict[str, Any]) -> None:
            captured_events.append({"task_id": task_id, "event": event})

    async def leaky_worker(node: SubTaskNode, context: dict[str, Any]):
        return WorkerResult(
            subtask_id=node.id,
            agent_id=node.agent_id,
            status="completed",
            content="Leaked sk-test1234567890secret and AIzaSySecretKey123456789",
            tokens=42,
        )

    plan = ExecutionPlan(
        task_id="task-mask-1",
        task_type="general",
        nodes=[
            SubTaskNode(
                id="n1",
                agent_id="agent-commander",
                instruction="Call API with Bearer secret_token_xyz123",
            )
        ],
        waves=[["n1"]],
    )

    dispatcher = AgentDispatcher(
        max_parallel=3,
        worker_fn=leaky_worker,
        session_factory=factory,
        ws_manager=FakeWsManager(),
    )
    await dispatcher.dispatch(task_id="task-mask-1", plan=plan)

    # Check DB TurnLog
    with factory() as session:
        turns = session.query(TurnLog).filter_by(task_id="task-mask-1").all()
        assert len(turns) == 1
        turn = turns[0]
        assert "secret_token_xyz123" not in str(turn.input_payload)
        assert "sk-test1234567890secret" not in str(turn.output_payload)
        assert "AIzaSySecretKey123456789" not in str(turn.output_payload)

    # Check WS broadcast events
    assert len(captured_events) >= 3  # task_status running, turn_started, turn_completed, task_status completed
    all_ws_str = str(captured_events)
    assert "secret_token_xyz123" not in all_ws_str
    assert "sk-test1234567890secret" not in all_ws_str
    assert "AIzaSySecretKey123456789" not in all_ws_str


# ============================================================================
# 7. WebSocket Endpoint Auth & Real-time Streaming + Tasks Dispatch API
# ============================================================================


def test_websocket_rejects_unauthorized_and_accepts_authorized(tmp_path: Path):
    """WS /ws/tasks/{id} rejects missing/bad token with 1008 and accepts header or query token."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="ws-secret-999")
    app = create_app(settings)
    client = TestClient(app)

    # 1. Missing token rejected with 1008
    with pytest.raises(WebSocketDisconnect) as missing_exc:
        with client.websocket_connect("/ws/tasks/task-ws-1"):
            pass
    assert missing_exc.value.code == 1008

    # 2. Invalid query token rejected with 1008
    with pytest.raises(WebSocketDisconnect) as bad_exc:
        with client.websocket_connect("/ws/tasks/task-ws-1?token=wrong-token"):
            pass
    assert bad_exc.value.code == 1008

    # 3. Valid query token accepted
    with client.websocket_connect("/ws/tasks/task-ws-1?token=ws-secret-999") as ws:
        msg = ws.receive_json()
        assert msg["event"] == "connected"
        assert msg["task_id"] == "task-ws-1"

    # 4. Valid header token accepted
    with client.websocket_connect(
        "/ws/tasks/task-ws-1",
        headers={"X-Local-Auth-Token": "ws-secret-999"},
    ) as ws:
        msg = ws.receive_json()
        assert msg["event"] == "connected"
        assert msg["task_id"] == "task-ws-1"


@pytest.mark.asyncio
async def test_websocket_receives_live_turn_events_during_dispatch(tmp_path: Path):
    """Connected WebSocket client receives real-time turn_started/turn_completed/task_status events."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="ws-live-token")
    app = create_app(settings)
    client = TestClient(app)

    factory = app.state.session_factory
    _create_task(factory, task_id="task-live-ws")

    plan = ExecutionPlan(
        task_id="task-live-ws",
        task_type="general",
        nodes=[SubTaskNode(id="step1", agent_id="agent-commander", instruction="Hello WS")],
        waves=[["step1"]],
    )

    with client.websocket_connect("/ws/tasks/task-live-ws?token=ws-live-token") as ws:
        initial = ws.receive_json()
        assert initial["event"] == "connected"

        dispatcher = AgentDispatcher(
            max_parallel=3,
            session_factory=factory,
            ws_manager=app.state.ws_manager,
            llm_router=LlmRouter(providers=MockProviderRegistry()),
        )
        result = await dispatcher.dispatch(task_id="task-live-ws", plan=plan)
        assert result.status == "completed"

        events = []
        for _ in range(4):
            events.append(ws.receive_json())

        event_names = [e["event"] for e in events]
        assert "turn_started" in event_names
        assert "turn_completed" in event_names
        assert any(
            e["event"] == "task_status" and e["status"] == "completed" for e in events
        )


def test_tasks_dispatch_and_turns_api_endpoints(tmp_path: Path):
    """POST /api/v1/tasks/{id}/dispatch and GET /api/v1/tasks/{id}/turns enforce auth, 404, and 200."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="api-token-123")
    app = create_app(settings)
    client = TestClient(app)
    headers = {"X-Local-Auth-Token": "api-token-123"}

    # 401 without token
    assert client.post("/api/v1/tasks/missing/dispatch").status_code == 401
    assert client.get("/api/v1/tasks/missing/turns").status_code == 401

    # 404 for unknown task
    assert client.post("/api/v1/tasks/missing/dispatch", headers=headers).status_code == 404
    assert client.get("/api/v1/tasks/missing/turns", headers=headers).status_code == 404
    assert client.get("/api/v1/tasks/missing", headers=headers).status_code == 404

    # Create task via /api/v1/tasks/parse
    parse_resp = client.post(
        "/api/v1/tasks/parse",
        headers=headers,
        json={
            "projectId": "proj-default",
            "promptText": "@ContentWriter viết bài giới thiệu sản phẩm AI mới",
            "mode": "autopilot",
        },
    )
    assert parse_resp.status_code == 200
    task_id = parse_resp.json()["data"]["task_id"]

    # Dispatch task
    dispatch_resp = client.post(
        f"/api/v1/tasks/{task_id}/dispatch",
        headers=headers,
    )
    assert dispatch_resp.status_code == 200
    body = dispatch_resp.json()["data"]
    assert body["task_id"] == task_id
    assert body["status"] == "completed"
    assert len(body["completed_nodes"]) >= 1

    # List turns
    turns_resp = client.get(f"/api/v1/tasks/{task_id}/turns", headers=headers)
    assert turns_resp.status_code == 200
    turns = turns_resp.json()["data"]
    assert len(turns) == len(body["completed_nodes"])
    assert turns[0]["task_id"] == task_id
    assert turns[0]["status"] == "completed"

    # Get task details
    task_resp = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert task_resp.status_code == 200
    task_data = task_resp.json()["data"]
    assert task_data["id"] == task_id
    assert task_data["status"] == "completed"
    assert task_data["turn_count"] == len(turns)

    # Re-dispatching a completed task returns 409 Conflict
    redispatch_resp = client.post(f"/api/v1/tasks/{task_id}/dispatch", headers=headers)
    assert redispatch_resp.status_code == 409

    # Dispatching with a cyclic custom DAG returns 422
    parse_resp2 = client.post(
        "/api/v1/tasks/parse",
        headers=headers,
        json={"projectId": "proj-default", "promptText": "Test cyclic validation"},
    )
    task_id2 = parse_resp2.json()["data"]["task_id"]
    cyclic_resp = client.post(
        f"/api/v1/tasks/{task_id2}/dispatch",
        headers=headers,
        json={
            "nodes": [
                {"id": "a", "agentId": "agent-commander", "instruction": "1", "dependsOn": ["b"]},
                {"id": "b", "agentId": "agent-report-agent", "instruction": "2", "dependsOn": ["a"]},
            ]
        },
    )
    assert cyclic_resp.status_code == 422


@pytest.mark.asyncio
async def test_ws_manager_prunes_dead_connections_without_crashing_healthy_clients():
    """Dead sockets failing on send_json are pruned while healthy clients continue receiving."""
    from app.api.ws import TaskWebSocketManager

    manager = TaskWebSocketManager()

    class DeadWebSocket:
        async def accept(self) -> None:
            pass

        async def send_json(self, data: Any) -> None:
            raise RuntimeError("socket closed")

    class HealthyWebSocket:
        def __init__(self) -> None:
            self.received: list[Any] = []

        async def accept(self) -> None:
            pass

        async def send_json(self, data: Any) -> None:
            self.received.append(data)

    dead = DeadWebSocket()
    healthy = HealthyWebSocket()

    await manager.connect("task-prune", dead)  # type: ignore[arg-type]
    await manager.connect("task-prune", healthy)  # type: ignore[arg-type]
    assert manager.active_count("task-prune") == 2

    await manager.broadcast("task-prune", {"event": "turn_started", "api_key": "sk-1234567890abcd"})
    assert manager.active_count("task-prune") == 1
    assert len(healthy.received) == 1
    assert "sk-1234567890abcd" not in str(healthy.received[0])


@pytest.mark.asyncio
async def test_parallel_default_workers_with_llm_router_and_sqlite_concurrency(db_env):
    """4 parallel subtasks across different agents execute safely against SQLite via BaseWorkerAgent."""
    from app.db.models import UsageRecord

    factory, _ = db_env
    _create_task(factory, task_id="task-parallel-llm")

    providers = MockProviderRegistry()
    router = LlmRouter(providers=providers)

    nodes = [
        SubTaskNode(id="p1", agent_id="agent-deep-researcher", instruction="Research 1"),
        SubTaskNode(id="p2", agent_id="agent-content-writer", instruction="Write 2"),
        SubTaskNode(id="p3", agent_id="agent-image-studio", instruction="Design 3"),
        SubTaskNode(id="p4", agent_id="agent-product-analyst", instruction="Analyze 4"),
    ]
    plan = ExecutionPlan(
        task_id="task-parallel-llm",
        task_type="general",
        nodes=nodes,
        waves=[["p1", "p2", "p3", "p4"]],
        mode="autopilot",
    )

    dispatcher = AgentDispatcher(
        max_parallel=3,
        session_factory=factory,
        llm_router=router,
    )
    result = await dispatcher.dispatch(task_id="task-parallel-llm", plan=plan)

    assert result.status == "completed"
    assert len(result.completed_nodes) == 4
    assert len(providers.calls) == 4

    with factory() as session:
        turns = session.query(TurnLog).filter_by(task_id="task-parallel-llm").all()
        usages = session.query(UsageRecord).filter_by(task_id="task-parallel-llm").all()
        assert len(turns) == 4
        assert len(usages) == 4


def test_dispatch_allows_failed_retry_and_blocks_running_with_409(tmp_path: Path):
    """FAILED tasks can be re-dispatched cleanly to COMPLETED; RUNNING tasks return 409 Conflict."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="retry-tok-123")
    app = create_app(settings)
    client = TestClient(app)
    headers = {"X-Local-Auth-Token": "retry-tok-123"}
    factory = app.state.session_factory

    with factory() as session:
        session.add(
            Task(
                id="task-failed-retry",
                project_id="proj-default",
                title="Failed Task",
                description="Retry after failure",
                status=TaskStatus.FAILED,
                task_metadata={"mode": "autopilot", "task_type": "general"},
            )
        )
        session.add(
            Task(
                id="task-running-conflict",
                project_id="proj-default",
                title="Running Task",
                description="Already executing",
                status=TaskStatus.RUNNING,
                task_metadata={"mode": "autopilot", "task_type": "general"},
            )
        )
        session.commit()

    # 1. Re-dispatching FAILED task succeeds (200) and transitions to COMPLETED
    retry_resp = client.post("/api/v1/tasks/task-failed-retry/dispatch", headers=headers)
    assert retry_resp.status_code == 200
    assert retry_resp.json()["data"]["status"] == "completed"

    with factory() as session:
        retried = session.get(Task, "task-failed-retry")
        assert retried is not None
        assert retried.status == TaskStatus.COMPLETED

    # 2. Dispatching RUNNING task is rejected with 409 Conflict
    running_resp = client.post("/api/v1/tasks/task-running-conflict/dispatch", headers=headers)
    assert running_resp.status_code == 409


@pytest.mark.asyncio
async def test_dispatcher_raises_conflict_on_running_and_handles_approved_retry(db_env):
    """AgentDispatcher rejects RUNNING with TaskDispatchConflictError and transitions APPROVED -> COMPLETED."""
    from app.orchestrator.dispatcher import TaskDispatchConflictError

    factory, _ = db_env
    with factory() as session:
        session.add(
            Task(
                id="t-run-atomic",
                project_id="proj-default",
                title="Running",
                status=TaskStatus.RUNNING,
            )
        )
        session.add(
            Task(
                id="t-approved-run",
                project_id="proj-default",
                title="Approved",
                status=TaskStatus.APPROVED,
            )
        )
        session.commit()

    worker_called = False

    async def tracked_worker(node: SubTaskNode, context: dict[str, Any]):
        nonlocal worker_called
        worker_called = True
        return {"content": "ok"}

    dispatcher = AgentDispatcher(max_parallel=3, worker_fn=tracked_worker, session_factory=factory)

    plan_running = ExecutionPlan(
        task_id="t-run-atomic",
        task_type="general",
        nodes=[SubTaskNode(id="n1", agent_id="agent-commander", instruction="noop")],
        waves=[["n1"]],
    )
    with pytest.raises(TaskDispatchConflictError):
        await dispatcher.dispatch(task_id="t-run-atomic", plan=plan_running)
    assert worker_called is False

    plan_approved = ExecutionPlan(
        task_id="t-approved-run",
        task_type="general",
        nodes=[SubTaskNode(id="n1", agent_id="agent-commander", instruction="deliver")],
        waves=[["n1"]],
    )
    res = await dispatcher.dispatch(task_id="t-approved-run", plan=plan_approved)
    assert res.status == "completed"
    assert worker_called is True


def test_mask_secrets_hardened_patterns_and_runtime_token():
    """mask_secrets redacts JSON secret strings, X-Local-Auth-Token headers, bytes, quoted Bearer, and extra_secrets."""
    payload = {
        "json_blob": '{"api_key": "secret-12345", "local_auth_token": "tok-999", "note": "safe"}',
        "header_str": "X-Local-Auth-Token: dev-local-token",
        "quoted_bearer": 'Authorization: Bearer "eyJhbGciOiJIUzI1NiJ9.abc.xyz"',
        "raw_bytes": b"token_bytes_here",
        "secret": b"raw-secret-bytes",
        "bare_runtime": "leaked my-custom-runtime-token-777 inside text",
    }
    masked = mask_secrets(payload, extra_secrets=["my-custom-runtime-token-777"])
    assert "secret-12345" not in masked["json_blob"]
    assert "tok-999" not in masked["json_blob"]
    assert '"note": "safe"' in masked["json_blob"]
    assert "dev-local-token" not in masked["header_str"]
    assert "eyJhbGciOiJIUzI1NiJ9.abc.xyz" not in masked["quoted_bearer"]
    assert masked["secret"] == "***REDACTED***"
    assert "my-custom-runtime-token-777" not in masked["bare_runtime"]


@pytest.mark.asyncio
async def test_dispatcher_normalizes_agent_name_and_id_to_same_fifo_lock():
    """'ContentWriter' and 'agent-content-writer' must share the exact same FIFO asyncio.Lock."""
    active = 0
    peak = 0
    order: list[str] = []

    async def worker(node: SubTaskNode):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        order.append(f"start:{node.id}")
        await asyncio.sleep(0.03)
        order.append(f"end:{node.id}")
        active -= 1
        return {"ok": True}

    nodes = [
        SubTaskNode(id="n1", agent_id="ContentWriter", instruction="first"),
        SubTaskNode(id="n2", agent_id="agent-content-writer", instruction="second"),
    ]
    dispatcher = AgentDispatcher(max_parallel=3, worker_fn=worker)
    await dispatcher.run_batch(nodes)

    assert peak == 1
    assert order == ["start:n1", "end:n1", "start:n2", "end:n2"]


def test_websocket_loads_most_recent_20_turns_in_chronological_order(tmp_path: Path):
    """WS initial snapshot returns the latest 20 turns (6..25) in ascending turn_number order."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="ws-recent-tok")
    app = create_app(settings)
    factory = app.state.session_factory

    with factory() as session:
        session.add(
            Task(
                id="task-many-turns",
                project_id="proj-default",
                title="Many turns",
                status=TaskStatus.RUNNING,
            )
        )
        session.flush()
        for i in range(1, 26):
            session.add(
                TurnLog(
                    id=f"turn-{i}",
                    task_id="task-many-turns",
                    turn_number=i,
                    action="execute_subtask",
                    tool="worker_agent",
                    input_payload={"step": i, "secret": "ws-recent-tok"},
                    output_payload={"ok": True},
                    status="completed",
                )
            )
        session.commit()

    client = TestClient(app)
    with client.websocket_connect("/ws/tasks/task-many-turns?token=ws-recent-tok") as ws:
        msg = ws.receive_json()
        assert msg["event"] == "connected"
        turns = msg["recent_turns"]
        assert len(turns) == 20
        assert [t["turn_number"] for t in turns] == list(range(6, 26))
        assert "ws-recent-tok" not in str(turns)


def test_dispatch_explicit_mode_overrides_existing_plan_mode(tmp_path: Path):
    """Explicit mode='copilot' on POST /dispatch overrides stored plan.mode='autopilot'."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="mode-override-tok")
    app = create_app(settings)
    client = TestClient(app)
    headers = {"X-Local-Auth-Token": "mode-override-tok"}

    parse_resp = client.post(
        "/api/v1/tasks/parse",
        headers=headers,
        json={
            "projectId": "proj-default",
            "promptText": "Viết bài giới thiệu sản phẩm",
            "mode": "autopilot",
        },
    )
    assert parse_resp.status_code == 200
    task_id = parse_resp.json()["data"]["task_id"]

    # Seed stored plan with mode='autopilot' but one node having requires_review=False
    factory = app.state.session_factory
    with factory() as session:
        task = session.get(Task, task_id)
        assert task is not None
        meta = dict(task.task_metadata or {})
        meta["plan"] = {
            "task_id": task_id,
            "task_type": "general",
            "mode": "autopilot",
            "nodes": [
                {
                    "id": "step1",
                    "agent_id": "agent-commander",
                    "instruction": "Do work",
                    "depends_on": [],
                    "requires_review": False,
                    "metadata": {},
                }
            ],
            "waves": [["step1"]],
        }
        task.task_metadata = meta
        session.commit()

    resp = client.post(
        f"/api/v1/tasks/{task_id}/dispatch",
        headers=headers,
        json={"mode": "copilot"},
    )
    assert resp.status_code == 200
    with factory() as session:
        task = session.get(Task, task_id)
        assert task is not None
        assert task.task_metadata is not None
        assert task.task_metadata["plan"]["mode"] == "copilot"


