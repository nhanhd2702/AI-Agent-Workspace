"""LLM Provider Routing, Exponential Backoff, Fallback, and Usage Tracking (Task 2.2).

Implements:
- Provider abstraction with ProviderError.
- MockProviderRegistry supporting fail_once, set_failures, custom responses, and usage omission.
- LlmResponse dataclass tracking execution metrics, tokens, and fallback actions.
- LlmRouter:
  - Quota enforcement before dispatch.
  - Automatic retry with exponential backoff on 5xx errors.
  - Immediate fallback on 429 rate limits (or retrying when no fallback is configured).
  - TurnLog recording on model fallback.
  - UsageRecord recording with local token estimation fallback when metadata is omitted.
  - Both async complete(agent: Agent, ...) and complete_sync(...) interfaces.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import time
from typing import Any, Callable, Optional
import uuid

logger = logging.getLogger(__name__)

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Agent, Task, TurnLog
from app.llm.usage import (
    QuotaExceededError,
    QuotaService,
    calculate_cost_usd,
    estimate_tokens,
)


# ============================================================================
# Provider Error & Domain Models
# ============================================================================


class ProviderError(Exception):
    """Exception raised when an upstream LLM provider fails."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        model: Optional[str] = None,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.model = model
        self.details = details


@dataclass
class LlmResponse:
    """Execution output and token accounting metadata returned by LlmRouter."""

    content: str
    model_used: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    is_estimated: bool = False
    fallback_triggered: bool = False
    attempts: int = 1
    provider_error_history: list[dict[str, Any]] = field(default_factory=list)


# ============================================================================
# MockProviderRegistry (for testing & local offline runs)
# ============================================================================


