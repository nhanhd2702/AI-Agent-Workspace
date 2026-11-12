"""Tests for SQLite database schema, 12-agent seeding, and Task finite state machine (FSM)."""

import pytest
from datetime import datetime, timezone
import concurrent.futures
import threading
from app.db.session import init_db, seed_defaults, get_db, reset_db_cache
from app.db.models import (
    Base,
    Project,
    Department,
    Agent,
    Skill,
    AgentSkill,
    Task,
    SubTask,
    TurnLog,
    Artifact,
    ReviewGate,
    UsageRecord,
    BrandProfile,
    Product,
    Conversation,
    Message,
    ConnectorConfig,
    UserSettings,
    TaskAuditLog,
    TaskStatus,
)
from app.db.state_machine import TaskStateMachine, InvalidStateTransitionError


EXPECTED_AGENTS = [
    ("Commander", "Master Commander & Orchestrator", "dept-office", True),
    ("DeepResearcher", "Deep Research Specialist", "dept-rd", False),
    ("ContentWriter", "Content Copywriter", "dept-content", False),
    ("ImageStudio", "Visual & Image Designer", "dept-content", False),
    ("VideoEditor", "Video Production Specialist", "dept-content", False),
    ("FunnelsAgent", "Funnels Strategist", "dept-funnels", False),
    ("GrowthAdvisor", "Growth & Pricing Advisor", "dept-funnels", False),
    ("UIDesigner", "UI/UX Landing Page Designer", "dept-funnels", False),
    ("SalesAgent", "Sales Consultant", "dept-ecommerce", False),
    ("CustomerSupportAgent", "Support Specialist", "dept-ecommerce", False),
    ("ReportAgent", "Reporting Specialist", "dept-office", False),
    ("ProductAnalyst", "Product Analyst", "dept-ecommerce", False),
]

EXPECTED_DEPARTMENTS = [
    ("dept-content", "Đội Content"),
    ("dept-funnels", "Đội Funnels"),
    ("dept-rd", "Nghiên cứu & Phát triển"),
    ("dept-ecommerce", "Thương mại điện tử"),
    ("dept-office", "Văn phòng"),
]


def test_seed_creates_12_agents_and_5_departments(tmp_path):
    """Seed should create 12 core agents and 5 standard departments."""
    SessionLocal = init_db(tmp_path / "app.db")
    with SessionLocal() as db:
        seed_defaults(db)
        assert db.query(Agent).count() == 12
        assert db.query(Department).count() == 5
        assert db.query(Project).filter_by(id="proj-default").count() == 1


def test_seed_is_idempotent(tmp_path):
    """Calling seed_defaults repeatedly must not duplicate rows or crash."""
    SessionLocal = init_db(tmp_path / "app.db")
    with SessionLocal() as db:
        seed_defaults(db)
        # Second call
        seed_defaults(db)
        # Third call
        seed_defaults(db)
        assert db.query(Agent).count() == 12
        assert db.query(Department).count() == 5
        assert db.query(Project).filter_by(id="proj-default").count() == 1


def test_all_12_agents_slugs_and_roles(tmp_path):
    """Verify all 12 agents have correct names, roles, departments and system flag."""
    SessionLocal = init_db(tmp_path / "app.db")
    with SessionLocal() as db:
        seed_defaults(db)
        for name, role, dept_id, is_sys in EXPECTED_AGENTS:
            agent = db.query(Agent).filter_by(name=name).first()
            assert agent is not None, f"Agent '{name}' not found"
            assert agent.role == role
            assert agent.department_id == dept_id
            assert agent.is_system == is_sys
            assert agent.display_name is not None
            assert len(agent.display_name) > 0


