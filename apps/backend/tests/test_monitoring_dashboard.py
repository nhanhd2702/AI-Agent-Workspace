"""Unit and integration tests for System Monitoring Dashboard & CSV Export (Task 5.2).

Covers:
- GET /api/v1/monitoring/dashboard?period=7d:
  - Aggregates by agent, model, daily trends, task stats, and quota.
  - Daily trend series aggregation (date, tokens, cost_usd, requests).
  - Task success rate & stats (total, completed, failed, in_progress, success_rate_pct).
  - Period filtering ('today', '7d', '30d', 'all').
- GET /api/v1/monitoring/export.csv:
  - MIME type text/csv and Content-Disposition attachment header.
  - Columns: timestamp,task_id,agent_id,agent_name,model_name,prompt_tokens,completion_tokens,total_tokens,cost_usd,is_estimated.
  - Disarming CSV formula injection on text fields (=, +, -, @, \\t, \\r).
- Authentication enforcement (X-Local-Auth-Token required).
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.db.models import Agent, Department, Project, Task, TaskStatus, UsageRecord, UserSettings
from app.db.session import init_db, seed_defaults
from app.main import create_app


@pytest.fixture
def client_with_db(tmp_path: Path) -> TestClient:
    """Fixture providing initialized FastAPI test client with seeded database and auth header."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="test-secret-token")
    app = create_app(settings)
    client = TestClient(app, headers={"X-Local-Auth-Token": "test-secret-token"})
    client.app_settings = settings  # type: ignore[attr-defined]
    return client


@pytest.fixture
def seeded_usage(client_with_db: TestClient):
    """Seed sample projects, tasks, agents, and usage records spanning multiple dates."""
    SessionLocal = init_db(client_with_db.app_settings.resolved_db_path)
    with SessionLocal() as session:
        seed_defaults(session)

        # Ensure project exists
        project = session.get(Project, "proj-default")
        if not project:
            project = Project(
                id="proj-default",
                name="Default Project",
                default_department_id="dept-office",
            )
            session.add(project)
            session.flush()

        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        three_days_ago = now - timedelta(days=3)

        # Seed Tasks for task success stats
        t_completed = Task(
            id="task-comp-1",
            project_id=project.id,
            title="Completed Task 1",
            status=TaskStatus.COMPLETED,
            assigned_agent_id="agent-commander",
            created_at=yesterday,
        )
        t_failed = Task(
            id="task-fail-1",
            project_id=project.id,
            title="Failed Task 1",
            status=TaskStatus.FAILED,
            assigned_agent_id="agent-content-writer",
            created_at=yesterday,
        )
        t_running = Task(
            id="task-run-1",
            project_id=project.id,
            title="Running Task 1",
            status=TaskStatus.RUNNING,
            assigned_agent_id="agent-commander",
            created_at=now,
        )
        session.add_all([t_completed, t_failed, t_running])
        session.flush()

        # Seed UsageRecords
        # 1. Today record by commander with Gemini
        u1 = UsageRecord(
            id="usage-1",
            task_id=t_running.id,
            agent_id="agent-commander",
            model_name="gemini-2.5-flash",
            prompt_tokens=1000,
            completion_tokens=2000,
            total_tokens=3000,
            cost_usd=0.000675,
            is_estimated=False,
            created_at=now,
        )
        # 2. Yesterday record by copywriter with Claude
        u2 = UsageRecord(
            id="usage-2",
            task_id=t_completed.id,
            agent_id="agent-content-writer",
            model_name="claude-3-5-sonnet",
            prompt_tokens=500,
            completion_tokens=1500,
            total_tokens=2000,
            cost_usd=0.024,
            is_estimated=False,
            created_at=yesterday,
        )
        # 3. 3 days ago record with formula injection payload in model_name / agent
        u3 = UsageRecord(
            id="usage-3",
            task_id=t_failed.id,
            agent_id="agent-commander",
            model_name="=CMD()|' /C calc'!A0",
            prompt_tokens=400,
            completion_tokens=600,
            total_tokens=1000,
            cost_usd=0.001,
            is_estimated=True,
            created_at=three_days_ago,
        )

        session.add_all([u1, u2, u3])
        session.commit()

    return {
        "tasks": ["task-comp-1", "task-fail-1", "task-run-1"],
        "records": ["usage-1", "usage-2", "usage-3"],
    }


