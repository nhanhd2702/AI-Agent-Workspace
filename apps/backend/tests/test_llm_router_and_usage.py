"""Tests for LLM Router, Token Tracking, Quota Guard, and Usage Monitoring API (Task 2.2).

Covers:
- Brief tests: 429 fallback to secondary model and token recording.
- QuotaService: 80% warning flag, 100% quota enforcement raising QuotaExceededError.
- Exponential backoff retry on 5xx before fallback (checking retry count and delays).
- 5xx recovery on retry #1 without triggering fallback.
- 429 retry behavior without fallback model.
- TurnLog entry recorded on fallback when task exists.
- Local token estimation (len(text) // 4) with is_estimated=True on omitted metadata.
- Provider pricing table calculations (Gemini, Claude, GPT, Ollama local 0 USD, default).
- UTC day boundary isolation (yesterday spend does not block today).
- Router blocking calls with QuotaExceededError when quota is exceeded.
- GET /api/v1/monitoring/usage: 401 unauth, 200 breakdown (quota, summary, by_model, by_agent).
- Async complete interface with Agent ORM entity.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.db.models import Agent, Project, Task, TaskStatus, TurnLog, UsageRecord, UserSettings
from app.db.session import init_db, seed_defaults
from app.main import create_app
from app.llm.router import LlmResponse, LlmRouter, MockProviderRegistry, ProviderError
from app.llm.usage import (
    PRICING_PER_1M_TOKENS,
    QuotaExceededError,
    QuotaService,
    QuotaStatus,
    calculate_cost_usd,
    estimate_tokens,
)


@pytest.fixture
def db_session(tmp_path: Path):
    """Provide an isolated seeded SQLAlchemy session per test with default task 't1'."""
    SessionLocal = init_db(tmp_path / "test.db")
    with SessionLocal() as session:
        seed_defaults(session)
        # Ensure default Project exists
        if not session.get(Project, "proj-default"):
            session.add(
                Project(
                    id="proj-default",
                    name="Default Project",
                    default_department_id="dept-office",
                )
            )
            session.flush()
        # Seed test task 't1' for FK integrity in TurnLog and UsageRecord
        if not session.get(Task, "t1"):
            session.add(
                Task(
                    id="t1",
                    project_id="proj-default",
                    title="Test Task 1",
                    status=TaskStatus.RUNNING,
                    assigned_agent_id="agent-commander",
                )
            )
            session.commit()
        yield session


@pytest.fixture
def mock_providers():
    """Fixture providing MockProviderRegistry."""
    return MockProviderRegistry()


@pytest.fixture
def client_with_db(tmp_path: Path) -> TestClient:
    """Fixture providing initialized FastAPI test client with seeded database and auth header."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="test-secret-token")
    app = create_app(settings)
    client = TestClient(app, headers={"X-Local-Auth-Token": "test-secret-token"})
    client.app_settings = settings  # type: ignore[attr-defined]
    return client


# ============================================================================
# 1. Brief Specific Tests
# ============================================================================


def test_llm_router_falls_back_on_429_and_records_usage(db_session, mock_providers):
    """Brief Test 1: Fallback from primary to fallback model on 429, recording usage."""
    mock_providers.fail_once("gemini-2.5-flash", status=429)
    router = LlmRouter(providers=mock_providers)
    res = router.complete_sync(
        primary="gemini-2.5-flash",
        fallback="claude-3-5-sonnet",
        messages=[{"role": "user", "content": "hi"}],
        db=db_session,
        task_id="t1",
        agent_id="ContentWriter",
    )
    assert res.model_used == "claude-3-5-sonnet"
    assert res.total_tokens > 0
    assert res.fallback_triggered is True

    # Verify UsageRecord created in DB
    records = db_session.query(UsageRecord).all()
    assert len(records) == 1
    assert records[0].model_name == "claude-3-5-sonnet"
    assert records[0].agent_id == "agent-content-writer"  # Resolved from name 'ContentWriter'
    assert records[0].task_id == "t1"

    # Verify TurnLog created for fallback action
    turn_logs = db_session.query(TurnLog).filter_by(task_id="t1").all()
    assert len(turn_logs) == 1
    assert turn_logs[0].action == "fallback_model"
    assert turn_logs[0].output_payload.get("selected_model") == "claude-3-5-sonnet"


