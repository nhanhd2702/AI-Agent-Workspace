"""Monitoring API endpoints for Token Usage, LLM Cost, Quota Guard, and Monitoring Dashboard (F01.5 / F11.2).

Implements:
- GET /api/v1/monitoring/usage: token & cost aggregation across periods ('today', '7d', '30d', 'all')
  with quota state, summary metrics, breakdowns by model & agent, and recent usage history.
- GET /api/v1/monitoring/dashboard: comprehensive dashboard metrics (KPI summary, agent/model breakdown,
  daily trends series, task success rates, and quota status).
- GET /api/v1/monitoring/export.csv: export usage records as sanitized CSV disarming formula injection.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import io
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db.models import Agent, Task, TaskStatus, UsageRecord
from app.db.session import get_db
from app.llm.usage import QuotaService

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


def _format_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    """Serialize datetime as ISO-8601 string normalized with UTC timezone offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def _sanitize_csv_cell(value: Any) -> Any:
    """Disarm formula injection in CSV text cells (=, +, -, @, \\t, \\r)."""
    if value is None:
        return ""
    val_str = str(value)
    stripped = val_str.lstrip()
    if stripped and stripped[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{val_str}"
    return val_str


@router.get("/usage", status_code=status.HTTP_200_OK)
def get_usage_metrics(
    period: str = Query(default="today", pattern="^(today|7d|30d|all)$"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve token consumption, USD spend, quota status, and dimensional breakdowns."""
    now = datetime.now(timezone.utc)
    start_time: Optional[datetime] = None

    if period == "today":
        start_time = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)
    elif period == "7d":
        start_time = now - timedelta(days=7)
    elif period == "30d":
        start_time = now - timedelta(days=30)
    elif period == "all":
        start_time = None

    query = db.query(UsageRecord)
    if start_time is not None:
        query = query.filter(UsageRecord.created_at >= start_time)

    records = query.order_by(UsageRecord.created_at.desc()).all()

    # Summary metrics calculation
    total_requests = len(records)
    prompt_tokens = sum(r.prompt_tokens for r in records)
    completion_tokens = sum(r.completion_tokens for r in records)
    cached_tokens = sum(r.cached_tokens for r in records)
    total_tokens = sum(r.total_tokens for r in records)
    total_cost_usd = round(sum(r.cost_usd for r in records), 6)
    is_estimated_count = sum(1 for r in records if r.is_estimated)

    summary = {
        "total_requests": total_requests,
        "total_tokens": total_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_tokens": cached_tokens,
        "total_cost_usd": total_cost_usd,
        "is_estimated_count": is_estimated_count,
    }

    # Breakdown by Model
    model_groups: dict[str, dict[str, Any]] = {}
    for r in records:
        m_name = r.model_name or "unknown"
        if m_name not in model_groups:
            model_groups[m_name] = {
                "model_name": m_name,
                "requests": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
            }
        model_groups[m_name]["requests"] += 1
        model_groups[m_name]["total_tokens"] += r.total_tokens
        model_groups[m_name]["cost_usd"] = round(
            model_groups[m_name]["cost_usd"] + r.cost_usd, 6
        )
    by_model = sorted(model_groups.values(), key=lambda x: x["cost_usd"], reverse=True)

    # Breakdown by Agent
    agent_cache: dict[str, str] = {}
    agent_groups: dict[str, dict[str, Any]] = {}
    for r in records:
        ag_id = r.agent_id or "unassigned"
        if ag_id not in agent_groups:
            if ag_id != "unassigned" and ag_id not in agent_cache:
                ag = db.get(Agent, ag_id)
                agent_cache[ag_id] = ag.display_name if ag else ag_id
            ag_name = agent_cache.get(ag_id, "Chưa chỉ định" if ag_id == "unassigned" else ag_id)

            agent_groups[ag_id] = {
                "agent_id": ag_id,
                "agent_name": ag_name,
                "requests": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
            }
        agent_groups[ag_id]["requests"] += 1
        agent_groups[ag_id]["total_tokens"] += r.total_tokens
        agent_groups[ag_id]["cost_usd"] = round(
            agent_groups[ag_id]["cost_usd"] + r.cost_usd, 6
        )
    by_agent = sorted(agent_groups.values(), key=lambda x: x["cost_usd"], reverse=True)

    # Daily Quota Status
    quota_svc = QuotaService()
    quota_status = quota_svc.check_quota(db)

    # Recent serialized records (up to 50 latest)
    recent_records = [
        {
            "id": r.id,
            "task_id": r.task_id,
            "agent_id": r.agent_id,
            "turn_log_id": r.turn_log_id,
            "model_name": r.model_name,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "cached_tokens": r.cached_tokens,
            "total_tokens": r.total_tokens,
            "cost_usd": round(r.cost_usd, 6),
            "is_estimated": r.is_estimated,
            "created_at": _format_utc_iso(r.created_at),
        }
        for r in records[:50]
    ]

    return {
        "status": "success",
        "data": {
            "period": period,
            "quota": quota_status.to_dict(),
            "summary": summary,
            "by_model": by_model,
            "by_agent": by_agent,
            "recent_records": recent_records,
        },
    }


@router.get("/dashboard", status_code=status.HTTP_200_OK)
def get_monitoring_dashboard(
    period: str = Query(default="7d", pattern="^(today|7d|30d|all)$"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve high-level dashboard metrics, daily trends, agent/model breakdown, and task stats."""
    now = datetime.now(timezone.utc)
    start_time: Optional[datetime] = None

    if period == "today":
        start_time = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)
    elif period == "7d":
        start_time = now - timedelta(days=7)
    elif period == "30d":
        start_time = now - timedelta(days=30)
    elif period == "all":
        start_time = None

    # 1. Query UsageRecords
    usage_query = db.query(UsageRecord)
    if start_time is not None:
        usage_query = usage_query.filter(UsageRecord.created_at >= start_time)
    records = usage_query.order_by(UsageRecord.created_at.desc()).all()

    total_requests = len(records)
    prompt_tokens = sum(r.prompt_tokens for r in records)
    completion_tokens = sum(r.completion_tokens for r in records)
    total_tokens = sum(r.total_tokens for r in records)
    total_cost_usd = round(sum(r.cost_usd for r in records), 6)

    # 2. Breakdown by Agent
    agent_cache: dict[str, str] = {}
    agent_groups: dict[str, dict[str, Any]] = {}
    for r in records:
        ag_id = r.agent_id or "unassigned"
        if ag_id not in agent_groups:
            if ag_id != "unassigned" and ag_id not in agent_cache:
                ag = db.get(Agent, ag_id)
                agent_cache[ag_id] = ag.display_name if ag else ag_id
            ag_name = agent_cache.get(ag_id, "Chưa chỉ định" if ag_id == "unassigned" else ag_id)

            agent_groups[ag_id] = {
                "agent_id": ag_id,
                "agent_name": ag_name,
                "requests": 0,
                "tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "percentage": 0.0,
            }
        agent_groups[ag_id]["requests"] += 1
        agent_groups[ag_id]["tokens"] += r.total_tokens
        agent_groups[ag_id]["total_tokens"] += r.total_tokens
        agent_groups[ag_id]["cost_usd"] = round(
            agent_groups[ag_id]["cost_usd"] + r.cost_usd, 6
        )

    for ag_item in agent_groups.values():
        if total_cost_usd > 0:
            ag_item["percentage"] = round((ag_item["cost_usd"] / total_cost_usd) * 100, 2)
        elif total_tokens > 0:
            ag_item["percentage"] = round((ag_item["tokens"] / total_tokens) * 100, 2)
        else:
            ag_item["percentage"] = 0.0

    by_agent = sorted(agent_groups.values(), key=lambda x: x["cost_usd"], reverse=True)

    # 3. Breakdown by Model
    model_groups: dict[str, dict[str, Any]] = {}
    for r in records:
        m_name = r.model_name or "unknown"
        if m_name not in model_groups:
            model_groups[m_name] = {
                "model_name": m_name,
                "requests": 0,
                "tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
            }
        model_groups[m_name]["requests"] += 1
        model_groups[m_name]["tokens"] += r.total_tokens
        model_groups[m_name]["total_tokens"] += r.total_tokens
        model_groups[m_name]["cost_usd"] = round(
            model_groups[m_name]["cost_usd"] + r.cost_usd, 6
        )
    by_model = sorted(model_groups.values(), key=lambda x: x["cost_usd"], reverse=True)

    # 4. Daily Trends Series
    if period == "today":
        date_keys = [now.strftime("%Y-%m-%d")]
    elif period == "7d":
        date_keys = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in reversed(range(7))]
    elif period == "30d":
        date_keys = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in reversed(range(30))]
    else:
        # 'all': extract dates present in records
        seen_dates = set()
        for r in records:
            r_dt = r.created_at.astimezone(timezone.utc) if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
            seen_dates.add(r_dt.strftime("%Y-%m-%d"))
        date_keys = sorted(seen_dates) if seen_dates else [now.strftime("%Y-%m-%d")]

    trend_map: dict[str, dict[str, Any]] = {
        d: {"date": d, "tokens": 0, "cost_usd": 0.0, "requests": 0}
        for d in date_keys
    }

    for r in records:
        r_dt = r.created_at.astimezone(timezone.utc) if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
        d_str = r_dt.strftime("%Y-%m-%d")
        if d_str not in trend_map:
            trend_map[d_str] = {"date": d_str, "tokens": 0, "cost_usd": 0.0, "requests": 0}
        trend_map[d_str]["tokens"] += r.total_tokens
        trend_map[d_str]["cost_usd"] = round(trend_map[d_str]["cost_usd"] + r.cost_usd, 6)
        trend_map[d_str]["requests"] += 1

    daily_trends = sorted(trend_map.values(), key=lambda x: x["date"])

    # 5. Task Success Rate & Stats
    task_query = db.query(Task)
    if start_time is not None:
        task_query = task_query.filter(Task.created_at >= start_time)
    tasks = task_query.all()

    total_tasks = len(tasks)
    completed_tasks = sum(1 for t in tasks if t.status in (TaskStatus.COMPLETED, TaskStatus.DELIVERED))
    failed_tasks = sum(1 for t in tasks if t.status in (TaskStatus.FAILED, TaskStatus.REJECTED, TaskStatus.CANCELLED))
    in_progress_tasks = sum(1 for t in tasks if t.status in (TaskStatus.RUNNING, TaskStatus.PENDING, TaskStatus.WAITING_REVIEW, TaskStatus.APPROVED, TaskStatus.PAUSED))

    success_rate_pct = round((completed_tasks / total_tasks) * 100, 2) if total_tasks > 0 else 0.0

    task_stats = {
        "total": total_tasks,
        "total_tasks": total_tasks,
        "completed": completed_tasks,
        "completed_tasks": completed_tasks,
        "failed": failed_tasks,
        "failed_tasks": failed_tasks,
        "in_progress": in_progress_tasks,
        "success_rate_pct": success_rate_pct,
    }

    # 6. Daily Quota
    quota_svc = QuotaService()
    quota_status = quota_svc.check_quota(db)

    return {
        "status": "success",
        "data": {
            "period": period,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost_usd,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_requests": total_requests,
            "by_agent": by_agent,
            "by_model": by_model,
            "daily_trends": daily_trends,
            "task_stats": task_stats,
            "quota": quota_status.to_dict(),
        },
    }


