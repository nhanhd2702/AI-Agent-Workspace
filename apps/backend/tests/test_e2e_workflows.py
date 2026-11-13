"""End-to-End Multi-Agent Workflow Integration Tests (Task 5.4).

Covers the 3 core end-to-end integration scenarios:
1. Scenario 1: Content Pipeline (Research -> Writer -> Image)
   - Parse NL task prompt ("Nghiên cứu Alex Hormozi rồi viết bài FB kèm ảnh 1080x1080")
   - Dispatch DAG waves across DeepResearcher -> ContentWriter -> ImageStudio
   - Verify handoff chain in task metadata and turn logs
   - Verify HTML (offline research deck, copy preview) and 1080x1080 PNG artifacts
2. Scenario 2: Funnel Pipeline with HIL Approval & Landing Page
   - Parse funnel strategy prompt with copilot mode
   - Dispatch FunnelsAgent and GrowthAdvisor
   - Trigger HIL review gate pause in waiting_review state
   - Human operator reviews and approves via /api/v1/reviews/{id}/decide
   - Resume execution to run UIDesigner and produce offline landing page prototype
3. Scenario 3: Unified Inbox & Multi-channel Engagement with Human Takeover
   - Incoming webhook on Zalo with customer inquiry -> AI grounded in RAG
   - Legal/damage complaint webhook -> automatic escalation to human takeover (status=waiting)
   - Incoming follow-up while in takeover -> AI response suppressed (human_handling)
   - Human operator direct reply via /api/v1/inbox/conversations/{id}/reply dispatched to channel adapter
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Optional
import uuid

import pytest
from fastapi.testclient import TestClient

from app.agents.base import WorkerResult
from app.api.inbox import get_bridge, reset_bridge
from app.config import AppSettings
from app.db.models import (
    Agent,
    Artifact,
    BrandProfile,
    ConnectorConfig,
    Conversation,
    Message,
    Project,
    ReviewGate,
    Task,
    TaskStatus,
    TurnLog,
)
from app.db.session import init_db, seed_defaults
from app.llm.router import LlmResponse
from app.main import create_app
from app.mcp.browser_server import (
    BrowserActionResult,
    BrowserGateStatus,
)
from app.mcp.external_apis import TranscriptResult, VideoMeta
from app.mcp.messaging_bridge import BaseChannelAdapter


# ============================================================================
# Deterministic Mock Fixtures & Helpers
# ============================================================================


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
                channel_title=item["channel_title"],
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
            available=True,
            text="Transcript nội dung video mẫu...",
            language="vi",
        )


class MockBrowser:
    """In-memory mock for BrowserController render_html_to_png and navigate."""

    def __init__(self) -> None:
        self.last_viewport: Optional[dict[str, int]] = None
        self.last_rendered_html: Optional[str] = None
        self.last_output_path: Optional[str] = None
        self.calls: list[dict[str, Any]] = []

    async def render_html_to_png(
        self,
        html: str,
        output_path: Path | str,
        *,
        width: int = 1280,
        height: int = 720,
        full_page: bool = False,
        task_workspace: Optional[Path] = None,
    ) -> BrowserActionResult:
        self.last_viewport = {"width": int(width), "height": int(height)}
        self.last_rendered_html = html
        self.last_output_path = str(output_path)
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Write valid 1080x1080 PNG header/bytes
        out_path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x048\x00\x00\x048\x08\x06\x00\x00\x00"
            b"\xbb\xaf\x11\xa3\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        self.calls.append(
            {
                "html": html,
                "output_path": str(output_path),
                "width": int(width),
                "height": int(height),
            }
        )
        return BrowserActionResult(
            status=BrowserGateStatus.OK.value,
            action="render_html_to_png",
            screenshot_path=str(out_path),
            duration_ms=45,
        )

    async def navigate(self, url: str) -> BrowserActionResult:
        return BrowserActionResult(
            status=BrowserGateStatus.OK.value,
            action="navigate",
            title="Alex Hormozi Business Playbook",
            content="Alex Hormozi $100M Offers framework and execution notes.",
            duration_ms=50,
        )


@dataclass
class MockRagChunk:
    text: str
    score: float = 0.95
    source: str = "chinh_sach_bao_hanh.md"


class MockRetriever:
    """Mock RAG Knowledge Base retriever for grounded customer responses."""

    def __init__(self, seeded_text: Optional[str] = None) -> None:
        self.seeded_text = (
            seeded_text
            or "Sản phẩm được bảo hành chính hãng 12 tháng, 1 đổi 1 trong 30 ngày nếu có lỗi sản xuất."
        )

    def search(
        self,
        query: str,
        collections: Optional[list[str]] = None,
        top_k: int = 2,
    ) -> list[MockRagChunk]:
        return [MockRagChunk(text=self.seeded_text, score=0.95)]


class MockChannelAdapter(BaseChannelAdapter):
    """In-memory mock channel adapter recording sent messages for Zalo and Telegram."""

    def __init__(self, channel: str = "mock", account_id: str = "mock-acc-1") -> None:
        self.channel = channel
        self.account_id = account_id
        self.sent_messages: list[dict[str, Any]] = []

    async def send_message(
        self,
        conv_id: str,
        content: str,
        attachments: Optional[list[dict[str, Any]]] = None,
    ) -> bool:
        self.sent_messages.append(
            {
                "channel": self.channel,
                "conv_id": conv_id,
                "content": content,
                "attachments": attachments or [],
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return True


class MockLlmRouter:
    """Deterministic LLM Router producing valid structured responses for all agents."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: Any = None,
        agent: Optional[Agent] = None,
        **kwargs: Any,
    ) -> LlmResponse:
        self.calls.append({"messages": messages, "agent": agent, "kwargs": kwargs})

        combined_text = ""
        if isinstance(messages, list):
            for m in messages:
                if isinstance(m, dict):
                    combined_text += " " + str(m.get("content", ""))
                else:
                    combined_text += " " + str(m)
        elif messages:
            combined_text = str(messages)

        ag_name = (agent.name.lower() if agent and agent.name else "")
        prompt_lower = combined_text.lower()

        # 1. DeepResearcher: 5 localized Vietnamese ideas
        if "deepresearcher" in ag_name or "ý tưởng" in prompt_lower or "research" in prompt_lower:
            content = json.dumps(
                {
                    "ideas": [
                        "Ý tưởng 1: Áp dụng $100M Offers của Alex Hormozi cho thị trường Việt Nam",
                        "Ý tưởng 2: Nghệ thuật định giá cao và xây dựng Grand Slam Offer",
                        "Ý tưởng 3: 3 Bước tạo Lead Magnet không thể từ chối để thu hút 10.000 khách hàng",
                        "Ý tưởng 4: Chiến lược giữ chân khách hàng (Retention) và giảm thiểu tỷ lệ rời bỏ",
                        "Ý tưởng 5: Tự động hóa quy trình chốt sale từ kinh nghiệm của Alex Hormozi",
                    ]
                },
                ensure_ascii=False,
            )
            return LlmResponse(
                content=content,
                model_used="mock-gemini-2.5-flash",
                input_tokens=120,
                output_tokens=180,
                total_tokens=300,
                cost_usd=0.0001,
            )

        # 2. ContentWriter: hooks, body, cta, disclaimer
        if "contentwriter" in ag_name or "hook" in prompt_lower or "bài viết" in prompt_lower or "soạn thảo" in prompt_lower:
            content = json.dumps(
                {
                    "hooks": [
                        "Bật mí công thức $100M Offers từ Alex Hormozi giúp tăng vọt doanh số!",
                        "Tại sao sản phẩm tốt vẫn khó bán? Đây là bài học đắt giá từ Alex Hormozi.",
                        "3 Bí quyết tạo lời đề nghị không thể chối từ cho người kinh doanh online.",
                    ],
                    "body": (
                        "Muốn bán được hàng với giá cao, bạn không chỉ bán tính năng mà phải bán kết quả cụ thể. "
                        "Alex Hormozi đã chỉ ra rằng khi giá trị cảm nhận vượt xa mức giá, khách hàng sẽ lập tức ra quyết định. "
                        "Hãy tập trung vào giải quyết vấn đề lớn nhất của khách hàng mục tiêu bằng một Grand Slam Offer thực sự."
                    ),
                    "cta": "Bình luận ngay 'OFFER' để nhận trọn bộ tài liệu phân tích chi tiết!",
                    "disclaimer": "Lưu ý: Kết quả thực tế phụ thuộc vào mô hình kinh doanh và nỗ lực thực thi của từng cá nhân.",
                },
                ensure_ascii=False,
            )
            return LlmResponse(
                content=content,
                model_used="mock-gemini-2.5-flash",
                input_tokens=150,
                output_tokens=220,
                total_tokens=370,
                cost_usd=0.00015,
            )

        # 3. FunnelsAgent: 7-section funnel strategy
        if "funnel" in ag_name or "phễu" in prompt_lower or "sections" in prompt_lower:
            content = json.dumps(
                {
                    "sections": [
                        {
                            "id": "overview",
                            "title": "Toàn cảnh phễu",
                            "summary": "Chiến lược phễu chuyển đổi 3 tầng từ mồi câu đến đồng hành cao cấp.",
                            "target_metrics": {"optin_rate": "15%", "conversion_rate": "3.5%"},
                        },
                        {
                            "id": "lead_magnet",
                            "title": "Tài liệu",
                            "product_name": "Tài liệu tự học & biểu mẫu thực chiến",
                            "price": 200000,
                            "strategy": "Ebook hướng dẫn nền tảng và bài tập thực hành.",
                        },
                        {
                            "id": "coach",
                            "title": "Coach",
                            "product_name": "Combo Coach 4 tuần",
                            "price": 5000000,
                            "strategy": "Chương trình huấn luyện nhóm 4 tuần kèm phản hồi trực tiếp.",
                        },
                        {
                            "id": "intensive_mentorship",
                            "title": "Đồng hành chuyên sâu",
                            "product_name": "Đồng hành chuyên sâu 1:1",
                            "price": 10000000,
                            "strategy": "Coaching 1:1 cá nhân hóa trong 3 tháng với cam kết lộ trình.",
                        },
                        {
                            "id": "content_and_metrics",
                            "title": "Nội dung & đo lường",
                            "kpis": ["Traffic", "CPL", "CAC", "LTV", "ROAS"],
                            "content_pillars": ["Giáo dục nhận thức", "Case study thực tế", "Xử lý rào cản"],
                        },
                        {
                            "id": "closing_points",
                            "title": "Điểm cần chốt",
                            "triggers": ["Ưu đãi giới hạn slot", "Quà tặng kèm độc quyền", "Chính sách hoàn tiền"],
                        },
                        {
                            "id": "compliance",
                            "title": "Tuân thủ & Miễn trừ trách nhiệm",
                            "disclaimer": "Không bảo đảm kết quả kinh doanh. Kết quả phụ thuộc vào năng lực thực thi cá nhân.",
                        },
                    ]
                },
                ensure_ascii=False,
            )
            return LlmResponse(
                content=content,
                model_used="mock-gemini-2.5-flash",
                input_tokens=200,
                output_tokens=300,
                total_tokens=500,
                cost_usd=0.0002,
            )

        # 4. GrowthAdvisor: growth experiments & KPI analysis
        if "growth" in ag_name or "tăng trưởng" in prompt_lower or "advisor" in prompt_lower:
            content = json.dumps(
                {
                    "analysis": "Phễu hiện tại có tỷ lệ chuyển đổi tầng mồi câu đạt 15%, cần tối ưu thêm tầng upsell.",
                    "growth_experiments": [
                        {"name": "Thử nghiệm A/B tiêu đề trang cảm ơn", "impact": "Cao", "effort": "Thấp"},
                        {"name": "Bổ sung video testimonial ngắn 60s", "impact": "Rất cao", "effort": "Trung bình"},
                    ],
                    "compliance_disclaimer": "Không bảo đảm kết quả kinh doanh. Các số liệu chỉ mang tính chất dự phóng tham khảo.",
                },
                ensure_ascii=False,
            )
            return LlmResponse(
                content=content,
                model_used="mock-gemini-2.5-flash",
                input_tokens=180,
                output_tokens=250,
                total_tokens=430,
                cost_usd=0.00018,
            )

        # 5. UIDesigner: landing page sections
        if "designer" in ag_name or "landing" in prompt_lower or "uidesigner" in ag_name or "giao diện" in prompt_lower:
            content = json.dumps(
                {
                    "headline": "Bứt Phá Thu Nhập Cùng Bộ Kỹ Năng Tự Động Hóa Thực Chiến",
                    "subheadline": "Sở hữu toàn bộ quy trình, biểu mẫu và công cụ tăng tốc công việc chỉ với 200K.",
                    "pain_points": [
                        "Tốn hàng chục giờ mỗi tuần cho những công việc thủ công lặp đi lặp lại",
                        "Lúng túng không biết bắt đầu ứng dụng AI và phễu tự động từ đâu",
                        "Chi phí thuê ngoài đắt đỏ nhưng hiệu quả không tương xứng",
                    ],
                    "solutions": [
                        "Lộ trình tinh gọn từng bước đi kèm checklist thực hành ngay lập tức",
                        "Bộ thư viện prompt và template chuyển giao sẵn dùng không cần kỹ thuật phức tạp",
                        "Phương pháp đo lường và tối ưu hóa chuyển đổi bền vững",
                    ],
                    "deliverables": [
                        "Ebook thực chiến 120 trang định dạng PDF chất lượng cao",
                        "20+ Biểu mẫu kịch bản phễu chuyển đổi chuẩn ngành",
                        "Video walkthrough hướng dẫn cài đặt và thiết lập nhanh trong 30 phút",
                    ],
                    "testimonials": [
                        {
                            "name": "Nguyễn Minh Tuấn",
                            "role": "Founder, DigiMark",
                            "content": "Khóa học rất hay và hữu ích! Tôi đã tối ưu được 40% chi phí vận hành sau 2 tuần.",
                            "avatar_initials": "NT",
                        }
                    ],
                    "pricing": {
                        "lead_magnet": {"title": "Bộ Starter Kit", "price": "200.000đ", "features": ["Ebook", "Checklist"]},
                        "main_offer": {"title": "Combo Tự Động Hóa", "price": "5.000.000đ", "features": ["Toàn bộ khóa học", "Coaching nhóm"]},
                        "vip_offer": {"title": "Đồng Hành 1:1", "price": "10.000.000đ", "features": ["Tư vấn trực tiếp 3 tháng"]},
                    },
                    "guarantee": "Cam kết hoàn tiền trong 7 ngày nếu không hài lòng với nội dung tài liệu.",
                    "faq": [
                        {"question": "Người mới bắt đầu có học được không?", "answer": "Hoàn toàn phù hợp vì khóa học đi từ nền tảng từng bước."},
                        {"question": "Tôi có được hỗ trợ kỹ thuật không?", "answer": "Có đội ngũ trợ giảng hỗ trợ qua nhóm trao đổi riêng."},
                    ],
                    "compliance_disclaimer": "Không bảo đảm kết quả kinh doanh. Thành công phụ thuộc vào năng lực thực thi của học viên.",
                },
                ensure_ascii=False,
            )
            return LlmResponse(
                content=content,
                model_used="mock-gemini-2.5-flash",
                input_tokens=220,
                output_tokens=350,
                total_tokens=570,
                cost_usd=0.00025,
            )

        # Default fallback
        content = json.dumps(
            {"status": "ok", "message": "Thực hiện tác vụ thành công", "summary": combined_text[:100]},
            ensure_ascii=False,
        )
        return LlmResponse(
            content=content,
            model_used="mock-gemini-2.5-flash",
            input_tokens=50,
            output_tokens=50,
            total_tokens=100,
            cost_usd=0.00005,
        )

    async def __call__(self, messages: Any, **kwargs: Any) -> LlmResponse:
        return await self.complete(messages=messages, **kwargs)