def test_quota_warns_at_80_percent_and_blocks_at_100_percent(db_session):
    """Brief Test 2: Warning flag at >=80% and QuotaExceededError raised at >=100%."""
    svc = QuotaService(daily_limit_usd=1.0)
    svc.record_cost(
        db_session,
        task_id="t1",
        agent_id="Commander",
        model="gemini-2.5-flash",
        input_tokens=100,
        output_tokens=100,
        cost_usd=0.85,
    )
    status = svc.check_quota(db_session)
    assert status.warning_triggered is True
    assert status.exceeded is False

    svc.record_cost(
        db_session,
        task_id="t1",
        agent_id="Commander",
        model="gemini-2.5-flash",
        input_tokens=100,
        output_tokens=100,
        cost_usd=0.20,
    )
    status_exceeded = svc.check_quota(db_session)
    assert status_exceeded.exceeded is True
    assert status_exceeded.warning_triggered is True

    with pytest.raises(QuotaExceededError):
        svc.enforce_quota(db_session)


# ============================================================================
# 2. Retry with Exponential Backoff on 5xx & Fallback
# ============================================================================


def test_5xx_retries_primary_with_exponential_backoff_then_falls_back(db_session, mock_providers):
    """Router retries primary 2 times with exponential backoff on 5xx before falling back."""
    # Primary fails with 500 continuously (more than 2 retries)
    mock_providers.set_failures("gemini-2.5-flash", count=5, status=500)
    recorded_delays: list[float] = []

    def mock_sleep(seconds: float) -> None:
        recorded_delays.append(seconds)

    router = LlmRouter(
        providers=mock_providers,
        max_retries=2,
        base_delay=0.5,
        sleep_fn=mock_sleep,
    )

    res = router.complete_sync(
        primary="gemini-2.5-flash",
        fallback="claude-3-5-sonnet",
        messages=[{"role": "user", "content": "hello world"}],
        db=db_session,
        task_id="t1",
        agent_id="agent-commander",
    )

    # Primary attempted 1 initial + 2 retries = 3 attempts total
    assert res.model_used == "claude-3-5-sonnet"
    assert res.fallback_triggered is True
    # Exponential backoff: base_delay * (2 ** 0) = 0.5, base_delay * (2 ** 1) = 1.0
    assert recorded_delays == [0.5, 1.0]


def test_5xx_recovers_on_retry_1_without_falling_back(db_session, mock_providers):
    """Router retries on first 5xx and recovers on retry 1 without falling back."""
    mock_providers.set_failures("gemini-2.5-flash", count=1, status=503)
    recorded_delays: list[float] = []

    router = LlmRouter(
        providers=mock_providers,
        max_retries=2,
        base_delay=0.25,
        sleep_fn=lambda s: recorded_delays.append(s),
    )

    res = router.complete_sync(
        primary="gemini-2.5-flash",
        fallback="claude-3-5-sonnet",
        messages=[{"role": "user", "content": "recover test"}],
        db=db_session,
        task_id="t1",
    )

    assert res.model_used == "gemini-2.5-flash"
    assert res.fallback_triggered is False
    assert res.attempts == 2
    assert recorded_delays == [0.25]


def test_429_retries_when_no_fallback_configured(mock_providers):
    """When no fallback model is configured, 429 retries primary up to max_retries before raising."""
    mock_providers.set_failures("gemini-2.5-flash", count=5, status=429)
    recorded_delays: list[float] = []

    router = LlmRouter(
        providers=mock_providers,
        max_retries=2,
        base_delay=0.1,
        sleep_fn=lambda s: recorded_delays.append(s),
    )

    with pytest.raises(ProviderError) as exc_info:
        router.complete_sync(
            primary="gemini-2.5-flash",
            fallback=None,
            messages=[{"role": "user", "content": "no fallback test"}],
        )

    assert exc_info.value.status_code == 429
    assert recorded_delays == [0.1, 0.2]


# ============================================================================
# 3. Token Estimation & Pricing Table
# ============================================================================


