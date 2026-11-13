"""Multi-channel Messaging Bridge and Race-Safe Human Takeover System (Task 4.6).

Provides:
- TokenBucketRateLimiter (30 tokens/min default enforced per channel account)
- MockChannelAdapter, ZaloChannelAdapter, TelegramChannelAdapter
- MessagingBridge with race-safe per-conversation generation tracking and human takeover/release
- Deduplication via client_message_id
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
from typing import Any, Optional
import uuid

from sqlalchemy.orm import Session

from app.db.models import Conversation, Message


class TokenBucketRateLimiter:
    """Per-account token-bucket rate limiter (default 30 msgs/min)."""

    def __init__(self, rate_per_min: float = 30.0, capacity: float | None = None) -> None:
        self.rate_per_min = float(rate_per_min)
        self.capacity = float(capacity if capacity is not None else rate_per_min)
        self._tokens: dict[str, float] = {}
        self._last_check: dict[str, float] = {}

    def acquire(self, account_id: str, tokens: float = 1.0) -> bool:
        """Attempt to acquire specified tokens for an account. Return True if granted."""
        now = time.monotonic()
        if account_id not in self._last_check:
            self._tokens[account_id] = self.capacity
            self._last_check[account_id] = now
        else:
            elapsed = now - self._last_check[account_id]
            self._last_check[account_id] = now
            # Replenish rate: tokens per second = rate_per_min / 60
            replenished = elapsed * (self.rate_per_min / 60.0)
            self._tokens[account_id] = min(
                self.capacity,
                self._tokens[account_id] + replenished,
            )

        if self._tokens[account_id] >= tokens:
            self._tokens[account_id] -= tokens
            return True
        return False


class BaseChannelAdapter:
    """Base class for social and messaging channel adapters."""

    def __init__(self, channel: str, account_id: str) -> None:
        self.channel = channel
        self.account_id = account_id

    async def send_message(
        self,
        conv_id: str,
        content: str,
        attachments: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError


class MockChannelAdapter(BaseChannelAdapter):
    """In-memory channel adapter for unit tests and local simulation."""

    def __init__(self, channel: str = "mock", account_id: str = "mock-acc-1") -> None:
        super().__init__(channel=channel, account_id=account_id)
        self.sent_messages: list[dict[str, Any]] = []

    async def send_message(
        self,
        conv_id: str,
        content: str,
        attachments: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        msg_record = {
            "id": f"mock-msg-{uuid.uuid4().hex[:8]}",
            "conv_id": conv_id,
            "content": content,
            "attachments": attachments or [],
            "channel": self.channel,
            "account_id": self.account_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "extra": kwargs,
        }
        self.sent_messages.append(msg_record)
        return {"status": "sent", "message_id": msg_record["id"], "record": msg_record}


class ZaloChannelAdapter(BaseChannelAdapter):
    """Adapter for Zalo Official Account (OA) messaging API."""

    def __init__(
        self,
        account_id: str = "zalo-oa-default",
        oa_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> None:
        super().__init__(channel="zalo", account_id=account_id)
        self.oa_id = oa_id or account_id
        self.access_token = access_token
        self.sent_messages: list[dict[str, Any]] = []

    async def send_message(
        self,
        conv_id: str,
        content: str,
        attachments: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Record sent message
        msg_record = {
            "id": f"zalo-msg-{uuid.uuid4().hex[:8]}",
            "conv_id": conv_id,
            "content": content,
            "attachments": attachments or [],
            "channel": "zalo",
            "oa_id": self.oa_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.sent_messages.append(msg_record)
        return {"status": "sent", "message_id": msg_record["id"]}


class TelegramChannelAdapter(BaseChannelAdapter):
    """Adapter for Telegram Bot messaging API."""

    def __init__(
        self,
        account_id: str = "telegram-bot-default",
        bot_token: Optional[str] = None,
    ) -> None:
        super().__init__(channel="telegram", account_id=account_id)
        self.bot_token = bot_token
        self.sent_messages: list[dict[str, Any]] = []

    async def send_message(
        self,
        conv_id: str,
        content: str,
        attachments: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        msg_record = {
            "id": f"tg-msg-{uuid.uuid4().hex[:8]}",
            "conv_id": conv_id,
            "content": content,
            "attachments": attachments or [],
            "channel": "telegram",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.sent_messages.append(msg_record)
        return {"status": "sent", "message_id": msg_record["id"]}


class MessagingBridge:
    """Multi-channel messaging bridge with race-safe human takeover generation tracking."""

    def __init__(
        self,
        db: Session,
        adapter: Optional[BaseChannelAdapter] = None,
        rate_limit_per_min: float = 30.0,
        event_bus: Optional[Any] = None,
    ) -> None:
        self.db = db
        self.adapter = adapter or MockChannelAdapter()
        self.rate_limiter = TokenBucketRateLimiter(rate_per_min=rate_limit_per_min)
        # Monotonically increasing generation per conversation to prevent race conditions
        self.takeover_generation: dict[str, int] = {}
        self.processed_client_ids: set[str] = set()
        self.event_bus = event_bus

    def human_takeover(self, conv_id: str) -> Optional[Conversation]:
        """Mark conversation as directly managed by human operator and increment generation."""
        self.takeover_generation[conv_id] = self.takeover_generation.get(conv_id, 0) + 1
        conv = self.db.get(Conversation, conv_id)
        if conv:
            conv.is_human_takeover = True
            conv.status = "in_progress"
            self.db.commit()
            self.db.refresh(conv)
        return conv

    def human_release(self, conv_id: str) -> Optional[Conversation]:
        """Release conversation back to AI automated assistant and advance generation."""
        self.takeover_generation[conv_id] = self.takeover_generation.get(conv_id, 0) + 1
        conv = self.db.get(Conversation, conv_id)
        if conv:
            conv.is_human_takeover = False
            self.db.commit()
            self.db.refresh(conv)
        return conv

    async def process_incoming_with_ai(
        self,
        conv_id: str,
        customer_msg: str,
        client_message_id: Optional[str] = None,
        delay_s: float = 0.0,
        force_escalate: bool = False,
        sender_id: Optional[str] = None,
        sender_name: Optional[str] = None,
        attachments: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Handle incoming customer message with race-safe generation check.

        If a human takes over during delay or AI processing, the AI draft reply is discarded.
        """
        # 1. Deduplication check
        if client_message_id:
            if client_message_id in self.processed_client_ids:
                return {
                    "status": "duplicate",
                    "message": "Duplicate message dropped via client_message_id",
                }
            self.processed_client_ids.add(client_message_id)

        # 2. Token-bucket rate limiter check
        acc_id = getattr(self.adapter, "account_id", "default")
        if not self.rate_limiter.acquire(acc_id):
            return {
                "status": "rate_limited",
                "message": "Rate limit exceeded (30 msg/min)",
            }

        # 3. Retrieve or create conversation
        conv = self.db.get(Conversation, conv_id)
        if not conv:
            conv = Conversation(
                id=conv_id,
                project_id="proj-default",
                channel=getattr(self.adapter, "channel", "internal"),
                participant_name=sender_name or "Khách hàng",
                status="open",
                is_human_takeover=False,
            )
            self.db.add(conv)
            self.db.commit()
            self.db.refresh(conv)

        # 4. Snapshot generation before async processing
        gen_before = self.takeover_generation.get(conv_id, 0)

        # 5. Persist incoming customer message
        msg_obj = Message(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            conversation_id=conv_id,
            sender_type="customer",
            sender_id=sender_id or conv.channel_conv_id or "customer",
            sender_name=sender_name or conv.participant_name or "Khách hàng",
            content=customer_msg,
            attachments=attachments or [],
            message_metadata={"client_message_id": client_message_id} if client_message_id else {},
        )
        self.db.add(msg_obj)
        self.db.commit()

        # 6. If conversation is already under human takeover, skip AI response
        if conv.is_human_takeover:
            return {
                "status": "human_handling",
                "message": "Conversation is currently handled by human operator",
            }

        # 7. Check for automatic escalation (force_escalate or complaint keywords)
        escalation_keywords = ["khiếu nại", "gặp quản lý", "lỗi vỡ", "hoàn tiền", "lừa đảo"]
        is_complaint = force_escalate or any(
            kw in customer_msg.lower() for kw in escalation_keywords
        )
        if is_complaint:
            self.takeover_generation[conv_id] = self.takeover_generation.get(conv_id, 0) + 1
            conv.is_human_takeover = True
            conv.status = "waiting"
            self.db.commit()

            esc_msg = Message(
                id=f"msg-{uuid.uuid4().hex[:8]}",
                conversation_id=conv_id,
                sender_type="system",
                content="[Hệ thống] Cuộc hội thoại đã tự động chuyển giao cho nhân viên trực tiếp xử lý.",
            )
            self.db.add(esc_msg)
            self.db.commit()
            return {
                "status": "escalated",
                "escalated": True,
                "message": "Escalated to human operator",
            }

        # 8. Async generation delay / LLM call simulation
        if delay_s > 0:
            await asyncio.sleep(delay_s)

        # 9. RACE CHECK: Verify generation hasn't changed and human takeover is NOT active
        gen_after = self.takeover_generation.get(conv_id, 0)
        conv = self.db.get(Conversation, conv_id)
        if gen_after != gen_before or (conv and conv.is_human_takeover):
            # Human took over during AI processing! Discard AI draft reply!
            return {
                "status": "cancelled_by_takeover",
                "message": "AI reply draft discarded because human takeover intervened",
            }

        # 10. Generate AI response and deliver via adapter
        ai_reply = self._generate_draft_reply(customer_msg)
        await self.adapter.send_message(conv_id=conv_id, content=ai_reply)

        ai_msg_obj = Message(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            conversation_id=conv_id,
            sender_type="agent",
            sender_id="agent-consultant",
            sender_name="Tư vấn viên AI",
            content=ai_reply,
        )
        self.db.add(ai_msg_obj)
        if conv:
            conv.status = "in_progress"
        self.db.commit()

        return {
            "status": "processed",
            "reply": ai_reply,
            "message_id": ai_msg_obj.id,
        }

    def _generate_draft_reply(self, query: str) -> str:
        """Generate helpful contextual customer service reply."""
        lower = query.lower()
        if "giá" in lower or "bao nhiêu" in lower:
            return "Dạ chào bạn, các sản phẩm hiện có mức giá ưu đãi từ 199.000đ - 499.000đ. Bạn đang quan tâm mẫu nào ạ?"
        if "bảo hành" in lower:
            return "Dạ sản phẩm bên em được bảo hành chính hãng 12 tháng, 1 đổi 1 trong 30 ngày nếu có lỗi sản xuất ạ."
        return "Dạ chào bạn! Em là trợ lý tư vấn AI, em có thể hỗ trợ thông tin gì cho bạn hôm nay ạ?"
