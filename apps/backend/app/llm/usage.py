"""Token accounting, cost calculation, and quota guard service (Task 2.2).

Implements:
- PRICING_PER_1M_TOKENS pricing table for commercial and local models.
- Exact cost calculation per provider token rates.
- Local character-based token estimation fallback when metadata is omitted.
- QuotaStatus and QuotaExceededError.
- QuotaService: UTC day boundary checking, 80% warning flag, 100% hard block,
  and robust FK resolution for UsageRecord.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Agent, Task, TurnLog, UsageRecord, UserSettings


# ============================================================================
# Pricing Table (USD per 1,000,000 tokens)
# ============================================================================

PRICING_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    # Gemini models
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    # Anthropic Claude models
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-7-sonnet": {"input": 3.00, "output": 15.00},
    # OpenAI GPT models
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # Default fallback rate for unknown commercial models
    "default": {"input": 1.00, "output": 3.00},
}


def calculate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate exact USD cost for prompt and completion token counts.

    Local models (ollama/*) are free (0.0 USD). Unknown models fall back to default pricing.
    """
    normalized = (model or "").lower().strip()
    if normalized.startswith("ollama/") or normalized.startswith("ollama"):
        return 0.0

    rates = PRICING_PER_1M_TOKENS.get(normalized, PRICING_PER_1M_TOKENS["default"])
    cost = (input_tokens / 1_000_000.0) * rates["input"] + (
        output_tokens / 1_000_000.0
    ) * rates["output"]
    return round(cost, 8)


def estimate_tokens(text: Optional[str]) -> int:
    """Fallback character-based token estimation when provider stream drops usage metadata.

    Approximates ~4 characters per token (max(1, len(text) // 4) for non-empty text, 0 if empty).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


# ============================================================================
# Quota Domain Types & Errors
# ============================================================================


class QuotaExceededError(RuntimeError):
    """Raised when daily spend reaches or exceeds the configured daily_usd_limit."""

    pass


@dataclass
class QuotaStatus:
    """Current daily spending quota state and warning triggers."""

    daily_limit_usd: float
    spent_today_usd: float
    remaining_usd: float
    utilization_pct: float
    warning_triggered: bool
    exceeded: bool
    total_tokens_today: int
    as_of: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily_limit_usd": round(self.daily_limit_usd, 4),
            "spent_today_usd": round(self.spent_today_usd, 4),
            "remaining_usd": round(self.remaining_usd, 4),
            "utilization_pct": round(self.utilization_pct, 2),
            "warning_triggered": self.warning_triggered,
            "exceeded": self.exceeded,
            "total_tokens_today": self.total_tokens_today,
            "as_of": self.as_of.isoformat() if self.as_of else None,
        }


def get_utc_day_start() -> datetime:
    """Return midnight 00:00:00 UTC for the current day."""
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)


# ============================================================================
# QuotaService
# ============================================================================


class QuotaService:
    """Service to track token usage, record cost, and enforce daily spending limits."""

    def __init__(self, daily_limit_usd: Optional[float] = None) -> None:
        self._daily_limit_usd = daily_limit_usd

    def get_daily_limit(self, db: Optional[Session] = None) -> float:
        """Resolve daily spend limit from instance override or UserSettings in database."""
        if self._daily_limit_usd is not None:
            return float(self._daily_limit_usd)
        if db is not None:
            settings = db.get(UserSettings, "settings-default")
            if settings and settings.daily_usd_limit is not None:
                return float(settings.daily_usd_limit)
        return 10.0  # Default 10.0 USD from seed_defaults

    def record_cost(
        self,
        db: Session,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        model: str = "gemini-2.5-flash",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        cost_usd: Optional[float] = None,
        is_estimated: bool = False,
        turn_log_id: Optional[str] = None,
    ) -> UsageRecord:
        """Record token usage and cost in database with clean foreign key resolution."""
        # 1. Resolve agent_id: accept either agent.id or agent.name (e.g. 'Commander')
        resolved_agent_id: Optional[str] = None
        if agent_id:
            agent = db.get(Agent, agent_id)
            if agent:
                resolved_agent_id = agent.id
            else:
                agent_by_name = (
                    db.query(Agent)
                    .filter(func.lower(Agent.name) == agent_id.lower())
                    .first()
                )
                if agent_by_name:
                    resolved_agent_id = agent_by_name.id
                else:
                    resolved_agent_id = None

        # 2. Resolve task_id: verify Task exists to prevent SQLite FK constraint failure
        resolved_task_id: Optional[str] = None
        if task_id:
            task = db.get(Task, task_id)
            if task:
                resolved_task_id = task.id
            else:
                resolved_task_id = None

        # 3. Resolve turn_log_id: verify TurnLog exists if provided
        resolved_turn_log_id: Optional[str] = None
        if turn_log_id:
            turn_log = db.get(TurnLog, turn_log_id)
            if turn_log:
                resolved_turn_log_id = turn_log.id
            else:
                resolved_turn_log_id = None

        # 4. Calculate cost if not explicitly passed
        computed_cost = (
            cost_usd
            if cost_usd is not None
            else calculate_cost_usd(model, input_tokens, output_tokens)
        )
        total_tokens = input_tokens + output_tokens + cached_tokens

        record = UsageRecord(
            id=f"usage-{uuid.uuid4().hex[:12]}",
            task_id=resolved_task_id,
            agent_id=resolved_agent_id,
            turn_log_id=resolved_turn_log_id,
            model_name=model,
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            cached_tokens=cached_tokens,
            total_tokens=total_tokens,
            cost_usd=float(computed_cost),
            is_estimated=is_estimated,
            created_at=datetime.now(timezone.utc),
        )

        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def check_quota(self, db: Session) -> QuotaStatus:
        """Check current day spend vs daily limit, evaluating warning and exceeded triggers."""
        daily_limit = self.get_daily_limit(db)
        day_start = get_utc_day_start()

        records = (
            db.query(UsageRecord)
            .filter(UsageRecord.created_at >= day_start)
            .all()
        )

        spent_today = sum(r.cost_usd for r in records)
        tokens_today = sum(r.total_tokens for r in records)

        utilization_pct = (spent_today / daily_limit * 100.0) if daily_limit > 0 else 0.0
        warning_triggered = spent_today >= (0.80 * daily_limit)
        exceeded = spent_today >= daily_limit
        remaining_usd = max(0.0, daily_limit - spent_today)

        return QuotaStatus(
            daily_limit_usd=daily_limit,
            spent_today_usd=spent_today,
            remaining_usd=remaining_usd,
            utilization_pct=utilization_pct,
            warning_triggered=warning_triggered,
            exceeded=exceeded,
            total_tokens_today=tokens_today,
            as_of=datetime.now(timezone.utc),
        )

    def enforce_quota(self, db: Session) -> QuotaStatus:
        """Evaluate quota and raise QuotaExceededError if spend reaches or exceeds daily limit."""
        status = self.check_quota(db)
        if status.exceeded:
            raise QuotaExceededError(
                f"Daily spending quota exceeded: ${status.spent_today_usd:.4f} spent today "
                f"exceeds limit of ${status.daily_limit_usd:.4f}."
            )
        return status
