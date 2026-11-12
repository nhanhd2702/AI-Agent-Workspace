"""Sandboxed Playwright BrowserController MCP Server (Task 3.1)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import inspect
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Iterable, Optional
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from app.config import get_settings
from app.mcp.security import (
    SecurityPolicyError,
    mask_policy_text,
    validate_safe_http_url,
    validate_task_workspace,
)
from app.orchestrator.dispatcher import mask_secrets


class BrowserPolicyError(SecurityPolicyError):
    """Raised when a browser URL or file path violates security policy."""


class CaptchaRequiredError(Exception):
    """Optional exception representation when an automated browser hits a human gate."""


class BrowserGateStatus(str, Enum):
    """Execution status values returned by BrowserController actions."""

    OK = "OK"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


@dataclass
class BrowserActionResult:
    """Structured result returned by BrowserController actions."""

    status: str
    action: str
    url: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    gate_type: Optional[str] = None
    message: Optional[str] = None
    screenshot_path: Optional[str] = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "action": self.action,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "data": self.data,
            "gate_type": self.gate_type,
            "message": self.message,
            "screenshot_path": self.screenshot_path,
            "duration_ms": self.duration_ms,
        }


_CAPTCHA_SELECTORS: tuple[str, ...] = (
    "iframe[src*='recaptcha']",
    ".g-recaptcha",
    "#g-recaptcha",
    "iframe[src*='hcaptcha']",
    ".h-captcha",
    "iframe[src*='challenges.cloudflare.com']",
    ".cf-turnstile",
    "#cf-challenge-running",
    "[name='cf-turnstile-response']",
    "[data-sitekey]",
)

_TWO_FA_SELECTORS: tuple[str, ...] = (
    "input[autocomplete='one-time-code']",
    "input[name*='otp' i]",
    "input[name*='totp' i]",
    "input[name*='2fa' i]",
)

_PAYMENT_SELECTORS: tuple[str, ...] = (
    "iframe[src*='js.stripe.com']",
    "iframe[src*='checkout.stripe.com']",
    "iframe[src*='paypal.com']",
    "input[autocomplete='cc-number']",
    "input[name*='cardnumber' i]",
)

_CAPTCHA_TEXT_RE = re.compile(
    r"(verify you are human|are you a robot|complete the captcha|attention required!\s*\|\s*cloudflare|checking your browser|please solve the captcha|recaptcha|hcaptcha|turnstile)",
    re.IGNORECASE,
)

_TWO_FA_TEXT_RE = re.compile(
    r"(two-factor authentication|2-step verification|enter verification code|authenticator app|one-time password|enter the 6-digit code)",
    re.IGNORECASE,
)

_PAYMENT_TEXT_RE = re.compile(
    r"(complete your payment|enter payment details|credit card number|cardholder name)",
    re.IGNORECASE,
)

_SAFE_INLINE_DATA_PREFIXES: tuple[str, ...] = (
    "data:image/",
    "data:text/css",
    "data:font/",
    "data:application/font",
)


class BrowserController:
    """Playwright wrapper enforcing 30s action timeouts, SSRF/path policy, gate detection, and cleanup."""

    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        action_timeout_s: float = 30.0,
        headless: bool = True,
        playwright_factory: Optional[Callable[[], Any]] = None,
        browser: Optional[Any] = None,
        allow_private_network: bool = False,
        extra_secrets: Optional[Iterable[str]] = None,
        dns_resolver: Optional[Callable[[str], Iterable[str]]] = None,
    ) -> None:
        if action_timeout_s <= 0:
            raise ValueError("action_timeout_s must be > 0")

        self.workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root is not None
            else get_settings().workspace_dir.resolve()
        )
        self.action_timeout_s = float(action_timeout_s)
        self.headless = headless
        self._playwright_factory = playwright_factory
        self._browser = browser
        self._playwright: Any = None
        self._contexts: list[Any] = []
        self._pages: list[Any] = []
        self._page: Any = None
        self._active_task_workspace: Optional[Path] = None
        self._blocked_request_error: Optional[str] = None
        self.allow_private_network = allow_private_network
        self.dns_resolver = dns_resolver

        secrets: list[str] = []
        if extra_secrets is not None:
            secrets.extend(str(s) for s in extra_secrets if s)
        else:
            settings = get_settings()
            if settings.local_auth_token:
                secrets.append(settings.local_auth_token)
            if settings.encryption_key:
                secrets.append(settings.encryption_key.decode("utf-8", errors="ignore"))
        self.extra_secrets = secrets

    @property
    def action_timeout_ms(self) -> int:
        return int(self.action_timeout_s * 1000)

    def _mask(self, data: Any) -> Any:
        return mask_secrets(data, extra_secrets=self.extra_secrets)

    def _policy_error(self, message: str) -> BrowserPolicyError:
        return BrowserPolicyError(mask_policy_text(message, self.extra_secrets))

    async def __aenter__(self) -> "BrowserController":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def _ensure_browser(self) -> Any:
        if self._browser is not None:
            return self._browser

        if self._playwright_factory is not None:
            pw_candidate = self._playwright_factory()
            if inspect.isawaitable(pw_candidate):
                pw_candidate = await pw_candidate
            if hasattr(pw_candidate, "start") and callable(pw_candidate.start):
                started = pw_candidate.start()
                self._playwright = (
                    await started if inspect.isawaitable(started) else started
                )
            else:
                self._playwright = pw_candidate
        else:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise RuntimeError(
                    "Playwright is not installed. Install with `pip install playwright && playwright install chromium`."
                ) from exc
            self._playwright = await async_playwright().start()

        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        return self._browser

    async def _attach_browsing_route(self, context: Any) -> None:
        if not (hasattr(context, "route") and callable(context.route)):
            return

        async def _route_handler(route: Any) -> None:
            req_url = getattr(getattr(route, "request", None), "url", "") or ""
            if req_url == "about:blank":
                await route.continue_()
                return
            try:
                self.validate_url(req_url, task_workspace=self._active_task_workspace)
            except BrowserPolicyError as exc:
                self._blocked_request_error = str(exc)
                try:
                    await route.abort()
                except Exception:
                    pass
                return
            try:
                await route.continue_()
            except Exception:
                pass

        await context.route("**/*", _route_handler)

    async def _ensure_page(self) -> Any:
        if self._page is not None and not getattr(self._page, "closed", False):
            return self._page

        browser = await self._ensure_browser()
        context = await browser.new_context()
        self._contexts.append(context)
        await self._attach_browsing_route(context)
        page = await context.new_page()
        self._pages.append(page)
        if hasattr(page, "set_default_timeout") and callable(page.set_default_timeout):
            page.set_default_timeout(self.action_timeout_ms)
        self._page = page
        return page

    async def close(self) -> None:
        """Close all opened pages, contexts, browser, and Playwright driver cleanly."""
        for page in reversed(self._pages):
            try:
                if hasattr(page, "close") and callable(page.close):
                    res = page.close()
                    if inspect.isawaitable(res):
                        await res
            except Exception:
                pass
        self._pages.clear()
        self._page = None

        for ctx in reversed(self._contexts):
            try:
                if hasattr(ctx, "close") and callable(ctx.close):
                    res = ctx.close()
                    if inspect.isawaitable(res):
                        await res
            except Exception:
                pass
        self._contexts.clear()

        if self._browser is not None:
            try:
                if hasattr(self._browser, "close") and callable(self._browser.close):
                    res = self._browser.close()
                    if inspect.isawaitable(res):
                        await res
            except Exception:
                pass
            self._browser = None

        if self._playwright is not None:
            try:
                if hasattr(self._playwright, "stop") and callable(self._playwright.stop):
                    res = self._playwright.stop()
                    if inspect.isawaitable(res):
                        await res
            except Exception:
                pass
            self._playwright = None

    def _validate_task_workspace(
        self,
        task_workspace: Optional[Path],
        *,
        required: bool = False,
    ) -> Optional[Path]:
        if task_workspace is None:
            if required:
                raise self._policy_error(
                    "Explicit task_workspace is required for local file or screenshot operations"
                )
            return None
        return validate_task_workspace(
            task_workspace,
            self.workspace_root,
            error_cls=BrowserPolicyError,
            extra_secrets=self.extra_secrets,
        )

    def _validate_output_path(
        self,
        output_path: Path | str,
        task_workspace: Optional[Path] = None,
    ) -> Path:
        raw_str = str(output_path)
        if not raw_str or "\x00" in raw_str:
            raise self._policy_error("Invalid screenshot output path")
        if raw_str.startswith("\\\\") or raw_str.startswith("//"):
            raise self._policy_error(f"UNC output path forbidden: {raw_str!r}")
        if re.match(r"^[A-Za-z]:[/\\]", raw_str) and sys.platform != "win32":
            raise self._policy_error(f"Windows drive path forbidden: {raw_str!r}")

        base_dir = self._validate_task_workspace(task_workspace, required=True)
        assert base_dir is not None
        candidate = Path(output_path)
        resolved = (
            (base_dir / candidate).resolve()
            if not candidate.is_absolute()
            else candidate.resolve()
        )
        if not resolved.is_relative_to(base_dir):
            raise self._policy_error(
                f"Output path '{output_path}' escapes task_workspace '{base_dir}'"
            )
        return resolved

    def validate_url(
        self,
        url: str,
        task_workspace: Optional[Path] = None,
    ) -> str:
        if not isinstance(url, str) or not url.strip():
            raise self._policy_error("URL must be a non-empty string")
        if any(ch in url for ch in ("\n", "\r", "\x00")):
            raise self._policy_error("URL contains forbidden control characters")

        stripped = url.strip()
        parsed = urlparse(stripped)
        scheme = parsed.scheme.lower()
        if not scheme:
            raise self._policy_error(f"URL missing scheme: {url!r}")

        if scheme == "file":
            if parsed.netloc and parsed.netloc.lower() not in {"localhost", ""}:
                raise self._policy_error(f"Remote file:// host forbidden: {url!r}")
            base_dir = self._validate_task_workspace(task_workspace, required=True)
            assert base_dir is not None
            local_str = url2pathname(unquote(parsed.path))
            resolved = Path(local_str).resolve()
            if not resolved.is_relative_to(base_dir):
                raise self._policy_error(
                    f"file:// URL '{url}' escapes task_workspace '{base_dir}'"
                )
            return stripped

        if scheme in {"http", "https"}:
            return validate_safe_http_url(
                stripped,
                allow_private_network=self.allow_private_network,
                dns_resolver=self.dns_resolver,
                error_cls=BrowserPolicyError,
                extra_secrets=self.extra_secrets,
            )

        raise self._policy_error(
            f"Blocked unsupported or unsafe URL scheme: {scheme!r}"
        )

    async def _bounded(self, awaitable: Any, default: Any = None) -> Any:
        try:
            return await asyncio.wait_for(awaitable, timeout=self.action_timeout_s)
        except Exception:
            return default

    async def _safe_page_title(self, page: Any) -> str:
        if hasattr(page, "title") and callable(page.title):
            res = await self._bounded(page.title(), default="")
            return str(res or "")
        return ""

    async def _safe_page_text(self, page: Any) -> str:
        if hasattr(page, "inner_text") and callable(page.inner_text):
            res = await self._bounded(
                page.inner_text("body", timeout=min(self.action_timeout_ms, 5000)),
                default=None,
            )
            if res is not None:
                return str(res)
        if hasattr(page, "content") and callable(page.content):
            res = await self._bounded(page.content(), default="")
            return str(res or "")
        return ""

    async def _matches_any_selector(
        self, page: Any, selectors: tuple[str, ...]
    ) -> Optional[str]:
        if not (hasattr(page, "query_selector") and callable(page.query_selector)):
            return None
        for sel in selectors:
            match = await self._bounded(page.query_selector(sel), default=None)
            if match is not None:
                return sel
        return None

    async def _detect_gate(self, page: Any) -> Optional[tuple[str, str]]:
        """Detect CAPTCHA, 2FA/OTP, or payment checkout gates without interacting with them."""
        sel_match = await self._matches_any_selector(page, _CAPTCHA_SELECTORS)
        if sel_match:
            return ("captcha", f"selector:{sel_match}")

        sel_match = await self._matches_any_selector(page, _TWO_FA_SELECTORS)
        if sel_match:
            return ("2fa", f"selector:{sel_match}")

        sel_match = await self._matches_any_selector(page, _PAYMENT_SELECTORS)
        if sel_match:
            return ("payment", f"selector:{sel_match}")

        title = await self._safe_page_title(page)
        body_text = await self._safe_page_text(page)
        combined = f"{title}\n{body_text}"

        if _CAPTCHA_TEXT_RE.search(combined):
            return ("captcha", "text_pattern")
        if _TWO_FA_TEXT_RE.search(combined):
            return ("2fa", "text_pattern")
        if _PAYMENT_TEXT_RE.search(combined):
            return ("payment", "text_pattern")

        return None

    async def _check_gate_result(
        self, page: Any, action: str, t0: float
    ) -> Optional[BrowserActionResult]:
        gate = await self._detect_gate(page)
        if gate is None:
            return None
        gate_type, reason = gate
        current_url = str(self._mask(getattr(page, "url", "") or ""))
        title = str(self._mask(await self._safe_page_title(page)))
        duration_ms = max(0, int((time.perf_counter() - t0) * 1000))
        return BrowserActionResult(
            status=BrowserGateStatus.CAPTCHA_REQUIRED.value,
            action=action,
            url=current_url,
            title=title,
            gate_type=gate_type,
            message=(
                f"Automated execution halted: {gate_type} gate detected ({reason}). "
                "Human intervention required."
            ),
            duration_ms=duration_ms,
        )

    async def navigate(
        self,
        url: str,
        *,
        task_workspace: Optional[Path] = None,
        wait_until: str = "domcontentloaded",
    ) -> BrowserActionResult:
        t0 = time.perf_counter()
        ws = self._validate_task_workspace(task_workspace, required=False)
        safe_url = self.validate_url(url, task_workspace=ws)
        self._active_task_workspace = ws
        self._blocked_request_error = None

        page = await self._ensure_page()
        try:
            await page.goto(
                safe_url, wait_until=wait_until, timeout=self.action_timeout_ms
            )
        except Exception as exc:
            if self._blocked_request_error:
                raise self._policy_error(self._blocked_request_error) from exc
            raise

        if self._blocked_request_error:
            raise self._policy_error(self._blocked_request_error)

        final_url = getattr(page, "url", "") or ""
        if final_url and final_url != "about:blank":
            self.validate_url(final_url, task_workspace=ws)

        gate_result = await self._check_gate_result(page, "navigate", t0)
        if gate_result is not None:
            return gate_result

        return BrowserActionResult(
            status=BrowserGateStatus.OK.value,
            action="navigate",
            url=str(self._mask(final_url or safe_url)),
            title=str(self._mask(await self._safe_page_title(page))),
            duration_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        )

    async def click(
        self,
        selector: str,
        *,
        task_workspace: Optional[Path] = None,
    ) -> BrowserActionResult:
        t0 = time.perf_counter()
        ws = self._validate_task_workspace(task_workspace, required=False)
        self._active_task_workspace = ws
        self._blocked_request_error = None
        page = await self._ensure_page()
        gate_before = await self._check_gate_result(page, "click", t0)
        if gate_before is not None:
            return gate_before

        try:
            await page.click(selector, timeout=self.action_timeout_ms)
        except Exception as exc:
            if self._blocked_request_error:
                raise self._policy_error(self._blocked_request_error) from exc
            raise

        if self._blocked_request_error:
            raise self._policy_error(self._blocked_request_error)

        gate_after = await self._check_gate_result(page, "click", t0)
        if gate_after is not None:
            return gate_after

        return BrowserActionResult(
            status=BrowserGateStatus.OK.value,
            action="click",
            url=str(self._mask(getattr(page, "url", ""))),
            title=str(self._mask(await self._safe_page_title(page))),
            duration_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        )

    async def fill(
        self,
        selector: str,
        value: str,
        *,
        task_workspace: Optional[Path] = None,
    ) -> BrowserActionResult:
        t0 = time.perf_counter()
        self._validate_task_workspace(task_workspace, required=False)
        page = await self._ensure_page()
        gate_before = await self._check_gate_result(page, "fill", t0)
        if gate_before is not None:
            return gate_before

        await page.fill(selector, value, timeout=self.action_timeout_ms)

        gate_after = await self._check_gate_result(page, "fill", t0)
        if gate_after is not None:
            return gate_after

        return BrowserActionResult(
            status=BrowserGateStatus.OK.value,
            action="fill",
            url=str(self._mask(getattr(page, "url", ""))),
            title=str(self._mask(await self._safe_page_title(page))),
            duration_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        )

    async def extract_text(
        self,
        selector: str = "body",
        *,
        task_workspace: Optional[Path] = None,
    ) -> BrowserActionResult:
        t0 = time.perf_counter()
        self._validate_task_workspace(task_workspace, required=False)
        page = await self._ensure_page()
        gate_result = await self._check_gate_result(page, "extract_text", t0)
        if gate_result is not None:
            return gate_result

        raw_text = await page.inner_text(selector, timeout=self.action_timeout_ms)
        masked_text = str(self._mask(raw_text or ""))
        return BrowserActionResult(
            status=BrowserGateStatus.OK.value,
            action="extract_text",
            url=str(self._mask(getattr(page, "url", ""))),
            title=str(self._mask(await self._safe_page_title(page))),
            content=masked_text,
            duration_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        )

    async def take_snapshot(
        self,
        *,
        task_workspace: Optional[Path] = None,
    ) -> BrowserActionResult:
        t0 = time.perf_counter()
        self._validate_task_workspace(task_workspace, required=False)
        page = await self._ensure_page()
        gate_result = await self._check_gate_result(page, "take_snapshot", t0)
        if gate_result is not None:
            return gate_result

        raw_text = await self._safe_page_text(page)
        title = await self._safe_page_title(page)
        current_url = getattr(page, "url", "") or ""

        dom_summary: dict[str, Any] = {}
        if hasattr(page, "evaluate") and callable(page.evaluate):
            evaluated = await self._bounded(
                page.evaluate(
                    """() => ({
                        links: Array.from(document.querySelectorAll('a[href]')).slice(0, 50).map(a => ({text: (a.innerText || '').trim(), href: a.href})),
                        inputs: Array.from(document.querySelectorAll('input, textarea, select')).slice(0, 50).map(el => ({name: el.name || el.id || '', type: el.type || el.tagName.toLowerCase()})),
                        buttons: Array.from(document.querySelectorAll('button, [role="button"]')).slice(0, 50).map(b => (b.innerText || '').trim())
                    })"""
                ),
                default={},
            )
            if isinstance(evaluated, dict):
                dom_summary = evaluated

        masked_data = self._mask(
            {
                "url": current_url,
                "title": title,
                "text": raw_text[:20000],
                **dom_summary,
            }
        )
        return BrowserActionResult(
            status=BrowserGateStatus.OK.value,
            action="take_snapshot",
            url=str(self._mask(current_url)),
            title=str(self._mask(title)),
            content=str(self._mask(raw_text[:20000])),
            data=masked_data,
            duration_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        )

    async def screenshot(
        self,
        output_path: Path | str,
        *,
        full_page: bool = True,
        selector: Optional[str] = None,
        task_workspace: Optional[Path] = None,
    ) -> BrowserActionResult:
        t0 = time.perf_counter()
        resolved_out = self._validate_output_path(
            output_path, task_workspace=task_workspace
        )
        resolved_out.parent.mkdir(parents=True, exist_ok=True)

        page = await self._ensure_page()
        gate_result = await self._check_gate_result(page, "screenshot", t0)
        if gate_result is not None:
            return gate_result

        if selector:
            locator = page.locator(selector)
            await locator.screenshot(
                path=str(resolved_out), timeout=self.action_timeout_ms
            )
        else:
            await page.screenshot(
                path=str(resolved_out),
                full_page=full_page,
                timeout=self.action_timeout_ms,
            )

        return BrowserActionResult(
            status=BrowserGateStatus.OK.value,
            action="screenshot",
            url=str(self._mask(getattr(page, "url", ""))),
            title=str(self._mask(await self._safe_page_title(page))),
            screenshot_path=str(resolved_out),
            duration_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        )

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
        """Render local HTML content in an isolated context with external/file subresources blocked."""
        t0 = time.perf_counter()
        if not (1 <= int(width) <= 4096) or not (1 <= int(height) <= 4096):
            raise ValueError("Viewport width and height must be between 1 and 4096")

        resolved_out = self._validate_output_path(
            output_path, task_workspace=task_workspace
        )
        resolved_out.parent.mkdir(parents=True, exist_ok=True)

        browser = await self._ensure_browser()
        iso_context = await browser.new_context()
        iso_page: Any = None
        try:
            if hasattr(iso_context, "route") and callable(iso_context.route):
                async def _isolated_route(route: Any) -> None:
                    req_url = getattr(getattr(route, "request", None), "url", "") or ""
                    lower = req_url.strip().lower()
                    if lower == "about:blank" or lower.startswith(_SAFE_INLINE_DATA_PREFIXES):
                        await route.continue_()
                        return
                    await route.abort()

                await iso_context.route("**/*", _isolated_route)

            iso_page = await iso_context.new_page()
            if hasattr(iso_page, "set_default_timeout") and callable(
                iso_page.set_default_timeout
            ):
                iso_page.set_default_timeout(self.action_timeout_ms)
            if hasattr(iso_page, "set_viewport_size") and callable(
                iso_page.set_viewport_size
            ):
                await iso_page.set_viewport_size(
                    {"width": int(width), "height": int(height)}
                )
            await iso_page.set_content(html, timeout=self.action_timeout_ms)
            await iso_page.screenshot(
                path=str(resolved_out),
                full_page=full_page,
                timeout=self.action_timeout_ms,
            )
        finally:
            if iso_page is not None:
                try:
                    res = iso_page.close()
                    if inspect.isawaitable(res):
                        await res
                except Exception:
                    pass
            try:
                res = iso_context.close()
                if inspect.isawaitable(res):
                    await res
            except Exception:
                pass

        return BrowserActionResult(
            status=BrowserGateStatus.OK.value,
            action="render_html_to_png",
            screenshot_path=str(resolved_out),
            duration_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        )
