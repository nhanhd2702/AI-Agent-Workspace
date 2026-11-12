"""Sandboxed ShellExecutor MCP Server (Task 3.1)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Iterable, Optional, Sequence

from app.config import get_settings
from app.orchestrator.dispatcher import mask_secrets


class SecurityPolicyError(Exception):
    """Raised when a command, argument, URL, or path violates sandbox policy."""


class ShellTimeoutError(TimeoutError):
    """Raised when a sandboxed shell command exceeds its execution timeout."""

    def __init__(
        self,
        message: str,
        *,
        executable: str = "",
        timeout_s: float = 0.0,
        stdout: str = "",
        stderr: str = "",
        duration_ms: int = 0,
    ) -> None:
        super().__init__(message)
        self.executable = executable
        self.timeout_s = timeout_s
        self.stdout = stdout
        self.stderr = stderr
        self.duration_ms = duration_ms


@dataclass
class ShellResult:
    """Structured result from executing a sandboxed command."""

    executable: str
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "executable": self.executable,
            "args": list(self.args),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
        }


DEFAULT_ALLOWED_EXECUTABLES: frozenset[str] = frozenset(
    {"ffmpeg", "ffprobe", "python", "node", "yt-dlp"}
)

_FORBIDDEN_METACHAR_TOKENS: tuple[str, ...] = (
    "&&",
    "||",
    ";",
    "|",
    "`",
    "$(",
    ">",
    "<",
    "\n",
    "\r",
    "\x00",
)

_PATH_TAKING_FLAGS: frozenset[str] = frozenset(
    {
        "-i",
        "-o",
        "--output",
        "--input",
        "--out",
        "--file",
        "--config",
        "--config-location",
        "--paths",
        "-p",
        "--batch-file",
        "-a",
        "--cookies",
        "--download-archive",
        "--write-info-json",
        "--load-info-json",
    }
)

_SAFE_ENV_KEYS: tuple[str, ...] = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "PATHEXT",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
)

_WINDOWS_DRIVE_ABS_RE = re.compile(r"^[A-Za-z]:[/\\]")
_WINDOWS_DRIVE_REL_RE = re.compile(r"^[A-Za-z]:(?![/\\])")
_URL_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")
_PYTHON_SHORT_C_RE = re.compile(r"^-[BEIOQSqsudvxi]*c")
_NODE_SHORT_EVAL_RE = re.compile(r"^-[A-Za-z]*[ep]")


class ShellExecutor:
    """Executes strictly whitelisted commands inside a task-scoped workspace directory."""

    def __init__(
        self,
        workspace_root: Path,
        allowed_executables: Optional[Iterable[str]] = None,
        default_timeout_s: float = 300.0,
        max_output_bytes: int = 1024 * 1024,
        extra_secrets: Optional[Iterable[str]] = None,
    ) -> None:
        if default_timeout_s <= 0:
            raise ValueError("default_timeout_s must be > 0")
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be > 0")

        self.workspace_root = Path(workspace_root).resolve()
        if allowed_executables is None:
            self.allowed_executables = set(DEFAULT_ALLOWED_EXECUTABLES)
        else:
            self.allowed_executables = {
                self._normalize_whitelist_entry(item) for item in allowed_executables
            }
        self.default_timeout_s = float(default_timeout_s)
        self.max_output_bytes = int(max_output_bytes)

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

    @staticmethod
    def _normalize_whitelist_entry(entry: str) -> str:
        raw = str(entry).strip().lower()
        if not raw or "/" in raw or "\\" in raw or ".." in raw or ":" in raw:
            raise ValueError(f"Invalid allowed executable entry: {entry!r}")
        if raw.endswith(".exe"):
            raw = raw[:-4]
        return raw

    def _validate_executable(self, executable: str) -> str:
        if not isinstance(executable, str):
            raise SecurityPolicyError("Executable name must be a string")
        raw = executable.strip()
        if not raw:
            raise SecurityPolicyError("Executable name cannot be empty")
        if any(tok in raw for tok in _FORBIDDEN_METACHAR_TOKENS) or any(
            ch.isspace() for ch in raw
        ):
            raise SecurityPolicyError(f"Invalid characters in executable: {executable!r}")
        if "/" in raw or "\\" in raw or ".." in raw or ":" in raw:
            raise SecurityPolicyError(
                f"Path separators or traversal forbidden in executable: {executable!r}"
            )
        norm = raw.lower()
        if norm.endswith(".exe"):
            norm = norm[:-4]
        if norm not in self.allowed_executables:
            raise SecurityPolicyError(
                f"Executable '{executable}' is not in the allowed whitelist: {sorted(self.allowed_executables)}"
            )
        return norm

    def _validate_task_workspace(self, task_workspace: Path) -> Path:
        if not isinstance(task_workspace, (Path, str)):
            raise SecurityPolicyError("task_workspace must be a valid Path")
        raw_ws = Path(task_workspace)
        resolved_ws = raw_ws.resolve()
        if not resolved_ws.is_relative_to(self.workspace_root):
            raise SecurityPolicyError(
                f"task_workspace '{task_workspace}' escapes workspace_root '{self.workspace_root}'"
            )
        if not resolved_ws.exists() or not resolved_ws.is_dir():
            raise SecurityPolicyError(
                f"task_workspace '{task_workspace}' must be an existing directory"
            )
        return resolved_ws

    @staticmethod
    def _check_metacharacters(arg: str) -> None:
        for token in _FORBIDDEN_METACHAR_TOKENS:
            if token in arg:
                raise SecurityPolicyError(
                    f"Forbidden shell metacharacter {token!r} in argument {arg!r}"
                )

    def _validate_inline_execution(self, executable: str, arg: str) -> None:
        lower = arg.lower()
        if arg == "-":
            raise SecurityPolicyError(
                f"Stdin execution '-' is forbidden for '{executable}'"
            )
        if lower == "--eval" or lower.startswith("--eval="):
            raise SecurityPolicyError(
                f"Inline code evaluation flag {arg!r} is forbidden"
            )

        if executable == "python":
            if _PYTHON_SHORT_C_RE.match(arg):
                raise SecurityPolicyError(
                    f"Inline Python execution flag {arg!r} is forbidden"
                )
        elif executable == "node":
            if lower in {"-e", "--eval", "-p", "--print"} or lower.startswith(
                ("--eval=", "--print=")
            ) or _NODE_SHORT_EVAL_RE.match(arg):
                raise SecurityPolicyError(
                    f"Inline Node.js execution flag {arg!r} is forbidden"
                )
        elif executable == "yt-dlp":
            if lower == "--exec" or lower.startswith("--exec="):
                raise SecurityPolicyError(
                    "yt-dlp '--exec' command hook is forbidden"
                )

    def _validate_path_value(
        self,
        value: str,
        task_workspace_resolved: Path,
        *,
        is_flag_context: bool = False,
    ) -> None:
        if not value:
            if is_flag_context:
                raise SecurityPolicyError("Empty path argument is forbidden")
            return

        # UNC paths (\\server\share or //server/share)
        if value.startswith("\\\\") or value.startswith("//"):
            raise SecurityPolicyError(f"UNC path forbidden: {value!r}")

        # Home directory expansion (~ or ~/...)
        if value == "~" or value.startswith("~/") or value.startswith("~\\"):
            raise SecurityPolicyError(f"Home directory path forbidden: {value!r}")

        # Drive-relative Windows paths like C:foo.txt
        if _WINDOWS_DRIVE_REL_RE.match(value):
            raise SecurityPolicyError(
                f"Drive-relative path forbidden: {value!r}"
            )

        # URL scheme handling (allow http/https URLs; block file:// and others)
        scheme_match = _URL_SCHEME_RE.match(value)
        if scheme_match and not _WINDOWS_DRIVE_ABS_RE.match(value):
            scheme = scheme_match.group(1).lower()
            if scheme in {"http", "https"}:
                return
            raise SecurityPolicyError(
                f"URI scheme '{scheme}://' is forbidden in shell arguments: {value!r}"
            )

        # Windows drive-letter absolute path on POSIX must always be rejected
        if _WINDOWS_DRIVE_ABS_RE.match(value) and sys.platform != "win32":
            raise SecurityPolicyError(
                f"Windows drive path forbidden on non-Windows host: {value!r}"
            )

        # Resolve relative to task_workspace and ensure strict containment
        candidate = Path(value)
        if not candidate.is_absolute():
            resolved = (task_workspace_resolved / candidate).resolve()
        else:
            resolved = candidate.resolve()

        if not resolved.is_relative_to(task_workspace_resolved):
            raise SecurityPolicyError(
                f"Path argument {value!r} resolves to '{resolved}' outside task_workspace '{task_workspace_resolved}'"
            )

    def _validate_args(
        self,
        executable: str,
        args: Sequence[str],
        task_workspace_resolved: Path,
    ) -> list[str]:
        if not isinstance(args, (list, tuple)):
            raise SecurityPolicyError("args must be a sequence of strings")

        validated: list[str] = []
        expect_path_next = False

        for raw_arg in args:
            if not isinstance(raw_arg, str):
                raise SecurityPolicyError(
                    f"All arguments must be strings, got {type(raw_arg).__name__}"
                )
            self._check_metacharacters(raw_arg)
            self._validate_inline_execution(executable, raw_arg)

            if expect_path_next:
                self._validate_path_value(
                    raw_arg, task_workspace_resolved, is_flag_context=True
                )
                expect_path_next = False
                validated.append(raw_arg)
                continue

            if raw_arg.startswith("-"):
                lower_flag = raw_arg.lower()
                # Check flag=value form (e.g., --output=../../etc/passwd)
                if "=" in raw_arg:
                    flag_part, val_part = raw_arg.split("=", 1)
                    self._validate_inline_execution(executable, flag_part)
                    self._validate_path_value(
                        val_part,
                        task_workspace_resolved,
                        is_flag_context=(flag_part.lower() in _PATH_TAKING_FLAGS),
                    )
                elif lower_flag in _PATH_TAKING_FLAGS:
                    # Note: for node, '-p' is already blocked above; for yt-dlp '-P' is paths
                    if not (executable == "node" and lower_flag == "-p"):
                        expect_path_next = True
                validated.append(raw_arg)
                continue

            # Non-flag positional argument: validate if path-like, key=value, or file reference
            if "=" in raw_arg and not _URL_SCHEME_RE.match(raw_arg):
                _, val_part = raw_arg.split("=", 1)
                if (
                    "/" in val_part
                    or "\\" in val_part
                    or ".." in val_part
                    or val_part.startswith("~")
                    or _WINDOWS_DRIVE_ABS_RE.match(val_part)
                    or _WINDOWS_DRIVE_REL_RE.match(val_part)
                ):
                    self._validate_path_value(val_part, task_workspace_resolved)
            else:
                self._validate_path_value(raw_arg, task_workspace_resolved)

            validated.append(raw_arg)

        if expect_path_next:
            raise SecurityPolicyError(
                f"Flag '{validated[-1]}' requires a path argument"
            )

        return validated

    def _build_sanitized_env(self, task_workspace_resolved: Path) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in _SAFE_ENV_KEYS:
            val = os.environ.get(key)
            if val is not None:
                env[key] = val
        ws_str = str(task_workspace_resolved)
        env["HOME"] = ws_str
        env["USERPROFILE"] = ws_str
        env["TMPDIR"] = ws_str
        env["TEMP"] = ws_str
        env["TMP"] = ws_str
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    @staticmethod
    def _resolve_binary(norm_exec: str) -> str:
        if norm_exec == "python":
            if sys.executable and Path(sys.executable).exists():
                return sys.executable
        located = shutil.which(norm_exec)
        return located or norm_exec

    def _decode_and_sanitize_output(self, raw_bytes: bytes) -> str:
        truncated = False
        data = raw_bytes
        if len(data) > self.max_output_bytes:
            data = data[: self.max_output_bytes]
            truncated = True
        text = data.decode("utf-8", errors="replace")
        masked = str(mask_secrets(text, extra_secrets=self.extra_secrets))
        if truncated:
            masked += "\n... [TRUNCATED]"
        return masked

    async def _kill_process_tree(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        pid = proc.pid
        if sys.platform == "win32":
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/F",
                    "/T",
                    "/PID",
                    str(pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(killer.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    killer.kill()
                    await killer.wait()
            except OSError:
                pass
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    async def run(
        self,
        executable: str,
        args: Sequence[str],
        task_workspace: Path,
        timeout_s: Optional[float] = None,
        *,
        raise_on_timeout: bool = True,
    ) -> ShellResult:
        """Validate and execute a whitelisted command inside `task_workspace`."""
        norm_exec = self._validate_executable(executable)
        ws_resolved = self._validate_task_workspace(task_workspace)
        validated_args = self._validate_args(norm_exec, args, ws_resolved)
        effective_timeout = (
            float(timeout_s) if timeout_s is not None else self.default_timeout_s
        )
        if effective_timeout <= 0:
            raise ValueError("timeout_s must be > 0")

        binary = self._resolve_binary(norm_exec)
        env = self._build_sanitized_env(ws_resolved)

        spawn_kwargs: dict[str, Any] = {
            "cwd": str(ws_resolved),
            "env": env,
            "stdin": asyncio.subprocess.DEVNULL,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if sys.platform == "win32":
            spawn_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            spawn_kwargs["start_new_session"] = True

        t0 = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            binary,
            *validated_args,
            **spawn_kwargs,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout,
            )
            duration_ms = max(0, int((time.perf_counter() - t0) * 1000))
            return ShellResult(
                executable=norm_exec,
                args=validated_args,
                returncode=int(proc.returncode or 0),
                stdout=self._decode_and_sanitize_output(stdout_bytes or b""),
                stderr=self._decode_and_sanitize_output(stderr_bytes or b""),
                timed_out=False,
                duration_ms=duration_ms,
            )
        except asyncio.TimeoutError as exc:
            await self._kill_process_tree(proc)
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                stdout_bytes, stderr_bytes = b"", b""
                try:
                    await proc.wait()
                except Exception:
                    pass

            duration_ms = max(0, int((time.perf_counter() - t0) * 1000))
            out_str = self._decode_and_sanitize_output(stdout_bytes or b"")
            err_str = self._decode_and_sanitize_output(stderr_bytes or b"")

            if raise_on_timeout:
                raise ShellTimeoutError(
                    f"Command '{norm_exec}' timed out after {effective_timeout}s",
                    executable=norm_exec,
                    timeout_s=effective_timeout,
                    stdout=out_str,
                    stderr=err_str,
                    duration_ms=duration_ms,
                ) from exc

            return ShellResult(
                executable=norm_exec,
                args=validated_args,
                returncode=-1,
                stdout=out_str,
                stderr=err_str,
                timed_out=True,
                duration_ms=duration_ms,
            )
        except BaseException:
            await self._kill_process_tree(proc)
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except Exception:
                pass
            raise
