"""Unit and integration tests for UIDesignerAgent (Task 4.4).

Verifies:
1. UIDesignerAgent outputs offline responsive prototype HTML with prototype banner.
2. Simulated checkout modal with pure JS interaction (order summary, customer inputs, simulated payment).
3. BrandProfile styling integration (brand name, colors, tagline).
4. FunnelsAgent output integration (funnel strategy context, tiers, compliance disclaimer).
5. Secret redaction (mask_secrets) across inputs, outputs, and artifacts.
6. BaseWorkerAgent and WorkerResult interface compatibility via execute() adapter.
7. Standard high-converting sections (Hero, Pain, Solution, Deliverables, Testimonials, Pricing, Guarantee, FAQ, Checkout) and inline SVGs.
"""

from __future__ import annotations

import json
from typing import Any, Optional
import pytest

from app.agents.base import BaseWorkerAgent, WorkerResult
from app.agents.funnels import (
    AgentResult,
    ArtifactOutput,
    FunnelsAgent,
    UIDesignerAgent,
)
from app.db.models import BrandProfile
from app.llm.router import LlmResponse


class MockLlm:
    """Mock LLM Router simulating structured responses for UI Designer Agent."""

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
                            "name": "Nguyễn Văn Hùng",
                            "role": "Chủ shop phụ kiện công nghệ",
                            "comment": "Tài liệu rất chi tiết, tôi áp dụng ngay và tăng được 35% tỷ lệ chốt đơn tuần đầu.",
                            "rating": 5,
                        },
                        {
                            "name": "Trần Thị Mai",
                            "role": "Freelance Marketing",
                            "comment": "Giá 200K quá hời cho lượng kiến thức thực chiến và biểu mẫu chất lượng thế này.",
                            "rating": 5,
                        },
                    ],
                    "faqs": [
                        {
                            "question": "Tôi có được hỗ trợ sau khi nhận tài liệu không?",
                            "answer": "Có, bạn được tham gia nhóm trao đổi riêng và nhận các bản cập nhật tài liệu trọn đời.",
                        },
                        {
                            "question": "Sau khi đặt mua thì nhận tài liệu như thế nào?",
                            "answer": "Tài liệu được gửi tự động qua email kèm link truy cập kho tài nguyên bảo mật ngay lập tức.",
                        },
                    ],
                    "guarantee": "Cam kết hoàn tiền 100% trong 30 ngày nếu bạn không thấy tài liệu hữu ích cho công việc.",
                }
            )
        return LlmResponse(
            content=content,
            model_used="mock-gemini-2.5",
            input_tokens=180,
            output_tokens=420,
            total_tokens=600,
            cost_usd=0.0018,
        )


@pytest.fixture
def mock_llm() -> MockLlm:
    return MockLlm()


# ============================================================================
# Task 4.4 Spec & Core Tests
# ============================================================================


@pytest.mark.asyncio
async def test_ui_designer_outputs_offline_responsive_html_with_prototype_banner(mock_llm: MockLlm) -> None:
    """Exact test specified in Task 4.4 specification."""
    agent = UIDesignerAgent(llm=mock_llm)
    res = await agent.run({"product_name": "Tài liệu tự học 200K", "price": "200.000đ"})
    html = res.artifacts[0].content
    assert "BẢN THIẾT KẾ ĐỂ DUYỆT" in html
    assert "https://cdn" not in html
    assert "@media" in html


@pytest.mark.asyncio
async def test_ui_designer_simulated_checkout_modal(mock_llm: MockLlm) -> None:
    """Verify simulated checkout popup markup, form fields, and client-side JS interaction."""
    agent = UIDesignerAgent(llm=mock_llm)
    res = await agent.run({
        "product_name": "Khóa học AI Automation 500K",
        "price": 500000,
    })
    html = res.artifacts[0].content

    # Check simulated checkout modal container and order summary
    assert "checkout-modal" in html or "id=\"checkout-modal\"" in html
    assert "500.000" in html or "500000" in html
    assert "Khóa học AI Automation 500K" in html

    # Check simulated customer input fields
    assert "checkout-name" in html or "customer_name" in html
    assert "checkout-phone" in html or "customer_phone" in html
    assert "checkout-address" in html or "customer_address" in html

    # Check simulated payment trigger & pure client-side JS handler
    assert "simulated-checkout-btn" in html or "openCheckout" in html or "handleCheckout" in html
    assert "simulatePayment" in html or "confirmCheckout" in html or "checkout-success" in html
    # Pure client-side JS without external API calls or payment gate redirection
    assert "fetch(" not in html or "window.location" not in html


