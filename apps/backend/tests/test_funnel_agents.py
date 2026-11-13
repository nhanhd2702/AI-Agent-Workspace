"""Unit and integration tests for FunnelsAgent and GrowthAdvisorAgent (Task 4.3).

Verifies:
1. FunnelsAgent builds a 7-section funnel strategy with compliance guard ('Không bảo đảm').
2. Strict compliance disclaimer enforcement across health, weight loss, medical, finance, and crypto domains.
3. Offline interactive HTML artifact generation ('funnel_strategy.html') with secure CSP.
4. GrowthAdvisorAgent analyzes funnel metrics, identifies bottlenecks, and generates 'growth_plan.html'.
5. Secret redaction (mask_secrets) across inputs, outputs, structured data, and artifacts.
6. WorkerResult / BaseWorkerAgent compatibility via execute() adapter.
"""

from __future__ import annotations

import json
from typing import Any, Optional
import pytest

from app.agents.base import WorkerResult
from app.agents.funnels import (
    AgentResult,
    ArtifactOutput,
    FunnelsAgent,
    GrowthAdvisorAgent,
)
from app.llm.router import LlmResponse


class MockLlm:
    """Mock LLM Router simulating structured responses for funnel and growth agents."""

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
                    "sections": [
                        {
                            "id": "overview",
                            "title": "Toàn cảnh",
                            "summary": "Chiến lược phễu chuyển đổi 3 tầng từ mồi câu đến đồng hành cao cấp.",
                            "target_metrics": {"optin_rate": "15%", "conversion_rate": "3.5%"},
                        },
                        {
                            "id": "lead_magnet",
                            "title": "Tài liệu",
                            "product_name": "Tài liệu tự học",
                            "price": 200000,
                            "strategy": "Ebook hướng dẫn nền tảng và bài tập thực hành.",
                        },
                        {
                            "id": "coach",
                            "title": "Coach",
                            "product_name": "Combo Coach",
                            "price": 5000000,
                            "strategy": "Chương trình huấn luyện nhóm 4 tuần kèm phản hồi trực tiếp.",
                        },
                        {
                            "id": "intensive_mentorship",
                            "title": "Đồng hành chuyên sâu",
                            "product_name": "Đồng hành chuyên sâu",
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
                            "id": "full_profile",
                            "title": "Hồ sơ đầy đủ",
                            "dossier": "Toàn bộ tài liệu phễu, kịch bản email nurture, và timeline kích hoạt chiến dịch.",
                        },
                    ],
                    "recommendations": [
                        {
                            "category": "Quick Win",
                            "title": "Tối ưu trang cảm ơn (Thank You Page)",
                            "description": "Đặt ưu đãi Tripwire ngay sau khi khách hàng tải tài liệu tự học.",
                            "impact": "High",
                        },
                        {
                            "category": "Core Funnel",
                            "title": "Kích hoạt chuỗi email nurture 5 ngày",
                            "description": "Gửi case study chuyển hóa trước khi mời vào chương trình Coach.",
                            "impact": "High",
                        },
                    ],
                    "disclaimer": "Lưu ý quan trọng: Nội dung và chiến lược này không bảo đảm thay thế tư vấn y khoa chuyên nghiệp hoặc cam kết kết quả cụ thể.",
                }
            )
        return LlmResponse(
            content=content,
            model_used="mock-gemini-2.5",
            input_tokens=150,
            output_tokens=350,
            total_tokens=500,
            cost_usd=0.0015,
        )


@pytest.fixture
def mock_llm() -> MockLlm:
    return MockLlm()


# ============================================================================
# FunnelsAgent Tests
# ============================================================================


