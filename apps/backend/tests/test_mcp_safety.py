"""Security, timeout, isolation, and gate-detection tests for Task 3.1 MCP Gateway."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import socket
import sys
import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.config import AppSettings
from app.mcp.browser_server import (
    BrowserActionResult,
    BrowserController,
    BrowserGateStatus,
    BrowserPolicyError,
)
from app.mcp.gateway import McpGateway
from app.mcp.shell_server import (
    SecurityPolicyError,
    ShellExecutor,
    ShellResult,
    ShellTimeoutError,
)


def _public_dns(_host: str) -> list[str]:
    return ["93.184.216.34"]


# ============================================================================
# ShellExecutor Tests
# ============================================================================


@pytest.mark.asyncio
async def test_shell_executor_blocks_disallowed_commands_and_traversal(tmp_path: Path):
    executor = ShellExecutor(workspace_root=tmp_path)
    task_dir = tmp_path / "task-1"
    task_dir.mkdir()
    with pytest.raises(SecurityPolicyError):
        await executor.run("rm", ["-rf", "/"], task_workspace=task_dir)
    with pytest.raises(SecurityPolicyError):
        await executor.run("python", ["../../etc/passwd"], task_workspace=task_dir)
    with pytest.raises(SecurityPolicyError):
        await executor.run("ffmpeg", ["-i", "a.mp4 && del C:\\*"], task_workspace=task_dir)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_exec",
    [
        "powershell",
        "cmd",
        "cmd.exe",
        "bash",
        "sh",
        "/bin/sh",
        "../python",
        "subdir/python",
        "C:\\Windows\\System32\\cmd.exe",
        "",
        "   ",
    ],
)
async def test_shell_executor_rejects_non_whitelisted_or_path_executables(
    tmp_path: Path, bad_exec: str
):
    executor = ShellExecutor(workspace_root=tmp_path)
    task_dir = tmp_path / "task-1"
    task_dir.mkdir()
    with pytest.raises(SecurityPolicyError):
        await executor.run(bad_exec, ["--version"], task_workspace=task_dir)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_arg",
    [
        "file.mp4 && whoami",
        "file.mp4 || echo pwned",
        "file.mp4; ls",
        "file.mp4 | cat",
        "`whoami`",
        "$(whoami)",
        "out.txt > /tmp/pwn",
        "in.txt < /etc/passwd",
        "line1\nwhoami",
        "line1\rwhoami",
        "arg\x00evil",
    ],
)
async def test_shell_executor_blocks_shell_injection_metacharacters(
    tmp_path: Path, bad_arg: str
):
    executor = ShellExecutor(workspace_root=tmp_path)
    task_dir = tmp_path / "task-1"
    task_dir.mkdir()
    with pytest.raises(SecurityPolicyError):
        await executor.run("ffmpeg", ["-i", bad_arg], task_workspace=task_dir)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("executable", "args"),
    [
        ("python", ["-c", "print('evil')"]),
        ("python", ["-uc", "print('evil')"]),
        ("python", ["-cprint('evil')"]),
        ("python", ["-"]),
        ("node", ["-e", "console.log(1)"]),
        ("node", ["--eval", "console.log(1)"]),
        ("node", ["--eval=console.log(1)"]),
        ("node", ["-p", "1+1"]),
        ("node", ["--print", "1+1"]),
        ("node", ["-"]),
        ("yt-dlp", ["--exec", "calc.exe", "https://example.com/video"]),
        ("yt-dlp", ["--exec=calc.exe", "https://example.com/video"]),
    ],
)
async def test_shell_executor_blocks_inline_code_execution_flags(
    tmp_path: Path, executable: str, args: list[str]
):
    executor = ShellExecutor(workspace_root=tmp_path)
    task_dir = tmp_path / "task-1"
    task_dir.mkdir()
    with pytest.raises(SecurityPolicyError):
        await executor.run(executable, args, task_workspace=task_dir)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("executable", "args"),
    [
        ("ffmpeg", ["-i", "../outside.mp4", "out.mp4"]),
        ("ffmpeg", ["-i", "in.mp4", "-o", "../../escape.mp4"]),
        ("ffmpeg", ["-i", "in.mp4", "--output=../../escape.mp4"]),
        ("python", ["C:\\Windows\\System32\\drivers\\etc\\hosts"]),
        ("python", ["\\\\evil-server\\share\\payload.py"]),
        ("python", ["//evil-server/share/payload.py"]),
        ("python", ["~/.ssh/id_rsa"]),
        ("python", ["C:relative_drive.py"]),
        ("python", ["file:///etc/passwd"]),
        ("ffmpeg", ["-i", "in.mp4", "/tmp/outside.mp4"]),
    ],
)
async def test_shell_executor_blocks_path_escapes_unc_drive_and_tilde(
    tmp_path: Path, executable: str, args: list[str]
):
    executor = ShellExecutor(workspace_root=tmp_path)
    task_dir = tmp_path / "task-1"
    task_dir.mkdir()
    with pytest.raises(SecurityPolicyError):
        await executor.run(executable, args, task_workspace=task_dir)


@pytest.mark.asyncio
async def test_shell_executor_blocks_outside_task_workspace_and_symlink_escapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret_file = outside_dir / "secret.py"
    secret_file.write_text("print('leaked')", encoding="utf-8")

    executor = ShellExecutor(workspace_root=workspace_root)

    # 1. Direct outside task_workspace
    with pytest.raises(SecurityPolicyError):
        await executor.run("python", ["secret.py"], task_workspace=outside_dir)

    task_dir = workspace_root / "task-1"
    task_dir.mkdir()

    # 2. Symlink inside task_workspace pointing outside (with deterministic fallback on unprivileged Windows)
    symlink_file = task_dir / "escape.py"
    symlink_ws = workspace_root / "symlink_ws"
    try:
        os.symlink(secret_file, symlink_file)
        os.symlink(outside_dir, symlink_ws, target_is_directory=True)
    except OSError:
        symlink_file.write_text("placeholder", encoding="utf-8")
        symlink_ws.mkdir()
        real_resolve = Path.resolve

        def fake_resolve(self: Path, strict: bool = False) -> Path:
            if self.name == "escape.py":
                return real_resolve(secret_file, strict=strict)
            if self.name == "symlink_ws":
                return real_resolve(outside_dir, strict=strict)
            return real_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", fake_resolve)

    with pytest.raises(SecurityPolicyError):
        await executor.run("python", ["escape.py"], task_workspace=task_dir)
    with pytest.raises(SecurityPolicyError):
        await executor.run("python", ["secret.py"], task_workspace=symlink_ws)


@pytest.mark.asyncio
async def test_shell_executor_runs_safe_python_scrubs_env_masks_secrets_and_caps_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    task_dir = workspace_root / "task-run"
    task_dir.mkdir()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-supersecret1234567890")
    monkeypatch.setenv("LOCAL_AUTH_TOKEN", "my-very-secret-local-token")
    monkeypatch.setenv("ENCRYPTION_KEY", "fernet-secret-key-value-123")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret-value-xyz")

    script = task_dir / "inspect_env.py"
    script.write_text(
        "\n".join(
            [
                "import os, pathlib, sys",
                "keys = sorted(os.environ.keys())",
                "print('CWD=' + str(pathlib.Path.cwd()))",
                "print('ENV_KEYS=' + ','.join(keys))",
                "print('LEAK_TEST=sk-1234567890abcdef')",
                "print('EXTRA_TEST=my-very-secret-local-token')",
                "print('ERR_KEY=AIzaSyDummyKey1234567890', file=sys.stderr)",
            ]
        ),
        encoding="utf-8",
    )

    executor = ShellExecutor(
        workspace_root=workspace_root,
        extra_secrets=["my-very-secret-local-token"],
    )
    res = await executor.run("python", ["inspect_env.py"], task_workspace=task_dir)

    assert isinstance(res, ShellResult)
    assert res.executable == "python"
    assert res.returncode == 0
    assert res.timed_out is False
    assert res.duration_ms >= 0
    assert f"CWD={task_dir.resolve()}" in res.stdout

    # Sensitive env vars stripped
    for forbidden in (
        "OPENAI_API_KEY",
        "LOCAL_AUTH_TOKEN",
        "ENCRYPTION_KEY",
        "AWS_SECRET_ACCESS_KEY",
    ):
        assert forbidden not in res.stdout

    # Secrets in stdout & stderr masked
    assert "sk-1234567890abcdef" not in res.stdout
    assert "my-very-secret-local-token" not in res.stdout
    assert "AIzaSyDummyKey1234567890" not in res.stderr
    assert "***REDACTED***" in res.stdout
    assert "***REDACTED***" in res.stderr

    # Output capping
    big_script = task_dir / "big.py"
    big_script.write_text("print('A' * 5000)", encoding="utf-8")
    capped_executor = ShellExecutor(workspace_root=workspace_root, max_output_bytes=256)
    capped_res = await capped_executor.run("python", ["big.py"], task_workspace=task_dir)
    assert "[TRUNCATED]" in capped_res.stdout
    assert len(capped_res.stdout.encode("utf-8")) < 400


@pytest.mark.asyncio
async def test_shell_executor_timeout_kills_process_tree(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    task_dir = workspace_root / "task-timeout"
    task_dir.mkdir()

    pid_file = task_dir / "child.pid"
    script = task_dir / "spawn_child.py"
    script.write_text(
        "\n".join(
            [
                "import pathlib, subprocess, sys, time",
                f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])",
                f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid), encoding='utf-8')",
                "time.sleep(60)",
            ]
        ),
        encoding="utf-8",
    )

    executor = ShellExecutor(workspace_root=workspace_root, default_timeout_s=1)
    with pytest.raises(ShellTimeoutError):
        await executor.run("python", ["spawn_child.py"], task_workspace=task_dir, timeout_s=1)

    # Give OS a brief moment to finalize process termination if child PID was written
    if pid_file.exists():
        child_pid = int(pid_file.read_text(encoding="utf-8").strip())
        deadline = time.monotonic() + 2.0
        alive = True
        while time.monotonic() < deadline:
            try:
                if sys.platform == "win32":
                    import ctypes

                    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                    STILL_ACTIVE = 259
                    handle = ctypes.windll.kernel32.OpenProcess(
                        PROCESS_QUERY_LIMITED_INFORMATION, False, child_pid
                    )
                    if not handle:
                        alive = False
                        break
                    exit_code = ctypes.c_ulong()
                    ok = ctypes.windll.kernel32.GetExitCodeProcess(
                        handle, ctypes.byref(exit_code)
                    )
                    ctypes.windll.kernel32.CloseHandle(handle)
                    if not ok or exit_code.value != STILL_ACTIVE:
                        alive = False
                        break
                else:
                    os.kill(child_pid, 0)
            except ProcessLookupError:
                alive = False
                break
            except PermissionError:
                pass
            time.sleep(0.1)
        assert alive is False, f"Child process {child_pid} survived process-tree kill"


# ============================================================================
# Fake Playwright Helpers for Deterministic BrowserController Tests
# ============================================================================


class FakeRouteRequest:
    def __init__(self, url: str) -> None:
        self.url = url


class FakeRoute:
    def __init__(self, url: str) -> None:
        self.request = FakeRouteRequest(url)
        self.aborted = False
        self.continued = False

    async def abort(self) -> None:
        self.aborted = True

    async def continue_(self) -> None:
        self.continued = True


class FakePage:
    def __init__(
        self,
        *,
        url: str = "https://example.com",
        title: str = "Example Domain",
        body_text: str = "Hello world",
        html: str = "<html><body><p>Hello world</p></body></html>",
        matching_selectors: set[str] | None = None,
        redirect_to: str | None = None,
    ) -> None:
        self.url = url
        self._title = title
        self._body_text = body_text
        self._html = html
        self._matching_selectors = matching_selectors or set()
        self._redirect_to = redirect_to
        self.closed = False
        self.timeouts_seen: list[Any] = []
        self.clicked_selectors: list[str] = []
        self.filled_inputs: list[tuple[str, str]] = []
        self.goto_calls: list[tuple[str, Any]] = []
        self.screenshot_calls: list[dict[str, Any]] = []
        self.set_content_calls: list[str] = []
        self.viewport_sizes: list[dict[str, int]] = []
        self._context: FakeContext | None = None

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.timeouts_seen.append(kwargs.get("timeout"))
        self.goto_calls.append((url, kwargs))
        target = self._redirect_to or url
        if self._context is not None and self._context.route_handlers:
            route = FakeRoute(target)
            for handler in self._context.route_handlers:
                await handler(route)
            if route.aborted:
                raise RuntimeError("net::ERR_ABORTED")
        self.url = target

    async def click(self, selector: str, **kwargs: Any) -> None:
        self.timeouts_seen.append(kwargs.get("timeout"))
        self.clicked_selectors.append(selector)

    async def fill(self, selector: str, value: str, **kwargs: Any) -> None:
        self.timeouts_seen.append(kwargs.get("timeout"))
        self.filled_inputs.append((selector, value))

    async def title(self) -> str:
        return self._title

    async def inner_text(self, selector: str, **kwargs: Any) -> str:
        self.timeouts_seen.append(kwargs.get("timeout"))
        return self._body_text

    async def content(self) -> str:
        return self._html

    async def query_selector(self, selector: str) -> Any:
        if selector in self._matching_selectors:
            return object()
        return None

    async def screenshot(self, **kwargs: Any) -> bytes:
        self.timeouts_seen.append(kwargs.get("timeout"))
        self.screenshot_calls.append(kwargs)
        path = kwargs.get("path")
        if path:
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return b"\x89PNG\r\n\x1a\nfake"

    async def set_content(self, html: str, **kwargs: Any) -> None:
        self.timeouts_seen.append(kwargs.get("timeout"))
        self.set_content_calls.append(html)
        self._html = html

    async def set_viewport_size(self, viewport: dict[str, int]) -> None:
        self.viewport_sizes.append(viewport)

    async def evaluate(self, script: str) -> Any:
        return {
            "links": [{"text": "More", "href": "https://example.com/more"}],
            "inputs": [{"name": "q", "type": "text"}],
            "buttons": ["Submit"],
        }

    def set_default_timeout(self, timeout_ms: float) -> None:
        self.timeouts_seen.append(timeout_ms)

    async def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.page._context = self
        self.closed = False
        self.route_handlers: list[Any] = []

    async def route(self, pattern: str, handler: Any) -> None:
        self.route_handlers.append(handler)

    async def new_page(self) -> FakePage:
        return self.page

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, page: FakePage | None = None) -> None:
        self.page = page or FakePage()
        self.extra_pages: list[FakePage] = []
        self.contexts: list[FakeContext] = []
        self.closed = False

    async def new_context(self, **kwargs: Any) -> FakeContext:
        if len(self.contexts) == 0:
            p = self.page
        else:
            p = FakePage()
            self.extra_pages.append(p)
        ctx = FakeContext(p)
        self.contexts.append(ctx)
        return ctx

    async def close(self) -> None:
        self.closed = True


# ============================================================================
# BrowserController Tests
# ============================================================================


@pytest.mark.asyncio
async def test_browser_controller_enforces_30s_timeout_and_closes_on_exit(
    tmp_path: Path,
):
    fake_page = FakePage(
        url="https://example.com/?token=sk-1234567890abcdef",
        title="Example",
        body_text="Welcome key sk-1234567890abcdef",
    )
    fake_browser = FakeBrowser(fake_page)
    task_dir = tmp_path / "task-browser"
    task_dir.mkdir()

    async with BrowserController(
        workspace_root=tmp_path,
        browser=fake_browser,
        dns_resolver=_public_dns,
    ) as ctrl:
        assert ctrl.action_timeout_s == 30.0
        nav_res = await ctrl.navigate("https://example.com", task_workspace=task_dir)
        assert nav_res.status == BrowserGateStatus.OK
        assert 30_000 in fake_page.timeouts_seen

        fill_res = await ctrl.fill("input[name='q']", "hello", task_workspace=task_dir)
        assert fill_res.status == BrowserGateStatus.OK
        assert fake_page.filled_inputs == [("input[name='q']", "hello")]

        click_res = await ctrl.click("button[type='submit']", task_workspace=task_dir)
        assert click_res.status == BrowserGateStatus.OK
        assert fake_page.clicked_selectors == ["button[type='submit']"]

        text_res = await ctrl.extract_text("body", task_workspace=task_dir)
        assert text_res.status == BrowserGateStatus.OK
        assert "sk-1234567890abcdef" not in (text_res.content or "")
        assert "***REDACTED***" in (text_res.content or "")

        snap_res = await ctrl.take_snapshot(task_workspace=task_dir)
        assert snap_res.status == BrowserGateStatus.OK
        assert snap_res.data is not None
        assert "links" in snap_res.data

        shot_path = task_dir / "screens" / "page.png"
        shot_res = await ctrl.screenshot(shot_path, task_workspace=task_dir)
        assert shot_res.status == BrowserGateStatus.OK
        assert shot_path.exists()

    assert fake_page.closed is True
    assert all(ctx.closed for ctx in fake_browser.contexts)
    assert fake_browser.closed is True


@pytest.mark.asyncio
async def test_browser_controller_closes_resources_even_on_exception(tmp_path: Path):
    fake_page = FakePage()
    fake_browser = FakeBrowser(fake_page)

    with pytest.raises(RuntimeError, match="boom"):
        async with BrowserController(
            workspace_root=tmp_path, browser=fake_browser, dns_resolver=_public_dns
        ) as ctrl:
            await ctrl.navigate("https://example.com")
            raise RuntimeError("boom")

    assert fake_page.closed is True
    assert all(ctx.closed for ctx in fake_browser.contexts)
    assert fake_browser.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://0.0.0.0:8080/",
    ],
)
async def test_browser_controller_blocks_unsafe_urls_and_ssrf(
    tmp_path: Path, bad_url: str
):
    fake_browser = FakeBrowser()
    task_dir = tmp_path / "task-1"
    task_dir.mkdir()
    async with BrowserController(workspace_root=tmp_path, browser=fake_browser) as ctrl:
        with pytest.raises(BrowserPolicyError):
            await ctrl.navigate(bad_url, task_workspace=task_dir)


@pytest.mark.asyncio
async def test_browser_controller_allows_workspace_file_url_and_blocks_screenshot_escape(
    tmp_path: Path,
):
    task_dir = tmp_path / "task-1"
    task_dir.mkdir()
    local_html = task_dir / "preview.html"
    local_html.write_text("<h1>Local</h1>", encoding="utf-8")

    fake_browser = FakeBrowser()
    async with BrowserController(workspace_root=tmp_path, browser=fake_browser) as ctrl:
        res = await ctrl.navigate(local_html.as_uri(), task_workspace=task_dir)
        assert res.status == BrowserGateStatus.OK

        with pytest.raises(SecurityPolicyError):
            await ctrl.screenshot(tmp_path / "outside.png", task_workspace=task_dir)

        with pytest.raises(SecurityPolicyError):
            await ctrl.render_html_to_png(
                "<h1>Hi</h1>",
                tmp_path.parent / "escape.png",
                task_workspace=task_dir,
            )

        ok_render = await ctrl.render_html_to_png(
            "<h1>Hi</h1>",
            task_dir / "card.png",
            task_workspace=task_dir,
        )
        assert ok_render.status == BrowserGateStatus.OK
        assert (task_dir / "card.png").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("page_kwargs", "expected_gate"),
    [
        (
            {
                "url": "https://target.example.com/login",
                "title": "Just a moment...",
                "body_text": "Verify you are human by completing the action below.",
                "matching_selectors": {".cf-turnstile"},
            },
            "captcha",
        ),
        (
            {
                "url": "https://target.example.com/form",
                "title": "Security Check",
                "body_text": "Please solve the captcha",
                "matching_selectors": {"iframe[src*='recaptcha']"},
            },
            "captcha",
        ),
        (
            {
                "url": "https://target.example.com/2fa",
                "title": "Two-Factor Authentication",
                "body_text": "Enter the 6-digit code from your authenticator app.",
                "matching_selectors": {"input[autocomplete='one-time-code']"},
            },
            "2fa",
        ),
        (
            {
                "url": "https://target.example.com/checkout",
                "title": "Checkout",
                "body_text": "Enter payment details to continue.",
                "matching_selectors": {"iframe[src*='js.stripe.com']"},
            },
            "payment",
        ),
    ],
)
async def test_browser_controller_stops_on_captcha_2fa_payment_gates(
    tmp_path: Path, page_kwargs: dict[str, Any], expected_gate: str
):
    fake_page = FakePage(**page_kwargs)
    fake_browser = FakeBrowser(fake_page)
    task_dir = tmp_path / "task-gate"
    task_dir.mkdir()

    async with BrowserController(
        workspace_root=tmp_path, browser=fake_browser, dns_resolver=_public_dns
    ) as ctrl:
        res = await ctrl.navigate(page_kwargs["url"], task_workspace=task_dir)
        assert isinstance(res, BrowserActionResult)
        assert res.status == "CAPTCHA_REQUIRED"
        assert res.gate_type == expected_gate
        assert fake_page.clicked_selectors == []
        assert fake_page.filled_inputs == []


@pytest.mark.asyncio
async def test_browser_controller_lazy_playwright_factory(tmp_path: Path):
    fake_page = FakePage()
    fake_browser = FakeBrowser(fake_page)
    chromium_launch = AsyncMock(return_value=fake_browser)

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = type("Chromium", (), {"launch": chromium_launch})()
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    fake_pw = FakePlaywright()
    factory_called = False

    async def _factory() -> FakePlaywright:
        nonlocal factory_called
        factory_called = True
        return fake_pw

    ctrl = BrowserController(
        workspace_root=tmp_path, playwright_factory=_factory, dns_resolver=_public_dns
    )
    assert factory_called is False  # Lazy: not started until an action runs

    res = await ctrl.navigate("https://example.com")
    assert factory_called is True
    assert res.status == BrowserGateStatus.OK
    chromium_launch.assert_awaited_once()

    await ctrl.close()
    assert fake_pw.stopped is True


# ============================================================================
# McpGateway Tests
# ============================================================================


@pytest.mark.asyncio
async def test_mcp_gateway_wires_settings_lists_tools_and_enforces_workspace(
    tmp_path: Path,
):
    workspace_root = tmp_path / "ws_root"
    workspace_root.mkdir()
    task_dir = workspace_root / "task-gw"
    task_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    script = task_dir / "ok.py"
    script.write_text("print('gateway-ok')", encoding="utf-8")

    settings = AppSettings(
        workspace_dir=workspace_root,
        local_auth_token="gw-secret-token-999",
    )
    fake_browser = FakeBrowser(FakePage())
    browser_ctrl = BrowserController(
        workspace_root=workspace_root,
        browser=fake_browser,
        extra_secrets=[settings.local_auth_token],
        dns_resolver=_public_dns,
    )

    async with McpGateway(settings=settings, browser_controller=browser_ctrl) as gateway:
        tools = gateway.list_tools()
        tool_names = {t["name"] for t in tools}
        assert "shell.run" in tool_names
        assert "browser.navigate" in tool_names
        assert "browser.screenshot" in tool_names

        shell_out = await gateway.call_tool(
            "shell.run",
            {"executable": "python", "args": ["ok.py"]},
            task_workspace=task_dir,
        )
        assert shell_out["returncode"] == 0
        assert "gateway-ok" in shell_out["stdout"]

        nav_out = await gateway.call_tool(
            "browser.navigate",
            {"url": "https://example.com"},
            task_workspace=task_dir,
        )
        assert nav_out["status"] == "OK"

        with pytest.raises(SecurityPolicyError):
            await gateway.call_tool(
                "shell.run",
                {"executable": "python", "args": ["ok.py"]},
                task_workspace=outside_dir,
            )

        with pytest.raises(ValueError, match="Unknown MCP tool"):
            await gateway.call_tool("unknown.tool", {}, task_workspace=task_dir)

    assert fake_browser.closed is True



# ============================================================================
# Security Review Regression Tests (Findings 1-13)
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("executable", "args"),
    [
        # Critical 1: Glued short flags
        ("yt-dlp", ["-o../../escape.mp4", "https://example.com/v"]),
        ("yt-dlp", ["-a/etc/passwd"]),
        ("yt-dlp", ["-P/tmp/escape", "https://example.com/v"]),
        ("node", ["-r../../outside.js", "app.js"]),
        ("ffmpeg", ["-i../../escape.mp4", "out.mp4"]),
        # Critical 2: Python short flags containing 'c' & -m module execution
        ("python", ["-Pc", "print(1)"]),
        ("python", ["-bc", "print(1)"]),
        ("python", ["-Rc", "print(1)"]),
        ("python", ["-tc", "print(1)"]),
        ("python", ["-Sc", "print(1)"]),
        ("python", ["-m", "pip", "list"]),
        ("python", ["-m", "timeit", "1+1"]),
        ("python", ["-m", "http.server"]),
        ("python", ["-m", "json.tool"]),
        ("python", ["-mpdb", "script.py"]),
        # Critical 3: yt-dlp dangerous flags
        ("yt-dlp", ["--exec-before-download", "echo pwn", "https://example.com/v"]),
        ("yt-dlp", ["--alias", "pwn", "--exec calc", "https://example.com/v"]),
        ("yt-dlp", ["--alias=pwn:--exec calc", "https://example.com/v"]),
        ("yt-dlp", ["--plugin-dirs", "/tmp/plugins", "https://example.com/v"]),
        ("yt-dlp", ["--plugin-dirs=/tmp/plugins", "https://example.com/v"]),
        ("yt-dlp", ["--use-postprocessor", "Exec", "https://example.com/v"]),
        ("yt-dlp", ["--config-location", "yt.conf", "https://example.com/v"]),
        ("yt-dlp", ["--cookies", "cookies.txt", "https://example.com/v"]),
        ("yt-dlp", ["--ffmpeg-location", "ffmpeg", "https://example.com/v"]),
        # Critical 4: ffmpeg/ffprobe filter graphs, avio protocols & SSRF URLs
        ("ffmpeg", ["-i", "in.mp4", "-vf", "drawtext=textfile=/etc/passwd", "out.mp4"]),
        ("ffmpeg", ["-i", "in.mp4", "-vf", "drawtext=textfile=../../secret.txt", "out.mp4"]),
        ("ffmpeg", ["-i", "in.mp4", "-vf", "movie=/etc/passwd", "out.mp4"]),
        ("ffmpeg", ["-i", "in.mp4", "-af", "amovie=../../secret.wav", "out.mp4"]),
        ("ffmpeg", ["-i", "in.mp4", "-vf", "subtitles=/etc/passwd", "out.mp4"]),
        ("ffmpeg", ["-i", "in.mp4", "-vf", "sendcmd=filename=/etc/passwd", "out.mp4"]),
        ("ffmpeg", ["-i", "in.mp4", "-filter_complex_script", "../../f.txt", "out.mp4"]),
        ("ffmpeg", ["-i", "in.mp4", "-filter_script", "/etc/passwd", "out.mp4"]),
        ("ffmpeg", ["-i", "in.mp4", "-vstats_file", "../../vstats.log", "out.mp4"]),
        ("ffmpeg", ["-i", "in.mp4", "-passlogfile", "../../pass", "out.mp4"]),
        ("ffmpeg", ["-i", "file:/etc/passwd", "out.mp4"]),
        ("ffmpeg", ["-i", "concat:/etc/passwd", "out.mp4"]),
        ("ffmpeg", ["-i", "subfile,,start,0,end,100,,:/etc/passwd", "out.mp4"]),
        ("ffmpeg", ["-i", "http://169.254.169.254/latest/meta-data/", "out.mp4"]),
        ("ffprobe", ["file:/etc/passwd"]),
        # Important 8: Node.js loader / debugger / env flags
        ("node", ["-r", "./hook.js", "app.js"]),
        ("node", ["--require", "./hook.js", "app.js"]),
        ("node", ["--require=./hook.js", "app.js"]),
        ("node", ["--import", "./hook.mjs", "app.js"]),
        ("node", ["--loader", "./loader.mjs", "app.js"]),
        ("node", ["--experimental-loader", "./loader.mjs", "app.js"]),
        ("node", ["--inspect", "app.js"]),
        ("node", ["--inspect-brk=0.0.0.0:9229", "app.js"]),
        ("node", ["--env-file=.env", "app.js"]),
        ("node", ["--watch", "app.js"]),
    ],
)
async def test_shell_executor_blocks_critical_flag_and_filter_bypasses(
    tmp_path: Path, executable: str, args: list[str]
):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    task_dir = ws_root / "task-sec"
    task_dir.mkdir()
    executor = ShellExecutor(workspace_root=ws_root, dns_resolver=_public_dns)
    with pytest.raises(SecurityPolicyError):
        await executor.run(executable, args, task_workspace=task_dir)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ssrf_url",
    [
        "http://localhost:8080/",
        "http://sub.localhost/admin",
        "http://printer.local/",
        "http://service.internal/secret",
        "http://2852039166/latest/meta-data/",
        "http://0xa9fea9fe/latest/meta-data/",
        "http://0251.0376.0251.0376/latest/meta-data/",
        "http://127.1/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/",
        "http://[::1]/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://100.64.0.1/",
    ],
)
async def test_shared_ssrf_blocks_localhost_internal_and_alt_ip_notations(
    tmp_path: Path, ssrf_url: str
):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    task_dir = ws_root / "task-ssrf"
    task_dir.mkdir()

    fake_browser = FakeBrowser()
    async with BrowserController(workspace_root=ws_root, browser=fake_browser) as ctrl:
        with pytest.raises(BrowserPolicyError):
            await ctrl.navigate(ssrf_url, task_workspace=task_dir)

    executor = ShellExecutor(workspace_root=ws_root)
    with pytest.raises(SecurityPolicyError):
        await executor.run("yt-dlp", [ssrf_url], task_workspace=task_dir)


@pytest.mark.asyncio
async def test_ssrf_fails_closed_on_private_dns_rebinding_and_dns_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    task_dir = ws_root / "task-dns"
    task_dir.mkdir()

    # 1. DNS rebinding / private IP resolution via dns_resolver
    async with BrowserController(
        workspace_root=ws_root,
        browser=FakeBrowser(),
        dns_resolver=lambda _host: ["127.0.0.1"],
    ) as ctrl:
        with pytest.raises(BrowserPolicyError):
            await ctrl.navigate("https://rebind.example.com", task_workspace=task_dir)

    # 2. Default socket.getaddrinfo returning link-local metadata IP
    def fake_getaddrinfo_private(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_private)
    async with BrowserController(workspace_root=ws_root, browser=FakeBrowser()) as ctrl:
        with pytest.raises(BrowserPolicyError):
            await ctrl.navigate("https://evil-dns.example.com", task_workspace=task_dir)

    # 3. Default socket.getaddrinfo failing (offline / NXDOMAIN) -> fail closed
    def fake_getaddrinfo_fail(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise socket.gaierror("DNS failure")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_fail)
    async with BrowserController(workspace_root=ws_root, browser=FakeBrowser()) as ctrl:
        with pytest.raises(BrowserPolicyError):
            await ctrl.navigate("https://unresolvable.example.com", task_workspace=task_dir)


@pytest.mark.asyncio
async def test_browser_controller_blocks_ssrf_redirects_and_isolates_render_html(
    tmp_path: Path,
):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    task_dir = ws_root / "task-redir"
    task_dir.mkdir()

    # 1. Redirect from safe public URL to metadata SSRF target must be aborted & rejected
    redir_page = FakePage(redirect_to="http://169.254.169.254/latest/meta-data/")
    fake_browser = FakeBrowser(redir_page)
    async with BrowserController(
        workspace_root=ws_root, browser=fake_browser, dns_resolver=_public_dns
    ) as ctrl:
        with pytest.raises(BrowserPolicyError):
            await ctrl.navigate("https://example.com/start", task_workspace=task_dir)

    # 2. render_html_to_png uses isolated page/context, blocks http/file subresources, bounds viewport
    active_page = FakePage(url="https://example.com/active")
    iso_browser = FakeBrowser(active_page)
    async with BrowserController(
        workspace_root=ws_root, browser=iso_browser, dns_resolver=_public_dns
    ) as ctrl:
        await ctrl.navigate("https://example.com/active", task_workspace=task_dir)
        out_png = task_dir / "card.png"
        res = await ctrl.render_html_to_png(
            "<img src='https://evil.com/leak.png'><img src='file:///etc/passwd'>",
            out_png,
            width=800,
            height=600,
            task_workspace=task_dir,
        )
        assert res.status == BrowserGateStatus.OK
        assert out_png.exists()

        # Caller's active page was NOT modified or closed
        assert active_page.set_content_calls == []
        assert active_page.viewport_sizes == []
        assert active_page.closed is False

        # Isolated context/page had route handlers blocking external/file subresources and closed
        assert len(iso_browser.extra_pages) == 1
        iso_page = iso_browser.extra_pages[0]
        assert iso_page.closed is True
        assert iso_browser.contexts[-1].closed is True

        iso_handlers = iso_browser.contexts[-1].route_handlers
        assert len(iso_handlers) == 1
        http_route = FakeRoute("https://evil.com/leak.png")
        file_route = FakeRoute("file:///etc/passwd")
        data_route = FakeRoute("data:image/png;base64,AAAA")
        await iso_handlers[0](http_route)
        await iso_handlers[0](file_route)
        await iso_handlers[0](data_route)
        assert http_route.aborted is True
        assert file_route.aborted is True
        assert data_route.continued is True

        # Viewport bounds enforced
        with pytest.raises(ValueError):
            await ctrl.render_html_to_png(
                "<h1>Too big</h1>", out_png, width=5000, height=720, task_workspace=task_dir
            )
        with pytest.raises(ValueError):
            await ctrl.render_html_to_png(
                "<h1>Zero</h1>", out_png, width=0, height=720, task_workspace=task_dir
            )


@pytest.mark.asyncio
async def test_strict_task_workspace_isolation_forbids_root_and_db_chroma_dirs(
    tmp_path: Path,
):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (ws_root / "app.db").write_text("db", encoding="utf-8")
    chroma_dir = ws_root / "chroma"
    chroma_dir.mkdir()
    bad_task_with_db = ws_root / "bad-task"
    bad_task_with_db.mkdir()
    (bad_task_with_db / "checkpoints.db").write_text("ckpt", encoding="utf-8")

    task_dir = ws_root / "good-task"
    task_dir.mkdir()
    local_html = task_dir / "page.html"
    local_html.write_text("<p>hi</p>", encoding="utf-8")

    executor = ShellExecutor(workspace_root=ws_root)
    with pytest.raises(SecurityPolicyError):
        await executor.run("python", ["--version"], task_workspace=ws_root)
    with pytest.raises(SecurityPolicyError):
        await executor.run("python", ["--version"], task_workspace=chroma_dir)
    with pytest.raises(SecurityPolicyError):
        await executor.run("python", ["--version"], task_workspace=bad_task_with_db)

    async with BrowserController(
        workspace_root=ws_root, browser=FakeBrowser(), dns_resolver=_public_dns
    ) as ctrl:
        with pytest.raises(BrowserPolicyError):
            await ctrl.navigate(local_html.as_uri(), task_workspace=None)
        with pytest.raises(BrowserPolicyError):
            await ctrl.screenshot(task_dir / "a.png", task_workspace=None)
        with pytest.raises(BrowserPolicyError):
            await ctrl.render_html_to_png("<p>x</p>", task_dir / "b.png", task_workspace=None)
        with pytest.raises(BrowserPolicyError):
            await ctrl.screenshot(ws_root / "a.png", task_workspace=ws_root)

    settings = AppSettings(workspace_dir=ws_root)
    async with McpGateway(
        settings=settings,
        browser_controller=BrowserController(
            workspace_root=ws_root, browser=FakeBrowser(), dns_resolver=_public_dns
        ),
    ) as gateway:
        with pytest.raises(SecurityPolicyError):
            await gateway.call_tool(
                "shell.run",
                {"executable": "python", "args": ["--version"]},
                task_workspace=ws_root,
            )


@pytest.mark.asyncio
async def test_secret_masking_on_args_errors_and_gateway_param_validation(
    tmp_path: Path,
):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    task_dir = ws_root / "task-mask"
    task_dir.mkdir()
    script = task_dir / "echo_arg.py"
    script.write_text("import sys; print('ok')", encoding="utf-8")

    secret = "sk-verysecretvalue99999"
    executor = ShellExecutor(workspace_root=ws_root, extra_secrets=[secret])

    res = await executor.run(
        "python", ["echo_arg.py", f"--token={secret}"], task_workspace=task_dir
    )
    assert all(secret not in a for a in res.args)
    assert any("***REDACTED***" in a for a in res.args)

    with pytest.raises(SecurityPolicyError) as exc_info:
        await executor.run("python", ["-c", secret], task_workspace=task_dir)
    assert secret not in str(exc_info.value)

    settings = AppSettings(workspace_dir=ws_root, local_auth_token="tok-secret-888")
    gateway = McpGateway(
        settings=settings,
        browser_controller=BrowserController(
            workspace_root=ws_root, browser=FakeBrowser(), dns_resolver=_public_dns
        ),
    )
    assert "tok-secret-888" in gateway.shell.extra_secrets
    assert "tok-secret-888" in gateway.browser.extra_secrets
    with pytest.raises(ValueError, match="Missing required parameter"):
        await gateway.call_tool("shell.run", {}, task_workspace=task_dir)
    await gateway.close()


@pytest.mark.asyncio
async def test_browser_controller_bounds_title_content_and_evaluate_timeouts(
    tmp_path: Path,
):
    class HangingPage(FakePage):
        async def title(self) -> str:
            await asyncio.sleep(5)
            return "never"

        async def content(self) -> str:
            await asyncio.sleep(5)
            return "never"

        async def evaluate(self, script: str) -> Any:
            await asyncio.sleep(5)
            return {}

    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    task_dir = ws_root / "task-hang"
    task_dir.mkdir()

    async with BrowserController(
        workspace_root=ws_root,
        action_timeout_s=0.05,
        browser=FakeBrowser(HangingPage()),
        dns_resolver=_public_dns,
    ) as ctrl:
        snap = await ctrl.take_snapshot(task_workspace=task_dir)
        assert snap.status == BrowserGateStatus.OK
        assert snap.title == ""


@pytest.mark.asyncio
async def test_shell_executor_fails_closed_when_binary_missing_and_cleans_up_on_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    task_dir = ws_root / "task-minor"
    task_dir.mkdir()

    # Minor 12: shutil.which returning None must fail closed rather than falling back to bare name
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)
    executor = ShellExecutor(workspace_root=ws_root)
    with pytest.raises(FileNotFoundError):
        await executor.run("ffmpeg", ["-version"], task_workspace=task_dir)

    # Minor 13: CancelledError during run kills the process tree cleanly
    pid_file = task_dir / "cancel.pid"
    script = task_dir / "wait_forever.py"
    script.write_text(
        "\n".join(
            [
                "import os, pathlib, time",
                f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8')",
                "time.sleep(60)",
            ]
        ),
        encoding="utf-8",
    )

    task = asyncio.create_task(
        executor.run("python", ["wait_forever.py"], task_workspace=task_dir, timeout_s=30)
    )
    deadline = time.monotonic() + 3.0
    while not pid_file.exists() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    assert pid_file.exists()
    child_pid = int(pid_file.read_text(encoding="utf-8").strip())

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Confirm child process exited after cancellation
    kill_deadline = time.monotonic() + 2.0
    alive = True
    while time.monotonic() < kill_deadline:
        if sys.platform == "win32":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, child_pid)
            if not handle:
                alive = False
                break
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            if not ok or exit_code.value != 259:
                alive = False
                break
        else:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                alive = False
                break
        await asyncio.sleep(0.05)
    assert alive is False