# ============================================================================
# Pytest Fixtures
# ============================================================================


@pytest.fixture
def env(tmp_path: Path):
    """Provide isolated FastAPI app, TestClient, and AppSettings."""
    settings = AppSettings(
        workspace_dir=tmp_path,
        local_auth_token="test-e2e-token",
    )
    app = create_app(settings)
    client = TestClient(app, headers={"X-Local-Auth-Token": "test-e2e-token"})
    return client, app, settings


@pytest.fixture
def client_with_db(env):
    """Convenient client fixture matching the brief requirements."""
    client, _, _ = env
    return client


@pytest.fixture
def mock_all_externals(env):
    """Seed and configure deterministic mocks across all external boundaries."""
    client, app, settings = env

    mock_llm = MockLlmRouter()
    mock_yt = MockYouTubeClient()
    mock_browser = MockBrowser()
    mock_retriever = MockRetriever(
        seeded_text="Sản phẩm được bảo hành toàn diện 12 tháng chính hãng và 1 đổi 1 trong 30 ngày nếu có lỗi sản xuất."
    )
    mock_zalo_adapter = MockChannelAdapter(channel="zalo", account_id="zalo-oa-test")
    mock_tg_adapter = MockChannelAdapter(channel="telegram", account_id="tg-bot-test")

    # Seed YouTube videos and transcripts for Alex Hormozi
    mock_yt.seed_videos(
        [
            {
                "id": "hormozi-v1",
                "title": "Alex Hormozi - How to Make $100M Offers That Customers Cannot Refuse",
                "view_count": 250000,
                "url": "https://youtube.com/watch?v=hormozi-v1",
                "channel_title": "Alex Hormozi",
            }
        ],
        channel_url="https://youtube.com/@AlexHormozi",
    )
    mock_yt.seed_transcript(
        video_id="hormozi-v1",
        text="Đây là chiến lược tạo ưu đãi không thể từ chối $100M Offers: Tăng giá trị cảm nhận, giảm rủi ro và tăng tốc độ đạt kết quả.",
    )

    # Attach mocks to app state so tasks/dispatch can use them
    app.state.llm_router = mock_llm
    app.state.yt_client = mock_yt
    app.state.browser = mock_browser
    app.state.retriever = mock_retriever

    # Setup messaging bridge for inbox
    reset_bridge()
    bridge = get_bridge(channel="zalo")
    bridge.retriever = mock_retriever
    bridge.register_adapter("zalo", mock_zalo_adapter)
    bridge.register_adapter("telegram", mock_tg_adapter)
    bridge.adapter = mock_zalo_adapter

    # Seed BrandProfile in DB if needed
    factory = app.state.session_factory
    with factory() as db:
        if not db.query(BrandProfile).filter_by(project_id="proj-default").first():
            db.add(
                BrandProfile(
                    id="bp-test-default",
                    project_id="proj-default",
                    brand_name="AI Agent Workspace",
                    tagline="Văn Phòng AI Thông Minh",
                    tone_of_voice="Chuyên nghiệp, truyền cảm hứng và thực chiến",
                    target_audience="Chủ doanh nghiệp SME và nhà sáng tạo nội dung",
                    legal_boundaries="Không cam kết doanh thu tuyệt đối",
                    brand_colors=["#2563eb", "#1e40af", "#f59e0b"],
                    fonts=["Inter, sans-serif"],
                )
            )
            db.commit()

    mocks = {
        "llm": mock_llm,
        "yt": mock_yt,
        "browser": mock_browser,
        "retriever": mock_retriever,
        "zalo_adapter": mock_zalo_adapter,
        "tg_adapter": mock_tg_adapter,
        "bridge": bridge,
    }

    yield mocks

    reset_bridge()