@router.get("/export.csv", status_code=status.HTTP_200_OK)
def export_usage_csv(
    period: str = Query(default="7d", pattern="^(today|7d|30d|all)$"),
    db: Session = Depends(get_db),
) -> Response:
    """Export detailed token usage records within period as sanitized CSV."""
    now = datetime.now(timezone.utc)
    start_time: Optional[datetime] = None

    if period == "today":
        start_time = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)
    elif period == "7d":
        start_time = now - timedelta(days=7)
    elif period == "30d":
        start_time = now - timedelta(days=30)
    elif period == "all":
        start_time = None

    query = db.query(UsageRecord)
    if start_time is not None:
        query = query.filter(UsageRecord.created_at >= start_time)

    records = query.order_by(UsageRecord.created_at.desc()).all()

    # Pre-populate agent display names
    agent_cache: dict[str, str] = {}
    for r in records:
        if r.agent_id and r.agent_id not in agent_cache:
            ag = db.get(Agent, r.agent_id)
            agent_cache[r.agent_id] = ag.display_name if ag else r.agent_id

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
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
    ])

    for r in records:
        ag_name = agent_cache.get(r.agent_id or "", r.agent_id or "")
        writer.writerow([
            _format_utc_iso(r.created_at) or "",
            _sanitize_csv_cell(r.task_id or ""),
            _sanitize_csv_cell(r.agent_id or ""),
            _sanitize_csv_cell(ag_name),
            _sanitize_csv_cell(r.model_name or ""),
            r.prompt_tokens,
            r.completion_tokens,
            r.total_tokens,
            round(r.cost_usd, 6),
            r.is_estimated,
        ])

    csv_text = output.getvalue()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=usage_export_{period}.csv",
        },
    )
