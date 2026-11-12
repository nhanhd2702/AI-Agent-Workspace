"""Unit and security tests for External API Connectors (YouTube, Google Sheets, Notion) - Task 3.2."""

from __future__ import annotations

from typing import Any, Optional
import pytest

from app.db.models import ConnectorConfig
from app.mcp.external_apis import (
    ConnectorHealthResult,
    ExternalApiError,
    NotionClient,
    NotionPageResult,
    SheetsAppendResult,
    SheetsClient,
    TranscriptResult,
    VideoMeta,
    YouTubeClient,
    build_connector_client,
    extract_channel_identifier,
)


class MockYouTubeTransport:
    """Mock in-memory transport for YouTubeClient tests."""

    def __init__(self) -> None:
        self.disabled_captions: set[str] = set()
        self.transcripts: dict[str, TranscriptResult] = {}
        self.channel_videos: dict[str, list[VideoMeta]] = {}
        self.is_healthy: bool = True

    def set_captions_disabled(self, video_id: str) -> None:
        self.disabled_captions.add(video_id)

    def set_transcript(
        self,
        video_id: str,
        text: str,
        segments: Optional[list[dict[str, Any]]] = None,
        language: str = "vi",
    ) -> None:
        self.transcripts[video_id] = TranscriptResult(
            video_id=video_id,
            available=True,
            language=language,
            segments=segments or [],
            text=text,
            note=None,
        )

    def set_channel_videos(self, channel_key: str, videos: list[VideoMeta]) -> None:
        self.channel_videos[channel_key] = videos

    def fetch_transcript(self, video_id: str) -> TranscriptResult:
        if video_id in self.disabled_captions:
            return TranscriptResult(
                video_id=video_id,
                available=False,
                note="Không đọc được phụ đề",
            )
        if video_id in self.transcripts:
            return self.transcripts[video_id]
        return TranscriptResult(
            video_id=video_id,
            available=False,
            note="Không đọc được phụ đề",
        )

    def fetch_channel_videos(
        self, channel_url: str, min_views: int = 0, limit: int = 20
    ) -> list[VideoMeta]:
        # Return matched videos for channel or default list
        all_vids = self.channel_videos.get(channel_url, [])
        if not all_vids:
            for k, v in self.channel_videos.items():
                if k in channel_url:
                    all_vids = v
                    break
        filtered = [v for v in all_vids if v.view_count >= min_views]
        return filtered[:limit]

    def health_check(self) -> ConnectorHealthResult:
        return ConnectorHealthResult(
            provider="youtube",
            healthy=self.is_healthy,
            latency_ms=12.5,
            error=None if self.is_healthy else "Service unavailable",
        )


class MockSheetsTransport:
    """Mock transport for Google Sheets client."""

    def __init__(self) -> None:
        self.appended_calls: list[dict[str, Any]] = []
        self.data: dict[str, list[list[Any]]] = {}
        self.fail_with_secret: Optional[str] = None

    def append_rows(
        self, spreadsheet_id: str, sheet_range: str, rows: list[list[Any]]
    ) -> SheetsAppendResult:
        if self.fail_with_secret:
            raise RuntimeError(f"Google API Error with auth token: {self.fail_with_secret}")
        self.appended_calls.append(
            {"spreadsheet_id": spreadsheet_id, "sheet_range": sheet_range, "rows": rows}
        )
        existing = self.data.setdefault(spreadsheet_id, [])
        existing.extend(rows)
        return SheetsAppendResult(
            spreadsheet_id=spreadsheet_id,
            sheet_range=sheet_range,
            rows_appended=len(rows),
            updated_range=f"{sheet_range}!A1:Z{len(rows)}",
            raw_response={"updates": {"updatedRows": len(rows)}},
        )

    def read_rows(self, spreadsheet_id: str, sheet_range: str) -> list[list[Any]]:
        return self.data.get(spreadsheet_id, [])

    def health_check(self) -> ConnectorHealthResult:
        return ConnectorHealthResult(
            provider="google_sheets",
            healthy=True,
            latency_ms=25.0,
        )


