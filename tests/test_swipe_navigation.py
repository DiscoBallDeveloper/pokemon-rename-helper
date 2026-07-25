from pogo_auto.navigation import triangle_level_swipe


def test_next_pokemon_swipes_right_to_left():
    swipe = triangle_level_swipe("right", 1008, 2244)
    assert swipe.start.x > swipe.end.x
    assert swipe.start.y == swipe.end.y
    assert 1650 <= swipe.start.y <= 1900


def test_previous_pokemon_swipes_left_to_right():
    swipe = triangle_level_swipe("left", 1008, 2244)
    assert swipe.start.x < swipe.end.x
    assert swipe.start.y == swipe.end.y


def test_coordinates_scale_to_screen():
    swipe = triangle_level_swipe("right", 1440, 3200)
    assert 0 <= swipe.end.x < swipe.start.x < 1440
    assert 0 <= swipe.start.y < 3200
