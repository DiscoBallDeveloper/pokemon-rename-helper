from __future__ import annotations

import hashlib
from pathlib import Path
import time

import cv2
import numpy as np

from .adb import AdbTarget, require_device
from .legacy_scan import make_ocr, run_ocr
from .native_consensus import consensus, normalize_species
from .native_models import FailureReason, NativeFrameResult
from .navigation import swipe_triangle_level
from .ocr_anchored_appraisal import OcrAnchoredAppraisalDetector
from .paths import CROPS_DIR, SCREENSHOTS_DIR, TEMPLATES_DIR, ensure_runtime_dirs
from .rename_manifest import write_manifest
from .ui import DEFAULT_SCREEN


def _capture(target: AdbTarget, path: Path) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(target.screencap_png(), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Could not decode ADB screenshot")
    if not cv2.imwrite(str(path), image):
        raise IOError(f"Could not write screenshot: {path}")
    return image


def _fingerprint(image: np.ndarray) -> str:
    """A stable, lightweight detail-screen fingerprint for swipe verification."""
    h, w = image.shape[:2]
    crop = image[0:int(h * 0.48), 0:w]
    small = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (64, 64))
    return hashlib.sha256(small.tobytes()).hexdigest()


def _text_center(rows: list[dict], expected: str) -> tuple[int, int] | None:
    for row in rows:
        if str(row.get("text", "")).strip().casefold() != expected.casefold():
            continue
        box = row.get("box")
        try:
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
        except (TypeError, ValueError, IndexError):
            continue
        return round((min(xs) + max(xs)) / 2), round((min(ys) + max(ys)) / 2)
    return None


def _three_bar_center(image: np.ndarray) -> tuple[int, int] | None:
    """Locate the known Pokémon GO three-bar control before using coordinates."""
    template_path = TEMPLATES_DIR / "three_bar_menu_template.png"
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        return None
    source = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    needle = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    if source.shape[0] < needle.shape[0] or source.shape[1] < needle.shape[1]:
        return None
    _, score, _, location = cv2.minMaxLoc(cv2.matchTemplate(source, needle, cv2.TM_CCOEFF_NORMED))
    if score < 0.65:
        return None
    return location[0] + needle.shape[1] // 2, location[1] + needle.shape[0] // 2


def _has_appraisal_labels(rows: list[dict]) -> bool:
    labels = {str(row.get("text", "")).strip().casefold() for row in rows}
    return "attack" in labels and ("defense" in labels or "defence" in labels) and "hp" in labels


def _ensure_appraisal_visible(target: AdbTarget, ocr: object) -> None:
    """Dismiss the appraisal introduction only until the actual bars are visible."""
    width, height = target.wm_size()
    settle = DEFAULT_SCREEN.scale_point(DEFAULT_SCREEN.center, width, height)
    for attempt in range(1, 4):
        time.sleep(1.0)
        image = _capture(target, SCREENSHOTS_DIR / f"native_appraisal_ready_{attempt}_{time.strftime('%Y%m%d_%H%M%S')}.png")
        if _has_appraisal_labels(run_ocr(ocr, image)):
            print("Native appraisal labels are visible.")
            return
        print(f"Appraisal introduction/loading state ({attempt}/3); settling at {settle.x},{settle.y}")
        target.input_tap(settle.x, settle.y)
    raise RuntimeError("Appraisal labels did not appear after opening Appraise")


def _open_appraisal(target: AdbTarget, ocr: object) -> None:
    width, height = target.wm_size()
    before = _capture(target, SCREENSHOTS_DIR / f"native_before_menu_{time.strftime('%Y%m%d_%H%M%S')}.png")
    menu_point = _three_bar_center(before)
    if menu_point is None:
        # This is a benign control and retains a scaled fallback, unlike the
        # Appraise action below which must be text-confirmed.
        menu = DEFAULT_SCREEN.scale_point(DEFAULT_SCREEN.three_bar_menu, width, height)
        menu_point = menu.x, menu.y
        print(f"Three-bar template missed; using scaled menu fallback at {menu_point[0]},{menu_point[1]}")
    else:
        print(f"Three-bar template matched at {menu_point[0]},{menu_point[1]}")
    target.input_tap(*menu_point)
    time.sleep(1.0)
    menu_image = _capture(target, SCREENSHOTS_DIR / f"native_before_appraise_{time.strftime('%Y%m%d_%H%M%S')}.png")
    point = _text_center(run_ocr(ocr, menu_image), "Appraise")
    if point is None:
        raise RuntimeError(
            "Appraise menu OCR did not find the Appraise action; no fallback tap was sent. "
            f"Inspect {menu_image}."
        )
    print(f"Appraise OCR matched menu text at {point[0]},{point[1]}")
    target.input_tap(*point)
    # The dialogue is asynchronous. Wait for labels instead of assuming a
    # fixed delay, then dismiss only the introduction state when necessary.
    _ensure_appraisal_visible(target, ocr)


