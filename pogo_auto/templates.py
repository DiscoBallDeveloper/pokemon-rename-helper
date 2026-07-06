from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class TemplateMatch:
    name: str
    score: float
    center_x: int
    center_y: int
    rect: tuple[int, int, int, int]


def match_template(
    screenshot_path: Path,
    template_path: Path,
    name: str,
    threshold: float = 0.65,
    search_region: tuple[int, int, int, int] | None = None,
) -> TemplateMatch | None:
    img = cv2.imread(str(screenshot_path))
    tmpl = cv2.imread(str(template_path))
    if img is None:
        raise RuntimeError(f"Could not read screenshot: {screenshot_path}")
    if tmpl is None:
        raise RuntimeError(f"Could not read template: {template_path}")

    x_offset = 0
    y_offset = 0
    if search_region is not None:
        x, y, w, h = search_region
        img = img[y:y+h, x:x+w]
        x_offset = x
        y_offset = y

    result = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None

    th, tw = tmpl.shape[:2]
    x = x_offset + max_loc[0]
    y = y_offset + max_loc[1]
    return TemplateMatch(
        name=name,
        score=float(max_val),
        center_x=x + tw // 2,
        center_y=y + th // 2,
        rect=(x, y, tw, th),
    )


def lower_left_triangle_region(width: int, height: int) -> tuple[int, int, int, int]:
    return (0, int(height * 0.58), int(width * 0.18), int(height * 0.32))


def lower_right_triangle_region(width: int, height: int) -> tuple[int, int, int, int]:
    return (int(width * 0.82), int(height * 0.58), int(width * 0.18), int(height * 0.32))
