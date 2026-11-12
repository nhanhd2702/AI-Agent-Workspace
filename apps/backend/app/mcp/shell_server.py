"""Sandboxed ShellExecutor MCP Server (Task 3.1)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Optional, Sequence

from app.config import get_settings
from app.mcp.security import (
    SecurityPolicyError,
    mask_policy_text,
    validate_safe_http_url,
    validate_task_workspace,
)
from app.orchestrator.dispatcher import mask_secrets


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

# Python safe flags (strict allowlist; blocks -c, -Pc, -m, -W, -X, -, etc.)
_PYTHON_SAFE_SHORT_RE = re.compile(r"^-[uBEIOqsVv]+$")
_PYTHON_SAFE_LONG_FLAGS: frozenset[str] = frozenset({"--version", "--help"})

# Node safe flags (strict allowlist; blocks -e, --eval, -p, --print, -r, --require, --import, --loader, --inspect*, --env-file*, --watch*, -)
_NODE_SAFE_FLAGS: frozenset[str] = frozenset(
    {"-v", "--version", "-h", "--help", "--check", "--no-warnings", "--trace-warnings"}
)

# yt-dlp safe flags (strict allowlist; blocks --exec*, --alias*, --plugin-dirs*, --use-postprocessor*, --config-location*, --cookies*, --ffmpeg-location*, etc.)
_YTDLP_SAFE_NO_VAL_FLAGS: frozenset[str] = frozenset(
    {
        "--version",
        "--help",
        "-h",
        "--no-playlist",
        "--yes-playlist",
        "-x",
        "--extract-audio",
        "--write-subs",
        "--write-auto-subs",
        "--write-thumbnail",
        "--write-info-json",
        "--dump-json",
        "-j",
        "--quiet",
        "-q",
        "--no-warnings",
        "--progress",
        "--newline",
        "--no-overwrites",
        "--force-overwrites",
        "--restrict-filenames",
        "--windows-filenames",
        "--no-part",
    }
)
_YTDLP_PATH_FLAGS: frozenset[str] = frozenset(
    {
        "-o",
        "--output",
        "-P",
        "--paths",
        "-a",
        "--batch-file",
        "--download-archive",
        "--load-info-json",
    }
)
_YTDLP_SCALAR_FLAGS: frozenset[str] = frozenset(
    {
        "-f",
        "--format",
        "-S",
        "--format-sort",
        "--audio-format",
        "--audio-quality",
        "--merge-output-format",
        "--remux-video",
        "--recode-video",
        "--sub-langs",
        "--convert-subs",
        "--print",
        "--trim-filenames",
        "--retries",
        "--fragment-retries",
        "-N",
        "--concurrent-fragments",
        "--max-filesize",
        "--match-filter",
        "-I",
        "--playlist-items",
    }
)

# ffmpeg / ffprobe safe flags & filter graph file keys
_FFMPEG_PATH_FLAGS: frozenset[str] = frozenset(
    {
        "-i",
        "-o",
        "--output",
        "--input",
        "-filter_complex_script",
        "-filter_script",
        "-filter_script:v",
        "-filter_script:a",
        "-vstats_file",
        "-passlogfile",
        "-sdp_file",
        "-attach",
        "-dump_attachment",
    }
)
_FFMPEG_FILTER_FLAGS: frozenset[str] = frozenset(
    {"-vf", "-af", "-filter_complex", "-lavfi", "-filter", "-filter:v", "-filter:a"}
)
_FFMPEG_TIMESTAMP_FLAGS: frozenset[str] = frozenset(
    {"-ss", "-to", "-t", "-itsoffset"}
)
_FFMPEG_STREAM_SPEC_FLAGS: frozenset[str] = frozenset(
    {"-map", "-select_streams"}
)
_FFMPEG_SCALAR_VALUE_FLAGS: frozenset[str] = frozenset(
    {
        "-crf",
        "-preset",
        "-tune",
        "-pix_fmt",
        "-movflags",
        "-threads",
        "-loglevel",
        "-stream_loop",
        "-fflags",
        "-flags",
        "-strict",
        "-ar",
        "-ac",
        "-ab",
        "-vb",
        "-maxrate",
        "-bufsize",
        "-g",
        "-keyint_min",
        "-sc_threshold",
        "-rc_override",
        "-metadata",
        "-show_entries",
        "-print_format",
        "-of",
        "-v",
        "-f",
        "-aspect",
        "-s",
        "-r",
        "-b:v",
        "-b:a",
        "-c:v",
        "-c:a",
        "-codec:v",
        "-codec:a",
        "-profile:v",
        "-level:v",
        "-avoid_negative_ts",
        "-read_intervals",
    }
)
_FFMPEG_SAFE_FLAGS: frozenset[str] = frozenset(
    {
        *_FFMPEG_PATH_FLAGS,
        *_FFMPEG_FILTER_FLAGS,
        *_FFMPEG_TIMESTAMP_FLAGS,
        *_FFMPEG_STREAM_SPEC_FLAGS,
        *_FFMPEG_SCALAR_VALUE_FLAGS,
        "-vn",
        "-an",
        "-sn",
        "-dn",
        "-hide_banner",
        "-version",
        "--version",
        "-formats",
        "-codecs",
        "-filters",
        "-shortest",
        "-re",
        "-loop",
        "-copyts",
        "-show_format",
        "-show_streams",
        "-y",
        "-n",
        "-q",
        "-h",
        "-help",
        "--help",
        "-show_packets",
        "-show_frames",
        "-count_frames",
        "-count_packets",
    }
)
_FFMPEG_COLON_FLAG_RE = re.compile(
    r"^-(c|b|r|s|codec|profile|level|filter|filter_script|metadata)(:[A-Za-z0-9_]+)+$"
)
_FFMPEG_TIMESTAMP_RE = re.compile(r"^\d+(:\d{1,2}){0,2}(\.\d+)?$")
_FFMPEG_STREAM_SPEC_RE = re.compile(r"^-?\[?[A-Za-z0-9_]+(:[A-Za-z0-9_]+)*\??\]?$")
_DANGEROUS_PROTO_RE = re.compile(
    r"(?:^|[\s,=;:'\"])(file|concat|subfile|pipe|tcp|udp|http|https|data|rtmp|rtsp|rtp|ftp|ftps|sftp|smb|crypto|cache|async|fd|mmsh|mmst|hls|tee|icecast|gopher|exec)\s*:",
    re.IGNORECASE,
)
_FFMPEG_FILE_FILTER_KEYS: frozenset[str] = frozenset(
    {
        "textfile",
        "fontfile",
        "filename",
        "file",
        "movie",
        "amovie",
        "subtitles",
        "ass",
        "lut",
        "lut3d",
        "haldclut",
        "icc",
        "psfile",
        "curves",
        "f",
        "src",
    }
)


class ShellExecutor:
    """Executes strictly whitelisted commands inside a task-scoped workspace directory."""

    def __init__(
        self,
        workspace_root: Path,
        allowed_executables: Optional[Iterable[str]] = None,
        default_timeout_s: float = 300.0,
        max_output_bytes: int = 1024 * 1024,
        extra_secrets: Optional[Iterable[str]] = None,
        allow_private_network: bool = False,
        dns_resolver: Optional[Callable[[str], Iterable[str]]] = None,
    ) -> None:
        timeout_val = float(default_timeout_s)
        if not math.isfinite(timeout_val) or timeout_val <= 0:
            raise ValueError("default_timeout_s must be a finite number > 0")
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

    def _policy_error(self, message: str) -> SecurityPolicyError:
        return SecurityPolicyError(mask_policy_text(message, self.extra_secrets))

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
            raise self._policy_error("Executable name must be a string")
        raw = executable.strip()
        if not raw:
            raise self._policy_error("Executable name cannot be empty")
        if any(tok in raw for tok in _FORBIDDEN_METACHAR_TOKENS) or any(
            ch.isspace() for ch in raw
        ):
            raise self._policy_error(f"Invalid characters in executable: {executable!r}")
        if "/" in raw or "\\" in raw or ".." in raw or ":" in raw:
            raise self._policy_error(
                f"Path separators or traversal forbidden in executable: {executable!r}"
            )
        norm = raw.lower()
        if norm.endswith(".exe"):
            norm = norm[:-4]
        if norm not in self.allowed_executables:
            raise self._policy_error(
                f"Executable '{executable}' is not in the allowed whitelist: {sorted(self.allowed_executables)}"
            )
        return norm

    def _validate_task_workspace(self, task_workspace: Path) -> Path:
        return validate_task_workspace(
            task_workspace,
            self.workspace_root,
            error_cls=SecurityPolicyError,
            extra_secrets=self.extra_secrets,
        )

    def _check_metacharacters(self, arg: str) -> None:
        for token in _FORBIDDEN_METACHAR_TOKENS:
            if token in arg:
                raise self._policy_error(
                    f"Forbidden shell metacharacter {token!r} in argument {arg!r}"
                )

    def _validate_path_value(
        self,
        value: str,
        task_workspace_resolved: Path,
        *,
        is_flag_context: bool = False,
        allow_http_url: bool = True,
        allow_ytdlp_prefix: bool = False,
    ) -> None:
        if not value:
            if is_flag_context:
                raise self._policy_error("Empty path argument is forbidden")
            return

        if allow_ytdlp_prefix and ":" in value:
            prefix, rest = value.split(":", 1)
            if prefix.lower() in {"home", "temp"} and not _WINDOWS_DRIVE_ABS_RE.match(
                value
            ):
                value = rest
                if not value:
                    raise self._policy_error("Empty yt-dlp -P path suffix is forbidden")

        # UNC paths (\\server\share or //server/share)
        if value.startswith("\\\\") or value.startswith("//"):
            raise self._policy_error(f"UNC path forbidden: {value!r}")

        # Home directory expansion (~ or ~/...)
        if value == "~" or value.startswith("~/") or value.startswith("~\\"):
            raise self._policy_error(f"Home directory path forbidden: {value!r}")

        # Drive-relative Windows paths like C:foo.txt
        if _WINDOWS_DRIVE_REL_RE.match(value):
            raise self._policy_error(f"Drive-relative path forbidden: {value!r}")

        # URL scheme handling: only http:// or https:// passing strict SSRF checks
        lower_val = value.lower()
        if lower_val.startswith(("http://", "https://")):
            if not allow_http_url:
                raise self._policy_error(f"URL not allowed in this argument: {value!r}")
            validate_safe_http_url(
                value,
                allow_private_network=self.allow_private_network,
                dns_resolver=self.dns_resolver,
                error_cls=SecurityPolicyError,
                extra_secrets=self.extra_secrets,
            )
            return

        # Windows drive absolute path
        if _WINDOWS_DRIVE_ABS_RE.match(value):
            if sys.platform != "win32":
                raise self._policy_error(
                    f"Windows drive path forbidden on non-Windows host: {value!r}"
                )
            resolved = Path(value).resolve()
            if not resolved.is_relative_to(task_workspace_resolved):
                raise self._policy_error(
                    f"Path argument {value!r} resolves to '{resolved}' outside task_workspace '{task_workspace_resolved}'"
                )
            return

        # Block any colon in non-URL, non-Windows-drive values (blocks avio protocols like file:, concat:, subfile,,..:)
        if ":" in value:
            raise self._policy_error(
                f"Colon/protocol specifier forbidden in argument: {value!r}"
            )

        scheme_match = _URL_SCHEME_RE.match(value)
        if scheme_match:
            raise self._policy_error(
                f"URI scheme '{scheme_match.group(1).lower()}://' is forbidden: {value!r}"
            )

        candidate = Path(value)
        resolved = (
            (task_workspace_resolved / candidate).resolve()
            if not candidate.is_absolute()
            else candidate.resolve()
        )
        if not resolved.is_relative_to(task_workspace_resolved):
            raise self._policy_error(
                f"Path argument {value!r} resolves to '{resolved}' outside task_workspace '{task_workspace_resolved}'"
            )

    def _validate_scalar_value(self, value: str, *, flag_name: str = "") -> None:
        if not value:
            raise self._policy_error(f"Empty scalar value forbidden for {flag_name or 'option'}")
        if (
            ".." in value
            or "\\" in value
            or value.startswith(("/", "~"))
            or "//" in value
            or _WINDOWS_DRIVE_ABS_RE.match(value)
        ):
            raise self._policy_error(
                f"Path-like or traversal token forbidden in scalar value {value!r}"
            )
        if _DANGEROUS_PROTO_RE.search(value):
            raise self._policy_error(
                f"Protocol specifier forbidden in scalar value {value!r}"
            )

    def _validate_ffmpeg_filter_graph(
        self,
        expr: str,
        task_workspace_resolved: Path,
    ) -> None:
        if not expr:
            raise self._policy_error("Empty ffmpeg filter expression is forbidden")
        if _DANGEROUS_PROTO_RE.search(expr):
            raise self._policy_error(
                f"Protocol specifier forbidden in ffmpeg filter graph: {expr!r}"
            )
        if "\\\\" in expr or "~/" in expr or "~\\" in expr:
            raise self._policy_error(
                f"Unsafe path prefix forbidden in ffmpeg filter graph: {expr!r}"
            )

        for item in re.split(r"[,;]", expr):
            token = item.strip()
            if not token:
                continue

            # Split filter options on ':' (preserving Windows drive prefixes only for workspace validation)
            colon_parts = [p for p in re.split(r"(?<!^[A-Za-z]):(?![/\\])", token) if p]
            # Fallback simple split on ':' for multi-option chains like text=Hello:fontsize=24:textfile=/etc/passwd
            sub_tokens: list[str] = []
            for part in colon_parts:
                if ":" in part and not _WINDOWS_DRIVE_ABS_RE.match(part.split("=")[-1].strip().strip("'\"")):
                    sub_tokens.extend(p for p in part.split(":") if p)
                else:
                    sub_tokens.append(part)

            for sub in sub_tokens:
                eq_parts = [p.strip().strip("'\"") for p in sub.split("=")]
                for idx, part in enumerate(eq_parts):
                    prev_key = eq_parts[idx - 1].lower() if idx > 0 else ""
                    is_file_key = prev_key in _FFMPEG_FILE_FILTER_KEYS
                    if (
                        is_file_key
                        or "/" in part
                        or "\\" in part
                        or ".." in part
                        or part.startswith("~")
                        or _WINDOWS_DRIVE_ABS_RE.match(part)
                        or _WINDOWS_DRIVE_REL_RE.match(part)
                    ):
                        self._validate_path_value(
                            part,
                            task_workspace_resolved,
                            is_flag_context=is_file_key,
                            allow_http_url=False,
                        )

    def _validate_python_args(
        self, args: Sequence[str], task_workspace_resolved: Path
    ) -> list[str]:
        validated: list[str] = []
        seen_script = False
        for arg in args:
            if not seen_script and arg == "-":
                raise self._policy_error("Stdin execution '-' is forbidden for 'python'")
            if not seen_script and arg.startswith("-"):
                if arg in _PYTHON_SAFE_LONG_FLAGS or _PYTHON_SAFE_SHORT_RE.match(arg):
                    validated.append(arg)
                    continue
                raise self._policy_error(
                    f"Flag {arg!r} is not permitted for 'python'"
                )
            seen_script = True
            if arg.startswith("-") and "=" in arg:
                _, val = arg.split("=", 1)
                self._validate_path_value(
                    val, task_workspace_resolved, allow_http_url=False
                )
            elif not arg.startswith("-"):
                # Positional argument (script path or script arg): NEVER split on '='
                self._validate_path_value(
                    arg, task_workspace_resolved, allow_http_url=False
                )
            validated.append(arg)
        return validated

    def _validate_node_args(
        self, args: Sequence[str], task_workspace_resolved: Path
    ) -> list[str]:
        validated: list[str] = []
        seen_script = False
        for arg in args:
            if not seen_script and arg == "-":
                raise self._policy_error("Stdin execution '-' is forbidden for 'node'")
            if not seen_script and arg.startswith("-"):
                if arg in _NODE_SAFE_FLAGS:
                    validated.append(arg)
                    continue
                raise self._policy_error(f"Flag {arg!r} is not permitted for 'node'")
            seen_script = True
            if arg.startswith("-") and "=" in arg:
                _, val = arg.split("=", 1)
                self._validate_path_value(
                    val, task_workspace_resolved, allow_http_url=False
                )
            elif not arg.startswith("-"):
                # Positional argument (script path or script arg): NEVER split on '='
                self._validate_path_value(
                    arg, task_workspace_resolved, allow_http_url=False
                )
            validated.append(arg)
        return validated

    def _validate_ytdlp_args(
        self, args: Sequence[str], task_workspace_resolved: Path
    ) -> list[str]:
        validated: list[str] = []
        expect_path = False
        expect_paths_prefix = False
        expect_scalar = False

        for arg in args:
            if expect_path:
                self._validate_path_value(
                    arg,
                    task_workspace_resolved,
                    is_flag_context=True,
                    allow_http_url=False,
                    allow_ytdlp_prefix=expect_paths_prefix,
                )
                expect_path = False
                expect_paths_prefix = False
                validated.append(arg)
                continue

            if expect_scalar:
                if arg.startswith("-"):
                    raise self._policy_error(f"Expected scalar value, got flag {arg!r}")
                self._validate_scalar_value(arg, flag_name="yt-dlp")
                expect_scalar = False
                validated.append(arg)
                continue

            if arg == "-":
                raise self._policy_error("Stdin '-' is forbidden for 'yt-dlp'")

            if arg.startswith("-"):
                if "=" in arg:
                    flag_part, val_part = arg.split("=", 1)
                    if flag_part in _YTDLP_PATH_FLAGS:
                        self._validate_path_value(
                            val_part,
                            task_workspace_resolved,
                            is_flag_context=True,
                            allow_http_url=False,
                            allow_ytdlp_prefix=(flag_part in {"-P", "--paths"}),
                        )
                        validated.append(arg)
                        continue
                    if flag_part in _YTDLP_SCALAR_FLAGS:
                        self._validate_scalar_value(val_part, flag_name=flag_part)
                        validated.append(arg)
                        continue
                    raise self._policy_error(
                        f"Flag {flag_part!r} is not permitted for 'yt-dlp'"
                    )

                if arg in _YTDLP_SAFE_NO_VAL_FLAGS:
                    validated.append(arg)
                    continue
                if arg in _YTDLP_PATH_FLAGS:
                    expect_path = True
                    expect_paths_prefix = arg in {"-P", "--paths"}
                    validated.append(arg)
                    continue
                if arg in _YTDLP_SCALAR_FLAGS:
                    expect_scalar = True
                    validated.append(arg)
                    continue

                # Glued short flags: e.g. -o../escape.mp4, -a/etc/passwd, -P/tmp/escape, -fbest
                if not arg.startswith("--") and len(arg) > 2:
                    prefix = arg[:2]
                    suffix = arg[2:]
                    if prefix in _YTDLP_PATH_FLAGS:
                        self._validate_path_value(
                            suffix,
                            task_workspace_resolved,
                            is_flag_context=True,
                            allow_http_url=False,
                            allow_ytdlp_prefix=(prefix == "-P"),
                        )
                        validated.append(arg)
                        continue
                    if prefix in _YTDLP_SCALAR_FLAGS:
                        self._validate_scalar_value(suffix, flag_name=prefix)
                        validated.append(arg)
                        continue

                raise self._policy_error(f"Flag {arg!r} is not permitted for 'yt-dlp'")

            self._validate_path_value(arg, task_workspace_resolved, allow_http_url=True)
            validated.append(arg)

        if expect_path or expect_scalar:
            raise self._policy_error(f"Flag {validated[-1]!r} requires a value")
        return validated

    def _validate_ffmpeg_option_value(
        self, kind: str, val: str, task_workspace_resolved: Path, flag_name: str
    ) -> None:
        if kind == "path":
            self._validate_path_value(
                val,
                task_workspace_resolved,
                is_flag_context=True,
                allow_http_url=True,
            )
            return
        if kind == "filter":
            self._validate_ffmpeg_filter_graph(val, task_workspace_resolved)
            return
        if kind == "timestamp":
            if not _FFMPEG_TIMESTAMP_RE.fullmatch(val):
                raise self._policy_error(
                    f"Invalid timestamp {val!r} for flag {flag_name!r}"
                )
            return
        if kind == "stream_spec":
            if _DANGEROUS_PROTO_RE.search(val) or not _FFMPEG_STREAM_SPEC_RE.fullmatch(val):
                raise self._policy_error(
                    f"Invalid stream specifier {val!r} for flag {flag_name!r}"
                )
            return
        if kind == "scalar":
            self._validate_scalar_value(val, flag_name=flag_name)
            return
        raise self._policy_error(f"Unhandled option kind {kind!r}")

    def _ffmpeg_flag_expect_kind(self, flag_l: str) -> Optional[str]:
        if flag_l in _FFMPEG_PATH_FLAGS or flag_l.startswith("--filter_script"):
            return "path"
        if flag_l in _FFMPEG_FILTER_FLAGS or flag_l.startswith("--filter"):
            return "filter"
        if flag_l in _FFMPEG_TIMESTAMP_FLAGS:
            return "timestamp"
        if flag_l in _FFMPEG_STREAM_SPEC_FLAGS:
            return "stream_spec"
        if flag_l in _FFMPEG_SCALAR_VALUE_FLAGS or _FFMPEG_COLON_FLAG_RE.match(flag_l):
            return "scalar"
        return None

    def _validate_ffmpeg_args(
        self, executable: str, args: Sequence[str], task_workspace_resolved: Path
    ) -> list[str]:
        validated: list[str] = []
        expect_kind: Optional[str] = None
        expect_flag: str = ""

        for arg in args:
            if expect_kind is not None:
                self._validate_ffmpeg_option_value(
                    expect_kind, arg, task_workspace_resolved, expect_flag
                )
                expect_kind = None
                expect_flag = ""
                validated.append(arg)
                continue

            if arg == "-":
                raise self._policy_error(f"Stdin/stdout '-' is forbidden for '{executable}'")

            if arg.startswith("-"):
                if "=" in arg:
                    flag_part, val_part = arg.split("=", 1)
                    flag_l = flag_part.lower()
                    kind = self._ffmpeg_flag_expect_kind(flag_l)
                    if kind is not None:
                        self._validate_ffmpeg_option_value(
                            kind, val_part, task_workspace_resolved, flag_part
                        )
                        validated.append(arg)
                        continue
                    if flag_l in _FFMPEG_SAFE_FLAGS:
                        self._validate_scalar_value(val_part, flag_name=flag_part)
                        validated.append(arg)
                        continue
                    raise self._policy_error(
                        f"Flag {flag_part!r} is not permitted for '{executable}'"
                    )

                arg_l = arg.lower()
                kind = self._ffmpeg_flag_expect_kind(arg_l)
                if kind is not None:
                    expect_kind = kind
                    expect_flag = arg
                    validated.append(arg)
                    continue
                if arg_l in _FFMPEG_SAFE_FLAGS:
                    validated.append(arg)
                    continue

                raise self._policy_error(
                    f"Flag {arg!r} is not permitted for '{executable}'"
                )

            # Positional argument: NEVER parse as filter graph; ALWAYS validate as workspace path or SSRF-safe URL
            self._validate_path_value(arg, task_workspace_resolved, allow_http_url=True)
            validated.append(arg)

        if expect_kind is not None:
            raise self._policy_error(f"Flag {validated[-1]!r} requires an argument")
        return validated

    def _validate_args(
        self,
        executable: str,
        args: Sequence[str],
        task_workspace_resolved: Path,
    ) -> list[str]:
        if not isinstance(args, (list, tuple)):
            raise self._policy_error("args must be a sequence of strings")

        for raw_arg in args:
            if not isinstance(raw_arg, str):
                raise self._policy_error(
                    f"All arguments must be strings, got {type(raw_arg).__name__}"
                )
            self._check_metacharacters(raw_arg)

        if executable == "python":
            return self._validate_python_args(args, task_workspace_resolved)
        if executable == "node":
            return self._validate_node_args(args, task_workspace_resolved)
        if executable == "yt-dlp":
            return self._validate_ytdlp_args(args, task_workspace_resolved)
        if executable in {"ffmpeg", "ffprobe"}:
            return self._validate_ffmpeg_args(executable, args, task_workspace_resolved)

        # Generic fallback for custom allowed_executables
        validated: list[str] = []
        for raw_arg in args:
            if raw_arg == "-":
                raise self._policy_error("Stdin '-' is forbidden")
            if raw_arg.startswith("-"):
                if "=" in raw_arg:
                    _, val_part = raw_arg.split("=", 1)
                    self._validate_path_value(
                        val_part, task_workspace_resolved, allow_http_url=False
                    )
            else:
                self._validate_path_value(
                    raw_arg, task_workspace_resolved, allow_http_url=False
                )
            validated.append(raw_arg)
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
        if not located:
            raise FileNotFoundError(
                f"Allowed executable '{norm_exec}' was not found on system PATH"
            )
        return located

    def _decode_and_sanitize_output(
        self, raw_bytes: bytes, *, truncated: bool = False
    ) -> str:
        was_truncated = truncated
        data = raw_bytes
        if len(data) > self.max_output_bytes:
            data = data[: self.max_output_bytes]
            was_truncated = True
        text = data.decode("utf-8", errors="replace")
        masked = str(mask_secrets(text, extra_secrets=self.extra_secrets))
        if was_truncated:
            masked += "\n... [TRUNCATED]"
        return masked

    @staticmethod
    async def _read_bounded_stream(
        stream: Optional[asyncio.StreamReader],
        limit: int,
    ) -> tuple[bytes, bool]:
        if stream is None:
            return b"", False
        chunks: list[bytes] = []
        total = 0
        truncated = False
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                break
            if total < limit:
                remaining = limit - total
                if len(chunk) > remaining:
                    chunks.append(chunk[:remaining])
                    total += remaining
                    truncated = True
                else:
                    chunks.append(chunk)
                    total += len(chunk)
            else:
                truncated = True
        return b"".join(chunks), truncated

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

    async def _cleanup_process(self, proc: asyncio.subprocess.Process) -> None:
        await self._kill_process_tree(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except Exception:
            pass
        for stream_name in ("stdout", "stderr"):
            stream = getattr(proc, stream_name, None)
            if stream is not None and hasattr(stream, "feed_eof"):
                try:
                    stream.feed_eof()
                except Exception:
                    pass
        transport = getattr(proc, "_transport", None)
        if transport is not None and hasattr(transport, "close"):
            try:
                transport.close()
            except Exception:
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
        masked_args = [
            str(mask_secrets(arg, extra_secrets=self.extra_secrets))
            for arg in validated_args
        ]
        effective_timeout = (
            float(timeout_s) if timeout_s is not None else self.default_timeout_s
        )
        if not math.isfinite(effective_timeout) or effective_timeout <= 0:
            raise ValueError("timeout_s must be a finite number > 0")

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

        read_task = asyncio.gather(
            self._read_bounded_stream(proc.stdout, self.max_output_bytes),
            self._read_bounded_stream(proc.stderr, self.max_output_bytes),
            proc.wait(),
        )
        try:
            (stdout_bytes, out_trunc), (stderr_bytes, err_trunc), returncode = (
                await asyncio.wait_for(read_task, timeout=effective_timeout)
            )
            duration_ms = max(0, int((time.perf_counter() - t0) * 1000))
            return ShellResult(
                executable=norm_exec,
                args=masked_args,
                returncode=int(returncode or 0),
                stdout=self._decode_and_sanitize_output(stdout_bytes, truncated=out_trunc),
                stderr=self._decode_and_sanitize_output(stderr_bytes, truncated=err_trunc),
                timed_out=False,
                duration_ms=duration_ms,
            )
        except asyncio.TimeoutError as exc:
            await asyncio.shield(self._cleanup_process(proc))
            duration_ms = max(0, int((time.perf_counter() - t0) * 1000))
            if raise_on_timeout:
                raise ShellTimeoutError(
                    mask_policy_text(
                        f"Command '{norm_exec}' timed out after {effective_timeout}s",
                        self.extra_secrets,
                    ),
                    executable=norm_exec,
                    timeout_s=effective_timeout,
                    duration_ms=duration_ms,
                ) from exc

            return ShellResult(
                executable=norm_exec,
                args=masked_args,
                returncode=-1,
                stdout="",
                stderr="",
                timed_out=True,
                duration_ms=duration_ms,
            )
        except BaseException:
            await asyncio.shield(self._cleanup_process(proc))
            raise
