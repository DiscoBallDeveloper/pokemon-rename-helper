from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
import time
from typing import Any

import cv2
import numpy as np

from .adb import AdbTarget, require_device
from .legacy_scan import make_ocr, run_ocr
from .native_consensus import normalize_species
from .navigation import swipe_triangle_level
from .ocr_anchored_appraisal import OcrAnchoredAppraisalDetector
from .paths import CROPS_DIR, TEMPLATES_DIR
from .pvp_naming import encode_league_segment, suggested_pvp_name
from .pvp_rank import PokemonData
from .ui import DEFAULT_SCREEN


def prepare_native_rename_manifest(
    source_path: str | Path,
    output_path: str | Path,
    *,
    data_path: str | Path,
    pvp_min_percentile: float = 95.0,
    min_cap_ratio: float = 0.90,
    discard_tag: str = "delete2",
) -> Path:
    """Freeze conservative native rename decisions into a new manifest."""
    if not discard_tag or len(discard_tag) > 12:
        raise ValueError("discard_tag must contain 1..12 characters")
    source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    data = PokemonData(data_path)
    prepared: list[dict[str, Any]] = []
    for entry in source.get("scans", []):
        item = dict(entry)
        item["rename_allowed"] = False
        item["rename_to"] = None
        item["rename_decision"] = "REVIEW"
        item["rename_reason"] = "native scan is not VERIFIED"
        ivs = item.get("verified_ivs") or item.get("ivs")
        identity = item.get("identity", {})
        if (
            item.get("scan_status") != "VERIFIED"
            or not isinstance(ivs, list)
            or len(ivs) != 3
            or not identity.get("species")
            or not identity.get("form")
        ):
            prepared.append(item)
            continue
        attack, defense, hp = (int(value) for value in ivs)
        try:
            name, selected = suggested_pvp_name(
                data, identity["species"], attack, defense, hp,
                form=identity["form"], min_cap_ratio=min_cap_ratio,
            )
        except (KeyError, ValueError) as exc:
            item["rename_reason"] = f"rank data error: {exc}"
            prepared.append(item)
            continue
        qualifying = {
            league: candidate for league, candidate in selected.items()
            if candidate.entry.percentile >= pvp_min_percentile
        }
        if qualifying:
            # A non-qualifying league must not consume name characters.
            rename_to = "".join(
                encode_league_segment(qualifying[league])
                for league in ("GL", "UL") if league in qualifying
            )
            item.update({
                "rename_allowed": True,
                "rename_to": rename_to,
                "rename_decision": "KEEP_PVP",
                "rename_reason": f"local PvP percentile >= {pvp_min_percentile:.1f}",
            })
        elif attack >= 14 and defense >= 14 and hp >= 14:
            item.update({
                "rename_allowed": True,
                "rename_to": f"{attack}{defense}{hp}",
                "rename_decision": "KEEP_RAID",
                "rename_reason": "raid IV floor: all IVs >= 14",
            })
        else:
            item.update({
                "rename_allowed": True,
                "rename_to": discard_tag,
                "rename_decision": "DISCARD_TAG",
                "rename_reason": "verified, not PvP-qualified, and below raid IV floor",
            })
        item["rank_candidates"] = {
            league: {
                "species": candidate.species,
                "form": candidate.form,
                "evolution_stage": candidate.evolution_stage,
                "rank": candidate.entry.rank,
                "percentile": candidate.entry.percentile,
                "level": candidate.entry.level,
                "cp": candidate.entry.cp,
            }
            for league, candidate in selected.items()
        }
        prepared.append(item)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"version": 2, "source_manifest": str(source_path), "scans": prepared}, indent=2), encoding="utf-8")
    return target


def native_rename_entries(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        entry for entry in payload.get("scans", [])
        if entry.get("scan_status") == "VERIFIED"
        and entry.get("rename_allowed") is True
        and isinstance(entry.get("rename_to"), str)
        and entry["rename_to"]
    ]


