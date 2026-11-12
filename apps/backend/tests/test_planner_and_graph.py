"""Tests for DAG Planner, LangGraph SqliteSaver Orchestrator, and Crash Recovery (Task 2.1)."""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.db.models import Agent, SubTask, Task, TaskAuditLog, TaskStatus
from app.db.session import init_db, seed_defaults
from app.main import create_app
from app.orchestrator.graph import (
    OrchestratorGraph,
    _parse_review_decision,
    recover_interrupted_tasks,
)
from app.orchestrator.parser import TASK_TYPES, TaskParser
from app.orchestrator.planner import DagCycleError, DagPlanner, ExecutionPlan, SubTaskNode


@pytest.fixture
def db_session(tmp_path: Path):
    """Provide an isolated seeded SQLAlchemy session per test."""
    SessionLocal = init_db(tmp_path / "test.db")
    with SessionLocal() as session:
        seed_defaults(session)
        yield session


# --- 1. DAG Validation & Cycle Detection Tests ---


def test_dag_planner_rejects_cycles_and_caps_at_10_nodes():
    """Brief test: Reject cycles with DagCycleError and >10 nodes with ValueError."""
    cyclic_nodes = [
        SubTaskNode(id="a", agent_id="DeepResearcher", instruction="step 1", depends_on=["b"]),
        SubTaskNode(id="b", agent_id="ContentWriter", instruction="step 2", depends_on=["a"]),
    ]
    with pytest.raises(DagCycleError):
        DagPlanner.validate_dag(cyclic_nodes)

    # 3-node cycle
    tri_cycle = [
        SubTaskNode(id="n1", agent_id="DeepResearcher", instruction="1", depends_on=["n3"]),
        SubTaskNode(id="n2", agent_id="ContentWriter", instruction="2", depends_on=["n1"]),
        SubTaskNode(id="n3", agent_id="ImageStudio", instruction="3", depends_on=["n2"]),
    ]
    with pytest.raises(DagCycleError):
        DagPlanner.validate_dag(tri_cycle)

    # Self-loop
    self_loop = [
        SubTaskNode(id="loop", agent_id="Commander", instruction="self", depends_on=["loop"]),
    ]
    with pytest.raises(DagCycleError):
        DagPlanner.validate_dag(self_loop)

    # > 10 nodes rejected
    eleven_nodes = [
        SubTaskNode(
            id=f"n{i}",
            agent_id="ContentWriter",
            instruction=f"step {i}",
            depends_on=[f"n{i - 1}"] if i > 0 else [],
        )
        for i in range(11)
    ]
    with pytest.raises(ValueError, match="10"):
        DagPlanner.validate_dag(eleven_nodes)

    # Exactly 10 nodes allowed
    ten_nodes = eleven_nodes[:10]
    ordered = DagPlanner.validate_dag(ten_nodes)
    assert len(ordered) == 10


def test_dag_planner_rejects_unknown_dependencies_and_duplicate_ids():
    """Reject missing dependency targets and duplicate node IDs with ValueError."""
    unknown_dep = [
        SubTaskNode(id="a", agent_id="DeepResearcher", instruction="step 1", depends_on=["missing"]),
    ]
    with pytest.raises(ValueError, match="unknown"):
        DagPlanner.validate_dag(unknown_dep)

    duplicate_ids = [
        SubTaskNode(id="dup", agent_id="DeepResearcher", instruction="step 1"),
        SubTaskNode(id="dup", agent_id="ContentWriter", instruction="step 2"),
    ]
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        DagPlanner.validate_dag(duplicate_ids)


def test_dag_planner_topological_order_and_waves():
    """Kahn's topological sort orders dependencies before dependents and computes parallel waves."""
    nodes = [
        SubTaskNode(id="d", agent_id="ReportAgent", instruction="compile", depends_on=["b", "c"]),
        SubTaskNode(id="c", agent_id="ImageStudio", instruction="design", depends_on=["a"]),
        SubTaskNode(id="b", agent_id="ContentWriter", instruction="write", depends_on=["a"]),
        SubTaskNode(id="a", agent_id="DeepResearcher", instruction="research", depends_on=[]),
    ]
    ordered = DagPlanner.validate_dag(nodes)
    ordered_ids = [n.id for n in ordered]
    assert ordered_ids.index("a") < ordered_ids.index("b")
    assert ordered_ids.index("a") < ordered_ids.index("c")
    assert ordered_ids.index("b") < ordered_ids.index("d")
    assert ordered_ids.index("c") < ordered_ids.index("d")

    waves = DagPlanner.compute_waves(ordered)
    assert len(waves) == 3
    assert waves[0] == ["a"]
    assert set(waves[1]) == {"b", "c"}
    assert waves[2] == ["d"]


