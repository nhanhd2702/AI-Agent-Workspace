"""Storyboard Data Models, Builder, and Pacing Linter (Task 3.5).

Implements:
- Scene: individual scene timeline segment with start, end, overlay text, effect, and visual notes.
- Storyboard: sequence of scenes, total duration, and lint warnings.
- StoryboardBuilder:
  - lint_pacing(scenes): flags back-to-back heavy effects (containing 'sát nhau')
    and > 20s stretches without major effects (containing '20 giây').
  - build_from_transcript(transcript_segments, total_duration): strictly preserves spoken dialogue.
  - to_markdown(scenes, warnings, total_duration): generates readable Markdown breakdown.
  - to_dict(scenes, warnings, total_duration): serializes to dictionary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Optional

__all__ = [
    "HEAVY_EFFECTS",
    "Scene",
    "Storyboard",
    "StoryboardBuilder",
]

HEAVY_EFFECT_PREFIX = "major_"
HEAVY_EFFECTS: frozenset[str] = frozenset(
    {
        "major_zoom",
        "major_split",
        "major_shake",
        "major_glitch",
        "heavy",
        "zoom_in_fast",
        "split_screen_flash",
        "shake",
        "glitch",
    }
)


@dataclass
class Scene:
    """Individual scene segment within a video storyboard."""

    scene_id: str
    start: float
    end: float
    effect: str = "none"
    overlay_text: str = ""
    visual_notes: str = ""
    transition: str = "cut"

    @property
    def duration(self) -> float:
        """Computed duration of the scene in seconds."""
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        """Convert Scene to JSON-serializable dictionary."""
        return {
            "scene_id": self.scene_id,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
            "effect": self.effect,
            "overlay_text": self.overlay_text,
            "visual_notes": self.visual_notes,
            "transition": self.transition,
        }


@dataclass
class Storyboard:
    """Complete video storyboard with pacing evaluation."""

    scenes: list[Scene] = field(default_factory=list)
    total_duration: float = 0.0
    pacing_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenes": [s.to_dict() for s in self.scenes],
            "total_duration": round(self.total_duration, 3),
            "scene_count": len(self.scenes),
            "pacing_warnings": list(self.pacing_warnings),
        }


class StoryboardBuilder:
    """Builder and linter for video storyboards and pacing."""

    @staticmethod
    def is_heavy_effect(effect: Optional[str]) -> bool:
        """Determine if an effect is classified as a heavy/major effect."""
        if not effect:
            return False
        eff = str(effect).strip().lower()
        return eff.startswith(HEAVY_EFFECT_PREFIX) or eff in HEAVY_EFFECTS

    @classmethod
    def lint_pacing(cls, scenes: list[Scene]) -> list[str]:
        """Lint storyboard pacing against engagement standards.

        Rules:
        1. Flags adjacent heavy effects (> 1 back-to-back). Warning MUST contain 'sát nhau'.
        2. Flags dry spans (> 20s continuous span without any major effect). Warning MUST contain '20 giây'.
        """
        warnings: list[str] = []
        if not scenes:
            return warnings

        # Rule 1: Flags adjacent heavy effects (> 1 back-to-back)
        for i in range(len(scenes) - 1):
            s1 = scenes[i]
            s2 = scenes[i + 1]
            if cls.is_heavy_effect(s1.effect) and cls.is_heavy_effect(s2.effect):
                warnings.append(
                    f"2 hiệu ứng mạnh diễn ra sát nhau ở cảnh {s1.scene_id} ({s1.effect}) "
                    f"và cảnh {s2.scene_id} ({s2.effect}). Cần giãn nhịp độ hiệu ứng mạnh."
                )

        # Rule 2: Flags dry spans (> 20s continuous span without any major effect)
        sorted_scenes = sorted(scenes, key=lambda s: s.start)
        span_start: Optional[float] = None
        span_end: Optional[float] = None

        for scene in sorted_scenes:
            if not cls.is_heavy_effect(scene.effect):
                if span_start is None:
                    span_start = scene.start
                span_end = max(span_end if span_end is not None else scene.end, scene.end)
            else:
                if span_start is not None and span_end is not None:
                    span_len = span_end - span_start
                    if span_len > 20.0:
                        warnings.append(
                            f"Đoạn video kéo dài hơn 20 giây (từ {span_start:.1f}s đến {span_end:.1f}s, "
                            f"tổng {span_len:.1f}s) không có điểm nhấn hiệu ứng nào."
                        )
                span_start = None
                span_end = None

        if span_start is not None and span_end is not None:
            span_len = span_end - span_start
            if span_len > 20.0:
                warnings.append(
                    f"Đoạn video kéo dài hơn 20 giây (từ {span_start:.1f}s đến {span_end:.1f}s, "
                    f"tổng {span_len:.1f}s) không có điểm nhấn hiệu ứng nào."
                )

        return warnings

    @classmethod
    def build_from_transcript(
        cls,
        transcript_segments: list[dict[str, Any]],
        total_duration: Optional[float] = None,
    ) -> list[Scene]:
        """Build storyboard scenes strictly constrained to spoken transcript text.

        Preserves exact timestamps and spoken dialogue without fabrication.
        """
        scenes: list[Scene] = []
        for i, seg in enumerate(transcript_segments):
            scene_id = str(seg.get("scene_id") or seg.get("id") or (i + 1))
            start = float(seg.get("start", 0.0))

            if seg.get("end") is not None:
                end = float(seg["end"])
            elif seg.get("duration") is not None:
                end = start + float(seg["duration"])
            elif i + 1 < len(transcript_segments) and transcript_segments[i + 1].get("start") is not None:
                end = float(transcript_segments[i + 1]["start"])
            elif total_duration is not None and total_duration > start:
                end = float(total_duration)
            else:
                end = start + 3.0

            overlay_text = str(
                seg.get("text") if seg.get("text") is not None else seg.get("overlay_text", "")
            ).strip()
            effect = str(seg.get("effect", "none")).strip()
            visual_notes = str(seg.get("visual_notes", "")).strip()
            transition = str(seg.get("transition", "cut")).strip()

            scenes.append(
                Scene(
                    scene_id=scene_id,
                    start=start,
                    end=end,
                    effect=effect or "none",
                    overlay_text=overlay_text,
                    visual_notes=visual_notes,
                    transition=transition or "cut",
                )
            )

        return scenes

    @classmethod
    def build(
        cls,
        transcript_segments: list[dict[str, Any]],
        total_duration: Optional[float] = None,
    ) -> Storyboard:
        """Construct a complete Storyboard with lint warnings."""
        scenes = cls.build_from_transcript(transcript_segments, total_duration=total_duration)
        calc_total = max([s.end for s in scenes], default=(total_duration or 0.0))
        if total_duration is not None and total_duration > calc_total:
            calc_total = total_duration
        warnings = cls.lint_pacing(scenes)
        return Storyboard(
            scenes=scenes,
            total_duration=calc_total,
            pacing_warnings=warnings,
        )

    @classmethod
    def to_markdown(
        cls,
        scenes: list[Scene],
        warnings: list[str],
        total_duration: Optional[float] = None,
    ) -> str:
        """Render storyboard and pacing review to a formatted Markdown report."""
        tot = total_duration if total_duration is not None else max([s.end for s in scenes], default=0.0)
        lines: list[str] = [
            "# Kịch bản phân cảnh (Storyboard)",
            "",
            f"- **Tổng thời lượng**: {tot:.1f}s",
            f"- **Số phân cảnh**: {len(scenes)}",
            "",
            "## Cảnh báo nhịp độ (Pacing Linter)",
        ]

        if warnings:
            for w in warnings:
                lines.append(f"- ⚠️ {w}")
        else:
            lines.append("- ✅ Nhịp độ video hài hòa, không phát hiện lỗi pacing.")

        lines.extend([
            "",
            "## Danh sách phân cảnh chi tiết",
            "",
            "| Cảnh | Bắt đầu | Kết thúc | Thời lượng | Hiệu ứng | Chuyển cảnh | Phụ đề / Lời thoại | Ghi chú hình ảnh |",
            "|------|---------|----------|------------|----------|-------------|--------------------|-------------------|",
        ])

        for s in scenes:
            txt = s.overlay_text.replace("|", "\\|").replace("\n", " ")
            notes = s.visual_notes.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {s.scene_id} | {s.start:.1f}s | {s.end:.1f}s | {s.duration:.1f}s | "
                f"`{s.effect}` | `{s.transition}` | {txt} | {notes} |"
            )

        lines.append("")
        return "\n".join(lines)

    @classmethod
    def to_dict(
        cls,
        scenes: list[Scene],
        warnings: list[str],
        total_duration: Optional[float] = None,
    ) -> dict[str, Any]:
        tot = total_duration if total_duration is not None else max([s.end for s in scenes], default=0.0)
        return {
            "scenes": [s.to_dict() for s in scenes],
            "total_duration": round(tot, 3),
            "scene_count": len(scenes),
            "pacing_warnings": list(warnings),
        }
