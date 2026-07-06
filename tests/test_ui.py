from pogo_auto.ui import DEFAULT_SCREEN, Point

def test_fixed_left_triangle_reference():
    p = DEFAULT_SCREEN.fixed_triangle("left", 1008, 2244)
    assert p == Point(39, 1757)
