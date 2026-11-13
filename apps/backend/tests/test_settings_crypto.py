"""Tests for encrypted LLM settings, profile preferences, and connector health checks (Task 5.1)."""

from __future__ import annotations

from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.db.models import ConnectorConfig, UserSettings
from app.main import create_app


@pytest.fixture
def client_with_db(tmp_path: Path) -> TestClient:
    """Fixture providing initialized FastAPI test client with seeded database and auth header."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="settings-test-token")
    app = create_app(settings)
    client = TestClient(app, headers={"X-Local-Auth-Token": "settings-test-token"})
    client.app_settings = settings  # type: ignore[attr-defined]
    return client


@pytest.fixture
def db_session(client_with_db: TestClient):
    """Yield a database session bound to the test client's engine."""
    factory = client_with_db.app.state.session_factory
    with factory() as session:
        yield session


# --- 1. Exact Test from Specification Plan ---

def test_llm_api_key_is_encrypted_at_rest_and_masked_in_get(client_with_db, db_session):
    """From plan: LLM API key must be encrypted at rest in DB and masked in GET response."""
    resp = client_with_db.put(
        "/api/v1/settings/llm",
        json={"provider": "gemini", "api_key": "AIzaSySecretTestKey1234", "default_model": "gemini-2.5-flash"},
    )
    assert resp.status_code == 200
    raw_row = client_with_db.app.state.get_raw_secret(db_session, "gemini")
    assert "AIzaSySecretTestKey1234" not in raw_row
    get_resp = client_with_db.get("/api/v1/settings/llm").json()
    assert get_resp["data"]["gemini"]["masked_key"].endswith("1234")
    assert "AIzaSySecret" not in get_resp["data"]["gemini"]["masked_key"]


# --- 2. Multiple Providers and CRUD Operations ---

def test_multiple_providers_configuration_and_retrieval(client_with_db: TestClient, db_session):
    """Tests saving and retrieving settings across multiple LLM providers."""
    providers = [
        {"provider": "openai", "api_key": "sk-proj-openaiSecretKey9988", "default_model": "gpt-4o"},
        {"provider": "anthropic", "api_key": "sk-ant-anthropicSecretKey7766", "default_model": "claude-3-5-sonnet-20241022"},
        {"provider": "deepseek", "api_key": "sk-deepseekSecretKey5544", "default_model": "deepseek-chat"},
        {"provider": "ollama", "api_key": "", "default_model": "llama3.2", "base_url": "http://localhost:11434"},
    ]

    for p in providers:
        resp = client_with_db.put("/api/v1/settings/llm", json=p)
        assert resp.status_code == 200

    get_resp = client_with_db.get("/api/v1/settings/llm").json()
    assert get_resp["status"] == "ok"
    data = get_resp["data"]

    # Verify OpenAI
    assert data["openai"]["has_key"] is True
    assert data["openai"]["masked_key"].endswith("9988")
    assert "openaiSecretKey" not in data["openai"]["masked_key"]
    assert data["openai"]["default_model"] == "gpt-4o"

    # Verify Anthropic
    assert data["anthropic"]["has_key"] is True
    assert data["anthropic"]["masked_key"].endswith("7766")
    assert "anthropicSecretKey" not in data["anthropic"]["masked_key"]

    # Verify DeepSeek
    assert data["deepseek"]["has_key"] is True
    assert data["deepseek"]["masked_key"].endswith("5544")
    assert "deepseekSecretKey" not in data["deepseek"]["masked_key"]

    # Verify Ollama
    assert data["ollama"]["default_model"] == "llama3.2"
    assert data["ollama"]["base_url"] == "http://localhost:11434"


def test_encryption_at_rest_stores_fernet_ciphertext_and_decrypts(client_with_db: TestClient, db_session):
    """Directly audits database column auth_payload to guarantee Fernet encryption."""
    secret_key = "AIzaSySuperSecretAtRestVerification9999"
    resp = client_with_db.put(
        "/api/v1/settings/llm",
        json={"provider": "gemini", "api_key": secret_key, "default_model": "gemini-2.5-flash"},
    )
    assert resp.status_code == 200

    row = db_session.query(ConnectorConfig).filter_by(provider="gemini").first()
    assert row is not None
    assert row.auth_payload is not None
    assert secret_key not in row.auth_payload

    # Valid Fernet decrypt with current system key
    encryption_key: bytes = client_with_db.app_settings.encryption_key  # type: ignore[attr-defined]
    f = Fernet(encryption_key)
    decrypted = f.decrypt(row.auth_payload.encode("utf-8")).decode("utf-8")
    assert decrypted == secret_key

    # Invalid token check with an arbitrary foreign key
    foreign_f = Fernet(Fernet.generate_key())
    with pytest.raises(InvalidToken):
        foreign_f.decrypt(row.auth_payload.encode("utf-8"))


def test_update_model_preserves_existing_api_key_when_omitted(client_with_db: TestClient):
    """PUT /api/v1/settings/llm without api_key should keep previously saved encrypted key."""
    # 1. Set key
    client_with_db.put(
        "/api/v1/settings/llm",
        json={"provider": "gemini", "api_key": "AIzaSySecretKeepMe8888", "default_model": "gemini-2.5-flash"},
    )

    # 2. Update only model
    update_resp = client_with_db.put(
        "/api/v1/settings/llm",
        json={"provider": "gemini", "default_model": "gemini-2.5-pro"},
    )
    assert update_resp.status_code == 200

    # 3. Verify key is intact
    get_resp = client_with_db.get("/api/v1/settings/llm").json()
    gemini_info = get_resp["data"]["gemini"]
    assert gemini_info["default_model"] == "gemini-2.5-pro"
    assert gemini_info["has_key"] is True
    assert gemini_info["masked_key"].endswith("8888")


