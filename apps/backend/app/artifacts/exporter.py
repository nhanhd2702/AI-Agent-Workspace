"""File Exporter, Temporary File Cleanup, and Path Organization (Task 5.3 / F06.5).

Implements:
1. FileExporter: Packages files into ZIP archives with pre-flight disk space validation.
2. cleanup_old_temp_files: Prunes files older than N days from temp/, frames/, cache/.
3. organize_file_path: Standardizes workspace storage paths into workspace/{project}/{YYYY-MM}/{task_slug}/{filename}.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import time
from typing import List, Union
import zipfile


class InsufficientDiskSpaceError(Exception):
    """Raised when available storage on destination volume is insufficient for export operation."""
    pass


@dataclass
class ExportResult:
    """Metadata result of a ZIP export operation."""
    dest: Path
    file_count: int
    total_bytes: int
    zip_size: int


class FileExporter:
    """Packaging and export engine for artifacts and workspace files."""

    @classmethod
    def export_zip(
        cls,
        file_paths: List[Union[Path, str]],
        dest: Union[Path, str],
        min_free_bytes: int = 10 * 1024 * 1024,
    ) -> ExportResult:
        """Packages a list of files into a single ZIP archive.

        Pre-flight checks available disk space on the target volume. If available free
        bytes is less than (sum of input file sizes + min_free_bytes buffer), raises
        InsufficientDiskSpaceError.

        Args:
            file_paths: List of absolute or relative Path/str file paths to package.
            dest: Target destination .zip file path.
            min_free_bytes: Safety buffer of required free disk space in bytes (default 10MB).

        Returns:
            ExportResult with destination path, file count, raw total bytes, and compressed zip size.

        Raises:
            InsufficientDiskSpaceError: If target volume lacks required free space.
            FileNotFoundError: If any input file cannot be found.
        """
        dest_path = Path(dest).resolve()
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        resolved_files: list[Path] = []
        total_input_bytes = 0

        for fp in file_paths:
            p = Path(fp).resolve()
            if not p.is_file():
                raise FileNotFoundError(f"Input file not found: {p}")
            resolved_files.append(p)
            total_input_bytes += p.stat().st_size

        # Pre-flight disk space check on destination directory
        try:
            usage = shutil.disk_usage(dest_path.parent)
            required_space = total_input_bytes + min_free_bytes
            if usage.free < required_space:
                raise InsufficientDiskSpaceError(
                    f"Insufficient disk space on {dest_path.parent}: "
                    f"requires {required_space} bytes, only {usage.free} bytes available."
                )
        except OSError as exc:
            # If disk_usage fails (e.g. non-standard path), allow operation or re-raise
            pass

        # Write ZIP archive safely (preventing path traversal and absolute path leak)
        with zipfile.ZipFile(dest_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in resolved_files:
                # Store by filename (arcname) to avoid absolute directory leakage
                zf.write(p, arcname=p.name)

        zip_size = dest_path.stat().st_size

        return ExportResult(
            dest=dest_path,
            file_count=len(resolved_files),
            total_bytes=total_input_bytes,
            zip_size=zip_size,
        )


def cleanup_old_temp_files(workspace: Union[Path, str], days: int = 7) -> dict[str, int]:
    """Scans temp/, frames/, and cache/ directories under workspace and prunes files older than days.

    Args:
        workspace: Path to workspace root.
        days: Age threshold in days (default 7 days).

    Returns:
        dict: {"cleaned_files": int, "freed_bytes": int}
    """
    workspace_path = Path(workspace).resolve()
    target_subdirs = ("temp", "frames", "cache")

    cutoff_seconds = time.time() - (days * 86400)
    cleaned_count = 0
    freed_bytes = 0

    for subdir_name in target_subdirs:
        target_dir = workspace_path / subdir_name
        if not target_dir.exists() or not target_dir.is_dir():
            continue

        for root, dirs, files in os.walk(target_dir):
            for file_name in files:
                file_path = Path(root) / file_name
                try:
                    stat = file_path.stat()
                    if stat.st_mtime < cutoff_seconds:
                        size = stat.st_size
                        file_path.unlink()
                        cleaned_count += 1
                        freed_bytes += size
                except (OSError, FileNotFoundError):
                    continue

    return {"cleaned_files": cleaned_count, "freed_bytes": freed_bytes}


def organize_file_path(
    workspace: Union[Path, str],
    project: str,
    task_slug: str,
    filename: str,
) -> Path:
    """Constructs organized workspace path: workspace/{project}/{YYYY-MM}/{task_slug}/{filename}.

    Sanitizes project, task_slug, and filename to prevent path traversal.

    Args:
        workspace: Workspace root directory.
        project: Project ID or slug (e.g. 'proj-ecommerce').
        task_slug: Task slug or ID (e.g. 'tao-landing-page').
        filename: Destination file name.

    Returns:
        Path: Formatted, resolved Path within workspace.
    """
    ws = Path(workspace).resolve()
    clean_project = Path(project).name or "default"
    clean_task_slug = Path(task_slug).name or "general"
    clean_filename = Path(filename).name

    month_str = datetime.now(timezone.utc).strftime("%Y-%m")

    target_dir = ws / clean_project / month_str / clean_task_slug
    target_dir.mkdir(parents=True, exist_ok=True)

    return target_dir / clean_filename
