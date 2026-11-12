"""Tests for Artifact Renderer (F06.1 & F06.2) and Artifact API.

Covers:
- Offline HTML sanitization (strips external scripts, stylesheets, protocol-relative URLs, CSS @import).
- CSP injection and base offline CSS reset.
- Replacing/stripping author untrusted CSP meta tags.
- Fragment HTML wrapping into complete standard document.
- API GET /api/v1/artifacts/{id}/render (auth check, 404, path traversal guard, HTML sanitization, raw vs json format, markdown support).
"""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.artifacts.renderer import sanitize_offline_html
from app.config import AppSettings
from app.db.models import Artifact, Project, Task, TaskStatus
from app.db.session import init_db
from app.main import create_app


# --- 1. Brief Specific Test ---

def test_artifact_iframe_sandbox_blocks_parent_and_cdn():
    """From brief: dirty HTML with external script & stylesheet has them stripped with 2 warnings."""
    dirty = '<html><head><script src="https://cdn.tailwindcss.com"></script><link rel="stylesheet" href="https://evil.com/a.css"></head><body><h1>Hi</h1></body></html>'
    cleaned, warnings = sanitize_offline_html(dirty)
    assert "cdn.tailwindcss.com" not in cleaned
    assert "evil.com" not in cleaned
    assert len(warnings) == 2


# --- 2. Advanced Sanitization Tests ---

def test_sanitize_protocol_relative_and_css_imports():
    """Blocks protocol-relative URLs (//cdn...) and CSS @import url(...)."""
    html_with_imports = """
    <!DOCTYPE html>
    <html>
      <head>
        <script src="//code.jquery.com/jquery-3.6.0.min.js"></script>
        <link rel="stylesheet" href="//cdn.jsdelivr.net/npm/bootstrap.css">
        <style>
          @import url("https://fonts.googleapis.com/css?family=Roboto");
          @import '//fonts.googleapis.com/css?family=Open+Sans';
          @import "http://malicious.com/hack.css";
          body { color: #333; background: url('https://tracker.com/pixel.png'); }
        </style>
      </head>
      <body>
        <p>Offline content</p>
      </body>
    </html>
    """
    cleaned, warnings = sanitize_offline_html(html_with_imports)
    assert "code.jquery.com" not in cleaned
    assert "cdn.jsdelivr.net" not in cleaned
    assert "fonts.googleapis.com" not in cleaned
    assert "malicious.com" not in cleaned
    assert "tracker.com" not in cleaned
    # We should have warnings for each stripped external source
    assert len(warnings) >= 4


def test_sanitize_fragment_html_and_csp_injection():
    """Fragment HTML without html/head is wrapped and injected with strict CSP and base offline CSS."""
    fragment = "<div class='card'><h2>Dashboard</h2><p>Local analytics</p></div>"
    cleaned, warnings = sanitize_offline_html(fragment)
    assert warnings == []
    assert "<!DOCTYPE html>" in cleaned
    assert "<html" in cleaned
    assert "<head" in cleaned
    assert "Content-Security-Policy" in cleaned
    assert "default-src 'none'" in cleaned
    assert "style-src 'unsafe-inline'" in cleaned
    assert "script-src 'unsafe-inline'" in cleaned
    assert "img-src data: blob:" in cleaned
    assert "box-sizing: border-box" in cleaned
    assert "<body" in cleaned
    assert "<div class=\"card\"><h2>Dashboard</h2><p>Local analytics</p></div>" in cleaned or "<div class='card'>" in cleaned


def test_sanitize_replaces_existing_untrusted_csp():
    """Untrusted author CSP is stripped and replaced by our strict CSP."""
    raw = """
    <html>
      <head>
        <meta http-equiv="Content-Security-Policy" content="default-src * 'unsafe-inline' 'unsafe-eval'">
        <title>Test</title>
      </head>
      <body>Hello</body>
    </html>
    """
    cleaned, _ = sanitize_offline_html(raw)
    assert "default-src *" not in cleaned
    assert "default-src 'none'" in cleaned


# --- 3. API Fixture and Tests ---

@pytest.fixture
def client_with_db(tmp_path: Path) -> TestClient:
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="test-secret-token")
    app = create_app(settings)
    client = TestClient(app, headers={"X-Local-Auth-Token": "test-secret-token"})
    client.app_settings = settings  # type: ignore[attr-defined]
    return client


def _seed_project_and_task(client: TestClient) -> tuple[str, str]:
    """Helper to seed a Project and Task for attaching artifacts."""
    settings = client.app_settings  # type: ignore[attr-defined]
    factory = init_db(settings.resolved_db_path)
    with factory() as session:
        proj = Project(id="proj-test-1", name="Test Project")
        session.add(proj)
        task = Task(
            id="task-test-1",
            project_id="proj-test-1",
            title="Landing page design",
            status=TaskStatus.RUNNING,
            metadata={"task_type": "landing_page"},
        )
        session.add(task)
        session.commit()
    return "proj-test-1", "task-test-1"


