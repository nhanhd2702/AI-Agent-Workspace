"""Unified Inbox & Multi-channel Messaging API (Task 4.6).

Exposes:
- GET /api/v1/inbox/conversations
- GET /api/v1/inbox/conversations/{conv_id}
- GET /api/v1/inbox/conversations/{conv_id}/messages
- POST /api/v1/inbox/conversations/{conv_id}/takeover
- POST /api/v1/inbox/conversations/{conv_id}/release
- POST /api/v1/inbox/conversations/{conv_id}/reply
- POST /api/v1/inbox/webhook/{channel}
- GET /api/v1/inbox/connectors/status
- WebSocket /api/v1/inbox/ws
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.models import ConnectorConfig, Conversation, Message
from app.db.session import get_db
from app.mcp.messaging_bridge import (
    BaseChannelAdapter,
    MessagingBridge,
    MockChannelAdapter,
    TelegramChannelAdapter,
    ZaloChannelAdapter,
)

router = APIRouter(prefix="/api/v1/inbox", tags=["inbox"])


class OperatorReplyRequest(BaseModel):
    content: str = Field(..., min_length=1)
    attachments: Optional[list[dict[str, Any]]] = None


class WebhookPayload(BaseModel):
    sender_id: str = Field(..., min_length=1)
    sender_name: Optional[str] = None
    content: str = Field(..., min_length=1)
    client_message_id: Optional[str] = None
    attachments: Optional[list[dict[str, Any]]] = None


class InboxWebSocketManager:
    """Manages active WebSocket connections for live inbox updates."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, event: dict[str, Any]) -> None:
        async with self._lock:
            clients = list(self._connections)
        for client in clients:
            try:
                await client.send_json(event)
            except Exception:
                pass


inbox_ws_manager = InboxWebSocketManager()

# Global bridge instance cache to share race-safety generation state across requests
_bridge_instance: Optional[MessagingBridge] = None


def get_bridge(db: Session, channel: str = "mock") -> MessagingBridge:
    global _bridge_instance
    if _bridge_instance is None or _bridge_instance.db is not db:
        adapter: BaseChannelAdapter
        if channel == "zalo":
            adapter = ZaloChannelAdapter(account_id="zalo-oa-default")
        elif channel == "telegram":
            adapter = TelegramChannelAdapter(account_id="telegram-bot-default")
        else:
            adapter = MockChannelAdapter(channel=channel, account_id="acc-default")
        _bridge_instance = MessagingBridge(db=db, adapter=adapter, event_bus=inbox_ws_manager)
    return _bridge_instance


def _format_conv(conv: Conversation) -> dict[str, Any]:
    last_msg = None
    if conv.messages:
        sorted_msgs = sorted(conv.messages, key=lambda m: m.created_at or datetime.min)
        if sorted_msgs:
            lm = sorted_msgs[-1]
            last_msg = {
                "id": lm.id,
                "sender_type": lm.sender_type,
                "sender_name": lm.sender_name,
                "content": lm.content,
                "created_at": lm.created_at.isoformat() if lm.created_at else None,
            }

    return {
        "id": conv.id,
        "project_id": conv.project_id,
        "channel": conv.channel,
        "channel_conv_id": conv.channel_conv_id,
        "title": conv.title or (conv.participant_name or "Hội thoại"),
        "participant_name": conv.participant_name or "Khách hàng",
        "status": conv.status,
        "is_human_takeover": bool(conv.is_human_takeover),
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        "last_message": last_msg,
    }