class MockProviderRegistry:
    """Configurable provider client registry simulating LLM responses and errors."""

    def __init__(self) -> None:
        # Failure queues per model: model -> list of status_codes
        self._failures: dict[str, list[int]] = {}
        # Custom fixed responses per model: model -> dict
        self._custom_responses: dict[str, dict[str, Any]] = {}
        # Call history for assertions
        self.calls: list[dict[str, Any]] = []

    def fail_once(self, model: str, status: int = 429) -> None:
        """Configure provider to fail on the next call for model with given status code."""
        self._failures.setdefault(model, []).append(status)

    def set_failures(self, model: str, count: int, status: int = 500) -> None:
        """Configure provider to fail count consecutive times for model."""
        self._failures.setdefault(model, []).extend([status] * count)

    def set_custom_response(
        self,
        model: str,
        content: str,
        usage: Optional[dict[str, int]] = ...,  # type: ignore[assignment]
    ) -> None:
        """Configure a custom response payload (e.g. usage=None for token estimation)."""
        payload: dict[str, Any] = {"content": content}
        if usage is not ...:
            payload["usage"] = usage
        self._custom_responses[model] = payload

    def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Simulate LLM model completion call."""
        self.calls.append({"model": model, "messages": messages, "kwargs": kwargs})

        # Check configured failures
        if model in self._failures and self._failures[model]:
            status_code = self._failures[model].pop(0)
            raise ProviderError(
                f"Simulated error from provider '{model}': HTTP {status_code}",
                status_code=status_code,
                model=model,
            )

        # Check configured custom responses
        if model in self._custom_responses:
            resp = dict(self._custom_responses[model])
            resp.setdefault("model", model)
            return resp

        # Default synthetic response
        last_msg = messages[-1].get("content", "") if messages else ""
        prompt_len = sum(len(str(m.get("content", ""))) for m in messages)
        content = f"Synthetic response from {model} for: {last_msg}"

        return {
            "content": content,
            "model": model,
            "usage": {
                "input_tokens": max(1, prompt_len // 4),
                "output_tokens": max(1, len(content) // 4),
                "cached_tokens": 0,
            },
        }

    def __call__(
        self, model: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        return self.complete(model, messages, **kwargs)


# ============================================================================
# LlmRouter
# ============================================================================


class LlmRouter:
    """Smart LLM router handling quota guards, retries, model fallback, and accounting."""

    def __init__(
        self,
        providers: Any = None,
        quota_service: Optional[QuotaService] = None,
        max_retries: int = 2,
        base_delay: float = 0.5,
        sleep_fn: Optional[Callable[[float], None]] = None,
        retry_429_before_fallback: bool = False,
    ) -> None:
        self.providers = providers if providers is not None else MockProviderRegistry()
        self.quota_service = quota_service or QuotaService()
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.sleep_fn = sleep_fn
        self.retry_429_before_fallback = retry_429_before_fallback

    def _sleep(self, seconds: float) -> None:
        """Invoke injectable sleep function or system time.sleep."""
        if self.sleep_fn is not None:
            self.sleep_fn(seconds)
        else:
            time.sleep(seconds)

    def _call_raw_provider(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Dispatch call to underlying provider client or registry."""
        if hasattr(self.providers, "complete") and callable(self.providers.complete):
            return self.providers.complete(model, messages, **kwargs)
        if callable(self.providers):
            return self.providers(model, messages, **kwargs)
        if isinstance(self.providers, dict) and model in self.providers:
            caller = self.providers[model]
            return caller(messages, **kwargs) if callable(caller) else caller
        raise ProviderError(f"No configured provider client for model '{model}'", status_code=500, model=model)

    def complete_sync(
        self,
        primary: str,
        fallback: Optional[str] = None,
        messages: Optional[list[dict[str, Any]]] = None,
        db: Optional[Session] = None,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **kwargs: Any,
    ) -> LlmResponse:
        """Synchronously execute LLM completion with quota guard, retries, and fallback."""
        messages = messages or []

        # 1. Enforce quota prior to calling external LLM
        if db is not None:
            self.quota_service.enforce_quota(db)

        attempts = 0
        provider_error_history: list[dict[str, Any]] = []
        model_used = primary
        fallback_triggered = False
        raw_response: Optional[dict[str, Any]] = None

        # 2. Primary model execution loop with exponential backoff
        primary_succeeded = False
        for attempt_idx in range(self.max_retries + 1):
            attempts += 1
            try:
                raw_response = self._call_raw_provider(primary, messages, **kwargs)
                primary_succeeded = True
                model_used = primary
                break
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                if status_code is None:
                    status_code = 429 if "429" in str(exc) else 500

                err_entry = {
                    "model": primary,
                    "attempt": attempt_idx + 1,
                    "status_code": status_code,
                    "error": str(exc),
                }
                provider_error_history.append(err_entry)

                # 429 immediate failover policy: if fallback model is configured and
                # retry_429_before_fallback is False, switch immediately to fallback.
                if status_code == 429 and fallback and not self.retry_429_before_fallback:
                    break

                # If more retries remain, back off exponentially: base_delay * (2 ** attempt_idx)
                if attempt_idx < self.max_retries:
                    delay = self.base_delay * (2**attempt_idx)
                    self._sleep(delay)
                else:
                    break

        # 3. Fallback model execution if primary failed
        if not primary_succeeded:
            if not fallback:
                last_err = provider_error_history[-1] if provider_error_history else {}
                raise ProviderError(
                    f"Model '{primary}' failed after {attempts} attempts: {last_err.get('error', 'unknown error')}",
                    status_code=last_err.get("status_code", 500),
                    model=primary,
                    details=provider_error_history,
                )

            fallback_triggered = True
            model_used = fallback
            fallback_succeeded = False

            for fb_attempt_idx in range(self.max_retries + 1):
                attempts += 1
                try:
                    raw_response = self._call_raw_provider(fallback, messages, **kwargs)
                    fallback_succeeded = True
                    break
                except Exception as fb_exc:
                    fb_status = getattr(fb_exc, "status_code", None)
                    if fb_status is None:
                        fb_status = 429 if "429" in str(fb_exc) else 500

                    err_entry = {
                        "model": fallback,
                        "attempt": fb_attempt_idx + 1,
                        "status_code": fb_status,
                        "error": str(fb_exc),
                    }
                    provider_error_history.append(err_entry)

                    if fb_attempt_idx < self.max_retries:
                        delay = self.base_delay * (2**fb_attempt_idx)
                        self._sleep(delay)
                    else:
                        break

            if not fallback_succeeded:
                last_err = provider_error_history[-1] if provider_error_history else {}
                raise ProviderError(
                    f"Fallback model '{fallback}' failed after retries: {last_err.get('error', 'unknown error')}",
                    status_code=last_err.get("status_code", 500),
                    model=fallback,
                    details=provider_error_history,
                )

        # 4. Extract content and token usage metadata
        raw_response = raw_response or {}
        content = str(raw_response.get("content", ""))
        usage = raw_response.get("usage")

        # Resolve usage tokens: support both standard input/output_tokens and OpenAI prompt/completion_tokens
        in_tok = None
        out_tok = None
        if usage and isinstance(usage, dict):
            in_tok = (
                usage.get("input_tokens")
                if usage.get("input_tokens") is not None
                else usage.get("prompt_tokens")
            )
            out_tok = (
                usage.get("output_tokens")
                if usage.get("output_tokens") is not None
                else usage.get("completion_tokens")
            )

        if in_tok is not None and out_tok is not None:
            input_tokens = int(in_tok)
            output_tokens = int(out_tok)
            cached_tokens = int(usage.get("cached_tokens", 0) or 0)
            is_estimated = False
        else:
            # Fallback to local token estimation len(text) // 4
            prompt_text = " ".join(
                str(m.get("content", "")) for m in messages if isinstance(m, dict)
            )
            input_tokens = estimate_tokens(prompt_text)
            output_tokens = estimate_tokens(content)
            cached_tokens = 0
            is_estimated = True

        total_tokens = input_tokens + output_tokens + cached_tokens
        cost_usd = calculate_cost_usd(model_used, input_tokens, output_tokens)

        # 5. Log fallback TurnLog entry when task exists in database
        turn_log_id: Optional[str] = None
        if fallback_triggered and db is not None and task_id:
            task = db.get(Task, task_id)
            if task:
                resolved_agent_id: Optional[str] = None
                if agent_id:
                    a = db.get(Agent, agent_id) or (
                        db.query(Agent)
                        .filter(func.lower(Agent.name) == agent_id.lower())
                        .first()
                    )
                    if a:
                        resolved_agent_id = a.id

                current_turns = db.query(TurnLog).filter_by(task_id=task_id).count()
                turn_log = TurnLog(
                    id=f"turn-{uuid.uuid4().hex[:12]}",
                    task_id=task_id,
                    agent_id=resolved_agent_id,
                    turn_number=current_turns + 1,
                    action="fallback_model",
                    tool="llm_router",
                    input_payload={
                        "primary": primary,
                        "fallback": fallback,
                        "error_history": provider_error_history,
                    },
                    output_payload={
                        "selected_model": fallback,
                        "status": "switched",
                    },
                    tokens=total_tokens,
                    status="completed",
                    created_at=datetime.now(timezone.utc),
                )
                try:
                    db.add(turn_log)
                    db.commit()
                    db.refresh(turn_log)
                    turn_log_id = turn_log.id
                except Exception as log_exc:
                    db.rollback()
                    logger.warning("Failed to record fallback TurnLog: %s", log_exc)
                    turn_log_id = None

        # 6. Record UsageRecord in database via QuotaService
        if db is not None:
            self.quota_service.record_cost(
                db=db,
                task_id=task_id,
                agent_id=agent_id,
                model=model_used,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                cost_usd=cost_usd,
                is_estimated=is_estimated,
                turn_log_id=turn_log_id,
            )

        return LlmResponse(
            content=content,
            model_used=model_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            is_estimated=is_estimated,
            fallback_triggered=fallback_triggered,
            attempts=attempts,
            provider_error_history=provider_error_history,
        )

    async def complete(
        self,
        agent: Agent | str,
        messages: list[dict[str, Any]],
        db: Optional[Session] = None,
        task_id: Optional[str] = None,
        **kwargs: Any,
    ) -> LlmResponse:
        """Asynchronously dispatch completion request for an Agent or model name."""
        if isinstance(agent, Agent):
            primary = agent.default_model or "gemini-2.5-flash"
            fallback = agent.fallback_model
            agent_id = agent.id
        else:
            primary = str(agent)
            fallback = kwargs.pop("fallback", None)
            agent_id = kwargs.pop("agent_id", str(agent))

        # Offload sync complete execution safely to asyncio threadpool
        return await asyncio.to_thread(
            self.complete_sync,
            primary=primary,
            fallback=fallback,
            messages=messages,
            db=db,
            task_id=task_id,
            agent_id=agent_id,
            **kwargs,
        )
