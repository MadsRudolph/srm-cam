"""The corner bracket: screwed into the spoilboard's holes, nowhere else."""
import pytest

from gerber2rml.engine import bracket as br
from gerber2rml.engine import spoilboard

BED = (203.2, 152.4)


def test_the_default_is_the_measured_corner():
    # Read with the bit over the printed bracket's corner, 2026-11-03. Corner
    # screw in hole (19, 12).
    assert br.DEFAULT.corner == "back-right"
    assert br.DEFAULT.inside_corner() == pytest.approx((191.79, 128.43))
    assert br.fits(br.DEFAULT, bed=BED)
    # The sheet the lab stocks stays on the bed from there.
    x, y = br.DEFAULT.inside_corner()
    assert x - 160 >= 0 and y - 100 >= 0


def test_the_old_position_is_still_the_one_it_measured():
    assert br.OLD_DEFAULT.inside_corner() == pytest.approx((22.49, 129.47))


def test_it_moves_a_whole_hole_at_a_time():
    x0, y0 = br.OLD_DEFAULT.inside_corner()
    x1, y1 = br.Bracket(4, 10, "back-left").inside_corner()
    assert (x1 - x0, y1 - y0) == pytest.approx((30.0, -20.0))


def test_a_drop_snaps_to_the_nearest_position_it_can_be_screwed_into():
    assert br.snap(190.0, 130.0, bed=BED) == br.DEFAULT
    b = br.snap(26.0, 127.0, "back-left", bed=BED)
    assert b == br.OLD_DEFAULT
    b = br.snap(40.0, 120.0, "back-left", bed=BED)
    assert b.inside_corner() == pytest.approx((42.49, 119.47))


def test_every_screw_is_in_a_hole_of_the_plate():
    grid = spoilboard.measured_grid()
    for c in ("back-left", "front-left", "back-right", "front-right"):
        b = br.snap(100, 75, c, bed=BED)
        assert b is not None and b.corner == c
        for i, j in b.screws():
            assert 0 <= i < grid.nx and 0 <= j < grid.ny
    # Off the back of the plate there are no holes: it snaps back onto it.
    far = br.snap(191.79, 400.0, bed=BED)
    assert far.j == 12


def test_the_l_wraps_the_corner_it_holds():
    # Back-right: the bars are behind and right of the stock's corner.
    x, y = br.DEFAULT.inside_corner()
    xs = [p[0] for p in br.DEFAULT.outline()]
    ys = [p[1] for p in br.DEFAULT.outline()]
    assert max(xs) == pytest.approx(x + br.BAR_W)
    assert max(ys) == pytest.approx(y + br.BAR_W)
    # Front-right is the same part turned: in front and to the right.
    b = br.snap(150, 30, "front-right", bed=BED)
    x, y = b.inside_corner()
    assert max(p[0] for p in b.outline()) == pytest.approx(x + br.BAR_W)
    assert min(p[1] for p in b.outline()) == pytest.approx(y - br.BAR_W)


def test_the_drawn_part_has_the_tongue_over_the_stock():
    x, y = br.DEFAULT.inside_corner()
    pts = br.DEFAULT.outline()
    assert (x - 26.0, y - 4.0) in [pytest.approx(p) for p in pts]
    assert (x - 2.5, y - 4.0) in [pytest.approx(p) for p in pts]


def test_the_keepout_covers_the_tongue_with_its_clearance():
    x, y = br.DEFAULT.inside_corner()
    assert br.DEFAULT.keepout() == pytest.approx(
        (x - 26.5, y - 4.5, x - 2.0, y))


def test_saved_text_round_trips():
    assert br.from_text(br.to_text(br.Bracket(3, 12, "back-right"))) == \
        br.Bracket(3, 12, "back-right")
    assert br.from_text("22.49,129.47,back-left") is None
    assert br.from_text("") is None


def test_the_part_has_six_holes_along_each_arm():
    # The corner hole and five more at the pitch, on both arms.
    assert br.DEFAULT.screws() == [(19, 12), (14, 12), (19, 7)]
    assert br.ARM_X == br.ARM_Y

def test_a_machine_that_only_ever_had_the_old_default_gets_the_new_one():
    from gerber2rml.gui2 import autorun, workspace
    workspace.set_setting("autorun/bracket", "1,12,back-left")
    assert autorun.saved_bracket() == br.DEFAULT
    # A position someone chose stays theirs.
    workspace.set_setting("autorun/bracket", "3,12,back-left")
    assert autorun.saved_bracket() == br.Bracket(3, 12, "back-left")
