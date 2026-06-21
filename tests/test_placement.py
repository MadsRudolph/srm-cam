from pathlib import Path
from gerber2rml.loader import load_board, place_in_positive_quadrant

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


def test_places_board_lower_left_at_margin():
    board = place_in_positive_quadrant(load_board(FIXT, mirror=True), margin=2.0)
    # The outline (board edge) lower-left must land exactly at (margin, margin).
    # Copper sits inset from the board edge, so we check the outline bounds.
    minx, miny, _, _ = board.outline.bounds
    assert abs(minx - 2.0) < 1e-6
    assert abs(miny - 2.0) < 1e-6


def test_places_holes_too():
    raw = load_board(FIXT, mirror=True)
    placed = place_in_positive_quadrant(raw, margin=2.0)
    assert len(placed.holes) == len(raw.holes)
    assert all(x > 0 and y > 0 for (x, y, _d) in placed.holes)