# --- 2. DagPlanner.build_plan Tests ---


@pytest.mark.parametrize("task_type", TASK_TYPES)
def test_build_plan_across_all_task_types(db_session, task_type: str):
    """Build valid, cycle-free <=10-node ExecutionPlans for every supported task_type."""
    agents = db_session.query(Agent).all()
    parser = TaskParser()
    prompt_by_type = {
        "content_research": "Nghiên cứu 3 kênh YouTube đối thủ",
        "copywriting": "Viết kịch bản video TikTok 60 giây",
        "image_design": "Thiết kế banner 1200x630 cho chiến dịch",
        "video_edit": "Dựng video ngắn TikTok 30s cắt ghép ffmpeg",
        "funnel_strategy": "Xây dựng chiến lược phễu bán hàng đa tầng",
        "landing_page": "Tạo giao diện landing page HTML responsive",
        "sales_chat": "Soạn kịch bản tư vấn bán hàng và xử lý từ chối Zalo",
        "general": "Lập kế hoạch công việc tuần tới cho team",
    }
    intent = parser.parse(
        prompt_by_type[task_type],
        known_agents=[a.name for a in agents],
        record_history=False,
    )
    # Force exact task_type if heuristic picked differently
    intent.task_type = task_type

    plan_auto = DagPlanner.build_plan(intent, agents, task_id=f"t-{task_type}", mode="autopilot")
    assert isinstance(plan_auto, ExecutionPlan)
    assert plan_auto.task_id == f"t-{task_type}"
    assert plan_auto.task_type == task_type
    assert 1 <= len(plan_auto.nodes) <= 10
    assert sum(len(w) for w in plan_auto.waves) == len(plan_auto.nodes)
    assert all(not n.requires_review for n in plan_auto.nodes)
    DagPlanner.validate_dag(plan_auto.nodes)

    plan_copilot = DagPlanner.build_plan(intent, agents, task_id=f"t-{task_type}-co", mode="copilot")
    assert any(n.requires_review for n in plan_copilot.nodes)


def test_build_plan_respects_mentions_and_handles_empty_or_partial_agents(db_session):
    """Mentioned agents are assigned in the DAG, and empty/partial agent lists do not crash."""
    agents = db_session.query(Agent).all()
    parser = TaskParser()
    intent = parser.parse(
        "@DeepResearcher @UIDesigner tạo trang báo cáo HTML về xu hướng AI",
        known_agents=[a.name for a in agents],
        record_history=False,
    )

    plan = DagPlanner.build_plan(intent, agents, task_id="t-mentions", mode="autopilot")
    assigned_ids = {n.agent_id for n in plan.nodes}
    assert "agent-deep-researcher" in assigned_ids
    assert "agent-ui-designer" in assigned_ids

    # Partial agents list (only 1 agent)
    partial_plan = DagPlanner.build_plan(intent, [agents[0]], task_id="t-partial")
    assert 1 <= len(partial_plan.nodes) <= 10
    DagPlanner.validate_dag(partial_plan.nodes)

    # Empty agents list
    empty_plan = DagPlanner.build_plan(intent, [], task_id="t-empty")
    assert 1 <= len(empty_plan.nodes) <= 10
    DagPlanner.validate_dag(empty_plan.nodes)


# --- 3. OrchestratorGraph & SqliteSaver Checkpoint / HIL Tests ---


def test_orchestrator_graph_autopilot_full_run(tmp_path: Path):
    """Autopilot ExecutionPlan runs all waves to completion and persists checkpoints."""
    cp_db = tmp_path / "checkpoints.db"
    nodes = [
        SubTaskNode(id="step1", agent_id="DeepResearcher", instruction="Research", depends_on=[]),
        SubTaskNode(id="step2a", agent_id="ContentWriter", instruction="Write", depends_on=["step1"]),
        SubTaskNode(id="step2b", agent_id="ImageStudio", instruction="Design", depends_on=["step1"]),
        SubTaskNode(id="step3", agent_id="ReportAgent", instruction="Bundle", depends_on=["step2a", "step2b"]),
    ]
    ordered = DagPlanner.validate_dag(nodes)
    waves = DagPlanner.compute_waves(ordered)
    plan = ExecutionPlan(
        task_id="task-auto-1",
        task_type="content_research",
        nodes=ordered,
        waves=waves,
        mode="autopilot",
    )

    executed_order: list[str] = []

    def executor(node: dict, state: dict) -> dict:
        executed_order.append(node["id"])
        return {"summary": f"done:{node['id']}"}

    with OrchestratorGraph(checkpoint_db_path=cp_db, node_executor=executor) as graph:
        result = graph.run(plan, thread_id="thread-auto-1")
        assert "__interrupt__" not in result
        assert result["status"] == "completed"
        assert set(result["completed_nodes"]) == {"step1", "step2a", "step2b", "step3"}
        assert executed_order[0] == "step1"
        assert executed_order[-1] == "step3"
        assert not graph.is_interrupted("thread-auto-1")
        snapshot = graph.get_state("thread-auto-1")
        assert snapshot.next == ()

    assert cp_db.exists()


