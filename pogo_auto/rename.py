from __future__ import annotations

from .adb import require_device
from .runners import run_module


def run_rename_pass(
    count: int,
    adb_serial: str | None = None,
    wait_after_pencil: float = 1.5,
    wait_after_appraise_before_triangle_reveal: float = 1.5,
    wait_after_triangle_reveal: float = 2.0,
    execute: bool = True,
) -> None:
    """Run the stable rename pass.

    This currently delegates to legacy_rename while the renamer is being split
    into UI/navigation/action modules.
    """
    if execute:
        require_device(adb_serial)

    args = [
        "--count", str(count),
        "--wait-after-pencil", str(wait_after_pencil),
        "--wait-after-appraise-before-triangle-reveal", str(wait_after_appraise_before_triangle_reveal),
        "--wait-after-triangle-reveal", str(wait_after_triangle_reveal),
    ]
    if execute:
        args.append("--execute")

    run_module("pogo_auto.legacy_rename", args, adb_serial)
