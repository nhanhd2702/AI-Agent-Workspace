"""Tests for Multi-channel Messaging Bridge and Race-Safe Human Takeover (Task 4.6)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.db.models import ConnectorConfig, Conversation, Message
from app.db.session import init_db, seed_defaults
from app.main import create_app
from app.mcp.messaging_bridge import (
    MessagingBridge,
    MockChannelAdapter,
    TelegramChannelAdapter,
    TokenBucketRateLimiter,
    ZaloChannelAdapter,
)


@pytest.fixture
def db_session(tmp_path: Path):
    """Provide an isolated, seeded SQLite session for unit tests with initial inbox data."""
    db_path = tmp_path / "test_inbox_unit.db"
    factory = init_db(db_path, cache=False)
    with factory() as session:
        seed_defaults(session)
        # Seed test conversation
        conv = Conversation(
            id="conv-zalo-1",
            project_id="proj-default",
            channel="zalo",
            channel_conv_id="zalo-user-100",
            title="Nguyễn Văn A - Tư vấn sản phẩm",
            participant_name="Nguyễn Văn A",
            status="open",
            is_human_takeover=False,
        )
        session.add(conv)

        # Seed initial message
        msg = Message(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            conversation_id="conv-zalo-1",
            sender_type="customer",
            sender_id="zalo-user-100",
            sender_name="Nguyễn Văn A",
            content="Giá sao em?",
        )
        session.add(msg)

        # Seed connector configs
        session.add(
            ConnectorConfig(
                id="conn-zalo-1",
                name="Zalo OA Official",
                provider="zalo",
                status="connected",
                is_enabled=True,
                settings={"oa_id": "oa-123456", "rate_limit_per_min": 30},
            )
        )
        session.add(
            ConnectorConfig(
                id="conn-telegram-1",
                name="Telegram Bot Support",
                provider="telegram",
                status="connected",
                is_enabled=True,
                settings={"bot_username": "MySupportBot", "rate_limit_per_min": 30},
            )
        )
        session.commit()

    with factory() as session:
        yield session


@pytest.fixture
def mock_channel_adapter():
    """Provide a mock channel adapter tracking sent messages."""
    return MockChannelAdapter(channel="zalo", account_id="acc-zalo-1")


@pytest.fixture
def client_env(tmp_path: Path):
    """Provide a configured TestClient with valid auth token and seeded inbox data."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "inbox_app.db"
    settings = AppSettings(
        workspace_dir=workspace,
        db_path=db_path,
        local_auth_token="secret-inbox-token-123",
    )
    app = create_app(settings=settings)

    factory = app.state.session_factory
    with factory() as session:
        seed_defaults(session)
        conv1 = Conversation(
            id="conv-zalo-1",
            project_id="proj-default",
            channel="zalo",
            channel_conv_id="zalo-user-100",
            title="Khách Zalo A",
            participant_name="Nguyễn Văn A",
            status="waiting",
            is_human_takeover=False,
        )
        conv2 = Conversation(
            id="conv-tg-1",
            project_id="proj-default",
            channel="telegram",
            channel_conv_id="tg-user-200",
            title="Khách Telegram B",
            participant_name="Trần Thị B",
            status="in_progress",
            is_human_takeover=True,
        )
        conv3 = Conversation(
            id="conv-int-1",
            project_id="proj-default",
            channel="internal",
            channel_conv_id="internal-300",
            title="Khách Nội Bộ C",
            participant_name="Lê Văn C",
            status="open",
            is_human_takeover=False,
        )
        session.add_all([conv1, conv2, conv3])

        session.add(
            Message(
                id="msg-init-1",
                conversation_id="conv-zalo-1",
                sender_type="customer",
                sender_id="zalo-user-100",
                sender_name="Nguyễn Văn A",
                content="Giá sao em?",
            )
        )
        session.add(
            ConnectorConfig(
                id="conn-zalo-main",
                name="Zalo OA",
                provider="zalo",
                status="needs_reauth",
                is_enabled=True,
                settings={"qr_code_url": "https://example.com/qr/zalo-reauth"},
            )
        )
        session.add(
            ConnectorConfig(
                id="conn-telegram-main",
                name="Telegram Bot",
                provider="telegram",
                status="connected",
                is_enabled=True,
                settings={},
            )
        )
        session.commit()

    client = TestClient(app, headers={"X-Local-Auth-Token": "secret-inbox-token-123"})
    return client, app, factory