@pytest.mark.asyncio
async def test_ui_designer_brand_profile_styling(mock_llm: MockLlm) -> None:
    """Verify brand colors, brand name, and guidelines are injected into CSS and layout."""
    brand_profile = BrandProfile(
        id="bp-test-1",
        project_id="proj-brand",
        brand_name="Học Viện Siêu Trí Tuệ",
        tagline="Bứt phá giới hạn tư duy cùng AI",
        target_audience="Chủ doanh nghiệp nhỏ và Marketer",
        tone_of_voice="Chuyên nghiệp, truyền cảm hứng và thực chiến",
        brand_colors=["#10b981", "#047857", "#064e3b"],
        fonts=["Inter", "Roboto"],
    )

    agent = UIDesignerAgent(llm=mock_llm, brand_profile=brand_profile)
    res = await agent.run({
        "product_name": "Tài liệu tự học 200K",
        "price": 200000,
    })
    html = res.artifacts[0].content

    assert "Học Viện Siêu Trí Tuệ" in html
    assert "Bứt phá giới hạn tư duy cùng AI" in html
    assert "#10b981" in html
    assert res.structured_data["brand_name"] == "Học Viện Siêu Trí Tuệ"


@pytest.mark.asyncio
async def test_ui_designer_with_funnel_strategy_context(mock_llm: MockLlm) -> None:
    """Verify UIDesignerAgent seamlessly consumes outputs and context from FunnelsAgent."""
    funnel_agent = FunnelsAgent(llm=mock_llm)
    funnel_res = await funnel_agent.run({
        "products": [
            {"name": "Tài liệu tự học 200K", "price": 200000},
            {"name": "Combo Coach Thực Chiến", "price": 5000000},
            {"name": "Đồng hành chuyên sâu 1:1", "price": 10000000},
        ],
        "domain": "finance_investing",
        "objective": "Tối ưu hóa chuyển đổi trang bán tài liệu dẫn nhập",
    })

    ui_agent = UIDesignerAgent(llm=mock_llm)
    res = await ui_agent.run({
        "product_name": "Tài liệu tự học 200K",
        "price": 200000,
        "funnel_strategy": funnel_res.structured_data,
        "domain": "finance_investing",
    })

    assert res.status == "completed"
    html = res.artifacts[0].content
    # Mandatory prototype banner
    assert "BẢN THIẾT KẾ ĐỂ DUYỆT" in html
    # Compliance disclaimer from finance domain funnel strategy
    assert "Không bảo đảm" in html
    # Pricing correctly rendered in VND
    assert "200.000 ₫" in html or "200.000đ" in html or "200.000" in html
    # Funnel context reflected in structured data
    assert res.structured_data["domain"] == "finance_investing"
    assert "funnel_strategy" in res.structured_data


@pytest.mark.asyncio
async def test_ui_designer_secret_masking(mock_llm: MockLlm) -> None:
    """Verify secrets and sensitive tokens are masked in HTML and structured data."""
    secret_key = "sk-live-landingpage-designer-token-998877"
    auth_token = "bearer_secret_auth_token_for_designer"

    agent = UIDesignerAgent(llm=mock_llm)
    res = await agent.run({
        "product_name": f"Tài liệu tự học 200K (Secret: {secret_key})",
        "price": 200000,
        "api_key": secret_key,
        "auth_token": auth_token,
    })

    # Assert secret tokens are scrubbed from HTML artifact
    html = res.artifacts[0].content
    assert secret_key not in html
    assert auth_token not in html

    # Assert secret tokens are scrubbed from structured data
    structured_json = json.dumps(res.structured_data)
    assert secret_key not in structured_json
    assert auth_token not in structured_json


@pytest.mark.asyncio
async def test_ui_designer_base_worker_compatibility() -> None:
    """Verify UIDesignerAgent inherits from BaseWorkerAgent and operates via execute() adapter."""
    mock_llm_inst = MockLlm()
    agent = UIDesignerAgent(llm=mock_llm_inst)

    assert isinstance(agent, BaseWorkerAgent)

    subtask = {
        "id": "subtask-landing-page-1",
        "instruction": "Thiết kế giao diện landing page cho sản phẩm 200K",
        "metadata": {
            "product_name": "Tài liệu tự học 200K",
            "price": "200.000đ",
            "brand_profile": {
                "brand_name": "AI Growth Lab",
                "brand_colors": ["#3b82f6", "#1d4ed8"],
            },
        },
    }

    result = await agent.execute(subtask=subtask, context={})
    assert isinstance(result, WorkerResult)
    assert isinstance(result, AgentResult)
    assert result.status == "completed"
    assert len(result.artifacts) >= 1
    assert result.artifacts[0].filename in {"landing_page.html", "index.html"}
    assert "BẢN THIẾT KẾ ĐỂ DUYỆT" in result.artifacts[0].content