def test_orchestrator_graph_hil_interrupt_and_resume_across_instances(tmp_path: Path):
    """HIL interrupt() pauses execution in checkpoints.db and resumes on a brand-new instance."""
    cp_db = tmp_path / "checkpoints.db"
    nodes = [
        SubTaskNode(
            id="draft",
            agent_id="ContentWriter",
            instruction="Draft storyboard",
            depends_on=[],
            requires_review=True,
        ),
        SubTaskNode(
            id="render",
            agent_id="VideoEditor",
            instruction="Render final video",
            depends_on=["draft"],
            requires_review=False,
        ),
    ]
    ordered = DagPlanner.validate_dag(nodes)
    plan = ExecutionPlan(
        task_id="task-hil-1",
        task_type="video_edit",
        nodes=ordered,
        waves=DagPlanner.compute_waves(ordered),
        mode="copilot",
    )

    exec_counts: dict[str, int] = {}

    def executor_1(node: dict, state: dict) -> dict:
        exec_counts[node["id"]] = exec_counts.get(node["id"], 0) + 1
        return {"artifact": f"{node['id']}.md"}

    g1 = OrchestratorGraph(checkpoint_db_path=cp_db, node_executor=executor_1)
    try:
        paused = g1.run(plan, thread_id="thread-hil-1")
        assert "__interrupt__" in paused
        assert g1.is_interrupted("thread-hil-1") is True
        assert exec_counts == {"draft": 1}
        assert paused["completed_nodes"] == ["draft"]
    finally:
        g1.close()

    # Brand-new OrchestratorGraph instance reading the exact same checkpoints.db
    def executor_2(node: dict, state: dict) -> dict:
        exec_counts[node["id"]] = exec_counts.get(node["id"], 0) + 1
        return {"artifact": f"{node['id']}.mp4"}

    g2 = OrchestratorGraph(checkpoint_db_path=cp_db, node_executor=executor_2)
    try:
        assert g2.is_interrupted("thread-hil-1") is True
        resumed = g2.resume(
            thread_id="thread-hil-1",
            decision={"approved": True, "feedback": "Storyboard approved"},
        )
        assert "__interrupt__" not in resumed
        assert resumed["status"] == "completed"
        assert resumed["completed_nodes"] == ["draft", "render"]
        # Draft was NOT re-executed after resume; only render executed in g2
        assert exec_counts == {"draft": 1, "render": 1}
        assert g2.is_interrupted("thread-hil-1") is False
        assert g2.get_state("thread-hil-1").next == ()
    finally:
        g2.close()


def test_orchestrator_graph_hil_rejection_stops_downstream(tmp_path: Path):
    """Rejecting at HIL review gate records rejection and skips downstream waves."""
    cp_db = tmp_path / "checkpoints.db"
    nodes = [
        SubTaskNode(id="w1", agent_id="ContentWriter", instruction="Draft", requires_review=True),
        SubTaskNode(id="w2", agent_id="UIDesigner", instruction="Build", depends_on=["w1"]),
    ]
    plan = ExecutionPlan(
        task_id="task-hil-reject",
        task_type="landing_page",
        nodes=nodes,
        waves=[["w1"], ["w2"]],
        mode="copilot",
    )

    executed: list[str] = []
    with OrchestratorGraph(
        checkpoint_db_path=cp_db,
        node_executor=lambda n, s: executed.append(n["id"]) or {"ok": True},
    ) as graph:
        paused = graph.run(plan, thread_id="thread-reject-1")
        assert "__interrupt__" in paused
        assert executed == ["w1"]

        resumed = graph.resume(
            thread_id="thread-reject-1",
            decision={"approved": False, "feedback": "Change tone of voice"},
        )
        assert resumed["status"] == "rejected"
        assert executed == ["w1"]  # w2 must not execute
        assert resumed["review_decisions"]["0"]["feedback"] == "Change tone of voice"


# --- 4. Crash Recovery & FastAPI Lifespan Tests ---


