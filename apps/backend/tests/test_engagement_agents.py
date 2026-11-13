"""Tests for Engagement Agents — SalesAgent and SupportAgent (Task 4.5).

Verifies:
1. SupportAgent RAG grounding, citation generation, and confidence scoring.
2. SupportAgent escalation rules:
   - Angry complaints & legal threats ("kiện", "lừa đảo", "tố cáo", "báo công an", "tẩy chay", "bồi thường")
   - Low RAG confidence (top chunk score < 0.7 or no chunks)
   - Media/attachments present (images, files, or payment confirmation keywords like "đã chuyển khoản", "ảnh bill", "biên lai")
3. SalesAgent consultative selling grounded in product catalog & brand profile.
4. SalesAgent escalation rules:
   - Price negotiation / VIP discount requests beyond standard catalog
   - Payment transfer screenshots / bill confirmation keywords
   - Low RAG confidence when asked specific technical specs
   - Angry complaints
5. Co-pilot mode requirement (requires_review=True default).
6. Secret scrubbing (mask_secrets) across inputs, outputs, and citations.
7. BaseWorkerAgent inheritance and execute() adapter compatibility.
8. Re-exports in app.agents.__init__.py.
"""

from __future__ import annotations

from typing import Any, Optional
import pytest

from app.agents.base import WorkerResult
from app.agents.engagement import EngagementReply, SalesAgent, SupportAgent
from app.brain.retriever import ChunkHit
from app.llm.router import LlmResponse


