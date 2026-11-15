"""The board's own mounting holes as reference holes: which ones will do
(engine/mountfid.py). Pure."""
from gerber2rml.engine import mountfid

BOX = (0.0, 0.0, 100.0, 60.0)
CORNERS = [(4, 4, 3.2), (96, 4, 3.2), (96, 56, 3.2), (4, 56, 3.2)]


def test_four_corner_mounting_holes_are_all_used():
    holes = CORNERS + [(50, 30, 0.8), (20, 30, 1.0)]
    assert sorted(mountfid.pick(holes, BOX)) == sorted(CORNERS)


def test_holes_too_small_for_the_bit_are_not_reference_holes():
    """The bit plus 0.8 mm: room to drop in with runout."""
    assert mountfid.min_diameter(0.8) == 1.6
    holes = [(4, 4, 1.5), (96, 56, 1.5)]
    assert mountfid.pick(holes, BOX, bit_mm=0.8) == []
    assert len(mountfid.pick(holes, BOX, bit_mm=0.6)) == 2


def test_holes_too_wide_to_take_a_height_beside_are_left_out():
    assert mountfid.pick([(4, 4, 6.0), (96, 56, 6.0)], BOX) == []


def test_two_holes_side_by_side_are_not_enough():
    """The fit turns the whole face about them: 10 mm apart on a 100 mm
    board would make a hair at the holes a visible error at the far edge."""
    assert mountfid.pick([(45, 30, 3.2), (55, 30, 3.2)], BOX) == []


def test_two_far_apart_will_do():
    got = mountfid.pick([(4, 4, 3.2), (96, 56, 3.2), (50, 30, 0.9)], BOX)
    assert sorted(got) == [(4, 4, 3.2), (96, 56, 3.2)]


def test_sizes_are_not_mixed_and_more_corners_win():
    holes = CORNERS + [(10, 10, 2.0), (90, 50, 2.0)]
    assert {d for _x, _y, d in mountfid.pick(holes, BOX)} == {3.2}


def test_a_board_without_holes_has_none():
    assert mountfid.pick([], BOX) == []
