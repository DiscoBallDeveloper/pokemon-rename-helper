from __future__ import annotations

from pathlib import Path

from .paths import CROPS_DIR, LOGS_DIR, SCREENSHOTS_DIR, ensure_runtime_dirs


DEFAULT_CLEAN_PATTERNS = {
    SCREENSHOTS_DIR: ("*.png", "*.jpg", "*.jpeg", "*.webp"),
    CROPS_DIR: ("*.png", "*.jpg", "*.jpeg", "*.webp"),
    LOGS_DIR: ("*.csv", "*.log", "*.txt"),
}


def remove_matching_files(directory: Path, patterns: tuple[str, ...]) -> int:
    if not directory.exists():
        return 0

    removed = 0
    for pattern in patterns:
        for path in directory.glob(pattern):
            if path.is_file():
                path.unlink()
                removed += 1
    return removed


def clean_runtime_outputs() -> int:
    """Remove old screenshots, crops, and logs before a fresh run.

    Templates are intentionally not touched.
    """
    ensure_runtime_dirs()

    removed = 0
    for directory, patterns in DEFAULT_CLEAN_PATTERNS.items():
        removed += remove_matching_files(directory, patterns)

    return removed
