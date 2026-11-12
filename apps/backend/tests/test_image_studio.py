"""Tests for ImageStudioAgent (Task 3.4).

Verifies:
1. Exact requirement: test_image_studio_renders_1080x1080_html_and_png_without_paid_image_api.
2. 3 built-in offline HTML/CSS/SVG templates (quote_card, product_showcase, infographic) with full Vietnamese diacritics.
3. Aspect ratio / dimension parsing (1080x1080, 1200x630, 1080x1920, and named aliases).
4. BrandProfile colors and font integration.
5. Paid generative image model HIL gate (waiting_review + VND/USD cost confirmation).
6. WorkerResult compatibility when invoked via orchestrator execute(subtask, context).
7. Secret masking across headline, copy, and artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import pytest

from app.agents.base import WorkerResult
from app.agents.content import ImageStudioAgent
from app.db.models import BrandProfile
from app.mcp.browser_server import BrowserActionResult, BrowserController, BrowserGateStatus


class MockBrowser:
    """In-memory mock for BrowserController.render_html_to_png."""

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
        # Write minimal valid 1x1 PNG bytes so file exists on disk
        out_path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
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


@pytest.fixture
def mock_browser() -> MockBrowser:
    return MockBrowser()


# ============================================================================
# Step 1: Brief-mandated test
# ============================================================================


@pytest.mark.asyncio
async def test_image_studio_renders_1080x1080_html_and_png_without_paid_image_api(
    mock_browser: MockBrowser, tmp_path: Path
) -> None:
    """Exact test from Task 3.4 brief."""
    agent = ImageStudioAgent(browser=mock_browser, llm=None)
    res = await agent.run(
        {
            "headline": "Dành cho mình một khoảng nghỉ",
            "size": "1080x1080",
            "template": "quote_card",
            "output_dir": tmp_path,
        }
    )
    assert any(a.filename.endswith(".html") for a in res.artifacts)
    assert any(a.filename.endswith(".png") for a in res.artifacts)
    assert mock_browser.last_viewport == {"width": 1080, "height": 1080}


# ============================================================================
# Template Tests (All 3 offline templates with Vietnamese diacritics)
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "template_name,extra_ctx,expected_texts",
    [
        (
            "quote_card",
            {
                "headline": "Hành trình vạn dặm bắt đầu từ một bước chân nhỏ bé",
                "author": "Lão Tử",
                "subhead": "Triết lý sống cân bằng & an nhiên",
            },
            ["Hành trình vạn dặm", "Lão Tử", "Triết lý sống cân bằng"],
        ),
        (
            "product_showcase",
            {
                "headline": "Nến Thơm Thảo Mộc Cao Cấp",
                "badge": "Bán Chạy Nhất",
                "price": "289.000₫",
                "features": [
                    "100% sáp đậu nành tự nhiên thuần khiết",
                    "Tinh dầu oải hương Pháp nguyên chất",
                    "Bấc gỗ không khói thư giãn êm dịu",
                ],
                "cta_text": "Mua Ngay Nhận Ưu Đãi 20%",
            },
            [
                "Nến Thơm Thảo Mộc",
                "289.000₫",
                "100% sáp đậu nành",
                "Mua Ngay Nhận Ưu Đãi",
            ],
        ),
        (
            "infographic",
            {
                "headline": "3 Thói Quen Buổi Sáng Tái Tạo Năng Lượng",
                "items": [
                    {
                        "step": "01",
                        "title": "Uống 300ml Nước Ấm",
                        "desc": "Thanh lọc cơ thể và kích hoạt hệ tiêu hóa",
                    },
                    {
                        "step": "02",
                        "title": "Hít Thở Sâu 5 Phút",
                        "desc": "Cung cấp oxy dồi dào cho não bộ tỉnh táo",
                    },
                    {
                        "step": "03",
                        "title": "Lên Kế Hoạch 3 Việc Chính",
                        "desc": "Tập trung năng lượng vào mục tiêu quan trọng nhất",
                    },
                ],
                "footer": "Nguồn: Nghiên cứu khoa học thần kinh & hành vi 2026",
            },
            [
                "3 Thói Quen Buổi Sáng",
                "Uống 300ml Nước Ấm",
                "Hít Thở Sâu",
                "Lên Kế Hoạch 3 Việc",
            ],
        ),
    ],
)
async def test_image_studio_renders_all_three_templates_with_vietnamese(
    mock_browser: MockBrowser,
    tmp_path: Path,
    template_name: str,
    extra_ctx: dict[str, Any],
    expected_texts: list[str],
) -> None:
    agent = ImageStudioAgent(browser=mock_browser, llm=None)
    task_ctx = {
        "template": template_name,
        "size": "1080x1080",
        "output_dir": tmp_path,
        **extra_ctx,
    }
    res = await agent.run(task_ctx)
    assert res.status == "completed"
    assert len(res.artifacts) >= 2

    html_artifact = next(a for a in res.artifacts if a.filename.endswith(".html"))
    png_artifact = next(a for a in res.artifacts if a.filename.endswith(".png"))

    assert (tmp_path / html_artifact.filename).exists()
    assert (tmp_path / png_artifact.filename).exists()

    rendered = mock_browser.last_rendered_html or ""
    assert "charset" in rendered.lower()
    for text in expected_texts:
        assert text in rendered

    # Strictly offline: no external CDN links or remote script/font calls
    assert "https://" not in rendered
    assert "http://" not in rendered


# ============================================================================
# Dimension & Aspect Ratio Parsing Tests
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "size_input,expected_w,expected_h",
    [
        ("1080x1080", 1080, 1080),
        ("1200x630", 1200, 630),
        ("1080x1920", 1080, 1920),
        ("square", 1080, 1080),
        ("landscape", 1200, 630),
        ("story", 1080, 1920),
        ("reels", 1080, 1920),
        ("tiktok", 1080, 1920),
        ("og", 1200, 630),
        ("meta", 1200, 630),
        (None, 1080, 1080),  # default
        ("invalid-size-format", 1080, 1080),  # fallback default
    ],
)
async def test_image_studio_dimension_parsing(
    mock_browser: MockBrowser,
    tmp_path: Path,
    size_input: Optional[str],
    expected_w: int,
    expected_h: int,
) -> None:
    agent = ImageStudioAgent(browser=mock_browser, llm=None)
    task_ctx: dict[str, Any] = {
        "headline": "Kích thước hình ảnh chuẩn chuẩn hóa",
        "output_dir": tmp_path,
    }
    if size_input is not None:
        task_ctx["size"] = size_input

    res = await agent.run(task_ctx)
    assert res.status == "completed"
    assert mock_browser.last_viewport == {"width": expected_w, "height": expected_h}
    assert res.structured_data["width"] == expected_w
    assert res.structured_data["height"] == expected_h


@pytest.mark.asyncio
async def test_image_studio_explicit_width_and_height(
    mock_browser: MockBrowser, tmp_path: Path
) -> None:
    agent = ImageStudioAgent(browser=mock_browser, llm=None)
    res = await agent.run(
        {
            "headline": "Kích thước tùy biến",
            "width": 1200,
            "height": 630,
            "output_dir": tmp_path,
        }
    )
    assert res.status == "completed"
    assert mock_browser.last_viewport == {"width": 1200, "height": 630}


# ============================================================================
# BrandProfile Color & Font Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_image_studio_brand_profile_color_and_font_injection(
    mock_browser: MockBrowser, tmp_path: Path
) -> None:
    brand = BrandProfile(
        id="bp-eco",
        project_id="proj-default",
        brand_name="Mộc Hương Nature",
        brand_colors=["#166534", "#15803d", "#d97706", "#f0fdf4"],
        fonts=["'Be Vietnam Pro'", "sans-serif"],
        tagline="Hương thảo mộc an lành",
    )
    agent = ImageStudioAgent(browser=mock_browser, brand_profile=brand)
    res = await agent.run(
        {
            "headline": "Tinh túy từ thiên nhiên ban tặng",
            "template": "quote_card",
            "output_dir": tmp_path,
        }
    )
    assert res.status == "completed"
    html = mock_browser.last_rendered_html or ""
    assert "#166534" in html
    assert "Mộc Hương Nature" in html
    assert "'Be Vietnam Pro'" in html


@pytest.mark.asyncio
async def test_image_studio_brand_profile_dict_colors(
    mock_browser: MockBrowser, tmp_path: Path
) -> None:
    brand_dict = {
        "brand_name": "Sống Tối Giản",
        "primary_color": "#0f172a",
        "secondary_color": "#334155",
        "accent_color": "#38bdf8",
        "background_color": "#f8fafc",
        "font_family": "system-ui, sans-serif",
    }
    agent = ImageStudioAgent(browser=mock_browser)
    res = await agent.run(
        {
            "headline": "Bớt một vật, thêm một phần tự do",
            "brand_profile": brand_dict,
            "output_dir": tmp_path,
        }
    )
    assert res.status == "completed"
    html = mock_browser.last_rendered_html or ""
    assert "#0f172a" in html
    assert "#38bdf8" in html
    assert "Sống Tối Giản" in html


# ============================================================================
# Paid Generative Image Model HIL Gate Tests
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "paid_payload",
    [
        {"use_paid_api": True, "prompt": "hyperrealistic cinematic candle"},
        {"provider": "dall-e-3", "prompt": "studio product shot"},
        {"provider": "midjourney", "prompt": "anime landscape"},
        {"provider": "imagen", "prompt": "vietnamese coffee cup"},
        {"model": "dall-e-3", "prompt": "modern flat graphic"},
    ],
)
async def test_image_studio_paid_model_triggers_hil_review_gate(
    mock_browser: MockBrowser, tmp_path: Path, paid_payload: dict[str, Any]
) -> None:
    agent = ImageStudioAgent(browser=mock_browser, llm=None)
    task_ctx = {
        "output_dir": tmp_path,
        **paid_payload,
    }
    res = await agent.run(task_ctx)

    # Must NOT run browser render or silently consume paid credits
    assert res.status == "waiting_review"
    assert len(mock_browser.calls) == 0
    assert "Yêu cầu phê duyệt chi phí API hình ảnh trả phí" in (res.content or res.error or "")

    gate = res.structured_data.get("review_gate", {})
    assert gate.get("gate_type") == "paid_image_api"
    assert "estimated_cost" in gate or "cost_usd" in gate
    assert gate.get("status") == "waiting_review"


# ============================================================================
# Orchestrator Compatibility (execute method with subtask)
# ============================================================================


@pytest.mark.asyncio
async def test_image_studio_execute_compatibility_with_orchestrator(
    mock_browser: MockBrowser, tmp_path: Path
) -> None:
    agent = ImageStudioAgent(browser=mock_browser)
    subtask = {
        "id": "subtask-img-001",
        "instruction": "Tạo hình ảnh quote truyền cảm hứng làm việc",
        "metadata": {
            "template": "quote_card",
            "size": "1080x1080",
            "headline": "Kỷ luật mang lại sự tự do",
            "author": "Minh Hoàng",
            "output_dir": str(tmp_path),
        },
    }
    context = {"extra_secrets": ["TEST_SECRET_API_KEY_123"]}

    res = await agent.execute(subtask=subtask, context=context)

    assert isinstance(res, WorkerResult)
    assert res.subtask_id == "subtask-img-001"
    assert res.status == "completed"
    assert any(a.filename.endswith(".html") for a in res.artifacts)
    assert any(a.filename.endswith(".png") for a in res.artifacts)
    assert mock_browser.last_viewport == {"width": 1080, "height": 1080}


# ============================================================================
# Secret Masking Tests
# ============================================================================


@pytest.mark.asyncio
async def test_image_studio_masks_secrets_in_rendered_output_and_artifacts(
    mock_browser: MockBrowser, tmp_path: Path
) -> None:
    secret_val = "SECRET_TOKEN_XYZ_999"
    agent = ImageStudioAgent(browser=mock_browser)
    res = await agent.run(
        {
            "headline": f"Khám phá tài liệu mật {secret_val}",
            "template": "quote_card",
            "output_dir": tmp_path,
            "extra_secrets": [secret_val],
        }
    )
    assert res.status == "completed"
    rendered = mock_browser.last_rendered_html or ""
    assert secret_val not in rendered
    assert secret_val not in res.content
    for art in res.artifacts:
        assert secret_val not in art.content


@pytest.mark.asyncio
async def test_image_studio_masks_brand_name_in_structured_data(
    mock_browser: MockBrowser, tmp_path: Path
) -> None:
    secret_brand = "SECRET_BRAND_TOKEN_888"
    agent = ImageStudioAgent(browser=mock_browser)
    res = await agent.run(
        {
            "headline": "Tiêu đề chuẩn mực",
            "brand_profile": {"brand_name": secret_brand},
            "output_dir": tmp_path,
            "extra_secrets": [secret_brand],
        }
    )
    assert res.status == "completed"
    assert secret_brand not in res.structured_data["brand_name"]
    assert "***REDACTED***" in res.structured_data["brand_name"]


# ============================================================================
# Review Round 1 Regression Tests (P1 Injection & P2 Browser Hierarchy)
# ============================================================================


@pytest.mark.asyncio
async def test_image_studio_malicious_color_and_font_injection_sanitization(
    mock_browser: MockBrowser, tmp_path: Path
) -> None:
    """Verify that malicious color or font strings are rejected and sanitized."""
    malicious_brand = {
        "brand_name": "Secure Brand",
        "primary_color": '"><script>alert("injected_color")</script><style>',
        "secondary_color": "rgba(255, 0, 0, 0.8); background: red;",
        "accent_color": "#ff0000; font-size: 50px;",
        "background_color": "<svg/onload=alert(1)>",
        "brand_colors": [
            "blue; display: none;",
            "<img src=x onerror=alert('xss')>",
        ],
        "font_family": '"><script>alert("font_xss")</script>Roboto; color: red;',
    }
    agent = ImageStudioAgent(browser=mock_browser)
    res = await agent.run(
        {
            "headline": "Kiểm tra an toàn bảo mật injection",
            "brand_profile": malicious_brand,
            "output_dir": tmp_path,
        }
    )
    assert res.status == "completed"
    rendered = mock_browser.last_rendered_html or ""

    # Must NOT contain injected script tags or event handlers
    assert "<script>" not in rendered
    assert "</script>" not in rendered
    assert "injected_color" not in rendered
    assert "font_xss" not in rendered
    assert "<svg/onload" not in rendered
    assert "<img" not in rendered
    assert "onerror=" not in rendered

    # Default fallback color should be used when malicious color is discarded
    assert "#1e40af" in rendered


@pytest.mark.asyncio
async def test_image_studio_fallback_browser_workspace_hierarchy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that ImageStudioAgent(browser=None) uses output_dir.parent as workspace_root."""
    created_controllers: list[BrowserController] = []
    orig_init = BrowserController.__init__

    def tracking_init(self: Any, *args: Any, **kwargs: Any) -> None:
        orig_init(self, *args, **kwargs)
        created_controllers.append(self)

    monkeypatch.setattr(BrowserController, "__init__", tracking_init)

    async def fake_render(
        self: Any,
        html: str,
        output_path: Path | str,
        *,
        width: int = 1280,
        height: int = 720,
        full_page: bool = False,
        task_workspace: Optional[Path] = None,
    ) -> BrowserActionResult:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return BrowserActionResult(
            status=BrowserGateStatus.OK.value,
            action="render_html_to_png",
            screenshot_path=str(p),
            duration_ms=25,
        )

    monkeypatch.setattr(BrowserController, "render_html_to_png", fake_render)

    task_workspace_dir = tmp_path / "workspace_parent" / "target_output_dir"
    agent = ImageStudioAgent(browser=None)
    res = await agent.run(
        {
            "headline": "Kiểm tra cấu trúc thư mục fallback",
            "output_dir": task_workspace_dir,
        }
    )

    assert res.status == "completed"
    assert len(created_controllers) >= 1
    # Check that workspace_root was output_dir.resolve().parent, making output_dir a valid child
    assert any(
        ctrl.workspace_root == task_workspace_dir.resolve().parent
        for ctrl in created_controllers
    )
    assert any(a.filename.endswith(".png") for a in res.artifacts)

    # Test failure case when PNG rendering fails
    async def failing_render(*args: Any, **kwargs: Any) -> BrowserActionResult:
        raise RuntimeError("Chromium rendering engine crashed")

    monkeypatch.setattr(BrowserController, "render_html_to_png", failing_render)
    fail_dir = tmp_path / "fail_workspace" / "out"
    res_fail = await agent.run(
        {
            "headline": "Kiểm tra render lỗi",
            "output_dir": fail_dir,
        }
    )
    assert res_fail.status == "failed"
    assert "Chromium rendering engine crashed" in (res_fail.error or "")
    assert not any(a.filename.endswith(".png") for a in res_fail.artifacts)

