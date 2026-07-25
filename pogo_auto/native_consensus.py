from __future__ import annotations

from collections import Counter
from statistics import median

from .native_models import FailureReason, NativeConsensusResult, NativeFrameResult, ScanStatus


def normalize_species(value: str | None) -> str | None:
    if not value:
        return None
    normalized = " ".join(value.casefold().split())
    return normalized or None


def combine_hypothesis_scores(
    frames: list[NativeFrameResult],
) -> tuple[tuple[int, int, int] | None, dict[str, float]]:
    """Median-combine each bar's 16 legal-state scores across frames.

    This does not relax the conservative exact-frame gate below; it preserves
    useful evidence and provides a stable proposed tuple for REVIEW records.
    """
    values: list[int] = []
    margins: dict[str, float] = {}
    for name in ("attack", "defense", "hp"):
        rows = [frame.hypothesis_scores.get(name) for frame in frames]
        if not rows or any(row is None or len(row) != 16 for row in rows):
            return None, {}
        combined = [median([float(row[index]) for row in rows if row is not None]) for index in range(16)]
        ordered = sorted(range(16), key=lambda index: combined[index], reverse=True)
        values.append(ordered[0])
        margins[name] = combined[ordered[0]] - combined[ordered[1]]
    return tuple(values), margins  # type: ignore[return-value]


def consensus(
    scan_id: int,
    frames: list[NativeFrameResult],
    *,
    form: str | None = None,
    min_bar_confidence: float = 0.65,
    require_all_frames: bool = True,
) -> NativeConsensusResult:
    """Conservatively accept only exact complete native-frame agreement."""
    reasons: set[FailureReason] = set()
    complete = [frame for frame in frames if frame.ivs is not None]
    if len(complete) != len(frames):
        reasons.add(FailureReason.INCOMPLETE_SCAN)

    tuples = Counter(frame.ivs for frame in complete if frame.ivs is not None)
    voted_ivs, matches = (tuples.most_common(1)[0] if tuples else (None, 0))
    combined_ivs, _combined_margins = combine_hypothesis_scores(frames)
    selected_ivs = combined_ivs or voted_ivs
    species = Counter(
        frame.species_normalized for frame in frames if frame.species_normalized
    )
    selected_species, species_matches = (species.most_common(1)[0] if species else (None, 0))

    if selected_ivs is None:
        reasons.add(FailureReason.INCOMPLETE_SCAN)
    if selected_species is None:
        reasons.add(FailureReason.SPECIES_NOT_FOUND)
    if len(tuples) > 1 or (species and len(species) > 1):
        reasons.add(FailureReason.FRAME_DISAGREEMENT)
    if require_all_frames:
        if selected_ivs is not None and matches != len(frames):
            reasons.add(FailureReason.FRAME_DISAGREEMENT)
        if selected_species is not None and species_matches != len(frames):
            reasons.add(FailureReason.FRAME_DISAGREEMENT)
    if form is None:
        reasons.add(FailureReason.FORM_NOT_FOUND)

    for frame in frames:
        if frame.attack_confidence < min_bar_confidence:
            reasons.add(FailureReason.ATTACK_LOW_CONFIDENCE)
        if frame.defense_confidence < min_bar_confidence:
            reasons.add(FailureReason.DEFENSE_LOW_CONFIDENCE)
        if frame.hp_confidence < min_bar_confidence:
            reasons.add(FailureReason.HP_LOW_CONFIDENCE)
        reasons.update(frame.failure_reasons)

    confidence = min(
        (min(frame.attack_confidence, frame.defense_confidence, frame.hp_confidence) for frame in frames),
        default=0.0,
    )
    status = ScanStatus.VERIFIED if not reasons else ScanStatus.REVIEW
    return NativeConsensusResult(
        scan_id=scan_id,
        frames=tuple(frames),
        status=status,
        selected_species=selected_species,
        selected_form=form,
        selected_ivs=selected_ivs,
        matching_frame_count=matches,
        frame_count=len(frames),
        consensus_confidence=confidence,
        failure_reasons=tuple(sorted(reasons, key=lambda reason: reason.value)),
    )