# --- Core TDD Test from Plan ---

@pytest.mark.asyncio
async def test_human_takeover_cancels_pending_ai_reply(db_session, mock_channel_adapter):
    """Test race-safe human takeover cancels pending AI reply before delivery."""
    bridge = MessagingBridge(db=db_session, adapter=mock_channel_adapter, rate_limit_per_min=30)
    ai_task = asyncio.create_task(bridge.process_incoming_with_ai("conv-zalo-1", "Giá sao em?", delay_s=0.1))
    await asyncio.sleep(0.02)
    bridge.human_takeover("conv-zalo-1")
    await ai_task
    assert len(mock_channel_adapter.sent_messages) == 0


# --- Token-Bucket Rate Limiter Tests ---

def test_token_bucket_rate_limiter_enforces_30_msg_per_min():
    """Verify 30 msg/min token-bucket limit per channel account."""
    limiter = TokenBucketRateLimiter(rate_per_min=30)
    account_a = "acc-zalo-shop1"
    account_b = "acc-zalo-shop2"

    # Consuming 30 tokens for account A should succeed
    for _ in range(30):
        assert limiter.acquire(account_a) is True

    # 31st attempt exceeds rate limit
    assert limiter.acquire(account_a) is False

    # Account B has its own independent bucket
    assert limiter.acquire(account_b) is True

    # Simulated time advance replenishes tokens
    limiter._last_check[account_a] -= 4.0  # 4 seconds back = 4 * (30/60) = 2 tokens replenished
    assert limiter.acquire(account_a) is True
    assert limiter.acquire(account_a) is True
    assert limiter.acquire(account_a) is False


# --- Message Deduplication Tests ---

@pytest.mark.asyncio
async def test_deduplication_drops_duplicate_client_message_id(db_session, mock_channel_adapter):
    """Verify incoming messages with the same client_message_id are deduplicated."""
    bridge = MessagingBridge(db=db_session, adapter=mock_channel_adapter, rate_limit_per_min=30)
    client_msg_id = "zalo-dup-uuid-999"

    # First receive
    res1 = await bridge.process_incoming_with_ai(
        "conv-zalo-1",
        "Chào shop tư vấn giúp mình",
        client_message_id=client_msg_id,
        delay_s=0.0,
    )
    assert res1["status"] in ("processed", "success", "sent")
    assert len(mock_channel_adapter.sent_messages) == 1

    # Second receive with same client_message_id should be dropped as duplicate
    res2 = await bridge.process_incoming_with_ai(
        "conv-zalo-1",
        "Chào shop tư vấn giúp mình",
        client_message_id=client_msg_id,
        delay_s=0.0,
    )
    assert res2["status"] == "duplicate"
    # No second outgoing message sent
    assert len(mock_channel_adapter.sent_messages) == 1


# --- Human Release Tests ---

@pytest.mark.asyncio
async def test_human_release_restores_ai_processing(db_session, mock_channel_adapter):
    """Verify human_release clears takeover flag and restores AI draft replies."""
    bridge = MessagingBridge(db=db_session, adapter=mock_channel_adapter, rate_limit_per_min=30)

    # Human takes over
    bridge.human_takeover("conv-zalo-1")
    conv = db_session.get(Conversation, "conv-zalo-1")
    assert conv.is_human_takeover is True

    # Incoming message while human takeover is active should not trigger AI reply
    res1 = await bridge.process_incoming_with_ai("conv-zalo-1", "Em ơi còn hàng không?", delay_s=0.0)
    assert res1["status"] in ("human_handling", "skipped")
    assert len(mock_channel_adapter.sent_messages) == 0

    # Human releases back to AI
    bridge.human_release("conv-zalo-1")
    db_session.refresh(conv)
    assert conv.is_human_takeover is False

    # Next incoming message is successfully handled by AI
    res2 = await bridge.process_incoming_with_ai("conv-zalo-1", "Sản phẩm bảo hành bao lâu?", delay_s=0.0)
    assert res2["status"] in ("processed", "success", "sent")
    assert len(mock_channel_adapter.sent_messages) == 1


# --- AI Auto-Escalate Tests ---