@pytest.mark.asyncio
async def test_funnels_agent_builds_7_section_strategy_with_health_disclaimer(mock_llm: MockLlm) -> None:
    """Exact test specified in Task 4.3 specification."""
    agent = FunnelsAgent(llm=mock_llm)
    res = await agent.run({
        "products": [
            {"name": "Tài liệu tự học", "price": 200000},
            {"name": "Combo Coach", "price": 5000000},
            {"name": "Đồng hành chuyên sâu", "price": 10000000},
        ],
        "domain": "health_weight_loss",
    })
    assert len(res.structured_data["sections"]) == 7
    assert "Không bảo đảm" in res.artifacts[0].content


@pytest.mark.asyncio
async def test_funnels_agent_7_section_titles_and_structure(mock_llm: MockLlm) -> None:
    """Verify all 7 mandatory section titles are present in structured data."""
    agent = FunnelsAgent(llm=mock_llm)
    res = await agent.run({
        "products": [
            {"name": "Tài liệu tự học", "price": 200000},
            {"name": "Combo Coach", "price": 5000000},
            {"name": "Đồng hành chuyên sâu", "price": 10000000},
        ],
        "domain": "fitness_coaching",
    })

    assert res.status == "completed"
    sections = res.structured_data["sections"]
    assert len(sections) == 7

    expected_titles = [
        "Toàn cảnh",
        "Tài liệu",
        "Coach",
        "Đồng hành chuyên sâu",
        "Nội dung & đo lường",
        "Điểm cần chốt",
        "Hồ sơ đầy đủ",
    ]
    actual_titles = [s["title"] for s in sections]
    assert actual_titles == expected_titles

    # Verify primary artifact is HTML and sanitized
    assert res.artifacts[0].filename == "funnel_strategy.html"
    assert res.artifacts[0].artifact_type == "html"
    assert "<!DOCTYPE html>" in res.artifacts[0].content
    assert "default-src 'none'" in res.artifacts[0].content


@pytest.mark.asyncio
async def test_funnels_agent_finance_domain_compliance(mock_llm: MockLlm) -> None:
    """Verify financial and crypto domains trigger the mandatory 'Không bảo đảm' disclaimer."""
    agent = FunnelsAgent(llm=mock_llm)
    res = await agent.run({
        "products": [
            {"name": "Khóa học nhập môn Crypto", "price": 500000},
            {"name": "Nhóm tín hiệu & phân tích", "price": 3000000},
            {"name": "Cố vấn quản lý danh mục 1:1", "price": 20000000},
        ],
        "domain": "finance_crypto",
    })

    assert res.status == "completed"
    assert "Không bảo đảm" in res.structured_data["compliance_disclaimer"]
    assert "Không bảo đảm" in res.artifacts[0].content
    assert "tài chính" in res.structured_data["compliance_disclaimer"].lower()


@pytest.mark.asyncio
async def test_funnels_agent_masks_secrets(mock_llm: MockLlm) -> None:
    """Verify secrets are redacted from artifacts and structured data."""
    secret_key = "sk-live-supersecretapikey12345"
    agent = FunnelsAgent(llm=mock_llm)
    res = await agent.run({
        "products": [
            {"name": "Tài liệu tự học", "price": 200000, "note": f"Auth with {secret_key}"},
        ],
        "domain": "general_business",
        "api_key": secret_key,
    })

    for artifact in res.artifacts:
        assert secret_key not in artifact.content
        assert "***REDACTED***" in artifact.content or "sk-live-" not in artifact.content

    raw_json = json.dumps(res.structured_data)
    assert secret_key not in raw_json


@pytest.mark.asyncio
async def test_funnels_agent_execute_compatibility() -> None:
    """Verify FunnelsAgent works through BaseWorkerAgent.execute() adapter."""
    mock_llm_inst = MockLlm()
    agent = FunnelsAgent(llm=mock_llm_inst)
    subtask = {
        "id": "subtask-funnel-1",
        "instruction": "Xây dựng chiến lược phễu bán hàng",
        "metadata": {
            "products": [{"name": "Ebook", "price": 100000}],
            "domain": "health_weight_loss",
        },
    }
    result = await agent.execute(subtask=subtask, context={})
    assert isinstance(result, WorkerResult)
    assert isinstance(result, AgentResult)
    assert result.status == "completed"
    assert len(result.structured_data["sections"]) == 7
    assert "Không bảo đảm" in result.artifacts[0].content


