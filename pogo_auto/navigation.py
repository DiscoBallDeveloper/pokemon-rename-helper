from __future__ import annotations

import time

from .adb import AdbTarget
from .ui import DEFAULT_SCREEN, Point


def fixed_triangle_point(direction: str, width: int, height: int) -> Point:
    """Return the scaled fixed appraisal navigation triangle coordinate."""
    return DEFAULT_SCREEN.fixed_triangle(direction, width, height)


def reveal_triangles(target: AdbTarget, width: int, height: int) -> Point:
    """Tap the lower-right 3-bar/menu area to reveal appraisal triangles."""
    point = DEFAULT_SCREEN.scale_point(DEFAULT_SCREEN.three_bar_menu, width, height)
    target.input_tap(point.x, point.y)
    return point


def tap_fixed_triangle(target: AdbTarget, direction: str, width: int, height: int) -> Point:
    point = fixed_triangle_point(direction, width, height)
    target.input_tap(point.x, point.y)
    return point


def reveal_and_tap_fixed_triangle(
    target: AdbTarget,
    direction: str,
    wait_before_reveal: float = 1.5,
    wait_after_reveal: float = 2.0,
) -> Point:
    width, height = target.wm_size()

    if wait_before_reveal > 0:
        time.sleep(wait_before_reveal)

    reveal_triangles(target, width, height)

    if wait_after_reveal > 0:
        time.sleep(wait_after_reveal)

    return tap_fixed_triangle(target, direction, width, height)
