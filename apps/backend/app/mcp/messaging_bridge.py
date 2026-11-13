"""Multi-channel Messaging Bridge and Race-Safe Human Takeover System (Task 4.6).

Provides:
- TokenBucketRateLimiter (thread-safe, 30 tokens/min default enforced per channel account)
- MockChannelAdapter, ZaloChannelAdapter, TelegramChannelAdapter with secret masking
- MessagingBridge with race-safe per-conversation generation tracking and human takeover/release
- Deduplication via bounded client_message_id cache
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
import threading
import time
from typing import Any, Optional
import uuid

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Conversation, Message
from app.orchestrator.dispatcher import mask_secrets


class TokenBucketRateLimiter:
    """Per-account token-bucket rate limiter (default 30 msgs/min) with thread safety."""

    def __init__(self, rate_per_min: float = 30.0, capacity: float | None = None) -> None:
        self.rate_per_min = float(rate_per_min)
        self.capacity = float(capacity if capacity is not None else rate_per_min)
        self._tokens: dict[str, float] = {}
        self._last_check: dict[str, float] = {}
        self._lock = threading.Lock()

    def acquire(self, account_id: str, tokens: float = 1.0) -> bool:
        """Attempt to acquire specified tokens for an account. Return True if granted."""
        with self._lock:
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
        clean_content = mask_secrets(content)
        clean_attachments = mask_secrets(attachments) if attachments else []
        msg_record = {
            "id": f"mock-msg-{uuid.uuid4().hex[:8]}",
            "conv_id": conv_id,
            "content": clean_content,
            "attachments": clean_attachments,
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
        clean_content = mask_secrets(content)
        clean_attachments = mask_secrets(attachments) if attachments else []
        msg_record = {
            "id": f"zalo-msg-{uuid.uuid4().hex[:8]}",
            "conv_id": conv_id,
            "content": clean_content,
            "attachments": clean_attachments,
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
        clean_content = mask_secrets(content)
        clean_attachments = mask_secrets(attachments) if attachments else []
        msg_record = {
            "id": f"tg-msg-{uuid.uuid4().hex[:8]}",
            "conv_id": conv_id,
            "content": clean_content,
            "attachments": clean_attachments,
            "channel": "telegram",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.sent_messages.append(msg_record)
        return {"status": "sent", "message_id": msg_record["id"]}


class MessagingBridge:
    """Multi-channel messaging bridge with race-safe human takeover generation tracking."""

    def __init__(
        self,
        db: Optional[Session] = None,
        db_session_factory: Optional[sessionmaker] = None,
        adapter: Optional[BaseChannelAdapter] = None,
        rate_limit_per_min: float = 30.0,
        event_bus: Optional[Any] = None,
        max_dedup_size: int = 10000,
        retriever: Optional[Any] = None,
    ) -> None:
        self._db = db
        self.db_session_factory = db_session_factory
        self.adapter = adapter or MockChannelAdapter()
        self.adapters: dict[str, BaseChannelAdapter] = {}
        if adapter:
            self.adapters[getattr(adapter, "channel", "mock").lower()] = adapter
        self.rate_limiter = TokenBucketRateLimiter(rate_per_min=rate_limit_per_min)
        self.retriever = retriever
        # Monotonically increasing generation per conversation to prevent race conditions
        self.takeover_generation: dict[str, int] = {}
        self._processed_client_ids_set: set[str] = set()
        self._processed_client_ids_queue: deque[str] = deque()
        self._max_dedup_size = max_dedup_size
        self._dedup_lock = threading.Lock()
        self.event_bus = event_bus

    @property
    def db(self) -> Optional[Session]:
        return self._db

    @db.setter
    def db(self, session: Optional[Session]) -> None:
        self._db = session

    @property
    def processed_client_ids(self) -> set[str]:
        return self._processed_client_ids_set

    def register_adapter(self, channel: str, adapter: BaseChannelAdapter) -> None:
        """Register an adapter for a specific channel name."""
        self.adapters[channel.lower()] = adapter

    def get_adapter(self, channel: str) -> BaseChannelAdapter:
        """Get the adapter for a channel, falling back to default adapter."""
        return self.adapters.get(channel.lower(), self.adapter)

    def _get_db(self, db: Optional[Session] = None) -> Session:
        session = db if db is not None else self._db
        if session is None and self.db_session_factory is not None:
            session = self.db_session_factory()
        if session is None:
            raise ValueError("A database session is required for MessagingBridge operations")
        return session

    def _record_client_id(self, client_message_id: str) -> bool:
        """Record client message id in bounded cache. Return True if new, False if duplicate."""
        with self._dedup_lock:
            if client_message_id in self._processed_client_ids_set:
                return False
            if len(self._processed_client_ids_queue) >= self._max_dedup_size:
                oldest = self._processed_client_ids_queue.popleft()
                self._processed_client_ids_set.discard(oldest)
            self._processed_client_ids_queue.append(client_message_id)
            self._processed_client_ids_set.add(client_message_id)
            return True

    def human_takeover(self, conv_id: str, db: Optional[Session] = None) -> Optional[Conversation]:
        """Mark conversation as directly managed by human operator and increment generation."""
        session = self._get_db(db)
        self.takeover_generation[conv_id] = self.takeover_generation.get(conv_id, 0) + 1
        conv = session.get(Conversation, conv_id)
        if conv:
            conv.is_human_takeover = True
            conv.status = "in_progress"
            session.commit()
            session.refresh(conv)
        return conv

    def human_release(self, conv_id: str, db: Optional[Session] = None) -> Optional[Conversation]:
        """Release conversation back to AI automated assistant and advance generation."""
        session = self._get_db(db)
        self.takeover_generation[conv_id] = self.takeover_generation.get(conv_id, 0) + 1
        conv = session.get(Conversation, conv_id)
        if conv:
            conv.is_human_takeover = False
            session.commit()
            session.refresh(conv)
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
        db: Optional[Session] = None,
    ) -> dict[str, Any]:
        """Handle incoming customer message with race-safe generation check.

        If a human takes over during delay or AI processing, the AI draft reply is discarded.
        """
        session = self._get_db(db)

        # Redact secrets on input
        clean_customer_msg = mask_secrets(customer_msg)
        clean_attachments = mask_secrets(attachments) if attachments else []

        # 1. Deduplication check via bounded cache
        if client_message_id:
            if not self._record_client_id(client_message_id):
                return {
                    "status": "duplicate",
                    "message": "Duplicate message dropped via client_message_id",
                }

        # 2. Token-bucket rate limiter check
        adapter = self.get_adapter(getattr(self.adapter, "channel", "mock"))
        acc_id = getattr(adapter, "account_id", "default")
        if not self.rate_limiter.acquire(acc_id):
            return {
                "status": "rate_limited",
                "message": "Rate limit exceeded (30 msg/min)",
            }

        # 3. Retrieve or create conversation
        conv = session.get(Conversation, conv_id)
        if not conv:
            conv = Conversation(
                id=conv_id,
                project_id="proj-default",
                channel=getattr(adapter, "channel", "internal"),
                participant_name=sender_name or "Khách hàng",
                status="open",
                is_human_takeover=False,
            )
            session.add(conv)
            session.commit()
            session.refresh(conv)

        # 4. Snapshot generation before async processing
        gen_before = self.takeover_generation.get(conv_id, 0)

        # 5. Persist incoming customer message
        msg_obj = Message(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            conversation_id=conv_id,
            sender_type="customer",
            sender_id=sender_id or conv.channel_conv_id or "customer",
            sender_name=sender_name or conv.participant_name or "Khách hàng",
            content=clean_customer_msg,
            attachments=clean_attachments,
            message_metadata={"client_message_id": client_message_id} if client_message_id else {},
        )
        session.add(msg_obj)
        conv.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(msg_obj)

        if self.event_bus and hasattr(self.event_bus, "broadcast"):
            try:
                await self.event_bus.broadcast({
                    "type": "inbox.message",
                    "conversation_id": conv_id,
                    "message": {
                        "id": msg_obj.id,
                        "conversation_id": msg_obj.conversation_id,
                        "sender_type": msg_obj.sender_type,
                        "sender_id": msg_obj.sender_id,
                        "sender_name": msg_obj.sender_name,
                        "content": msg_obj.content,
                        "attachments": msg_obj.attachments or [],
                        "metadata": msg_obj.message_metadata or {},
                        "created_at": msg_obj.created_at.isoformat() if msg_obj.created_at else None,
                    },
                })
            except Exception:
                pass

        # 6. If conversation is already under human takeover, skip AI response
        if conv.is_human_takeover:
            return {
                "status": "human_handling",
                "message": "Conversation is currently handled by human operator",
            }

        # 7. Check for automatic escalation (force_escalate or complaint keywords)
        escalation_keywords = ["khiếu nại", "gặp quản lý", "lỗi vỡ", "hoàn tiền", "lừa đảo"]
        is_complaint = force_escalate or any(
            kw in clean_customer_msg.lower() for kw in escalation_keywords
        )
        if is_complaint:
            self.takeover_generation[conv_id] = self.takeover_generation.get(conv_id, 0) + 1
            conv.is_human_takeover = True
            conv.status = "waiting"
            session.commit()

            esc_msg = Message(
                id=f"msg-{uuid.uuid4().hex[:8]}",
                conversation_id=conv_id,
                sender_type="system",
                content="[Hệ thống] Cuộc hội thoại đã tự động chuyển giao cho nhân viên trực tiếp xử lý.",
            )
            session.add(esc_msg)
            session.commit()

            if self.event_bus and hasattr(self.event_bus, "broadcast"):
                try:
                    await self.event_bus.broadcast({
                        "type": "inbox.takeover",
                        "conversation_id": conv_id,
                        "is_human_takeover": True,
                    })
                except Exception:
                    pass

            return {
                "status": "escalated",
                "escalated": True,
                "message": "Escalated to human operator",
            }

        # 8. Broadcast AI start event
        if self.event_bus and hasattr(self.event_bus, "broadcast"):
            try:
                await self.event_bus.broadcast({
                    "type": "inbox.ai_start",
                    "conversation_id": conv_id,
                })
            except Exception:
                pass

        try:
            # 9. Async generation delay / LLM call simulation
            if delay_s > 0:
                await asyncio.sleep(delay_s)

            # 10. RACE CHECK: Verify generation hasn't changed and human takeover is NOT active
            # Expire & refresh to read latest DB state committed by concurrent requests
            try:
                session.expire(conv)
                session.refresh(conv)
            except Exception:
                conv = session.get(Conversation, conv_id)

            gen_after = self.takeover_generation.get(conv_id, 0)
            if gen_after != gen_before or (conv and conv.is_human_takeover):
                # Human took over during AI processing! Discard AI draft reply!
                return {
                    "status": "cancelled_by_takeover",
                    "message": "AI reply draft discarded because human takeover intervened",
                }

            # 11. Generate AI response and deliver via adapter
            ai_reply = mask_secrets(self._generate_draft_reply(clean_customer_msg))
            await adapter.send_message(conv_id=conv_id, content=ai_reply)

            ai_msg_obj = Message(
                id=f"msg-{uuid.uuid4().hex[:8]}",
                conversation_id=conv_id,
                sender_type="agent",
                sender_id="agent-consultant",
                sender_name="Tư vấn viên AI",
                content=ai_reply,
            )
            session.add(ai_msg_obj)
            if conv:
                conv.status = "in_progress"
                conv.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(ai_msg_obj)

            if self.event_bus and hasattr(self.event_bus, "broadcast"):
                try:
                    await self.event_bus.broadcast({
                        "type": "inbox.message",
                        "conversation_id": conv_id,
                        "message": {
                            "id": ai_msg_obj.id,
                            "conversation_id": ai_msg_obj.conversation_id,
                            "sender_type": ai_msg_obj.sender_type,
                            "sender_id": ai_msg_obj.sender_id,
                            "sender_name": ai_msg_obj.sender_name,
                            "content": ai_msg_obj.content,
                            "attachments": [],
                            "metadata": {},
                            "created_at": ai_msg_obj.created_at.isoformat() if ai_msg_obj.created_at else None,
                        },
                    })
                except Exception:
                    pass

            return {
                "status": "processed",
                "reply": ai_reply,
                "message_id": ai_msg_obj.id,
            }
        finally:
            if self.event_bus and hasattr(self.event_bus, "broadcast"):
                try:
                    await self.event_bus.broadcast({
                        "type": "inbox.ai_done",
                        "conversation_id": conv_id,
                    })
                except Exception:
                    pass

    def _generate_draft_reply(self, query: str) -> str:
        """Generate helpful contextual customer service reply."""
        if getattr(self, "retriever", None) is not None:
            try:
                chunks = self.retriever.search(query=query, collections=["catalog", "knowledge", "qa"], top_k=2)
                if chunks and getattr(chunks[0], "score", 0.0) >= 0.7:
                    return f"Dạ theo thông tin bên em: {chunks[0].text}"
            except Exception:
                pass

        lower = query.lower()
        if "giá" in lower or "bao nhiêu" in lower:
            return "Dạ chào bạn, các sản phẩm hiện có mức giá ưu đãi từ 199.000đ - 499.000đ. Bạn đang quan tâm mẫu nào ạ?"
        if "bảo hành" in lower:
            return "Dạ sản phẩm bên em được bảo hành chính hãng 12 tháng, 1 đổi 1 trong 30 ngày nếu có lỗi sản xuất ạ."
        return "Dạ chào bạn! Em là trợ lý tư vấn AI, em có thể hỗ trợ thông tin gì cho bạn hôm nay ạ?"
