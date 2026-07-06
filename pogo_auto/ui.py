from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class ScreenModel:
    width: int = 1008
    height: int = 2244

    three_bar_menu: Point = Point(866, 2105)
    appraise: Point = Point(680, 1743)
    rename_pencil: Point = Point(669, 924)
    rename_ok: Point = Point(504, 1207)

    left_triangle_reference: Point = Point(39, 1757)
    right_triangle_reference: Point = Point(970, 1757)

    center: Point = Point(504, 1122)

    def scale_point(self, point: Point, actual_width: int, actual_height: int) -> Point:
        return Point(
            x=int(actual_width * (point.x / self.width)),
            y=int(actual_height * (point.y / self.height)),
        )

    def fixed_triangle(self, direction: str, actual_width: int, actual_height: int) -> Point:
        if direction == "left":
            return self.scale_point(self.left_triangle_reference, actual_width, actual_height)
        if direction == "right":
            return self.scale_point(self.right_triangle_reference, actual_width, actual_height)
        raise ValueError(f"Unsupported triangle direction: {direction!r}")


DEFAULT_SCREEN = ScreenModel()
