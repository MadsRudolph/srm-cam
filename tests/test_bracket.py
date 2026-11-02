"""The corner bracket: screwed into the spoilboard's holes, nowhere else."""
import pytest

from gerber2rml.engine import bracket as br
from gerber2rml.engine import spoilboard

BED = (203.2, 152.4)


def test_the_default_is_the_measured_corner():
    # Measured with the bit, 2026-11-02, corner screw in hole (1, 12).
    assert br.DEFAULT.inside_corner() == pytest.approx((22.49, 129.47))
    assert br.fits(br.DEFAULT, bed=BED)


def test_it_moves_a_whole_hole_at_a_time():
    x0, y0 = br.DEFAULT.inside_corner()
    x1, y1 = br.Bracket(4, 10).inside_corner()
    assert (x1 - x0, y1 - y0) == pytest.approx((30.0, -20.0))


def test_a_drop_snaps_to_the_nearest_position_it_can_be_screwed_into():
    b = br.snap(26.0, 127.0, bed=BED)
    assert b == br.Bracket(1, 12)
    b = br.snap(40.0, 120.0, bed=BED)
    assert b.inside_corner() == pytest.approx((42.49, 119.47))


def test_every_screw_is_in_a_hole_of_the_plate():
    grid = spoilboard.measured_grid()
    for c in ("back-left", "front-left", "back-right", "front-right"):
        b = br.snap(100, 75, c, bed=BED)
        assert b is not None and b.corner == c
        for i, j in b.screws():
            assert 0 <= i < grid.nx and 0 <= j < grid.ny
    # Off the back of the plate there are no holes: it snaps back onto it.
    far = br.snap(22.49, 400.0, bed=BED)
    assert far.j == 12


def test_the_l_wraps_the_corner_it_holds():
    # Back-left: the bars are behind and left of the stock's corner.
    x, y = br.DEFAULT.inside_corner()
    xs = [p[0] for p in br.DEFAULT.outline()]
    ys = [p[1] for p in br.DEFAULT.outline()]
    assert min(xs) == pytest.approx(x - br.BAR_W)
    assert max(ys) == pytest.approx(y + br.BAR_W)
    # Front-right is the same part turned: in front and to the right.
    b = br.snap(150, 30, "front-right", bed=BED)
    x, y = b.inside_corner()
    assert max(p[0] for p in b.outline()) == pytest.approx(x + br.BAR_W)
    assert min(p[1] for p in b.outline()) == pytest.approx(y - br.BAR_W)


def test_saved_text_round_trips():
    assert br.from_text(br.to_text(br.Bracket(3, 12, "back-right"))) == \
        br.Bracket(3, 12, "back-right")
    assert br.from_text("22.49,129.47,back-left") is None
    assert br.from_text("") is None
