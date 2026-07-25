from pogo_auto.native_consensus import combine_hypothesis_scores, consensus
from pogo_auto.native_models import FailureReason, NativeFrameResult, ScanStatus


def frame(index: int, ivs=(8, 4, 1), species="wooloo", confidence=0.95):
    return NativeFrameResult(
        frame_index=index,
        screenshot=f"frame-{index}.png",
        debug_image=None,
        species_raw=species,
        species_normalized=species,
        attack=ivs[0], defense=ivs[1], hp=ivs[2],
        label_geometry_confidence=confidence,
        attack_confidence=confidence,
        defense_confidence=confidence,
        hp_confidence=confidence,
    )


def test_exact_three_frame_consensus_is_verified():
    result = consensus(1, [frame(1), frame(2), frame(3)], form="NORMAL")
    assert result.status is ScanStatus.VERIFIED
    assert result.selected_ivs == (8, 4, 1)
    assert result.iv_percent == 28.89


def test_frame_disagreement_is_review():
    result = consensus(1, [frame(1), frame(2, ivs=(8, 4, 2)), frame(3)], form="NORMAL")
    assert result.status is ScanStatus.REVIEW
    assert FailureReason.FRAME_DISAGREEMENT in result.failure_reasons
    manifest = result.to_dict()
    assert manifest["ivs"] is None
    assert manifest["verified_ivs"] is None
    assert manifest["proposed_ivs"] is not None
    assert manifest["rename_allowed"] is False


def test_missing_form_is_review():
    result = consensus(1, [frame(1), frame(2), frame(3)])
    assert result.status is ScanStatus.REVIEW
    assert FailureReason.FORM_NOT_FOUND in result.failure_reasons


def test_missing_species_is_not_reported_as_frame_disagreement():
    result = consensus(1, [frame(1, species=None), frame(2, species=None), frame(3, species=None)], form="NORMAL")
    assert result.status is ScanStatus.REVIEW
    assert FailureReason.SPECIES_NOT_FOUND in result.failure_reasons
    assert FailureReason.FRAME_DISAGREEMENT not in result.failure_reasons


def test_combined_hypothesis_scores_resist_one_noisy_frame():
    def scores(winner):
        values = [0.1] * 16
        values[winner] = 0.9
        return tuple(values)

    frames = [
        frame(1, ivs=(8, 4, 1)),
        frame(2, ivs=(8, 4, 1)),
        frame(3, ivs=(7, 5, 2)),
    ]
    for item, ivs in zip(frames, ((8, 4, 1), (8, 4, 1), (7, 5, 2))):
        object.__setattr__(item, "hypothesis_scores", {"attack": scores(ivs[0]), "defense": scores(ivs[1]), "hp": scores(ivs[2])})
    combined, margins = combine_hypothesis_scores(frames)
    assert combined == (8, 4, 1)
    assert min(margins.values()) > 0
