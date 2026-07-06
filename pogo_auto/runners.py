from __future__ import annotations

import os
import subprocess
import sys

from .paths import PROJECT_ROOT, ensure_runtime_dirs


def env_with_serial(adb_serial: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if adb_serial:
        env["POGO_ADB_SERIAL"] = adb_serial
        env["ADB_SERIAL"] = adb_serial
    return env


def run_module(module: str, args: list[str], adb_serial: str | None) -> None:
    ensure_runtime_dirs()
    subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=PROJECT_ROOT,
        check=True,
        env=env_with_serial(adb_serial),
    )