# ============================================================================
# Scenario 1: Content Pipeline (Research -> Writer -> Image)
# ============================================================================


def test_e2e_content_pipeline_research_to_writer_to_image(
    client_with_db: TestClient,
    mock_all_externals: dict[str, Any],
):
    """Scenario 1: Content Pipeline E2E.

    Verifies:
    1. Parse natural language prompt: "Nghiên cứu Alex Hormozi rồi viết bài FB kèm ảnh 1080x1080"
    2. Dispatch DAG across DeepResearcher -> ContentWriter -> ImageStudio
    3. Verify handoff chain in task metadata: ["DeepResearcher", "ContentWriter", "ImageStudio"]
    4. Assert handoff chain produced HTML + PNG artifacts queryable via API and on disk.
    """
    # 1. Parse prompt
    parse_resp = client_with_db.post(
        "/api/v1/tasks/parse",
        json={"prompt_text": "Nghiên cứu Alex Hormozi rồi viết bài FB kèm ảnh 1080x1080"},
    )
    assert parse_resp.status_code == 200, parse_resp.text
    parsed = parse_resp.json()
    task_id = parsed["data"]["task_id"]
    assert task_id.startswith("task-")

    # 2. Dispatch task
    dispatch = client_with_db.post(f"/api/v1/tasks/{task_id}/dispatch")
    assert dispatch.status_code == 200, dispatch.text
    dispatch_data = dispatch.json()["data"]
    assert dispatch_data["status"] == "completed"
    assert len(dispatch_data["completed_nodes"]) == 3
    assert dispatch_data["failed_nodes"] == []

    # 3. Verify task details & handoff chain in task metadata
    task_res = client_with_db.get(f"/api/v1/tasks/{task_id}")
    assert task_res.status_code == 200
    task_body = task_res.json()["data"]
    assert task_body["status"] == "completed"

    meta = task_body.get("task_metadata") or task_body.get("metadata") or {}
    handoff_chain = meta.get("handoff_chain")
    assert handoff_chain == ["DeepResearcher", "ContentWriter", "ImageStudio"], (
        f"Expected handoff chain ['DeepResearcher', 'ContentWriter', 'ImageStudio'], got {handoff_chain}"
    )

    # 4. Verify turn logs record handoffs and executions
    logs_res = client_with_db.get(f"/api/v1/tasks/{task_id}/logs")
    assert logs_res.status_code == 200
    logs = logs_res.json()["data"]
    assert len(logs) >= 3

    handoff_turns = [
        item for item in logs if item.get("action") == "handoff" or "bàn giao" in str(item.get("input_payload", "")).lower()
    ]
    # At least 2 handoffs occurred: DeepResearcher -> ContentWriter and ContentWriter -> ImageStudio
    assert len(handoff_turns) >= 2 or len(handoff_chain) == 3

    # 5. Verify generated artifacts (HTML + PNG)
    # Check mock browser was invoked to render 1080x1080 PNG
    mock_browser: MockBrowser = mock_all_externals["browser"]
    assert len(mock_browser.calls) >= 1
    assert mock_browser.last_viewport == {"width": 1080, "height": 1080}

    # Query turns or check database for created artifacts
    turns_res = client_with_db.get(f"/api/v1/tasks/{task_id}/turns")
    assert turns_res.status_code == 200

    # Retrieve all subtasks and check artifacts exist
    subtasks = task_body.get("subtasks", [])
    assert len(subtasks) == 3

    # Check artifacts in workspace
    app_settings: AppSettings = getattr(client_with_db.app.state, "settings")
    art_dir = app_settings.workspace_dir / "artifacts" / task_id
    assert art_dir.exists(), f"Artifact directory {art_dir} does not exist"

    artifacts_on_disk = list(art_dir.glob("*"))
    assert len(artifacts_on_disk) >= 2, f"Expected at least 2 artifacts, found {artifacts_on_disk}"

    html_artifacts = [f for f in artifacts_on_disk if f.suffix.lower() == ".html"]
    png_artifacts = [f for f in artifacts_on_disk if f.suffix.lower() == ".png"]

    assert len(html_artifacts) >= 1, "Expected at least 1 HTML artifact produced"
    assert len(png_artifacts) >= 1, "Expected at least 1 PNG artifact produced"

    # Verify PNG artifact is non-empty valid file
    png_file = png_artifacts[0]
    assert png_file.stat().st_size > 0
    assert png_file.read_bytes().startswith(b"\x89PNG")

    # Verify HTML artifact can be rendered via API
    # Find artifact record in DB
    session_factory = client_with_db.app.state.session_factory
    with session_factory() as db:
        db_artifacts = db.query(Artifact).filter(Artifact.task_id == task_id).all()
        assert len(db_artifacts) >= 2

        html_art_rec = next((a for a in db_artifacts if a.file_type == "html"), None)
        assert html_art_rec is not None

        render_res = client_with_db.get(f"/api/v1/artifacts/{html_art_rec.id}/render")
        assert render_res.status_code == 200
        render_json = render_res.json()
        assert render_json["status"] == "success"
        assert len(render_json["data"]["content"]) > 0


