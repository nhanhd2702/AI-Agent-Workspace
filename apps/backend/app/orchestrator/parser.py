"""Natural Language Task Input & Intent Parser for Master Commander (F01.1).

Validates prompt inputs, extracts URLs and @Agent mentions, classifies primary task_type,
extracts domain entities, and maintains a 50-entry prompt history for UI autocomplete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Optional


class PromptValidationError(ValueError):
    """Raised when prompt text or attachments violate validation constraints."""
    pass


@dataclass
class ParsedIntent:
    """Structured representation of parsed user command."""

    raw_prompt: str
    cleaned_prompt: str
    task_type: str
    intent: str
    mentioned_agents: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    attachment_ids: list[str] = field(default_factory=list)
    entities: dict[str, Any] = field(default_factory=dict)
    urgency: str = "normal"


# 8 Supported primary task types according to BA spec F01.1 / F01.2
TASK_TYPES = [
    "content_research",
    "copywriting",
    "image_design",
    "video_edit",
    "funnel_strategy",
    "landing_page",
    "sales_chat",
    "general",
]

# Mapping from canonical or lower-case agent names to task type affinities
AGENT_TASK_AFFINITIES: dict[str, str] = {
    "deepresearcher": "content_research",
    "productanalyst": "content_research",
    "contentwriter": "copywriting",
    "imagestudio": "image_design",
    "videoeditor": "video_edit",
    "funnelsagent": "funnel_strategy",
    "growthadvisor": "funnel_strategy",
    "uidesigner": "landing_page",
    "salesagent": "sales_chat",
    "customersupportagent": "sales_chat",
}

# Weighted keyword signals (Vietnamese and English) for classifying task_type
TASK_KEYWORD_PATTERNS: dict[str, list[tuple[str, int]]] = {
    "content_research": [
        ("nghiên cứu", 6),
        ("research", 6),
        ("đối thủ", 5),
        ("competitor", 5),
        ("thị trường", 4),
        ("market", 4),
        ("khảo sát", 4),
        ("survey", 4),
        ("phân tích kênh", 6),
        ("channel analysis", 6),
        ("youtube", 4),
        ("xu hướng", 5),
        ("trending", 5),
        ("trend", 4),
        ("scrape", 6),
        ("crawl", 6),
        ("benchmark", 5),
        ("thu thập", 4),
        ("views", 3),
        ("phân tích hook", 5),
    ],
    "copywriting": [
        ("viết kịch bản", 8),
        ("kịch bản video", 7),
        ("kịch bản", 6),
        ("script", 6),
        ("bài viết", 6),
        ("article", 5),
        ("bài đăng", 6),
        ("post", 4),
        ("soạn", 4),
        ("draft", 4),
        ("copywriting", 8),
        ("copy", 4),
        ("caption", 6),
        ("tiêu đề", 5),
        ("headline", 6),
        ("newsletter", 7),
        ("email copy", 7),
        ("viết", 4),
        ("nội dung", 3),
    ],
    "image_design": [
        ("thiết kế ảnh", 8),
        ("banner", 7),
        ("poster", 7),
        ("thumbnail", 7),
        ("hình ảnh", 5),
        ("ảnh", 4),
        ("image", 4),
        ("infographic", 8),
        ("logo", 7),
        ("visual", 5),
        ("svg", 6),
        ("canvas", 5),
        ("graphic", 6),
        ("render ảnh", 7),
        ("thiết kế", 3),
    ],
    "video_edit": [
        ("dựng video", 8),
        ("edit video", 8),
        ("cắt ghép", 7),
        ("clips", 6),
        ("clip", 5),
        ("reel", 6),
        ("reels", 6),
        ("tiktok", 4),
        ("shorts", 5),
        ("ffmpeg", 8),
        ("timeline", 6),
        ("pacing", 7),
        ("storyboard", 6),
        ("render video", 8),
        ("video", 3),
    ],
    "funnel_strategy": [
        ("phễu bán hàng", 8),
        ("chiến lược phễu", 8),
        ("phễu", 6),
        ("funnel", 7),
        ("chiến lược", 5),
        ("strategy", 5),
        ("tỷ lệ chuyển đổi", 7),
        ("conversion", 6),
        ("lead magnet", 8),
        ("upsell", 7),
        ("downsell", 7),
        ("pricing", 6),
        ("định giá", 6),
        ("tăng trưởng", 5),
        ("growth", 5),
    ],
    "landing_page": [
        ("landing page", 9),
        ("trang đích", 8),
        ("giao diện", 5),
        ("ui", 4),
        ("ux", 4),
        ("html template", 7),
        ("template", 4),
        ("responsive", 6),
        ("website", 5),
        ("web page", 5),
        ("wireframe", 7),
        ("mockup", 6),
    ],
    "sales_chat": [
        ("tư vấn bán hàng", 8),
        ("bán hàng", 5),
        ("chốt đơn", 7),
        ("tư vấn", 5),
        ("sale", 4),
        ("sales", 4),
        ("chăm sóc khách hàng", 7),
        ("cskh", 6),
        ("support", 4),
        ("xử lý từ chối", 8),
        ("objection", 7),
        ("kịch bản tư vấn", 7),
        ("kịch bản chat", 7),
        ("tin nhắn tư vấn", 7),
        ("zalo", 4),
        ("inbox", 4),
        ("customer support", 7),
    ],
}

URL_REGEX = re.compile(r"https?://[^\s<>\"'{}|\\^`\[\]]+", re.IGNORECASE)
MENTION_REGEX = re.compile(r"(?<!\w)@([a-zA-Z0-9_-]+)")
COUNT_REGEX = re.compile(
    r"\b(\d+)\s*(?:video|bài|ý tưởng|ideas|posts|items|kênh|channels|trang|pages)\b",
    re.IGNORECASE,
)
URGENT_REGEX = re.compile(
    r"\b(gấp|khẩn cấp|urgent|asap|ngay lập tức|hỏa tốc)\b",
    re.IGNORECASE,
)


class TaskParser:
    """Parser and entity extractor for natural language task prompts."""

    def __init__(
        self,
        history_file: Optional[Path | str] = None,
        max_history: int = 50,
    ) -> None:
        self.history_file = Path(history_file).resolve() if history_file else None
        self.max_history = max_history
        self._history: list[str] = []
        self._load_history()

    def _load_history(self) -> None:
        """Loads prompt history from persistent JSON file if available."""
        if self.history_file and self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._history = [str(item).strip() for item in data if item][: self.max_history]
            except Exception:
                self._history = []

    def _save_history(self) -> None:
        """Saves prompt history to persistent JSON file atomically."""
        if self.history_file:
            try:
                self.history_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.history_file, "w", encoding="utf-8") as f:
                    json.dump(self._history, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def record_prompt(self, prompt: str) -> None:
        """Records a valid prompt into recent history (MRU order, max 50)."""
        clean = prompt.strip()
        if not clean:
            return
        if clean in self._history:
            self._history.remove(clean)
        self._history.insert(0, clean)
        if len(self._history) > self.max_history:
            self._history = self._history[: self.max_history]
        self._save_history()

    def get_history(self, query: Optional[str] = None, limit: int = 50) -> list[str]:
        """Returns recent prompts, optionally filtered by search substring."""
        if not query:
            return self._history[:limit]
        q = query.strip().lower()
        return [p for p in self._history if q in p.lower()][:limit]

    def parse(
        self,
        prompt_text: str,
        attachment_ids: Optional[list[str]] = None,
        known_agents: Optional[list[str]] = None,
        record_history: bool = True,
    ) -> ParsedIntent:
        """Validates and parses natural language prompt into ParsedIntent.

        Args:
            prompt_text: Natural language user instruction.
            attachment_ids: List of attached file IDs or paths (max 10).
            known_agents: Available agent names for mention resolution.
            record_history: If True, adds prompt to persistent autocomplete history.

        Returns:
            ParsedIntent with validated task_type, entities, and canonical mentions.

        Raises:
            PromptValidationError: If prompt is empty, >2000 chars, or attachments >10.
        """
        # 1. Validation
        if not prompt_text or not prompt_text.strip():
            raise PromptValidationError("Prompt cannot be empty or whitespace only")

        clean_prompt = prompt_text.strip()
        if len(clean_prompt) > 2000:
            raise PromptValidationError(
                f"Prompt length ({len(clean_prompt)}) exceeds maximum limit of 2000 characters"
            )

        attachments = list(attachment_ids or [])
        if len(attachments) > 10:
            raise PromptValidationError(
                f"Attachment count ({len(attachments)}) exceeds maximum limit of 10 files"
            )

        # 2. Extract URLs and clean them from trailing punctuation
        raw_urls = URL_REGEX.findall(clean_prompt)
        urls: list[str] = []
        for u in raw_urls:
            cleaned_url = u.rstrip(".,;:!?)'\"")
            if cleaned_url and cleaned_url not in urls:
                urls.append(cleaned_url)

        # 3. Strip URLs before mention extraction so YouTube/X @handles are not mistaken for agents
        text_without_urls = URL_REGEX.sub(" ", clean_prompt)

        # 4. Extract @Agent mentions and match case-insensitively against known_agents
        raw_mentions = MENTION_REGEX.findall(text_without_urls)
        mentioned_agents: list[str] = []

        canonical_lookup: dict[str, str] = {}
        if known_agents:
            canonical_lookup = {agent.lower(): agent for agent in known_agents}

        for m in raw_mentions:
            m_lower = m.lower()
            if canonical_lookup and m_lower in canonical_lookup:
                canonical = canonical_lookup[m_lower]
                if canonical not in mentioned_agents:
                    mentioned_agents.append(canonical)

        # 5. Classify primary task_type
        task_type = self._classify_task_type(clean_prompt, mentioned_agents)

        # 6. Extract domain entities
        entities = self._extract_entities(clean_prompt, urls, attachments)

        # 7. Check urgency
        urgency = "urgent" if URGENT_REGEX.search(clean_prompt) else "normal"

        # 8. Formulate intent slug
        intent = task_type
        if entities.get("output_format") == "html_app":
            intent = f"{task_type}_html_report"

        # 9. Record history
        if record_history:
            self.record_prompt(clean_prompt)

        return ParsedIntent(
            raw_prompt=clean_prompt,
            cleaned_prompt=text_without_urls.strip(),
            task_type=task_type,
            intent=intent,
            mentioned_agents=mentioned_agents,
            urls=urls,
            attachment_ids=attachments,
            entities=entities,
            urgency=urgency,
        )

    def _classify_task_type(self, prompt: str, mentioned_agents: list[str]) -> str:
        """Scores and classifies primary task_type across the 8 standard types."""
        prompt_lower = prompt.lower()
        scores: dict[str, int] = {t: 0 for t in TASK_TYPES}

        # Boost from mentioned agents
        for agent in mentioned_agents:
            affinity = AGENT_TASK_AFFINITIES.get(agent.lower())
            if affinity and affinity in scores:
                scores[affinity] += 12

        # Keyword matching
        for t_type, patterns in TASK_KEYWORD_PATTERNS.items():
            for kw, weight in patterns:
                if kw in prompt_lower:
                    scores[t_type] += weight

        # Pick highest scoring type
        best_type = "general"
        highest_score = 0
        for t_type, score in scores.items():
            if score > highest_score:
                highest_score = score
                best_type = t_type

        return best_type

    def _extract_entities(
        self,
        prompt: str,
        urls: list[str],
        attachments: list[str],
    ) -> dict[str, Any]:
        """Extracts numerical counts, output formats, and files into entity dict."""
        entities: dict[str, Any] = {
            "urls": urls,
            "files": attachments,
            "target_count": None,
            "output_format": None,
        }

        # Count match (e.g. "5 ý tưởng", "3 video")
        count_match = COUNT_REGEX.search(prompt)
        if count_match:
            try:
                entities["target_count"] = int(count_match.group(1))
            except ValueError:
                pass

        # Format detection
        prompt_lower = prompt.lower()
        if any(w in prompt_lower for w in ["html", "app html", "báo cáo html", "web app"]):
            entities["output_format"] = "html_app"
        elif any(w in prompt_lower for w in ["dựng video", "edit video", "mp4", "reel", "tiktok"]):
            entities["output_format"] = "video"
        elif any(w in prompt_lower for w in ["banner", "poster", "thumbnail", "thiết kế ảnh", "svg"]):
            entities["output_format"] = "image"
        elif any(w in prompt_lower for w in ["kịch bản", "bài viết", "newsletter", "copy"]):
            entities["output_format"] = "text_script"

        return entities
