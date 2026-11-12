"""Sandboxed Playwright BrowserController MCP Server (Task 3.1)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import inspect
import ipaddress
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Iterable, Optional
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from app.config import get_settings
from app.mcp.shell_server import SecurityPolicyError
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


_BLOCKED_METADATA_HOSTS: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "169.254.169.254",
        "100.100.100.200",
        "fd00:ec2::254",
    }
)

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
        self.allow_private_network = allow_private_network

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

    async def __aenter__(self) -> "BrowserController":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def _ensure_page(self) -> Any:
        if self._page is not None and not getattr(self._page, "closed", False):
            return self._page

        if self._browser is None:
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

        context = await self._browser.new_context()
        self._contexts.append(context)
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

    def _validate_task_workspace(self, task_workspace: Optional[Path]) -> Path:
        if task_workspace is None:
            return self.workspace_root
        resolved = Path(task_workspace).resolve()
        if not resolved.is_relative_to(self.workspace_root):
            raise BrowserPolicyError(
                f"task_workspace '{task_workspace}' escapes workspace_root '{self.workspace_root}'"
            )
        if not resolved.exists() or not resolved.is_dir():
            raise BrowserPolicyError(
                f"task_workspace '{task_workspace}' must be an existing directory"
            )
        return resolved

    def _validate_output_path(
        self,
        output_path: Path | str,
        task_workspace: Optional[Path] = None,
    ) -> Path:
        raw_str = str(output_path)
        if not raw_str or "\x00" in raw_str:
            raise BrowserPolicyError("Invalid screenshot output path")
        if raw_str.startswith("\\\\") or raw_str.startswith("//"):
            raise BrowserPolicyError(f"UNC output path forbidden: {raw_str!r}")
        if re.match(r"^[A-Za-z]:[/\\]", raw_str) and sys.platform != "win32":
            raise BrowserPolicyError(f"Windows drive path forbidden: {raw_str!r}")

        base_dir = self._validate_task_workspace(task_workspace)
        candidate = Path(output_path)
        resolved = (
            (base_dir / candidate).resolve()
            if not candidate.is_absolute()
            else candidate.resolve()
        )
        if not resolved.is_relative_to(base_dir):
            raise BrowserPolicyError(
                f"Output path '{output_path}' escapes allowed workspace '{base_dir}'"
            )
        return resolved

    def validate_url(
        self,
        url: str,
        task_workspace: Optional[Path] = None,
    ) -> str:
        if not isinstance(url, str) or not url.strip():
            raise BrowserPolicyError("URL must be a non-empty string")
        if any(ch in url for ch in ("\n", "\r", "\x00")):
            raise BrowserPolicyError("URL contains forbidden control characters")

        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        if not scheme:
            raise BrowserPolicyError(f"URL missing scheme: {url!r}")

        if scheme == "file":
            if parsed.netloc and parsed.netloc.lower() not in {"localhost", ""}:
                raise BrowserPolicyError(f"Remote file:// host forbidden: {url!r}")
            local_str = url2pathname(unquote(parsed.path))
            base_dir = self._validate_task_workspace(task_workspace)
            resolved = Path(local_str).resolve()
            if not resolved.is_relative_to(base_dir):
                raise BrowserPolicyError(
                    f"file:// URL '{url}' escapes allowed workspace '{base_dir}'"
                )
            return url.strip()

        if scheme not in {"http", "https"}:
            raise BrowserPolicyError(
                f"Blocked unsupported or unsafe URL scheme: {scheme!r}"
            )

        hostname = parsed.hostname
        if not hostname:
            raise BrowserPolicyError(f"URL missing hostname: {url!r}")

        if not self.allow_private_network:
            host_norm = hostname.lower().rstrip(".")
            if host_norm in _BLOCKED_METADATA_HOSTS:
                raise BrowserPolicyError(
                    f"SSRF protection blocked metadata host: {hostname!r}"
                )
            try:
                ip = ipaddress.ip_address(host_norm)
            except ValueError:
                ip = None
            if ip is not None and (ip.is_link_local or ip.is_unspecified or ip.is_multicast):
                raise BrowserPolicyError(
                    f"SSRF protection blocked restricted IP address: {hostname!r}"
                )

        return url.strip()

    async def _safe_page_title(self, page: Any) -> str:
        try:
            if hasattr(page, "title") and callable(page.title):
                return str(await page.title() or "")
        except Exception:
            pass
        return ""

    async def _safe_page_text(self, page: Any) -> str:
        try:
            if hasattr(page, "inner_text") and callable(page.inner_text):
                return str(await page.inner_text("body", timeout=2000) or "")
        except Exception:
            pass
        try:
            if hasattr(page, "content") and callable(page.content):
                return str(await page.content() or "")
        except Exception:
            pass
        return ""

    async def _matches_any_selector(
        self, page: Any, selectors: tuple[str, ...]
    ) -> Optional[str]:
        if not (hasattr(page, "query_selector") and callable(page.query_selector)):
            return None
        for sel in selectors:
            try:
                match = await page.query_selector(sel)
                if match is not None:
                    return sel
            except Exception:
                continue
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
        safe_url = self.validate_url(url, task_workspace=task_workspace)
        page = await self._ensure_page()
        await page.goto(safe_url, wait_until=wait_until, timeout=self.action_timeout_ms)

        gate_result = await self._check_gate_result(page, "navigate", t0)
        if gate_result is not None:
            return gate_result

        return BrowserActionResult(
            status=BrowserGateStatus.OK.value,
            action="navigate",
            url=str(self._mask(getattr(page, "url", safe_url))),
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
        self._validate_task_workspace(task_workspace)
        page = await self._ensure_page()
        gate_before = await self._check_gate_result(page, "click", t0)
        if gate_before is not None:
            return gate_before

        await page.click(selector, timeout=self.action_timeout_ms)

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
        self._validate_task_workspace(task_workspace)
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
        self._validate_task_workspace(task_workspace)
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
        self._validate_task_workspace(task_workspace)
        page = await self._ensure_page()
        gate_result = await self._check_gate_result(page, "take_snapshot", t0)
        if gate_result is not None:
            return gate_result

        raw_text = await self._safe_page_text(page)
        title = await self._safe_page_title(page)
        current_url = getattr(page, "url", "") or ""

        dom_summary: dict[str, Any] = {}
        if hasattr(page, "evaluate") and callable(page.evaluate):
            try:
                evaluated = await page.evaluate(
                    """() => ({
                        links: Array.from(document.querySelectorAll('a[href]')).slice(0, 50).map(a => ({text: (a.innerText || '').trim(), href: a.href})),
                        inputs: Array.from(document.querySelectorAll('input, textarea, select')).slice(0, 50).map(el => ({name: el.name || el.id || '', type: el.type || el.tagName.toLowerCase()})),
                        buttons: Array.from(document.querySelectorAll('button, [role="button"]')).slice(0, 50).map(b => (b.innerText || '').trim())
                    })"""
                )
                if isinstance(evaluated, dict):
                    dom_summary = evaluated
            except Exception:
                dom_summary = {}

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
        """Render local HTML content to a PNG image inside `task_workspace`."""
        t0 = time.perf_counter()
        resolved_out = self._validate_output_path(
            output_path, task_workspace=task_workspace
        )
        resolved_out.parent.mkdir(parents=True, exist_ok=True)

        page = await self._ensure_page()
        if hasattr(page, "set_viewport_size") and callable(page.set_viewport_size):
            await page.set_viewport_size({"width": int(width), "height": int(height)})
        await page.set_content(html, timeout=self.action_timeout_ms)
        await page.screenshot(
            path=str(resolved_out),
            full_page=full_page,
            timeout=self.action_timeout_ms,
        )

        return BrowserActionResult(
            status=BrowserGateStatus.OK.value,
            action="render_html_to_png",
            screenshot_path=str(resolved_out),
            duration_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        )
