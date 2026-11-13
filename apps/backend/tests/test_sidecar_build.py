"""Tests for PyInstaller backend sidecar packaging and target triple resolution (Task 5.5)."""

import platform
import re
import socket
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

# Ensure repository root is on sys.path so scripts package can be imported
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_sidecar import (
    detect_target_triple,
    generate_session_token,
    pick_free_loopback_port,
    get_pyinstaller_command,
    build_sidecar,
    parse_args,
    main,
)


class TestTargetTripleDetection:
    """Test suite for Rust/Tauri target triple mapping."""

    @pytest.mark.parametrize(
        "input_target,expected_triple",
        [
            ("windows-x86_64", "x86_64-pc-windows-msvc"),
            ("win32-x64", "x86_64-pc-windows-msvc"),
            ("windows-amd64", "x86_64-pc-windows-msvc"),
            ("x86_64-pc-windows-msvc", "x86_64-pc-windows-msvc"),
            ("windows-aarch64", "aarch64-pc-windows-msvc"),
            ("windows-arm64", "aarch64-pc-windows-msvc"),
            ("darwin-aarch64", "aarch64-apple-darwin"),
            ("darwin-arm64", "aarch64-apple-darwin"),
            ("macos-arm64", "aarch64-apple-darwin"),
            ("aarch64-apple-darwin", "aarch64-apple-darwin"),
            ("darwin-x86_64", "x86_64-apple-darwin"),
            ("darwin-x64", "x86_64-apple-darwin"),
            ("macos-x86_64", "x86_64-apple-darwin"),
            ("x86_64-apple-darwin", "x86_64-apple-darwin"),
            ("linux-x86_64", "x86_64-unknown-linux-gnu"),
            ("linux-x64", "x86_64-unknown-linux-gnu"),
            ("linux-amd64", "x86_64-unknown-linux-gnu"),
            ("x86_64-unknown-linux-gnu", "x86_64-unknown-linux-gnu"),
            ("linux-aarch64", "aarch64-unknown-linux-gnu"),
            ("linux-arm64", "aarch64-unknown-linux-gnu"),
            ("aarch64-unknown-linux-gnu", "aarch64-unknown-linux-gnu"),
        ],
    )
    def test_explicit_target_mapping(self, input_target: str, expected_triple: str):
        assert detect_target_triple(input_target) == expected_triple

    def test_auto_detect_current_platform(self):
        triple = detect_target_triple()
        assert isinstance(triple, str)
        assert len(triple) > 0
        assert "-" in triple

    @pytest.mark.parametrize(
        "mock_system,mock_machine,expected_triple",
        [
            ("Windows", "AMD64", "x86_64-pc-windows-msvc"),
            ("Windows", "ARM64", "aarch64-pc-windows-msvc"),
            ("Darwin", "arm64", "aarch64-apple-darwin"),
            ("Darwin", "x86_64", "x86_64-apple-darwin"),
            ("Linux", "x86_64", "x86_64-unknown-linux-gnu"),
            ("Linux", "aarch64", "aarch64-unknown-linux-gnu"),
        ],
    )
    def test_auto_detect_mocked_platforms(
        self, mock_system: str, mock_machine: str, expected_triple: str
    ):
        with patch("platform.system", return_value=mock_system), patch(
            "platform.machine", return_value=mock_machine
        ):
            assert detect_target_triple() == expected_triple

    def test_unsupported_target_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported target"):
            detect_target_triple("solaris-sparc")


class TestPortAndTokenGeneration:
    """Test suite for loopback port allocator and auth token generator."""

    def test_generate_session_token_format_and_entropy(self):
        token1 = generate_session_token()
        token2 = generate_session_token()

        assert len(token1) == 64
        assert len(token2) == 64
        assert re.fullmatch(r"^[0-9a-f]{64}$", token1) is not None
        assert re.fullmatch(r"^[0-9a-f]{64}$", token2) is not None
        assert token1 != token2

    def test_pick_free_loopback_port_bindable(self):
        port = pick_free_loopback_port()
        assert isinstance(port, int)
        assert port > 1024
        assert port <= 65535

        # Verify that the port can be bound (confirming it was released by picker)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_sock:
            test_sock.bind(("127.0.0.1", port))
            test_sock.listen(1)
            bound_port = test_sock.getsockname()[1]
            assert bound_port == port


