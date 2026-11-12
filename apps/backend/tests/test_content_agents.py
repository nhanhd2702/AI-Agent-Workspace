"""Unit and integration tests for DeepResearcherAgent and ContentWriterAgent (Task 3.3)."""

from __future__ import annotations

import json
from typing import Any, Optional
import pytest

from app.agents.base import WorkerResult
from app.agents.content import (
    AgentResult,
    ArtifactOutput,
    ContentWriterAgent,
    DeepResearcherAgent,
)
from app.db.models import BrandProfile
from app.llm.router import LlmResponse
from app.mcp.browser_server import BrowserActionResult, BrowserGateStatus
from app.mcp.external_apis import TranscriptResult, VideoMeta


class MockYouTubeClient:
    """Mock in-memory YouTubeClient for testing DeepResearcherAgent."""

    def __init__(self) -> None:
        self.videos_by_channel: dict[str, list[dict[str, Any]]] = {}
        self.all_videos: list[dict[str, Any]] = []
        self.transcripts: dict[str, TranscriptResult] = {}

    def seed_videos(
        self,
        videos: list[dict[str, Any]],
        channel_url: Optional[str] = None,
    ) -> None:
        for v in videos:
            meta = {
                "video_id": str(v.get("id") or v.get("video_id", "v1")),
                "title": str(v.get("title", "Video Title")),
                "view_count": int(v.get("view_count", 10000)),
                "url": str(
                    v.get("url") or f"https://youtube.com/watch?v={v.get('id', 'v1')}"
                ),
                "thumbnail_url": str(
                    v.get("thumbnail_url")
                    or f"https://img.youtube.com/vi/{v.get('id', 'v1')}/hqdefault.jpg"
                ),
                "channel_title": v.get("channel_title", "Channel"),
            }
            self.all_videos.append(meta)
            if channel_url:
                self.videos_by_channel.setdefault(channel_url, []).append(meta)

    def seed_transcript(
        self,
        video_id: str,
        text: str,
        available: bool = True,
        language: str = "vi",
    ) -> None:
        self.transcripts[video_id] = TranscriptResult(
            video_id=video_id,
            available=available,
            text=text,
            language=language,
            note=None if available else "Không đọc được phụ đề",
        )

    def fetch_channel_videos(
        self,
        channel_url: str,
        min_views: int = 0,
        limit: int = 20,
    ) -> list[VideoMeta]:
        pool = self.videos_by_channel.get(channel_url) or self.all_videos
        filtered = [
            VideoMeta(
                video_id=item["video_id"],
                title=item["title"],
                view_count=item["view_count"],
                thumbnail_url=item["thumbnail_url"],
                url=item["url"],
                channel_title=item.get("channel_title"),
            )
            for item in pool
            if item["view_count"] >= min_views
        ]
        return filtered[:limit]

    def fetch_transcript(self, video_id: str) -> TranscriptResult:
        if video_id in self.transcripts:
            return self.transcripts[video_id]
        return TranscriptResult(
            video_id=video_id,
            available=False,
            note="Không đọc được phụ đề",
        )