def native_rename_execution_plan(path: str | Path) -> list[dict[str, Any]]:
    """Return the safe reverse-order device plan for a frozen manifest.

    The native scan ends on its final record, so the rename pass begins there
    and moves previous/left after each name.  A REVIEW entry makes positional
    mapping unsafe; the operator must rescan or make a manifest containing
    only verified records before any phone mutation is allowed.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    scans = payload.get("scans", [])
    if not scans:
        raise ValueError("Rename manifest contains no scans")
    unsafe = [entry.get("scan_id") for entry in scans if not (
        entry.get("scan_status") == "VERIFIED"
        and entry.get("rename_allowed") is True
        and isinstance(entry.get("rename_to"), str)
        and entry.get("rename_to")
        and entry.get("identity", {}).get("species")
        and entry.get("identity", {}).get("form")
        and isinstance(entry.get("verified_ivs") or entry.get("ivs"), list)
    )]
    if unsafe:
        raise ValueError(
            "Refusing device rename: every scanned position must be VERIFIED "
            f"and actionable; unsafe scan IDs: {unsafe}"
        )
    return list(reversed(scans))


def _capture_image(target: AdbTarget) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(target.screencap_png(), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Could not decode device screenshot while verifying rename target")
    return image


def _detail_fingerprint(image: np.ndarray) -> str:
    """Stable enough to confirm a normal-detail-screen left swipe changed Pokémon."""
    height, width = image.shape[:2]
    crop = image[:int(height * 0.48), :width]
    small = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (64, 64))
    return hashlib.sha256(small.tobytes()).hexdigest()


def _close_appraisal_once(target: AdbTarget, width: int, height: int) -> None:
    """Return from Appraise to the ordinary Pokémon detail page before rename."""
    center = DEFAULT_SCREEN.scale_point(DEFAULT_SCREEN.center, width, height)
    print(f"Closing Appraise once with middle-screen tap at {center.x},{center.y}")
    target.input_tap(center.x, center.y)
    time.sleep(0.8)


def _template_center(image: np.ndarray, template_name: str, threshold: float = 0.70) -> tuple[int, int, float] | None:
    template_path = TEMPLATES_DIR / template_name
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        raise RuntimeError(f"Required template is unavailable: {template_path}")
    if image.shape[0] < template.shape[0] or image.shape[1] < template.shape[1]:
        raise RuntimeError(f"Template {template_name} is larger than the device screenshot")
    source = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    needle = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    _, score, _, location = cv2.minMaxLoc(cv2.matchTemplate(source, needle, cv2.TM_CCOEFF_NORMED))
    if score < threshold:
        return None
    return location[0] + template.shape[1] // 2, location[1] + template.shape[0] // 2, float(score)


def _is_rename_ok_candidate(image: np.ndarray, candidate: tuple[int, int, float] | None) -> bool:
    """Reject generic template matches outside the rename confirmation modal."""
    if candidate is None:
        return False
    x, y, _score = candidate
    height, width = image.shape[:2]
    # The rename modal's button is centre-lower. This excludes the regular
    # detail page's green Power Up/New Attack controls.
    if not int(height * 0.45) <= y <= int(height * 0.68):
        return False
    patch = image[max(0, y - 70):min(height, y + 70), max(0, x - 180):min(width, x + 180)]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (35, 45, 80), (95, 255, 255))
    return float(green.mean() / 255.0) >= 0.20


def _tap_confirmed_rename_ok(target: AdbTarget) -> None:
    """Submit with the keyboard ✓ first, then click Pokémon GO's green OK."""
    image = _capture_image(target)
    # Gboard's black/white ✓ is an input action, not Pokémon GO's final
    # confirmation. It must be sent first so the field value is committed.
    bottom = cv2.cvtColor(image[int(image.shape[0] * 0.70):, :], cv2.COLOR_BGR2GRAY)
    if float(bottom.mean()) < 95.0:
        print("Submitting nickname through the keyboard Enter/✓ action")
        target.input_keyevent("KEYCODE_ENTER")
        time.sleep(0.5)
        image = _capture_image(target)
    candidate = _template_center(image, "rename_ok_template.png")
    if not _is_rename_ok_candidate(image, candidate):
        debug = CROPS_DIR / f"native_rename_ok_missing_{time.strftime('%Y%m%d_%H%M%S')}.png"
        cv2.imwrite(str(debug), image)
        raise RuntimeError(
            "Rename OK button was not found after keyboard handling; "
            f"no swipe or further rename was sent. Inspect {debug}."
        )
    x, y, score = candidate
    print(f"Confirming rename via green OK template at {x},{y}, score={score:.3f}")
    target.input_tap(x, y)
    # A swipe after an uncommitted dialog would silently desynchronise the
    # frozen reverse-order plan. Require the dialog's OK surface to disappear.
    for _ in range(2):
        time.sleep(0.5)
        after = _capture_image(target)
        if not _is_rename_ok_candidate(after, _template_center(after, "rename_ok_template.png")):
            return
    debug = CROPS_DIR / f"native_rename_ok_still_visible_{time.strftime('%Y%m%d_%H%M%S')}.png"
    cv2.imwrite(str(debug), _capture_image(target))
    raise RuntimeError(
        f"Rename dialog remained open after OK tap; no swipe was sent. Inspect {debug}."
    )


