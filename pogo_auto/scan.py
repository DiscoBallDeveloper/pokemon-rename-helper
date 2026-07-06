from __future__ import annotations

from .adb import require_device
from .runners import run_module


def run_scan_pass(
    count: int,
    adb_serial: str | None = None,
    wait_before_ocr: float = 3.0,
    wait_after_next: float = 3.0,
    execute: bool = True,
) -> None:
    """Run the stable scan pass.

    This currently delegates to legacy_scan while the scanner is being split into
    OCR/template/logging modules.
    """
    if execute:
        require_device(adb_serial)

    args = [
        "--count", str(count),
        "--wait-before-ocr", str(wait_before_ocr),
        "--wait-after-next", str(wait_after_next),
    ]
    if execute:
        args.append("--execute")

    run_module("pogo_auto.legacy_scan", args, adb_serial)
