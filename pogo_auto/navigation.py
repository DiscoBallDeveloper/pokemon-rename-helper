from __future__ import annotations

import time
from dataclasses import dataclass

from .adb import AdbTarget
from .ui import DEFAULT_SCREEN, Point


@dataclass(frozen=True)
class Swipe:
    start: Point
    end: Point
    duration_ms: int


def fixed_triangle_point(direction: str, width: int, height: int) -> Point:
    """Return the scaled fixed appraisal navigation triangle coordinate."""
    return DEFAULT_SCREEN.fixed_triangle(direction, width, height)


def triangle_level_swipe(
    direction: str,
    width: int,
    height: int,
    duration_ms: int = 280,
    edge_inset_ratio: float = 0.035,
) -> Swipe:
    """Build a scaled swipe at the appraisal-arrow level.

    ``right`` means next Pokémon, so the finger moves right-to-left; ``left``
    means previous Pokémon and moves left-to-right.
    """
    if direction not in {"left", "right"}:
        raise ValueError(f"Unsupported navigation direction: {direction!r}")
    if duration_ms <= 0:
        raise ValueError("duration_ms must be positive")

    left = fixed_triangle_point("left", width, height)
    right = fixed_triangle_point("right", width, height)
    y = round((left.y + right.y) / 2)
    inset = max(8, round(width * edge_inset_ratio))
    left_x = max(inset, left.x)
    right_x = min(width - 1 - inset, right.x)
    if right_x <= left_x:
        left_x, right_x = round(width * 0.08), round(width * 0.92)

    if direction == "right":
        return Swipe(Point(right_x, y), Point(left_x, y), duration_ms)
    return Swipe(Point(left_x, y), Point(right_x, y), duration_ms)


def swipe_triangle_level(
    target: AdbTarget,
    direction: str,
    width: int,
    height: int,
    duration_ms: int = 280,
) -> Swipe:
    """Send a triangle-level swipe through the shared ADB abstraction."""
    swipe = triangle_level_swipe(direction, width, height, duration_ms)
    target.input_swipe(
        swipe.start.x, swipe.start.y, swipe.end.x, swipe.end.y, swipe.duration_ms
    )
    return swipe


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
