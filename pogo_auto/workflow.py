from __future__ import annotations

from .adb import AdbTarget, kill_pokegenie, require_device
from .cleanup import clean_runtime_outputs
from .rename import run_rename_pass
from .scan import run_scan_pass


def run_scan(
    count: int,
    adb_serial: str | None = None,
    wait_before_ocr: float = 3.0,
    wait_after_next: float = 3.0,
    execute: bool = True,
) -> None:
    run_scan_pass(
        count=count,
        adb_serial=adb_serial,
        wait_before_ocr=wait_before_ocr,
        wait_after_next=wait_after_next,
        execute=execute,
    )


def run_rename(
    count: int,
    adb_serial: str | None = None,
    wait_after_pencil: float = 1.5,
    wait_after_appraise_before_triangle_reveal: float = 1.5,
    wait_after_triangle_reveal: float = 2.0,
    execute: bool = True,
) -> None:
    run_rename_pass(
        count=count,
        adb_serial=adb_serial,
        wait_after_pencil=wait_after_pencil,
        wait_after_appraise_before_triangle_reveal=wait_after_appraise_before_triangle_reveal,
        wait_after_triangle_reveal=wait_after_triangle_reveal,
        execute=execute,
    )


def run_workflow(
    count: int,
    adb_serial: str | None = None,
    execute: bool = True,
    wait_before_ocr: float = 3.0,
    wait_after_next: float = 3.0,
    wait_after_pencil: float = 1.5,
    wait_after_appraise_before_triangle_reveal: float = 1.5,
    wait_after_triangle_reveal: float = 2.0,
    clean_start: bool = True,
) -> None:
    serial = require_device(adb_serial) if execute else adb_serial

    if clean_start:
        removed = clean_runtime_outputs()
        print(f"Clean start: removed {removed} old screenshot/crop/log file(s).")

    run_scan(
        count=count,
        adb_serial=serial,
        wait_before_ocr=wait_before_ocr,
        wait_after_next=wait_after_next,
        execute=execute,
    )

    if execute:
        kill_pokegenie(AdbTarget(serial=serial))

    run_rename(
        count=count,
        adb_serial=serial,
        wait_after_pencil=wait_after_pencil,
        wait_after_appraise_before_triangle_reveal=wait_after_appraise_before_triangle_reveal,
        wait_after_triangle_reveal=wait_after_triangle_reveal,
        execute=execute,
    )