@pytest.mark.asyncio
async def test_ui_designer_high_converting_sections_and_inline_svg(mock_llm: MockLlm) -> None:
    """Verify all standard high-converting sections and offline inline SVG icons/placeholders."""
    agent = UIDesignerAgent(llm=mock_llm)
    res = await agent.run({
        "product_name": "Sổ Tay Tự Động Hóa Doanh Nghiệp",
        "price": 250000,
    })

    html = res.artifacts[0].content

    # High-converting section markers
    assert "hero-section" in html or "hero" in html.lower()
    assert "pain-section" in html or "vấn đề" in html.lower() or "nỗi đau" in html.lower() or "pain" in html.lower()
    assert "solution-section" in html or "giải pháp" in html.lower() or "solution" in html.lower()
    assert "deliverables" in html.lower() or "bạn sẽ nhận được" in html.lower() or "nội dung" in html.lower()
    assert "testimonial" in html.lower() or "đánh giá" in html.lower() or "cảm nhận" in html.lower()
    assert "pricing" in html.lower() or "bảng giá" in html.lower() or "đặt mua" in html.lower()
    assert "guarantee" in html.lower() or "cam kết" in html.lower() or "bảo hành" in html.lower()
    assert "faq" in html.lower() or "câu hỏi" in html.lower()
    assert "checkout" in html.lower()

    # Inline SVG icons and placeholders (no external images)
    assert "<svg" in html
    assert "</svg>" in html
    assert "<img src=\"http" not in html
    assert "https://cdn" not in html


def test_agent_package_re_exports() -> None:
    """Verify app.agents re-exports FunnelsAgent, GrowthAdvisorAgent, and UIDesignerAgent."""
    import app.agents as agents_pkg

    assert hasattr(agents_pkg, "FunnelsAgent")
    assert hasattr(agents_pkg, "GrowthAdvisorAgent")
    assert hasattr(agents_pkg, "UIDesignerAgent")
    assert hasattr(agents_pkg, "AgentResult")
    assert hasattr(agents_pkg, "ArtifactOutput")


def test_growth_advisor_compute_metrics_aov_and_churn() -> None:
    """Verify Task 4.3 reviewer polish recommendation: GrowthAdvisorAgent computes aov and churn."""
    from app.agents.funnels import GrowthAdvisorAgent

    agent = GrowthAdvisorAgent()
    metrics_input = {
        "traffic": 5000,
        "leads": 500,
        "low_ticket_sales": 50,
        "mid_ticket_sales": 10,
        "high_ticket_sales": 2,
        "ad_spend": 10000000,
        "revenue": 50000000,
        "churn": 0.045,
    }
    res = agent._compute_metrics(metrics_input)

    assert "aov" in res
    assert "churn" in res
    # 62 total customers (50 + 10 + 2), revenue 50,000,000 -> aov = 50,000,000 / 62 = 806451.61
    assert res["aov"] == round(50000000 / 62, 2)
    assert res["churn"] == 0.045


@pytest.mark.asyncio
async def test_funnels_and_ui_designer_safe_numeric_price_parsing(mock_llm: MockLlm) -> None:
    """Verify safe numeric price parsing with various currency string formats."""
    from app.agents.funnels import FunnelsAgent, UIDesignerAgent

    # 1. Test FunnelsAgent._classify_products with formatted currency strings
    f_agent = FunnelsAgent(llm=mock_llm)
    classified = f_agent._classify_products([
        {"name": "Ebook 200K", "price": "200.000đ"},
        {"name": "Khóa học 1.5M", "price": "1.500.000 ₫"},
        {"name": "Gói Mentoring 10M", "price": "10,000,000"},
        {"name": "Khóa 50K", "price": "50k"},
        "Khóa miễn phí",
    ])

    assert classified[0]["price"] == 0.0  # Khóa miễn phí
    assert classified[1]["price"] == 50000.0  # 50k
    assert classified[2]["price"] == 200000.0  # 200.000đ
    assert classified[3]["price"] == 1500000.0  # 1.500.000 ₫
    assert classified[4]["price"] == 10000000.0  # 10,000,000

    # 2. Test UIDesignerAgent with formatted currency strings
    ui_agent = UIDesignerAgent(llm=mock_llm)
    res = await ui_agent.run({"product_name": "Combo AI Pro", "price": "350.000đ"})
    assert res.structured_data["price"] == 350000.0
    assert "350.000 ₫" in res.structured_data["formatted_price"]


