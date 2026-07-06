from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def format_percent(value: Optional[float]) -> str:
    if value is None:
        return ""
    s = f"{value:.1f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def compact_percent(value: float) -> str:
    s = f"{value:.1f}".replace(".", "")
    if s.endswith("0") and len(s) > 2:
        s = s[:-1]
    return s


def pvp_name(great: Optional[float], ultra: Optional[float]) -> str:
    """Build a short PvP nickname: G981, U954, or G972U954."""
    parts: list[str] = []
    if great is not None:
        parts.append(f"G{compact_percent(great)}")
    if ultra is not None:
        parts.append(f"U{compact_percent(ultra)}")
    return "".join(parts)


def iv_name(attack: int, defense: int, hp: int) -> str:
    """Compact IV nickname, e.g. 151414."""
    return f"{attack}{defense}{hp}"


@dataclass(frozen=True)
class RenameDecision:
    decision: str
    rename_to: str
    reason: str


def classify_for_name(
    attack: int | None,
    defense: int | None,
    hp: int | None,
    great: float | None,
    ultra: float | None,
    threshold: float = 95.0,
    iv_floor: int = 14,
) -> RenameDecision:
    if attack is not None and defense is not None and hp is not None:
        if attack >= iv_floor and defense >= iv_floor and hp >= iv_floor:
            name = iv_name(attack, defense, hp)
            return RenameDecision("KEEP", name, f"IV floor keep: {attack}-{defense}-{hp}")

    gr_keep = great is not None and great >= threshold
    ul_keep = ultra is not None and ultra >= threshold

    if gr_keep or ul_keep:
        name = pvp_name(great if gr_keep else None, ultra if ul_keep else None)
        bits = []
        if great is not None:
            bits.append(f"GR={great:.1f}%")
        if ultra is not None:
            bits.append(f"UL={ultra:.1f}%")
        return RenameDecision("KEEP", name, f"PvP keep: {', '.join(bits)}")

    return RenameDecision("RENAME_CANDIDATE", "delete1", "Below keep thresholds")


def pvp_name_with_markers(
    great: Optional[float],
    ultra: Optional[float],
    great_marker: Optional[str] = None,
    ultra_marker: Optional[str] = None,
) -> str:
    """Build a compact marker-aware PvP name: G6371, U9541, G9720U9542."""
    parts: list[str] = []
    if great is not None:
        parts.append(f"G{compact_percent(great)}{great_marker or ''}")
    if ultra is not None:
        parts.append(f"U{compact_percent(ultra)}{ultra_marker or ''}")
    return "".join(parts)
