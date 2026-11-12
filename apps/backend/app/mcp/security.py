"""Shared MCP security helpers: SSRF URL validation, workspace isolation, and secret-safe errors."""

from __future__ import annotations

import ipaddress
from pathlib import Path
import re
import socket
from typing import Any, Callable, Iterable, Optional, Type
from urllib.parse import urlparse

from app.orchestrator.dispatcher import mask_secrets


class SecurityPolicyError(Exception):
    """Raised when a command, argument, URL, or path violates sandbox policy."""


_FORBIDDEN_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata.goog",
    }
)

_FORBIDDEN_HOST_SUFFIXES: tuple[str, ...] = (
    ".localhost",
    ".local",
    ".internal",
    ".arpa",
    ".home.arpa",
)

_INET_ATON_PART_RE = re.compile(r"^(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)$")
_CGNAT_NETWORK = ipaddress.IPv4Network("100.64.0.0/10")


def mask_policy_text(
    text: str,
    extra_secrets: Optional[Iterable[str]] = None,
) -> str:
    """Redact sensitive tokens from error/diagnostic text."""
    return str(mask_secrets(text, extra_secrets=extra_secrets))


def _parse_inet_aton_part(part: str) -> Optional[int]:
    if not _INET_ATON_PART_RE.match(part):
        return None
    lower = part.lower()
    if lower.startswith("0x"):
        return int(lower, 16)
    if lower.startswith("0") and len(lower) > 1:
        return int(lower, 8)
    return int(lower, 10)


