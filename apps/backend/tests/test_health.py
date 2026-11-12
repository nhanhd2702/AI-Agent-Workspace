from fastapi.testclient import TestClient
from app.main import create_app
from app.config import AppSettings


def test_health_requires_local_auth_token(tmp_path):
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="secret-123")
    client = TestClient(create_app(settings))
    assert client.get("/api/v1/health").status_code == 401
    resp = client.get("/api/v1/health", headers={"X-Local-Auth-Token": "secret-123"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