def _format_msg(msg: Message) -> dict[str, Any]:
    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "sender_type": msg.sender_type,
        "sender_id": msg.sender_id,
        "sender_name": msg.sender_name,
        "content": msg.content,
        "attachments": msg.attachments or [],
        "metadata": msg.message_metadata or {},
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.get("/conversations")
def list_conversations(
    status: Optional[str] = Query(None, description="Status filter: waiting, in_progress, all, open"),
    channel: Optional[str] = Query(None, description="Channel filter: zalo, telegram, internal, all"),
    project_id: str = Query("proj-default"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List conversations filtered by status and channel."""
    query = db.query(Conversation).filter(Conversation.project_id == project_id)

    if channel and channel.lower() != "all":
        query = query.filter(Conversation.channel == channel.lower())

    if status and status.lower() != "all":
        stat = status.lower()
        if stat == "waiting":
            query = query.filter(
                (Conversation.status == "waiting")
                | ((Conversation.is_human_takeover == False) & (Conversation.status == "open"))
            )
        elif stat == "in_progress":
            query = query.filter(
                (Conversation.status == "in_progress") | (Conversation.is_human_takeover == True)
            )
        else:
            query = query.filter(Conversation.status == stat)

    convs = query.order_by(desc(Conversation.updated_at)).all()
    return [_format_conv(c) for c in convs]


@router.get("/conversations/{conv_id}")
def get_conversation(
    conv_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve details for a single conversation."""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _format_conv(conv)


@router.get("/conversations/{conv_id}/messages")
def get_conversation_messages(
    conv_id: str,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Retrieve chronologically ordered message thread for a conversation."""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return [_format_msg(m) for m in messages]


@router.post("/conversations/{conv_id}/takeover")
async def takeover_conversation(
    conv_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Human operator takes over conversation, cancelling any in-flight AI draft reply."""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    bridge = get_bridge(db, channel=conv.channel)
    updated_conv = bridge.human_takeover(conv_id)
    if not updated_conv:
        raise HTTPException(status_code=404, detail="Failed to takeover conversation")

    formatted = _format_conv(updated_conv)
    await inbox_ws_manager.broadcast({
        "type": "inbox.takeover",
        "conversation_id": conv_id,
        "is_human_takeover": True,
        "conversation": formatted,
    })
    return {"success": True, "conversation": formatted}


@router.post("/conversations/{conv_id}/release")
async def release_conversation(
    conv_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Release conversation back to automated AI agent processing."""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    bridge = get_bridge(db, channel=conv.channel)
    updated_conv = bridge.human_release(conv_id)
    if not updated_conv:
        raise HTTPException(status_code=404, detail="Failed to release conversation")

    formatted = _format_conv(updated_conv)
    await inbox_ws_manager.broadcast({
        "type": "inbox.release",
        "conversation_id": conv_id,
        "is_human_takeover": False,
        "conversation": formatted,
    })
    return {"success": True, "conversation": formatted}


@router.post("/conversations/{conv_id}/reply")
async def send_operator_reply(
    conv_id: str,
    payload: OperatorReplyRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Human operator sends a direct text reply to the customer."""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg = Message(
        id=f"msg-{uuid.uuid4().hex[:8]}",
        conversation_id=conv_id,
        sender_type="human",
        sender_id="operator-human",
        sender_name="Nhân viên hỗ trợ",
        content=payload.content,
        attachments=payload.attachments or [],
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    conv.updated_at = datetime.now(timezone.utc)
    conv.status = "in_progress"
    db.commit()
    db.refresh(msg)

    # Dispatch to channel adapter if external
    bridge = get_bridge(db, channel=conv.channel)
    try:
        await bridge.adapter.send_message(
            conv_id=conv_id,
            content=payload.content,
            attachments=payload.attachments,
        )
    except Exception:
        pass

    formatted_msg = _format_msg(msg)
    await inbox_ws_manager.broadcast({
        "type": "inbox.message",
        "conversation_id": conv_id,
        "message": formatted_msg,
    })
    return formatted_msg


@router.post("/webhook/{channel}")
async def handle_channel_webhook(
    channel: str,
    payload: WebhookPayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Receive incoming webhook payload from Zalo, Telegram, or internal channels."""
    ch = channel.lower()
    if ch not in ("zalo", "telegram", "internal"):
        raise HTTPException(status_code=400, detail=f"Unsupported channel: {channel}")

    # Find existing conversation or create new
    conv = (
        db.query(Conversation)
        .filter(Conversation.channel == ch, Conversation.channel_conv_id == payload.sender_id)
        .first()
    )
    if not conv:
        conv = Conversation(
            id=f"conv-{ch}-{uuid.uuid4().hex[:8]}",
            project_id="proj-default",
            channel=ch,
            channel_conv_id=payload.sender_id,
            title=f"Khách {ch.capitalize()} - {payload.sender_name or payload.sender_id}",
            participant_name=payload.sender_name or f"Khách {ch.capitalize()}",
            status="open",
            is_human_takeover=False,
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

    bridge = get_bridge(db, channel=ch)
    result = await bridge.process_incoming_with_ai(
        conv_id=conv.id,
        customer_msg=payload.content,
        client_message_id=payload.client_message_id,
        delay_s=0.0,
        sender_id=payload.sender_id,
        sender_name=payload.sender_name,
        attachments=payload.attachments,
    )

    await inbox_ws_manager.broadcast({
        "type": "inbox.message",
        "conversation_id": conv.id,
        "channel": ch,
        "result": result,
    })

    return {
        "success": True,
        "conversation_id": conv.id,
        "result": result,
    }


@router.get("/connectors/status")
def get_connectors_status(
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return status of social and messaging channel connectors (including QR re-auth urls)."""
    configs = db.query(ConnectorConfig).filter(
        ConnectorConfig.provider.in_(["zalo", "telegram", "internal"])
    ).all()

    items: list[dict[str, Any]] = []
    seen_providers = set()

    for c in configs:
        seen_providers.add(c.provider)
        settings = c.settings or {}
        items.append({
            "id": c.id,
            "name": c.name,
            "provider": c.provider,
            "status": c.status,
            "is_enabled": c.is_enabled,
            "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
            "qr_code_url": settings.get("qr_code_url"),
        })

    # Ensure baseline entries if not seeded in DB
    defaults = [
        {"id": "conn-zalo-def", "name": "Zalo OA", "provider": "zalo", "status": "disconnected", "is_enabled": False, "qr_code_url": "https://example.com/qr/zalo-reauth"},
        {"id": "conn-tg-def", "name": "Telegram Bot", "provider": "telegram", "status": "connected", "is_enabled": True, "qr_code_url": None},
        {"id": "conn-int-def", "name": "Kênh Nội Bộ", "provider": "internal", "status": "connected", "is_enabled": True, "qr_code_url": None},
    ]
    for d in defaults:
        if d["provider"] not in seen_providers:
            items.append(d)

    return items


@router.websocket("/ws")
async def inbox_websocket_stream(websocket: WebSocket) -> None:
    """Live WebSocket feed for inbox message arrivals and human takeover events."""
    await inbox_ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await inbox_ws_manager.disconnect(websocket)
    except Exception:
        await inbox_ws_manager.disconnect(websocket)
