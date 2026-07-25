from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping


class ScanStatus(str, Enum):
    VERIFIED = "VERIFIED"
    REVIEW = "REVIEW"
    FAILED = "FAILED"


class FailureReason(str, Enum):
    LABELS_NOT_FOUND = "LABELS_NOT_FOUND"
    LABEL_GEOMETRY_INVALID = "LABEL_GEOMETRY_INVALID"
    ATTACK_LOW_CONFIDENCE = "ATTACK_LOW_CONFIDENCE"
    DEFENSE_LOW_CONFIDENCE = "DEFENSE_LOW_CONFIDENCE"
    HP_LOW_CONFIDENCE = "HP_LOW_CONFIDENCE"
    FRAME_DISAGREEMENT = "FRAME_DISAGREEMENT"
    SPECIES_NOT_FOUND = "SPECIES_NOT_FOUND"
    SPECIES_AMBIGUOUS = "SPECIES_AMBIGUOUS"
    FORM_NOT_FOUND = "FORM_NOT_FOUND"
    INCOMPLETE_SCAN = "INCOMPLETE_SCAN"
    MALFORMED_POKEGENIE_RESULT = "MALFORMED_POKEGENIE_RESULT"
    NAVIGATION_UNCONFIRMED = "NAVIGATION_UNCONFIRMED"


@dataclass(frozen=True)
class NativeFrameResult:
    frame_index: int
    screenshot: str
    debug_image: str | None
    species_raw: str | None
    species_normalized: str | None
    attack: int | None
    defense: int | None
    hp: int | None
    label_geometry_confidence: float
    attack_confidence: float
    defense_confidence: float
    hp_confidence: float
    # Per-stat scores for all legal IV hypotheses 0..15.  These are retained
    # so consensus can combine evidence, rather than only compare rounded IVs.
    hypothesis_scores: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    geometry_failure_reasons: tuple[str, ...] = ()
    failure_reasons: tuple[FailureReason, ...] = ()

    @property
    def ivs(self) -> tuple[int, int, int] | None:
        if None in (self.attack, self.defense, self.hp):
            return None
        return self.attack, self.defense, self.hp

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["failure_reasons"] = [reason.value for reason in self.failure_reasons]
        return result


@dataclass(frozen=True)
class NativeConsensusResult:
    scan_id: int
    frames: tuple[NativeFrameResult, ...]
    status: ScanStatus
    selected_species: str | None
    selected_form: str | None
    selected_ivs: tuple[int, int, int] | None
    matching_frame_count: int
    frame_count: int
    consensus_confidence: float
    failure_reasons: tuple[FailureReason, ...] = ()

    @property
    def iv_percent(self) -> float | None:
        if self.status is not ScanStatus.VERIFIED or self.selected_ivs is None:
            return None
        return round(sum(self.selected_ivs) * 100.0 / 45.0, 2)

    @property
    def proposed_iv_percent(self) -> float | None:
        if self.selected_ivs is None:
            return None
        return round(sum(self.selected_ivs) * 100.0 / 45.0, 2)

    @property
    def rename_allowed(self) -> bool:
        return self.status is ScanStatus.VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "identity": {
                "species": self.selected_species,
                "form": self.selected_form,
            },
            # REVIEW values are diagnostic proposals, never final IVs that a
            # downstream rename/PvP path could accidentally consume.
            "ivs": list(self.selected_ivs) if self.status is ScanStatus.VERIFIED and self.selected_ivs else None,
            "verified_ivs": list(self.selected_ivs) if self.status is ScanStatus.VERIFIED and self.selected_ivs else None,
            "proposed_ivs": list(self.selected_ivs) if self.selected_ivs else None,
            "iv_percent": self.iv_percent,
            "verified_iv_percent": self.iv_percent,
            "proposed_iv_percent": self.proposed_iv_percent,
            "scan_status": self.status.value,
            "native_consensus": self.matching_frame_count == self.frame_count,
            "matching_frames": self.matching_frame_count,
            "frame_count": self.frame_count,
            "consensus_confidence": self.consensus_confidence,
            "rename_allowed": self.rename_allowed,
            "failure_reasons": [reason.value for reason in self.failure_reasons],
            "frames": [frame.to_dict() for frame in self.frames],
        }
