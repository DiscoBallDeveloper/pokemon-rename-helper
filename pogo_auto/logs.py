from __future__ import annotations

from pathlib import Path
import csv
from typing import Iterable, Mapping, Any


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: str | Path, rows: Iterable[Mapping[str, Any]], fieldnames: list[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))


def selected_rows_for_rename(rows: list[dict[str, str]], count: int, reverse: bool = True) -> list[dict[str, str]]:
    selected = rows[:count]
    return list(reversed(selected)) if reverse else selected
