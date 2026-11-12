"""Tests for VideoEditorAgent and Pacing Linter (Task 3.5).

Verifies:
1. Exact requirement: test_pacing_linter_flags_adjacent_heavy_effects_and_20s_dry_spans.
2. StoryboardBuilder.build_from_transcript strictly preserves exact dialogue and timestamps.
3. ffprobe media inspection via ShellExecutor.
4. HIL Storyboard Review Gate suspension (status='waiting_review', note, structured_data, artifacts).
5. Video rendering when approved=True via ffmpeg.
6. WorkerResult compatibility when invoked via orchestrator execute(subtask, context).
7. Secret masking across inputs, storyboard artifacts, and structured data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
import pytest

from app.agents.base import WorkerResult
from app.agents.content import AgentResult, VideoEditorAgent
from app.artifacts.storyboard import Scene, Storyboard, StoryboardBuilder
from app.mcp.shell_server import ShellExecutor, ShellResult


class MockShellExecutor:
    """Mock ShellExecutor for testing ffprobe and ffmpeg calls without OS dependencies."""

    def __init__(self, workspace_root: Optional[Path] = None) -> None:
        self.workspace_root = workspace_root or Path.cwd()
        self.calls: list[dict[str, Any]] = []
        self.ffprobe_output: dict[str, Any] = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                    "duration": "28.500000",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "duration": "28.500000",
                },
            ],
            "format": {
                "duration": "28.500000",
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                "size": "5242880",
            },
        }

    async def run(
        self,
        executable: str,
        args: list[str],
        task_workspace: Path,
        timeout_s: Optional[float] = None,
        *,
        raise_on_timeout: bool = True,
    ) -> ShellResult:
        self.calls.append({
            "executable": executable,
            "args": list(args),
            "task_workspace": task_workspace,
        })
        norm_exec = executable.lower()
        if norm_exec == "ffprobe":
            return ShellResult(
                executable="ffprobe",
                args=list(args),
                returncode=0,
                stdout=json.dumps(self.ffprobe_output),
                stderr="",
                duration_ms=15,
            )
        elif norm_exec == "ffmpeg":
            # Find output file argument (typically the last argument)
            out_arg = args[-1]
            out_path = task_workspace / out_arg if not Path(out_arg).is_absolute() else Path(out_arg)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Create dummy mp4 file
            out_path.write_bytes(b"\x00\x00\x00 ftypisom\x00\x00\x02\x00isomiso2avc1mp41")
            return ShellResult(
                executable="ffmpeg",
                args=list(args),
                returncode=0,
                stdout="ffmpeg version 6.0\nframe= 100 fps=30 q=-1.0 Lsize= 1024kB",
                stderr="",
                duration_ms=50,
            )
        return ShellResult(
            executable=executable,
            args=list(args),
            returncode=0,
            stdout="",
            stderr="",
            duration_ms=5,
        )


# ============================================================================
# Test 1: Exact Pacing Linter Test from Brief
# ============================================================================


def test_pacing_linter_flags_adjacent_heavy_effects_and_20s_dry_spans():
    scenes = [
        Scene(scene_id="1", start=0.0, end=2.0, effect="major_zoom", overlay_text="EDIT VIDEO"),
        Scene(scene_id="2", start=2.0, end=4.0, effect="major_split", overlay_text="AI"),
        Scene(scene_id="3", start=4.0, end=28.0, effect="none", overlay_text="Body"),
    ]
    warnings = StoryboardBuilder.lint_pacing(scenes)
    assert any("sát nhau" in w for w in warnings), f"Expected 'sát nhau' in warnings, got: {warnings}"
    assert any("20 giây" in w for w in warnings), f"Expected '20 giây' in warnings, got: {warnings}"


# ============================================================================
# Test 2: StoryboardBuilder Preserves Exact Spoken Transcript Text
# ============================================================================


def test_build_from_transcript_preserves_exact_words_and_timing():
    segments = [
        {
            "id": "c1",
            "text": "Chào mừng bạn đến với kênh AI Automation!",
            "start": 0.0,
            "end": 3.2,
            "effect": "major_zoom",
            "visual_notes": "Zoom vào MC ảo",
        },
        {
            "id": "c2",
            "text": "Hôm nay chúng ta cùng xây dựng Video Editor tự động.",
            "start": 3.2,
            "duration": 4.8,
            "effect": "none",
            "visual_notes": "Hiển thị sơ đồ kiến trúc",
        },
    ]

    scenes = StoryboardBuilder.build_from_transcript(segments, total_duration=8.0)
    assert len(scenes) == 2
    assert scenes[0].scene_id == "c1"
    assert scenes[0].overlay_text == "Chào mừng bạn đến với kênh AI Automation!"
    assert scenes[0].start == 0.0
    assert scenes[0].end == 3.2
    assert pytest.approx(scenes[0].duration, 0.01) == 3.2
    assert scenes[0].effect == "major_zoom"
    assert scenes[0].visual_notes == "Zoom vào MC ảo"

    # Segment with duration rather than explicit end
    assert scenes[1].scene_id == "c2"
    assert scenes[1].overlay_text == "Hôm nay chúng ta cùng xây dựng Video Editor tự động."
    assert scenes[1].start == 3.2
    assert pytest.approx(scenes[1].end, 0.01) == 8.0
    assert pytest.approx(scenes[1].duration, 0.01) == 4.8
    assert scenes[1].effect == "none"


# ============================================================================
# Test 3: ffprobe Media Inspection via ShellExecutor
# ============================================================================


@pytest.mark.asyncio
async def test_ffprobe_media_inspection_via_shell(tmp_path: Path):
    mock_shell = MockShellExecutor(workspace_root=tmp_path)
    agent = VideoEditorAgent(shell=mock_shell, workspace_root=tmp_path)

    # Place a dummy video file in workspace
    video_file = tmp_path / "raw_footage.mp4"
    video_file.write_bytes(b"\x00\x00\x00 ftypisom")

    task_ctx = {
        "video_path": str(video_file),
        "task_workspace": str(tmp_path),
        "transcript_segments": [
            {"text": "Mở đầu video", "start": 0.0, "end": 2.0, "effect": "major_zoom"},
            {"text": "Nội dung chính", "start": 2.0, "end": 28.5, "effect": "none"},
        ],
    }

    result = await agent.run(task_ctx)

    # Verify ffprobe was called
    ffprobe_calls = [c for c in mock_shell.calls if c["executable"] == "ffprobe"]
    assert len(ffprobe_calls) >= 1
    assert "raw_footage.mp4" in " ".join(ffprobe_calls[0]["args"])

    # Verify extracted metadata
    vmeta = result.structured_data.get("video_metadata", {})
    assert vmeta.get("duration") == 28.5
    assert vmeta.get("fps") == 30.0
    assert vmeta.get("resolution") == "1920x1080"
    assert vmeta.get("width") == 1920
    assert vmeta.get("height") == 1080
    assert vmeta.get("codec") == "h264"


# ============================================================================
# Test 4: HIL Storyboard Review Gate Suspension
# ============================================================================


@pytest.mark.asyncio
async def test_hil_storyboard_review_gate_suspension(tmp_path: Path):
    mock_shell = MockShellExecutor(workspace_root=tmp_path)
    agent = VideoEditorAgent(shell=mock_shell, workspace_root=tmp_path)

    task_ctx = {
        "task_workspace": str(tmp_path),
        "approved": False,
        "transcript_segments": [
            {"text": "Cảnh 1", "start": 0.0, "end": 2.0, "effect": "major_zoom"},
            {"text": "Cảnh 2", "start": 2.0, "end": 4.0, "effect": "major_split"},
            {"text": "Cảnh 3", "start": 4.0, "end": 28.0, "effect": "none"},
        ],
    }

    result = await agent.run(task_ctx)

    # 1. Status is waiting_review
    assert result.status == "waiting_review"

    # 2. Note / message contains required text
    assert "Phê duyệt kịch bản phân cảnh (Storyboard) trước khi render video" in result.content

    # 3. Review gate structured data
    gate = result.structured_data.get("review_gate", {})
    assert gate.get("gate_type") == "storyboard"
    assert gate.get("requires_approval") is True
    assert gate.get("scene_count") == 3
    assert len(gate.get("warnings", [])) >= 2
    assert any("sát nhau" in w for w in gate["warnings"])
    assert any("20 giây" in w for w in gate["warnings"])

    # 4. Artifacts generated (storyboard.md and storyboard.json)
    art_names = [a.filename for a in result.artifacts]
    assert any(name.endswith(".md") for name in art_names)
    assert any(name.endswith(".json") for name in art_names)

    # 5. ffmpeg MUST NOT be called before review approval
    ffmpeg_calls = [c for c in mock_shell.calls if c["executable"] == "ffmpeg"]
    assert len(ffmpeg_calls) == 0


# ============================================================================
# Test 5: Render Video when Approved=True via ffmpeg
# ============================================================================


@pytest.mark.asyncio
async def test_render_video_when_approved_invokes_ffmpeg(tmp_path: Path):
    mock_shell = MockShellExecutor(workspace_root=tmp_path)
    agent = VideoEditorAgent(shell=mock_shell, workspace_root=tmp_path)

    input_file = tmp_path / "raw.mp4"
    input_file.write_bytes(b"\x00\x00\x00 ftypisom")

    task_ctx = {
        "video_path": str(input_file),
        "task_workspace": str(tmp_path),
        "approved": True,
        "transcript_segments": [
            {"text": "Khúc đầu", "start": 0.0, "end": 3.0, "effect": "major_zoom"},
            {"text": "Khúc sau", "start": 3.0, "end": 6.0, "effect": "none"},
        ],
    }

    result = await agent.run(task_ctx)

    assert result.status == "completed"

    # Verify ffmpeg was executed
    ffmpeg_calls = [c for c in mock_shell.calls if c["executable"] == "ffmpeg"]
    assert len(ffmpeg_calls) >= 1
    args_str = " ".join(ffmpeg_calls[0]["args"])
    assert "-c:v" in args_str
    assert "libx264" in args_str

    # Verify MP4 video artifact is registered
    mp4_artifacts = [a for a in result.artifacts if a.filename.endswith(".mp4") or a.artifact_type in ("video", "mp4")]
    assert len(mp4_artifacts) >= 1
    rendered_file = tmp_path / mp4_artifacts[0].filename
    assert rendered_file.exists()


# ============================================================================
# Test 6: WorkerResult Compatibility with Orchestrator Subtasks
# ============================================================================


@pytest.mark.asyncio
async def test_worker_result_compatibility_orchestrator(tmp_path: Path):
    mock_shell = MockShellExecutor(workspace_root=tmp_path)
    agent = VideoEditorAgent(shell=mock_shell, workspace_root=tmp_path)

    subtask_dict = {
        "id": "subtask-video-001",
        "instruction": "Biên tập video và lint nhịp độ",
        "metadata": {
            "task_workspace": str(tmp_path),
            "transcript_segments": [
                {"text": "Đoạn 1", "start": 0.0, "end": 2.0},
            ],
        },
    }

    res = await agent.execute(subtask_dict)
    assert isinstance(res, WorkerResult)
    assert res.subtask_id == "subtask-video-001"
    assert res.agent_id == agent.agent.id
    assert res.status == "waiting_review"
    assert res.duration_ms >= 0

    as_dict = res.to_dict()
    assert as_dict["subtask_id"] == "subtask-video-001"
    assert "structured_data" in as_dict
    assert "artifacts" in as_dict


# ============================================================================
# Test 7: Secret Masking Across Storyboard Artifacts and Structured Data
# ============================================================================


@pytest.mark.asyncio
async def test_secret_masking_across_storyboard_and_artifacts(tmp_path: Path):
    mock_shell = MockShellExecutor(workspace_root=tmp_path)
    secret_key = "sk-live-supersecrettoken999"
    agent = VideoEditorAgent(shell=mock_shell, workspace_root=tmp_path)

    task_ctx = {
        "task_workspace": str(tmp_path),
        "api_key": secret_key,
        "extra_secrets": [secret_key],
        "transcript_segments": [
            {
                "text": f"Mật khẩu hệ thống là {secret_key}",
                "start": 0.0,
                "end": 3.0,
                "visual_notes": f"Hiển thị mã {secret_key}",
            },
        ],
    }

    result = await agent.run(task_ctx)

    # Verify secret is masked in content
    assert secret_key not in result.content
    assert "***" in result.content or "[REDACTED]" in result.content or "***" in str(result.structured_data)

    # Verify secret is not in any artifact
    for art in result.artifacts:
        assert secret_key not in art.content
        art_path = tmp_path / art.filename
        if art_path.exists():
            disk_content = art_path.read_text(encoding="utf-8")
            assert secret_key not in disk_content