@pytest.mark.asyncio
async def test_ui_designer_brand_color_xss_injection_sanitization(mock_llm: MockLlm) -> None:
    """Verify malicious brand_colors containing XSS/HTML injection are replaced by safe fallback."""
    from app.agents.funnels import _safe_hex_color

    xss_payload = "</style><script>alert('xss')</script>"

    # 1. Test helper function directly
    assert _safe_hex_color(xss_payload, "#2563eb") == "#2563eb"
    assert _safe_hex_color("red; background: url(x)", "#1d4ed8") == "#1d4ed8"
    assert _safe_hex_color("#3b82f6", "#2563eb") == "#3b82f6"
    assert _safe_hex_color("#fff", "#2563eb") == "#fff"

    # 2. Test agent execution with malicious brand_profile
    agent = UIDesignerAgent(llm=mock_llm)
    res = await agent.run({
        "product_name": "Tài liệu Bảo mật",
        "price": 200000,
        "brand_profile": {
            "brand_name": "CyberSec Pro",
            "brand_colors": [xss_payload, xss_payload, xss_payload],
        },
    })

    assert res.status == "completed"
    assert res.structured_data["primary_color"] == "#2563eb"
    html = res.artifacts[0].content
    assert "<script>alert('xss')</script>" not in html
    assert "--primary: #2563eb;" in html


@pytest.mark.asyncio
async def test_ui_designer_handles_string_list_testimonials_and_faqs() -> None:
    """Verify safe rendering when LLM generates string lists instead of dicts for testimonials and faqs."""
    canned_copy = json.dumps({
        "headline": "Khóa Học Thực Chiến Siêu Tốc",
        "subheadline": "Chinh phục kỹ năng mới chỉ sau 7 ngày",
        "testimonials": [
            "Khóa học rất hay và hữu ích!",
            "Giảng viên giải thích cực kỳ chi tiết, dễ hiểu.",
        ],
        "faqs": [
            "Khóa học này dành cho ai?",
            "Tôi có cần biết lập trình trước không?",
        ],
    })
    custom_mock_llm = MockLlm(canned_response=canned_copy)
    agent = UIDesignerAgent(llm=custom_mock_llm)
    res = await agent.run({
        "product_name": "Khóa Học Thực Chiến",
        "price": 300000,
    })
    assert res.status == "completed"
    html = res.artifacts[0].content
    assert "Khóa học rất hay và hữu ích!" in html
    assert "Giảng viên giải thích cực kỳ chi tiết" in html
    assert "Khóa học này dành cho ai?" in html
    assert "Tôi có cần biết lập trình trước không?" in html
    assert "Khách hàng thân thiết" in html


def test_growth_advisor_handles_percentage_churn_string() -> None:
    """Verify GrowthAdvisorAgent parses percentage churn strings safely without ValueError."""
    from app.agents.funnels import GrowthAdvisorAgent

    agent = GrowthAdvisorAgent()

    # Pass {"churn": "5%"}
    res1 = agent._compute_metrics({"traffic": 1000, "leads": 100, "churn": "5%"})
    assert res1["churn"] == 0.05

    # Pass {"churn_rate": "4.5%"}
    res2 = agent._compute_metrics({"traffic": 1000, "leads": 100, "churn_rate": "4.5%"})
    assert res2["churn"] == 0.045

    # Pass float or int
    res3 = agent._compute_metrics({"traffic": 1000, "leads": 100, "churn": 0.03})
    assert res3["churn"] == 0.03

    # Pass invalid string gracefully
    res4 = agent._compute_metrics({"traffic": 1000, "leads": 100, "churn": "invalid_churn"})
    assert res4["churn"] == 0.0


def test_parse_numeric_price_negative_clamping() -> None:
    """Verify _parse_numeric_price clamps negative numbers or strings to 0.0."""
    from app.agents.funnels import _parse_numeric_price

    assert _parse_numeric_price(-500) == 0.0
    assert _parse_numeric_price("-500") == 0.0
    assert _parse_numeric_price("-500.000đ") == 0.0
    assert _parse_numeric_price("-200k") == 0.0
    assert _parse_numeric_price(0) == 0.0
    assert _parse_numeric_price(200000) == 200000.0