def test_fsm_rejects_invalid_jump_from_pending_to_completed(tmp_path):
    """Task cannot jump directly from PENDING to COMPLETED."""
    SessionLocal = init_db(tmp_path / "app.db")
    with SessionLocal() as db:
        seed_defaults(db)
        task = Task(id="t1", project_id="proj-default", title="Test", status=TaskStatus.PENDING)
        db.add(task)
        db.commit()
        with pytest.raises(InvalidStateTransitionError):
            TaskStateMachine.transition(db, "t1", TaskStatus.COMPLETED, actor="user")


def test_fsm_valid_full_lifecycle_and_audit_logging(tmp_path):
    """Valid lifecycle: PENDING -> RUNNING -> WAITING_REVIEW -> APPROVED -> DELIVERED -> COMPLETED."""
    SessionLocal = init_db(tmp_path / "app.db")
    with SessionLocal() as db:
        seed_defaults(db)
        task = Task(id="t_flow", project_id="proj-default", title="Lifecycle Flow", status=TaskStatus.PENDING)
        db.add(task)
        db.commit()

        # Step 1: PENDING -> RUNNING
        t = TaskStateMachine.transition(db, "t_flow", TaskStatus.RUNNING, actor="commander", reason="Starting execution")
        assert t.status == TaskStatus.RUNNING

        # Step 2: RUNNING -> WAITING_REVIEW
        t = TaskStateMachine.transition(db, "t_flow", TaskStatus.WAITING_REVIEW, actor="agent-content-writer", reason="Draft ready")
        assert t.status == TaskStatus.WAITING_REVIEW

        # Step 3: WAITING_REVIEW -> APPROVED
        t = TaskStateMachine.transition(db, "t_flow", TaskStatus.APPROVED, actor="user", reason="Approved by reviewer")
        assert t.status == TaskStatus.APPROVED

        # Step 4: APPROVED -> DELIVERED
        t = TaskStateMachine.transition(db, "t_flow", TaskStatus.DELIVERED, actor="commander", reason="Artifacts packaged")
        assert t.status == TaskStatus.DELIVERED

        # Step 5: DELIVERED -> COMPLETED
        t = TaskStateMachine.transition(db, "t_flow", TaskStatus.COMPLETED, actor="user", reason="Final acceptance")
        assert t.status == TaskStatus.COMPLETED

        # Check audit log immutability and exact history
        logs = db.query(TaskAuditLog).filter_by(task_id="t_flow").order_by(TaskAuditLog.created_at.asc()).all()
        assert len(logs) == 5
        assert logs[0].from_status == "pending" and logs[0].to_status == "running" and logs[0].actor == "commander"
        assert logs[1].from_status == "running" and logs[1].to_status == "waiting_review"
        assert logs[2].from_status == "waiting_review" and logs[2].to_status == "approved"
        assert logs[3].from_status == "approved" and logs[3].to_status == "delivered"
        assert logs[4].from_status == "delivered" and logs[4].to_status == "completed" and logs[4].actor == "user"


def test_fsm_paused_transitions_for_crash_recovery(tmp_path):
    """Test PAUSED transitions required for crash recovery (RUNNING -> PAUSED -> RUNNING / CANCELLED)."""
    SessionLocal = init_db(tmp_path / "app.db")
    with SessionLocal() as db:
        seed_defaults(db)
        task = Task(id="t_pause", project_id="proj-default", title="Pause Test", status=TaskStatus.RUNNING)
        db.add(task)
        db.commit()

        # RUNNING -> PAUSED (simulating crash recovery)
        t = TaskStateMachine.transition(db, "t_pause", TaskStatus.PAUSED, actor="system", reason="Server restart crash recovery")
        assert t.status == TaskStatus.PAUSED

        # PAUSED -> RUNNING (resume)
        t = TaskStateMachine.transition(db, "t_pause", TaskStatus.RUNNING, actor="user", reason="Resume task")
        assert t.status == TaskStatus.RUNNING

        # RUNNING -> PAUSED -> CANCELLED
        t = TaskStateMachine.transition(db, "t_pause", TaskStatus.PAUSED, actor="user", reason="Pause again")
        assert t.status == TaskStatus.PAUSED
        t = TaskStateMachine.transition(db, "t_pause", TaskStatus.CANCELLED, actor="user", reason="Cancelled while paused")
        assert t.status == TaskStatus.CANCELLED


