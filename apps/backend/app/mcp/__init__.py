"""MCP Server Gateway package: sandboxed shell and browser controllers."""

from app.mcp.browser_server import (
    BrowserActionResult,
    BrowserController,
    BrowserGateStatus,
    BrowserPolicyError,
    CaptchaRequiredError,
)
from app.mcp.gateway import McpGateway
from app.mcp.security import (
    SecurityPolicyError,
    validate_safe_http_url,
    validate_task_workspace,
)
from app.mcp.shell_server import (
    DEFAULT_ALLOWED_EXECUTABLES,
    ShellExecutor,
    ShellResult,
    ShellTimeoutError,
)

__all__ = [
    "BrowserActionResult",
    "BrowserController",
    "BrowserGateStatus",
    "BrowserPolicyError",
    "CaptchaRequiredError",
    "DEFAULT_ALLOWED_EXECUTABLES",
    "McpGateway",
    "SecurityPolicyError",
    "ShellExecutor",
    "ShellResult",
    "ShellTimeoutError",
    "validate_safe_http_url",
    "validate_task_workspace",
]