def parse_ip_literal(host: str) -> Optional[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Parse standard IPv4/IPv6 and alternative decimal/hex/octal/short IPv4 notations."""
    cleaned = host.strip()
    if "%" in cleaned:
        # Strip IPv6 zone identifier (e.g., fe80::1%eth0)
        cleaned = cleaned.split("%", 1)[0]
    try:
        return ipaddress.ip_address(cleaned)
    except ValueError:
        pass

    parts = cleaned.split(".")
    if not (1 <= len(parts) <= 4):
        return None
    parsed_parts: list[int] = []
    for part in parts:
        val = _parse_inet_aton_part(part)
        if val is None or val < 0:
            return None
        parsed_parts.append(val)

    if len(parsed_parts) == 1:
        a = parsed_parts[0]
        if a > 0xFFFFFFFF:
            return None
        return ipaddress.IPv4Address(a)
    if len(parsed_parts) == 2:
        a, b = parsed_parts
        if a > 0xFF or b > 0xFFFFFF:
            return None
        return ipaddress.IPv4Address((a << 24) | b)
    if len(parsed_parts) == 3:
        a, b, c = parsed_parts
        if a > 0xFF or b > 0xFF or c > 0xFFFF:
            return None
        return ipaddress.IPv4Address((a << 24) | (b << 16) | c)
    a, b, c, d = parsed_parts
    if any(x > 0xFF for x in (a, b, c, d)):
        return None
    return ipaddress.IPv4Address((a << 24) | (b << 16) | (c << 8) | d)


def is_public_global_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True only if `ip` (and any unwrapped IPv4-mapped/tunneled address) is strictly global."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_global_ip(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return is_public_global_ip(ip.sixtofour)
        if ip.teredo is not None:
            return is_public_global_ip(ip.teredo[0]) and is_public_global_ip(ip.teredo[1])

    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_NETWORK:
        return False

    return bool(
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_reserved
        and not ip.is_unspecified
        and not ip.is_multicast
        and not getattr(ip, "is_site_local", False)
    )


def validate_safe_http_url(
    url: str,
    *,
    allow_private_network: bool = False,
    dns_resolver: Optional[Callable[[str], Iterable[str]]] = None,
    error_cls: Type[Exception] = SecurityPolicyError,
    extra_secrets: Optional[Iterable[str]] = None,
) -> str:
    """Validate an HTTP/HTTPS URL against SSRF, alternative IP notations, and DNS rebinding."""
    if not isinstance(url, str) or not url.strip():
        raise error_cls("URL must be a non-empty string")
    stripped = url.strip()
    if any(ch in stripped for ch in ("\n", "\r", "\x00")):
        raise error_cls("URL contains forbidden control characters")

    parsed = urlparse(stripped)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise error_cls(f"Unsupported or unsafe URL scheme: {scheme!r}")

    if "://" not in stripped:
        raise error_cls("HTTP(S) URL must contain '://'")
    after_scheme = stripped.split("://", 1)[1]
    raw_authority = re.split(r"[/?#]", after_scheme, maxsplit=1)[0]
    if "\\" in raw_authority or "\\" in parsed.netloc:
        raise error_cls(
            mask_policy_text(
                f"SSRF protection blocked backslash in URL authority: {stripped!r}",
                extra_secrets,
            )
        )
    if (
        "@" in raw_authority
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise error_cls(
            mask_policy_text(
                f"SSRF protection blocked userinfo '@' in URL authority: {stripped!r}",
                extra_secrets,
            )
        )

    hostname = parsed.hostname
    if not hostname:
        raise error_cls(
            mask_policy_text(f"URL missing hostname: {stripped!r}", extra_secrets)
        )

    if allow_private_network:
        return stripped

    host_norm = hostname.strip().lower().rstrip(".")
    if not host_norm:
        raise error_cls("URL hostname cannot be empty")

    if host_norm in _FORBIDDEN_HOSTNAMES or host_norm.endswith(_FORBIDDEN_HOST_SUFFIXES):
        raise error_cls(
            mask_policy_text(
                f"SSRF protection blocked internal/local host: {hostname!r}",
                extra_secrets,
            )
        )

    ip_literal = parse_ip_literal(host_norm)
    if ip_literal is not None:
        if not is_public_global_ip(ip_literal):
            raise error_cls(
                mask_policy_text(
                    f"SSRF protection blocked non-public IP address: {hostname!r}",
                    extra_secrets,
                )
            )
        return stripped

    # Domain name: resolve and fail closed on DNS error or any non-public IP
    port = parsed.port or (443 if scheme == "https" else 80)
    resolved_ips: list[str] = []
    try:
        if dns_resolver is not None:
            resolved_ips = [str(item).strip() for item in dns_resolver(host_norm) if item]
        else:
            infos = socket.getaddrinfo(host_norm, port, type=socket.SOCK_STREAM)
            for info in infos:
                sockaddr = info[4]
                if sockaddr and len(sockaddr) >= 1:
                    resolved_ips.append(str(sockaddr[0]))
    except Exception as exc:
        raise error_cls(
            mask_policy_text(
                f"SSRF protection failed closed during DNS resolution for {hostname!r}: {exc}",
                extra_secrets,
            )
        ) from exc

    if not resolved_ips:
        raise error_cls(
            mask_policy_text(
                f"SSRF protection failed closed: DNS returned no addresses for {hostname!r}",
                extra_secrets,
            )
        )

    for ip_str in resolved_ips:
        resolved_ip = parse_ip_literal(ip_str)
        if resolved_ip is None or not is_public_global_ip(resolved_ip):
            raise error_cls(
                mask_policy_text(
                    f"SSRF protection blocked host {hostname!r} resolving to non-public IP {ip_str!r}",
                    extra_secrets,
                )
            )

    return stripped


def validate_task_workspace(
    task_workspace: Optional[Path | str],
    workspace_root: Path,
    *,
    error_cls: Type[Exception] = SecurityPolicyError,
    extra_secrets: Optional[Iterable[str]] = None,
) -> Path:
    """Verify `task_workspace` is a strict subdirectory inside `workspace_root` with no DB/Chroma files."""
    if task_workspace is None or not isinstance(task_workspace, (Path, str)):
        raise error_cls("task_workspace must be an explicit Path inside workspace_root")

    raw_str = str(task_workspace).strip()
    if not raw_str:
        raise error_cls("task_workspace cannot be empty")

    resolved_root = Path(workspace_root).resolve()
    resolved_ws = Path(task_workspace).resolve()

    if not resolved_ws.is_relative_to(resolved_root):
        raise error_cls(
            mask_policy_text(
                f"task_workspace '{task_workspace}' escapes workspace_root '{resolved_root}'",
                extra_secrets,
            )
        )
    if resolved_ws == resolved_root:
        raise error_cls(
            "task_workspace cannot be workspace_root itself; must be a task subdirectory"
        )
    if not resolved_ws.exists() or not resolved_ws.is_dir():
        raise error_cls(
            mask_policy_text(
                f"task_workspace '{task_workspace}' must be an existing directory",
                extra_secrets,
            )
        )

    chroma_root = (resolved_root / "chroma").resolve()
    if resolved_ws.name.lower() == "chroma" or resolved_ws.is_relative_to(chroma_root):
        raise error_cls("task_workspace cannot target vector store 'chroma' directory")

    for forbidden in ("app.db", "checkpoints.db", "chroma"):
        if (resolved_ws / forbidden).exists():
            raise error_cls(
                f"task_workspace cannot contain protected runtime state '{forbidden}'"
            )

    return resolved_ws