def test_fsm_rejection_cycle(tmp_path):
    """Test WAITING_REVIEW -> REJECTED -> RUNNING rework cycle."""
    SessionLocal = init_db(tmp_path / "app.db")
    with SessionLocal() as db:
        seed_defaults(db)
        task = Task(id="t_rej", project_id="proj-default", title="Rejection Flow", status=TaskStatus.RUNNING)
        db.add(task)
        db.commit()

        # RUNNING -> WAITING_REVIEW
        TaskStateMachine.transition(db, "t_rej", TaskStatus.WAITING_REVIEW, actor="agent")

        # WAITING_REVIEW -> REJECTED
        t = TaskStateMachine.transition(db, "t_rej", TaskStatus.REJECTED, actor="user", reason="Needs more citations")
        assert t.status == TaskStatus.REJECTED

        # REJECTED -> RUNNING
        t = TaskStateMachine.transition(db, "t_rej", TaskStatus.RUNNING, actor="agent", reason="Adding citations")
        assert t.status == TaskStatus.RUNNING


def test_fsm_terminal_state_rejects_further_transitions(tmp_path):
    """COMPLETED and CANCELLED states are terminal and reject transitions."""
    SessionLocal = init_db(tmp_path / "app.db")
    with SessionLocal() as db:
        seed_defaults(db)
        t_comp = Task(id="t_comp", project_id="proj-default", title="Done", status=TaskStatus.COMPLETED)
        t_canc = Task(id="t_canc", project_id="proj-default", title="Cancelled", status=TaskStatus.CANCELLED)
        db.add_all([t_comp, t_canc])
        db.commit()

        with pytest.raises(InvalidStateTransitionError):
            TaskStateMachine.transition(db, "t_comp", TaskStatus.RUNNING, actor="user")

        with pytest.raises(InvalidStateTransitionError):
            TaskStateMachine.transition(db, "t_canc", TaskStatus.RUNNING, actor="user")


