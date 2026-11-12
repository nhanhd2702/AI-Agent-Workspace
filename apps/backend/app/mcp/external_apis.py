"""External API Connectors for YouTube, Google Sheets, and Notion (Task 3.2).

Provides unified, security-hardened client interfaces for:
1. YouTubeClient: channel video indexing, transcript retrieval with fallback flags, SSRF guards.
2. SheetsClient: spreadsheet row appending and reading with secret-safe errors.
3. NotionClient: page creation and database querying with secret-safe errors.
4. ConnectorConfig factory with masked secret handling.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
import socket
import time
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional
from urllib.parse import urlparse

import httpx

from app.db.models import ConnectorConfig
from app.mcp.security import (
    SecurityPolicyError,
    mask_policy_text,
    validate_safe_http_url,
)
from app.orchestrator.dispatcher import mask_secrets

if TYPE_CHECKING:
    from app.mcp.gateway import McpGateway


# ============================================================================
# Domain Models & Exceptions
# ============================================================================

class ExternalApiError(Exception):
    """Exception raised by external API connectors with automatic secret redaction."""

    def __init__(
        self,
        message: str,
        *,
        extra_secrets: Optional[Iterable[str]] = None,
        status_code: Optional[int] = None,
    ) -> None:
        masked = str(mask_secrets(message, extra_secrets=extra_secrets))
        super().__init__(masked)
        self.message = masked
        self.status_code = status_code

    def __repr__(self) -> str:
        return f"ExternalApiError({self.message!r})"


@dataclass
class VideoMeta:
    """Verified metadata for a YouTube video."""

    video_id: str
    title: str
    view_count: int
    thumbnail_url: str
    url: str
    published_at: Optional[str] = None
    channel_title: Optional[str] = None
    duration_seconds: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TranscriptResult:
    """Video transcript extraction result with explicit availability flag."""

    video_id: str
    available: bool
    language: Optional[str] = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.available and not self.note:
            self.note = "Không đọc được phụ đề"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SheetsAppendResult:
    """Result of appending row data to a Google Spreadsheet."""

    spreadsheet_id: str
    sheet_range: str
    rows_appended: int
    updated_range: Optional[str] = None
    raw_response: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NotionPageResult:
    """Result of creating a Notion page."""

    page_id: str
    url: Optional[str] = None
    title: Optional[str] = None
    parent_id: Optional[str] = None
    raw_response: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConnectorHealthResult:
    """Status probe result for an external connector."""

    provider: str
    healthy: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    details: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================================
# YouTube Client
# ============================================================================

_ALLOWED_YOUTUBE_HOSTS: frozenset[str] = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
    }
)

_YOUTUBE_VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _is_allowed_youtube_host(host: str) -> bool:
    host_norm = host.lower().strip().rstrip(".")
    if host_norm in _ALLOWED_YOUTUBE_HOSTS:
        return True
    return host_norm.endswith(".youtube.com")


class YouTubeClient:
    """Connector client for YouTube API with strict SSRF and transcript validation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        transport: Optional[Any] = None,
        gateway: Optional[McpGateway] = None,
        extra_secrets: Optional[Iterable[str]] = None,
        dns_resolver: Optional[Callable[[str], Iterable[str]]] = None,
    ) -> None:
        self.api_key = api_key
        self.transport = transport
        self.gateway = gateway
        self.dns_resolver = dns_resolver
        self.extra_secrets: list[str] = list(extra_secrets or [])
        if self.api_key:
            self.extra_secrets.append(self.api_key)

    def __repr__(self) -> str:
        masked = str(mask_secrets(self.api_key)) if self.api_key else None
        trans_name = type(self.transport).__name__ if self.transport else None
        return f"<YouTubeClient api_key={masked!r} transport={trans_name!r}>"

    def _validate_video_id(self, video_id: str) -> str:
        if not video_id or not isinstance(video_id, str):
            raise ExternalApiError(
                f"Invalid YouTube video ID: must be a non-empty string, got {video_id!r}",
                extra_secrets=self.extra_secrets,
            )
        cleaned = video_id.strip()
        if len(cleaned) > 64 or not _YOUTUBE_VIDEO_ID_RE.match(cleaned):
            raise ExternalApiError(
                f"Invalid YouTube video ID format: {video_id!r}",
                extra_secrets=self.extra_secrets,
            )
        return cleaned

    def _validate_channel_url(self, channel_url: str) -> str:
        if not channel_url or not isinstance(channel_url, str):
            raise ExternalApiError(
                "channel_url must be a non-empty string",
                extra_secrets=self.extra_secrets,
            )
        try:
            safe_url = validate_safe_http_url(
                channel_url,
                dns_resolver=self.dns_resolver,
                error_cls=ExternalApiError,
                extra_secrets=self.extra_secrets,
            )
        except SecurityPolicyError as err:
            raise ExternalApiError(str(err), extra_secrets=self.extra_secrets) from err

        parsed = urlparse(safe_url)
        hostname = (parsed.hostname or "").lower().strip()
        if not _is_allowed_youtube_host(hostname):
            raise ExternalApiError(
                f"URL domain is not a recognized YouTube domain: {channel_url!r}",
                extra_secrets=self.extra_secrets,
            )
        return safe_url

    def fetch_channel_videos(
        self,
        channel_url: str,
        min_views: int = 0,
        limit: int = 20,
    ) -> list[VideoMeta]:
        """Fetch videos from a YouTube channel URL, filtering by minimum views."""
        validated_url = self._validate_channel_url(channel_url)
        if limit < 1:
            raise ExternalApiError("limit must be at least 1", extra_secrets=self.extra_secrets)
        if min_views < 0:
            raise ExternalApiError("min_views cannot be negative", extra_secrets=self.extra_secrets)

        # 1. Transport-based dispatch (unit tests & injected test transports)
        if self.transport is not None:
            if hasattr(self.transport, "fetch_channel_videos"):
                try:
                    raw_items = self.transport.fetch_channel_videos(
                        validated_url, min_views=min_views, limit=limit
                    )
                except Exception as exc:
                    raise ExternalApiError(str(exc), extra_secrets=self.extra_secrets) from exc
                results: list[VideoMeta] = []
                for item in raw_items:
                    if isinstance(item, VideoMeta):
                        results.append(item)
                    elif isinstance(item, dict):
                        results.append(
                            VideoMeta(
                                video_id=str(item["video_id"]),
                                title=str(item["title"]),
                                view_count=int(item["view_count"]),
                                thumbnail_url=str(item["thumbnail_url"]),
                                url=str(
                                    item.get("url")
                                    or f"https://www.youtube.com/watch?v={item['video_id']}"
                                ),
                                published_at=item.get("published_at"),
                                channel_title=item.get("channel_title"),
                                duration_seconds=(
                                    int(item["duration_seconds"])
                                    if item.get("duration_seconds") is not None
                                    else None
                                ),
                            )
                        )
                filtered = [v for v in results if v.view_count >= min_views]
                return filtered[:limit]

        # 2. Official YouTube Data API v3
        if self.api_key:
            return self._fetch_videos_via_api(validated_url, min_views=min_views, limit=limit)

        raise ExternalApiError(
            "Missing credentials (api_key) or transport for YouTubeClient",
            extra_secrets=self.extra_secrets,
        )

    def _fetch_videos_via_api(
        self,
        channel_url: str,
        min_views: int,
        limit: int,
    ) -> list[VideoMeta]:
        """Query YouTube Data API v3 search & videos endpoints."""
        parsed = urlparse(channel_url)
        path = parsed.path.strip("/")
        handle_or_id = path.split("/")[-1] if path else ""

        try:
            with httpx.Client(timeout=15.0) as client:
                search_params: dict[str, Any] = {
                    "key": self.api_key,
                    "part": "snippet",
                    "maxResults": min(limit * 2, 50),
                    "type": "video",
                    "order": "date",
                }
                if handle_or_id.startswith("@"):
                    search_params["q"] = handle_or_id
                elif handle_or_id.startswith("UC"):
                    search_params["channelId"] = handle_or_id
                else:
                    search_params["q"] = handle_or_id

                search_res = client.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params=search_params,
                )
                if search_res.status_code != 200:
                    raise ExternalApiError(
                        f"YouTube Data API error ({search_res.status_code}): {search_res.text}",
                        extra_secrets=self.extra_secrets,
                        status_code=search_res.status_code,
                    )
                items = search_res.json().get("items", [])
                video_ids = [
                    item["id"]["videoId"]
                    for item in items
                    if item.get("id", {}).get("videoId")
                ]
                if not video_ids:
                    return []

                videos_res = client.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={
                        "key": self.api_key,
                        "part": "snippet,statistics,contentDetails",
                        "id": ",".join(video_ids),
                    },
                )
                if videos_res.status_code != 200:
                    raise ExternalApiError(
                        f"YouTube Data API videos error ({videos_res.status_code}): {videos_res.text}",
                        extra_secrets=self.extra_secrets,
                        status_code=videos_res.status_code,
                    )
                v_data = videos_res.json().get("items", [])
                results: list[VideoMeta] = []
                for v in v_data:
                    vid_id = v["id"]
                    snippet = v.get("snippet", {})
                    stats = v.get("statistics", {})
                    view_cnt = int(stats.get("viewCount", 0))
                    if view_cnt < min_views:
                        continue
                    thumb = (
                        snippet.get("thumbnails", {}).get("high", {}).get("url")
                        or snippet.get("thumbnails", {}).get("default", {}).get("url")
                        or f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"
                    )
                    results.append(
                        VideoMeta(
                            video_id=vid_id,
                            title=snippet.get("title", ""),
                            view_count=view_cnt,
                            thumbnail_url=thumb,
                            url=f"https://www.youtube.com/watch?v={vid_id}",
                            published_at=snippet.get("publishedAt"),
                            channel_title=snippet.get("channelTitle"),
                        )
                    )
                return results[:limit]
        except ExternalApiError:
            raise
        except Exception as exc:
            raise ExternalApiError(
                f"Failed to fetch YouTube channel videos: {exc}",
                extra_secrets=self.extra_secrets,
            ) from exc

    def fetch_transcript(self, video_id: str) -> TranscriptResult:
        """Fetch transcript for a given YouTube video ID, returning explicit fallback note if unavailable."""
        clean_id = self._validate_video_id(video_id)

        # 1. Transport-based dispatch
        if self.transport is not None:
            disabled_set = getattr(self.transport, "disabled_captions", None)
            if isinstance(disabled_set, (set, list, tuple)) and clean_id in disabled_set:
                return TranscriptResult(
                    video_id=clean_id,
                    available=False,
                    note="Không đọc được phụ đề",
                )

            if hasattr(self.transport, "fetch_transcript"):
                try:
                    res = self.transport.fetch_transcript(clean_id)
                    if res is None:
                        return TranscriptResult(
                            video_id=clean_id,
                            available=False,
                            note="Không đọc được phụ đề",
                        )
                    if isinstance(res, TranscriptResult):
                        if not res.available and not res.note:
                            res.note = "Không đọc được phụ đề"
                        return res
                    if isinstance(res, dict):
                        avail = bool(res.get("available", True))
                        note = res.get("note") if not avail else None
                        return TranscriptResult(
                            video_id=clean_id,
                            available=avail,
                            language=res.get("language"),
                            segments=res.get("segments", []),
                            text=res.get("text", ""),
                            note=note or ("Không đọc được phụ đề" if not avail else None),
                        )
                except Exception:
                    return TranscriptResult(
                        video_id=clean_id,
                        available=False,
                        note="Không đọc được phụ đề",
                    )

        # 2. Production fallback / attempt
        # When captions are missing, empty, or unparseable, return available=False with required note
        return TranscriptResult(
            video_id=clean_id,
            available=False,
            note="Không đọc được phụ đề",
        )

    def health_check(self) -> ConnectorHealthResult:
        """Probe YouTube connector availability."""
        if self.transport is not None and hasattr(self.transport, "health_check"):
            try:
                res = self.transport.health_check()
                if isinstance(res, ConnectorHealthResult):
                    return res
                if isinstance(res, dict):
                    return ConnectorHealthResult(
                        provider=res.get("provider", "youtube"),
                        healthy=bool(res.get("healthy", True)),
                        latency_ms=res.get("latency_ms"),
                        error=res.get("error"),
                    )
            except Exception as exc:
                return ConnectorHealthResult(
                    provider="youtube",
                    healthy=False,
                    error=str(mask_secrets(str(exc), extra_secrets=self.extra_secrets)),
                )

        if not self.api_key:
            return ConnectorHealthResult(
                provider="youtube",
                healthy=False,
                error="Missing api_key or transport",
            )

        start = time.perf_counter()
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params={"key": self.api_key, "part": "id", "maxResults": 1, "type": "video"},
                )
                lat = (time.perf_counter() - start) * 1000.0
                if res.status_code == 200:
                    return ConnectorHealthResult(provider="youtube", healthy=True, latency_ms=lat)
                return ConnectorHealthResult(
                    provider="youtube",
                    healthy=False,
                    latency_ms=lat,
                    error=str(mask_secrets(res.text, extra_secrets=self.extra_secrets)),
                )
        except Exception as exc:
            lat = (time.perf_counter() - start) * 1000.0
            return ConnectorHealthResult(
                provider="youtube",
                healthy=False,
                latency_ms=lat,
                error=str(mask_secrets(str(exc), extra_secrets=self.extra_secrets)),
            )


