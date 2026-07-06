from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
import json


@dataclass
class ScanSettings:
    count: int = 5
    threshold: float = 95.0
    iv_floor: int = 14
    wait_before_ocr: float = 3.0
    wait_after_next: float = 3.0


@dataclass
class RenameSettings:
    wait_after_pencil: float = 1.5
    wait_after_appraise_before_triangle_reveal: float = 1.5
    wait_after_triangle_reveal: float = 2.0
    reverse_log_order: bool = True
    navigation_direction: str = "left"


@dataclass
class AppSettings:
    pokemon_go_package: str = "com.nianticlabs.pokemongo"
    pokegenie_packages: tuple[str, ...] = ("com.cjin.pokegenie.standard", "com.cjin.pokegenie")


@dataclass
class AppConfig:
    adb_serial: str | None = None
    scan: ScanSettings = field(default_factory=ScanSettings)
    rename: RenameSettings = field(default_factory=RenameSettings)
    apps: AppSettings = field(default_factory=AppSettings)

    @classmethod
    def from_json(cls, path: str | Path) -> "AppConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        scan = ScanSettings(**data.get("scan", {}))
        rename = RenameSettings(**data.get("rename", {}))
        apps_data = data.get("apps", {})
        if "pokegenie_packages" in apps_data:
            apps_data["pokegenie_packages"] = tuple(apps_data["pokegenie_packages"])
        apps = AppSettings(**apps_data)
        return cls(adb_serial=data.get("adb_serial"), scan=scan, rename=rename, apps=apps)

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