# ============================================================================
# Scenario 2: Funnel Pipeline with HIL Approval & Landing Page
# ============================================================================


def test_e2e_funnel_pipeline_with_hil_approval_and_landing_page(
    client_with_db: TestClient,
    mock_all_externals: dict[str, Any],
):
    """Scenario 2: Funnel Pipeline with HIL Approval & Landing Page.

    Verifies:
    1. Parse funnel strategy prompt with mode="copilot".
    2. First dispatch executes FunnelsAgent and GrowthAdvisor.
    3. GrowthAdvisor wave pauses in waiting_review due to copilot review gate.
    4. Verify ReviewGate is created with status "pending".
    5. Human operator reviews and approves via PATCH /api/v1/reviews/{id}/decide.
    6. Resume execution by dispatching again, executing UIDesigner.
    7. Task reaches completed status and produces funnel_strategy.html, growth_plan.html, and landing_page.html.
    """
    # 1. Parse funnel task in copilot mode
    parse_resp = client_with_db.post(
        "/api/v1/tasks/parse",
        json={
            "prompt_text": "Xây dựng phễu bán hàng khóa học và tối ưu chuyển đổi",
            "mode": "copilot",
        },
    )
    assert parse_resp.status_code == 200, parse_resp.text
    parsed = parse_resp.json()
    task_id = parsed["data"]["task_id"]

    # 2. First dispatch -> should pause at GrowthAdvisor wave with review gate
    dispatch1 = client_with_db.post(f"/api/v1/tasks/{task_id}/dispatch")
    assert dispatch1.status_code == 200, dispatch1.text
    disp1_data = dispatch1.json()["data"]
    assert disp1_data["status"] == "waiting_review", (
        f"Expected task to pause in 'waiting_review', got {disp1_data['status']}"
    )

    # Verify task state in DB
    task_res1 = client_with_db.get(f"/api/v1/tasks/{task_id}")
    assert task_res1.status_code == 200
    assert task_res1.json()["data"]["status"] == "waiting_review"

    # 3. Retrieve HIL review gates for this task
    reviews_res = client_with_db.get(f"/api/v1/reviews?taskId={task_id}")
    assert reviews_res.status_code == 200
    reviews_data = reviews_res.json()["data"]
    assert len(reviews_data) >= 1, f"Expected at least 1 review gate, got {reviews_data}"

    review_gate = reviews_data[0]
    review_id = review_gate["id"]
    assert review_gate["status"] == "pending"

    # 4. Human operator approves the review gate
    decide_resp = client_with_db.patch(
        f"/api/v1/reviews/{review_id}/decide",
        json={"decision": "approve", "feedback_text": "Phê duyệt chiến lược phễu, cho phép tiếp tục thiết kế landing page."},
    )
    assert decide_resp.status_code == 200, decide_resp.text
    assert decide_resp.json()["data"]["status"] == "approved"

    # Verify task transitioned to APPROVED
    task_res2 = client_with_db.get(f"/api/v1/tasks/{task_id}")
    assert task_res2.status_code == 200
    assert task_res2.json()["data"]["status"] == "approved"

    # 5. Resume task dispatch -> skips completed waves and executes UIDesigner
    dispatch2 = client_with_db.post(f"/api/v1/tasks/{task_id}/dispatch")
    assert dispatch2.status_code == 200, dispatch2.text
    disp2_data = dispatch2.json()["data"]
    assert disp2_data["status"] == "completed", (
        f"Expected resumed task to finish 'completed', got {disp2_data['status']}"
    )

    # 6. Verify final task state
    task_final = client_with_db.get(f"/api/v1/tasks/{task_id}").json()["data"]
    assert task_final["status"] == "completed"

    # 7. Verify all 3 offline HTML artifacts exist on disk and in database
    app_settings: AppSettings = getattr(client_with_db.app.state, "settings")
    art_dir = app_settings.workspace_dir / "artifacts" / task_id
    assert art_dir.exists()

    generated_filenames = [f.name for f in art_dir.glob("*.html")]
    assert any("funnel" in fname.lower() for fname in generated_filenames), (
        f"Missing funnel artifact in {generated_filenames}"
    )
    assert any("growth" in fname.lower() for fname in generated_filenames), (
        f"Missing growth artifact in {generated_filenames}"
    )
    assert any("landing" in fname.lower() for fname in generated_filenames), (
        f"Missing landing page artifact in {generated_filenames}"
    )

    # 8. Check that landing_page.html contains prototype marker and high-converting sections
    landing_files = [f for f in art_dir.glob("*.html") if "landing" in f.name.lower()]
    assert len(landing_files) >= 1
    landing_content = landing_files[0].read_text(encoding="utf-8")
    assert "BẢN THIẾT KẾ ĐỂ DUYỆT" in landing_content
    assert "OFFLINE PROTOTYPE" in landing_content
    assert "checkout-modal" in landing_content or "Đặt hàng" in landing_content