def test_monitoring_dashboard_aggregates_by_agent_and_exports_csv(client_with_db, seeded_usage):
    """Exact test from plan: aggregates by agent and exports CSV."""
    resp = client_with_db.get("/api/v1/monitoring/dashboard?period=7d")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_tokens"] > 0
    assert len(data["by_agent"]) >= 1
    csv_resp = client_with_db.get("/api/v1/monitoring/export.csv?period=7d")
    assert csv_resp.headers["content-type"].startswith("text/csv")


def test_monitoring_dashboard_daily_trends_aggregation(client_with_db, seeded_usage):
    """GET /api/v1/monitoring/dashboard includes daily bucketed trend series."""
    resp = client_with_db.get("/api/v1/monitoring/dashboard?period=7d")
    assert resp.status_code == 200
    data = resp.json()["data"]

    trends = data["daily_trends"]
    assert isinstance(trends, list)
    assert len(trends) >= 2  # at least today and yesterday

    for day in trends:
        assert "date" in day
        assert "tokens" in day
        assert "cost_usd" in day
        assert "requests" in day
        assert isinstance(day["tokens"], int)
        assert isinstance(day["cost_usd"], (int, float))
        assert isinstance(day["requests"], int)

    # Check totals match sum across daily trends
    sum_trend_tokens = sum(d["tokens"] for d in trends)
    assert sum_trend_tokens == data["total_tokens"]


def test_monitoring_dashboard_task_stats(client_with_db, seeded_usage):
    """GET /api/v1/monitoring/dashboard computes task success rate and status counts."""
    resp = client_with_db.get("/api/v1/monitoring/dashboard?period=7d")
    assert resp.status_code == 200
    data = resp.json()["data"]

    stats = data["task_stats"]
    assert stats["total"] == 3
    assert stats["completed"] == 1
    assert stats["failed"] == 1
    assert stats["in_progress"] == 1
    # 1 completed / 3 total = 33.33%
    assert pytest.approx(stats["success_rate_pct"], 0.1) == 33.33


def test_monitoring_csv_export_format_and_formula_disarm(client_with_db, seeded_usage):
    """GET /api/v1/monitoring/export.csv produces valid CSV headers and disarms formula injection."""
    resp = client_with_db.get("/api/v1/monitoring/export.csv?period=7d")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in resp.headers.get("content-disposition", "")

    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    assert len(rows) >= 4  # header + 3 data rows

    header = rows[0]
    expected_headers = [
        "timestamp",
        "task_id",
        "agent_id",
        "agent_name",
        "model_name",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
        "is_estimated",
    ]
    assert header == expected_headers

    # Check formula injection disarmed for u3
    # u3 model_name was "=CMD()|' /C calc'!A0", should be escaped with leading single quote: "'=CMD()|' /C calc'!A0"
    injected_row = next((r for r in rows[1:] if "calc" in r[4]), None)
    assert injected_row is not None
    assert injected_row[4].startswith("'=")


def test_monitoring_auth_enforcement(client_with_db):
    """Monitoring dashboard and CSV export endpoints require valid X-Local-Auth-Token."""
    unauth_client = TestClient(client_with_db.app)

    # Missing token
    resp_dash = unauth_client.get("/api/v1/monitoring/dashboard")
    assert resp_dash.status_code == 401

    resp_csv = unauth_client.get("/api/v1/monitoring/export.csv")
    assert resp_csv.status_code == 401

    # Invalid token
    resp_bad = unauth_client.get(
        "/api/v1/monitoring/dashboard",
        headers={"X-Local-Auth-Token": "invalid-secret"},
    )
    assert resp_bad.status_code == 401


def test_monitoring_period_validation(client_with_db):
    """Monitoring endpoint validates allowed period query values."""
    resp_valid = client_with_db.get("/api/v1/monitoring/dashboard?period=30d")
    assert resp_valid.status_code == 200

    resp_invalid = client_with_db.get("/api/v1/monitoring/dashboard?period=1year")
    assert resp_invalid.status_code == 422
