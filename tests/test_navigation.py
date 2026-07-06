from pogo_auto.navigation import fixed_triangle_point
from pogo_auto.ui import Point

def test_fixed_triangle_points():
    assert fixed_triangle_point("left", 1008, 2244) == Point(39, 1757)
    assert fixed_triangle_point("right", 1008, 2244) == Point(970, 1757)
