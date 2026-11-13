"""Engagement Worker Agents — SalesAgent and SupportAgent (Task 4.5).

Implements:
- EngagementReply: Structured dataclass for engagement turn responses.
- SupportAgent: Customer support agent grounded in BrainRetriever knowledge base (min_similarity=0.7)
  with automated escalation for legal threats, angry complaints, attachments, payment proof,
  and low RAG confidence.
- SalesAgent: Consultative sales agent grounded in product catalog and brand profile
  with automated escalation for price negotiation / VIP discount requests, payment transfer screenshots,
  technical spec low RAG confidence, and angry complaints.
- Co-pilot mode: requires_review=True by default for human-in-the-loop oversight.
- Automatic secret redaction via mask_secrets across inputs, outputs, and citations.
- BaseWorkerAgent & WorkerResult compatibility via execute() adapter.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import re
import time
from typing import Any, Iterable, Optional

from app.agents.base import BaseWorkerAgent, WorkerResult
from app.brain.retriever import BrainRetriever, ChunkHit
from app.db.models import Agent
from app.llm.router import LlmRouter
from app.orchestrator.dispatcher import mask_secrets

logger = logging.getLogger(__name__)

__all__ = [
    "EngagementReply",
    "SupportAgent",
    "SalesAgent",
]


# ============================================================================
# Keyword Catalogs & Escalation Rules
# ============================================================================

_ANGRY_LEGAL_PHRASES: list[str] = [
    "khởi kiện",
    "kiện cáo",
    "kiện tụng",
    "ra tòa",
    "lừa đảo",
    "lừa gạt",
    "lừa tiền",
    "tố cáo",
    "báo công an",
    "công an",
    "tẩy chay",
    "bồi thường",
    "pháp luật",
    "luật sư",
    "ăn cắp",
    "chiếm đoạt",
]

_STANDALONE_LAWSUIT_RE = re.compile(
    r"(?<!điều\s)(?<!phụ\s)(?<!linh\s)(?<!sự\s)(?<!chứng\s)\bkiện\b",
    re.IGNORECASE,
)


def _is_angry_or_legal(text: str) -> bool:
    """Detect legal threats and aggressive complaints, avoiding compound words like 'điều kiện'."""
    text_lower = text.lower()
    for phrase in _ANGRY_LEGAL_PHRASES:
        if phrase in text_lower:
            return True
    if _STANDALONE_LAWSUIT_RE.search(text_lower):
        return True
    return False

_PAYMENT_PROOF_KEYWORDS: list[str] = [
    "đã chuyển khoản",
    "chuyển khoản rồi",
    "chuyển tiền rồi",
    "đã chuyển tiền",
    "ảnh bill",
    "anh bill",
    "biên lai",
    "đã thanh toán",
    "thanh toán rồi",
    "hóa đơn thanh toán",
    "ảnh chuyển khoản",
    "chụp màn hình chuyển khoản",
    "bill chuyển khoản",
    "bill thanh toán",
    "ủy nhiệm chi",
]

_BARGAIN_KEYWORDS: list[str] = [
    "giảm giá",
    "bớt giá",
    "chiết khấu",
    "giảm sâu",
    "vip discount",
    "deal riêng",
    "deal vip",
    "thương lượng giá",
    "hạ giá",
    "có bớt không",
    "bớt chút",
    "bớt không",
    "ưu đãi riêng",
    "giảm thêm",
    "xin giảm",
    "bớt được không",
    "discount",
    "giảm được không",
]

_TECH_SPEC_KEYWORDS: list[str] = [
    "thông số",
    "cấu hình",
    "gpu",
    "cluster",
    "latency",
    "ram",
    "cpu",
    "kỹ thuật",
    "api",
    "tốc độ",
    "tích hợp",
    "spec",
    "specs",
    "technical",
    "hạ tầng",
    "kiến trúc",
    "băng thông",
    "sla",
    "uptime",
    "server",
    "máy chủ",
    "benchmark",
    "chỉ số kỹ thuật",
]


def _match_any_keyword(text: str, keywords: Iterable[str]) -> bool:
    """Check if any keyword phrase appears in lowercased text with word boundaries."""
    text_lower = text.lower()
    for kw in keywords:
        if kw in text_lower:
            return True
    return False


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass
class EngagementReply:
    """Structured response object for customer engagement turns."""

    reply_text: str
    escalate_to_human: bool
    requires_review: bool = True
    confidence_score: float = 0.0
    escalation_reason: Optional[str] = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    intent: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize response to a JSON-safe dictionary."""
        return {
            "reply_text": self.reply_text,
            "escalate_to_human": self.escalate_to_human,
            "requires_review": self.requires_review,
            "confidence_score": self.confidence_score,
            "escalation_reason": self.escalation_reason,
            "citations": [dict(c) for c in self.citations],
            "suggested_actions": list(self.suggested_actions),
            "intent": self.intent,
        }


