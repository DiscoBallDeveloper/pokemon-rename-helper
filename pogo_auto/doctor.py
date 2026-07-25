from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

from .adb import list_devices
from .paths import TEMPLATES_DIR


REQUIRED_TEMPLATES = [
    "rename_pencil_template.png",
    "rename_ok_template.png",
    "three_bar_menu_template.png",
    "right_triangle_template.png",
    "pokegenie_overlay_template.png",
]


def check_python_import(module_name: str) -> tuple[bool, str]:
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return False, f"missing Python module: {module_name}"
    return True, f"ok: Python module {module_name}"


def check_adb_binary() -> tuple[bool, str]:
    adb = shutil.which("adb")
    if not adb:
        return False, "missing adb executable in PATH"
    return True, f"ok: adb found at {adb}"


def check_adb_devices() -> tuple[bool, str]:
    try:
        devices = list_devices()
    except Exception as exc:
        return False, f"adb devices failed: {exc}"

    if not devices:
        return False, "no authorized ADB device found"
    return True, "ok: ADB devices: " + ", ".join(devices)


def check_templates() -> list[tuple[bool, str]]:
    results: list[tuple[bool, str]] = []
    for name in REQUIRED_TEMPLATES:
        path = TEMPLATES_DIR / name
        if path.exists():
            results.append((True, f"ok: {path}"))
        else:
            results.append((False, f"missing template: {path}"))
    return results


def run_doctor(include_device: bool = True) -> int:
    checks: list[tuple[bool, str]] = []

    checks.append(check_adb_binary())
    if include_device:
        checks.append(check_adb_devices())

    for module in ("cv2", "pandas", "PIL", "paddleocr"):
        checks.append(check_python_import(module))

    checks.extend(check_templates())

    failures = 0
    for ok, msg in checks:
        prefix = "PASS" if ok else "FAIL"
        print(f"[{prefix}] {msg}")
        if not ok:
            failures += 1

    if failures:
        print(f"\nDoctor found {failures} problem(s).")
        return 1

    print("\nDoctor passed.")
    return 0
