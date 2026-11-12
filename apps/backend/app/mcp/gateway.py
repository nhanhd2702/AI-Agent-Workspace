"""Unified MCP Gateway wiring ShellExecutor and BrowserController (Task 3.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from app.config import AppSettings, get_settings
from app.mcp.browser_server import BrowserController
from app.mcp.security import validate_task_workspace
from app.mcp.shell_server import SecurityPolicyError, ShellExecutor


_TOOL_REGISTRY: list[dict[str, Any]] = [
    {
        "name": "shell.run",
        "description": "Execute a whitelisted CLI executable inside the task workspace.",
        "parameters": ["executable", "args", "timeout_s"],
    },
    {
        "name": "browser.navigate",
        "description": "Navigate the headless browser to an allowed HTTP/HTTPS or workspace file URL.",
        "parameters": ["url", "wait_until"],
    },
    {
        "name": "browser.click",
        "description": "Click a DOM element by CSS selector.",
        "parameters": ["selector"],
    },
    {
        "name": "browser.fill",
        "description": "Fill an input element matching a CSS selector.",
        "parameters": ["selector", "value"],
    },
    {
        "name": "browser.take_snapshot",
        "description": "Capture a structured DOM and text snapshot of the current page.",
        "parameters": [],
    },
    {
        "name": "browser.extract_text",
        "description": "Extract visible text from a CSS selector (default body).",
        "parameters": ["selector"],
    },
    {
        "name": "browser.screenshot",
        "description": "Save a PNG screenshot inside the task workspace.",
        "parameters": ["output_path", "full_page", "selector"],
    },
    {
        "name": "browser.render_html_to_png",
        "description": "Render an HTML string to a PNG image inside the task workspace.",
        "parameters": ["html", "output_path", "width", "height", "full_page"],
    },
]


class McpGateway:
    """Unified sandboxed MCP tool gateway over ShellExecutor and BrowserController."""

    def __init__(
        self,
        settings: Optional[AppSettings] = None,
        shell_executor: Optional[ShellExecutor] = None,
        browser_controller: Optional[BrowserController] = None,
        dns_resolver: Optional[Callable[[str], Iterable[str]]] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.workspace_root = self.settings.workspace_dir.resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

        secrets: list[str] = []
        if self.settings.local_auth_token:
            secrets.append(self.settings.local_auth_token)
        if self.settings.encryption_key:
            secrets.append(self.settings.encryption_key.decode("utf-8", errors="ignore"))

        self.shell = shell_executor or ShellExecutor(
            workspace_root=self.workspace_root,
            extra_secrets=secrets,
            dns_resolver=dns_resolver,
        )
        self.browser = browser_controller or BrowserController(
            workspace_root=self.workspace_root,
            extra_secrets=secrets,
            dns_resolver=dns_resolver,
        )

        # Ensure gateway secrets are always included even when executors were injected
        for sec in secrets:
            if sec not in self.shell.extra_secrets:
                self.shell.extra_secrets.append(sec)
            if sec not in self.browser.extra_secrets:
                self.browser.extra_secrets.append(sec)

    async def __aenter__(self) -> "McpGateway":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self.browser.close()

    def list_tools(self) -> list[dict[str, Any]]:
        """Return registered MCP tool definitions."""
        return [dict(item) for item in _TOOL_REGISTRY]

    def _validate_task_workspace(self, task_workspace: Path | str) -> Path:
        return validate_task_workspace(
            task_workspace,
            self.workspace_root,
            error_cls=SecurityPolicyError,
            extra_secrets=self.shell.extra_secrets,
        )

    @staticmethod
    def _require_param(args: dict[str, Any], key: str, tool_name: str) -> Any:
        if key not in args or args[key] is None:
            raise ValueError(
                f"Missing required parameter '{key}' for MCP tool '{tool_name}'"
            )
        return args[key]

    async def call_tool(
        self,
        name: str,
        params: Optional[dict[str, Any]],
        task_workspace: Path,
    ) -> dict[str, Any]:
        """Dispatch a tool invocation with workspace containment enforcement."""
        ws = self._validate_task_workspace(task_workspace)
        if params is not None and not isinstance(params, dict):
            raise ValueError("MCP tool params must be a dictionary")
        args = dict(params or {})

        if name == "shell.run":
            executable = self._require_param(args, "executable", name)
            cmd_args = args.get("args", [])
            result = await self.shell.run(
                executable=executable,
                args=cmd_args,
                task_workspace=ws,
                timeout_s=args.get("timeout_s"),
            )
            return result.to_dict()

        if name == "browser.navigate":
            url = self._require_param(args, "url", name)
            result = await self.browser.navigate(
                url=url,
                task_workspace=ws,
                wait_until=args.get("wait_until", "domcontentloaded"),
            )
            return result.to_dict()

        if name == "browser.click":
            selector = self._require_param(args, "selector", name)
            result = await self.browser.click(
                selector=selector,
                task_workspace=ws,
            )
            return result.to_dict()

        if name == "browser.fill":
            selector = self._require_param(args, "selector", name)
            value = self._require_param(args, "value", name)
            result = await self.browser.fill(
                selector=selector,
                value=value,
                task_workspace=ws,
            )
            return result.to_dict()

        if name == "browser.take_snapshot":
            result = await self.browser.take_snapshot(task_workspace=ws)
            return result.to_dict()

        if name == "browser.extract_text":
            result = await self.browser.extract_text(
                selector=args.get("selector", "body"),
                task_workspace=ws,
            )
            return result.to_dict()

        if name == "browser.screenshot":
            output_path = self._require_param(args, "output_path", name)
            result = await self.browser.screenshot(
                output_path=output_path,
                full_page=bool(args.get("full_page", True)),
                selector=args.get("selector"),
                task_workspace=ws,
            )
            return result.to_dict()

        if name == "browser.render_html_to_png":
            html = self._require_param(args, "html", name)
            output_path = self._require_param(args, "output_path", name)
            raw_w = args.get("width")
            raw_h = args.get("height")
            if isinstance(raw_w, bool) or isinstance(raw_h, bool):
                raise ValueError("width and height must be integers")
            width = 1280 if raw_w is None else int(raw_w)
            height = 720 if raw_h is None else int(raw_h)
            result = await self.browser.render_html_to_png(
                html=html,
                output_path=output_path,
                width=width,
                height=height,
                full_page=bool(args.get("full_page", False)),
                task_workspace=ws,
            )
            return result.to_dict()

        raise ValueError(f"Unknown MCP tool: {name!r}")