def test_stream_metadata_drop_falls_back_to_local_estimation(db_session, mock_providers):
    """When provider response omits usage metadata, estimates tokens via len(text)//4."""
    prompt_text = "This is a test prompt with around twenty words to measure estimation behavior."
    expected_input_est = max(1, len(prompt_text) // 4)
    response_text = "This is a synthesized completion output text."
    expected_output_est = max(1, len(response_text) // 4)

    # Set mock provider to return None usage
    mock_providers.set_custom_response(
        "gemini-2.5-flash",
        content=response_text,
        usage=None,
    )

    router = LlmRouter(providers=mock_providers)
    res = router.complete_sync(
        primary="gemini-2.5-flash",
        fallback=None,
        messages=[{"role": "user", "content": prompt_text}],
        db=db_session,
        task_id="t1",
        agent_id="Commander",
    )

    assert res.is_estimated is True
    assert res.input_tokens == expected_input_est
    assert res.output_tokens == expected_output_est
    assert res.total_tokens == expected_input_est + expected_output_est

    # Verify UsageRecord in DB has is_estimated=True
    records = db_session.query(UsageRecord).all()
    assert len(records) == 1
    assert records[0].is_estimated is True
    assert records[0].prompt_tokens == expected_input_est
    assert records[0].completion_tokens == expected_output_est


def test_pricing_table_exact_calculations():
    """Verify exact pricing calculations per 1M tokens across models."""
    # gemini-2.5-flash: $0.075 / 1M in, $0.30 / 1M out
    cost_flash = calculate_cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000)
    assert pytest.approx(cost_flash, 1e-6) == 0.375

    # gemini-2.5-pro: $1.25 / 1M in, $5.00 / 1M out
    cost_pro = calculate_cost_usd("gemini-2.5-pro", 1_000_000, 1_000_000)
    assert pytest.approx(cost_pro, 1e-6) == 6.25

    # claude-3-5-sonnet: $3.00 / 1M in, $15.00 / 1M out
    cost_claude = calculate_cost_usd("claude-3-5-sonnet", 1_000_000, 1_000_000)
    assert pytest.approx(cost_claude, 1e-6) == 18.00

    # claude-3-7-sonnet: $3.00 / 1M in, $15.00 / 1M out
    cost_claude_7 = calculate_cost_usd("claude-3-7-sonnet", 1_000_000, 1_000_000)
    assert pytest.approx(cost_claude_7, 1e-6) == 18.00

    # gpt-4o: $2.50 / 1M in, $10.00 / 1M out
    cost_gpt4o = calculate_cost_usd("gpt-4o", 1_000_000, 1_000_000)
    assert pytest.approx(cost_gpt4o, 1e-6) == 12.50

    # gpt-4o-mini: $0.15 / 1M in, $0.60 / 1M out
    cost_mini = calculate_cost_usd("gpt-4o-mini", 1_000_000, 1_000_000)
    assert pytest.approx(cost_mini, 1e-6) == 0.75

    # ollama/*: 0 USD for local execution
    assert calculate_cost_usd("ollama/llama3", 500_000, 500_000) == 0.0
    assert calculate_cost_usd("ollama/qwen2.5-coder", 1_000_000, 1_000_000) == 0.0

    # Default fallback for unknown model: $1.00 / 1M in, $3.00 / 1M out
    cost_unknown = calculate_cost_usd("custom-future-model", 1_000_000, 1_000_000)
    assert pytest.approx(cost_unknown, 1e-6) == 4.00

    # Small token counts precision
    small_cost = calculate_cost_usd("gemini-2.5-flash", 1000, 500)
    expected_small = (1000 / 1e6) * 0.075 + (500 / 1e6) * 0.30
    assert pytest.approx(small_cost, 1e-8) == expected_small


def test_estimate_tokens_helper():
    """Verify estimate_tokens boundary conditions."""
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0
    assert estimate_tokens("a") == 1  # max(1, 1//4) = 1
    assert estimate_tokens("1234") == 1
    assert estimate_tokens("12345678") == 2
    assert estimate_tokens("hello world!") == 3


# ============================================================================
# 4. UTC Day Boundary Isolation
# ============================================================================


def test_utc_day_boundary_isolation_yesterday_spend_does_not_block_today(db_session):
    """Yesterday's usage does not count towards today's daily quota limit."""
    svc = QuotaService(daily_limit_usd=1.0)

    # Insert a record from yesterday
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    old_record = UsageRecord(
        id="usage-old",
        task_id="t1",
        agent_id="agent-commander",
        model_name="gemini-2.5-flash",
        prompt_tokens=1000,
        completion_tokens=1000,
        total_tokens=2000,
        cost_usd=2.50,  # Far exceeds 1.0 limit!
        created_at=yesterday,
    )
    db_session.add(old_record)
    db_session.commit()

    # Quota check today should not include yesterday's $2.50
    status_today = svc.check_quota(db_session)
    assert status_today.spent_today_usd == 0.0
    assert status_today.exceeded is False
    assert status_today.warning_triggered is False

    # Enforce quota today should pass without error
    svc.enforce_quota(db_session)


def test_llm_router_blocks_calls_when_daily_quota_exceeded(db_session, mock_providers):
    """LlmRouter rejects completion requests with QuotaExceededError when quota is >= 100%."""
    svc = QuotaService(daily_limit_usd=0.50)
    # Seed spend today of $0.60
    svc.record_cost(
        db_session,
        task_id="t1",
        agent_id="Commander",
        model="gemini-2.5-flash",
        cost_usd=0.60,
    )

    router = LlmRouter(providers=mock_providers, quota_service=svc)

    with pytest.raises(QuotaExceededError) as exc_info:
        router.complete_sync(
            primary="gemini-2.5-flash",
            messages=[{"role": "user", "content": "hi"}],
            db=db_session,
            task_id="t1",
        )

    assert "quota exceeded" in str(exc_info.value).lower()


# ============================================================================
# 5. Async Complete Interface with Agent ORM Entity
# ============================================================================


@pytest.mark.asyncio
async def test_async_complete_with_agent_entity(db_session, mock_providers):
    """Test async complete(agent: Agent, messages: list[dict], db: Session, task_id: str)."""
    agent = db_session.get(Agent, "agent-commander")
    assert agent is not None
    agent.default_model = "gemini-2.5-flash"
    agent.fallback_model = "claude-3-5-sonnet"

    router = LlmRouter(providers=mock_providers)
    res = await router.complete(
        agent=agent,
        messages=[{"role": "user", "content": "plan the day"}],
        db=db_session,
        task_id="t1",
    )

    assert isinstance(res, LlmResponse)
    assert res.model_used == "gemini-2.5-flash"
    assert res.total_tokens > 0
    assert not res.fallback_triggered


# ============================================================================
# 6. Monitoring API: GET /api/v1/monitoring/usage
# ============================================================================


def test_monitoring_usage_endpoint_auth_enforcement(client_with_db: TestClient):
    """GET /api/v1/monitoring/usage requires valid X-Local-Auth-Token."""
    # Test without token
    unauth_client = TestClient(client_with_db.app)
    resp_no_token = unauth_client.get("/api/v1/monitoring/usage")
    assert resp_no_token.status_code == 401

    # Test with invalid token
    resp_bad_token = unauth_client.get(
        "/api/v1/monitoring/usage",
        headers={"X-Local-Auth-Token": "bad-token"},
    )
    assert resp_bad_token.status_code == 401


def test_monitoring_usage_endpoint_breakdown_and_periods(client_with_db: TestClient):
    """GET /api/v1/monitoring/usage returns complete metrics, quota, and agent/model breakdowns."""
    # Populate some usage records in the client's database
    SessionLocal = init_db(client_with_db.app_settings.resolved_db_path)
    with SessionLocal() as session:
        # Override user settings daily limit to $5.00 for testing
        settings = session.get(UserSettings, "settings-default")
        if settings:
            settings.daily_usd_limit = 5.0
            session.commit()

        svc = QuotaService(daily_limit_usd=5.0)
        # Record 1: Commander, gemini-2.5-flash, $2.00
        svc.record_cost(
            session,
            task_id=None,
            agent_id="Commander",
            model="gemini-2.5-flash",
            input_tokens=1000,
            output_tokens=2000,
            cost_usd=2.00,
        )
        # Record 2: ContentWriter, claude-3-5-sonnet, $2.20 (total $4.20 >= 80% of $5.00)
        svc.record_cost(
            session,
            task_id=None,
            agent_id="ContentWriter",
            model="claude-3-5-sonnet",
            input_tokens=500,
            output_tokens=1500,
            cost_usd=2.20,
        )

    # Call endpoint with default period ('today')
    resp = client_with_db.get("/api/v1/monitoring/usage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    data = body["data"]

    # Quota block verification
    quota = data["quota"]
    assert quota["daily_limit_usd"] == 5.0
    assert pytest.approx(quota["spent_today_usd"], 0.01) == 4.20
    assert quota["warning_triggered"] is True  # 4.20 / 5.0 = 84% >= 80%
    assert quota["exceeded"] is False

    # Summary block verification
    summary = data["summary"]
    assert summary["total_requests"] == 2
    assert summary["total_tokens"] == 5000  # (1000+2000) + (500+1500)
    assert pytest.approx(summary["total_cost_usd"], 0.01) == 4.20

    # by_model breakdown
    by_model = {item["model_name"]: item for item in data["by_model"]}
    assert "gemini-2.5-flash" in by_model
    assert by_model["gemini-2.5-flash"]["requests"] == 1
    assert "claude-3-5-sonnet" in by_model
    assert by_model["claude-3-5-sonnet"]["requests"] == 1

    # by_agent breakdown
    by_agent = {item["agent_id"]: item for item in data["by_agent"]}
    assert "agent-commander" in by_agent
    assert "agent-content-writer" in by_agent

    # recent_records list
    assert len(data["recent_records"]) == 2

    # Query with periods: '7d', '30d', 'all'
    for p in ["7d", "30d", "all"]:
        r = client_with_db.get(f"/api/v1/monitoring/usage?period={p}")
        assert r.status_code == 200
        assert r.json()["data"]["period"] == p