def _tap_confirmed_rename_pencil(target: AdbTarget) -> None:
    image = _capture_image(target)
    candidate = _template_center(image, "rename_pencil_template.png")
    if candidate is None:
        debug = CROPS_DIR / f"native_rename_pencil_missing_{time.strftime('%Y%m%d_%H%M%S')}.png"
        cv2.imwrite(str(debug), image)
        raise RuntimeError(
            f"Rename pencil was not found; no text or swipe was sent. Inspect {debug}."
        )
    x, y, score = candidate
    print(f"Opening rename field via pencil template at {x},{y}, score={score:.3f}")
    target.input_tap(x, y)


def _normalise_display_name(value: str) -> str:
    """Normalise harmless OCR whitespace/case differences, but not characters."""
    return re.sub(r"\s+", "", value).casefold()


def _verify_displayed_name(target: AdbTarget, ocr: object, expected: str, scan_id: object) -> None:
    """Require the committed detail-page nickname before moving to the prior Pokémon."""
    image = _capture_image(target)
    wanted = _normalise_display_name(expected)
    rows = run_ocr(ocr, image)
    observed = [str(row.get("text", "")).strip() for row in rows]
    if any(_normalise_display_name(text) == wanted for text in observed if text):
        print(f"Rename scan {scan_id}: confirmed displayed name {expected!r}")
        return
    debug = CROPS_DIR / f"native_rename_name_unconfirmed_scan{scan_id}_{time.strftime('%Y%m%d_%H%M%S')}.png"
    cv2.imwrite(str(debug), image)
    raise RuntimeError(
        f"Rename scan {scan_id} did not OCR-confirm {expected!r}; "
        f"no swipe was sent. Inspect {debug}. OCR saw: {observed!r}"
    )


def _verify_current_native_target(
    target: AdbTarget,
    detector: OcrAnchoredAppraisalDetector,
    ocr: object,
    item: dict[str, Any],
) -> None:
    """Fail closed unless the visible appraisal matches the frozen record."""
    image = _capture_image(target)
    result = detector.detect(image, run_ocr(ocr, image))
    expected_ivs = tuple(int(value) for value in (item.get("verified_ivs") or item["ivs"]))
    actual_ivs = (result.attack, result.defense, result.hp)
    expected_species = normalize_species(item["identity"]["species"])
    actual_species = normalize_species(result.species_from_sentence)
    if actual_ivs != expected_ivs or actual_species != expected_species:
        raise RuntimeError(
            "Visible appraisal does not match frozen rename record "
            f"scan {item.get('scan_id')}: expected {expected_species} {expected_ivs}; "
            f"got {actual_species} {actual_ivs}. No rename was sent."
        )