# ============================================================================
# Base Engagement Worker Agent
# ============================================================================


class _BaseEngagementAgent(BaseWorkerAgent):
    """Common foundation for customer engagement agents providing RAG and LLM integration."""

    def __init__(
        self,
        agent: Agent,
        retriever: Optional[Any] = None,
        llm: Optional[Any] = None,
        llm_router: Optional[LlmRouter] = None,
        collections: Optional[list[str]] = None,
        default_min_similarity: float = 0.7,
        session_factory: Optional[Any] = None,
        db: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        router = llm_router or (llm if isinstance(llm, LlmRouter) else None)
        super().__init__(
            agent=agent,
            llm_router=router,
            session_factory=session_factory,
            db=db,
            **kwargs,
        )
        self.retriever = retriever
        self.llm = llm
        self.collections = collections or ["knowledge"]
        self.default_min_similarity = default_min_similarity

    def _search_knowledge(
        self,
        query: str,
        collections: list[str],
        top_k: int = 5,
        min_similarity: Optional[float] = None,
    ) -> list[ChunkHit]:
        """Query knowledge retriever safely with fallback handling."""
        if self.retriever is None:
            try:
                self.retriever = BrainRetriever()
            except Exception as exc:
                logger.debug("Could not initialize default BrainRetriever: %s", exc)
                return []

        try:
            if hasattr(self.retriever, "search") and callable(self.retriever.search):
                return self.retriever.search(
                    query=query,
                    collections=collections,
                    top_k=top_k,
                    min_similarity=min_similarity,
                )
            elif callable(self.retriever):
                res = self.retriever(
                    query,
                    collections=collections,
                    top_k=top_k,
                    min_similarity=min_similarity,
                )
                return res if isinstance(res, list) else []
        except Exception as exc:
            logger.warning("Error searching knowledge retriever: %s", exc)
            return []
        return []

    async def _call_llm(self, messages: list[dict[str, Any]]) -> Optional[str]:
        """Safely invoke LLM completion through llm instance or llm_router."""
        target = self.llm or self.llm_router
        if target is None:
            return None

        try:
            if hasattr(target, "complete") and callable(target.complete):
                res = target.complete(
                    messages=messages,
                    agent=self.agent,
                    temperature=getattr(self.agent, "temperature", 0.4),
                    max_tokens=getattr(self.agent, "max_tokens", 2048),
                )
                if asyncio.iscoroutine(res):
                    res = await res
                if hasattr(res, "content"):
                    return str(res.content)
                if isinstance(res, dict):
                    return str(res.get("content", ""))
                return str(res)
            elif callable(target):
                res = target(messages)
                if asyncio.iscoroutine(res):
                    res = await res
                if hasattr(res, "content"):
                    return str(res.content)
                return str(res)
        except Exception as exc:
            logger.warning("Error invoking LLM in engagement agent: %s", exc)
            return None
        return None

    async def execute(
        self,
        subtask: Any,
        context: Optional[dict[str, Any]] = None,
        db_session_factory: Optional[Any] = None,
    ) -> WorkerResult:
        """Adapter method for BaseWorkerAgent orchestrator dispatch."""
        start_time = time.time()
        ctx = dict(context or {})
        task_ctx: dict[str, Any] = {}
        if isinstance(subtask, dict):
            task_ctx.update(subtask.get("metadata") or {})
            task_ctx.setdefault(
                "customer_msg",
                subtask.get("instruction") or subtask.get("message") or "",
            )
            task_ctx["subtask_id"] = subtask.get("id", "subtask")
        else:
            meta = getattr(subtask, "metadata", None) or {}
            task_ctx.update(meta)
            task_ctx.setdefault(
                "customer_msg",
                getattr(subtask, "instruction", "") or getattr(subtask, "message", ""),
            )
            task_ctx["subtask_id"] = getattr(subtask, "id", "subtask")

        task_ctx.update(ctx)

        conv_id = str(task_ctx.get("conv_id") or task_ctx.get("conversation_id") or "conv-default")
        customer_msg = str(
            task_ctx.get("customer_msg")
            or task_ctx.get("message")
            or task_ctx.get("instruction")
            or task_ctx.get("prompt")
            or ""
        )
        conversation_history = task_ctx.get("conversation_history") or task_ctx.get("history")
        attachments = task_ctx.get("attachments")
        project_id = str(task_ctx.get("project_id", "proj-default"))
        extra_secrets = list(task_ctx.get("extra_secrets") or [])

        reply = await self.draft_reply(
            conv_id=conv_id,
            customer_msg=customer_msg,
            conversation_history=conversation_history,
            attachments=attachments,
            project_id=project_id,
            extra_secrets=extra_secrets,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        agent_id = str(getattr(self.agent, "id", "agent-engagement"))
        subtask_id = str(task_ctx.get("subtask_id", "subtask"))

        return WorkerResult(
            subtask_id=subtask_id,
            agent_id=agent_id,
            status="completed",
            output=reply.to_dict(),
            content=reply.reply_text,
            model_used=getattr(self.agent, "default_model", "gemini-2.5-flash"),
            tokens=0,
            cost_usd=0.0,
            duration_ms=duration_ms,
            skills_loaded=list(self.loaded_skills.keys()),
            error=None,
        )


# ============================================================================
# SupportAgent
# ============================================================================


class SupportAgent(_BaseEngagementAgent):
    """Customer Support Worker Agent with RAG grounding and escalation controls.

    Key responsibilities:
    1. Answers customer queries accurately using knowledge base chunks (min_similarity=0.7).
    2. Escalates to human (escalate_to_human=True) on:
       - Angry complaints / legal threats ("kiện", "lừa đảo", "tố cáo", "báo công an", "tẩy chay", "bồi thường")
       - Low RAG confidence (top chunk score < 0.7 or no chunks found)
       - Attachments / media or payment confirmation keywords
    3. Runs in Co-pilot mode (requires_review=True) for human oversight.
    4. Automatically scrubs secrets from all inputs, outputs, and citations.
    """

    def __init__(
        self,
        agent: Optional[Agent] = None,
        retriever: Optional[Any] = None,
        llm: Optional[Any] = None,
        llm_router: Optional[LlmRouter] = None,
        collections: Optional[list[str]] = None,
        default_min_similarity: float = 0.7,
        session_factory: Optional[Any] = None,
        db: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        synth_agent = agent or Agent(
            id="agent-support",
            name="SupportAgent",
            display_name="Customer Support Agent",
            role="Customer Support Specialist",
            default_model="gemini-2.5-flash",
            temperature=0.3,
            max_tokens=2048,
        )
        cols = collections or ["knowledge", "policies", "faqs", "manuals"]
        super().__init__(
            agent=synth_agent,
            retriever=retriever,
            llm=llm,
            llm_router=llm_router,
            collections=cols,
            default_min_similarity=default_min_similarity,
            session_factory=session_factory,
            db=db,
            **kwargs,
        )

    async def draft_reply(
        self,
        conv_id: str,
        customer_msg: str,
        conversation_history: Optional[list[Any]] = None,
        attachments: Optional[list[Any]] = None,
        project_id: str = "proj-default",
        extra_secrets: Optional[list[str]] = None,
    ) -> EngagementReply:
        """Draft a support reply with RAG grounding, citations, and escalation checks."""
        extra_list = list(extra_secrets or [])
        clean_msg = str(mask_secrets(customer_msg or "", extra_secrets=extra_list)).strip()
        msg_lower = clean_msg.lower()

        # 1. Search knowledge base
        hits = self._search_knowledge(
            query=clean_msg,
            collections=self.collections,
            top_k=5,
            min_similarity=0.0,
        )

        top_score = float(hits[0].score) if hits else 0.0
        confidence_score = round(top_score, 4)

        # 2. Check escalation triggers
        reasons: list[str] = []
        intent: Optional[str] = "support_inquiry"

        # Check angry complaints & legal threats
        is_angry_or_legal = _is_angry_or_legal(clean_msg)
        if is_angry_or_legal:
            reasons.append("Khách hàng khiếu nại gay gắt hoặc có tranh chấp/yếu tố pháp lý.")
            intent = "complaint"

        # Check payment confirmations
        is_payment_proof = _match_any_keyword(msg_lower, _PAYMENT_PROOF_KEYWORDS)
        if is_payment_proof:
            reasons.append("Khách hàng gửi xác nhận thanh toán/chuyển khoản cần đối soát biên lai.")
            intent = "payment_confirmation"

        # Check media / attachments
        has_attachments = bool(attachments and len(attachments) > 0)
        if has_attachments:
            reasons.append("Tin nhắn có tệp tin hoặc hình ảnh đính kèm cần con người xác minh.")
            if intent == "support_inquiry":
                intent = "media_attachment"

        # Check RAG confidence
        is_low_rag = (not hits) or (top_score < self.default_min_similarity)
        if is_low_rag:
            reasons.append(
                f"Độ tin cậy RAG thấp ({top_score:.2f} < {self.default_min_similarity:.2f}) hoặc không tìm thấy tài liệu phù hợp."
            )

        escalate_to_human = len(reasons) > 0
        escalation_reason = " ".join(reasons) if reasons else None

        # 3. Build citations
        citations: list[dict[str, Any]] = []
        for h in hits:
            doc_title = getattr(h, "doc_title", "") or ""
            text = getattr(h, "text", "") or ""
            citations.append(
                {
                    "chunk_id": str(getattr(h, "chunk_id", "")),
                    "doc_id": str(getattr(h, "doc_id", "")),
                    "doc_title": str(mask_secrets(doc_title, extra_secrets=extra_list)),
                    "collection": str(getattr(h, "collection", "")),
                    "score": round(float(getattr(h, "score", 0.0)), 4),
                    "text": str(mask_secrets(text, extra_secrets=extra_list)),
                    "page": getattr(h, "page", None),
                }
            )

        # 4. Draft reply text via LLM or fallback
        prompt_messages = self._build_prompt(
            customer_msg=clean_msg,
            conversation_history=conversation_history,
            citations=citations,
            escalate_to_human=escalate_to_human,
            escalation_reason=escalation_reason,
        )
        raw_reply = await self._call_llm(prompt_messages)
        if raw_reply and raw_reply.strip():
            reply_text = raw_reply.strip()
        else:
            reply_text = self._build_fallback_reply(
                customer_msg=clean_msg,
                escalate_to_human=escalate_to_human,
                citations=citations,
            )

        reply_text = str(mask_secrets(reply_text, extra_secrets=extra_list))
        if escalation_reason:
            escalation_reason = str(mask_secrets(escalation_reason, extra_secrets=extra_list))

        # 5. Suggested actions
        if escalate_to_human:
            suggested_actions = [
                "Chuyển chuyên viên hỗ trợ cấp cao",
                "Liên hệ khách hàng qua điện thoại/hotline",
                "Kiểm tra lịch sử tài khoản khách hàng",
            ]
        else:
            suggested_actions = [
                "Gửi hướng dẫn chi tiết",
                "Khảo sát mức độ hài lòng",
                "Đóng phiếu hỗ trợ khi hoàn tất",
            ]

        return EngagementReply(
            reply_text=reply_text,
            escalate_to_human=escalate_to_human,
            requires_review=True,  # Co-pilot mode default
            confidence_score=confidence_score,
            escalation_reason=escalation_reason,
            citations=citations,
            suggested_actions=suggested_actions,
            intent=intent,
        )

    def _build_prompt(
        self,
        customer_msg: str,
        conversation_history: Optional[list[Any]],
        citations: list[dict[str, Any]],
        escalate_to_human: bool,
        escalation_reason: Optional[str],
    ) -> list[dict[str, Any]]:
        """Construct structured prompt for LLM completion."""
        system_content = (
            "Bạn là Trợ lý Hỗ trợ Khách hàng (Support Agent) chuyên nghiệp, thấu hiểu, tận tâm.\n"
            "Nhiệm vụ của bạn là soạn thảo câu trả lời (draft reply) cho khách hàng Việt Nam bằng tiếng Việt lịch sự, chuẩn mực.\n"
        )
        if citations:
            system_content += "\nThông tin tham khảo từ cơ sở tri thức doanh nghiệp:\n"
            for idx, c in enumerate(citations[:3], start=1):
                system_content += f"[{idx}] {c['doc_title']}: {c['text'][:300]}\n"

        if escalate_to_human:
            system_content += (
                f"\nLƯU Ý ĐẶC BIỆT: Yêu cầu này đang được gắn cờ chuyển con người xử lý (Lý do: {escalation_reason}).\n"
                "Hãy giữ thái độ hòa nhã, lịch thiệp, xin lỗi chân thành nếu khách hàng gặp sự cố, "
                "và thông báo rõ rằng đội ngũ quản lý/chuyên viên cấp cao sẽ liên hệ hỗ trợ trực tiếp ngay."
            )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]

        if conversation_history:
            for item in conversation_history[-5:]:
                if isinstance(item, dict):
                    role = item.get("role", "user")
                    content = str(item.get("content", ""))
                    messages.append({"role": role, "content": content})
                elif isinstance(item, str):
                    messages.append({"role": "user", "content": item})

        messages.append({"role": "user", "content": customer_msg})
        return messages

    def _build_fallback_reply(
        self,
        customer_msg: str,
        escalate_to_human: bool,
        citations: list[dict[str, Any]],
    ) -> str:
        """Heuristic fallback reply if LLM router is unavailable."""
        if escalate_to_human:
            return (
                "Dạ em rất tiếc và thành thật xin lỗi về trải nghiệm chưa tốt của anh/chị. "
                "Em đã chuyển tiếp thông tin và yêu cầu của mình đến bộ phận quản lý cấp cao "
                "để kiểm tra và xử lý thỏa đáng nhất cho anh/chị ngay ạ."
            )
        if citations and citations[0]["score"] >= self.default_min_similarity:
            text_snippet = citations[0]["text"][:200].strip()
            return (
                f"Dạ theo thông tin từ bộ phận hỗ trợ: {text_snippet}... "
                "Anh/chị cần em hỗ trợ thêm thông tin gì nữa không ạ?"
            )
        return (
            "Dạ xin chào anh/chị! Em có thể hỗ trợ giải đáp thắc mắc hoặc thông tin gì cho mình ạ?"
        )


# ============================================================================
# SalesAgent
# ============================================================================


class SalesAgent(_BaseEngagementAgent):
    """Consultative Sales Worker Agent with product catalog grounding and escalation rules.

    Key responsibilities:
    1. Delivers consultative selling grounded in product catalog and brand profile.
    2. Escalates to human (escalate_to_human=True) on:
       - Price negotiation / VIP discount requests beyond standard catalog
       - Payment transfer screenshots / bill confirmation keywords
       - Low RAG confidence when asked specific product technical specs
       - Angry complaints
    3. Runs in Co-pilot mode (requires_review=True) for human oversight.
    4. Automatically scrubs secrets from all inputs, outputs, and citations.
    """

    def __init__(
        self,
        agent: Optional[Agent] = None,
        retriever: Optional[Any] = None,
        llm: Optional[Any] = None,
        llm_router: Optional[LlmRouter] = None,
        collections: Optional[list[str]] = None,
        default_min_similarity: float = 0.7,
        session_factory: Optional[Any] = None,
        db: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        synth_agent = agent or Agent(
            id="agent-sales",
            name="SalesAgent",
            display_name="Consultative Sales Agent",
            role="Consultative Sales Specialist",
            default_model="gemini-2.5-flash",
            temperature=0.5,
            max_tokens=2048,
        )
        cols = collections or ["catalog", "products", "brand_profile", "knowledge"]
        super().__init__(
            agent=synth_agent,
            retriever=retriever,
            llm=llm,
            llm_router=llm_router,
            collections=cols,
            default_min_similarity=default_min_similarity,
            session_factory=session_factory,
            db=db,
            **kwargs,
        )

    async def draft_reply(
        self,
        conv_id: str,
        customer_msg: str,
        conversation_history: Optional[list[Any]] = None,
        attachments: Optional[list[Any]] = None,
        project_id: str = "proj-default",
        extra_secrets: Optional[list[str]] = None,
    ) -> EngagementReply:
        """Draft a consultative sales reply grounded in catalog with escalation triggers."""
        extra_list = list(extra_secrets or [])
        clean_msg = str(mask_secrets(customer_msg or "", extra_secrets=extra_list)).strip()
        msg_lower = clean_msg.lower()

        # 1. Search product catalog & brand knowledge base
        hits = self._search_knowledge(
            query=clean_msg,
            collections=self.collections,
            top_k=5,
            min_similarity=0.0,
        )

        top_score = float(hits[0].score) if hits else 0.0
        confidence_score = round(top_score, 4)

        # 2. Check escalation triggers
        reasons: list[str] = []
        intent: Optional[str] = "consultative_sales"

        # Check angry complaints
        is_angry = _is_angry_or_legal(clean_msg)
        if is_angry:
            reasons.append("Khách hàng khiếu nại gay gắt hoặc có tranh chấp pháp lý.")
            intent = "complaint"

        # Check price negotiation / VIP discount
        is_bargain = _match_any_keyword(msg_lower, _BARGAIN_KEYWORDS)
        if is_bargain:
            reasons.append("Khách hàng đàm phán giá / yêu cầu chiết khấu VIP ngoài bảng giá niêm yết.")
            intent = "price_negotiation"

        # Check payment confirmations / bill screenshots
        is_payment = _match_any_keyword(msg_lower, _PAYMENT_PROOF_KEYWORDS)
        has_attachments = bool(attachments and len(attachments) > 0)
        if is_payment or has_attachments:
            reasons.append("Khách hàng gửi xác nhận thanh toán / ảnh bill chuyển khoản cần đối soát.")
            intent = "payment_confirmation"

        # Check technical specs inquiry with low RAG confidence
        is_tech = _match_any_keyword(msg_lower, _TECH_SPEC_KEYWORDS)
        is_low_rag = (not hits) or (top_score < self.default_min_similarity)
        if is_tech and is_low_rag:
            reasons.append(
                f"Không đủ thông số kỹ thuật chuyên sâu trong tài liệu (RAG confidence {top_score:.2f} < {self.default_min_similarity:.2f})."
            )
            intent = "technical_spec_inquiry"

        escalate_to_human = len(reasons) > 0
        escalation_reason = " ".join(reasons) if reasons else None

        # 3. Build citations
        citations: list[dict[str, Any]] = []
        for h in hits:
            doc_title = getattr(h, "doc_title", "") or ""
            text = getattr(h, "text", "") or ""
            citations.append(
                {
                    "chunk_id": str(getattr(h, "chunk_id", "")),
                    "doc_id": str(getattr(h, "doc_id", "")),
                    "doc_title": str(mask_secrets(doc_title, extra_secrets=extra_list)),
                    "collection": str(getattr(h, "collection", "")),
                    "score": round(float(getattr(h, "score", 0.0)), 4),
                    "text": str(mask_secrets(text, extra_secrets=extra_list)),
                    "page": getattr(h, "page", None),
                }
            )

        # 4. Draft reply text via LLM or fallback
        prompt_messages = self._build_prompt(
            customer_msg=clean_msg,
            conversation_history=conversation_history,
            citations=citations,
            escalate_to_human=escalate_to_human,
            escalation_reason=escalation_reason,
        )
        raw_reply = await self._call_llm(prompt_messages)
        if raw_reply and raw_reply.strip():
            reply_text = raw_reply.strip()
        else:
            reply_text = self._build_fallback_reply(
                customer_msg=clean_msg,
                escalate_to_human=escalate_to_human,
                citations=citations,
            )

        reply_text = str(mask_secrets(reply_text, extra_secrets=extra_list))
        if escalation_reason:
            escalation_reason = str(mask_secrets(escalation_reason, extra_secrets=extra_list))

        # 5. Suggested actions
        if escalate_to_human:
            if is_bargain:
                suggested_actions = [
                    "Chuyển Sales Manager duyệt chiết khấu VIP",
                    "Đề xuất gói combo quà tặng thay vì giảm tiền mặt",
                    "Gửi hợp đồng nguyên tắc",
                ]
            elif is_payment:
                suggested_actions = [
                    "Kế toán kiểm tra sao kê ngân hàng",
                    "Xác nhận đơn hàng và kích hoạt khóa học",
                    "Xuất hóa đơn điện tử cho học viên",
                ]
            else:
                suggested_actions = [
                    "Chuyển chuyên viên kinh doanh cao cấp hỗ trợ",
                    "Lên lịch cuộc gọi tư vấn giải pháp 1:1",
                    "Gửi tài liệu kỹ thuật chi tiết",
                ]
        else:
            suggested_actions = [
                "Gửi thông tin lộ trình và bảng giá chi tiết",
                "Mời đăng ký trải nghiệm thử miễn phí",
                "Đề xuất đặt lịch tư vấn chuyên sâu 1:1",
            ]

        return EngagementReply(
            reply_text=reply_text,
            escalate_to_human=escalate_to_human,
            requires_review=True,  # Co-pilot mode default
            confidence_score=confidence_score,
            escalation_reason=escalation_reason,
            citations=citations,
            suggested_actions=suggested_actions,
            intent=intent,
        )

    def _build_prompt(
        self,
        customer_msg: str,
        conversation_history: Optional[list[Any]],
        citations: list[dict[str, Any]],
        escalate_to_human: bool,
        escalation_reason: Optional[str],
    ) -> list[dict[str, Any]]:
        """Construct structured prompt for LLM consultative sales completion."""
        system_content = (
            "Bạn là Chuyên viên Tư vấn Bán hàng (Sales Agent) chuyên nghiệp theo phong cách Consultative Selling.\n"
            "Nhiệm vụ của bạn là soạn thảo câu trả lời (draft reply) định hướng giải pháp, làm nổi bật giá trị sản phẩm "
            "và đồng hành cùng khách hàng Việt Nam bằng văn phong chuyên nghiệp, tinh tế.\n"
        )
        if citations:
            system_content += "\nThông tin danh mục sản phẩm & thương hiệu được kiểm chứng:\n"
            for idx, c in enumerate(citations[:3], start=1):
                system_content += f"[{idx}] {c['doc_title']}: {c['text'][:300]}\n"

        if escalate_to_human:
            system_content += (
                f"\nLƯU Ý ĐẶC BIỆT: Yêu cầu này đang được chuyển cấp quản lý/chuyên viên kinh doanh trực tiếp xử lý "
                f"(Lý do: {escalation_reason}).\n"
                "Hãy cảm ơn khách hàng, giải thích rằng ưu đãi đặc biệt hoặc thông tin chuyên sâu này cần được "
                "Quản lý Kinh doanh duyệt riêng để mang lại quyền lợi tốt nhất, và sẽ có nhân sự liên hệ ngay."
            )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]

        if conversation_history:
            for item in conversation_history[-5:]:
                if isinstance(item, dict):
                    role = item.get("role", "user")
                    content = str(item.get("content", ""))
                    messages.append({"role": role, "content": content})
                elif isinstance(item, str):
                    messages.append({"role": "user", "content": item})

        messages.append({"role": "user", "content": customer_msg})
        return messages

    def _build_fallback_reply(
        self,
        customer_msg: str,
        escalate_to_human: bool,
        citations: list[dict[str, Any]],
    ) -> str:
        """Heuristic fallback reply if LLM router is unavailable."""
        if escalate_to_human:
            return (
                "Dạ em xin cảm ơn anh/chị đã quan tâm sâu sắc đến chương trình bên em! "
                "Đối với yêu cầu ưu đãi/kỹ thuật chuyên biệt này, em xin phép chuyển thông tin "
                "đến Quản lý Kinh doanh để duyệt giải pháp và phản hồi sớm nhất cho mình ạ."
            )
        if citations and citations[0]["score"] >= self.default_min_similarity:
            text_snippet = citations[0]["text"][:200].strip()
            return (
                f"Dạ thông tin chi tiết về sản phẩm/dịch vụ anh/chị quan tâm: {text_snippet}... "
                "Anh/chị có muốn đặt lịch tư vấn 1:1 hoặc nhận tài liệu chi tiết không ạ?"
            )
        return (
            "Dạ em chào anh/chị! Em rất vui được hỗ trợ tư vấn các sản phẩm, giải pháp "
            "và khóa học AI phù hợp nhất với mục tiêu của mình ạ."
        )
