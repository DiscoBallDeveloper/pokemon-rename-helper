#!/usr/bin/env python3

import argparse
import os
import csv
import pathlib
import subprocess
import shlex
import time
from typing import Any, Dict, List, Optional, Tuple
import re

import cv2

from .ocr import find_text_center


# =============================================================================
# CONFIG
# =============================================================================

BASE_DIR = pathlib.Path("captures")
SCREEN_DIR = BASE_DIR / "screenshots"
LOG_DIR = BASE_DIR / "logs"

def _adb_base_cmd_from_env():
    serial = os.environ.get("POGO_ADB_SERIAL") or os.environ.get("ADB_SERIAL")
    if serial:
        return ["adb", "-s", serial]
    return ["adb"]

TEMPLATE_DIR = BASE_DIR / "templates"

for d in [SCREEN_DIR, LOG_DIR, TEMPLATE_DIR]:
    d.mkdir(parents=True, exist_ok=True)



try:
    from .navigation import fixed_triangle_point, triangle_level_swipe
except ImportError:  # Allows direct script execution during debugging.
    fixed_triangle_point = None
    triangle_level_swipe = None

COORDS_1008x2244 = {
    # Appraisal / navigation fallback coordinates
    "three_bar_menu": (866, 2105),
    "appraise": (680, 1743),
    "middle_left_of_triangle": (504, 1122),
    "right_triangle": (982, 1821),
    "left_triangle": (26, 1821),
    "after_triangle_center": (504, 1122),
    "cancel_button": (504, 2105),

    # Rename fallback coordinates
    "rename_pencil": (669, 924),
    "rename_text_field": (504, 1015),
    "rename_ok_backup": (504, 1170),
    "rename_ok": (504, 1207),
}

DEFAULT_LOG_FILE = "captures/logs/pokegenie_scan_log.csv"
DEFAULT_RENAME_TO = "delete1"

SEARCH_REGIONS = {
    "left_triangle": (0, 1350, 180, 650),
    "right_triangle": (828, 1350, 180, 650),
}

TEMPLATES = {
    "rename_pencil": TEMPLATE_DIR / "rename_pencil_template.png",
    "three_bar_menu": TEMPLATE_DIR / "three_bar_menu_template.png",
    "appraise": TEMPLATE_DIR / "appraise_template.png",
    "right_triangle": TEMPLATE_DIR / "right_triangle_template.png",
    "left_triangle": TEMPLATE_DIR / "left_triangle_template.png",
    "rename_ok": TEMPLATE_DIR / "rename_ok_template.png",
    "cancel_button": TEMPLATE_DIR / "cancel_button_template.png",
}

TEMPLATE_THRESHOLDS = {
    "rename_pencil": 0.70,
    "three_bar_menu": 0.65,
    "appraise": 0.65,
    "right_triangle": 0.65,
    "left_triangle": 0.65,
    "rename_ok": 0.65,
    "cancel_button": 0.65,
}

FALLBACK_COORDS = {
    "rename_pencil": COORDS_1008x2244["rename_pencil"],
    "three_bar_menu": COORDS_1008x2244["three_bar_menu"],
    "appraise": COORDS_1008x2244["appraise"],
    "right_triangle": COORDS_1008x2244["right_triangle"],
    "left_triangle": COORDS_1008x2244["left_triangle"],
    "rename_ok": COORDS_1008x2244["rename_ok"],
    "cancel_button": COORDS_1008x2244["cancel_button"],
}

# Keep matching broad/full-screen for portability across resolutions.
# You can set values like (x, y, w, h) later if matching gets slow or ambiguous.
SEARCH_REGIONS: Dict[str, Optional[Tuple[int, int, int, int]]] = {
    "rename_pencil": None,
    "three_bar_menu": None,
    "appraise": None,
    "right_triangle": None,
    "rename_ok": None,
    "cancel_button": None,
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


def adb_keyevent(key: str, execute: bool = False) -> None:
    if not execute:
        print(f"[DRY RUN] keyevent {key}")
        return
    adb("shell", "input", "keyevent", key)


def adb_delete_chars(n: int = 35, execute: bool = False) -> None:
    if not execute:
        print(f"[DRY RUN] delete {n} chars")
        return

    for _ in range(n):
        adb("shell", "input", "keyevent", "DEL")
        time.sleep(0.02)


def adb_type_ascii(text: str, execute: bool = False) -> None:
    """
    Type text through ADB safely.

    The Android-side shell parses the argument after `adb shell input text`.
    Characters like %, (, ), &, and spaces can break if they are not quoted.
    We use %s for spaces because Android's input command treats %s as a space,
    then quote the whole argument for the Android-side shell.
    """
    safe = text.replace(" ", "%s")
    remote_arg = shlex.quote(safe)

    if execute:
        print(f"ADB: adb shell input text {remote_arg}")
        adb("shell", "input", "text", remote_arg)
    else:
        print(f"DRY RUN: adb shell input text {remote_arg}")


def adb_screenshot(path: pathlib.Path) -> None:
    with path.open("wb") as f:
        result = subprocess.run(
            [*_adb_base_cmd_from_env(), "exec-out", "screencap", "-p"],
            stdout=f,
            stderr=subprocess.PIPE,
        )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))


def save_screenshot(prefix: str, row_number: int) -> Optional[pathlib.Path]:
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = SCREEN_DIR / f"rename_row{row_number}_{prefix}_{ts}.png"

    try:
        adb_screenshot(path)
        print(f"{prefix} screenshot saved:", path)
        return path
    except Exception as e:
        print(f"Could not save screenshot {prefix}:", e)
        return None


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
    """
    Returns:
        center_x, center_y, score, matched_rect

    matched_rect is:
        x, y, w, h
    """
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
    row_number: int,
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

    ts = time.strftime("%Y%m%d_%H%M%S")
    path = SCREEN_DIR / f"rename_row{row_number}_{name}_match_debug_{ts}.png"
    cv2.imwrite(str(path), img)
    print(f"{name} match debug saved:", path)
    return path