class MockNotionTransport:
    """Mock transport for Notion client."""

    def __init__(self) -> None:
        self.created_pages: list[dict[str, Any]] = []
        self.databases: dict[str, list[dict[str, Any]]] = {}
        self.fail_with_secret: Optional[str] = None

    def create_page(
        self,
        parent_id: str,
        title: str,
        content_blocks: Optional[list[dict[str, Any]]] = None,
        properties: Optional[dict[str, Any]] = None,
        parent_type: str = "database",
    ) -> NotionPageResult:
        if self.fail_with_secret:
            raise RuntimeError(f"Notion unauthorized with bearer {self.fail_with_secret}")
        page_id = f"page-{len(self.created_pages) + 1}"
        record = {
            "page_id": page_id,
            "parent_id": parent_id,
            "parent_type": parent_type,
            "title": title,
            "content_blocks": content_blocks or [],
            "properties": properties or {},
        }
        self.created_pages.append(record)
        return NotionPageResult(
            page_id=page_id,
            url=f"https://notion.so/{page_id}",
            title=title,
            parent_id=parent_id,
            raw_response={
                "id": page_id,
                "object": "page",
                "parent": {f"{parent_type}_id": parent_id},
            },
        )

    def query_database(
        self,
        database_id: str,
        filter_payload: Optional[dict[str, Any]] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        results = self.databases.get(database_id, [])
        return results[:limit]

    def health_check(self) -> ConnectorHealthResult:
        return ConnectorHealthResult(
            provider="notion",
            healthy=True,
            latency_ms=30.0,
        )


@pytest.fixture
def mock_yt_transport() -> MockYouTubeTransport:
    return MockYouTubeTransport()


# ---------------------------------------------------------------------------
# YouTube Client Tests
# ---------------------------------------------------------------------------

def test_transcript_missing_returns_explicit_unreadable_flag(mock_yt_transport: MockYouTubeTransport) -> None:
    """Exact test specified in task-3.2-brief.md."""
    mock_yt_transport.set_captions_disabled("vid123")
    client = YouTubeClient(api_key="test", transport=mock_yt_transport)
    res = client.fetch_transcript("vid123")
    assert res.available is False
    assert res.note == "Không đọc được phụ đề"


def test_transcript_available_returns_full_metadata(mock_yt_transport: MockYouTubeTransport) -> None:
    mock_yt_transport.set_transcript(
        "vid_vn_01",
        text="Xin chào các bạn đến với AI Agent Workspace",
        segments=[{"start": 0.0, "duration": 3.5, "text": "Xin chào các bạn"}],
        language="vi",
    )
    client = YouTubeClient(api_key="test_key", transport=mock_yt_transport)
    res = client.fetch_transcript("vid_vn_01")
    assert res.available is True
    assert res.video_id == "vid_vn_01"
    assert res.language == "vi"
    assert "Xin chào các bạn" in res.text
    assert len(res.segments) == 1
    assert res.note is None


def test_transcript_invalid_video_id_rejected() -> None:
    client = YouTubeClient(api_key="test")
    # Path traversal, illegal characters, command injection attempts
    invalid_ids = [
        "../../etc/passwd",
        "vid; rm -rf /",
        "vid space",
        "vid$evil",
        "vid\nwhoami",
        "",
        "a" * 128,
    ]
    for bad_id in invalid_ids:
        with pytest.raises(ExternalApiError):
            client.fetch_transcript(bad_id)


def test_youtube_fetch_channel_videos_filters_min_views_and_limit(
    mock_yt_transport: MockYouTubeTransport,
) -> None:
    channel_url = "https://www.youtube.com/@AIChannelOfficial"
    videos = [
        VideoMeta(
            video_id="v1",
            title="Video 1 Low Views",
            view_count=500,
            thumbnail_url="https://img.youtube.com/vi/v1/hqdefault.jpg",
            url="https://www.youtube.com/watch?v=v1",
            duration_seconds=120,
        ),
        VideoMeta(
            video_id="v2",
            title="Video 2 Trending",
            view_count=50000,
            thumbnail_url="https://img.youtube.com/vi/v2/hqdefault.jpg",
            url="https://www.youtube.com/watch?v=v2",
            duration_seconds=300,
        ),
        VideoMeta(
            video_id="v3",
            title="Video 3 Mega Viral",
            view_count=200000,
            thumbnail_url="https://img.youtube.com/vi/v3/hqdefault.jpg",
            url="https://www.youtube.com/watch?v=v3",
            duration_seconds=450,
        ),
    ]
    mock_yt_transport.set_channel_videos(channel_url, videos)

    client = YouTubeClient(api_key="test_key", transport=mock_yt_transport)

    # Filter with min_views=10000, limit=2
    res = client.fetch_channel_videos(channel_url, min_views=10000, limit=2)
    assert len(res) == 2
    assert res[0].video_id == "v2"
    assert res[0].view_count == 50000
    assert res[1].video_id == "v3"
    assert res[1].view_count == 200000

    # Test limit=1
    res_limited = client.fetch_channel_videos(channel_url, min_views=10000, limit=1)
    assert len(res_limited) == 1
    assert res_limited[0].video_id == "v2"


def test_youtube_fetch_channel_videos_ssrf_and_domain_protection(
    mock_yt_transport: MockYouTubeTransport,
) -> None:
    client = YouTubeClient(api_key="test_key", transport=mock_yt_transport)

    dangerous_urls = [
        "http://169.254.169.254/latest/meta-data",
        "http://127.0.0.1:8000/internal",
        "https://evil.attacker.com/@fakechannel",
        "ftp://youtube.com/@channel",
        "https://youtube.com\\@evil.com",
    ]
    for bad_url in dangerous_urls:
        with pytest.raises(ExternalApiError):
            client.fetch_channel_videos(bad_url)


def test_youtube_health_check(mock_yt_transport: MockYouTubeTransport) -> None:
    client = YouTubeClient(api_key="test_key", transport=mock_yt_transport)
    health = client.health_check()
    assert health.healthy is True
    assert health.provider == "youtube"

    mock_yt_transport.is_healthy = False
    unhealthy = client.health_check()
    assert unhealthy.healthy is False
    assert "unavailable" in (unhealthy.error or "")


# ---------------------------------------------------------------------------
# Google Sheets Client Tests
# ---------------------------------------------------------------------------

def test_sheets_append_rows_success_and_read() -> None:
    transport = MockSheetsTransport()
    client = SheetsClient(credentials={"token": "fake"}, transport=transport)

    rows = [
        ["Title", "Views", "URL"],
        ["AI Video 1", 15000, "https://youtube.com/watch?v=1"],
    ]
    res = client.append_rows(
        spreadsheet_id="sheet_abc_123",
        sheet_range="Sheet1!A1",
        rows=rows,
    )
    assert isinstance(res, SheetsAppendResult)
    assert res.spreadsheet_id == "sheet_abc_123"
    assert res.rows_appended == 2

    # Read back
    read_data = client.read_rows("sheet_abc_123", "Sheet1!A1:C2")
    assert len(read_data) == 2
    assert read_data[1][0] == "AI Video 1"


def test_sheets_validation_rejects_empty_inputs() -> None:
    transport = MockSheetsTransport()
    client = SheetsClient(credentials="token", transport=transport)

    with pytest.raises(ExternalApiError, match="spreadsheet_id"):
        client.append_rows("", "Sheet1!A1", [["val"]])

    with pytest.raises(ExternalApiError, match="sheet_range"):
        client.append_rows("id123", "", [["val"]])

    with pytest.raises(ExternalApiError, match="rows"):
        client.append_rows("id123", "Sheet1!A1", [])


def test_sheets_missing_credentials_raises_error() -> None:
    client = SheetsClient(credentials=None, transport=None)
    with pytest.raises(ExternalApiError, match="credentials or transport required"):
        client.append_rows("id123", "Sheet1!A1", [["data"]])


def test_sheets_masks_secrets_in_errors() -> None:
    secret_token = "ya29.a0AfH6SMB_secret_oauth_token_val_12345"
    transport = MockSheetsTransport()
    transport.fail_with_secret = secret_token
    client = SheetsClient(credentials=secret_token, transport=transport)

    with pytest.raises(ExternalApiError) as exc_info:
        client.append_rows("sheet_123", "Sheet1!A1", [["data"]])

    err_msg = str(exc_info.value)
    assert secret_token not in err_msg
    assert "***REDACTED***" in err_msg


# ---------------------------------------------------------------------------
# Notion Client Tests
# ---------------------------------------------------------------------------

def test_notion_create_page_and_query_database() -> None:
    transport = MockNotionTransport()
    transport.databases["db_test_id"] = [
        {"id": "row_1", "title": "First row"},
        {"id": "row_2", "title": "Second row"},
    ]
    client = NotionClient(api_token="ntn_fake_token", transport=transport)

    # Create page
    page = client.create_page(
        parent_id="parent_page_123",
        title="Bản tin AI Tuần 45",
        content_blocks=[{"object": "block", "type": "paragraph"}],
        properties={"Status": {"select": {"name": "Draft"}}},
    )
    assert isinstance(page, NotionPageResult)
    assert page.title == "Bản tin AI Tuần 45"
    assert page.parent_id == "parent_page_123"
    assert "notion.so" in (page.url or "")

    # Query database
    db_items = client.query_database("db_test_id", limit=1)
    assert len(db_items) == 1
    assert db_items[0]["id"] == "row_1"


def test_notion_validation_and_missing_token() -> None:
    client = NotionClient(api_token=None, transport=None)
    with pytest.raises(ExternalApiError, match="api_token or transport required"):
        client.create_page(parent_id="p1", title="Title")

    client_with_token = NotionClient(api_token="valid_token", transport=MockNotionTransport())
    with pytest.raises(ExternalApiError, match="parent_id"):
        client_with_token.create_page(parent_id="", title="Title")

    with pytest.raises(ExternalApiError, match="title"):
        client_with_token.create_page(parent_id="p1", title="")


def test_notion_masks_secrets_in_errors() -> None:
    secret_token = "secret_notion_api_token_value_987654321"
    transport = MockNotionTransport()
    transport.fail_with_secret = secret_token
    client = NotionClient(api_token=secret_token, transport=transport)

    with pytest.raises(ExternalApiError) as exc_info:
        client.create_page(parent_id="p1", title="Title")

    err_msg = str(exc_info.value)
    assert secret_token not in err_msg
    assert "***REDACTED***" in err_msg


# ---------------------------------------------------------------------------
# ConnectorConfig Factory & Secret Safety
# ---------------------------------------------------------------------------

def test_build_connector_client_youtube() -> None:
    cfg = ConnectorConfig(
        id="conn-yt",
        name="YouTube Connector",
        provider="youtube",
        auth_payload='{"api_key": "AIzaSyTestApiKey123456789"}',
        status="connected",
        is_enabled=True,
    )
    client = build_connector_client(cfg)
    assert isinstance(client, YouTubeClient)
    assert client.api_key == "AIzaSyTestApiKey123456789"
    # Ensure repr or str doesn't expose api key in raw form
    assert "AIzaSyTestApiKey123456789" not in repr(client)


def test_build_connector_client_sheets() -> None:
    cfg = ConnectorConfig(
        id="conn-sheets",
        name="Sheets Connector",
        provider="google_sheets",
        auth_payload='{"client_email": "sa@proj.iam.gserviceaccount.com", "private_key": "secret_key"}',
        status="connected",
        is_enabled=True,
    )
    client = build_connector_client(cfg)
    assert isinstance(client, SheetsClient)
    assert "secret_key" not in repr(client)


def test_build_connector_client_notion() -> None:
    cfg = ConnectorConfig(
        id="conn-notion",
        name="Notion Connector",
        provider="notion",
        auth_payload="secret_notion_raw_token_12345",
        status="connected",
        is_enabled=True,
    )
    client = build_connector_client(cfg)
    assert isinstance(client, NotionClient)
    assert "secret_notion_raw_token_12345" not in repr(client)


def test_build_connector_client_unsupported_provider() -> None:
    cfg = ConnectorConfig(
        id="conn-unsupported",
        name="Unknown",
        provider="unsupported_crm",
        auth_payload="{}",
    )
    with pytest.raises(ExternalApiError, match="Unsupported connector provider"):
        build_connector_client(cfg)


# ---------------------------------------------------------------------------
# Extended Tests: Dataclass Serialization, Direct Masking, Dict Transports
# ---------------------------------------------------------------------------

def test_external_api_error_masks_known_and_extra_secrets() -> None:
    err = ExternalApiError(
        "Request failed for api_key='sk-1234567890abcdef' with custom extra=secret-val-9999",
        extra_secrets=["secret-val-9999"],
        status_code=401,
    )
    msg = str(err)
    assert "sk-1234567890abcdef" not in msg
    assert "secret-val-9999" not in msg
    assert "***REDACTED***" in msg
    assert err.status_code == 401


def test_models_to_dict_and_defaults() -> None:
    v = VideoMeta(
        video_id="vid01",
        title="Title",
        view_count=100,
        thumbnail_url="http://thumb",
        url="http://url",
    )
    v_dict = v.to_dict()
    assert v_dict["video_id"] == "vid01"
    assert v_dict["view_count"] == 100

    t = TranscriptResult(video_id="vid01", available=False)
    assert t.note == "Không đọc được phụ đề"
    t_dict = t.to_dict()
    assert t_dict["note"] == "Không đọc được phụ đề"

    s = SheetsAppendResult(spreadsheet_id="s1", sheet_range="A1", rows_appended=5)
    assert s.to_dict()["rows_appended"] == 5

    n = NotionPageResult(page_id="p1", title="Notion Title")
    assert n.to_dict()["title"] == "Notion Title"

    h = ConnectorHealthResult(provider="youtube", healthy=True)
    assert h.to_dict()["healthy"] is True


def test_youtube_fetch_channel_videos_dict_items_and_bounds() -> None:
    class DictTransport:
        def fetch_channel_videos(self, url: str, min_views: int = 0, limit: int = 20) -> list[dict[str, Any]]:
            return [
                {
                    "video_id": "v_dict_1",
                    "title": "Dict Title",
                    "view_count": 25000,
                    "thumbnail_url": "https://img.youtube.com/thumb.jpg",
                    "duration_seconds": 180,
                }
            ]

    client = YouTubeClient(api_key="key", transport=DictTransport())
    videos = client.fetch_channel_videos("https://www.youtube.com/@Channel", min_views=1000)
    assert len(videos) == 1
    assert videos[0].video_id == "v_dict_1"
    assert videos[0].duration_seconds == 180
    assert "https://www.youtube.com/watch?v=v_dict_1" in videos[0].url

    # Test bounds validation
    with pytest.raises(ExternalApiError, match="limit must be at least 1"):
        client.fetch_channel_videos("https://www.youtube.com/@Channel", limit=0)

    with pytest.raises(ExternalApiError, match="min_views cannot be negative"):
        client.fetch_channel_videos("https://www.youtube.com/@Channel", min_views=-5)


# ---------------------------------------------------------------------------
# Strict Review Hardening Tests (Items 1 - 8)
# ---------------------------------------------------------------------------

def test_youtube_missing_view_count_never_fabricated() -> None:
    """Item 1: If view_count/viewCount is None or missing, skip video instead of fabricating 0."""
    class MissingViewCountTransport:
        def fetch_channel_videos(self, url: str, min_views: int = 0, limit: int = 20) -> list[dict[str, Any]]:
            return [
                {
                    "video_id": "v_missing_vc",
                    "title": "Video Without View Count",
                    "view_count": None,  # Should be skipped, NEVER fabricated as 0
                    "thumbnail_url": "https://img.youtube.com/thumb.jpg",
                },
                {
                    "video_id": "v_has_vc",
                    "title": "Valid Video",
                    "view_count": 15000,
                    "thumbnail_url": "https://img.youtube.com/thumb2.jpg",
                },
            ]

    client = YouTubeClient(api_key="key", transport=MissingViewCountTransport())
    videos = client.fetch_channel_videos("https://www.youtube.com/@Channel", min_views=0)
    assert len(videos) == 1
    assert videos[0].video_id == "v_has_vc"
    assert videos[0].view_count == 15000


def test_youtube_channel_subpath_extraction() -> None:
    """Item 2: Subpaths like /videos, /shorts, /featured are stripped and identifiers extracted."""
    # @Handle with subpaths
    id_type, ident = extract_channel_identifier("https://www.youtube.com/@AIChannelOfficial/videos")
    assert id_type == "handle"
    assert ident == "@AIChannelOfficial"

    id_type, ident = extract_channel_identifier("https://www.youtube.com/@Creator/shorts")
    assert id_type == "handle"
    assert ident == "@Creator"

    # /channel/UC... with subpath
    id_type, ident = extract_channel_identifier("https://www.youtube.com/channel/UC1234567890/featured")
    assert id_type == "channel_id"
    assert ident == "UC1234567890"

    # /c/CustomName and /user/Username
    id_type, ident = extract_channel_identifier("https://www.youtube.com/c/CustomChannel/community")
    assert id_type == "custom"
    assert ident == "CustomChannel"

    id_type, ident = extract_channel_identifier("https://www.youtube.com/user/LegacyUser/playlists")
    assert id_type == "user"
    assert ident == "LegacyUser"


def test_sheets_resource_id_and_range_injection_rejection() -> None:
    """Item 3: Strict validation against path traversal and URI injection characters."""
    client = SheetsClient(credentials={"token": "valid_token"}, transport=MockSheetsTransport())

    # spreadsheet_id invalid injection
    for bad_id in ["../secret_sheet", "sheet#fragment", "sheet?param=1", "sheet id with spaces", ""]:
        with pytest.raises(ExternalApiError, match="spreadsheet_id"):
            client.append_rows(bad_id, "Sheet1!A1", [["v"]])

    # sheet_range URI injection characters
    for bad_range in ["Sheet1/values", "Sheet1\\values", "Sheet1?evil=1", "Sheet1#anchor", ""]:
        with pytest.raises(ExternalApiError, match="sheet_range"):
            client.append_rows("valid_sheet_id", bad_range, [["v"]])


def test_sheets_live_http_missing_token_raises_error() -> None:
    """Item 5: Credentials without valid token must fail cleanly without empty Authorization header."""
    client = SheetsClient(credentials={"client_email": "sa@example.com"}, transport=None)
    with pytest.raises(ExternalApiError, match="Google Sheets credentials require a valid 'token' or 'access_token'"):
        client.append_rows("valid_sheet_id", "Sheet1!A1", [["v"]])


def test_notion_resource_id_injection_rejection() -> None:
    """Item 3: Validate parent_id and database_id against strict regex."""
    client = NotionClient(api_token="valid_token", transport=MockNotionTransport())

    for bad_parent in ["../secret_page", "page#frag", "page?query=1", "parent id with spaces", ""]:
        with pytest.raises(ExternalApiError, match="parent_id"):
            client.create_page(bad_parent, "Title")

    for bad_db in ["../secret_db", "db#frag", "db?filter=all", ""]:
        with pytest.raises(ExternalApiError, match="database_id"):
            client.query_database(bad_db)


def test_notion_parent_type_parameter_and_validation() -> None:
    """Item 4: Explicit parent_type ('database' vs 'page') instead of '-' heuristic."""
    transport = MockNotionTransport()
    client = NotionClient(api_token="valid_token", transport=transport)

    # Page with parent_type="page" (even with dashed UUID)
    res_page = client.create_page("uuid-1234-page", "Page Title", parent_type="page")
    assert res_page.title == "Page Title"
    assert transport.created_pages[-1]["parent_type"] == "page"

    # Database with parent_type="database"
    res_db = client.create_page("uuid5678db", "DB Row Title", parent_type="database")
    assert res_db.title == "DB Row Title"
    assert transport.created_pages[-1]["parent_type"] == "database"

    # Invalid parent_type rejected
    with pytest.raises(ExternalApiError, match="parent_type"):
        client.create_page("uuid-1234", "Title", parent_type="invalid_type")  # type: ignore[arg-type]


def test_notion_empty_token_raises_error() -> None:
    """Item 8: Empty or whitespace api_token fails _require_auth cleanly."""
    for empty_tok in ["", "   ", None]:
        client = NotionClient(api_token=empty_tok, transport=None)
        with pytest.raises(ExternalApiError, match="Notion api_token or transport required"):
            client.create_page("parent_id_123", "Title")


def test_youtube_gateway_documentation_and_error() -> None:
    """Item 6: Gateway handling when api_key and transport are absent."""
    client = YouTubeClient(gateway=object())  # Dummy gateway
    with pytest.raises(ExternalApiError, match="gateway"):
        client.fetch_channel_videos("https://www.youtube.com/@Channel")