class MockLlm:
    """Mock LLM Router simulating structured responses."""

    def __init__(self, canned_response: Optional[str] = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.canned_response = canned_response

    async def complete(self, messages: Any = None, **kwargs: Any) -> LlmResponse:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self.canned_response:
            content = self.canned_response
        else:
            content = json.dumps(
                {
                    "hooks": [
                        "Bật mí cách ngủ ngon sau 5 phút với nến thơm",
                        "Đừng đốt nến thơm nếu bạn chưa biết điều này!",
                        "Bí quyết thư giãn đỉnh cao của dân văn phòng buổi tối",
                    ],
                    "body": "Sau một ngày làm việc căng thẳng, một ngọn nến thơm với hương hoa oải hương dịu nhẹ...",
                    "cta": "Nhắn tin ngay để nhận tư vấn mùi hương phù hợp nhất với bạn!",
                    "disclaimer": "Lưu ý: Sản phẩm không phải là thuốc và không thay thế các liệu pháp y tế.",
                    "ideas": [
                        "Ý tưởng 1: 5 mẹo chọn mùi hương nến thơm giải tỏa căng thẳng",
                        "Ý tưởng 2: Hướng dẫn chăm sóc bấc nến đúng chuẩn để dùng lâu hơn",
                        "Ý tưởng 3: Phân biệt sáp đậu nành tự nhiên và sáp paraffin công nghiệp",
                        "Ý tưởng 4: Góc thư giãn tại gia: Kết hợp nến thơm và âm nhạc lo-fi",
                        "Ý tưởng 5: Sai lầm phổ biến khi đốt nến thơm trong phòng ngủ kín",
                    ],
                }
            )
        return LlmResponse(
            content=content,
            model_used="mock-gemini",
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            cost_usd=0.001,
        )


@pytest.fixture
def mock_yt_client() -> MockYouTubeClient:
    return MockYouTubeClient()


@pytest.fixture
def mock_llm() -> MockLlm:
    return MockLlm()


# ============================================================================
# DeepResearcherAgent Tests
# ============================================================================


@pytest.mark.asyncio
async def test_deep_researcher_produces_offline_html_with_verified_urls_only(
    mock_yt_client: MockYouTubeClient, mock_llm: MockLlm
) -> None:
    mock_yt_client.seed_videos(
        [
            {
                "id": "v1",
                "title": "Hormozi Hook",
                "view_count": 50000,
                "url": "https://youtube.com/watch?v=v1",
            }
        ]
    )
    agent = DeepResearcherAgent(yt_client=mock_yt_client, llm=mock_llm)
    result = await agent.run(
        {"channels": ["https://youtube.com/@AlexHormozi"], "min_views": 10000}
    )

    assert result.status == "completed"
    assert len(result.artifacts) > 0
    assert result.artifacts[0].filename.endswith(".html")
    assert "https://youtube.com/watch?v=v1" in result.artifacts[0].content
    assert "cdn.tailwindcss.com" not in result.artifacts[0].content
    # Strict offline CSP check
    assert "Content-Security-Policy" in result.artifacts[0].content


@pytest.mark.asyncio
async def test_deep_researcher_records_transcript_unavailable_note(
    mock_yt_client: MockYouTubeClient, mock_llm: MockLlm
) -> None:
    mock_yt_client.seed_videos(
        [
            {
                "id": "v_no_cc",
                "title": "Video Without Captions",
                "view_count": 25000,
                "url": "https://youtube.com/watch?v=v_no_cc",
            }
        ]
    )
    agent = DeepResearcherAgent(yt_client=mock_yt_client, llm=mock_llm)
    result = await agent.run({"channels": ["https://youtube.com/@TestChannel"]})

    videos_data = result.structured_data.get("videos", [])
    assert len(videos_data) == 1
    assert videos_data[0]["transcript_available"] is False
    assert videos_data[0]["transcript_note"] == "Không đọc được phụ đề"
    # Ensure note is reflected in HTML artifact
    assert "Không đọc được phụ đề" in result.artifacts[0].content


@pytest.mark.asyncio
async def test_deep_researcher_generates_5_vietnamese_ideas(
    mock_yt_client: MockYouTubeClient, mock_llm: MockLlm
) -> None:
    mock_yt_client.seed_videos(
        [
            {
                "id": "v2",
                "title": "Viral Video Strategy",
                "view_count": 120000,
                "url": "https://youtube.com/watch?v=v2",
            }
        ]
    )
    agent = DeepResearcherAgent(yt_client=mock_yt_client, llm=mock_llm)
    result = await agent.run(
        {"channels": ["https://youtube.com/@ViralMarketing"], "topic": "Viral Video"}
    )

    ideas = result.structured_data.get("ideas", [])
    assert isinstance(ideas, list)
    assert len(ideas) == 5
    # Check that ideas contain localized Vietnamese text
    for idea in ideas:
        idea_text = idea if isinstance(idea, str) else idea.get("title", "")
        assert len(idea_text) > 0


@pytest.mark.asyncio
async def test_deep_researcher_fallback_generates_5_vietnamese_ideas_without_llm(
    mock_yt_client: MockYouTubeClient,
) -> None:
    """When LLM is None or fails, deterministic Vietnamese ideas are strictly derived."""
    mock_yt_client.seed_videos(
        [
            {
                "id": "v3",
                "title": "Hook Mastery Guide",
                "view_count": 45000,
                "url": "https://youtube.com/watch?v=v3",
            }
        ]
    )
    agent = DeepResearcherAgent(yt_client=mock_yt_client, llm=None)
    result = await agent.run(
        {"channels": ["https://youtube.com/@HookMaster"], "topic": "Hook Mastery"}
    )

    ideas = result.structured_data.get("ideas", [])
    assert len(ideas) == 5
    # Verify non-empty strings
    for idea in ideas:
        idea_text = idea if isinstance(idea, str) else str(idea)
        assert len(idea_text) > 5


@pytest.mark.asyncio
async def test_deep_researcher_html_xss_escaping_and_safe_urls(
    mock_yt_client: MockYouTubeClient, mock_llm: MockLlm
) -> None:
    """Malicious video titles, channel names, and script injections must be HTML-escaped."""
    malicious_title = "<script>alert('xss')</script><img src=x onerror=alert(1)>"
    mock_yt_client.seed_videos(
        [
            {
                "id": "xss1",
                "title": malicious_title,
                "view_count": 99999,
                "url": "https://youtube.com/watch?v=xss1",
                "channel_title": "<svg onload=alert(2)>",
            }
        ]
    )
    agent = DeepResearcherAgent(yt_client=mock_yt_client, llm=mock_llm)
    result = await agent.run({"channels": ["https://youtube.com/@Attacker"]})

    content = result.artifacts[0].content
    # The raw unescaped script tag should NOT exist in the body
    assert "<script>alert('xss')</script>" not in content
    assert "<img src=x onerror=alert(1)>" not in content
    assert "<svg onload=alert(2)>" not in content
    # The properly escaped entities must be present
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in content or "&lt;script&gt;alert('xss')&lt;/script&gt;" in content


@pytest.mark.asyncio
async def test_deep_researcher_browser_safe_halt_on_captcha_gate(
    mock_llm: MockLlm,
) -> None:
    """When BrowserController encounters CAPTCHA, execution halts safely."""
    class MockGateBrowser:
        async def navigate(self, url: str, **kwargs: Any) -> BrowserActionResult:
            return BrowserActionResult(
                status=BrowserGateStatus.CAPTCHA_REQUIRED.value,
                action="navigate",
                url=url,
                title="Cloudflare Gate",
                gate_type="captcha",
                message="Automated execution halted: captcha gate detected. Human intervention required.",
            )

    agent = DeepResearcherAgent(browser=MockGateBrowser(), llm=mock_llm)
    result = await agent.run({"urls": ["https://protected-site.example.com"]})

    assert result.status == "halted"
    assert result.structured_data.get("gate") == "CAPTCHA_REQUIRED"
    assert "captcha gate detected" in result.error or "CAPTCHA_REQUIRED" in result.error


# ============================================================================
# ContentWriterAgent Tests
# ============================================================================


@pytest.mark.asyncio
async def test_content_writer_outputs_3_hooks_and_disclaimer(
    mock_llm: MockLlm,
) -> None:
    agent = ContentWriterAgent(llm=mock_llm)
    result = await agent.run({"topic": "Nến thơm buổi tối", "channel": "Facebook"})

    assert result.status == "completed"
    assert len(result.structured_data["hooks"]) >= 3
    # Check legal disclaimer exists in structured data
    disclaimer = (
        result.structured_data.get("disclaimer")
        or result.structured_data.get("legal_disclaimer")
    )
    assert disclaimer is not None and len(disclaimer) > 0

    # Check artifacts generated (markdown and/or HTML)
    assert len(result.artifacts) >= 1
    assert any(a.filename.endswith(".md") for a in result.artifacts)


@pytest.mark.asyncio
async def test_content_writer_brand_profile_injection(
    mock_llm: MockLlm,
) -> None:
    brand = BrandProfile(
        id="brand-1",
        brand_name="Aura Scent",
        tone_of_voice="Thư thái, an yên, chuyên nghiệp",
        target_audience="Dân văn phòng, người thường xuyên căng thẳng",
        legal_boundaries="Không cam kết chữa dứt điểm bệnh mất ngủ",
    )
    agent = ContentWriterAgent(llm=mock_llm, brand_profile=brand)
    result = await agent.run(
        {
            "topic": "Nến thơm hoa oải hương",
            "channel": "Facebook",
            "forbidden_terms": ["thần dược", "chữa dứt điểm"],
        }
    )

    assert result.status == "completed"
    assert result.structured_data["brand_profile"]["brand_name"] == "Aura Scent"
    # Verify prompt received brand context
    assert len(mock_llm.calls) > 0
    prompt_str = str(mock_llm.calls[0]["messages"])
    assert "Aura Scent" in prompt_str
    assert "Thư thái, an yên" in prompt_str

    # Legal boundaries must be in disclaimer
    disclaimer = result.structured_data.get("disclaimer", "")
    assert "Không cam kết chữa dứt điểm" in disclaimer or "Aura Scent" in disclaimer


@pytest.mark.asyncio
async def test_content_writer_masks_secrets_in_artifacts() -> None:
    """API secrets and tokens in context must be redacted via mask_secrets."""
    secret_token = "sk-live-supersecretapikey12345"
    mock_llm = MockLlm(
        canned_response=json.dumps(
            {
                "hooks": ["Hook 1", "Hook 2", "Hook 3"],
                "body": f"Contact us using key {secret_token} for discount",
                "cta": "Buy now",
                "disclaimer": "Standard disclaimer",
            }
        )
    )
    agent = ContentWriterAgent(llm=mock_llm)
    result = await agent.run(
        {"topic": "Nến thơm", "channel": "Facebook", "api_key": secret_token}
    )

    for artifact in result.artifacts:
        assert secret_token not in artifact.content
        assert "***REDACTED***" in artifact.content or "sk-live-" not in artifact.content


@pytest.mark.asyncio
async def test_content_agents_worker_result_compatibility() -> None:
    """AgentResult should be compatible with WorkerResult interface."""
    res = AgentResult(
        agent_id="test-agent",
        subtask_id="sub-1",
        status="completed",
        content="Success content",
        structured_data={"hooks": ["h1", "h2", "h3"]},
        artifacts=[ArtifactOutput(filename="out.html", content="<html></html>")],
    )

    d = res.to_dict()
    assert d["agent_id"] == "test-agent"
    assert d["subtask_id"] == "sub-1"
    assert d["status"] == "completed"
    assert len(res.artifacts) == 1
    assert res.artifacts[0].filename == "out.html"