def test_clear_api_key_when_empty_string(client_with_db: TestClient, db_session):
    """PUT with empty api_key clears stored secret and updates status."""
    client_with_db.put(
        "/api/v1/settings/llm",
        json={"provider": "gemini", "api_key": "AIzaSySecretToClear1111", "default_model": "gemini-2.5-flash"},
    )

    # Clear key
    clear_resp = client_with_db.put(
        "/api/v1/settings/llm",
        json={"provider": "gemini", "api_key": ""},
    )
    assert clear_resp.status_code == 200

    raw_row = client_with_db.app.state.get_raw_secret(db_session, "gemini")
    assert raw_row == ""

    get_resp = client_with_db.get("/api/v1/settings/llm").json()
    assert get_resp["data"]["gemini"]["has_key"] is False
    assert get_resp["data"]["gemini"]["masked_key"] == ""


# --- 3. Connection Ping Test ---

def test_llm_connection_ping_scenarios(client_with_db: TestClient):
    """Tests POST /api/v1/settings/llm/test connection ping."""
    # 1. Test ping with valid explicit key
    ping_resp = client_with_db.post(
        "/api/v1/settings/llm/test",
        json={"provider": "gemini", "api_key": "AIzaSyValidTestKey1234", "default_model": "gemini-2.5-flash"},
    )
    assert ping_resp.status_code == 200
    res_data = ping_resp.json()
    assert res_data["success"] is True
    assert "thành công" in res_data["message"].lower()

    # 2. Test ping with saved key in database
    client_with_db.put(
        "/api/v1/settings/llm",
        json={"provider": "openai", "api_key": "sk-proj-ValidKey5678", "default_model": "gpt-4o"},
    )
    ping_saved_resp = client_with_db.post(
        "/api/v1/settings/llm/test",
        json={"provider": "openai"},
    )
    assert ping_saved_resp.status_code == 200
    assert ping_saved_resp.json()["success"] is True

    # 3. Test ping without key on unconfigured provider fails gracefully
    ping_missing = client_with_db.post(
        "/api/v1/settings/llm/test",
        json={"provider": "anthropic"},
    )
    assert ping_missing.status_code == 200
    assert ping_missing.json()["success"] is False
    assert "chưa cấu hình" in ping_missing.json()["message"].lower()

    # 4. Test ping with explicit invalid key fails gracefully
    ping_invalid = client_with_db.post(
        "/api/v1/settings/llm/test",
        json={"provider": "gemini", "api_key": "invalid-dummy-key"},
    )
    assert ping_invalid.status_code == 200
    assert ping_invalid.json()["success"] is False


# --- 4. Connector Health Check ---

def test_connectors_health_endpoint(client_with_db: TestClient):
    """Tests GET /api/v1/settings/connectors/health for runtime and external tools."""
    resp = client_with_db.get("/api/v1/settings/connectors/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    items = payload["data"]
    assert isinstance(items, list)

    item_ids = {it["id"] for it in items}
    expected_ids = {"ffmpeg", "playwright", "shell", "chromadb", "youtube", "telegram", "zalo"}
    assert expected_ids.issubset(item_ids)

    for it in items:
        assert "id" in it
        assert "name" in it
        assert "healthy" in it
        assert "status" in it
        assert "last_checked" in it


# --- 5. User Profile Preferences ---

def test_user_profile_get_and_put(client_with_db: TestClient):
    """Tests GET and PUT /api/v1/settings/profile."""
    # 1. Get default seeded profile
    get_resp = client_with_db.get("/api/v1/settings/profile")
    assert get_resp.status_code == 200
    profile = get_resp.json()["data"]
    assert profile["theme"] == "dark"
    assert profile["language"] == "vi"
    assert profile["auto_backup"] is True

    # 2. Update profile
    put_resp = client_with_db.put(
        "/api/v1/settings/profile",
        json={
            "theme": "light",
            "language": "en",
            "daily_token_limit": 500000,
            "daily_usd_limit": 25.5,
            "auto_backup": False,
            "preferences": {"notifications_enabled": True, "compact_view": False},
        },
    )
    assert put_resp.status_code == 200
    updated = put_resp.json()["data"]
    assert updated["theme"] == "light"
    assert updated["language"] == "en"
    assert updated["daily_token_limit"] == 500000
    assert updated["daily_usd_limit"] == 25.5
    assert updated["auto_backup"] is False
    assert updated["preferences"]["notifications_enabled"] is True

    # 3. Verify persistence
    persisted = client_with_db.get("/api/v1/settings/profile").json()["data"]
    assert persisted["theme"] == "light"
    assert persisted["language"] == "en"


# --- 6. Local Auth Enforcement ---

def test_settings_endpoints_require_local_auth(tmp_path: Path):
    """Ensures unauthenticated requests to /api/v1/settings/* return 401."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="secure-token")
    client = TestClient(create_app(settings))  # no auth header

    assert client.get("/api/v1/settings/llm").status_code == 401
    assert client.put("/api/v1/settings/llm", json={"provider": "gemini"}).status_code == 401
    assert client.post("/api/v1/settings/llm/test", json={"provider": "gemini"}).status_code == 401
    assert client.get("/api/v1/settings/connectors/health").status_code == 401
    assert client.get("/api/v1/settings/profile").status_code == 401
    assert client.put("/api/v1/settings/profile", json={"theme": "dark"}).status_code == 401