class MockLlm:
    """Mock LLM Router simulating text completion for engagement agents."""

    def __init__(self, canned_response: Optional[str] = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.canned_response = canned_response or "Dạ xin chào! Em có thể hỗ trợ gì cho anh/chị ạ?"

    async def complete(self, messages: Any = None, **kwargs: Any) -> LlmResponse:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return LlmResponse(
            content=self.canned_response,
            model_used="mock-llm-model",
            input_tokens=50,
            output_tokens=30,
            total_tokens=80,
            cost_usd=0.0001,
        )


class MockRetriever:
    """Mock BrainRetriever returning predefined ChunkHits."""

    def __init__(self, hits: Optional[list[ChunkHit]] = None) -> None:
        self.hits = hits if hits is not None else []
        self.calls: list[dict[str, Any]] = []

    def search(
        self,
        query: str,
        collections: list[str],
        top_k: int = 5,
        min_similarity: Optional[float] = None,
    ) -> list[ChunkHit]:
        self.calls.append(
            {
                "query": query,
                "collections": collections,
                "top_k": top_k,
                "min_similarity": min_similarity,
            }
        )
        return self.hits


@pytest.fixture
def mock_llm() -> MockLlm:
    return MockLlm()


@pytest.fixture
def mock_retriever_low_score() -> MockRetriever:
    """Returns chunks with similarity score below 0.7 threshold."""
    return MockRetriever(
        hits=[
            ChunkHit(
                chunk_id="chunk-low-1",
                doc_id="doc-low",
                doc_title="Chính Sách Chung",
                collection="knowledge",
                text="Một số thông tin tham khảo chung.",
                score=0.52,
                page=1,
            )
        ]
    )


@pytest.fixture
def mock_retriever_high_score() -> MockRetriever:
    """Returns chunks with high similarity score >= 0.7."""
    return MockRetriever(
        hits=[
            ChunkHit(
                chunk_id="chunk-high-1",
                doc_id="doc-refund",
                doc_title="Chính Sách Hoàn Tiền",
                collection="knowledge",
                text="Chính sách hoàn tiền: Trong vòng 30 ngày kể từ ngày mua, khách hàng được hoàn 100% nếu chưa xem quá 20% khóa học.",
                score=0.88,
                page=1,
            )
        ]
    )


@pytest.fixture
def mock_catalog_retriever() -> MockRetriever:
    """Returns chunks from catalog and brand profile."""
    return MockRetriever(
        hits=[
            ChunkHit(
                chunk_id="prod-1",
                doc_id="doc-catalog",
                doc_title="Bảng Giá Sản Phẩm 2026",
                collection="catalog",
                text="Khóa AI Engineer Pro: Giá niêm yết 15.000.000 ₫. Lộ trình 12 tuần thực chiến cùng chuyên gia.",
                score=0.92,
                page=1,
            )
        ]
    )


# ============================================================================
# Exact Spec Test
# ============================================================================


@pytest.mark.asyncio
async def test_support_agent_escalates_angry_complaint_or_low_rag_confidence(
    mock_retriever_low_score, mock_llm
):
    """Exact test case required by specification."""
    agent = SupportAgent(retriever=mock_retriever_low_score, llm=mock_llm)
    res = await agent.draft_reply("conv-1", "Tôi muốn kiện công ty vì lừa đảo!")
    assert res.escalate_to_human is True
    assert res.requires_review is True


# ============================================================================
# SupportAgent Tests
# ============================================================================


@pytest.mark.asyncio
async def test_support_agent_happy_path_grounded_rag(mock_retriever_high_score, mock_llm):
    mock_llm.canned_response = "Dạ theo chính sách của công ty, anh/chị được hoàn tiền 100% trong 30 ngày ạ."
    agent = SupportAgent(retriever=mock_retriever_high_score, llm=mock_llm)

    res = await agent.draft_reply("conv-10", "Cho em hỏi điều kiện hoàn tiền khóa học?")

    assert res.escalate_to_human is False
    assert res.requires_review is True  # Co-pilot mode default
    assert res.confidence_score >= 0.7
    assert len(res.citations) >= 1
    assert res.citations[0]["doc_title"] == "Chính Sách Hoàn Tiền"
    assert "hoàn tiền" in res.reply_text.lower()


@pytest.mark.asyncio
async def test_support_agent_escalates_legal_threats_and_angry_keywords(
    mock_retriever_high_score, mock_llm
):
    agent = SupportAgent(retriever=mock_retriever_high_score, llm=mock_llm)

    threat_messages = [
        "Tôi sẽ tố cáo bên bạn lên báo công an!",
        "Lừa đảo khách hàng, tôi kêu gọi tẩy chay!",
        "Yêu cầu bồi thường thiệt hại ngay lập tức!",
    ]
    for msg in threat_messages:
        res = await agent.draft_reply("conv-threat", msg)
        assert res.escalate_to_human is True
        assert res.requires_review is True
        assert res.escalation_reason is not None


@pytest.mark.asyncio
async def test_support_agent_escalates_attachments_or_payment_confirmation(
    mock_retriever_high_score, mock_llm
):
    agent = SupportAgent(retriever=mock_retriever_high_score, llm=mock_llm)

    # Escalates on image/file attachment
    res_attachment = await agent.draft_reply(
        "conv-att",
        "Em gửi file lỗi ở đây ạ",
        attachments=["screenshot_error.png"],
    )
    assert res_attachment.escalate_to_human is True
    assert res_attachment.requires_review is True

    # Escalates on payment keywords
    res_bill = await agent.draft_reply(
        "conv-bill",
        "Mình đã chuyển khoản xong rồi, kiểm tra giúp mình biên lai nhé",
    )
    assert res_bill.escalate_to_human is True
    assert "chuyển khoản" in (res_bill.escalation_reason or "").lower() or "thanh toán" in (
        res_bill.escalation_reason or ""
    ).lower() or "biên lai" in (res_bill.escalation_reason or "").lower()


# ============================================================================
# SalesAgent Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sales_agent_happy_path_consultative_selling(mock_catalog_retriever, mock_llm):
    mock_llm.canned_response = (
        "Dạ khóa học AI Engineer Pro bên em có học phí niêm yết là 15.000.000 ₫ với 12 tuần thực chiến ạ!"
    )
    agent = SalesAgent(retriever=mock_catalog_retriever, llm=mock_llm)

    res = await agent.draft_reply("conv-sales-1", "Khóa AI Engineer Pro giá bao nhiêu vậy bạn?")

    assert res.escalate_to_human is False
    assert res.requires_review is True
    assert res.confidence_score >= 0.7
    assert len(res.citations) >= 1
    assert res.citations[0]["doc_title"] == "Bảng Giá Sản Phẩm 2026"
    assert len(res.suggested_actions) >= 1


@pytest.mark.asyncio
async def test_sales_agent_escalates_price_negotiation_and_vip_discount(
    mock_catalog_retriever, mock_llm
):
    agent = SalesAgent(retriever=mock_catalog_retriever, llm=mock_llm)

    bargain_messages = [
        "Khóa này bớt giá được không em, giảm giá cho anh 30% đi",
        "Có chiết khấu riêng cho công ty anh không, xin deal riêng VIP discount nhé",
        "Bên bạn có giảm sâu hôm nay không?",
    ]
    for msg in bargain_messages:
        res = await agent.draft_reply("conv-bargain", msg)
        assert res.escalate_to_human is True
        assert res.requires_review is True
        assert res.escalation_reason is not None


@pytest.mark.asyncio
async def test_sales_agent_escalates_payment_proof(mock_catalog_retriever, mock_llm):
    agent = SalesAgent(retriever=mock_catalog_retriever, llm=mock_llm)

    res = await agent.draft_reply(
        "conv-pay",
        "Tôi đã chuyển khoản học phí rồi, đây là ảnh bill nhé",
        attachments=["bill.jpg"],
    )
    assert res.escalate_to_human is True
    assert res.requires_review is True


@pytest.mark.asyncio
async def test_sales_agent_escalates_low_rag_on_technical_specs(mock_retriever_low_score, mock_llm):
    agent = SalesAgent(retriever=mock_retriever_low_score, llm=mock_llm)

    res = await agent.draft_reply(
        "conv-tech",
        "Cho mình hỏi chi tiết thông số GPU cluster và latency API của hệ thống bên bạn?",
    )
    assert res.escalate_to_human is True
    assert res.requires_review is True


# ============================================================================
# EngagementReply & Dataclass Contract Tests
# ============================================================================


def test_engagement_reply_dataclass_and_to_dict():
    reply = EngagementReply(
        reply_text="Xin chào quý khách",
        escalate_to_human=False,
        requires_review=True,
        confidence_score=0.85,
        escalation_reason=None,
        citations=[{"doc_title": "Chính sách", "score": 0.85}],
        suggested_actions=["Gửi link tư vấn"],
        intent="general_inquiry",
    )
    d = reply.to_dict()
    assert d["reply_text"] == "Xin chào quý khách"
    assert d["escalate_to_human"] is False
    assert d["requires_review"] is True
    assert d["confidence_score"] == 0.85
    assert d["citations"] == [{"doc_title": "Chính sách", "score": 0.85}]
    assert d["suggested_actions"] == ["Gửi link tư vấn"]
    assert d["intent"] == "general_inquiry"


# ============================================================================
# Secret Scrubbing & BaseWorkerAgent Adapter Tests
# ============================================================================


@pytest.mark.asyncio
async def test_secret_scrubbing_with_mask_secrets(mock_retriever_high_score, mock_llm):
    secret_key = "sk-proj-supersecretkey1234567890abcdef"
    mock_llm.canned_response = f"Khóa học có thể thanh toán qua token {secret_key}"
    agent = SupportAgent(retriever=mock_retriever_high_score, llm=mock_llm)

    res = await agent.draft_reply(
        "conv-sec",
        f"Tôi đang dùng API key {secret_key}, hỗ trợ giúp tôi",
    )
    assert secret_key not in res.reply_text
    assert secret_key not in str(res.citations)


@pytest.mark.asyncio
async def test_base_worker_agent_execute_adapter(mock_retriever_high_score, mock_llm):
    agent = SupportAgent(retriever=mock_retriever_high_score, llm=mock_llm)

    class DummySubtask:
        id = "subtask-eng-1"
        agent_id = "agent-support"

    context = {
        "conv_id": "conv-exec-1",
        "customer_msg": "Hỗ trợ chính sách hoàn tiền",
    }
    result = await agent.execute(DummySubtask(), context)
    assert isinstance(result, WorkerResult)
    assert result.status == "completed"
    assert "output" in result.to_dict()
    assert result.output["requires_review"] is True


def test_reexport_in_agents_package():
    from app.agents import EngagementReply as ER, SalesAgent as SA, SupportAgent as SupA

    assert SA is SalesAgent
    assert SupA is SupportAgent
    assert ER is EngagementReply


# ============================================================================
# Regression Tests (Task 4.5 Review Findings)
# ============================================================================


def test_support_agent_default_collections_match_spec():
    """Verify default collections are ['brand_profile', 'policies', 'faqs', 'default']."""
    agent = SupportAgent()
    assert agent.collections == ["brand_profile", "policies", "faqs", "default"]


@pytest.mark.asyncio
async def test_conversation_history_secret_scrubbed(mock_retriever_high_score, mock_llm):
    """Pass secret in conversation_history and verify prompt received by LLM has secret masked."""
    agent = SupportAgent(retriever=mock_retriever_high_score, llm=mock_llm)
    secret_key = "sk-proj-historysecret1234567890abcdef"
    extra_secret = "EXTRA_CONFIDENTIAL_HISTORY_TOKEN"

    history = [
        {"role": "user", "content": f"My secret API key is {secret_key}"},
        {"role": "assistant", "content": f"Acknowledged token: {extra_secret}"},
    ]

    await agent.draft_reply(
        conv_id="conv-hist-sec",
        customer_msg="Cho em hỏi chính sách hoàn tiền?",
        conversation_history=history,
        extra_secrets=[extra_secret],
    )

    assert len(mock_llm.calls) > 0
    prompt_str = str(mock_llm.calls[-1]["messages"])
    assert secret_key not in prompt_str
    assert extra_secret not in prompt_str
    assert "sk-***REDACTED***" in prompt_str
    assert "***REDACTED***" in prompt_str


@pytest.mark.asyncio
async def test_sub_threshold_chunks_do_not_leak_into_citations_or_prompt(mock_llm):
    """Verify chunks with score < 0.70 do not appear in reply.citations or prompt messages."""
    high_chunk = ChunkHit(
        chunk_id="chunk-valid",
        doc_id="doc-valid",
        doc_title="Valid Knowledge Doc",
        collection="policies",
        text="This is valid policy text that should be cited.",
        score=0.85,
        page=1,
    )
    sub_threshold_chunk = ChunkHit(
        chunk_id="chunk-sub",
        doc_id="doc-sub",
        doc_title="Sub Threshold Internal Draft",
        collection="default",
        text="Sub-threshold text that must NEVER leak into citations or prompt.",
        score=0.65,
        page=2,
    )
    retriever = MockRetriever(hits=[high_chunk, sub_threshold_chunk])
    agent = SupportAgent(retriever=retriever, llm=mock_llm)

    reply = await agent.draft_reply(
        conv_id="conv-sub-test",
        customer_msg="Hỗ trợ chính sách giúp tôi",
    )

    # 1. Citations must only contain valid_hits >= 0.70
    assert len(reply.citations) == 1
    assert reply.citations[0]["doc_title"] == "Valid Knowledge Doc"
    assert reply.citations[0]["score"] == 0.85

    # 2. Sub-threshold chunk must NOT appear in reply.citations
    for citation in reply.citations:
        assert citation["doc_title"] != "Sub Threshold Internal Draft"
        assert citation["score"] >= 0.70

    # 3. Sub-threshold chunk must NOT leak into the LLM prompt messages
    assert len(mock_llm.calls) > 0
    prompt_str = str(mock_llm.calls[-1]["messages"])
    assert "Sub Threshold Internal Draft" not in prompt_str
    assert "Sub-threshold text that must NEVER leak" not in prompt_str
    assert "Valid Knowledge Doc" in prompt_str

    # 4. Verify case where all chunks are below threshold
    all_sub_retriever = MockRetriever(hits=[sub_threshold_chunk])
    agent_sub = SupportAgent(retriever=all_sub_retriever, llm=mock_llm)
    reply_sub = await agent_sub.draft_reply(
        conv_id="conv-all-sub",
        customer_msg="Cho tôi hỏi thông tin?",
    )
    assert reply_sub.escalate_to_human is True
    assert reply_sub.confidence_score == 0.65
    assert len(reply_sub.citations) == 0
    prompt_str_sub = str(mock_llm.calls[-1]["messages"])
    assert "Sub Threshold Internal Draft" not in prompt_str_sub


@pytest.mark.asyncio
async def test_suggested_actions_secret_scrubbed(mock_retriever_high_score, mock_llm):
    """Verify suggested_actions are masked."""
    secret_term = "chuyên viên"
    agent = SupportAgent(retriever=mock_retriever_high_score, llm=mock_llm)

    # Escalated state includes "Chuyển chuyên viên hỗ trợ cấp cao"
    reply_escalated = await agent.draft_reply(
        conv_id="conv-act-esc",
        customer_msg="Tôi muốn kiện công ty",
        extra_secrets=[secret_term],
    )
    assert reply_escalated.escalate_to_human is True
    assert len(reply_escalated.suggested_actions) > 0
    assert any("***REDACTED***" in act for act in reply_escalated.suggested_actions)
    assert not any(secret_term in act for act in reply_escalated.suggested_actions)

    # Non-escalated state includes "Gửi hướng dẫn chi tiết"
    reply_normal = await agent.draft_reply(
        conv_id="conv-act-norm",
        customer_msg="Cho em hỏi chính sách hoàn tiền?",
        extra_secrets=["hướng dẫn"],
    )
    assert reply_normal.escalate_to_human is False
    assert any("***REDACTED***" in act for act in reply_normal.suggested_actions)
    assert not any("hướng dẫn" in act for act in reply_normal.suggested_actions)