# ============================================================================
# GrowthAdvisorAgent Tests
# ============================================================================


@pytest.mark.asyncio
async def test_growth_advisor_analyzes_funnel_metrics_and_generates_growth_plan(mock_llm: MockLlm) -> None:
    """Verify GrowthAdvisorAgent analyzes metrics, identifies bottlenecks, and generates growth_plan.html."""
    agent = GrowthAdvisorAgent(llm=mock_llm)
    res = await agent.run({
        "metrics": {
            "traffic": 10000,
            "leads": 800,
            "low_ticket_sales": 50,
            "mid_ticket_sales": 8,
            "high_ticket_sales": 1,
            "ad_spend": 5000000,
            "revenue": 25000000,
        },
        "domain": "online_education",
        "objective": "Tối ưu hóa tỷ lệ chuyển đổi từ lead sang mua khóa học",
    })

    assert res.status == "completed"
    assert len(res.structured_data["recommendations"]) >= 2
    assert "funnel_analysis" in res.structured_data
    assert "bottlenecks" in res.structured_data
    assert res.structured_data["funnel_analysis"]["optin_rate"] == 0.08

    # Verify growth_plan.html artifact
    assert any(a.filename == "growth_plan.html" for a in res.artifacts)
    plan_artifact = next(a for a in res.artifacts if a.filename == "growth_plan.html")
    assert "<!DOCTYPE html>" in plan_artifact.content
    assert "default-src 'none'" in plan_artifact.content


@pytest.mark.asyncio
async def test_growth_advisor_compliance_disclaimer(mock_llm: MockLlm) -> None:
    """Verify GrowthAdvisor enforces compliance guard when sensitive domains are analyzed."""
    agent = GrowthAdvisorAgent(llm=mock_llm)
    res = await agent.run({
        "metrics": {
            "traffic": 5000,
            "leads": 400,
            "low_ticket_sales": 30,
            "mid_ticket_sales": 5,
            "high_ticket_sales": 1,
        },
        "domain": "medical_supplements",
    })

    assert res.status == "completed"
    assert "Không bảo đảm" in res.structured_data["compliance_disclaimer"]
    plan_artifact = next(a for a in res.artifacts if a.filename == "growth_plan.html")
    assert "Không bảo đảm" in plan_artifact.content


@pytest.mark.asyncio
async def test_growth_advisor_masks_secrets(mock_llm: MockLlm) -> None:
    """Verify secrets are redacted in GrowthAdvisorAgent outputs and artifacts."""
    secret_token = "ghp_superSecretTokenForGrowthAdvisor123456"
    agent = GrowthAdvisorAgent(llm=mock_llm)
    res = await agent.run({
        "metrics": {"traffic": 1000, "leads": 100},
        "domain": "general",
        "token": secret_token,
    })

    for artifact in res.artifacts:
        assert secret_token not in artifact.content

    assert secret_token not in json.dumps(res.structured_data)


@pytest.mark.asyncio
async def test_growth_advisor_execute_compatibility() -> None:
    """Verify GrowthAdvisorAgent works through execute() adapter."""
    mock_llm_inst = MockLlm()
    agent = GrowthAdvisorAgent(llm=mock_llm_inst)
    subtask = {
        "id": "subtask-growth-1",
        "instruction": "Tối ưu hóa phễu tăng trưởng",
        "metadata": {
            "metrics": {"traffic": 2000, "leads": 200},
            "domain": "finance_wealth",
        },
    }
    result = await agent.execute(subtask=subtask, context={})
    assert isinstance(result, AgentResult)
    assert result.status == "completed"
    assert any(a.filename == "growth_plan.html" for a in result.artifacts)
    assert "Không bảo đảm" in result.structured_data["compliance_disclaimer"]
