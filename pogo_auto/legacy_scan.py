#!/usr/bin/env python3

from __future__ import annotations

import os
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_enable_mkldnn"] = "0"

import argparse
import csv
import datetime
import json
import pathlib
import re
import subprocess
import time
from typing import Any, Dict, List, Tuple, Optional

import cv2

from .ocr_anchored_appraisal import OcrAnchoredAppraisalDetector
from .pvp_rank import PokemonData, all_league_ranks
from .ocr import find_text_center


# =============================================================================
# CONFIG
# =============================================================================

BASE_DIR = pathlib.Path("captures")
SCREEN_DIR = BASE_DIR / "screenshots"
CROP_DIR = BASE_DIR / "crops"
LOG_DIR = BASE_DIR / "logs"

def _adb_base_cmd_from_env():
    serial = os.environ.get("POGO_ADB_SERIAL") or os.environ.get("ADB_SERIAL")
    if serial:
        return ["adb", "-s", serial]
    return ["adb"]

TEMPLATE_DIR = BASE_DIR / "templates"

for d in [SCREEN_DIR, CROP_DIR, LOG_DIR, TEMPLATE_DIR]:
    d.mkdir(parents=True, exist_ok=True)



try:
    from .navigation import fixed_triangle_point, triangle_level_swipe
except ImportError:  # Allows direct script execution during debugging.
    fixed_triangle_point = None
    triangle_level_swipe = None

COORDS_1008x2244 = {
    "three_bar_menu": (866, 2105),
    "appraise": (680, 1743),
    "middle_left_of_triangle": (504, 1122),
    "left_triangle": (26, 1821),
    "right_triangle": (982, 1821),
}

# Fallback Poke Genie table crop on left side.
POKE_GENIE_TABLE_REGION = (0, 680, 380, 540)  # x, y, w, h

TEMPLATES = {
    "three_bar_menu": TEMPLATE_DIR / "three_bar_menu_template.png",
    "appraise": TEMPLATE_DIR / "appraise_template.png",
    "right_triangle": TEMPLATE_DIR / "right_triangle_template.png",
    "pokegenie_overlay": TEMPLATE_DIR / "pokegenie_overlay_template.png",
}

TEMPLATE_THRESHOLDS = {
    "three_bar_menu": 0.65,
    "appraise": 0.65,
    "right_triangle": 0.65,
    "pokegenie_overlay": 0.60,
}

FALLBACK_COORDS = {
    "three_bar_menu": COORDS_1008x2244["three_bar_menu"],
    "appraise": COORDS_1008x2244["appraise"],
    "right_triangle": COORDS_1008x2244["right_triangle"],
}

# Full-screen matching is more portable across resolutions.
SEARCH_REGIONS: Dict[str, Optional[Tuple[int, int, int, int]]] = {
    "three_bar_menu": None,
    "appraise": None,
    "right_triangle": None,
    "pokegenie_overlay": None,
}


# =============================================================================
# ADB HELPERS
# =============================================================================

def adb(*args: Any, check: bool = True) -> subprocess.CompletedProcess:
    cmd = _adb_base_cmd_from_env() + [str(a) for a in args]
    print("ADB:", " ".join(cmd))
    return subprocess.run(
        cmd,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def adb_tap(x: int, y: int, execute: bool = False) -> None:
    if not execute:
        print(f"[DRY RUN] tap {x},{y}")
        return

    adb("shell", "input", "tap", x, y)


def adb_swipe(
    start_x: int, start_y: int, end_x: int, end_y: int,
    duration_ms: int = 280, execute: bool = False,
) -> None:
    if duration_ms <= 0:
        raise ValueError("duration_ms must be positive")
    if not execute:
        print(f"[DRY RUN] adb shell input swipe {start_x} {start_y} {end_x} {end_y} {duration_ms}")
        return
    adb("shell", "input", "swipe", start_x, start_y, end_x, end_y, duration_ms)


def adb_screenshot(path: pathlib.Path) -> None:
    with path.open("wb") as f:
        result = subprocess.run(
            [*_adb_base_cmd_from_env(), "exec-out", "screencap", "-p"],
            stdout=f,
            stderr=subprocess.PIPE,
        )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))


def save_screen(prefix: str, iteration: int, attempt: int = 0) -> pathlib.Path:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCREEN_DIR / f"{prefix}_scan{iteration}_attempt{attempt}_{ts}.png"
    adb_screenshot(path)
    print(f"Screenshot saved: {path}")
    return path


def check_adb_device() -> None:
    result = subprocess.run(
        ["adb", "devices"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    devices = []

    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])

    if not devices:
        raise RuntimeError("No ADB device found. Check USB debugging and `adb devices`.")

    print("ADB device:", devices[0])


# =============================================================================
# TEMPLATE MATCHING
# =============================================================================

def find_template_center(
    screenshot_path: pathlib.Path,
    template_path: pathlib.Path,
    threshold: float,
    search_region: Optional[Tuple[int, int, int, int]] = None,
) -> Optional[Tuple[int, int, float, Tuple[int, int, int, int]]]:
    screenshot = cv2.imread(str(screenshot_path))
    template = cv2.imread(str(template_path))

    if screenshot is None:
        print(f"Could not read screenshot: {screenshot_path}")
        return None

    if template is None:
        print(f"Could not read template: {template_path}")
        return None

    offset_x = 0
    offset_y = 0

    if search_region is not None:
        x, y, w, h = search_region
        screenshot = screenshot[y:y + h, x:x + w]
        offset_x = x
        offset_y = y

    screenshot_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

    result = cv2.matchTemplate(
        screenshot_gray,
        template_gray,
        cv2.TM_CCOEFF_NORMED,
    )

    _, max_score, _, max_loc = cv2.minMaxLoc(result)

    th, tw = template_gray.shape[:2]
    match_x = offset_x + max_loc[0]
    match_y = offset_y + max_loc[1]
    center_x = match_x + tw // 2
    center_y = match_y + th // 2

    print(
        f"Template match {template_path.name}: score={max_score:.3f}, "
        f"center=({center_x},{center_y}), threshold={threshold}"
    )

    if max_score < threshold:
        return None

    return center_x, center_y, float(max_score), (match_x, match_y, tw, th)