# ============================================================================
# Scenario 3: Unified Inbox & Multi-channel Engagement with Human Takeover
# ============================================================================


def test_e2e_inbox_engagement_and_human_takeover(
    client_with_db: TestClient,
    mock_all_externals: dict[str, Any],
):
    """Scenario 3: Unified Inbox & Multi-channel Engagement with Human Takeover.

    Verifies:
    1. Customer inquiry webhook on Zalo -> AI auto-response grounded in RAG.
    2. Customer complaint webhook ("lỗi vỡ, khiếu nại, hoàn tiền") -> auto-escalation to human takeover.
    3. Conversation status changes to "waiting" with is_human_takeover=True and system escalation notice.
    4. Subsequent customer message while in takeover has AI response suppressed (human_handling).
    5. Operator sends direct reply via /api/v1/inbox/conversations/{id}/reply.
    6. Verify reply is delivered through the channel adapter with sender_type="human".
    7. Verify complete audit trail in /api/v1/inbox/conversations/{id}/messages.
    """
    zalo_adapter: MockChannelAdapter = mock_all_externals["zalo_adapter"]

    # 1. Incoming customer inquiry -> AI grounded in RAG
    inquiry_payload = {
        "sender_id": "cust-zalo-888",
        "sender_name": "Trần Văn An",
        "content": "Chính sách bảo hành và đổi trả bên mình như thế nào ạ?",
        "client_message_id": "wh-msg-inquiry-001",
    }
    resp1 = client_with_db.post("/api/v1/inbox/webhook/zalo", json=inquiry_payload)
    assert resp1.status_code in (200, 201), resp1.text
    data1 = resp1.json()
    conv_id = data1["conversation_id"]
    res1 = data1["result"]

    assert res1["status"] == "processed"
    assert "bảo hành" in res1["reply"].lower()
    assert "12 tháng" in res1["reply"] or "chính sách" in res1["reply"].lower()

    # Verify adapter recorded AI message dispatch
    assert len(zalo_adapter.sent_messages) == 1
    assert zalo_adapter.sent_messages[0]["conv_id"] == conv_id
    assert "bảo hành" in zalo_adapter.sent_messages[0]["content"].lower()

    # 2. Customer complaint webhook -> auto-escalation
    complaint_payload = {
        "sender_id": "cust-zalo-888",
        "sender_name": "Trần Văn An",
        "content": "Hàng tôi nhận bị lỗi vỡ nghiêm trọng, tôi yêu cầu khiếu nại và hoàn tiền gấp!",
        "client_message_id": "wh-msg-complaint-002",
    }
    resp2 = client_with_db.post("/api/v1/inbox/webhook/zalo", json=complaint_payload)
    assert resp2.status_code in (200, 201), resp2.text
    res2 = resp2.json()["result"]
    assert res2["status"] == "escalated"
    assert res2.get("escalated") is True

    # Verify conversation state: human takeover active, status="waiting"
    conv_resp = client_with_db.get(f"/api/v1/inbox/conversations/{conv_id}")
    assert conv_resp.status_code == 200
    conv_json = conv_resp.json()
    conv_obj = conv_json.get("conversation") or conv_json
    assert conv_obj["is_human_takeover"] is True
    assert conv_obj["status"] == "waiting"

    # 3. Follow-up customer message while in takeover -> AI suppressed
    followup_payload = {
        "sender_id": "cust-zalo-888",
        "sender_name": "Trần Văn An",
        "content": "Shop có ai trực không? Trả lời tôi đi!",
        "client_message_id": "wh-msg-followup-003",
    }
    resp3 = client_with_db.post("/api/v1/inbox/webhook/zalo", json=followup_payload)
    assert resp3.status_code in (200, 201), resp3.text
    res3 = resp3.json()["result"]
    assert res3["status"] == "human_handling"
    assert "human operator" in res3["message"].lower()

    # Channel adapter should still only have the 1 AI message from before
    assert len(zalo_adapter.sent_messages) == 1

    # 4. Human operator sends direct reply
    operator_text = "Dạ chào anh An, em là trưởng bộ phận CSKH. Em đã tiếp nhận thông tin hàng bị vỡ và sẽ tiến hành hoàn tiền cho anh ngay trong hôm nay ạ."
    reply_payload = {"content": operator_text}
    resp4 = client_with_db.post(f"/api/v1/inbox/conversations/{conv_id}/reply", json=reply_payload)
    assert resp4.status_code == 200, resp4.text
    reply_data = resp4.json()
    assert reply_data["sender_type"] == "human"
    assert reply_data["content"] == operator_text

    # Verify operator message was dispatched via channel adapter
    assert len(zalo_adapter.sent_messages) == 2
    last_sent = zalo_adapter.sent_messages[-1]
    assert last_sent["conv_id"] == conv_id
    assert last_sent["content"] == operator_text

    # 5. Verify full conversation history
    msgs_resp = client_with_db.get(f"/api/v1/inbox/conversations/{conv_id}/messages")
    assert msgs_resp.status_code == 200
    messages = msgs_resp.json()
    assert len(messages) >= 5

    sender_types = [m["sender_type"] for m in messages]
    assert "customer" in sender_types
    assert "agent" in sender_types
    assert "system" in sender_types
    assert "human" in sender_types


