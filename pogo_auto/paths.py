from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAPTURES_DIR = PROJECT_ROOT / "captures"
TEMPLATES_DIR = CAPTURES_DIR / "templates"
LOGS_DIR = CAPTURES_DIR / "logs"
SCREENSHOTS_DIR = CAPTURES_DIR / "screenshots"
CROPS_DIR = CAPTURES_DIR / "crops"


def ensure_runtime_dirs() -> None:
    for path in (TEMPLATES_DIR, LOGS_DIR, SCREENSHOTS_DIR, CROPS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def log_path(name: str) -> Path:
    ensure_runtime_dirs()
    return LOGS_DIR / name