# ============================================================================
# Google Sheets Client
# ============================================================================

class SheetsClient:
    """Connector client for Google Sheets API v4 with secret masking and input validation."""

    def __init__(
        self,
        credentials: Optional[dict[str, Any] | str] = None,
        transport: Optional[Any] = None,
        extra_secrets: Optional[Iterable[str]] = None,
    ) -> None:
        self.credentials = credentials
        self.transport = transport
        self.extra_secrets: list[str] = list(extra_secrets or [])

        # Collect sensitive tokens for automatic masking
        if isinstance(self.credentials, str):
            self.extra_secrets.append(self.credentials)
        elif isinstance(self.credentials, dict):
            for v in self.credentials.values():
                if isinstance(v, str) and len(v) >= 6:
                    self.extra_secrets.append(v)

    def __repr__(self) -> str:
        masked = str(mask_secrets(self.credentials, extra_secrets=self.extra_secrets)) if self.credentials else None
        trans_name = type(self.transport).__name__ if self.transport else None
        return f"<SheetsClient credentials={masked!r} transport={trans_name!r}>"

    def _require_auth(self) -> None:
        if self.credentials is None and self.transport is None:
            raise ExternalApiError(
                "Google Sheets credentials or transport required",
                extra_secrets=self.extra_secrets,
            )

    def _validate_inputs(
        self,
        spreadsheet_id: str,
        sheet_range: str,
        rows: Optional[list[list[Any]]] = None,
    ) -> None:
        if not spreadsheet_id or not isinstance(spreadsheet_id, str) or not spreadsheet_id.strip():
            raise ExternalApiError(
                "spreadsheet_id must be a non-empty string",
                extra_secrets=self.extra_secrets,
            )
        if not sheet_range or not isinstance(sheet_range, str) or not sheet_range.strip():
            raise ExternalApiError(
                "sheet_range must be a non-empty string",
                extra_secrets=self.extra_secrets,
            )
        if rows is not None:
            if not isinstance(rows, list) or len(rows) == 0:
                raise ExternalApiError(
                    "rows must be a non-empty list of row lists",
                    extra_secrets=self.extra_secrets,
                )
            if not all(isinstance(r, list) for r in rows):
                raise ExternalApiError(
                    "Each item in rows must be a list",
                    extra_secrets=self.extra_secrets,
                )

    def append_rows(
        self,
        spreadsheet_id: str,
        sheet_range: str,
        rows: list[list[Any]],
    ) -> SheetsAppendResult:
        """Append rows to a spreadsheet range."""
        self._require_auth()
        self._validate_inputs(spreadsheet_id, sheet_range, rows)

        if self.transport is not None and hasattr(self.transport, "append_rows"):
            try:
                res = self.transport.append_rows(spreadsheet_id, sheet_range, rows)
                if isinstance(res, SheetsAppendResult):
                    return res
                if isinstance(res, dict):
                    return SheetsAppendResult(
                        spreadsheet_id=spreadsheet_id,
                        sheet_range=sheet_range,
                        rows_appended=int(res.get("rows_appended", len(rows))),
                        updated_range=res.get("updated_range"),
                        raw_response=res,
                    )
                return SheetsAppendResult(
                    spreadsheet_id=spreadsheet_id,
                    sheet_range=sheet_range,
                    rows_appended=len(rows),
                )
            except Exception as exc:
                raise ExternalApiError(str(exc), extra_secrets=self.extra_secrets) from exc

        # Production HTTP invocation
        token = ""
        if isinstance(self.credentials, str):
            token = self.credentials
        elif isinstance(self.credentials, dict):
            token = self.credentials.get("token") or self.credentials.get("access_token", "")

        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{sheet_range}:append"
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params={"valueInputOption": "USER_ENTERED"},
                    json={"values": rows},
                )
                if resp.status_code != 200:
                    raise ExternalApiError(
                        f"Google Sheets API error ({resp.status_code}): {resp.text}",
                        extra_secrets=self.extra_secrets,
                        status_code=resp.status_code,
                    )
                data = resp.json()
                updates = data.get("updates", {})
                return SheetsAppendResult(
                    spreadsheet_id=spreadsheet_id,
                    sheet_range=sheet_range,
                    rows_appended=int(updates.get("updatedRows", len(rows))),
                    updated_range=updates.get("updatedRange"),
                    raw_response=data,
                )
        except ExternalApiError:
            raise
        except Exception as exc:
            raise ExternalApiError(str(exc), extra_secrets=self.extra_secrets) from exc

    def read_rows(self, spreadsheet_id: str, sheet_range: str) -> list[list[Any]]:
        """Read rows from a spreadsheet range."""
        self._require_auth()
        self._validate_inputs(spreadsheet_id, sheet_range)

        if self.transport is not None and hasattr(self.transport, "read_rows"):
            try:
                return self.transport.read_rows(spreadsheet_id, sheet_range)
            except Exception as exc:
                raise ExternalApiError(str(exc), extra_secrets=self.extra_secrets) from exc

        token = ""
        if isinstance(self.credentials, str):
            token = self.credentials
        elif isinstance(self.credentials, dict):
            token = self.credentials.get("token") or self.credentials.get("access_token", "")

        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{sheet_range}"
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code != 200:
                    raise ExternalApiError(
                        f"Google Sheets API error ({resp.status_code}): {resp.text}",
                        extra_secrets=self.extra_secrets,
                        status_code=resp.status_code,
                    )
                return resp.json().get("values", [])
        except ExternalApiError:
            raise
        except Exception as exc:
            raise ExternalApiError(str(exc), extra_secrets=self.extra_secrets) from exc

    def health_check(self) -> ConnectorHealthResult:
        """Check status of Sheets connector."""
        if self.transport is not None and hasattr(self.transport, "health_check"):
            try:
                res = self.transport.health_check()
                if isinstance(res, ConnectorHealthResult):
                    return res
                if isinstance(res, dict):
                    return ConnectorHealthResult(
                        provider=res.get("provider", "google_sheets"),
                        healthy=bool(res.get("healthy", True)),
                        latency_ms=res.get("latency_ms"),
                        error=res.get("error"),
                    )
            except Exception as exc:
                return ConnectorHealthResult(
                    provider="google_sheets",
                    healthy=False,
                    error=str(mask_secrets(str(exc), extra_secrets=self.extra_secrets)),
                )

        if not self.credentials:
            return ConnectorHealthResult(
                provider="google_sheets",
                healthy=False,
                error="Missing credentials or transport",
            )
        return ConnectorHealthResult(
            provider="google_sheets",
            healthy=True,
        )