def apply_native_rename_manifest(
    path: str | Path,
    *,
    adb_serial: str | None,
    execute: bool,
    wait_after_pencil: float = 1.0,
    wait_after_confirm: float = 1.0,
    start_scan: int | None = None,
    already_on_detail: bool = False,
) -> list[dict[str, Any]]:
    """Apply a frozen manifest from its last scanned appraisal position.

    A real run validates the initial, final-scan appraisal before closing it
    with one centre tap. It then follows the frozen reverse-order manifest on
    the normal detail page and confirms every left swipe changed the Pokémon.
    It never uses OCR proposals, Poke Genie fields, or REVIEW records.
    """
    full_plan = native_rename_execution_plan(path)
    plan = full_plan
    if start_scan is not None:
        start_index = next((index for index, item in enumerate(full_plan) if item.get("scan_id") == start_scan), None)
        if start_index is None:
            raise ValueError(f"scan {start_scan} is not present in the frozen rename manifest")
        plan = full_plan[start_index:]
    if wait_after_pencil < 0 or wait_after_confirm < 0:
        raise ValueError("rename waits must not be negative")
    if not execute:
        if already_on_detail:
            print(f"[DRY RUN] Resume on scan {plan[0].get('scan_id')} normal detail page.")
        else:
            print("[DRY RUN] Start on the LAST Pokémon from the native scan, with Appraise open.")
        for index, item in enumerate(plan):
            if index == 0 and not already_on_detail:
                print("[DRY RUN] verify the final scan's native identity/IVs, then middle-tap once to close Appraise.")
            print(
                f"[DRY RUN] rename scan {item.get('scan_id')} to {item['rename_to']!r} "
                f"({item.get('rename_decision', 'prepared')})"
            )
            if index < len(plan) - 1:
                print("[DRY RUN] swipe previous/left (finger left-to-right) on the normal detail screen.")
        return plan

    serial = require_device(adb_serial)
    target = AdbTarget(serial)
    width, height = target.wm_size()
    text_field = DEFAULT_SCREEN.scale_point(DEFAULT_SCREEN.rename_text_field, width, height)
    detector = OcrAnchoredAppraisalDetector()
    ocr = make_ocr()

    # Appraise is required for native IV validation only.  It must not remain
    # open while driving the pencil/name controls or the reverse carousel.
    if not already_on_detail:
        _verify_current_native_target(target, detector, ocr, plan[0])
        _close_appraisal_once(target, width, height)

    for index, item in enumerate(plan):
        print(f"Rename scan {item.get('scan_id')}: {item['rename_to']} ({item['rename_decision']})")
        _tap_confirmed_rename_pencil(target)
        time.sleep(wait_after_pencil)
        target.input_tap(text_field.x, text_field.y)
        # Delete forward from HOME.  The previous END/backspace sequence was
        # device-dependent and could leave a nickname suffix behind.
        target.input_keyevent("KEYCODE_MOVE_HOME")
        for _ in range(24):
            target.input_keyevent("KEYCODE_FORWARD_DEL")
        target.input_text(item["rename_to"])
        _tap_confirmed_rename_ok(target)
        time.sleep(wait_after_confirm)
        _verify_displayed_name(target, ocr, item["rename_to"], item.get("scan_id"))
        if index < len(plan) - 1:
            before = _detail_fingerprint(_capture_image(target))
            swipe_triangle_level(target, "left", width, height)
            time.sleep(wait_after_confirm)
            after = _detail_fingerprint(_capture_image(target))
            if after == before:
                print("Detail-screen left swipe did not change the Pokémon; retrying once.")
                swipe_triangle_level(target, "left", width, height)
                time.sleep(wait_after_confirm)
                after = _detail_fingerprint(_capture_image(target))
                if after == before:
                    raise RuntimeError(
                        "Reverse rename navigation was not confirmed; no further rename was sent."
                    )
    return plan
