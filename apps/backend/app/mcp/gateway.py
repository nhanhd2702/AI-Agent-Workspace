"""Unified MCP Gateway wiring ShellExecutor and BrowserController (Task 3.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from app.config import AppSettings, get_settings
from app.mcp.browser_server import BrowserController
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
        )
        self.browser = browser_controller or BrowserController(
            workspace_root=self.workspace_root,
            extra_secrets=secrets,
        )

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
        ws = Path(task_workspace).resolve()
        if not ws.is_relative_to(self.workspace_root):
            raise SecurityPolicyError(
                f"task_workspace '{task_workspace}' escapes configured workspace_dir '{self.workspace_root}'"
            )
        if not ws.exists() or not ws.is_dir():
            raise SecurityPolicyError(
                f"task_workspace '{task_workspace}' must be an existing directory"
            )
        return ws

    async def call_tool(
        self,
        name: str,
        params: Optional[dict[str, Any]],
        task_workspace: Path,
    ) -> dict[str, Any]:
        """Dispatch a tool invocation with workspace containment enforcement."""
        ws = self._validate_task_workspace(task_workspace)
        args = dict(params or {})

        if name == "shell.run":
            result = await self.shell.run(
                executable=args["executable"],
                args=args.get("args", []),
                task_workspace=ws,
                timeout_s=args.get("timeout_s"),
            )
            return result.to_dict()

        if name == "browser.navigate":
            result = await self.browser.navigate(
                url=args["url"],
                task_workspace=ws,
                wait_until=args.get("wait_until", "domcontentloaded"),
            )
            return result.to_dict()

        if name == "browser.click":
            result = await self.browser.click(
                selector=args["selector"],
                task_workspace=ws,
            )
            return result.to_dict()

        if name == "browser.fill":
            result = await self.browser.fill(
                selector=args["selector"],
                value=args["value"],
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
            result = await self.browser.screenshot(
                output_path=args["output_path"],
                full_page=bool(args.get("full_page", True)),
                selector=args.get("selector"),
                task_workspace=ws,
            )
            return result.to_dict()

        if name == "browser.render_html_to_png":
            result = await self.browser.render_html_to_png(
                html=args["html"],
                output_path=args["output_path"],
                width=int(args.get("width", 1280)),
                height=int(args.get("height", 720)),
                full_page=bool(args.get("full_page", False)),
                task_workspace=ws,
            )
            return result.to_dict()

        raise ValueError(f"Unknown MCP tool: {name!r}")