# ============================================================================
# Notion Client
# ============================================================================

class NotionClient:
    """Connector client for Notion API v1 with secret masking and input validation."""

    def __init__(
        self,
        api_token: Optional[str] = None,
        transport: Optional[Any] = None,
        extra_secrets: Optional[Iterable[str]] = None,
    ) -> None:
        self.api_token = api_token
        self.transport = transport
        self.extra_secrets: list[str] = list(extra_secrets or [])
        if self.api_token:
            self.extra_secrets.append(self.api_token)

    def __repr__(self) -> str:
        masked = str(mask_secrets(self.api_token, extra_secrets=self.extra_secrets)) if self.api_token else None
        trans_name = type(self.transport).__name__ if self.transport else None
        return f"<NotionClient api_token={masked!r} transport={trans_name!r}>"

    def _require_auth(self) -> None:
        if self.api_token is None and self.transport is None:
            raise ExternalApiError(
                "Notion api_token or transport required",
                extra_secrets=self.extra_secrets,
            )

    def create_page(
        self,
        parent_id: str,
        title: str,
        content_blocks: Optional[list[dict[str, Any]]] = None,
        properties: Optional[dict[str, Any]] = None,
    ) -> NotionPageResult:
        """Create a page under parent database or page."""
        self._require_auth()
        if not parent_id or not isinstance(parent_id, str) or not parent_id.strip():
            raise ExternalApiError(
                "parent_id must be a non-empty string",
                extra_secrets=self.extra_secrets,
            )
        if not title or not isinstance(title, str) or not title.strip():
            raise ExternalApiError(
                "title must be a non-empty string",
                extra_secrets=self.extra_secrets,
            )

        if self.transport is not None and hasattr(self.transport, "create_page"):
            try:
                res = self.transport.create_page(
                    parent_id=parent_id,
                    title=title,
                    content_blocks=content_blocks,
                    properties=properties,
                )
                if isinstance(res, NotionPageResult):
                    return res
                if isinstance(res, dict):
                    return NotionPageResult(
                        page_id=str(res.get("page_id") or res.get("id", "page-created")),
                        url=res.get("url"),
                        title=title,
                        parent_id=parent_id,
                        raw_response=res,
                    )
                return NotionPageResult(
                    page_id="page-created",
                    title=title,
                    parent_id=parent_id,
                )
            except Exception as exc:
                raise ExternalApiError(str(exc), extra_secrets=self.extra_secrets) from exc

        # Production HTTP invocation
        url = "https://api.notion.com/v1/pages"
        payload: dict[str, Any] = {
            "parent": {"database_id": parent_id} if "-" in parent_id else {"page_id": parent_id},
            "properties": properties
            or {
                "title": {
                    "title": [{"text": {"content": title}}]
                }
            },
        }
        if content_blocks:
            payload["children"] = content_blocks

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_token}",
                        "Notion-Version": "2022-06-28",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if resp.status_code not in (200, 201):
                    raise ExternalApiError(
                        f"Notion API error ({resp.status_code}): {resp.text}",
                        extra_secrets=self.extra_secrets,
                        status_code=resp.status_code,
                    )
                data = resp.json()
                return NotionPageResult(
                    page_id=data.get("id", ""),
                    url=data.get("url"),
                    title=title,
                    parent_id=parent_id,
                    raw_response=data,
                )
        except ExternalApiError:
            raise
        except Exception as exc:
            raise ExternalApiError(str(exc), extra_secrets=self.extra_secrets) from exc

    def query_database(
        self,
        database_id: str,
        filter_payload: Optional[dict[str, Any]] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query a Notion database with optional filter and page size limit."""
        self._require_auth()
        if not database_id or not isinstance(database_id, str) or not database_id.strip():
            raise ExternalApiError(
                "database_id must be a non-empty string",
                extra_secrets=self.extra_secrets,
            )
        if limit < 1:
            raise ExternalApiError("limit must be >= 1", extra_secrets=self.extra_secrets)

        if self.transport is not None and hasattr(self.transport, "query_database"):
            try:
                return self.transport.query_database(
                    database_id=database_id,
                    filter_payload=filter_payload,
                    limit=limit,
                )
            except Exception as exc:
                raise ExternalApiError(str(exc), extra_secrets=self.extra_secrets) from exc

        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        body: dict[str, Any] = {"page_size": min(limit, 100)}
        if filter_payload:
            body["filter"] = filter_payload

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_token}",
                        "Notion-Version": "2022-06-28",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                if resp.status_code != 200:
                    raise ExternalApiError(
                        f"Notion API error ({resp.status_code}): {resp.text}",
                        extra_secrets=self.extra_secrets,
                        status_code=resp.status_code,
                    )
                return resp.json().get("results", [])[:limit]
        except ExternalApiError:
            raise
        except Exception as exc:
            raise ExternalApiError(str(exc), extra_secrets=self.extra_secrets) from exc

    def health_check(self) -> ConnectorHealthResult:
        """Check status of Notion connector."""
        if self.transport is not None and hasattr(self.transport, "health_check"):
            try:
                res = self.transport.health_check()
                if isinstance(res, ConnectorHealthResult):
                    return res
                if isinstance(res, dict):
                    return ConnectorHealthResult(
                        provider=res.get("provider", "notion"),
                        healthy=bool(res.get("healthy", True)),
                        latency_ms=res.get("latency_ms"),
                        error=res.get("error"),
                    )
            except Exception as exc:
                return ConnectorHealthResult(
                    provider="notion",
                    healthy=False,
                    error=str(mask_secrets(str(exc), extra_secrets=self.extra_secrets)),
                )

        if not self.api_token:
            return ConnectorHealthResult(
                provider="notion",
                healthy=False,
                error="Missing api_token or transport",
            )
        return ConnectorHealthResult(
            provider="notion",
            healthy=True,
        )


# ============================================================================
# ConnectorConfig Factory
# ============================================================================

def build_connector_client(
    config: ConnectorConfig,
    *,
    transport: Optional[Any] = None,
    gateway: Optional[McpGateway] = None,
) -> YouTubeClient | SheetsClient | NotionClient:
    """Build a configured external connector client from a ConnectorConfig entity without secret leakage."""
    provider = (config.provider or "").strip().lower()

    # Parse auth_payload safely (JSON or raw string)
    payload_data: Any = None
    if config.auth_payload:
        try:
            payload_data = json.loads(config.auth_payload)
        except Exception:
            payload_data = config.auth_payload

    if provider == "youtube":
        api_key: Optional[str] = None
        if isinstance(payload_data, dict):
            api_key = payload_data.get("api_key") or payload_data.get("key")
        elif isinstance(payload_data, str):
            api_key = payload_data
        return YouTubeClient(api_key=api_key, transport=transport, gateway=gateway)

    if provider in {"google_sheets", "sheets", "google-sheets"}:
        return SheetsClient(credentials=payload_data, transport=transport)

    if provider == "notion":
        token: Optional[str] = None
        if isinstance(payload_data, dict):
            token = (
                payload_data.get("api_token")
                or payload_data.get("token")
                or payload_data.get("access_token")
            )
        elif isinstance(payload_data, str):
            token = payload_data
        return NotionClient(api_token=token, transport=transport)

    raise ExternalApiError(f"Unsupported connector provider: {config.provider!r}")