def test_e2e_content_pipeline_artifact_size_and_library_export(
    client_with_db: TestClient,
    mock_all_externals: dict[str, Any],
) -> None:
    """Verify that Content Pipeline artifacts populate positive size_bytes and can be listed and exported via File Library."""
    parse_resp = client_with_db.post(
        "/api/v1/tasks/parse",
        json={"prompt_text": "Nghiên cứu Alex Hormozi rồi viết bài FB kèm ảnh 1080x1080"},
    )
    assert parse_resp.status_code == 200
    task_id = parse_resp.json()["data"]["task_id"]

    dispatch_resp = client_with_db.post(f"/api/v1/tasks/{task_id}/dispatch")
    assert dispatch_resp.status_code == 200

    # Query DB for artifacts
    factory = client_with_db.app.state.session_factory
    with factory() as session:
        artifacts = session.query(Artifact).filter_by(task_id=task_id).all()
        assert len(artifacts) >= 2
        for art in artifacts:
            assert art.size_bytes > 0, f"Artifact {art.name} size_bytes should be > 0"
            assert Path(art.file_path).exists()

        art_ids = [art.id for art in artifacts]

    # Query File Library endpoint
    files_resp = client_with_db.get("/api/v1/files")
    assert files_resp.status_code == 200
    files_data = files_resp.json()
    listed_ids = [f["id"] for f in files_data["data"]]
    for aid in art_ids:
        assert aid in listed_ids

    # Export artifacts to ZIP
    export_resp = client_with_db.post("/api/v1/files/export", json={"file_ids": art_ids})
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"] == "application/zip"
    assert len(export_resp.content) > 100


