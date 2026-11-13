#!/usr/bin/env python3
"""Build and package backend sidecar binary for Tauri desktop distribution.

Bundles the FastAPI backend into a standalone onefile binary placed under
`apps/desktop/src-tauri/binaries/backend-sidecar-{target_triple}[.exe]`.
"""

import argparse
import platform
import re
import secrets
import socket
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST_DIR = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "binaries"
DEFAULT_ENTRYPOINT = REPO_ROOT / "apps" / "backend" / "app" / "main.py"

TARGET_TRIPLE_MAP: dict[str, str] = {
    # Windows
    "windows-x86_64": "x86_64-pc-windows-msvc",
    "win32-x64": "x86_64-pc-windows-msvc",
    "windows-amd64": "x86_64-pc-windows-msvc",
    "x86_64-pc-windows-msvc": "x86_64-pc-windows-msvc",
    "windows-aarch64": "aarch64-pc-windows-msvc",
    "windows-arm64": "aarch64-pc-windows-msvc",
    "aarch64-pc-windows-msvc": "aarch64-pc-windows-msvc",
    # macOS
    "darwin-aarch64": "aarch64-apple-darwin",
    "darwin-arm64": "aarch64-apple-darwin",
    "macos-arm64": "aarch64-apple-darwin",
    "aarch64-apple-darwin": "aarch64-apple-darwin",
    "darwin-x86_64": "x86_64-apple-darwin",
    "darwin-x64": "x86_64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
    "x86_64-apple-darwin": "x86_64-apple-darwin",
    # Linux
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "linux-x64": "x86_64-unknown-linux-gnu",
    "linux-amd64": "x86_64-unknown-linux-gnu",
    "x86_64-unknown-linux-gnu": "x86_64-unknown-linux-gnu",
    "linux-aarch64": "aarch64-unknown-linux-gnu",
    "linux-arm64": "aarch64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu": "aarch64-unknown-linux-gnu",
}


def detect_target_triple(target: str | None = None) -> str:
    """Resolve Tauri-compatible Rust target triple for the specified target or host system."""
    if target:
        normalized = target.strip().lower()
        if normalized in TARGET_TRIPLE_MAP:
            return TARGET_TRIPLE_MAP[normalized]
        # Allow passing an exact standard 3/4-part target triple
        if re.match(r"^[a-z0-9_]+-[a-z0-9_]+-[a-z0-9_]+(-[a-z0-9_]+)?$", normalized):
            return normalized
        raise ValueError(f"Unsupported target: {target}")

    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        if machine in ("amd64", "x86_64", "x64"):
            return "x86_64-pc-windows-msvc"
        if machine in ("arm64", "aarch64"):
            return "aarch64-pc-windows-msvc"
    elif system == "darwin":
        if machine in ("arm64", "aarch64"):
            return "aarch64-apple-darwin"
        if machine in ("x86_64", "amd64", "x64"):
            return "x86_64-apple-darwin"
    elif system == "linux":
        if machine in ("x86_64", "amd64", "x64"):
            return "x86_64-unknown-linux-gnu"
        if machine in ("aarch64", "arm64"):
            return "aarch64-unknown-linux-gnu"

    raise ValueError(f"Unsupported target system={system} machine={machine}")


def generate_session_token() -> str:
    """Generate a cryptographically secure 64-character hexadecimal session token."""
    return secrets.token_hex(32)


def pick_free_loopback_port() -> int:
    """Bind to an ephemeral port on 127.0.0.1, capture the assigned port, and release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port: int = s.getsockname()[1]
        return port


def get_pyinstaller_command(
    python_exe: str | Path | None = None,
    target_triple: str | None = None,
    dist_dir: Path | str | None = None,
    clean: bool = False,
    entrypoint: Path | str | None = None,
    workpath: Path | str | None = None,
    specpath: Path | str | None = None,
) -> list[str]:
    """Construct PyInstaller execution command for the backend sidecar."""
    py_bin = str(python_exe or sys.executable)
    triple = detect_target_triple(target_triple)
    dist_path = Path(dist_dir or DEFAULT_DIST_DIR).resolve()
    entrypoint_path = Path(entrypoint or DEFAULT_ENTRYPOINT).resolve()

    cmd = [
        py_bin,
        "-m",
        "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name",
        f"backend-sidecar-{triple}",
        "--distpath",
        str(dist_path),
    ]

    if clean:
        cmd.append("--clean")

    if workpath:
        cmd.extend(["--workpath", str(Path(workpath).resolve())])
    if specpath:
        cmd.extend(["--specpath", str(Path(specpath).resolve())])

    # Core hidden imports required by FastAPI + Uvicorn + SQLite + Pydantic
    hidden_imports = [
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "aiosqlite",
        "sqlite3",
        "pydantic",
        "pydantic_settings",
        "app.main",
        "app.config",
    ]
    for hi in hidden_imports:
        cmd.extend(["--hidden-import", hi])

    cmd.append(str(entrypoint_path))
    return cmd


def build_sidecar(
    target_triple: str | None = None,
    dist_dir: Path | str | None = None,
    clean: bool = False,
    dry_run: bool = False,
    python_exe: str | Path | None = None,
    entrypoint: Path | str | None = None,
) -> dict:
    """Build or plan backend sidecar packaging with PyInstaller."""
    triple = detect_target_triple(target_triple)
    dist_path = Path(dist_dir or DEFAULT_DIST_DIR).resolve()

    binary_name = f"backend-sidecar-{triple}.exe" if "windows" in triple else f"backend-sidecar-{triple}"
    output_binary = dist_path / binary_name

    cmd = get_pyinstaller_command(
        python_exe=python_exe,
        target_triple=triple,
        dist_dir=dist_path,
        clean=clean,
        entrypoint=entrypoint,
    )

    result = {
        "command": cmd,
        "target_triple": triple,
        "dist_dir": str(dist_path),
        "output_binary": str(output_binary),
        "dry_run": dry_run,
    }

    if dry_run:
        print(f"[DRY-RUN] Target Triple: {triple}")
        print(f"[DRY-RUN] Output Binary: {output_binary}")
        print(f"[DRY-RUN] Command: {' '.join(cmd)}")
        return result

    dist_path.mkdir(parents=True, exist_ok=True)
    print(f"Building sidecar binary for {triple} into {dist_path}...")
    subprocess.run(cmd, check=True)
    return result


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for sidecar builder."""
    parser = argparse.ArgumentParser(
        description="Package AI Agent Workspace FastAPI backend as a Tauri externalBin sidecar."
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        default=False,
        help="Clean PyInstaller cache before building.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print PyInstaller build command without executing.",
    )
    parser.add_argument(
        "--dist-dir",
        type=str,
        default=str(DEFAULT_DIST_DIR),
        help=f"Target directory for output sidecar binary (default: {DEFAULT_DIST_DIR}).",
    )
    parser.add_argument(
        "--target-triple",
        type=str,
        default=None,
        help="Target triple override (e.g. x86_64-pc-windows-msvc).",
    )
    parser.add_argument(
        "--python-exe",
        type=str,
        default=None,
        help="Path to python executable to invoke PyInstaller.",
    )
    return parser.parse_args(args)


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint."""
    args = parse_args(argv)
    try:
        build_sidecar(
            target_triple=args.target_triple,
            dist_dir=args.dist_dir,
            clean=args.clean,
            dry_run=args.dry_run,
            python_exe=args.python_exe,
        )
        return 0
    except Exception as exc:
        print(f"Error building sidecar: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