def _frame_result(
    detector: OcrAnchoredAppraisalDetector,
    image: np.ndarray,
    rows: list[dict],
    frame_index: int,
    screenshot: Path,
    debug_image: Path | None,
) -> NativeFrameResult:
    result = detector.detect(image, rows, debug_path=str(debug_image) if debug_image else None)
    confidences = {
        name: result.bars.get(name).confidence if name in result.bars else 0.0
        for name in ("attack", "defense", "hp")
    }

    reasons: list[FailureReason] = []
    if not result.rois:
        reasons.append(
            FailureReason.LABEL_GEOMETRY_INVALID
            if result.geometry is not None
            else FailureReason.LABELS_NOT_FOUND
        )
    if result.attack is None:
        reasons.append(FailureReason.ATTACK_LOW_CONFIDENCE)
    if result.defense is None:
        reasons.append(FailureReason.DEFENSE_LOW_CONFIDENCE)
    if result.hp is None:
        reasons.append(FailureReason.HP_LOW_CONFIDENCE)
    species = normalize_species(result.species_from_sentence)
    if species is None:
        reasons.append(FailureReason.SPECIES_NOT_FOUND)
    return NativeFrameResult(
        frame_index=frame_index,
        screenshot=str(screenshot),
        debug_image=str(debug_image) if debug_image else None,
        species_raw=result.species_from_sentence,
        species_normalized=species,
        attack=result.attack,
        defense=result.defense,
        hp=result.hp,
        label_geometry_confidence=(result.geometry.geometry_confidence if result.geometry else 0.0),
        attack_confidence=confidences["attack"],
        defense_confidence=confidences["defense"],
        hp_confidence=confidences["hp"],
        hypothesis_scores={
            name: tuple(hypothesis.score for hypothesis in bar.hypotheses)
            for name, bar in result.bars.items()
        },
        geometry_failure_reasons=(result.geometry.failure_reasons if result.geometry else ()),
        failure_reasons=tuple(sorted(set(reasons), key=lambda reason: reason.value)),
    )


def run_native_scan(
    *,
    count: int,
    adb_serial: str | None,
    frames_per_pokemon: int,
    frame_delay_ms: int,
    form: str | None,
    manifest_output: str | Path,
    debug_native: bool,
    advance: bool,
    open_appraise: bool,
    execute: bool,
) -> Path | None:
    if frames_per_pokemon < 1:
        raise ValueError("frames_per_pokemon must be positive")
    if frame_delay_ms < 0:
        raise ValueError("frame_delay_ms must not be negative")
    if count > 1 and not advance:
        raise ValueError("--count > 1 requires --advance so navigation is explicit")
    if not execute:
        print("[DRY RUN] native scan captures no screenshots and writes no manifest.")
        print(f"[DRY RUN] would collect {frames_per_pokemon} frame(s) per Pokémon.")
        if advance:
            print("[DRY RUN] would verify each intentional next-Pokémon swipe.")
        if open_appraise:
            print("[DRY RUN] would open the three-bar menu, OCR-tap Appraise, then capture frames.")
        return None

    ensure_runtime_dirs()
    serial = require_device(adb_serial)
    target = AdbTarget(serial)
    ocr = make_ocr()
    detector = OcrAnchoredAppraisalDetector()
    scans = []

    if open_appraise:
        _open_appraisal(target, ocr)
    else:
        _ensure_appraisal_visible(target, ocr)

    for scan_id in range(1, count + 1):
        frames = []
        first_image: np.ndarray | None = None
        for frame_index in range(1, frames_per_pokemon + 1):
            stamp = time.strftime("%Y%m%d_%H%M%S")
            screenshot = SCREENSHOTS_DIR / f"native_scan{scan_id}_frame{frame_index}_{stamp}.png"
            debug = CROPS_DIR / f"native_scan{scan_id}_frame{frame_index}_debug_{stamp}.png" if debug_native else None
            image = _capture(target, screenshot)
            first_image = first_image if first_image is not None else image
            frame = _frame_result(detector, image, run_ocr(ocr, image), frame_index, screenshot, debug)
            frames.append(frame)
            if frame.label_geometry_confidence == 0.0:
                geometry_reasons = ",".join(frame.geometry_failure_reasons) or "unknown"
                print(
                    "Native geometry was not fitted "
                    f"({geometry_reasons}); inspect this frame's debug artefacts."
                )
            print(
                f"Native scan {scan_id}, frame {frame_index}: IVs={frame.ivs}; "
                f"bar confidence={min(frame.attack_confidence, frame.defense_confidence, frame.hp_confidence):.3f}; "
                f"species={frame.species_normalized or 'missing'}"
            )
            if frame_index < frames_per_pokemon:
                time.sleep(frame_delay_ms / 1000.0)

        item = consensus(scan_id, frames, form=form)
        scans.append(item)
        print(
            f"Native scan {scan_id}: {item.status.value}; IVs={item.selected_ivs}; "
            f"confidence={item.consensus_confidence:.3f}; reasons="
            f"{','.join(reason.value for reason in item.failure_reasons) or 'none'}"
        )

        if scan_id < count:
            assert first_image is not None
            before = _fingerprint(first_image)
            width, height = target.wm_size()
            gesture = swipe_triangle_level(target, "right", width, height)
            print(
                "Advancing to next Pokémon: adb shell input swipe "
                f"{gesture.start.x} {gesture.start.y} {gesture.end.x} {gesture.end.y} {gesture.duration_ms}"
            )
            time.sleep(1.0)
            after_image = _capture(target, SCREENSHOTS_DIR / f"native_scan{scan_id}_after_swipe_{time.strftime('%Y%m%d_%H%M%S')}.png")
            if _fingerprint(after_image) == before:
                print("Navigation fingerprint unchanged; retrying the same next-Pokémon swipe once.")
                swipe_triangle_level(target, "right", width, height)
                time.sleep(1.0)
                after_image = _capture(target, SCREENSHOTS_DIR / f"native_scan{scan_id}_after_swipe_retry_{time.strftime('%Y%m%d_%H%M%S')}.png")
                if _fingerprint(after_image) == before:
                    raise RuntimeError(FailureReason.NAVIGATION_UNCONFIRMED.value)
            print("Navigation fingerprint changed; next Pokémon confirmed.")

    output = write_manifest(manifest_output, scans)
    print(f"Native manifest written: {output}")
    return output
