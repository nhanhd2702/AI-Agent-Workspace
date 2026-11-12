"""Tests for HTTP Range Media Streaming and Storyboard Endpoints (Task 3.6).

Covers:
1. HTTP 206 Partial Content Range streaming:
   - Full content when Range header absent (200 OK, Accept-Ranges: bytes, Content-Length).
   - Range requests (bytes=0-1023, bytes=1024-, bytes=-500) return 206 Partial Content.
   - Out-of-bounds / invalid Range returns 416 Range Not Satisfiable with Content-Range: bytes */{total}.
   - Supported on both GET /api/v1/artifacts/{id}/stream and GET /api/v1/files/{id}/stream.
   - Path traversal guard (403 Forbidden).
   - Media MIME types (mp4, webm, mp3, wav, ogg, png, jpg).
   - Local auth token enforcement (401 Unauthorized).
2. Storyboard API:
   - GET /api/v1/artifacts/{id}/storyboard returns parsed storyboard JSON.
   - PATCH /api/v1/artifacts/{id}/storyboard/scenes/{scene_id} updates text/effect or deletes scene.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.artifacts.storyboard import Scene, Storyboard, StoryboardBuilder
from app.config import AppSettings
from app.db.models import Artifact, Project, Task, TaskStatus
from app.db.session import init_db
from app.main import create_app


@pytest.fixture
def client_with_db(tmp_path: Path) -> TestClient:
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="test-secret-token")
    app = create_app(settings)
    client = TestClient(app, headers={"X-Local-Auth-Token": "test-secret-token"})
    client.app_settings = settings  # type: ignore[attr-defined]
    return client


def _seed_project_and_task(client: TestClient) -> tuple[str, str]:
    settings = client.app_settings  # type: ignore[attr-defined]
    factory = init_db(settings.resolved_db_path)
    with factory() as session:
        proj = Project(id="proj-media-1", name="Media Test Project")
        session.add(proj)
        task = Task(
            id="task-media-1",
            project_id="proj-media-1",
            title="Video production task",
            status=TaskStatus.RUNNING,
        )
        session.add(task)
        session.commit()
    return "proj-media-1", "task-media-1"


# ============================================================================
# 1. Media Streaming Tests
# ============================================================================


def test_stream_media_auth_required(client_with_db: TestClient):
    """GET /stream endpoints require X-Local-Auth-Token."""
    no_auth_client = TestClient(client_with_db.app)
    resp = no_auth_client.get("/api/v1/artifacts/art-1/stream")
    assert resp.status_code == 401

    resp_file = no_auth_client.get("/api/v1/files/sample.mp4/stream")
    assert resp_file.status_code == 401


def test_stream_media_not_found(client_with_db: TestClient):
    """Non-existent artifact or file returns 404."""
    resp = client_with_db.get("/api/v1/artifacts/nonexistent-art/stream")
    assert resp.status_code == 404

    resp_file = client_with_db.get("/api/v1/files/missing-video.mp4/stream")
    assert resp_file.status_code == 404


def test_stream_media_path_traversal_guard(client_with_db: TestClient, tmp_path: Path):
    """Path traversal outside workspace returns 403 Forbidden."""
    outside_file = tmp_path.parent / "secret_video.mp4"
    outside_file.write_bytes(b"secret video bytes 1234567890")

    # Direct file route attempt
    resp = client_with_db.get(f"/api/v1/files/../{outside_file.name}/stream")
    assert resp.status_code in (403, 404)

    # Artifact database record pointing outside workspace
    _, task_id = _seed_project_and_task(client_with_db)
    settings = client_with_db.app_settings  # type: ignore[attr-defined]
    factory = init_db(settings.resolved_db_path)
    with factory() as session:
        art = Artifact(
            id="art-traversal-video",
            task_id=task_id,
            name="secret.mp4",
            file_path=str(outside_file),
            file_type="mp4",
            mime_type="video/mp4",
        )
        session.add(art)
        session.commit()

    resp_art = client_with_db.get("/api/v1/artifacts/art-traversal-video/stream")
    assert resp_art.status_code == 403


def test_stream_media_full_content_no_range(client_with_db: TestClient, tmp_path: Path):
    """When Range header is absent, returns 200 OK with full file content and headers."""
    media_content = b"VIDEO_HEADER_DATA_" + b"0123456789" * 100  # 1018 bytes
    media_file = tmp_path / "sample_video.mp4"
    media_file.write_bytes(media_content)

    _, task_id = _seed_project_and_task(client_with_db)
    settings = client_with_db.app_settings  # type: ignore[attr-defined]
    factory = init_db(settings.resolved_db_path)
    with factory() as session:
        art = Artifact(
            id="art-video-full",
            task_id=task_id,
            name="sample_video.mp4",
            file_path=str(media_file),
            file_type="mp4",
            mime_type="video/mp4",
            size_bytes=len(media_content),
        )
        session.add(art)
        session.commit()

    # Test via /api/v1/artifacts/{id}/stream
    resp = client_with_db.get("/api/v1/artifacts/art-video-full/stream")
    assert resp.status_code == 200
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["content-length"] == str(len(media_content))
    assert "video/mp4" in resp.headers["content-type"]
    assert resp.content == media_content

    # Test via /api/v1/files/{id}/stream (both artifact id and filename)
    resp_by_art_id = client_with_db.get("/api/v1/files/art-video-full/stream")
    assert resp_by_art_id.status_code == 200
    assert resp_by_art_id.content == media_content

    resp_by_filename = client_with_db.get("/api/v1/files/sample_video.mp4/stream")
    assert resp_by_filename.status_code == 200
    assert resp_by_filename.content == media_content


def test_stream_media_range_partial_content_206(client_with_db: TestClient, tmp_path: Path):
    """Range requests return 206 Partial Content with correct Content-Range and chunk."""
    # 200 bytes dummy payload
    data = bytes([i % 256 for i in range(200)])
    media_file = tmp_path / "audio_track.mp3"
    media_file.write_bytes(data)

    _, task_id = _seed_project_and_task(client_with_db)
    settings = client_with_db.app_settings  # type: ignore[attr-defined]
    factory = init_db(settings.resolved_db_path)
    with factory() as session:
        art = Artifact(
            id="art-audio-1",
            task_id=task_id,
            name="audio_track.mp3",
            file_path=str(media_file),
            file_type="mp3",
            mime_type="audio/mpeg",
            size_bytes=len(data),
        )
        session.add(art)
        session.commit()

    # 1. Exact range: bytes=0-49 (first 50 bytes)
    resp = client_with_db.get(
        "/api/v1/artifacts/art-audio-1/stream",
        headers={"Range": "bytes=0-49"},
    )
    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 0-49/200"
    assert resp.headers["content-length"] == "50"
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.content == data[0:50]

    # 2. Open end range: bytes=100- (bytes 100 to 199, total 100 bytes)
    resp2 = client_with_db.get(
        "/api/v1/artifacts/art-audio-1/stream",
        headers={"Range": "bytes=100-"},
    )
    assert resp2.status_code == 206
    assert resp2.headers["content-range"] == "bytes 100-199/200"
    assert resp2.headers["content-length"] == "100"
    assert resp2.content == data[100:200]

    # 3. Suffix range: bytes=-30 (last 30 bytes: 170-199)
    resp3 = client_with_db.get(
        "/api/v1/artifacts/art-audio-1/stream",
        headers={"Range": "bytes=-30"},
    )
    assert resp3.status_code == 206
    assert resp3.headers["content-range"] == "bytes 170-199/200"
    assert resp3.headers["content-length"] == "30"
    assert resp3.content == data[170:200]


def test_stream_media_invalid_range_416(client_with_db: TestClient, tmp_path: Path):
    """Out-of-bounds or invalid ranges return 416 Range Not Satisfiable."""
    media_file = tmp_path / "clip.webm"
    media_file.write_bytes(b"0123456789" * 10)  # 100 bytes

    # Start >= file size
    resp = client_with_db.get(
        "/api/v1/files/clip.webm/stream",
        headers={"Range": "bytes=500-600"},
    )
    assert resp.status_code == 416
    assert resp.headers["content-range"] == "bytes */100"

    # Start > End
    resp2 = client_with_db.get(
        "/api/v1/files/clip.webm/stream",
        headers={"Range": "bytes=50-20"},
    )
    assert resp2.status_code == 416
    assert resp2.headers["content-range"] == "bytes */100"


# ============================================================================
# 2. Storyboard Endpoints Tests
# ============================================================================


def test_storyboard_get_and_patch_api(client_with_db: TestClient, tmp_path: Path):
    """GET and PATCH /api/v1/artifacts/{id}/storyboard endpoints."""
    _, task_id = _seed_project_and_task(client_with_db)

    # Prepare storyboard data
    storyboard_data = {
        "style_name": "Rainmaker Style",
        "styleName": "Rainmaker Style",
        "total_duration": 5.0,
        "totalDuration": 5.0,
        "warnings": ["2 hiệu ứng mạnh diễn ra sát nhau ở cảnh s1 và s2"],
        "scenes": [
            {
                "scene_id": "s1",
                "sceneId": "s1",
                "start": 0.0,
                "end": 2.0,
                "duration": 2.0,
                "durationSec": 2.0,
                "overlay_text": "EDIT VIDEO",
                "overlayText": "EDIT VIDEO",
                "effect": "major_zoom",
            },
            {
                "scene_id": "s2",
                "sceneId": "s2",
                "start": 2.0,
                "end": 5.0,
                "duration": 3.0,
                "durationSec": 3.0,
                "overlay_text": "AI AGENT",
                "overlayText": "AI AGENT",
                "effect": "major_split",
            },
        ],
    }

    # Save to disk as storyboard.json
    sb_file = tmp_path / "storyboard.json"
    sb_file.write_text(json.dumps(storyboard_data), encoding="utf-8")

    settings = client_with_db.app_settings  # type: ignore[attr-defined]
    factory = init_db(settings.resolved_db_path)
    with factory() as session:
        art = Artifact(
            id="art-storyboard-1",
            task_id=task_id,
            name="storyboard.json",
            file_path=str(sb_file),
            file_type="json",
            mime_type="application/json",
            artifact_metadata={"storyboard": storyboard_data},
        )
        session.add(art)
        session.commit()

    # 1. GET /api/v1/artifacts/{id}/storyboard
    get_resp = client_with_db.get("/api/v1/artifacts/art-storyboard-1/storyboard")
    assert get_resp.status_code == 200
    res_data = get_resp.json()["data"]
    assert len(res_data["scenes"]) == 2
    assert res_data["totalDuration"] == 5.0

    # 2. PATCH scene s1: change text and effect
    patch_resp = client_with_db.patch(
        "/api/v1/artifacts/art-storyboard-1/storyboard/scenes/s1",
        json={"overlayText": "UPDATED INTRO", "effect": "none"},
    )
    assert patch_resp.status_code == 200
    updated_data = patch_resp.json()["data"]
    s1_updated = next(s for s in updated_data["scenes"] if s["sceneId"] == "s1")
    assert s1_updated["overlayText"] == "UPDATED INTRO"
    assert s1_updated["effect"] == "none"

    # 3. PATCH scene s2: delete scene
    delete_resp = client_with_db.patch(
        "/api/v1/artifacts/art-storyboard-1/storyboard/scenes/s2",
        json={"action": "delete"},
    )
    assert delete_resp.status_code == 200
    after_del_data = delete_resp.json()["data"]
    assert len(after_del_data["scenes"]) == 1
    assert after_del_data["scenes"][0]["sceneId"] == "s1"
    # Recalculated total duration
    assert pytest.approx(after_del_data["totalDuration"], 0.01) == 2.0