def save_template_debug_overlay(
    screenshot_path: pathlib.Path,
    iteration: int,
    attempt: int,
    name: str,
    rect: Tuple[int, int, int, int],
    score: float,
) -> Optional[pathlib.Path]:
    img = cv2.imread(str(screenshot_path))
    if img is None:
        return None

    x, y, w, h = rect
    cv2.rectangle(img, (x, y), (x + w, y + h), (0, 255, 0), 3)
    cv2.putText(
        img,
        f"{name} {score:.3f}",
        (x, max(30, y - 12)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = CROP_DIR / f"scan{iteration}_attempt{attempt}_{name}_template_debug_{ts}.png"
    cv2.imwrite(str(path), img)
    print(f"{name} template debug saved:", path)
    return path


def tap_ui_template(
    name: str,
    execute: bool,
    iteration: int,
    attempt: int = 0,
    fallback: bool = True,
    disable_templates: bool = False,
) -> Optional[Tuple[int, int]]:
    fallback_xy = FALLBACK_COORDS.get(name)

    if name == "appraise" and not disable_templates:
        screenshot_path = save_screen("before_ocr_appraise", iteration, attempt)
        point = find_text_center(screenshot_path, "Appraise")
        if point is not None:
            print(f"appraise: OCR matched menu text at {point[0]},{point[1]}")
            adb_tap(*point, execute=execute)
            return point
        print("appraise: OCR did not find menu text; using configured fallback.")

    if disable_templates:
        print(f"{name}: template matching disabled.")
        if fallback_xy is None:
            raise RuntimeError(f"No fallback coordinate for {name}")
        adb_tap(*fallback_xy, execute=execute)
        return fallback_xy

    template_path = TEMPLATES.get(name)
    if template_path is None or not template_path.exists():
        print(f"{name}: template missing: {template_path}")
        if fallback and fallback_xy is not None:
            print(f"{name}: falling back to fixed coordinate {fallback_xy}")
            adb_tap(*fallback_xy, execute=execute)
            return fallback_xy
        raise FileNotFoundError(f"Template not found for {name}: {template_path}")

    screenshot_path = save_screen(f"before_template_{name}", iteration, attempt)
    match = find_template_center(
        screenshot_path=screenshot_path,
        template_path=template_path,
        threshold=TEMPLATE_THRESHOLDS.get(name, 0.65),
        search_region=SEARCH_REGIONS.get(name),
    )

    if match is None:
        print(f"{name}: template match failed.")
        if fallback and fallback_xy is not None:
            print(f"{name}: falling back to fixed coordinate {fallback_xy}")
            adb_tap(*fallback_xy, execute=execute)
            return fallback_xy
        raise RuntimeError(f"Template match failed for {name}")

    x, y, score, rect = match
    save_template_debug_overlay(
        screenshot_path=screenshot_path,
        iteration=iteration,
        attempt=attempt,
        name=name,
        rect=rect,
        score=score,
    )

    print(f"{name}: tapping matched center {x},{y}, score={score:.3f}")
    adb_tap(x, y, execute=execute)
    return (x, y)


def template_visible_once(
    name: str,
    iteration: int,
    attempt: int = 0,
    threshold_override: Optional[float] = None,
) -> bool:
    """
    Checks that a template is currently visible. This is a guard only: it never taps.
    """
    template_path = TEMPLATES.get(name)
    if template_path is None:
        raise RuntimeError(f"No template configured for guard: {name}")

    if not template_path.exists():
        raise FileNotFoundError(f"Guard template missing for {name}: {template_path}")

    screenshot_path = save_screen(f"guard_check_{name}", iteration, attempt)
    threshold = threshold_override if threshold_override is not None else TEMPLATE_THRESHOLDS.get(name, 0.65)

    match = find_template_center(
        screenshot_path=screenshot_path,
        template_path=template_path,
        threshold=threshold,
        search_region=SEARCH_REGIONS.get(name),
    )

    if match is None:
        print(f"STARTUP GUARD: {name} not visible.")
        return False

    x, y, score, rect = match
    save_template_debug_overlay(
        screenshot_path=screenshot_path,
        iteration=iteration,
        attempt=attempt,
        name=f"guard_{name}",
        rect=rect,
        score=score,
    )
    print(f"STARTUP GUARD: {name} visible at {x},{y}, score={score:.3f}")
    return True


def require_templates_visible(
    names: List[str],
    iteration: int,
    attempt: int,
    retries: int,
    wait_seconds: float,
    disable_templates: bool,
) -> None:
    """
    Waits until all requested templates are visible.

    retries < 0 means wait forever, taking a fresh screenshot on every attempt.
    retries >= 0 means try once plus that many retries, then raise.
    """
    if disable_templates:
        print("STARTUP GUARD: templates disabled; skipping template visibility guard.")
        return

    guard_attempt = 1
    missing = list(names)

    while True:
        limit_text = "forever" if retries < 0 else str(retries + 1)
        print(f"STARTUP GUARD attempt {guard_attempt}/{limit_text}: need {missing}")

        still_missing = []
        for name in missing:
            if not template_visible_once(name=name, iteration=iteration, attempt=attempt):
                still_missing.append(name)

        if not still_missing:
            print("STARTUP GUARD: all required templates visible. Continuing.")
            return

        missing = still_missing

        if retries >= 0 and guard_attempt >= retries + 1:
            raise RuntimeError(
                "Startup guard failed. Required template(s) not visible: "
                + ", ".join(missing)
                + ". Put the game on the expected screen or use --disable-startup-guards."
            )

        print(f"STARTUP GUARD: missing {missing}; waiting {wait_seconds:.1f}s before fresh screenshot...")
        time.sleep(wait_seconds)
        guard_attempt += 1


# =============================================================================
# IMAGE HELPERS
# =============================================================================

def crop_region(img, region: Tuple[int, int, int, int]):
    x, y, w, h = region
    return img[y:y + h, x:x + w]


def preprocess_for_ocr(img):
    return cv2.resize(img, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)


def find_pokegenie_ocr_roi(
    screenshot_path: pathlib.Path,
    iteration: int,
    attempt: int,
    fallback_roi: Tuple[int, int, int, int],
    disable_templates: bool,
    no_template_fallback: bool,
    roi_width: int,
    roi_height: int,
    offset_x: int,
    offset_y: int,
) -> Tuple[int, int, int, int, Optional[Tuple[int, int, int, int, float]]]:
    """
    Uses pokegenie_overlay_template.png to locate the Poke Genie table.

    The default assumption is that the overlay template was cropped from the
    top-left stable part of the Poke Genie table. If your template was cropped
    with a different anchor, use --ocr-roi-offset-x/y.
    """
    if disable_templates:
        print("Poke Genie ROI template disabled; using fallback ROI:", fallback_roi)
        return (*fallback_roi, None)

    template_path = TEMPLATES["pokegenie_overlay"]
    if not template_path.exists():
        print("Poke Genie overlay template missing:", template_path)
        if no_template_fallback:
            raise FileNotFoundError(f"Missing Poke Genie overlay template: {template_path}")
        print("Using fallback ROI:", fallback_roi)
        return (*fallback_roi, None)

    match = find_template_center(
        screenshot_path=screenshot_path,
        template_path=template_path,
        threshold=TEMPLATE_THRESHOLDS["pokegenie_overlay"],
        search_region=SEARCH_REGIONS.get("pokegenie_overlay"),
    )

    if match is None:
        if no_template_fallback:
            raise RuntimeError("Poke Genie overlay template match failed")
        print("Poke Genie overlay match failed; using fallback ROI:", fallback_roi)
        return (*fallback_roi, None)

    _cx, _cy, score, rect = match
    match_x, match_y, template_w, template_h = rect
    roi_x = max(0, match_x + offset_x)
    roi_y = max(0, match_y + offset_y)
    roi = (roi_x, roi_y, roi_width, roi_height)

    print(
        f"Poke Genie OCR ROI from template: x={roi_x}, y={roi_y}, "
        f"w={roi_width}, h={roi_height}, score={score:.3f}"
    )

    return (*roi, (match_x, match_y, template_w, template_h, score))


def save_debug_overlay(
    img,
    path: pathlib.Path,
    iteration: int,
    attempt: int,
    ocr_region: Tuple[int, int, int, int],
    overlay_match: Optional[Tuple[int, int, int, int, float]] = None,
) -> None:
    debug = img.copy()

    x, y, w, h = ocr_region
    cv2.rectangle(debug, (x, y), (x + w, y + h), (0, 255, 255), 4)
    cv2.putText(
        debug,
        "POKE GENIE OCR",
        (x + 10, max(40, y - 15)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        (0, 255, 255),
        3,
        cv2.LINE_AA,
    )

    if overlay_match is not None:
        mx, my, mw, mh, score = overlay_match
        cv2.rectangle(debug, (mx, my), (mx + mw, my + mh), (0, 255, 0), 3)
        cv2.putText(
            debug,
            f"overlay {score:.3f}",
            (mx, max(40, my - 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

    # Fallback tap points for reference only.
    for label, (tx, ty) in COORDS_1008x2244.items():
        cv2.circle(debug, (tx, ty), 22, (0, 0, 255), -1)
        cv2.circle(debug, (tx, ty), 30, (255, 255, 255), 3)
        cv2.putText(
            debug,
            label,
            (max(10, tx - 240), max(50, ty - 38)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )

    cv2.putText(
        debug,
        f"scan {iteration}, attempt {attempt}",
        (30, 60),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (255, 255, 255),
        4,
        cv2.LINE_AA,
    )

    cv2.imwrite(str(path), debug)


# =============================================================================
# OCR
# =============================================================================

def make_ocr() -> PaddleOCR:
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise RuntimeError(
            "PaddleOCR is required to scan. Install project dependencies with "
            "`python -m pip install -e .`."
        ) from exc
    return PaddleOCR(
        lang="en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=True,
        enable_mkldnn=False,
    )


def run_ocr(ocr: PaddleOCR, img) -> List[Dict[str, Any]]:
    if not hasattr(ocr, "predict"):
        rows: List[Dict[str, Any]] = []

        def visit(node: Any) -> None:
            if (
                isinstance(node, (list, tuple)) and len(node) == 2
                and isinstance(node[0], (list, tuple)) and len(node[0]) >= 4
                and isinstance(node[1], (list, tuple)) and len(node[1]) >= 2
                and isinstance(node[1][0], str)
            ):
                rows.append({
                    "text": str(node[1][0]),
                    "score": float(node[1][1]),
                    "box": [list(point) for point in node[0]],
                })
                return
            if isinstance(node, (list, tuple)):
                for child in node:
                    visit(child)

        visit(ocr.ocr(img, cls=True))
        return rows

    result = ocr.predict(img)
    rows = []

    if not result:
        return rows

    for page in result:
        try:
            data = dict(page)
        except Exception:
            data = page

        if not hasattr(data, "get"):
            continue

        texts = data.get("rec_texts", []) or []
        scores = data.get("rec_scores", []) or []
        boxes = (
            data.get("rec_polys")
            or data.get("dt_polys")
            or data.get("det_polys")
            or [None] * len(texts)
        )

        for i, text in enumerate(texts):
            score = scores[i] if i < len(scores) else 0.0
            box = boxes[i] if i < len(boxes) else None

            if hasattr(box, "tolist"):
                box = box.tolist()

            rows.append({
                "text": str(text),
                "score": float(score),
                "box": box,
            })

    return rows


# =============================================================================
# PARSING
# =============================================================================

def parse_poke_genie_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    texts = [r["text"].strip() for r in rows if r.get("text", "").strip()]
    joined = " | ".join(texts)

    parsed = {
        "raw_text": joined,
        "species": None,
        "iv_percent": None,
        "attack": None,
        "defense": None,
        "hp": None,
        "cp": None,
        "level": None,
        "pvp_percentages": [],
        "pvp_rank_1_percent": None,
        "pvp_rank_2_percent": None,
        "max_pvp_percent": None,
        "keep_reason_type": None,
        "rename_to": None,
        "decision": None,
        "reason": None,
    }

    if texts:
        first = re.sub(r"[^A-Za-z♀♂.' -]", "", texts[0]).strip()
        if first and first.lower() not in {"iv", "cp", "lvl", "level"}:
            parsed["species"] = first

    # Examples:
    # IV 89% (15-10-15)
    # IV89% (15-10-15)
    m = re.search(
        r"IV\s*(\d{1,3})\s*%\s*\(?\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s*\)?",
        joined,
        flags=re.IGNORECASE,
    )
    if m:
        parsed["iv_percent"] = int(m.group(1))
        parsed["attack"] = int(m.group(2))
        parsed["defense"] = int(m.group(3))
        parsed["hp"] = int(m.group(4))

    # Example:
    # CP 610, lvl 20.0
    m = re.search(
        r"CP\s*(\d+)\s*,?\s*(?:lvl|Ivl|lvI|lvi|level)\s*(\d+(?:\.\d+)?)",
        joined,
        flags=re.IGNORECASE,
    )
    if m:
        parsed["cp"] = int(m.group(1))
        parsed["level"] = float(m.group(2))

    pvp_percentages: List[float] = []

    for text in texts:
        percent_match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
        if not percent_match:
            continue

        val = float(percent_match.group(1))
        if not (0.0 <= val <= 100.0):
            continue

        # Skip the IV percent line, because PvP ranking rows are separate lines.
        if re.search(r"\bIV\b", text, flags=re.IGNORECASE):
            continue

        pvp_percentages.append(val)

        # Poke Genie often OCRs first/second PvP rows as ① and ②.
        # Keep a few common OCR alternatives as fallbacks.
        if "①" in text or "⓵" in text or re.search(r"(?:^|\s)[(（]?[1lI][)）]?\s*$", text):
            parsed["pvp_rank_1_percent"] = val

        if "②" in text or "⓶" in text or re.search(r"(?:^|\s)[(（]?[2Zz][)）]?\s*$", text):
            parsed["pvp_rank_2_percent"] = val

    # Fallback: if circled-number OCR is missed, assume the PvP rows are ordered.
    if parsed["pvp_rank_1_percent"] is None and len(pvp_percentages) >= 1:
        parsed["pvp_rank_1_percent"] = pvp_percentages[0]

    if parsed["pvp_rank_2_percent"] is None and len(pvp_percentages) >= 2:
        parsed["pvp_rank_2_percent"] = pvp_percentages[1]

    parsed["pvp_percentages"] = pvp_percentages
    parsed["max_pvp_percent"] = max(pvp_percentages) if pvp_percentages else None

    return parsed



def format_rename_percent(value: float) -> str:
    """Format a PvP percentage for Pokémon name text, e.g. 96.8 or 100."""
    if value is None:
        return ""
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}"




def compact_pvp_percent(value: float) -> str:
    """Convert 99.4 -> 994, 100.0 -> 100."""
    s = f"{value:.1f}".replace(".", "")
    if s.endswith("0") and len(s) > 2:
        # 95.0 -> 95, 100.0 -> 100
        s = s[:-1]
    return s



CIRCLED_EVOLUTION_MARKERS = {
    "⓪": "0",
    "①": "1",
    "②": "2",
    "③": "3",
    "④": "4",
    "⑤": "5",
    "0": "0",
    "1": "1",
    "2": "2",
    "3": "3",
    "4": "4",
    "5": "5",
}


def pvp_rows_from_raw_text(raw_text: str) -> List[Tuple[float, Optional[str]]]:
    """
    Extract PvP rows in visible order as (percentage, evolution/form marker).

    The marker is the circled number after the percentage when OCR sees it:
      ⓪ / 0 = base form
      ① / 1 = first evolution/form row
      ② / 2 = second evolution/form row

    Examples:
      "13.2% ①" -> (13.2, "1")
      "95.4%①" -> (95.4, "1")
    """
    if not raw_text:
        return []

    parts = [p.strip() for p in re.split(r"\s*\|\s*|\n+", raw_text) if p.strip()]
    rows: List[Tuple[float, Optional[str]]] = []

    for part in parts:
        if re.search(r"\bIV\b", part, re.IGNORECASE):
            continue

        # Ignore IV ranges like 40-62%.
        if re.search(r"\d+\s*-\s*\d+\s*%", part):
            continue

        m = re.search(r"(\d{1,3}(?:\.\d)?)\s*%\s*([⓪①②③④⑤0-5])?", part)
        if not m:
            continue

        try:
            val = float(m.group(1))
        except ValueError:
            continue

        if not (0.0 <= val <= 100.0):
            continue

        marker = CIRCLED_EVOLUTION_MARKERS.get(m.group(2) or "")
        rows.append((val, marker))

    return rows


def build_pvp_rename(
    rank1: Optional[float],
    rank2: Optional[float],
    threshold: float,
    rank1_evo: Optional[str] = None,
    rank2_evo: Optional[str] = None,
) -> str:
    """
    Build a short Pokémon GO nickname containing only league values that pass.

    Format:
      G6371 = Great League 63.7, evolution/form marker 1
      U9541 = Ultra League 95.4, evolution/form marker 1
      G9720U9542 = both leagues passed with markers 0 and 2

    This avoids parentheses so two-league names fit within Pokémon GO's
    nickname length limit.
    """
    parts = []

    if rank1 is not None and rank1 >= threshold:
        parts.append(f"G{compact_pvp_percent(rank1)}{rank1_evo or ''}")

    if rank2 is not None and rank2 >= threshold:
        parts.append(f"U{compact_pvp_percent(rank2)}{rank2_evo or ''}")

    return "".join(parts)




def ordered_pvp_percentages_from_raw_text(raw_text: str) -> List[float]:
    """
    Extract PvP percentages in visible row order from Poke Genie text.

    The first PvP percentage after the IV line is the blue/Great row.
    The second PvP percentage is the yellow-orange/Ultra row.

    Example:
      IV 91% (12-14-15) | 63.7% ① | 99.4% ① | CP...
      -> [63.7, 99.4]

    This avoids using circled rank numbers to infer league. Both rows can show
    ①, so rank symbols cannot decide GR vs UL.
    """
    if not raw_text:
        return []

    # Split rough OCR rows while preserving visible order.
    parts = [p.strip() for p in re.split(r"\s*\|\s*|\n+", raw_text) if p.strip()]
    values: List[float] = []

    for part in parts:
        # Skip IV percentage line explicitly.
        if re.search(r"\bIV\b", part, re.IGNORECASE):
            continue

        # Only treat percent rows with rank/triangle context as PvP rows when possible.
        # But OCR often drops triangle symbols, so accept all non-IV percent rows.
        for match in re.finditer(r"(\d{1,3}(?:\.\d)?)\s*%", part):
            try:
                val = float(match.group(1))
            except ValueError:
                continue
            # Avoid IV range lines like "40-62%" and keep sane PvP score values.
            if 0.0 <= val <= 100.0:
                values.append(val)

    return values


def repair_ordered_pvp_fields(parsed: Dict[str, Any]) -> None:
    """
    Force pvp_rank_1_percent and pvp_rank_2_percent from visible row order.

    This fixes cases where both rows have circled rank ① and the old parser
    assigned the same high value to both leagues.
    """
    raw_text = str(parsed.get("raw_text", "") or "")
    values = ordered_pvp_percentages_from_raw_text(raw_text)

    rows = pvp_rows_from_raw_text(raw_text)
    values = [value for value, _marker in rows]

    if values:
        parsed["pvp_percentages"] = values
        parsed["pvp_rank_1_percent"] = values[0] if len(values) >= 1 else None
        parsed["pvp_rank_2_percent"] = values[1] if len(values) >= 2 else None
        parsed["pvp_rank_1_evo"] = rows[0][1] if len(rows) >= 1 else None
        parsed["pvp_rank_2_evo"] = rows[1][1] if len(rows) >= 2 else None
        parsed["max_pvp_percent"] = max(values) if values else None


def classify(parsed: Dict[str, Any], threshold: float, iv_floor: int = 14) -> None:
    repair_ordered_pvp_fields(parsed)
    raw = (parsed.get("raw_text") or "").lower()

    parsed["keep_reason_type"] = None
    parsed["rename_to"] = None

    if "unable to" in raw or "detect name" in raw or "tap to edit" in raw:
        parsed["decision"] = "RETRY_OR_REVIEW"
        parsed["reason"] = "Poke Genie unable to detect name"
        parsed["rename_to"] = ""
        return

    attack = parsed.get("attack")
    defense = parsed.get("defense")
    hp = parsed.get("hp")

    # Highest-priority keep rule: IV floor, e.g. 14-14-14 or better.
    # This produces a row-0 rename marker.
    if attack is not None and defense is not None and hp is not None:
        if attack >= iv_floor and defense >= iv_floor and hp >= iv_floor:
            parsed["decision"] = "KEEP"
            parsed["keep_reason_type"] = "iv_floor"
            parsed["rename_to"] = f"{attack}{defense}{hp}"
            parsed["reason"] = (
                f"IV stats {attack}-{defense}-{hp} >= "
                f"{iv_floor}-{iv_floor}-{iv_floor}; rename {parsed['rename_to']}"
            )
            return

    rank1 = parsed.get("pvp_rank_1_percent")
    rank2 = parsed.get("pvp_rank_2_percent")

    # PvP row 1 is the blue inverted triangle row, treated as Great League.
    # PvP row 2 is the yellow/orange inverted triangle row, treated as Ultra League.
    #
    # If either league is good enough, keep the Pokémon and combine both parsed
    # league values into the nickname, e.g. GR97.2UL95.9.
    rank1_keep = rank1 is not None and rank1 >= threshold
    rank2_keep = rank2 is not None and rank2 >= threshold

    if rank1_keep or rank2_keep:
        parsed["decision"] = "KEEP"

        if rank1_keep and rank2_keep:
            parsed["keep_reason_type"] = "great_and_ultra_league"
        elif rank1_keep:
            parsed["keep_reason_type"] = "great_league"
        else:
            parsed["keep_reason_type"] = "ultra_league"

        parsed["rename_to"] = build_pvp_rename(rank1, rank2, threshold, parsed.get("pvp_rank_1_evo"), parsed.get("pvp_rank_2_evo"))

        reasons = []
        if rank1 is not None:
            reasons.append(f"GR={rank1:.1f}%")
        if rank2 is not None:
            reasons.append(f"UL={rank2:.1f}%")

        parsed["reason"] = (
            f"PvP keep: {', '.join(reasons)}; at least one >= {threshold:.1f}%; "
            f"rename {parsed['rename_to']}"
        )
        return

    if rank1 is None and rank2 is None:
        parsed["decision"] = "REVIEW"
        parsed["keep_reason_type"] = "review"
        parsed["rename_to"] = ""
        parsed["reason"] = "no PvP rank 1/2 percentage parsed"
        return

    iv_text = (
        f"{attack}-{defense}-{hp}"
        if attack is not None and defense is not None and hp is not None
        else "unknown"
    )

    parsed["decision"] = "RENAME_CANDIDATE"
    parsed["keep_reason_type"] = "delete"
    parsed["rename_to"] = "delete1"
    parsed["reason"] = (
        f"IV stats {iv_text} not >= {iv_floor}-{iv_floor}-{iv_floor}; "
        f"PvP rank 1={rank1}, rank 2={rank2}, both < {threshold:.1f}%; rename delete1"
    )


def is_readable(result: Dict[str, Any]) -> bool:
    raw = (result.get("raw_text") or "").lower()

    if "unable to" in raw or "detect name" in raw or "tap to edit" in raw:
        return False

    if result.get("iv_percent") is None:
        return False

    if result.get("max_pvp_percent") is None:
        return False

    return True


# =============================================================================
# SCAN + RETRY + LOG
# =============================================================================

def scan_current_table_once(
    ocr: PaddleOCR,
    iteration: int,
    attempt: int,
    threshold: float,
    iv_floor: int,
    disable_templates: bool,
    no_template_fallback: bool,
    ocr_roi_width: int,
    ocr_roi_height: int,
    ocr_roi_offset_x: int,
    ocr_roi_offset_y: int,
) -> Dict[str, Any]:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    screen_path = SCREEN_DIR / f"scan{iteration}_attempt{attempt}_screen_{ts}.png"
    debug_path = CROP_DIR / f"scan{iteration}_attempt{attempt}_debug_overlay_{ts}.png"
    raw_crop_path = CROP_DIR / f"scan{iteration}_attempt{attempt}_pokegenie_raw_{ts}.png"
    ocr_crop_path = CROP_DIR / f"scan{iteration}_attempt{attempt}_pokegenie_ocr_{ts}.png"

    adb_screenshot(screen_path)

    img = cv2.imread(str(screen_path))
    if img is None:
        raise RuntimeError(f"Could not read screenshot: {screen_path}")

    h, w = img.shape[:2]
    print(f"Screenshot shape: {w}x{h}")

    ocr_x, ocr_y, ocr_w, ocr_h, overlay_match = find_pokegenie_ocr_roi(
        screenshot_path=screen_path,
        iteration=iteration,
        attempt=attempt,
        fallback_roi=POKE_GENIE_TABLE_REGION,
        disable_templates=disable_templates,
        no_template_fallback=no_template_fallback,
        roi_width=ocr_roi_width,
        roi_height=ocr_roi_height,
        offset_x=ocr_roi_offset_x,
        offset_y=ocr_roi_offset_y,
    )

    ocr_region = (ocr_x, ocr_y, ocr_w, ocr_h)
    save_debug_overlay(img, debug_path, iteration, attempt, ocr_region, overlay_match)
    print("Debug overlay saved:", debug_path)

    raw_crop = crop_region(img, ocr_region)
    cv2.imwrite(str(raw_crop_path), raw_crop)
    print("Raw crop saved:", raw_crop_path)

    ocr_crop = preprocess_for_ocr(raw_crop)
    cv2.imwrite(str(ocr_crop_path), ocr_crop)
    print("OCR crop saved:", ocr_crop_path)

    rows = run_ocr(ocr, ocr_crop)
    parsed = parse_poke_genie_rows(rows)
    classify(parsed, threshold, iv_floor=iv_floor)
    # Legacy/Poke Genie scans are comparison evidence only. They do not have
    # the multi-frame native consensus required for an automatic rename.
    parsed["scan_status"] = "REVIEW"
    parsed["failure_reasons"] = ["INCOMPLETE_SCAN"]

    # The Poke Genie crop does not contain Pokémon GO's native appraisal labels
    # or caught sentence, so run the same OCR adapter over the full screenshot.
    full_screen_rows = run_ocr(ocr, img)
    native_debug_path = CROP_DIR / (
        f"scan{iteration}_attempt{attempt}_native_iv_debug_{ts}.png"
    )
    native = OcrAnchoredAppraisalDetector().detect(
        img, full_screen_rows, debug_path=str(native_debug_path)
    )

    pokegenie_species = parsed.get("species")
    native_species = native.species_from_sentence
    ranking_species = native_species or pokegenie_species
    parsed.update({
        "pokegenie_species": pokegenie_species,
        "native_species": native_species,
        "species_match": bool(
            pokegenie_species and native_species
            and pokegenie_species.casefold() == native_species.casefold()
        ),
        "native_attack": native.attack,
        "native_defense": native.defense,
        "native_hp": native.hp,
        "native_bar_confidence": native.confidence,
        "native_bar_reason": native.reason,
        "native_bar_debug": str(native_debug_path),
        "native_vs_genie_match": (
            all(value is not None for value in (
                native.attack, native.defense, native.hp,
                parsed.get("attack"), parsed.get("defense"), parsed.get("hp"),
            ))
            and (int(parsed["attack"]), int(parsed["defense"]), int(parsed["hp"]))
            == (native.attack, native.defense, native.hp)
        ),
        "calculated_gl_rank": None,
        "calculated_ul_rank": None,
        "calculated_ml_rank": None,
        "rank_error": None,
    })

    # Rankings intentionally require an explicit complete data file. The bundled
    # example JSON is not selected automatically and must not produce real ranks.
    pokemon_data_path = os.environ.get("POGO_POKEMON_DATA")
    if (
        pokemon_data_path and ranking_species
        and native.reason == "ok"
        and native.attack is not None and native.defense is not None and native.hp is not None
    ):
        try:
            ranks = all_league_ranks(
                PokemonData(pokemon_data_path), ranking_species,
                native.attack, native.defense, native.hp,
                form=os.environ.get("POGO_FORM", "NORMAL"),
                max_level=float(os.environ.get("POGO_MAX_LEVEL", "50")),
            )
            parsed["calculated_gl_rank"] = ranks["GL"].rank
            parsed["calculated_ul_rank"] = ranks["UL"].rank
            parsed["calculated_ml_rank"] = ranks["ML"].rank
        except (OSError, KeyError, ValueError) as exc:
            parsed["rank_error"] = str(exc)

    result = {
        "iteration": iteration,
        "attempt": attempt,
        "timestamp": ts,
        "screenshot": str(screen_path),
        "debug_overlay": str(debug_path),
        "raw_crop": str(raw_crop_path),
        "ocr_crop": str(ocr_crop_path),
        "ocr_region": ocr_region,
        "ocr_rows": rows,
        **parsed,
    }

    return result


def refresh_same_pokemon_left_right(
    execute: bool,
    wait_after_left: float,
    wait_after_right: float,
    disable_templates: bool,
    no_template_fallback: bool,
    iteration: int,
) -> None:
    print("Refreshing same Pokémon: previous swipe -> wait -> next swipe -> wait")
    swipe_fixed_scan_triangle_level("left", execute=execute)
    time.sleep(wait_after_left)
    swipe_fixed_scan_triangle_level("right", execute=execute)
    time.sleep(wait_after_right)
    return
    adb_tap(*COORDS_1008x2244["left_triangle"], execute=execute)
    time.sleep(wait_after_left)

    tap_ui_template(
        name="right_triangle",
        execute=execute,
        iteration=iteration,
        fallback=not no_template_fallback,
        disable_templates=disable_templates,
    )
    time.sleep(wait_after_right)


def scan_current_table_with_retries(
    ocr: PaddleOCR,
    iteration: int,
    threshold: float,
    iv_floor: int,
    retries: int,
    retry_wait_before_ocr: float,
    execute: bool,
    refresh_on_retry: bool,
    wait_after_left: float,
    wait_after_right: float,
    disable_templates: bool,
    no_template_fallback: bool,
    ocr_roi_width: int,
    ocr_roi_height: int,
    ocr_roi_offset_x: int,
    ocr_roi_offset_y: int,
) -> Dict[str, Any]:
    last_result: Optional[Dict[str, Any]] = None

    for attempt in range(1, retries + 2):
        print(f"\nOCR attempt {attempt}/{retries + 1}")
        print(f"Waiting {retry_wait_before_ocr:.1f}s before OCR...")
        time.sleep(retry_wait_before_ocr)

        result = scan_current_table_once(
            ocr=ocr,
            iteration=iteration,
            attempt=attempt,
            threshold=threshold,
            iv_floor=iv_floor,
            disable_templates=disable_templates,
            no_template_fallback=no_template_fallback,
            ocr_roi_width=ocr_roi_width,
            ocr_roi_height=ocr_roi_height,
            ocr_roi_offset_x=ocr_roi_offset_x,
            ocr_roi_offset_y=ocr_roi_offset_y,
        )

        last_result = result

        if is_readable(result):
            if attempt > 1:
                result["reason"] = f"{result.get('reason')} | succeeded after retry {attempt}"
            return result

        print("OCR/Poke Genie result not readable.")
        print("Raw text:", result.get("raw_text"))

        if attempt <= retries:
            if refresh_on_retry:
                refresh_same_pokemon_left_right(
                    execute=execute,
                    wait_after_left=wait_after_left,
                    wait_after_right=wait_after_right,
                    disable_templates=disable_templates,
                    no_template_fallback=no_template_fallback,
                    iteration=iteration,
                )
            else:
                print("Retry refresh disabled. Waiting before next OCR attempt...")
                time.sleep(wait_after_right)

    print("Still unreadable after retries. Keeping final REVIEW result.")
    assert last_result is not None
    last_result["scan_status"] = "REVIEW"
    last_result["decision"] = "REVIEW"
    last_result["rename_to"] = ""
    last_result["keep_reason_type"] = "review"
    last_result["failure_reasons"] = ["MALFORMED_POKEGENIE_RESULT"]
    last_result["reason"] = "REVIEW: malformed or incomplete Poke Genie OCR result"
    return last_result


def log_scan(result: Dict[str, Any]) -> None:
    csv_path = LOG_DIR / "pokegenie_scan_log.csv"
    write_header = not csv_path.exists()

    row = {
        "iteration": result["iteration"],
        "attempt": result.get("attempt"),
        "timestamp": result["timestamp"],
        "decision": result.get("decision"),
        "scan_status": result.get("scan_status", "REVIEW"),
        "failure_reasons": json.dumps(result.get("failure_reasons", [])),
        "reason": result.get("reason"),
        "species": result.get("species"),
        "pokegenie_species": result.get("pokegenie_species"),
        "native_species": result.get("native_species"),
        "species_match": result.get("species_match"),
        "iv_percent": result.get("iv_percent"),
        "attack": result.get("attack"),
        "defense": result.get("defense"),
        "hp": result.get("hp"),
        "native_attack": result.get("native_attack"),
        "native_defense": result.get("native_defense"),
        "native_hp": result.get("native_hp"),
        "native_bar_confidence": result.get("native_bar_confidence"),
        "native_bar_reason": result.get("native_bar_reason"),
        "native_vs_genie_match": result.get("native_vs_genie_match"),
        "calculated_gl_rank": result.get("calculated_gl_rank"),
        "calculated_ul_rank": result.get("calculated_ul_rank"),
        "calculated_ml_rank": result.get("calculated_ml_rank"),
        "rank_error": result.get("rank_error"),
        "cp": result.get("cp"),
        "level": result.get("level"),
        "pvp_percentages": json.dumps(result.get("pvp_percentages", [])),
        "pvp_rank_1_percent": result.get("pvp_rank_1_percent"),
        "pvp_rank_2_percent": result.get("pvp_rank_2_percent"),
        "max_pvp_percent": result.get("max_pvp_percent"),
        "keep_reason_type": result.get("keep_reason_type"),
        "rename_to": result.get("rename_to"),
        "raw_text": result.get("raw_text"),
        "screenshot": result.get("screenshot"),
        "debug_overlay": result.get("debug_overlay"),
        "raw_crop": result.get("raw_crop"),
        "ocr_crop": result.get("ocr_crop"),
        "ocr_region": json.dumps(result.get("ocr_region")),
        "ocr_rows": json.dumps(result.get("ocr_rows", []), ensure_ascii=False, default=str),
    }

    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    print("Logged:", csv_path)


def print_scan(result: Dict[str, Any]) -> None:
    print("\nOCR rows:")
    rows = result.get("ocr_rows", [])
    if not rows:
        print("[no text detected]")
    for r in rows:
        print(f"{r['score']:.3f}  {r['text']}")

    print("\nParsed:")
    for key in [
        "species",
        "iv_percent",
        "attack",
        "defense",
        "hp",
        "cp",
        "level",
        "pvp_percentages",
        "pvp_rank_1_percent",
        "pvp_rank_2_percent",
        "max_pvp_percent",
        "keep_reason_type",
        "rename_to",
        "decision",
        "reason",
        "raw_text",
        "ocr_region",
    ]:
        print(f"{key}: {result.get(key)}")


# =============================================================================
# ACTION SEQUENCES
# =============================================================================

def open_initial_appraisal(
    execute: bool,
    wait_after_appraise: float,
    wait_after_middle_tap: float,
    disable_templates: bool,
    no_template_fallback: bool,
) -> None:
    tap_ui_template(
        name="three_bar_menu",
        execute=execute,
        iteration=0,
        fallback=not no_template_fallback,
        disable_templates=disable_templates,
    )
    time.sleep(0.8)

    tap_ui_template(
        name="appraise",
        execute=execute,
        iteration=0,
        fallback=not no_template_fallback,
        disable_templates=disable_templates,
    )
    time.sleep(wait_after_appraise)

    # Keep this fixed because this tap is a screen-settle/Poke-Genie activation tap,
    # not a UI element with a visible template.
    adb_tap(*COORDS_1008x2244["middle_left_of_triangle"], execute=execute)
    time.sleep(wait_after_middle_tap)



def tap_fixed_scan_triangle(direction: str, execute: bool) -> Tuple[int, int]:
    """
    Scanner navigation should use the real lower side appraisal triangle coordinates,
    not the triangle template. Template matching can falsely match Pokémon body/wing
    shapes around y≈550 and break scanning.
    """
    width, height = get_screen_size()

    if fixed_triangle_point is not None:
        point = fixed_triangle_point(direction, width, height)
        x, y = point.x, point.y
    else:
        y = int(height * (1757 / 2244))
        if direction == "left":
            x = int(width * (39 / 1008))
        elif direction == "right":
            x = int(width * (970 / 1008))
        else:
            raise ValueError(f"Unsupported scan triangle direction: {direction!r}")

    print(f"Fixed scan {direction} triangle tap at {x},{y} for screen {width}x{height}")
    adb_tap(x, y, execute=execute)
    return x, y


def swipe_fixed_scan_triangle_level(
    direction: str, execute: bool, duration_ms: int = 280,
) -> Tuple[int, int, int, int]:
    """Swipe at the scaled appraisal-arrow level; use known geometry in dry runs."""
    width, height = get_screen_size() if execute else (1008, 2244)
    if triangle_level_swipe is not None:
        gesture = triangle_level_swipe(direction, width, height, duration_ms)
        start_x, start_y = gesture.start.x, gesture.start.y
        end_x, end_y = gesture.end.x, gesture.end.y
    else:
        y = round(height * (1757 / 2244))
        left_x, right_x = max(8, round(width * (39 / 1008))), min(width - 9, round(width * (970 / 1008)))
        start_x, end_x = (right_x, left_x) if direction == "right" else (left_x, right_x)
        start_y = end_y = y
    print(f"Scanner {direction} swipe at triangle level: ({start_x},{start_y}) -> ({end_x},{end_y}), {duration_ms}ms, screen {width}x{height}")
    adb_swipe(start_x, start_y, end_x, end_y, duration_ms, execute)
    return start_x, start_y, end_x, end_y


def press_next_triangle(
    execute: bool,
    wait_after_next: float,
    disable_templates: bool,
    no_template_fallback: bool,
    iteration: int,
) -> None:
    print("Scanner swipe navigation enabled; swiping right-to-left at triangle level.")
    swipe_fixed_scan_triangle_level("right", execute=execute)
    time.sleep(wait_after_next)
    return

    tap_ui_template(
        name="right_triangle",
        execute=execute,
        iteration=iteration,
        fallback=not no_template_fallback,
        disable_templates=disable_templates,
    )
    time.sleep(wait_after_next)


def get_screen_size() -> Tuple[int, int]:
    result = adb("shell", "wm", "size", check=True)
    text = result.stdout.decode("utf-8", errors="replace")
    # Example: "Physical size: 1008x2244"
    m = re.search(r"(\d+)x(\d+)", text)
    if not m:
        raise RuntimeError(f"Could not parse screen size from: {text!r}")
    return int(m.group(1)), int(m.group(2))


def tap_far_right_middle_for_rename_prepare(execute: bool) -> None:
    width, height = get_screen_size()

    # Same idea as x=1006,y=1122 on 1008x2244:
    # very close to right edge, vertically centered.
    x = max(1, width - 2)
    y = int(height * 0.50)

    print(f"Preparing rename start with scaled far-right tap at {x},{y} for screen {width}x{height}")
    adb_tap(x, y, execute=execute)


def return_to_first_scanned_pokemon(
    execute: bool,
    left_taps: int,
    wait_after_left: float,
    prepare_for_rename: bool,
    wait_after_prepare_tap: float,
) -> None:
    """
    After scanning N Pokémon, the scanner has moved right N-1 times.
    Pressing left N-1 times returns to the first scanned Pokémon.
    """
    if left_taps <= 0:
        print("Return-to-start: no left taps needed.")
        return

    print(f"Return-to-start: swiping to previous Pokémon {left_taps} time(s)...")

    for idx in range(1, left_taps + 1):
        print(f"Return-to-start previous swipe {idx}/{left_taps}")
        swipe_fixed_scan_triangle_level("left", execute=execute)
        time.sleep(wait_after_left)

    if prepare_for_rename:
        print("Return-to-start: final far-right middle tap to prepare clean rename start.")
        tap_far_right_middle_for_rename_prepare(execute=execute)
        time.sleep(wait_after_prepare_tap)


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan Poke Genie OCR table across Pokémon using triangle navigation."
    )

    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--skip-open", action="store_true")

    parser.add_argument(
        "--return-to-start",
        action="store_true",
        default=False,
        help="After scanning, press left triangle count-1 times to return to the first scanned Pokémon. Default: disabled; the safer workflow leaves the game on the last scanned Pokémon and the renamer processes the log in reverse.",
    )
    parser.add_argument(
        "--no-return-to-start",
        action="store_false",
        dest="return_to_start",
        help="Do not return to the first scanned Pokémon after scanning. This is now the default safe workflow.",
    )
    parser.add_argument(
        "--return-left-taps",
        type=int,
        default=None,
        help="Override number of left-triangle taps after scanning. Default: count-1.",
    )
    parser.add_argument(
        "--wait-after-return-left",
        type=float,
        default=1.5,
        help="Seconds to wait after each return-to-start left tap. Default: 1.5.",
    )
    parser.add_argument(
        "--prepare-rename-after-return",
        action="store_true",
        default=True,
        help="After returning to the first scanned Pokémon, tap near the far-right middle of the screen to prepare for rename pass. Default: enabled.",
    )
    parser.add_argument(
        "--no-prepare-rename-after-return",
        action="store_false",
        dest="prepare_rename_after_return",
        help="Do not do the far-right middle prepare tap after returning to start.",
    )
    parser.add_argument(
        "--wait-after-prepare-rename-tap",
        type=float,
        default=1.0,
        help="Seconds to wait after the far-right middle prepare tap. Default: 1.0.",
    )
    parser.add_argument(
        "--prepare-rename-after-scan",
        action="store_true",
        default=True,
        help="After scanning, tap near far-right middle on the current Pokémon to prepare the rename pass. Default: enabled.",
    )
    parser.add_argument(
        "--no-prepare-rename-after-scan",
        action="store_false",
        dest="prepare_rename_after_scan",
        help="Do not do the final far-right middle prepare tap after scanning.",
    )
    parser.add_argument("--threshold", type=float, default=95.0)
    parser.add_argument("--iv-floor", type=int, default=14, help="Minimum IV stat to auto-KEEP, e.g. 14 keeps 14-14-14 or better. Default: 14.")

    parser.add_argument("--disable-templates", action="store_true")
    parser.add_argument("--no-template-fallback", action="store_true")

    parser.add_argument(
        "--disable-startup-guards",
        action="store_true",
        help="Skip initial template visibility guard checks.",
    )

    parser.add_argument(
        "--require-pokegenie-table-after-open",
        action="store_true",
        help="After opening Appraise, also wait until pokegenie_overlay_template.png is visible. Default: disabled.",
    )
    parser.add_argument(
        "--startup-guard-retries",
        type=int,
        default=-1,
        help="Retries for initial template guard checks. Use -1 to wait forever. Default: -1.",
    )
    parser.add_argument(
        "--startup-guard-wait",
        type=float,
        default=1.0,
        help="Seconds between initial template guard retries. Default: 1.0.",
    )

    parser.add_argument("--wait-after-appraise", type=float, default=2.5)
    parser.add_argument("--wait-after-middle-tap", type=float, default=1.0)
    parser.add_argument("--wait-after-next", type=float, default=3.0)
    parser.add_argument("--wait-before-ocr", type=float, default=3.0)
    parser.add_argument("--retries", type=int, default=1)

    parser.add_argument("--refresh-on-retry", action="store_true", default=False)
    parser.add_argument("--no-refresh-on-retry", action="store_false", dest="refresh_on_retry")
    parser.add_argument("--wait-after-left", type=float, default=2.5)
    parser.add_argument("--wait-after-right-retry", type=float, default=3.0)

    parser.add_argument(
        "--ocr-roi-width",
        type=int,
        default=380,
        help="OCR crop width after locating Poke Genie overlay. Default: 380.",
    )
    parser.add_argument(
        "--ocr-roi-height",
        type=int,
        default=540,
        help="OCR crop height after locating Poke Genie overlay. Default: 540.",
    )
    parser.add_argument(
        "--ocr-roi-offset-x",
        type=int,
        default=0,
        help="X offset from overlay template match top-left to OCR ROI top-left. Default: 0.",
    )
    parser.add_argument(
        "--ocr-roi-offset-y",
        type=int,
        default=0,
        help="Y offset from overlay template match top-left to OCR ROI top-left. Default: 0.",
    )

    args = parser.parse_args()

    print("=" * 80)
    print("Mode:", "EXECUTE" if args.execute else "DRY RUN")
    print("Count:", args.count)
    print("Skip open:", args.skip_open)
    print("Return to start:", args.return_to_start)
    print("Return left taps override:", args.return_left_taps)
    print("Prepare rename after return:", args.prepare_rename_after_return)
    print("Prepare rename after scan:", args.prepare_rename_after_scan)
    print("Threshold:", args.threshold)
    print("IV floor:", args.iv_floor)
    print("Template matching:", "disabled" if args.disable_templates else "enabled")
    print("Template fallback:", "disabled" if args.no_template_fallback else "enabled")
    print("Startup guards:", "disabled" if args.disable_startup_guards else ("enabled, waiting forever" if args.startup_guard_retries < 0 else "enabled"))
    print("Require Poke Genie table after open:", args.require_pokegenie_table_after_open)
    print("Template directory:", TEMPLATE_DIR)
    print("Wait after appraise:", args.wait_after_appraise)
    print("Wait after middle tap:", args.wait_after_middle_tap)
    print("Wait after next:", args.wait_after_next)
    print("Wait before OCR:", args.wait_before_ocr)
    print("Retries:", args.retries)
    print("Refresh on retry:", args.refresh_on_retry)
    print("Wait after left:", args.wait_after_left)
    print("Wait after right retry:", args.wait_after_right_retry)
    print("OCR ROI size:", (args.ocr_roi_width, args.ocr_roi_height))
    print("OCR ROI offset:", (args.ocr_roi_offset_x, args.ocr_roi_offset_y))
    print("=" * 80)

    check_adb_device()

    print("Loading PaddleOCR...")
    ocr = make_ocr()

    if not args.disable_startup_guards:
        print("\nStartup guard for scanner: waiting until 3-bar menu is visible...")
        require_templates_visible(
            names=["three_bar_menu"],
            iteration=0,
            attempt=0,
            retries=args.startup_guard_retries,
            wait_seconds=args.startup_guard_wait,
            disable_templates=args.disable_templates,
        )

    if not args.skip_open:
        print("\nOpening appraisal/Poke Genie table...")
        open_initial_appraisal(
            execute=args.execute,
            wait_after_appraise=args.wait_after_appraise,
            wait_after_middle_tap=args.wait_after_middle_tap,
            disable_templates=args.disable_templates,
            no_template_fallback=args.no_template_fallback,
        )

        if args.require_pokegenie_table_after_open and not args.disable_startup_guards:
            print("\nOptional guard for scanner: waiting until Poke Genie table overlay is visible...")
            require_templates_visible(
                names=["pokegenie_overlay"],
                iteration=0,
                attempt=1,
                retries=args.startup_guard_retries,
                wait_seconds=args.startup_guard_wait,
                disable_templates=args.disable_templates,
            )

    for i in range(1, args.count + 1):
        print("\n" + "#" * 80)
        print(f"SCAN {i}/{args.count}")
        print("#" * 80)

        result = scan_current_table_with_retries(
            ocr=ocr,
            iteration=i,
            threshold=args.threshold,
            iv_floor=args.iv_floor,
            retries=args.retries,
            retry_wait_before_ocr=args.wait_before_ocr,
            execute=args.execute,
            refresh_on_retry=args.refresh_on_retry,
            wait_after_left=args.wait_after_left,
            wait_after_right=args.wait_after_right_retry,
            disable_templates=args.disable_templates,
            no_template_fallback=args.no_template_fallback,
            ocr_roi_width=args.ocr_roi_width,
            ocr_roi_height=args.ocr_roi_height,
            ocr_roi_offset_x=args.ocr_roi_offset_x,
            ocr_roi_offset_y=args.ocr_roi_offset_y,
        )

        print_scan(result)
        log_scan(result)

        if i < args.count:
            print("\nPressing right triangle to next Pokémon...")
            press_next_triangle(
                execute=args.execute,
                wait_after_next=args.wait_after_next,
                disable_templates=args.disable_templates,
                no_template_fallback=args.no_template_fallback,
                iteration=i,
            )

    did_prepare_tap = False

    if args.return_to_start:
        left_taps = args.return_left_taps if args.return_left_taps is not None else max(0, args.count - 1)
        return_to_first_scanned_pokemon(
            execute=args.execute,
            left_taps=left_taps,
            wait_after_left=args.wait_after_return_left,
            prepare_for_rename=args.prepare_rename_after_return,
            wait_after_prepare_tap=args.wait_after_prepare_rename_tap,
        )
        did_prepare_tap = bool(args.prepare_rename_after_return)

    if args.prepare_rename_after_scan and not did_prepare_tap:
        print("Final scan prepare: far-right middle tap on current Pokémon for rename pass.")
        tap_far_right_middle_for_rename_prepare(execute=args.execute)
        time.sleep(args.wait_after_prepare_rename_tap)

    print("\nDone.")
    print("\nOpen latest debug overlay:")
    print('  xdg-open "$(ls -t captures/crops/scan*_attempt*_debug_overlay_*.png | head -1)"')
    print("\nOpen latest template debug overlay:")
    print('  xdg-open "$(ls -t captures/crops/*template_debug*.png | head -1)"')
    print("\nOpen scan log:")
    print("  xdg-open captures/logs/pokegenie_scan_log.csv")


if __name__ == "__main__":
    main()