def tap_ui_template(
    name: str,
    execute: bool,
    row_number: int,
    fallback: bool = True,
    threshold_override: Optional[float] = None,
    disable_templates: bool = False,
) -> Optional[Tuple[int, int]]:
    """
    Finds a UI template and taps its center. Falls back to old coordinates if needed.
    """
    fallback_xy = FALLBACK_COORDS.get(name)

    if name == "appraise" and not disable_templates:
        screenshot_path = save_screenshot("before_ocr_appraise", row_number)
        if screenshot_path is not None:
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
    if template_path is None:
        if fallback and fallback_xy is not None:
            print(f"{name}: no template configured, falling back to {fallback_xy}")
            adb_tap(*fallback_xy, execute=execute)
            return fallback_xy
        raise RuntimeError(f"No template configured for {name}")

    threshold = threshold_override if threshold_override is not None else TEMPLATE_THRESHOLDS.get(name, 0.65)

    if not template_path.exists():
        print(f"{name}: template not found: {template_path}")
        if fallback and fallback_xy is not None:
            print(f"{name}: falling back to fixed coordinate {fallback_xy}")
            adb_tap(*fallback_xy, execute=execute)
            return fallback_xy
        raise FileNotFoundError(f"Template not found for {name}: {template_path}")

    screenshot_path = save_screenshot(f"before_template_{name}", row_number)
    if screenshot_path is None:
        if fallback and fallback_xy is not None:
            print(f"{name}: screenshot failed, falling back to {fallback_xy}")
            adb_tap(*fallback_xy, execute=execute)
            return fallback_xy
        raise RuntimeError(f"Could not take screenshot before matching {name}")

    match = find_template_center(
        screenshot_path=screenshot_path,
        template_path=template_path,
        threshold=threshold,
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
        row_number=row_number,
        name=name,
        rect=rect,
        score=score,
    )

    print(f"{name}: tapping matched center {x},{y}, score={score:.3f}")
    adb_tap(x, y, execute=execute)
    return (x, y)


def template_visible_once(
    name: str,
    row_number: int,
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

    screenshot_path = save_screenshot(f"guard_check_{name}", row_number)
    if screenshot_path is None:
        raise RuntimeError(f"Could not take screenshot for guard: {name}")

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
        row_number=row_number,
        name=f"guard_{name}",
        rect=rect,
        score=score,
    )
    print(f"STARTUP GUARD: {name} visible at {x},{y}, score={score:.3f}")
    return True


def require_templates_visible(
    names: List[str],
    row_number: int,
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

    attempt = 1
    missing = list(names)

    while True:
        limit_text = "forever" if retries < 0 else str(retries + 1)
        print(f"STARTUP GUARD attempt {attempt}/{limit_text}: need {missing}")

        still_missing = []
        for name in missing:
            if not template_visible_once(name=name, row_number=row_number):
                still_missing.append(name)

        if not still_missing:
            print("STARTUP GUARD: all required templates visible. Continuing.")
            return

        missing = still_missing

        if retries >= 0 and attempt >= retries + 1:
            raise RuntimeError(
                "Startup guard failed. Required template(s) not visible: "
                + ", ".join(missing)
                + ". Put the game on the expected screen or use --disable-startup-guards."
            )

        print(f"STARTUP GUARD: missing {missing}; waiting {wait_seconds:.1f}s before fresh screenshot...")
        time.sleep(wait_seconds)
        attempt += 1


# =============================================================================
# SCREEN STATE HELPERS
# =============================================================================

def keyboard_likely_open_from_screenshot(path: pathlib.Path) -> bool:
    img = cv2.imread(str(path))
    if img is None:
        print("Keyboard check: could not read screenshot.")
        return False

    h, w = img.shape[:2]
    bottom = img[int(h * 0.70):h, 0:w]

    gray = cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY)
    mean_brightness = float(gray.mean())

    keyboard_open = mean_brightness < 95.0

    print(f"Keyboard check: bottom mean brightness={mean_brightness:.1f}, open={keyboard_open}")
    return keyboard_open


def ensure_keyboard_after_pencil(
    execute: bool,
    row_number: int,
    wait_after_focus_tap: float,
) -> bool:
    if not execute:
        print("[DRY RUN] would check whether keyboard is open after pencil")
        return True

    first = save_screenshot("after_pencil_keyboard_check_1", row_number)
    if first and keyboard_likely_open_from_screenshot(first):
        return True

    print("Keyboard not detected. Tapping rename text field to refocus...")
    adb_tap(*COORDS_1008x2244["rename_text_field"], execute=execute)
    time.sleep(wait_after_focus_tap)

    second = save_screenshot("after_pencil_keyboard_check_2", row_number)
    if second and keyboard_likely_open_from_screenshot(second):
        return True

    print("WARNING: keyboard still not detected. Will attempt delete/type anyway.")
    return False


# =============================================================================
# LOG READING
# =============================================================================