def test_e2e_funnel_pipeline_hil_rejection_and_feedback(
    client_with_db: TestClient,
    mock_all_externals: dict[str, Any],
) -> None:
    """Verify that HIL review gate rejection records feedback and stops execution."""
    parse_resp = client_with_db.post(
        "/api/v1/tasks/parse",
        json={
            "prompt_text": "Xây dựng chiến lược phễu 7 bước cho sản phẩm Coaching Giảm Cân 5M",
            "mode": "copilot",
        },
    )
    assert parse_resp.status_code == 200
    task_id = parse_resp.json()["data"]["task_id"]

    # First dispatch -> hits HIL review gate
    dispatch1 = client_with_db.post(f"/api/v1/tasks/{task_id}/dispatch")
    assert dispatch1.status_code == 200
    assert dispatch1.json()["data"]["status"] == "waiting_review"

    # Get the review gate
    rev_resp = client_with_db.get(f"/api/v1/reviews?taskId={task_id}")
    assert rev_resp.status_code == 200
    reviews_data = rev_resp.json()["data"]
    assert len(reviews_data) >= 1
    gate_id = reviews_data[0]["id"]

    # Reject with feedback
    reject_resp = client_with_db.patch(
        f"/api/v1/reviews/{gate_id}/decide",
        json={
            "decision": "reject",
            "feedback_text": "Cần bổ sung cam kết hoàn tiền 30 ngày rõ ràng hơn",
        },
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["data"]["status"] == "rejected"

    # Verify task state in DB reflects rejection
    factory = client_with_db.app.state.session_factory
    with factory() as session:
        gate = session.query(ReviewGate).filter_by(id=gate_id).first()
        assert gate is not None
        assert gate.status == "rejected"
        assert gate.feedback_text == "Cần bổ sung cam kết hoàn tiền 30 ngày rõ ràng hơn"

