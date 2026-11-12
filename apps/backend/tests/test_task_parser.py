"""Tests for Natural Language Task Input & Intent Parser (F01.1).

Covers:
- Prompt text validation (1 <= len <= 2000, non-blank).
- Attachment limit validation (<= 10 attachments).
- URL extraction and isolation (ensuring YouTube handles like @AlexHormozi are NOT parsed as agent mentions).
- @Agent mention extraction, case-insensitivity, and deduplication against known agents.
- Primary task_type classification across all 8 supported types (Vietnamese and English).
- Entity extraction (target_count, format, etc.).
- Prompt history persistence capped at 50 entries with disk persistence and LRU-style ordering.
- API endpoints: POST /api/v1/tasks/parse (auth, 200, 422) and GET /api/v1/tasks/history.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.main import create_app
from app.orchestrator.parser import ParsedIntent, PromptValidationError, TaskParser
from app.db.models import Task, TaskStatus


# --- Unit Tests: TaskParser & NLP Logic ---

def test_parse_extracts_mentions_and_youtube_urls():
    """From brief: Extracts valid mentions and separates YouTube handles in URLs."""
    parser = TaskParser()
    res = parser.parse(
        "@DeepResearcher nghiên cứu https://www.youtube.com/@AlexHormozi tìm 3 video >10.000 view",
        attachment_ids=[],
        known_agents=["DeepResearcher", "ContentWriter"],
    )
    assert res.mentioned_agents == ["DeepResearcher"]
    assert "https://www.youtube.com/@AlexHormozi" in res.urls
    assert res.task_type == "content_research"


def test_parse_rejects_empty_or_over_2000_chars():
    """From brief: Rejects empty/blank prompts or prompts exceeding 2000 characters."""
    parser = TaskParser()
    with pytest.raises(PromptValidationError):
        parser.parse("   ", [], [])
    with pytest.raises(PromptValidationError):
        parser.parse("", [], [])
    with pytest.raises(PromptValidationError):
        parser.parse("a" * 2001, [], [])


def test_parse_rejects_more_than_10_attachments():
    """F01.1 rule: Rejects requests with more than 10 attachments."""
    parser = TaskParser()
    with pytest.raises(PromptValidationError) as exc_info:
        parser.parse("Hợp nhất tài liệu đính kèm", [f"file-{i}" for i in range(11)], [])
    assert "10" in str(exc_info.value)


def test_parse_strips_urls_and_does_not_falsely_mention_youtube_handle():
    """Ensure URL paths with @handles (YouTube, Twitter/X, GitHub) are not parsed as agent mentions."""
    parser = TaskParser()
    # Even if "alexhormozi" happened to be in known_agents, the URL must be stripped first!
    res = parser.parse(
        "Xem clip https://youtube.com/@AlexHormozi và bài viết https://x.com/@elonmusk/status/123",
        attachment_ids=[],
        known_agents=["DeepResearcher", "AlexHormozi", "ElonMusk"],
    )
    assert res.mentioned_agents == []
    assert len(res.urls) == 2
    assert "https://youtube.com/@AlexHormozi" in res.urls
    assert "https://x.com/@elonmusk/status/123" in res.urls


def test_parse_mention_case_insensitivity_and_deduplication():
    """Mentions should be matched case-insensitively to canonical names and deduplicated preserving order."""
    parser = TaskParser()
    prompt = "@deepresearcher hãy phối hợp cùng @CONTENTWRITER và @DeepResearcher để viết bài"
    res = parser.parse(
        prompt,
        attachment_ids=[],
        known_agents=["DeepResearcher", "ContentWriter", "VideoEditor"],
    )
    assert res.mentioned_agents == ["DeepResearcher", "ContentWriter"]


@pytest.mark.parametrize(
    ("prompt", "expected_type"),
    [
        ("Nghiên cứu 5 kênh YouTube đối thủ và xu hướng thị trường", "content_research"),
        ("Research competitor market trends and scrape recent video benchmarks", "content_research"),
        ("Viết kịch bản video TikTok 60 giây và soạn bài đăng Facebook", "copywriting"),
        ("Draft a high-converting email newsletter copy and headline", "copywriting"),
        ("Thiết kế banner 1200x630 và hình ảnh thumbnail cho khóa học", "image_design"),
        ("Design social poster graphics and SVG visual layout", "image_design"),
        ("Dựng video ngắn TikTok 30s cắt ghép ffmpeg theo timeline storyboard", "video_edit"),
        ("Edit short reel clips with pacing rhythm and captions", "video_edit"),
        ("Xây dựng chiến lược phễu bán hàng đa tầng và tối ưu tỷ lệ chuyển đổi", "funnel_strategy"),
        ("Develop sales funnel strategy with pricing tiers and upsell flow", "funnel_strategy"),
        ("Tạo giao diện landing page responsive cho sản phẩm mới bằng HTML", "landing_page"),
        ("Build responsive landing page UI template for our software", "landing_page"),
        ("Soạn kịch bản tư vấn bán hàng và xử lý từ chối cho khách hàng Zalo", "sales_chat"),
        ("Sales chat objection handling and customer support consultation script", "sales_chat"),
        ("Lập bảng phân công công việc tuần tới", "general"),
    ],
)
def test_task_type_classification_vietnamese_and_english(prompt: str, expected_type: str):
    """Accurately classifies prompts across all 8 supported task types in VI and EN."""
    parser = TaskParser()
    res = parser.parse(prompt, attachment_ids=[], known_agents=[])
    assert res.task_type == expected_type


def test_entities_extraction():
    """Extracts target counts and formats into entities."""
    parser = TaskParser()
    res = parser.parse(
        "Nghiên cứu 5 ý tưởng video YouTube kèm báo cáo HTML",
        attachment_ids=["file-1", "file-2"],
        known_agents=["DeepResearcher"],
    )
    assert res.entities["target_count"] == 5
    assert res.entities["output_format"] == "html_app"
    assert res.entities["files"] == ["file-1", "file-2"]


def test_prompt_history_cap_50_and_persistence(tmp_path: Path):
    """Prompt history must be capped at 50 entries and persist to disk."""
    history_file = tmp_path / "prompt_history.json"
    parser1 = TaskParser(history_file=history_file)

    # Submit 60 distinct prompts
    for i in range(60):
        parser1.parse(f"Prompt number {i:03d}", attachment_ids=[], known_agents=[])

    history1 = parser1.get_history()
    assert len(history1) == 50
    # Most recent prompt should be at the front
    assert history1[0] == "Prompt number 059"
    # Oldest retained prompt should be 10 (0..9 evicted)
    assert history1[-1] == "Prompt number 010"

    # Reload with a new parser instance from the same history file
    parser2 = TaskParser(history_file=history_file)
    history2 = parser2.get_history()
    assert len(history2) == 50
    assert history2 == history1


# --- Integration Tests: FastAPI Endpoints ---

def test_api_parse_requires_auth(tmp_path: Path):
    """POST /api/v1/tasks/parse must require valid X-Local-Auth-Token."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="test-token")
    client = TestClient(create_app(settings))

    payload = {"prompt_text": "Phân tích đối thủ"}
    # Missing token -> 401
    resp = client.post("/api/v1/tasks/parse", json=payload)
    assert resp.status_code == 401

    # Invalid token -> 401
    resp = client.post(
        "/api/v1/tasks/parse",
        json=payload,
        headers={"X-Local-Auth-Token": "wrong-token"},
    )
    assert resp.status_code == 401