def read_scan_log(path: pathlib.Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")

    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise RuntimeError(f"Log file is empty: {path}")

    return rows


def select_rows(
    rows: List[Dict[str, str]],
    start: int,
    count: Optional[int],
) -> List[Dict[str, str]]:
    if start < 1:
        raise ValueError("--start must be 1 or greater")

    selected = rows[start - 1:]

    if count is not None:
        selected = selected[:count]

    return selected


# =============================================================================
# ACTIONS
# =============================================================================


def is_green_rename_ok_area(
    screenshot_path: pathlib.Path,
    center_x: int,
    center_y: int,
) -> bool:
    """
    Checks whether the matched OK is sitting on the green Pokémon GO rename button.

    This rejects keyboard OK / text suggestions / other white or dark UI areas.
    """
    img = cv2.imread(str(screenshot_path))
    if img is None:
        print("Green check: could not read screenshot.")
        return False

    h, w = img.shape[:2]

    # Sample a rectangle around the OK text, biased to include the green button background.
    x1 = max(0, center_x - 180)
    x2 = min(w, center_x + 180)
    y1 = max(0, center_y - 70)
    y2 = min(h, center_y + 70)

    patch = img[y1:y2, x1:x2]
    if patch.size == 0:
        return False

    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)

    # Pokémon GO green/teal button range.
    # Hue roughly green/cyan, decent saturation, decent brightness.
    lower = (35, 45, 80)
    upper = (95, 255, 255)

    mask = cv2.inRange(hsv, lower, upper)
    green_ratio = float(mask.mean() / 255.0)

    print(f"Green OK check: green_ratio={green_ratio:.3f} around ({center_x},{center_y})")

    return green_ratio >= 0.20
    
    

def tap_far_left_middle_for_triangle_reveal(execute: bool) -> None:
    """
    When appraisal is open, the left/right navigation triangles may be hidden until
    the player taps near the edge/middle of the screen. This tap is only used to
    reveal navigation UI before matching/tapping the triangle.
    """
    width, height = get_screen_size()
    x = max(2, int(width * 0.002))
    y = int(height * 0.50)
    print(f"Revealing left triangle with scaled far-left tap at {x},{y} for screen {width}x{height}")
    adb_tap(x, y, execute=execute)


def tap_far_right_middle_for_triangle_reveal(execute: bool) -> None:
    """
    Symmetric reveal tap for right-side navigation UI.
    """
    width, height = get_screen_size()
    x = max(1, width - 2)
    y = int(height * 0.50)
    print(f"Revealing right triangle with scaled far-right tap at {x},{y} for screen {width}x{height}")
    adb_tap(x, y, execute=execute)



def tap_three_bar_area_for_triangle_reveal(execute: bool) -> None:
    """
    Pokémon GO reliably shows the appraisal navigation triangles after appraisal
    is open and we tap the lower-right 3-bar/menu area. This is more reliable
    than a 2-pixel edge tap on some screens.
    """
    x, y = COORDS_1008x2244["three_bar_menu"]
    print(f"Revealing navigation triangles with 3-bar-area tap at {x},{y}")
    adb_tap(x, y, execute=execute)

def triangle_match_is_in_expected_edge(
    name: str,
    x: int,
    y: int,
    screenshot_path: pathlib.Path,
) -> bool:
    """
    Reject triangle template matches that are not actually near the lower screen edge.
    The real appraisal navigation triangles are around y≈1750 on 1008x2244.
    """
    img = cv2.imread(str(screenshot_path))
    if img is None:
        return False

    h, w = img.shape[:2]
    lower_y = int(h * 0.58)
    upper_y = int(h * 0.92)

    if name == "left_triangle":
        return x <= max(100, int(w * 0.13)) and lower_y <= y <= upper_y

    if name == "right_triangle":
        return x >= min(w - 100, int(w * 0.87)) and lower_y <= y <= upper_y

    return True


    h, w = img.shape[:2]

    if name == "left_triangle":
        return x <= max(90, int(w * 0.12)) and int(h * 0.55) <= y <= int(h * 0.90)

    if name == "right_triangle":
        return x >= min(w - 90, int(w * 0.88)) and int(h * 0.55) <= y <= int(h * 0.90)

    return True