def test_all_18_orm_models_can_be_created_and_persisted(tmp_path):
    """Verify that all 18 ORM models can be instantiated and persisted in SQLite."""
    SessionLocal = init_db(tmp_path / "app.db")
    with SessionLocal() as db:
        seed_defaults(db)

        # 1. Project (already seeded)
        proj = db.get(Project, "proj-default")
        assert proj is not None

        # 2. Department (already seeded)
        dept = db.get(Department, "dept-content")
        assert dept is not None

        # 3. Agent (already seeded)
        agent = db.get(Agent, "agent-commander")
        assert agent is not None

        # 4. Skill
        skill = Skill(
            id="skill-test",
            name="test-skill",
            description="A test skill",
            file_path="skills/test/SKILL.md",
            content="# Test Skill\nInstructions",
            allowed_tools=["web_search", "browser"],
        )
        db.add(skill)

        # 5. AgentSkill
        agent_skill = AgentSkill(
            id="askill-1",
            agent_id="agent-commander",
            skill_id="skill-test",
            is_active=True,
        )
        db.add(agent_skill)

        # 6. Task
        task = Task(
            id="task-orm-test",
            project_id="proj-default",
            title="ORM Test Task",
            description="Testing all relations",
            status=TaskStatus.PENDING,
            assigned_agent_id="agent-commander",
        )
        db.add(task)
        db.flush()

        # 7. SubTask
        subtask = SubTask(
            id="subtask-1",
            task_id="task-orm-test",
            agent_id="agent-commander",
            title="SubTask 1",
            status="pending",
        )
        db.add(subtask)

        # 8. TurnLog
        turn_log = TurnLog(
            id="turn-1",
            task_id="task-orm-test",
            turn_number=1,
            action="tool_call",
            tool="web_search",
            duration_ms=120,
            tokens=450,
            status="completed",
        )
        db.add(turn_log)

        # 9. Artifact
        artifact = Artifact(
            id="art-1",
            task_id="task-orm-test",
            name="output.html",
            file_path="artifacts/output.html",
            file_type="html",
            mime_type="text/html",
            size_bytes=1024,
        )
        db.add(artifact)

        # 10. ReviewGate
        review_gate = ReviewGate(
            id="rg-1",
            task_id="task-orm-test",
            status="pending",
        )
        db.add(review_gate)

        # 11. UsageRecord
        usage = UsageRecord(
            id="usage-1",
            task_id="task-orm-test",
            agent_id="agent-commander",
            model_name="gemini-2.5-flash",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.0001,
        )
        db.add(usage)

        # 12. BrandProfile
        brand = BrandProfile(
            id="brand-1",
            project_id="proj-default",
            brand_name="TestBrand",
            tagline="Think Forward",
            tone_of_voice="Chuyên nghiệp, sắc bén",
        )
        db.add(brand)

        # 13. Product
        product = Product(
            id="prod-1",
            project_id="proj-default",
            sku="SKU-TEST-01",
            name="Test Product",
            price_vnd=250000,
        )
        db.add(product)

        # 14. Conversation
        conv = Conversation(
            id="conv-1",
            project_id="proj-default",
            channel="zalo",
            title="Khách hỏi tư vấn",
        )
        db.add(conv)
        db.flush()

        # 15. Message
        msg = Message(
            id="msg-1",
            conversation_id="conv-1",
            sender_type="user",
            content="Xin chào shop!",
        )
        db.add(msg)

        # 16. ConnectorConfig
        conn = ConnectorConfig(
            id="conn-zalo",
            name="Zalo Personal",
            provider="zalo",
            is_enabled=True,
            status="connected",
        )
        db.add(conn)

        # 17. UserSettings
        settings = UserSettings(
            id="settings-test",
            theme="dark",
            language="vi",
            daily_token_limit=500000,
        )
        db.add(settings)

        # 18. TaskAuditLog
        audit = TaskAuditLog(
            id="audit-1",
            task_id="task-orm-test",
            from_status="pending",
            to_status="running",
            actor="user",
            reason="Manual trigger",
        )
        db.add(audit)

        db.commit()

        # Verify all rows persisted
        assert db.get(Skill, "skill-test") is not None
        assert db.get(AgentSkill, "askill-1") is not None
        assert db.get(SubTask, "subtask-1") is not None
        assert db.get(TurnLog, "turn-1") is not None
        assert db.get(Artifact, "art-1") is not None
        assert db.get(ReviewGate, "rg-1") is not None
        assert db.get(UsageRecord, "usage-1") is not None
        assert db.get(BrandProfile, "brand-1") is not None
        assert db.get(Product, "prod-1") is not None
        assert db.get(Conversation, "conv-1") is not None
        assert db.get(Message, "msg-1") is not None
        assert db.get(ConnectorConfig, "conn-zalo") is not None
        assert db.get(UserSettings, "settings-test") is not None
        assert db.get(TaskAuditLog, "audit-1") is not None


def test_fsm_completed_at_cleared_on_retry_from_failed(tmp_path):
    """When retrying a FAILED task, completed_at timestamp must be reset to None."""
    SessionLocal = init_db(tmp_path / "app.db")
    with SessionLocal() as db:
        seed_defaults(db)
        task = Task(id="t_retry", project_id="proj-default", title="Retry Test", status=TaskStatus.RUNNING)
        db.add(task)
        db.commit()

        # Transition to FAILED -> sets completed_at
        TaskStateMachine.transition(db, "t_retry", TaskStatus.FAILED, actor="system", reason="Timeout")
        assert task.status == TaskStatus.FAILED
        assert task.completed_at is not None

        # Retry: FAILED -> RUNNING -> completed_at must be cleared
        TaskStateMachine.transition(db, "t_retry", TaskStatus.RUNNING, actor="user", reason="Manual retry")
        assert task.status == TaskStatus.RUNNING
        assert task.completed_at is None


