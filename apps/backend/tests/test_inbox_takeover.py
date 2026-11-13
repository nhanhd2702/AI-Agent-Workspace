"""Tests for Multi-channel Messaging Bridge and Race-Safe Human Takeover (Task 4.6)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.api.inbox import get_bridge, reset_bridge
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
    reset_bridge()
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


# --- Fix Round 1: New Rigorous Verification Tests ---

def test_cross_request_singleton_state_persists(tmp_path: Path):
    """Verify get_bridge() maintains generation, rate limiter, and deduplication across multiple HTTP requests with distinct DB sessions."""
    reset_bridge()
    db_path1 = tmp_path / "req1.db"
    db_path2 = tmp_path / "req2.db"
    f1 = init_db(db_path1, cache=False)
    f2 = init_db(db_path2, cache=False)

    with f1() as s1, f2() as s2:
        bridge1 = get_bridge(s1, channel="mock")
        bridge2 = get_bridge(s2, channel="mock")

        # 1. Must be the exact same persistent singleton instance
        assert bridge1 is bridge2

        # 2. Rate limiter state persists
        assert bridge1.rate_limiter.acquire("acc-persists", tokens=10) is True
        # Consumption on bridge1 is visible on bridge2
        assert bridge2.rate_limiter._tokens["acc-persists"] == 20.0  # 30 - 10

        # 3. Deduplication state persists
        assert bridge1._record_client_id("client-msg-persistent-001") is True
        assert "client-msg-persistent-001" in bridge2.processed_client_ids
        assert bridge2._record_client_id("client-msg-persistent-001") is False

        # 4. Takeover generation persists across requests
        bridge1.takeover_generation["conv-persist-1"] = 5
        assert bridge2.takeover_generation.get("conv-persist-1") == 5


@pytest.mark.asyncio
async def test_cross_request_human_takeover_cancels_ai(client_env):
    """Simulate concurrent HTTP requests: Request 1 starts processing with delay and Request 2 calls /takeover; verify AI draft is discarded."""
    client, app, factory = client_env
    reset_bridge()

    # Request 1 starts processing with 0.1s simulated delay
    with factory() as session1:
        bridge = get_bridge(session1, channel="zalo")
        mock_adapter = MockChannelAdapter(channel="zalo", account_id="acc-zalo-1")
        bridge.adapter = mock_adapter

        ai_task = asyncio.create_task(
            bridge.process_incoming_with_ai(
                conv_id="conv-zalo-1",
                customer_msg="Cho mình hỏi giá và cách mua hàng?",
                delay_s=0.1,
                db=session1,
            )
        )

        # Brief pause to ensure Request 1 is in-flight (waiting in sleep)
        await asyncio.sleep(0.02)

        # Request 2 arrives via HTTP POST /takeover with its own DB session
        res_takeover = client.post("/api/v1/inbox/conversations/conv-zalo-1/takeover")
        assert res_takeover.status_code == 200
        assert res_takeover.json()["conversation"]["is_human_takeover"] is True

        # Wait for Request 1 to complete
        result1 = await ai_task

        # Verify AI draft was cancelled by takeover
        assert result1["status"] == "cancelled_by_takeover"
        assert len(mock_adapter.sent_messages) == 0

        # Verify in DB conversation is in human takeover
        with factory() as verify_session:
            conv = verify_session.get(Conversation, "conv-zalo-1")
            assert conv.is_human_takeover is True
            # Verify no AI message was stored in DB
            ai_messages = (
                verify_session.query(Message)
                .filter(Message.conversation_id == "conv-zalo-1", Message.sender_type == "agent")
                .all()
            )
            assert len(ai_messages) == 0


def test_websocket_auth_enforced(client_env):
    """Verify /api/v1/inbox/ws rejects connections without valid token (1008) and accepts valid token."""
    _, app, _ = client_env
    anon_client = TestClient(app)

    # 1. Missing token -> rejected with WS 1008 policy violation
    with pytest.raises(WebSocketDisconnect) as exc:
        with anon_client.websocket_connect("/api/v1/inbox/ws") as ws:
            ws.send_text("ping")
    assert exc.value.code == 1008

    # 2. Invalid token in query param -> rejected with WS 1008 policy violation
    with pytest.raises(WebSocketDisconnect) as exc:
        with anon_client.websocket_connect("/api/v1/inbox/ws?token=invalid-secret-xyz") as ws:
            ws.send_text("ping")
    assert exc.value.code == 1008

    # 3. Valid token in query param -> Connected, ping responds with pong
    with anon_client.websocket_connect("/api/v1/inbox/ws?token=secret-inbox-token-123") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"

    # 4. Valid token in X-Local-Auth-Token header -> Connected
    with anon_client.websocket_connect("/api/v1/inbox/ws", headers={"X-Local-Auth-Token": "secret-inbox-token-123"}) as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_secret_masking_in_inbox_messages(client_env):
    """Verify secrets (API keys, bearer tokens) are masked in DB, operator replies, and broadcast events."""
    client, app, factory = client_env
    reset_bridge()

    # 1. Webhook with customer message containing secrets
    raw_secret_key = "sk-proj-1234567890abcdef12345678"
    raw_customer_msg = f"Tôi lỡ gửi nhầm key: {raw_secret_key} và password=mypassword123 shop hỗ trợ xoá giúp"

    res_wh = client.post(
        "/api/v1/inbox/webhook/zalo",
        json={
            "sender_id": "zalo-cust-secrets",
            "sender_name": "Khách Bảo Mật",
            "content": raw_customer_msg,
            "client_message_id": "wh-secret-001",
        },
    )
    assert res_wh.status_code in (200, 201)
    conv_id = res_wh.json()["conversation_id"]

    # Verify customer message in DB has redacted content
    with factory() as session:
        cust_msg = (
            session.query(Message)
            .filter(Message.conversation_id == conv_id, Message.sender_type == "customer")
            .first()
        )
        assert cust_msg is not None
        assert raw_secret_key not in cust_msg.content
        assert "sk-***REDACTED***" in cust_msg.content

    # 2. Operator reply containing sensitive token
    raw_op_token = "Bearer secret-super-token-999"
    res_reply = client.post(
        f"/api/v1/inbox/conversations/{conv_id}/reply",
        json={"content": f"Vâng em đã xoá rồi ạ, đây là token tạm thời: {raw_op_token}"},
    )
    assert res_reply.status_code == 200
    reply_data = res_reply.json()
    assert raw_op_token not in reply_data["content"]
    assert "***REDACTED***" in reply_data["content"]

    # Verify operator message in DB has redacted content
    with factory() as session:
        op_msg = (
            session.query(Message)
            .filter(Message.conversation_id == conv_id, Message.sender_type == "human")
            .first()
        )
        assert op_msg is not None
        assert raw_op_token not in op_msg.content
        assert "***REDACTED***" in op_msg.content


def test_rate_limiter_thread_safety_and_bounded_cache():
    """Verify thread safety under concurrent acquire calls and bounded cache eviction for deduplication."""
    import concurrent.futures

    # 1. Thread safety on TokenBucketRateLimiter
    limiter = TokenBucketRateLimiter(rate_per_min=100.0, capacity=100.0)
    acc = "acc-threaded-test"

    def _worker():
        return limiter.acquire(acc, tokens=1.0)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_worker) for _ in range(120)]
        results = [f.result() for f in futures]

    # Exactly 100 acquires should succeed, 20 fail
    success_count = sum(1 for r in results if r is True)
    failure_count = sum(1 for r in results if r is False)
    assert success_count == 100
    assert failure_count == 20

    # 2. Bounded deduplication cache on MessagingBridge
    bridge = MessagingBridge(max_dedup_size=5)
    for i in range(10):
        assert bridge._record_client_id(f"client-id-{i}") is True

    # Total set size should never exceed max_dedup_size (5)
    assert len(bridge.processed_client_ids) == 5
    # Oldest entries 0-4 must have been evicted
    assert "client-id-0" not in bridge.processed_client_ids
    assert "client-id-4" not in bridge.processed_client_ids
    # Newest entries 5-9 must be present
    for i in range(5, 10):
        assert f"client-id-{i}" in bridge.processed_client_ids


def test_webhook_and_reply_payload_bounds(client_env):
    """Verify payload bounds (max_length) reject oversized inputs with 422 Unprocessable Entity."""
    client, _, _ = client_env

    # Oversized content > 10000 chars
    huge_content = "A" * 10001
    res = client.post(
        "/api/v1/inbox/webhook/zalo",
        json={"sender_id": "cust-1", "content": huge_content},
    )
    assert res.status_code == 422

    # Oversized sender_id > 128 chars
    huge_sender = "x" * 129
    res_sender = client.post(
        "/api/v1/inbox/webhook/zalo",
        json={"sender_id": huge_sender, "content": "hello"},
    )
    assert res_sender.status_code == 422

