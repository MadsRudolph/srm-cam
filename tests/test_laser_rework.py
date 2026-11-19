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
    # As it ran then: before the edge of the field got passes of its own.
    from dataclasses import replace
    job = xtool.traces_job(art, (60.0, 60.0),
                           replace(xtool.FR4_TRACES_RECIPE, edge_passes=0))
    assert job.seconds == pytest.approx(48, abs=4)


# -- trenches that isolate nothing -----------------------------------------

def _pour_board():
    """40 x 30 board. A ground pour 0.5 mm in from the edge with: a mounting
    hole's empty clearance (r 2.5 at (5, 5)), a signal pad in its own
    clearance (r 1 in a 1.4 clearance at (20, 15)), and a ground pad that is
    part of the pour (no clearance, at (30, 15))."""
    from shapely.geometry import Point, box
    outline = box(0, 0, 40, 30)
    pour = (box(0.5, 0.5, 39.5, 29.5)
            .difference(Point(5, 5).buffer(2.5))
            .difference(Point(20, 15).buffer(1.4)))
    signal = Point(20, 15).buffer(1.0)
    copper = pour.union(signal)
    drills = [(5.0, 5.0, 3.2), (20.0, 15.0, 0.8), (30.0, 15.0, 0.8)]
    return xtool.traces_art(copper, outline, drills, side="top", mirror=False)


def _where(art, k):
    c = art.apertures[k].centroid
    return round(c.x, 1), round(c.y, 1)


def test_the_edge_and_the_mounting_hole_isolate_nothing_the_signal_pad_does():
    art = _pour_board()
    skip = xtool.needless_trenches(art)
    kept = set(range(len(art.apertures))) - skip
    from shapely.geometry import Point
    sig = [k for k, g in enumerate(art.apertures) if g.distance(Point(20, 15)) < 1.5]
    mount = [k for k, g in enumerate(art.apertures) if g.distance(Point(5, 5)) < 2.6]
    edge = [k for k, g in enumerate(art.apertures) if g.distance(art.outline.exterior) < 0.4]
    assert sig and set(sig) <= kept                 # the signal pad stays isolated
    assert mount and set(mount) <= skip
    assert edge and set(edge) <= skip


def test_thermal_relief_gaps_are_etched_but_the_mounting_ring_is_not():
    """A pad joined to the pour by four spokes is one piece of copper with the
    pour, so its gaps border only the pour. They make the relief: kept."""
    from shapely.geometry import Point, box
    outline = box(0, 0, 40, 30)
    pour = (box(0.5, 0.5, 39.5, 29.5)
            .difference(Point(5, 5).buffer(2.5))
            .difference(Point(20, 15).buffer(1.5)))
    pad = Point(20, 15).buffer(1.0)
    spokes = (box(18.5, 14.75, 21.5, 15.25).union(box(19.75, 13.5, 20.25, 16.5)))
    copper = pour.union(pad).union(spokes)
    art = xtool.traces_art(copper, outline, [(5.0, 5.0, 3.2), (20.0, 15.0, 0.8)],
                           side="top", mirror=False)
    skip = xtool.needless_trenches(art)
    relief = [k for k, g in enumerate(art.apertures) if 0.6 < g.distance(Point(20, 15)) < 1.8 and g.area > 0.3]      # the four gaps
    mount = [k for k, g in enumerate(art.apertures) if g.distance(Point(5, 5)) < 2.6]
    assert len(relief) == 4 and not (set(relief) & skip)
    assert mount and set(mount) <= skip


def test_a_board_without_a_pour_skips_nothing():
    from shapely.geometry import Point, box
    copper = Point(10, 10).buffer(1).union(Point(30, 10).buffer(1))
    art = xtool.traces_art(copper, box(0, 0, 40, 20), [], side="top", mirror=False)
    assert xtool.needless_trenches(art) == set()


def test_the_page_skips_them_and_runs_the_rest(qt_app, monkeypatch):
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "skip"))
    art = _pour_board()
    d = sl.StencilLaserDialog(art)
    try:
        d.skip_auto.setChecked(True)
        d._find_skips(force=True)
        auto = set(d.skipped)
        assert auto == xtool.needless_trenches(d.base_art) and auto
        assert not d.skip_note.isHidden()
        keep = d._traces_only()
        assert keep == set(range(len(d.art.apertures))) - auto
        whole = xtool.traces_job(d.art, d.origin(), d._run_recipe()).seconds
        part = xtool.traces_job(d.art, d.origin(), d._run_recipe(), only=keep).seconds
        assert part < whole
        # Skip mode: a click on the signal pad's trench leaves it out too, and back
        from PySide6.QtCore import QPointF, QRectF
        d.mode.set_current("skip")
        d._set_mode("skip")
        ox, oy = d.origin()
        _, h = d.art.size
        at = QPointF(ox + 20 + 1.1, oy + (h - 15))      # just outside the pad
        d._boxed(QRectF(at, at), False)
        assert len(d.skipped) == len(auto) + 1
        d._boxed(QRectF(at, at), False)
        assert d.skipped == auto
        d.skip_auto.setChecked(False)
        assert d.skipped == set() and d._traces_only() is None
        assert d.skip_auto.text() == "Auto-skip: off" and not d.skip_auto.isHidden()
    finally:
        d.close()


def test_skip_mode_is_only_for_traces(qt_app, monkeypatch):
    from shapely.geometry import box
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "skip2"))
    d = sl.StencilLaserDialog(xtool.LaserArt(kind="mask", outline=box(0, 0, 20, 20),
                                             apertures=[box(5, 5, 8, 8)]))
    try:
        d._set_mode("skip")
        assert d._mode != "skip" and d.skip_auto.isHidden()
    finally:
        d.close()