def test_api_parse_success_and_creates_task(tmp_path: Path):
    """POST /api/v1/tasks/parse parses intent, extracts entities, and creates Task in DB."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="test-token")
    app = create_app(settings)
    client = TestClient(app)

    payload = {
        "project_id": "proj-default",
        "prompt_text": "@DeepResearcher nghiên cứu 3 video YouTube https://www.youtube.com/@AlexHormozi",
        "attachment_ids": [],
        "mode": "copilot",
    }
    resp = client.post(
        "/api/v1/tasks/parse",
        json=payload,
        headers={"X-Local-Auth-Token": "test-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"

    data = body["data"]
    assert data["task_id"].startswith("task-")
    assert data["task_type"] == "content_research"
    assert data["mentioned_agents"] == ["DeepResearcher"]
    assert "https://www.youtube.com/@AlexHormozi" in data["urls"]
    assert data["entities"]["target_count"] == 3

    # Check Task in DB
    from app.db.session import init_db
    SessionLocal = init_db(settings.resolved_db_path)
    with SessionLocal() as db:
        task = db.get(Task, data["task_id"])
        assert task is not None
        assert task.status == TaskStatus.PENDING
        assert task.project_id == "proj-default"
        assert task.task_metadata["task_type"] == "content_research"


def test_api_parse_validation_errors(tmp_path: Path):
    """POST /api/v1/tasks/parse returns 422 for blank prompt or prompt > 2000 chars."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="test-token")
    client = TestClient(create_app(settings))
    headers = {"X-Local-Auth-Token": "test-token"}

    # Blank prompt
    resp = client.post("/api/v1/tasks/parse", json={"prompt_text": "   "}, headers=headers)
    assert resp.status_code == 422
    assert "detail" in resp.json()

    # Over 2000 chars
    resp = client.post("/api/v1/tasks/parse", json={"prompt_text": "a" * 2001}, headers=headers)
    assert resp.status_code == 422

    # Over 10 attachments
    resp = client.post(
        "/api/v1/tasks/parse",
        json={"prompt_text": "Hợp nhất", "attachment_ids": [f"f{i}" for i in range(11)]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_api_tasks_history_endpoint(tmp_path: Path):
    """GET /api/v1/tasks/history returns recent prompts and filters for autocomplete."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="test-token")
    client = TestClient(create_app(settings))
    headers = {"X-Local-Auth-Token": "test-token"}

    # Submit 2 prompts
    client.post("/api/v1/tasks/parse", json={"prompt_text": "Nghiên cứu đối thủ YouTube"}, headers=headers)
    client.post("/api/v1/tasks/parse", json={"prompt_text": "Viết bài Facebook"}, headers=headers)

    # Get history
    resp = client.get("/api/v1/tasks/history", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "Viết bài Facebook" in body["data"]
    assert "Nghiên cứu đối thủ YouTube" in body["data"]

    # Filter with autocomplete query
    resp_filter = client.get("/api/v1/tasks/history?query=YouTube", headers=headers)
    assert resp_filter.status_code == 200
    filtered_data = resp_filter.json()["data"]
    assert len(filtered_data) == 1
    assert "YouTube" in filtered_data[0]


def test_openapi_schema_does_not_leak_db_path(tmp_path: Path):
    """Ensure get_db dependency does not expose db_path as a query param in OpenAPI schema."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="test-token")
    app = create_app(settings)
    schema = app.openapi()
    parse_op = schema["paths"]["/api/v1/tasks/parse"]["post"]
    params = parse_op.get("parameters", [])
    param_names = [p["name"] for p in params]
    assert "db_path" not in param_names


def test_api_parse_rejects_unknown_project_id(tmp_path: Path):
    """POST /api/v1/tasks/parse returns 404 when project_id does not exist and does not pollute history."""
    settings = AppSettings(workspace_dir=tmp_path, local_auth_token="test-token")
    client = TestClient(create_app(settings))
    headers = {"X-Local-Auth-Token": "test-token"}

    resp = client.post(
        "/api/v1/tasks/parse",
        json={"project_id": "proj-nonexistent", "prompt_text": "Lệnh không hợp lệ"},
        headers=headers,
    )
    assert resp.status_code == 404
    assert "proj-nonexistent" in resp.json()["detail"]

    # Verify history was not polluted
    hist_resp = client.get("/api/v1/tasks/history", headers=headers)
    assert "Lệnh không hợp lệ" not in hist_resp.json()["data"]
