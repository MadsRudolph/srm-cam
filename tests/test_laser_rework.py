"""Rework on the laser: boxes on the bed, the traces again only inside them."""
import pytest
from shapely.geometry import Point, box

from gerber2rml.engine import xtool

ORIGIN = (50.0, 50.0)          # the outline's top-left corner on the bed


def _art():
    # Two pads far apart on a 40 x 20 board: (5, 10) and (35, 10), Y up.
    copper = Point(5, 10).buffer(1).union(Point(35, 10).buffer(1))
    return xtool.traces_art(copper, box(0, 0, 40, 20), [], side="top",
                            mirror=False)


def _bed(x, y, h=20.0):
    """Artwork point to the bed, as to_bed does."""
    return ORIGIN[0] + x, ORIGIN[1] + (h - y)


def _rings(job):
    return [p for z in job.zone_paths for p in z]


def test_a_box_keeps_only_the_isolation_inside_it():
    art = _art()
    whole = xtool.traces_job(art, ORIGIN, xtool.DEFAULT_TRACES_RECIPE)
    x, y = _bed(5, 10)
    job = xtool.traces_job(art, ORIGIN, xtool.DEFAULT_TRACES_RECIPE,
                           boxes=[(x - 3, y - 3, x + 3, y + 3)])
    pts = [q for r in _rings(job) for q in r]
    assert pts and all(abs(px - x) <= 3 + 1e-6 and abs(py - y) <= 3 + 1e-6
                       for px, py in pts)
    assert job.seconds < whole.seconds
    assert len(_rings(job)) == xtool.DEFAULT_TRACES_RECIPE.offsets


def test_a_box_cuts_a_ring_to_its_edge():
    art = _art()
    x, y = _bed(5, 10)
    job = xtool.traces_job(art, ORIGIN, xtool.DEFAULT_TRACES_RECIPE,
                           boxes=[(x, y - 5, x + 5, y + 5)])     # right half
    pts = [q for r in _rings(job) for q in r]
    assert pts and min(px for px, _ in pts) >= x - 1e-6


def test_boxes_drawn_from_any_corner_and_several_at_once():
    art = _art()
    (ax, ay), (bx, by) = _bed(5, 10), _bed(35, 10)
    job = xtool.traces_job(art, ORIGIN, xtool.DEFAULT_TRACES_RECIPE,
                           boxes=[(ax + 3, ay + 3, ax - 3, ay - 3),
                                  (bx - 3, by - 3, bx + 3, by + 3)])
    xs = [px for r in _rings(job) for px, _ in r]
    assert min(xs) < ax + 3 and max(xs) > bx - 3


def test_the_rework_does_not_score_the_outline_again():
    art = _art()
    x, y = _bed(5, 10)
    r = xtool.DEFAULT_TRACES_RECIPE
    from dataclasses import replace
    job = xtool.traces_job(art, ORIGIN, replace(r, mark_outline=True),
                           boxes=[(x - 3, y - 3, x + 3, y + 3)])
    assert all(t[2] != -1 for t in job.timeline)       # -1 is the outline


def test_a_box_over_nothing_says_so():
    x, y = _bed(20, 10)                       # between the pads: no copper
    with pytest.raises(ValueError, match="rework boxes"):
        xtool.traces_job(_art(), ORIGIN, xtool.DEFAULT_TRACES_RECIPE,
                         boxes=[(x - 1, y - 1, x + 1, y + 1)])


def test_rework_follows_the_job_where_it_sits():
    art = _art()
    moved = (60.0, 70.0)
    x, y = moved[0] + 5, moved[1] + 10          # pad (5, 10) with the job moved
    job = xtool.traces_job(art, moved, xtool.DEFAULT_TRACES_RECIPE,
                           boxes=[(x - 3, y - 3, x + 3, y + 3)])
    assert _rings(job)


# -- on the page ------------------------------------------------------------

@pytest.fixture
def page(qt_app, monkeypatch):
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "rework"))
    d = sl.StencilLaserDialog(_art())
    d.x.setValue(ORIGIN[0])
    d.y.setValue(ORIGIN[1])
    yield d
    d.close()


