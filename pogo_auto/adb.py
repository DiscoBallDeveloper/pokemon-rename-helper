from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AdbTarget:
    """USB or Wi-Fi ADB target."""
    serial: Optional[str] = None

    @classmethod
    def from_env(cls) -> "AdbTarget":
        return cls(serial=os.environ.get("POGO_ADB_SERIAL") or os.environ.get("ADB_SERIAL"))

    def base_cmd(self) -> list[str]:
        return ["adb", "-s", self.serial] if self.serial else ["adb"]

    def run(
        self,
        *args: str,
        check: bool = True,
        capture_output: bool = False,
        text: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*self.base_cmd(), *map(str, args)],
            check=check,
            capture_output=capture_output,
            text=text,
            timeout=timeout,
        )

    def shell(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return self.run("shell", *args, check=check)

    def input_tap(self, x: int, y: int) -> None:
        self.shell("input", "tap", str(x), str(y))

    def input_text(self, text: str) -> None:
        import shlex
        safe = text.replace(" ", "%s")
        self.shell("input", "text", shlex.quote(safe))

    def screencap_png(self) -> bytes:
        result = self.run("exec-out", "screencap", "-p", capture_output=True, text=False)
        return result.stdout

    def wm_size(self) -> tuple[int, int]:
        result = self.run("shell", "wm", "size", capture_output=True)
        out = result.stdout
        # expected: Physical size: 1008x2244
        import re
        m = re.search(r"(\d+)x(\d+)", out)
        if not m:
            raise RuntimeError(f"Could not parse adb wm size output: {out!r}")
        return int(m.group(1)), int(m.group(2))


def list_devices() -> list[str]:
    result = subprocess.run(["adb", "devices"], check=True, capture_output=True, text=True)
    devices: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def require_device(serial: str | None = None) -> str | None:
    devices = list_devices()
    if serial:
        if serial not in devices:
            raise RuntimeError(f"ADB device {serial!r} not found. Connected: {devices}")
        return serial
    if not devices:
        raise RuntimeError("No ADB device found. Run: pogo devices")
    if len(devices) > 1:
        raise RuntimeError(
            "More than one ADB device found. Re-run with --adb-serial. "
            f"Connected: {devices}"
        )
    return devices[0]


def connect_wifi(host: str, port: int = CONNECT_PORT) -> None:
    subprocess.run(["adb", "connect", f"{host}:{port}"], check=True)


def pair_wifi(host: str, port: int) -> None:
    subprocess.run(["adb", "pair", f"{host}:{port}"], check=True)


def kill_pokegenie(target: AdbTarget | None = None) -> None:
    target = target or AdbTarget.from_env()
    for pkg in ("com.cjin.pokegenie.standard", "com.cjin.pokegenie"):
        target.run("shell", "am", "force-stop", pkg, check=False)
    target.run("shell", "monkey", "-p", "com.nianticlabs.pokemongo", "1", check=False)