class TestPyInstallerCommandGeneration:
    """Test suite for PyInstaller command line construction."""

    def test_command_generation_flags(self, tmp_path: Path):
        dist_dir = tmp_path / "binaries"
        cmd = get_pyinstaller_command(
            python_exe="python",
            target_triple="x86_64-pc-windows-msvc",
            dist_dir=dist_dir,
            clean=True,
            entrypoint="app.main",
        )

        assert "python" in cmd[0]
        assert "PyInstaller" in cmd or "-m" in cmd
        assert "--onefile" in cmd
        assert "--noconsole" in cmd
        assert "--clean" in cmd
        assert "--distpath" in cmd
        assert str(dist_dir) in cmd
        assert "--name" in cmd
        assert "backend-sidecar-x86_64-pc-windows-msvc" in cmd

        # Verify hidden imports
        cmd_str = " ".join(cmd)
        assert "uvicorn" in cmd_str
        assert "fastapi" in cmd_str
        assert "app.main" in cmd_str

    def test_command_generation_clean_false(self, tmp_path: Path):
        cmd = get_pyinstaller_command(
            python_exe="python",
            target_triple="x86_64-apple-darwin",
            dist_dir=tmp_path,
            clean=False,
        )
        assert "--clean" not in cmd
        assert "backend-sidecar-x86_64-apple-darwin" in cmd


class TestSidecarBuildCliAndDryRun:
    """Test suite for CLI arguments and dry-run execution."""

    def test_cli_argument_defaults(self):
        args = parse_args([])
        assert args.clean is False
        assert args.dry_run is False
        assert args.target_triple is None
        assert "binaries" in args.dist_dir

    def test_cli_argument_overrides(self, tmp_path: Path):
        custom_dist = str(tmp_path / "custom_bin")
        args = parse_args(
            [
                "--clean",
                "--dry-run",
                "--target-triple",
                "x86_64-unknown-linux-gnu",
                "--dist-dir",
                custom_dist,
                "--python-exe",
                "/usr/bin/python3",
            ]
        )
        assert args.clean is True
        assert args.dry_run is True
        assert args.target_triple == "x86_64-unknown-linux-gnu"
        assert args.dist_dir == custom_dist
        assert args.python_exe == "/usr/bin/python3"

    def test_build_sidecar_dry_run(self, tmp_path: Path):
        result = build_sidecar(
            target_triple="x86_64-pc-windows-msvc",
            dist_dir=tmp_path / "bin",
            dry_run=True,
            clean=False,
        )

        assert isinstance(result, dict)
        assert result["dry_run"] is True
        assert result["target_triple"] == "x86_64-pc-windows-msvc"
        assert "backend-sidecar-x86_64-pc-windows-msvc" in result["output_binary"]
        assert result["output_binary"].endswith(".exe")
        assert any("--onefile" in item for item in result["command"])

    def test_build_sidecar_dry_run_non_windows(self, tmp_path: Path):
        result = build_sidecar(
            target_triple="aarch64-apple-darwin",
            dist_dir=tmp_path / "bin",
            dry_run=True,
            clean=True,
        )
        assert result["dry_run"] is True
        assert result["target_triple"] == "aarch64-apple-darwin"
        assert not result["output_binary"].endswith(".exe")

    def test_main_cli_dry_run(self, capsys):
        exit_code = main(["--dry-run", "--target-triple", "x86_64-pc-windows-msvc"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "backend-sidecar-x86_64-pc-windows-msvc" in captured.out