def test_artifact_render_api_auth_required(client_with_db: TestClient):
    """GET /api/v1/artifacts/{id}/render requires valid X-Local-Auth-Token."""
    no_auth_client = TestClient(client_with_db.app)
    resp = no_auth_client.get("/api/v1/artifacts/art-1/render")
    assert resp.status_code == 401


def test_artifact_render_api_not_found(client_with_db: TestClient):
    """Non-existent artifact returns 404."""
    resp = client_with_db.get("/api/v1/artifacts/art-missing-999/render")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_artifact_render_api_path_traversal_guard(client_with_db: TestClient):
    """Artifact pointing outside workspace directory returns 403 Forbidden."""
    _, task_id = _seed_project_and_task(client_with_db)
    settings = client_with_db.app_settings  # type: ignore[attr-defined]
    factory = init_db(settings.resolved_db_path)

    with factory() as session:
        art = Artifact(
            id="art-evil-1",
            task_id=task_id,
            name="malicious.html",
            file_path="../../outside/secret.html",
            file_type="html",
            mime_type="text/html",
        )
        session.add(art)
        session.commit()

    resp = client_with_db.get("/api/v1/artifacts/art-evil-1/render")
    assert resp.status_code == 403
    assert "outside workspace" in resp.json()["detail"].lower()


def test_artifact_render_api_success_html_and_raw(client_with_db: TestClient):
    """HTML artifact returns sanitized JSON payload or raw HTML based on ?format=raw."""
    _, task_id = _seed_project_and_task(client_with_db)
    settings = client_with_db.app_settings  # type: ignore[attr-defined]
    workspace = settings.workspace_dir
    html_file = workspace / "index.html"
    html_file.parent.mkdir(parents=True, exist_ok=True)
    html_file.write_text(
        '<html><head><script src="https://cdn.tailwindcss.com"></script></head><body><h1>Landing</h1></body></html>',
        encoding="utf-8",
    )

    factory = init_db(settings.resolved_db_path)
    with factory() as session:
        art = Artifact(
            id="art-html-1",
            task_id=task_id,
            name="index.html",
            file_path="index.html",
            file_type="html",
            mime_type="text/html",
        )
        session.add(art)
        session.commit()

    # Default JSON format
    resp = client_with_db.get("/api/v1/artifacts/art-html-1/render")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["data"]["id"] == "art-html-1"
    assert "cdn.tailwindcss.com" not in data["data"]["sanitized_html"]
    assert len(data["data"]["warnings"]) == 1

    # Raw format
    raw_resp = client_with_db.get("/api/v1/artifacts/art-html-1/render?format=raw")
    assert raw_resp.status_code == 200
    assert "text/html" in raw_resp.headers["content-type"]
    assert "cdn.tailwindcss.com" not in raw_resp.text
    assert "<h1>Landing</h1>" in raw_resp.text


def test_artifact_render_api_inline_content(client_with_db: TestClient):
    """Artifact with inline content in artifact_metadata is sanitized without requiring disk file."""
    _, task_id = _seed_project_and_task(client_with_db)
    settings = client_with_db.app_settings  # type: ignore[attr-defined]
    factory = init_db(settings.resolved_db_path)

    with factory() as session:
        art = Artifact(
            id="art-inline-1",
            task_id=task_id,
            name="preview.html",
            file_path="virtual.html",
            file_type="html",
            mime_type="text/html",
            artifact_metadata={"content_inline": "<div><h2>Pure Virtual</h2></div>"},
        )
        session.add(art)
        session.commit()

    resp = client_with_db.get("/api/v1/artifacts/art-inline-1/render")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "Pure Virtual" in data["sanitized_html"]
    assert "default-src 'none'" in data["sanitized_html"]


def test_artifact_render_api_markdown(client_with_db: TestClient):
    """Markdown artifact returns content safely."""
    _, task_id = _seed_project_and_task(client_with_db)
    settings = client_with_db.app_settings  # type: ignore[attr-defined]
    md_file = settings.workspace_dir / "BAN-GIAO.md"
    md_file.write_text("# Bàn Giao Kịch Bản\n\nNội dung chi tiết...", encoding="utf-8")

    factory = init_db(settings.resolved_db_path)
    with factory() as session:
        art = Artifact(
            id="art-md-1",
            task_id=task_id,
            name="BAN-GIAO.md",
            file_path="BAN-GIAO.md",
            file_type="markdown",
            mime_type="text/markdown",
        )
        session.add(art)
        session.commit()

    resp = client_with_db.get("/api/v1/artifacts/art-md-1/render")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["content"].startswith("# Bàn Giao Kịch Bản")
    assert data["sanitized_html"] is None
