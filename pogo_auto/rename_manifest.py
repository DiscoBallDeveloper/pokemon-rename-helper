from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .native_models import NativeConsensusResult, ScanStatus


def write_manifest(path: str | Path, scans: Iterable[NativeConsensusResult]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "scans": [scan.to_dict() for scan in scans]}
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def verified_entries(path: str | Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = payload.get("scans", [])
    return [
        entry for entry in entries
        if entry.get("scan_status") == ScanStatus.VERIFIED.value
        and entry.get("rename_allowed") is True
        and entry.get("ivs") is not None
        and entry.get("identity", {}).get("species")
        and entry.get("identity", {}).get("form")
    ]