def test_recover_interrupted_tasks_on_startup(db_session):
    """Brief test: Orphaned RUNNING tasks move to PAUSED with audit log on recovery."""
    db_session.add(
        Task(id="t-orphan", project_id="proj-default", title="Orphan", status=TaskStatus.RUNNING)
    )
    db_session.add(
        SubTask(id="st-orphan", task_id="t-orphan", title="Step 1", status="running")
    )
    db_session.add(
        Task(id="t-pending", project_id="proj-default", title="Pending", status=TaskStatus.PENDING)
    )
    db_session.add(
        Task(id="t-review", project_id="proj-default", title="Review", status=TaskStatus.WAITING_REVIEW)
    )
    db_session.add(
        Task(id="t-done", project_id="proj-default", title="Done", status=TaskStatus.COMPLETED)
    )
    db_session.commit()

    recovered = recover_interrupted_tasks(db_session)
    assert recovered == 1

    orphan = db_session.get(Task, "t-orphan")
    assert orphan is not None
    assert orphan.status == TaskStatus.PAUSED

    sub = db_session.get(SubTask, "st-orphan")
    assert sub is not None
    assert sub.status == "paused"

    audit = (
        db_session.query(TaskAuditLog)
        .filter_by(task_id="t-orphan", to_status="paused")
        .first()
    )
    assert audit is not None
    assert audit.from_status == "running"
    assert audit.actor == "system"
    assert audit.reason == "crash_recovery"

    # Unrelated tasks untouched
    assert db_session.get(Task, "t-pending").status == TaskStatus.PENDING
    assert db_session.get(Task, "t-review").status == TaskStatus.WAITING_REVIEW
    assert db_session.get(Task, "t-done").status == TaskStatus.COMPLETED