def find_navigation_triangle_center(
    name: str,
    screenshot_path: pathlib.Path,
    template_path: pathlib.Path,
    threshold: float,
) -> Optional[Tuple[int, int, float, Tuple[int, int, int, int]]]:
    """
    Search only the real lower side area where Pokémon GO appraisal navigation
    triangles appear. This prevents false positives like x=95,y=324.
    Returns full-screen coordinates.
    """
    img = cv2.imread(str(screenshot_path))
    tmpl = cv2.imread(str(template_path))

    if img is None:
        raise RuntimeError(f"Could not read screenshot: {screenshot_path}")
    if tmpl is None:
        raise RuntimeError(f"Could not read template: {template_path}")

    h, w = img.shape[:2]

    # Real appraisal side triangles on 1008x2244 appear around y≈1756.
    # Use a lower-side crop only.
    y1 = int(h * 0.58)
    y2 = int(h * 0.90)

    if name == "left_triangle":
        x1 = 0
        x2 = int(w * 0.18)
    elif name == "right_triangle":
        x1 = int(w * 0.82)
        x2 = w
    else:
        return find_template_center(
            screenshot_path=screenshot_path,
            template_path=template_path,
            threshold=threshold,
            search_region=SEARCH_REGIONS.get(name),
        )

    crop = img[y1:y2, x1:x2]

    if crop.size == 0:
        return None

    result = cv2.matchTemplate(crop, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val < threshold:
        print(f"{name}: no lower-region match, score={max_val:.3f}, threshold={threshold}")
        return None

    th, tw = tmpl.shape[:2]
    lx, ly = max_loc
    full_x1 = x1 + lx
    full_y1 = y1 + ly
    center_x = full_x1 + tw // 2
    center_y = full_y1 + th // 2

    rect = (full_x1, full_y1, tw, th)
    print(
        f"Template match {template_path.name} in lower navigation region: "
        f"score={max_val:.3f}, center=({center_x},{center_y}), threshold={threshold}"
    )

    return center_x, center_y, float(max_val), rect


def tap_navigation_triangle_with_reveal(
    name: str,
    direction: str,
    execute: bool,
    row_number: int,
    fallback: bool,
    disable_templates: bool,
    reveal_before_match: bool,
    wait_before_reveal: float,
    wait_after_reveal: float,
    reveal_retries: int,
    triangle_reveal_tap: str,
    save_reveal_screenshots: bool,
) -> Tuple[int, int]:
    """
    Reveals the hidden side triangle UI, then template-matches the actual side
    triangle near the screen edge. This avoids matching random triangle-like
    shapes when Pokémon GO hides the navigation triangle.
    """
    fallback_xy = FALLBACK_COORDS.get(name)

    if disable_templates:
        print(f"{name}: template matching disabled.")
        if fallback and fallback_xy is not None:
            adb_tap(*fallback_xy, execute=execute)
            return fallback_xy
        raise RuntimeError(f"{name}: templates disabled and no fallback allowed.")

    template_path = TEMPLATES.get(name)
    if template_path is None or not template_path.exists():
        print(f"{name}: template missing: {template_path}")
        if fallback and fallback_xy is not None:
            print(f"{name}: falling back to fixed coordinate {fallback_xy}")
            adb_tap(*fallback_xy, execute=execute)
            return fallback_xy
        raise FileNotFoundError(f"Template not found for {name}: {template_path}")

    threshold = TEMPLATE_THRESHOLDS.get(name, 0.65)
    attempts = max(1, reveal_retries)

    for attempt in range(1, attempts + 1):
        print(f"{name}: reveal/match attempt {attempt}/{attempts}")

        if reveal_before_match:
            if wait_before_reveal > 0:
                print(f"{name}: waiting {wait_before_reveal:.1f}s before reveal tap...")
                time.sleep(wait_before_reveal)

            if triangle_reveal_tap == "three_bar":
                tap_three_bar_area_for_triangle_reveal(execute=execute)
            elif triangle_reveal_tap == "edge":
                if direction == "left":
                    tap_far_left_middle_for_triangle_reveal(execute=execute)
                elif direction == "right":
                    tap_far_right_middle_for_triangle_reveal(execute=execute)
                else:
                    raise ValueError(f"Unsupported triangle direction: {direction!r}")
            else:
                raise ValueError(f"Unsupported triangle reveal tap mode: {triangle_reveal_tap!r}")

            time.sleep(wait_after_reveal)

            if execute and save_reveal_screenshots:
                save_screenshot(f"after_{direction}_triangle_reveal_attempt{attempt}", row_number)

        screenshot_path = save_screenshot(f"before_template_{name}_attempt{attempt}", row_number)
        if screenshot_path is None:
            print(f"{name}: screenshot failed on attempt {attempt}")
            continue

        if name in {"left_triangle", "right_triangle"}:
            match = find_navigation_triangle_center(
                name=name,
                screenshot_path=screenshot_path,
                template_path=template_path,
                threshold=threshold,
            )
        else:
            match = find_template_center(
                screenshot_path=screenshot_path,
                template_path=template_path,
                threshold=threshold,
                search_region=SEARCH_REGIONS.get(name),
            )

        if match is None:
            print(f"{name}: no template match on attempt {attempt}")
            continue

        x, y, score, rect = match

        save_template_debug_overlay(
            screenshot_path=screenshot_path,
            row_number=row_number,
            name=f"{name}_attempt{attempt}",
            rect=rect,
            score=score,
        )

        if not triangle_match_is_in_expected_edge(name, x, y, screenshot_path):
            print(f"{name}: rejected match at {x},{y}, score={score:.3f}; not in lower side triangle region.")
            continue

        print(f"{name}: accepted edge match at {x},{y}, score={score:.3f}; tapping.")
        adb_tap(x, y, execute=execute)
        return (x, y)

    if fallback and fallback_xy is not None:
        print(f"{name}: all reveal/template attempts failed; falling back to fixed coordinate {fallback_xy}")
        adb_tap(*fallback_xy, execute=execute)
        return fallback_xy

    raise RuntimeError(f"{name}: failed to reveal/match navigation triangle after {attempts} attempt(s).")


def confirm_rename_with_guarded_ok_template(
    execute: bool,
    row_number: int,
    disable_templates: bool,
    no_template_fallback: bool,
) -> None:
    print("Confirming rename with guarded OK template...")

    if disable_templates:
        print("Templates disabled. Using fixed OK taps.")
        adb_keyevent("ENTER", execute=execute)
        time.sleep(0.8)
        adb_tap(*COORDS_1008x2244["rename_ok_backup"], execute=execute)
        time.sleep(0.5)
        adb_tap(*COORDS_1008x2244["rename_ok"], execute=execute)
        time.sleep(1.2)
        return

    template_path = TEMPLATES["rename_ok"]
    threshold = TEMPLATE_THRESHOLDS.get("rename_ok", 0.65)

    if not template_path.exists():
        print(f"rename_ok template missing: {template_path}")
        if no_template_fallback:
            raise FileNotFoundError(template_path)

        print("Falling back to fixed OK taps.")
        adb_keyevent("ENTER", execute=execute)
        time.sleep(0.8)
        adb_tap(*COORDS_1008x2244["rename_ok_backup"], execute=execute)
        time.sleep(0.5)
        adb_tap(*COORDS_1008x2244["rename_ok"], execute=execute)
        time.sleep(1.2)
        return

    # Do NOT press ENTER before matching.
    # The green OK button is visible while the keyboard is open.
    screenshot_path = save_screenshot("before_guarded_rename_ok", row_number)
    if screenshot_path is None:
        if no_template_fallback:
            raise RuntimeError("Could not screenshot before guarded OK match.")

        print("Screenshot failed. Falling back to fixed OK taps.")
        adb_keyevent("ENTER", execute=execute)
        time.sleep(0.8)
        adb_tap(*COORDS_1008x2244["rename_ok_backup"], execute=execute)
        time.sleep(0.5)
        adb_tap(*COORDS_1008x2244["rename_ok"], execute=execute)
        time.sleep(1.2)
        return

    match = find_template_center(
        screenshot_path=screenshot_path,
        template_path=template_path,
        threshold=threshold,
        # Only search the green Pokémon GO dialog OK button area.
        search_region=(80, 1080, 850, 260),
    )

    if match is None:
        print("Guarded OK: template match failed.")
        if no_template_fallback:
            raise RuntimeError("Guarded OK template match failed.")

        print("Falling back to fixed OK taps.")
        adb_keyevent("ENTER", execute=execute)
        time.sleep(0.8)
        adb_tap(*COORDS_1008x2244["rename_ok_backup"], execute=execute)
        time.sleep(0.5)
        adb_tap(*COORDS_1008x2244["rename_ok"], execute=execute)
        time.sleep(1.2)
        return

    x, y, score, rect = match

    save_template_debug_overlay(
        screenshot_path=screenshot_path,
        row_number=row_number,
        name="guarded_rename_ok",
        rect=rect,
        score=score,
    )

    if not is_green_rename_ok_area(screenshot_path, x, y):
        print("Guarded OK: template matched, but background is not green/teal.")
        if no_template_fallback:
            raise RuntimeError("Guarded OK match rejected by green background check.")

        print("Falling back to fixed OK taps.")
        adb_keyevent("ENTER", execute=execute)
        time.sleep(0.8)
        adb_tap(*COORDS_1008x2244["rename_ok_backup"], execute=execute)
        time.sleep(0.5)
        adb_tap(*COORDS_1008x2244["rename_ok"], execute=execute)
        time.sleep(1.2)
        return

    print(f"Guarded OK accepted: tapping {x},{y}, score={score:.3f}")
    adb_tap(x, y, execute=execute)
    time.sleep(1.5)
    
    
def get_screen_size() -> Tuple[int, int]:
    result = adb("shell", "wm", "size", check=True)
    text = result.stdout.decode("utf-8", errors="replace")
    # Example: "Physical size: 1008x2244"
    m = re.search(r"(\d+)x(\d+)", text)
    if not m:
        raise RuntimeError(f"Could not parse screen size from: {text!r}")
    return int(m.group(1)), int(m.group(2))


def tap_far_left_middle_for_keyboard_dismiss(execute: bool) -> None:
    width, height = get_screen_size()

    # Same idea as x=2,y=1122 on 1008x2244:
    # very close to left edge, vertically centered.
    x = max(2, int(width * 0.002))
    y = int(height * 0.50)

    print(f"Dismissing keyboard with scaled far-left tap at {x},{y} for screen {width}x{height}")
    adb_tap(x, y, execute=execute)        

def rename_current_pokemon(
    rename_to: str,
    execute: bool,
    row_number: int,
    wait_after_pencil: float,
    wait_after_focus_tap: float,
    disable_templates: bool,
    no_template_fallback: bool,
) -> None:
    print("Opening rename field by template-matching pencil...")

    tap_ui_template(
        name="rename_pencil",
        execute=execute,
        row_number=row_number,
        fallback=not no_template_fallback,
        disable_templates=disable_templates,
    )

    time.sleep(wait_after_pencil)

    ensure_keyboard_after_pencil(
        execute=execute,
        row_number=row_number,
        wait_after_focus_tap=wait_after_focus_tap,
    )

    print("Deleting old name...")
    adb_delete_chars(35, execute=execute)
    time.sleep(0.2)

    print(f"Typing rename: {rename_to}")
    adb_type_ascii(rename_to, execute=execute)
    time.sleep(0.5)

    if execute:
        save_screenshot("after_typing_before_confirm", row_number)

    print("Dismissing keyboard with far-left middle tap...")
    tap_far_left_middle_for_keyboard_dismiss(execute=execute)
    time.sleep(1.0)

    if execute:
        save_screenshot("after_keyboard_dismiss_tap", row_number)

    print("Confirming rename with guarded green OK template...")

    confirm_rename_with_guarded_ok_template(
        execute=execute,
        row_number=row_number,
        disable_templates=disable_templates,
        no_template_fallback=no_template_fallback,
    )

    time.sleep(1.2)

    if execute:
        save_screenshot("post_rename", row_number)


def tap_fixed_navigation_triangle(
    direction: str,
    execute: bool,
) -> Tuple[int, int]:
    """
    Tap the real appraisal navigation triangle by scaled coordinates.

    Uses pogo_auto.navigation.fixed_triangle_point when running as a package.
    Falls back to the proven inline calculation if this file is run directly.
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
            raise ValueError(f"Unsupported navigation direction: {direction!r}")

    print(f"Fixed {direction} triangle tap at {x},{y} for screen {width}x{height}")
    adb_tap(x, y, execute=execute)
    return x, y


def swipe_fixed_navigation_triangle_level(
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
    print(f"Swipe {direction} at triangle level: ({start_x},{start_y}) -> ({end_x},{end_y}), {duration_ms}ms, screen {width}x{height}")
    adb_swipe(start_x, start_y, end_x, end_y, duration_ms, execute)
    return start_x, start_y, end_x, end_y


def reveal_triangles_with_three_bar_and_tap_fixed(
    direction: str,
    execute: bool,
    wait_after_appraise_before_reveal: float,
    wait_after_reveal: float,
) -> Tuple[int, int]:
    """
    After Appraise is open, tap the 3-bar/menu area to reveal the appraisal
    left/right triangles, wait, then tap the fixed triangle center.
    """
    if wait_after_appraise_before_reveal > 0:
        print(f"Waiting {wait_after_appraise_before_reveal:.1f}s before 3-bar reveal tap...")
        time.sleep(wait_after_appraise_before_reveal)

    print("Revealing navigation triangles by tapping 3-bar/menu area...")
    adb_tap(*COORDS_1008x2244["three_bar_menu"], execute=execute)

    if wait_after_reveal > 0:
        print(f"Waiting {wait_after_reveal:.1f}s after 3-bar reveal tap...")
        time.sleep(wait_after_reveal)

    return swipe_fixed_navigation_triangle_level(direction=direction, execute=execute)


def open_appraisal_and_go_next(
    execute: bool,
    row_number: int,
    navigation_index: int,
    wait_before_appraise: float,
    wait_after_appraise: float,
    wait_after_middle_tap: float,
    wait_after_next: float,
    skip_pre_triangle_tap_first_navigation: bool,
    wait_between_triangle_taps: float,
    wait_after_right_side_middle: float,
    disable_templates: bool,
    no_template_fallback: bool,
    navigation_direction: str,
    triangle_taps_per_navigation: int,
    reveal_triangle_before_navigation: bool,
    wait_before_triangle_reveal: float,
    wait_after_triangle_reveal: float,
    triangle_reveal_retries: int,
    triangle_reveal_tap: str,
    save_triangle_reveal_screenshots: bool,
    fixed_triangle_navigation: bool,
    wait_after_appraise_before_triangle_reveal: float,
) -> None:
    print("Opening appraisal/navigation state...")

    tap_ui_template(
        name="three_bar_menu",
        execute=execute,
        row_number=row_number,
        fallback=not no_template_fallback,
        disable_templates=disable_templates,
    )
    time.sleep(wait_before_appraise)

    tap_ui_template(
        name="appraise",
        execute=execute,
        row_number=row_number,
        fallback=not no_template_fallback,
        disable_templates=disable_templates,
    )
    time.sleep(wait_after_appraise)

    print(
        f"Skipping middle-screen pre-tap before {navigation_direction} navigation; "
        "3-bar reveal + triangle-level swipe will handle navigation."
    )

    triangle_taps = max(1, triangle_taps_per_navigation)

    print(f"Going to {navigation_direction} Pokémon with {triangle_taps} swipe(s)...")

    if fixed_triangle_navigation:
        for tap_num in range(1, triangle_taps + 1):
            reveal_triangles_with_three_bar_and_tap_fixed(
                direction=navigation_direction,
                execute=execute,
                wait_after_appraise_before_reveal=wait_after_appraise_before_triangle_reveal,
                wait_after_reveal=wait_after_triangle_reveal,
            )
            if tap_num < triangle_taps:
                time.sleep(wait_between_triangle_taps)
            else:
                time.sleep(wait_after_next)

        print("Pressing center of screen after triangle-level swipes...")
        adb_tap(*COORDS_1008x2244["after_triangle_center"], execute=execute)
        time.sleep(wait_after_right_side_middle)
        return

    for tap_num in range(1, triangle_taps + 1):
        if navigation_direction == "right":
            template_name = "right_triangle"
        elif navigation_direction == "left":
            template_name = "left_triangle"
        else:
            raise ValueError(f"Unsupported navigation direction: {navigation_direction!r}")

        tap_navigation_triangle_with_reveal(
            name=template_name,
            direction=navigation_direction,
            execute=execute,
            row_number=row_number,
            fallback=not no_template_fallback,
            disable_templates=disable_templates,
            reveal_before_match=reveal_triangle_before_navigation,
            wait_before_reveal=wait_before_triangle_reveal,
            wait_after_reveal=wait_after_triangle_reveal,
            reveal_retries=triangle_reveal_retries,
            triangle_reveal_tap=triangle_reveal_tap,
            save_reveal_screenshots=save_triangle_reveal_screenshots,
        )

        if tap_num < triangle_taps:
            time.sleep(wait_between_triangle_taps)
        else:
            time.sleep(wait_after_next)

    print("Pressing center of screen after triangle taps...")
    adb_tap(*COORDS_1008x2244["after_triangle_center"], execute=execute)
    time.sleep(wait_after_right_side_middle)


def close_appraisal_to_clean_page(
    execute: bool,
    wait_after_close: float,
    row_number: int,
) -> None:
    print("Closing appraisal/navigation state with wait only...")

    # This intentionally does not tap BACK or cancel because your current working
    # version became stable after removing that tap.
    time.sleep(wait_after_close)

    if execute:
        save_screenshot("after_close_appraisal", row_number)


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rename Pokémon from an existing Poke Genie scan log."
    )

    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--log-file", default=DEFAULT_LOG_FILE)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--rename-to", default=DEFAULT_RENAME_TO)

    parser.add_argument(
        "--reverse-log-order",
        action="store_true",
        default=True,
        help="Process selected CSV rows from bottom to top. Default: enabled; use this when the scanner leaves the game on the last scanned Pokémon.",
    )
    parser.add_argument(
        "--forward-log-order",
        action="store_false",
        dest="reverse_log_order",
        help="Process selected CSV rows from top to bottom. Use only when the game is definitely on the first selected Pokémon.",
    )
    parser.add_argument(
        "--navigation-direction",
        choices=["left", "right"],
        default="left",
        help="Triangle direction after each rename. Default: left, matching reverse-log-order.",
    )
    parser.add_argument(
        "--triangle-taps-per-navigation",
        type=int,
        default=1,
        help="Number of triangle taps after each rename. Default: 1. Do not use 2 unless one-tap navigation is confirmed to fail.",
    )

    parser.add_argument(
        "--fixed-triangle-navigation",
        action="store_true",
        default=True,
        help="Use scaled fixed appraisal triangle coordinates after 3-bar reveal. Default: enabled.",
    )
    parser.add_argument(
        "--template-triangle-navigation",
        action="store_false",
        dest="fixed_triangle_navigation",
        help="Use template matching for triangle navigation instead of fixed coordinates.",
    )
    parser.add_argument(
        "--wait-after-appraise-before-triangle-reveal",
        type=float,
        default=1.0,
        help="Seconds to wait after tapping Appraise before tapping 3-bar to reveal triangles. Default: 1.0.",
    )

    parser.add_argument(
        "--reveal-triangle-before-navigation",
        action="store_true",
        default=True,
        help="Before matching/tapping the left/right triangle, tap 2px from the screen edge at mid-height to reveal the hidden triangle UI. Default: enabled.",
    )
    parser.add_argument(
        "--no-reveal-triangle-before-navigation",
        action="store_false",
        dest="reveal_triangle_before_navigation",
        help="Do not do the edge reveal tap before triangle navigation.",
    )
    parser.add_argument(
        "--wait-after-triangle-reveal",
        type=float,
        default=1.5,
        help="Seconds to wait after the triangle reveal tap before matching the triangle. Default: 1.5.",
    )
    parser.add_argument(
        "--wait-before-triangle-reveal",
        type=float,
        default=1.0,
        help="Extra seconds to wait after opening Appraise and before tapping the 3-bar area to reveal triangles. Default: 1.0.",
    )
    parser.add_argument(
        "--triangle-reveal-retries",
        type=int,
        default=5,
        help="How many reveal+match attempts before falling back/failing. Default: 5.",
    )
    parser.add_argument(
        "--triangle-reveal-tap",
        choices=["three_bar", "edge"],
        default="three_bar",
        help="Where to tap to reveal hidden navigation triangles. Default: three_bar.",
    )
    parser.add_argument(
        "--save-triangle-reveal-screenshots",
        action="store_true",
        default=False,
        help="Save an extra screenshot immediately after the reveal tap. Default: disabled to keep navigation fast.",
    )

    parser.add_argument(
        "--rename-decisions",
        default="RENAME_CANDIDATE",
        help="Comma-separated decisions that should be renamed.",
    )

    parser.add_argument(
        "--disable-templates",
        action="store_true",
        help="Disable all template matching and use fixed fallback coordinates.",
    )

    parser.add_argument(
        "--no-template-fallback",
        action="store_true",
        help="Fail instead of falling back to fixed coordinates if a template is missing or not matched.",
    )

    parser.add_argument(
        "--disable-startup-guards",
        action="store_true",
        help="Skip initial template visibility guard checks.",
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

    parser.add_argument(
        "--wait-after-pencil",
        dest="wait_after_pencil",
        type=float,
        default=1.2,
        help="Seconds to wait after pressing pencil. Default: 1.2.",
    )

    parser.add_argument(
        "--wait-after-focus-tap",
        type=float,
        default=0.8,
        help="Seconds to wait after tapping rename text field if keyboard is not detected.",
    )

    parser.add_argument(
        "--wait-before-appraise",
        type=float,
        default=2.0,
        help="Seconds to wait after pressing bars before pressing Appraise.",
    )

    parser.add_argument(
        "--wait-after-appraise",
        type=float,
        default=2.5,
        help="Seconds to wait after pressing Appraise.",
    )

    parser.add_argument(
        "--wait-after-middle-tap",
        type=float,
        default=1.0,
        help="Seconds to wait after middle-left tap.",
    )

    parser.add_argument(
        "--wait-after-next",
        type=float,
        default=3.0,
        help="Seconds to wait after final right-triangle tap.",
    )

    parser.add_argument(
        "--wait-between-triangle-taps",
        type=float,
        default=0.35,
        help="Seconds between the two right-triangle taps. Default: 0.35.",
    )

    parser.add_argument(
        "--wait-after-right-side-middle",
        type=float,
        default=0.8,
        help="Seconds after tapping center screen after triangle. Default: 0.8.",
    )

    parser.add_argument(
        "--wait-after-close",
        type=float,
        default=2.0,
        help="Seconds to wait after navigation settle.",
    )

    parser.add_argument(
        "--skip-pre-triangle-tap-first-navigation",
        action="store_true",
        default=True,
        help="Skip middle-left tap before right triangle on first navigation.",
    )

    parser.add_argument(
        "--no-skip-pre-triangle-tap-first-navigation",
        action="store_false",
        dest="skip_pre_triangle_tap_first_navigation",
        help="Do not skip middle-left tap before right triangle on first navigation.",
    )

    args = parser.parse_args()

    log_path = pathlib.Path(args.log_file)
    rows = read_scan_log(log_path)
    selected = select_rows(rows, start=args.start, count=args.count)
    selected_numbered = [
        (args.start + offset, row)
        for offset, row in enumerate(selected)
    ]
    if args.reverse_log_order:
        selected_numbered = list(reversed(selected_numbered))

    rename_decisions = {
        item.strip()
        for item in args.rename_decisions.split(",")
        if item.strip()
    }

    print("=" * 80)
    print("Mode:", "EXECUTE" if args.execute else "DRY RUN")
    print("Log file:", log_path)
    print("Total rows in log:", len(rows))
    print("Start row:", args.start)
    print("Rows selected:", len(selected_numbered))
    print("Rename to:", args.rename_to)
    print("Rename decisions:", sorted(rename_decisions))
    print("Template matching:", "disabled" if args.disable_templates else "enabled")
    print("Template fallback:", "disabled" if args.no_template_fallback else "enabled")
    print("Startup guards:", "disabled" if args.disable_startup_guards else ("enabled, waiting forever" if args.startup_guard_retries < 0 else "enabled"))
    print("Template directory:", TEMPLATE_DIR)
    print("Skip pre-triangle tap first navigation:", args.skip_pre_triangle_tap_first_navigation)
    print("Reverse log order:", args.reverse_log_order)
    print("Navigation direction:", args.navigation_direction)
    print("Triangle taps per navigation:", args.triangle_taps_per_navigation)
    print("Fixed triangle navigation:", getattr(args, "fixed_triangle_navigation", True))
    print("Reveal triangle before navigation:", getattr(args, "reveal_triangle_before_navigation", True))
    print("Triangle reveal retries:", getattr(args, "triangle_reveal_retries", 3))
    print("Triangle reveal tap:", getattr(args, "triangle_reveal_tap", "three_bar"))
    print("Wait before triangle reveal:", getattr(args, "wait_before_triangle_reveal", 1.0))
    print("Save triangle reveal screenshots:", getattr(args, "save_triangle_reveal_screenshots", False))
    print("=" * 80)

    print("\nIMPORTANT:")
    if args.reverse_log_order:
        print("Before running with --execute, manually put Pokémon GO on the LAST Pokémon")
        print("from the selected scan log rows, on the normal clean detail page.")
    else:
        print("Before running with --execute, manually put Pokémon GO on the FIRST Pokémon")
        print("from the selected scan log rows, on the normal clean detail page.")
    print("Templates should be under captures/templates/.\n")

    check_adb_device()

    if not args.disable_startup_guards:
        print("\nStartup guard for rename: checking that the clean Pokémon detail screen is visible...")
        require_templates_visible(
            names=["three_bar_menu"],
            row_number=0,
            retries=args.startup_guard_retries,
            wait_seconds=args.startup_guard_wait,
            disable_templates=args.disable_templates,
        )

    action_log_path = LOG_DIR / "rename_from_log_action_log.csv"
    write_header = not action_log_path.exists()

    with action_log_path.open("a", newline="", encoding="utf-8") as f:
        fieldnames = [
            "run_timestamp",
            "log_row_number",
            "iteration",
            "species",
            "decision",
            "reason",
            "max_pvp_percent",
            "renamed",
            "rename_to",
            "rename_source",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if write_header:
            writer.writeheader()

        navigation_index = 0

        for idx, (actual_log_row_number, row) in enumerate(selected_numbered, start=1):

            species = row.get("species") or ""
            decision = row.get("decision") or ""
            reason = row.get("reason") or ""
            max_pvp = row.get("max_pvp_percent") or ""

            print("\n" + "#" * 80)
            print(f"LOG ROW {actual_log_row_number} / SELECTED {idx}/{len(selected_numbered)}")
            print("#" * 80)
            print("Species:", species)
            print("Decision:", decision)
            print("Reason:", reason)
            print("Max PvP:", max_pvp)
            print("Log rename_to:", row.get("rename_to") or "")

            log_rename_to = (row.get("rename_to") or "").strip()
            should_rename = bool(log_rename_to) or decision in rename_decisions
            renamed = False
            chosen_rename_to = ""
            rename_source = ""

            if log_rename_to:
                chosen_rename_to = log_rename_to
                rename_source = "log_rename_to"
            elif decision in rename_decisions:
                chosen_rename_to = args.rename_to
                rename_source = "fallback_decision"

            if should_rename:
                print(f"Action: RENAME to {chosen_rename_to!r} ({rename_source})")
                rename_current_pokemon(
                    rename_to=chosen_rename_to,
                    execute=args.execute,
                    row_number=actual_log_row_number,
                    wait_after_pencil=args.wait_after_pencil,
                    wait_after_focus_tap=args.wait_after_focus_tap,
                    disable_templates=args.disable_templates,
                    no_template_fallback=args.no_template_fallback,
                )
                renamed = True
            else:
                print("Action: KEEP / SKIP RENAME")

            writer.writerow({
                "run_timestamp": time.strftime("%Y%m%d_%H%M%S"),
                "log_row_number": actual_log_row_number,
                "iteration": row.get("iteration"),
                "species": species,
                "decision": decision,
                "reason": reason,
                "max_pvp_percent": max_pvp,
                "renamed": renamed,
                "rename_to": chosen_rename_to if renamed else "",
                "rename_source": rename_source if renamed else "",
            })
            f.flush()

            if idx < len(selected_numbered):
                navigation_index += 1

                open_appraisal_and_go_next(
                    execute=args.execute,
                    row_number=actual_log_row_number,
                    navigation_index=navigation_index,
                    wait_before_appraise=args.wait_before_appraise,
                    wait_after_appraise=args.wait_after_appraise,
                    wait_after_middle_tap=args.wait_after_middle_tap,
                    wait_after_next=args.wait_after_next,
                    skip_pre_triangle_tap_first_navigation=args.skip_pre_triangle_tap_first_navigation,
                    wait_between_triangle_taps=args.wait_between_triangle_taps,
                    wait_after_right_side_middle=args.wait_after_right_side_middle,
                    disable_templates=args.disable_templates,
                    no_template_fallback=args.no_template_fallback,
                    navigation_direction=args.navigation_direction,
                    triangle_taps_per_navigation=args.triangle_taps_per_navigation,
                    fixed_triangle_navigation=getattr(args, "fixed_triangle_navigation", True),
                    wait_after_appraise_before_triangle_reveal=getattr(args, "wait_after_appraise_before_triangle_reveal", 1.0),
                    reveal_triangle_before_navigation=getattr(args, "reveal_triangle_before_navigation", True),
                    wait_before_triangle_reveal=getattr(args, "wait_before_triangle_reveal", 1.0),
                    wait_after_triangle_reveal=getattr(args, "wait_after_triangle_reveal", 1.5),
                    triangle_reveal_retries=getattr(args, "triangle_reveal_retries", 5),
                    triangle_reveal_tap=getattr(args, "triangle_reveal_tap", "three_bar"),
                    save_triangle_reveal_screenshots=getattr(args, "save_triangle_reveal_screenshots", False),
                )

                close_appraisal_to_clean_page(
                    execute=args.execute,
                    wait_after_close=args.wait_after_close,
                    row_number=actual_log_row_number,
                )

    print("\nDone.")
    print("Action log:")
    print(f"  xdg-open {action_log_path}")
    print("\nLatest template match debug screenshot:")
    print('  xdg-open "$(ls -t captures/screenshots/*match_debug*.png | head -1)"')
    print("\nLatest keyboard-check screenshot:")
    print('  xdg-open "$(ls -t captures/screenshots/*keyboard_check*.png | head -1)"')
    print("\nLatest after-close screenshot:")
    print('  xdg-open "$(ls -t captures/screenshots/*after_close_appraisal*.png | head -1)"')


if __name__ == "__main__":
    main()
