"""Tests for FileExporter, Workspace Storage Quota Guard, Temp Cleanup, and File Library API (Task 5.3 / F06.5 / F03).

Covers:
1. Exact plan test: FileExporter.export_zip packages files safely and validates disk space.
2. InsufficientDiskSpaceError raised when destination filesystem free space is below threshold.
3. cleanup_old_temp_files(workspace, days=7) cleans files older than 7 days from temp/, frames/, cache/.
4. Path organization: organize_file_path(workspace, project, task_slug, filename) -> workspace/{project}/{YYYY-MM}/{task_slug}/{filename}.
5. POST /api/v1/files/upload: Multipart upload, path traversal validation, and 5GB quota check (HTTP 507).
6. GET /api/v1/files: File listing with filters (file_type, project_id, search).
7. POST /api/v1/files/export: Batch export files into ZIP archive download.
8. DELETE /api/v1/files/{file_id}: Delete physical file and DB record.
9. POST /api/v1/files/cleanup: Trigger temp files cleanup via API.
10. GET /api/v1/files/storage: Workspace storage usage summary (used bytes, limit, percentage).
11. Auth protection: X-Local-Auth-Token required on all endpoints.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.artifacts.exporter import (
    ExportResult,
    FileExporter,
    InsufficientDiskSpaceError,
    cleanup_old_temp_files,
    organize_file_path,
)
from app.config import AppSettings
from app.db.models import Artifact, FileAsset, Project, Task, TaskStatus
from app.main import create_app


# --- Fixtures ---

@pytest.fixture
def client_with_db(tmp_path: Path) -> TestClient:
    """FastAPI test client with initialized SQLite database and auth headers."""
    settings = AppSettings(
        workspace_dir=tmp_path,
        local_auth_token="test-secret-token",
        max_workspace_bytes=5 * 1024 * 1024 * 1024,
    )
    app = create_app(settings)
    client = TestClient(app, headers={"X-Local-Auth-Token": "test-secret-token"})
    client.app_settings = settings  # type: ignore[attr-defined]
    return client


# --- 1. FileExporter & Disk Space Tests ---

def test_export_zip_packages_files_and_checks_disk_space(tmp_path):
    """Exact test from plan: packages files and verifies ZIP archive contents."""
    f1 = tmp_path / "index.html"
    f2 = tmp_path / "BAN-GIAO.md"
    f1.write_text("<h1>OK</h1>", encoding="utf-8")
    f2.write_text("# Done", encoding="utf-8")
    out_zip = tmp_path / "bundle.zip"
    res = FileExporter.export_zip([f1, f2], out_zip)
    assert res.file_count == 2
    with zipfile.ZipFile(out_zip) as zf:
        assert set(zf.namelist()) == {"index.html", "BAN-GIAO.md"}


def test_export_zip_raises_insufficient_disk_space(tmp_path, monkeypatch):
    """FileExporter raises InsufficientDiskSpaceError when free space is insufficient."""
    f1 = tmp_path / "report.pdf"
    f1.write_bytes(b"A" * 1024)
    out_zip = tmp_path / "out.zip"

    # Simulate free disk space of only 500 bytes (less than file size + 10MB margin)
    def mock_disk_usage(path):
        import collections
        Usage = collections.namedtuple("usage", ["total", "used", "free"])
        return Usage(total=1000000, used=999500, free=500)

    monkeypatch.setattr(shutil, "disk_usage", mock_disk_usage)

    with pytest.raises(InsufficientDiskSpaceError):
        FileExporter.export_zip([f1], out_zip, min_free_bytes=10 * 1024 * 1024)


# --- 2. Temp File Cleanup Tests ---

def test_cleanup_old_temp_files(tmp_path):
    """cleanup_old_temp_files deletes files > 7 days old from temp/, frames/, cache/ only."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    temp_dir = workspace / "temp"
    frames_dir = workspace / "frames"
    cache_dir = workspace / "cache"
    output_dir = workspace / "outputs"  # should NOT be cleaned

    for d in (temp_dir, frames_dir, cache_dir, output_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Old files (> 7 days, e.g. 10 days ago)
    old_time = time.time() - (10 * 86400)
    old_temp = temp_dir / "old_scratch.txt"
    old_temp.write_text("old scratch", encoding="utf-8")
    os.utime(old_temp, (old_time, old_time))

    old_frame = frames_dir / "frame_001.png"
    old_frame.write_bytes(b"old frame")
    os.utime(old_frame, (old_time, old_time))

    old_cache = cache_dir / "cache_block.bin"
    old_cache.write_bytes(b"old cache")
    os.utime(old_cache, (old_time, old_time))

    # Old file in outputs directory (MUST NOT be touched)
    old_output = output_dir / "final_report.pdf"
    old_output.write_bytes(b"important report")
    os.utime(old_output, (old_time, old_time))

    # Recent files (< 7 days, e.g. 1 day ago)
    recent_time = time.time() - (1 * 86400)
    recent_temp = temp_dir / "recent.tmp"
    recent_temp.write_text("recent", encoding="utf-8")
    os.utime(recent_temp, (recent_time, recent_time))

    # Run cleanup
    result = cleanup_old_temp_files(workspace, days=7)

    assert result["cleaned_files"] == 3
    assert result["freed_bytes"] > 0

    assert not old_temp.exists()
    assert not old_frame.exists()
    assert not old_cache.exists()
    assert recent_temp.exists(), "Recent temp file should not be deleted"
    assert old_output.exists(), "Files outside temp/frames/cache must not be touched"


# --- 3. Path Organization Tests ---

def test_organize_file_path(tmp_path):
    """organize_file_path formats path into workspace/{project}/{YYYY-MM}/{task_slug}/{filename}."""
    organized = organize_file_path(
        workspace=tmp_path,
        project="proj-ecommerce",
        task_slug="tao-landing-page",
        filename="index.html",
    )
    parts = organized.relative_to(tmp_path).parts
    assert parts[0] == "proj-ecommerce"
    # parts[1] is YYYY-MM
    assert len(parts[1]) == 7 and parts[1][4] == "-"
    assert parts[2] == "tao-landing-page"
    assert parts[3] == "index.html"


# --- 4. API Endpoints Tests ---

def test_upload_file_api_and_quota_guard(client_with_db: TestClient, tmp_path: Path):
    """POST /api/v1/files/upload handles multipart upload, path validation, and 5GB quota limit."""
    # 1. Normal file upload
    file_bytes = b"<html><body>Test File</body></html>"
    files = {"file": ("landing.html", io.BytesIO(file_bytes), "text/html")}
    data = {"project_id": "proj-default", "task_slug": "demo-task"}

    resp = client_with_db.post("/api/v1/files/upload", files=files, data=data)
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert body["status"] == "success"
    uploaded = body["data"]
    assert uploaded["name"] == "landing.html"
    assert uploaded["size_bytes"] == len(file_bytes)
    assert uploaded["file_type"] in ("html", "code")

    # 2. Path traversal attack rejection
    bad_files = {"file": ("../../malicious.sh", io.BytesIO(b"echo 1"), "application/x-sh")}
    resp_bad = client_with_db.post("/api/v1/files/upload", files=bad_files, data=data)
    # Either filename is sanitized or rejected with 400 Bad Request
    if resp_bad.status_code == 201 or resp_bad.status_code == 200:
        bad_name = resp_bad.json()["data"]["name"]
        assert ".." not in bad_name
    else:
        assert resp_bad.status_code == 400

    # 3. Quota exceeded: When workspace storage exceeds 5GB, returns HTTP 507
    # Temporarily set max_workspace_bytes to a tiny limit (10 bytes)
    client_with_db.app.state.settings.max_workspace_bytes = 10
    heavy_file = {"file": ("heavy.bin", io.BytesIO(b"X" * 100), "application/octet-stream")}
    resp_quota = client_with_db.post("/api/v1/files/upload", files=heavy_file, data=data)
    assert resp_quota.status_code == 507
    assert "quota" in resp_quota.json()["detail"].lower() or "insufficient" in resp_quota.json()["detail"].lower()


def test_list_files_api_with_filters(client_with_db: TestClient):
    """GET /api/v1/files lists files and supports file_type, project_id, and search filtering."""
    # Seed 3 files
    client_with_db.app.state.settings.max_workspace_bytes = 5 * 1024 * 1024 * 1024

    f1 = {"file": ("banner.png", io.BytesIO(b"PNG_DATA"), "image/png")}
    client_with_db.post("/api/v1/files/upload", files=f1, data={"project_id": "p1", "task_slug": "t1"})

    f2 = {"file": ("kpi_report.pdf", io.BytesIO(b"PDF_DATA"), "application/pdf")}
    client_with_db.post("/api/v1/files/upload", files=f2, data={"project_id": "p1", "task_slug": "t2"})

    f3 = {"file": ("promo.mp4", io.BytesIO(b"MP4_DATA"), "video/mp4")}
    client_with_db.post("/api/v1/files/upload", files=f3, data={"project_id": "p2", "task_slug": "t3"})

    # 1. List all
    resp_all = client_with_db.get("/api/v1/files")
    assert resp_all.status_code == 200
    all_files = resp_all.json()["data"]
    assert len(all_files) >= 3

    # 2. Filter by file_type
    resp_img = client_with_db.get("/api/v1/files?file_type=image")
    assert resp_img.status_code == 200
    img_files = resp_img.json()["data"]
    assert all(f["file_type"] == "image" for f in img_files)
    assert any(f["name"] == "banner.png" for f in img_files)

    # 3. Filter by project_id
    resp_p2 = client_with_db.get("/api/v1/files?project_id=p2")
    assert resp_p2.status_code == 200
    p2_files = resp_p2.json()["data"]
    assert all(f.get("project_id") == "p2" for f in p2_files)

    # 4. Search filter
    resp_search = client_with_db.get("/api/v1/files?search=kpi")
    assert resp_search.status_code == 200
    search_files = resp_search.json()["data"]
    assert len(search_files) == 1
    assert "kpi" in search_files[0]["name"].lower()


def test_export_files_zip_api(client_with_db: TestClient):
    """POST /api/v1/files/export batches files into a ZIP download."""
    client_with_db.app.state.settings.max_workspace_bytes = 5 * 1024 * 1024 * 1024

    f1 = {"file": ("doc1.txt", io.BytesIO(b"Content One"), "text/plain")}
    f2 = {"file": ("doc2.txt", io.BytesIO(b"Content Two"), "text/plain")}

    r1 = client_with_db.post("/api/v1/files/upload", files=f1, data={"project_id": "p1"}).json()["data"]
    r2 = client_with_db.post("/api/v1/files/upload", files=f2, data={"project_id": "p1"}).json()["data"]

    # Export selected file IDs
    export_payload = {"file_ids": [r1["id"], r2["id"]]}
    resp_export = client_with_db.post("/api/v1/files/export", json=export_payload)

    assert resp_export.status_code == 200
    assert resp_export.headers["content-type"] == "application/zip"
    assert "attachment; filename=" in resp_export.headers.get("content-disposition", "")

    # Verify zip content
    zf = zipfile.ZipFile(io.BytesIO(resp_export.content))
    namelist = zf.namelist()
    assert "doc1.txt" in namelist
    assert "doc2.txt" in namelist
    assert zf.read("doc1.txt") == b"Content One"


def test_delete_file_api(client_with_db: TestClient):
    """DELETE /api/v1/files/{file_id} removes file from disk and database."""
    client_with_db.app.state.settings.max_workspace_bytes = 5 * 1024 * 1024 * 1024

    f = {"file": ("to_delete.txt", io.BytesIO(b"Delete me"), "text/plain")}
    uploaded = client_with_db.post("/api/v1/files/upload", files=f, data={"project_id": "p1"}).json()["data"]
    file_id = uploaded["id"]

    # Delete existing
    del_resp = client_with_db.delete(f"/api/v1/files/{file_id}")
    assert del_resp.status_code in (200, 204)

    # Second delete returns 404
    del_again = client_with_db.delete(f"/api/v1/files/{file_id}")
    assert del_again.status_code == 404


def test_cleanup_api(client_with_db: TestClient, tmp_path: Path):
    """POST /api/v1/files/cleanup deletes old temp files."""
    resp = client_with_db.post("/api/v1/files/cleanup?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "cleaned_files" in body["data"]
    assert "freed_bytes" in body["data"]


def test_storage_summary_api(client_with_db: TestClient):
    """GET /api/v1/files/storage returns workspace storage stats."""
    resp = client_with_db.get("/api/v1/files/storage")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "used_bytes" in body
    assert "max_bytes" in body
    assert "percentage" in body
    assert body["max_bytes"] == 5 * 1024 * 1024 * 1024


def test_files_api_auth_protection(client_with_db: TestClient):
    """Unauthenticated requests to /api/v1/files/* return 401 Unauthorized."""
    unauth_client = TestClient(client_with_db.app)

    assert unauth_client.get("/api/v1/files").status_code == 401
    assert unauth_client.get("/api/v1/files/storage").status_code == 401
    assert unauth_client.post("/api/v1/files/cleanup").status_code == 401
    assert unauth_client.post("/api/v1/files/export", json={"file_ids": []}).status_code == 401