def test_boxes_are_drawn_and_clicked_away(page):
    from PySide6.QtCore import QPointF, QRectF
    page.mode.set_current("rework")
    page._set_mode("rework")
    x, y = _bed(5, 10)
    page._boxed(QRectF(QPointF(x - 3, y - 3), QPointF(x + 3, y + 3)), False)
    assert len(page.rework_boxes) == 1 and page.rework_btn.isEnabled()
    assert "1 box" in page.rework_btn.text()
    page._boxed(QRectF(QPointF(x, y), QPointF(x, y)), False)     # a click inside
    assert page.rework_boxes == [] and not page.rework_btn.isEnabled()


def test_rework_runs_only_the_boxes_with_its_own_passes(page, monkeypatch):
    from PySide6.QtCore import QPointF, QRectF
    page._set_mode("rework")
    x, y = _bed(5, 10)
    page._boxed(QRectF(QPointF(x - 3, y - 3), QPointF(x + 3, y + 3)), False)
    page.rework_passes.setValue(4)
    started = {}
    monkeypatch.setattr(page, "_start", lambda work, msg, done: started.update(msg=msg))
    page.rework()
    assert page._job.passes == 4
    assert "1 box" in started["msg"]
    pts = [q for z in page._job.zone_paths for r in z for q in r]
    assert all(abs(px - x) <= 3 + 1e-6 for px, _ in pts)


def test_rework_is_only_for_traces(page):
    assert not page.rework_section.isHidden()
    page.kind = "mask"
    page._sync_rework()
    assert page.rework_section.isHidden()


# -- the camera calibration on a blank (no drilled holes) -------------------

def test_marks_go_on_the_isolation_of_a_blank():
    art = _art()                                    # no drills
    plan = xtool.proof_on_isolation(art, ORIGIN)
    assert plan.where == "isolation" and len(plan.marks) >= 2
    # Far apart: one round each pad, 30 mm from each other.
    xs = sorted(m.centroid.x for m in plan.marks)
    assert xs[-1] - xs[0] > 20


def test_waste_marks_go_by_the_corners_of_a_blank():
    plan = xtool.proof_in_waste(_art(), ORIGIN)
    assert plan.where == "waste" and len(plan.marks) >= 2


def test_the_calibration_is_offered_on_a_blank(page):
    assert not page.proof_btn.isHidden()
    assert page.proof_btn.text() == "Calibrate the camera"
    assert "blank" in page.proof_hint.text()


# -- how long a job takes: measured on the machine --------------------------

def test_long_segments_go_at_the_speed_short_ones_no_faster_than_the_controller():
    long_line = [[(0.0, 0.0), (100.0, 0.0)]]
    assert xtool._draw_seconds(long_line, 1000.0) == pytest.approx(
        0.1 + xtool.JUMP_S)
    # 1000 segments of 0.01 mm: 10 mm, but each takes the controller's minimum
    tiny = [[(i * 0.01, 0.0) for i in range(1001)]]
    assert xtool._draw_seconds(tiny, 1000.0) == pytest.approx(
        1000 * xtool.SEGMENT_MIN_S + xtool.JUMP_S)


def test_every_path_costs_a_jump():
    one = xtool._draw_seconds([[(0, 0), (10, 0)]], 1000.0)
    two = xtool._draw_seconds([[(0, 0), (10, 0)], [(10, 0), (20, 0)]], 1000.0)
    assert two - 2 * one == pytest.approx(0.0, abs=1e-9)     # no distance between
    far = xtool._draw_seconds([[(0, 0), (10, 0)], [(40, 0), (50, 0)]], 1000.0)
    assert far - two == pytest.approx(30 / xtool.JUMP_SPEED)


def test_the_align_test_board_is_estimated_as_it_ran():
    """examples/laser_align_test with the proven FR4 recipe ran 48 s at the
    machine; the old estimate (cutting length over speed) said 24 s."""
    from pathlib import Path
    from gerber2rml.gui2.laser_app import job_builder
    board = Path(__file__).resolve().parent.parent / "examples" / "laser_align_test"
    art = job_builder(board)("traces", side="top")
    job = xtool.traces_job(art, (60.0, 60.0), xtool.FR4_TRACES_RECIPE)
    assert job.seconds == pytest.approx(48, abs=4)