@pytest.mark.asyncio
async def test_ai_auto_escalate_sets_human_takeover_in_db(db_session, mock_channel_adapter):
    """Verify that when AI reply has escalate_to_human=True, conversation is escalated."""
    bridge = MessagingBridge(db=db_session, adapter=mock_channel_adapter, rate_limit_per_min=30)

    # Trigger message with explicit escalation flag or complaint
    res = await bridge.process_incoming_with_ai(
        "conv-zalo-1",
        "Tôi muốn gặp quản lý khiếu nại về hàng lỗi vỡ!",
        force_escalate=True,
        delay_s=0.0,
    )
    assert res["escalated"] is True

    conv = db_session.get(Conversation, "conv-zalo-1")
    assert conv.is_human_takeover is True
    assert conv.status in ("waiting", "escalated", "in_progress")


# --- REST & WebSocket API Endpoint Tests ---

def test_api_list_and_filter_conversations(client_env):
    """Test GET /api/v1/inbox/conversations with channel and status filtering."""
    client, _, _ = client_env

    # List all
    res = client.get("/api/v1/inbox/conversations")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 3

    # Filter by channel=zalo
    res_zalo = client.get("/api/v1/inbox/conversations?channel=zalo")
    assert res_zalo.status_code == 200
    zalo_items = res_zalo.json()
    assert all(c["channel"] == "zalo" for c in zalo_items)

    # Filter by status=waiting
    res_waiting = client.get("/api/v1/inbox/conversations?status=waiting")
    assert res_waiting.status_code == 200
    waiting_items = res_waiting.json()
    assert any(c["id"] == "conv-zalo-1" for c in waiting_items)


def test_api_get_conversation_messages(client_env):
    """Test GET /api/v1/inbox/conversations/{conv_id}/messages."""
    client, _, _ = client_env
    res = client.get("/api/v1/inbox/conversations/conv-zalo-1/messages")
    assert res.status_code == 200
    msgs = res.json()
    assert len(msgs) >= 1
    assert msgs[0]["content"] == "Giá sao em?"


def test_api_takeover_and_release_endpoints(client_env):
    """Test POST /takeover and POST /release endpoints."""
    client, _, _ = client_env

    # Takeover
    res_to = client.post("/api/v1/inbox/conversations/conv-zalo-1/takeover")
    assert res_to.status_code == 200
    assert res_to.json()["conversation"]["is_human_takeover"] is True

    # Release
    res_rel = client.post("/api/v1/inbox/conversations/conv-zalo-1/release")
    assert res_rel.status_code == 200
    assert res_rel.json()["conversation"]["is_human_takeover"] is False


def test_api_operator_reply_endpoint(client_env):
    """Test POST /api/v1/inbox/conversations/{conv_id}/reply."""
    client, _, _ = client_env
    payload = {"content": "Chào anh, sản phẩm giá 199k nhé ạ!"}
    res = client.post("/api/v1/inbox/conversations/conv-zalo-1/reply", json=payload)
    assert res.status_code == 200
    msg = res.json()
    assert msg["sender_type"] == "human"
    assert msg["content"] == payload["content"]


def test_api_webhook_channel_endpoints(client_env):
    """Test POST /api/v1/inbox/webhook/{channel} for Zalo and Telegram."""
    client, _, _ = client_env

    # Webhook Zalo
    zalo_payload = {
        "sender_id": "zalo-cust-99",
        "sender_name": "Khách Mới Zalo",
        "content": "Shop có ship hỏa tốc không?",
        "client_message_id": "wh-zalo-001",
    }
    res_zalo = client.post("/api/v1/inbox/webhook/zalo", json=zalo_payload)
    assert res_zalo.status_code in (200, 201)
    z_data = res_zalo.json()
    assert "conversation_id" in z_data

    # Webhook Telegram
    tg_payload = {
        "sender_id": "tg-cust-88",
        "sender_name": "Khách Telegram",
        "content": "Check đơn hàng giúp mình với",
        "client_message_id": "wh-tg-002",
    }
    res_tg = client.post("/api/v1/inbox/webhook/telegram", json=tg_payload)
    assert res_tg.status_code in (200, 201)
    tg_data = res_tg.json()
    assert "conversation_id" in tg_data


def test_api_connectors_status(client_env):
    """Test GET /api/v1/inbox/connectors/status returns connector status with QR support."""
    client, _, _ = client_env
    res = client.get("/api/v1/inbox/connectors/status")
    assert res.status_code == 200
    items = res.json()
    assert len(items) >= 2
    zalo_conn = next((c for c in items if c["provider"] == "zalo"), None)
    assert zalo_conn is not None
    assert zalo_conn["status"] == "needs_reauth"
    assert "qr_code_url" in zalo_conn
