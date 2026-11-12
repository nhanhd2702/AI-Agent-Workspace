"""Monitoring API endpoints for Token Usage, LLM Cost, and Quota Guard (F01.5 / F11.2).

Implements:
- GET /api/v1/monitoring/usage: token & cost aggregation across periods ('today', '7d', '30d', 'all')
  with quota state, summary metrics, breakdowns by model & agent, and recent usage history.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.models import Agent, UsageRecord
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