def test_fastapi_lifespan_recovers_interrupted_tasks_on_startup(tmp_path: Path):
    """FastAPI lifespan hook runs crash recovery on startup without breaking non-context TestClient."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="tok-life")
    SessionLocal = init_db(settings.resolved_db_path)
    with SessionLocal() as db:
        seed_defaults(db)
        db.add(
            Task(
                id="t-crash-boot",
                project_id="proj-default",
                title="Crashed before restart",
                status=TaskStatus.RUNNING,
            )
        )
        db.commit()

    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/v1/health", headers={"X-Local-Auth-Token": "tok-life"})
        assert resp.status_code == 200
        assert client.app.state.recovered_tasks_count == 1

    with SessionLocal() as db:
        recovered_task = db.get(Task, "t-crash-boot")
        assert recovered_task is not None
        assert recovered_task.status == TaskStatus.PAUSED
        audit = db.query(TaskAuditLog).filter_by(task_id="t-crash-boot").first()
        assert audit is not None
        assert audit.actor == "system"
        assert audit.reason == "crash_recovery"


# --- 5. Fix Round 1/5 Regression Tests ---


def test_build_plan_preserves_evicted_template_agent_when_also_mentioned(db_session):
    """[IMP-2] When @UIDesigner evicts DeepResearcher on nodes[0], @DeepResearcher is still included."""
    agents = db_session.query(Agent).all()
    parser = TaskParser()
    intent = parser.parse(
        "@UIDesigner @DeepResearcher viết bài phân tích trang đích",
        known_agents=[a.name for a in agents],
        record_history=False,
    )
    intent.task_type = "copywriting"

    plan = DagPlanner.build_plan(intent, agents, task_id="t-evict", mode=" COPILOT ")
    assert plan.mode == "copilot"
    assigned_ids = {n.agent_id for n in plan.nodes}
    assert "agent-ui-designer" in assigned_ids
    assert "agent-deep-researcher" in assigned_ids
    assert "agent-content-writer" in assigned_ids
    DagPlanner.validate_dag(plan.nodes)

    with pytest.raises(ValueError, match="Invalid mode"):
        DagPlanner.build_plan(intent, agents, task_id="t-bad-mode", mode="invalid_mode")


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"decision": " reject "}, False),
        ({"decision": "maybe"}, False),
        ({"approved": "false"}, False),
        ({"approved": "0"}, False),
        ({"approved": "maybe"}, False),
        ({"approved": 1}, False),
        ({}, False),
        ("maybe", False),
        (" reject ", False),
        (False, False),
        (None, False),
        ("approve", True),
        (" YES ", True),
        ({"decision": " approved "}, True),
        ({"approved": "true"}, True),
        ({"approved": True}, True),
        (True, True),
    ],
)
def test_parse_review_decision_strict_fail_closed(payload, expected: bool):
    """[IMP-1] HIL review decision parsing fails closed on ambiguous/reject inputs."""
    approved, record = _parse_review_decision(payload)
    assert approved is expected
    assert record["approved"] is expected


def test_orchestrator_graph_resume_guards_multi_wave_hil_and_closed_check(tmp_path: Path):
    """[IMP-3] Guard resume() on nonexistent/completed threads, handle 2+ HIL gates, and guard close()."""
    cp_db = tmp_path / "checkpoints.db"
    nodes = [
        SubTaskNode(id="w1", agent_id="DeepResearcher", instruction="Research", requires_review=True),
        SubTaskNode(id="w2", agent_id="ContentWriter", instruction="Draft", depends_on=["w1"], requires_review=True),
        SubTaskNode(id="w3", agent_id="ReportAgent", instruction="Deliver", depends_on=["w2"], requires_review=False),
    ]
    ordered = DagPlanner.validate_dag(nodes)
    plan = ExecutionPlan(
        task_id="task-multi-hil",
        task_type="content_research",
        nodes=ordered,
        waves=DagPlanner.compute_waves(ordered),
        mode="copilot",
    )

    executed: list[str] = []
    graph = OrchestratorGraph(
        checkpoint_db_path=cp_db,
        node_executor=lambda n, s: executed.append(n["id"]) or {"ok": n["id"]},
    )

    # Nonexistent thread raises ValueError
    with pytest.raises(ValueError, match="not currently interrupted"):
        graph.resume("nonexistent-thread", True)

    # Wave 1 hits first HIL gate
    p1 = graph.run(plan, thread_id="thread-multi-1")
    assert "__interrupt__" in p1
    assert executed == ["w1"]
    assert graph.is_interrupted("thread-multi-1") is True

    # Resume wave 1 -> runs wave 2 -> hits second HIL gate
    p2 = graph.resume("thread-multi-1", {"approved": True, "note": "w1 ok"})
    assert "__interrupt__" in p2
    assert executed == ["w1", "w2"]
    assert graph.is_interrupted("thread-multi-1") is True

    # Resume wave 2 -> runs wave 3 -> completes
    p3 = graph.resume("thread-multi-1", {"approved": True, "note": "w2 ok"})
    assert "__interrupt__" not in p3
    assert p3["status"] == "completed"
    assert executed == ["w1", "w2", "w3"]
    assert graph.is_interrupted("thread-multi-1") is False

    # Already-completed thread raises ValueError and does not re-run final wave
    with pytest.raises(ValueError, match="not currently interrupted"):
        graph.resume("thread-multi-1", True)
    assert executed == ["w1", "w2", "w3"]

    # Closed connection guards
    graph.close()
    graph.close()  # idempotent
    with pytest.raises(RuntimeError, match="closed"):
        graph.run(plan, thread_id="thread-after-close")
    with pytest.raises(RuntimeError, match="closed"):
        graph.resume("thread-multi-1", True)
    with pytest.raises(RuntimeError, match="closed"):
        graph.get_state("thread-multi-1")
    with pytest.raises(RuntimeError, match="closed"):
        graph.is_interrupted("thread-multi-1")


def test_recover_interrupted_tasks_waiting_review_subtasks_and_rollback(db_session, monkeypatch):
    """[IMP-4] Pause waiting_review subtasks and roll back cleanly if transition() raises."""
    db_session.add(
        Task(id="t-wr-sub", project_id="proj-default", title="With WR Subtask", status=TaskStatus.RUNNING)
    )
    db_session.add(
        SubTask(id="st-wr", task_id="t-wr-sub", title="Gate step", status="waiting_review")
    )
    db_session.commit()

    # First verify rollback when TaskStateMachine.transition fails mid-recovery
    def failing_transition(*args, **kwargs):
        raise RuntimeError("simulated transition failure")

    monkeypatch.setattr("app.orchestrator.graph.TaskStateMachine.transition", failing_transition)
    with pytest.raises(RuntimeError, match="simulated transition failure"):
        recover_interrupted_tasks(db_session)

    # SubTask must still be waiting_review (uncommitted mutation rolled back)
    db_session.expire_all()
    assert db_session.get(SubTask, "st-wr").status == "waiting_review"
    assert db_session.get(Task, "t-wr-sub").status == TaskStatus.RUNNING

    # Restore real transition and verify waiting_review subtask moves to paused
    monkeypatch.undo()
    recovered = recover_interrupted_tasks(db_session)
    assert recovered == 1
    assert db_session.get(Task, "t-wr-sub").status == TaskStatus.PAUSED
    assert db_session.get(SubTask, "st-wr").status == "paused"