def test_fsm_rejects_running_directly_to_approved(tmp_path):
    """APPROVED must only be entered via WAITING_REVIEW; RUNNING -> APPROVED is illegal."""
    SessionLocal = init_db(tmp_path / "app.db")
    with SessionLocal() as db:
        seed_defaults(db)
        task = Task(id="t_no_bypass", project_id="proj-default", title="No Bypass", status=TaskStatus.RUNNING)
        db.add(task)
        db.commit()

        with pytest.raises(InvalidStateTransitionError):
            TaskStateMachine.transition(db, "t_no_bypass", TaskStatus.APPROVED, actor="user")


def test_get_db_reuses_cached_sessionmaker(tmp_path):
    """get_db and init_db reuse the cached sessionmaker and Engine for the same db path."""
    db_file = tmp_path / "cached_test.db"
    f1 = init_db(db_file)
    f2 = init_db(db_file)
    assert f1 is f2

    # Test get_db generator reuses the same bind
    g1 = get_db(db_file)
    g2 = get_db(db_file)
    s1 = next(g1)
    s2 = next(g2)
    assert s1.bind is s2.bind
    s1.close()
    s2.close()


def test_multithreaded_memory_db_access():
    """Ensure multi-threaded access to in-memory SQLite works cleanly with StaticPool."""
    SessionLocal = init_db(":memory:")
    with SessionLocal() as db:
        seed_defaults(db)

    # Thread 1: performs write on different thread
    def _writer_thread(task_id: str, results: list[str]) -> None:
        with SessionLocal() as session:
            task = Task(
                id=task_id,
                project_id="proj-default",
                title=f"Task {task_id}",
                status=TaskStatus.PENDING,
            )
            session.add(task)
            session.commit()
            results.append(task_id)

    # Thread 2: verifies read on yet another thread
    def _reader_thread(task_id: str, results: list[bool]) -> None:
        with SessionLocal() as session:
            t = session.get(Task, task_id)
            results.append(t is not None)

    written: list[str] = []
    read_results: list[bool] = []

    t1 = threading.Thread(target=_writer_thread, args=("t_cross_thread_1", written))
    t1.start()
    t1.join()

    assert written == ["t_cross_thread_1"]

    t2 = threading.Thread(target=_reader_thread, args=("t_cross_thread_1", read_results))
    t2.start()
    t2.join()

    assert read_results == [True]

    # Concurrent workers with thread synchronization
    lock = threading.Lock()

    def _concurrent_worker(worker_id: int) -> int:
        with lock:
            with SessionLocal() as session:
                task = Task(
                    id=f"t_thread_{worker_id}",
                    project_id="proj-default",
                    title=f"Thread Task {worker_id}",
                    status=TaskStatus.PENDING,
                )
                session.add(task)
                session.commit()
                return session.query(Task).count()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_concurrent_worker, i) for i in range(4)]
        worker_counts = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(worker_counts) == 4
    with SessionLocal() as db:
        # 1 from thread 1 + 4 from concurrent workers = 5 tasks
        assert db.query(Task).count() == 5


def test_fsm_transition_missing_task_raises_value_error(tmp_path):
    """Attempting to transition a non-existent task must raise ValueError."""
    SessionLocal = init_db(tmp_path / "app.db")
    with SessionLocal() as db:
        seed_defaults(db)
        with pytest.raises(ValueError, match="Task with id 'missing-id' not found"):
            TaskStateMachine.transition(db, "missing-id", TaskStatus.RUNNING, actor="user")

