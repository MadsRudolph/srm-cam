"""The solder mask drawn as rings pad by pad instead of a hatch swept across
the whole board (2026-11-22, the analog synth's power board: the hatch spent
most of its four minutes jumping between pads)."""
from pathlib import Path

import pytest
from shapely.geometry import LineString, box
from shapely.affinity import translate
from shapely.ops import unary_union

from gerber2rml.engine import soldermask, xtool

FIX = Path(__file__).parent / "fixtures"


def test_rings_cover_a_square_pad_corners_and_all():
    pad = box(10, 10, 11.8, 11.8)
    r = xtool.CONCENTRIC_REMOVE_MASK
    paths = xtool.concentric([pad], r.interval)
    burnt = unary_union([LineString(p).buffer(r.interval * 0.75) for p in paths])
    assert pad.difference(burnt).area < 1e-3          # nothing left inside
    assert burnt.difference(pad.buffer(r.interval)).area < 1e-3   # nor outside
    first = paths[0]
    assert max(x for x, _ in first) == pytest.approx(11.8 - r.interval / 2, abs=1e-6)
    assert all(LineString(p).is_ring for p in paths)


def test_every_other_pass_sits_half_a_step_in():
    pad = box(0, 0, 2, 2)
    a = xtool.concentric([pad], 0.1)[0]
    b = xtool.concentric([pad], 0.1, phase=0.05)[0]
    assert max(x for x, _ in a) - max(x for x, _ in b) == pytest.approx(0.05)


def test_rings_go_pad_by_pad_and_are_quicker_than_the_hatch():
    art = soldermask.build_mask(FIX / "mosfet_test", mirror=True)
    pads = [translate(o, 40, 40) for o in art.openings]
    hatch = xtool.fill_job(pads, [], xtool.SPHAWES_REMOVE_MASK)
    rings = xtool.fill_job(pads, [], xtool.CONCENTRIC_REMOVE_MASK)
    assert rings.seconds < hatch.seconds
    assert (rings.passes, hatch.passes) == (4, 6)
    assert "S400F48000" in rings.text and rings.text.count("G0") > len(pads)


def test_the_page_offers_the_rings_for_the_mask(qt_app, monkeypatch):
    from gerber2rml.gui2 import stencil_laser as sl
    from gerber2rml.gui2.window import MainWindow
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "mask-rings"))
    w = MainWindow()
    try:
        w.load_folder(str(FIX / "mosfet_test"))
        w.action_traces_laser()
        d = w.laser_view
        d.switch_kind("mask")
        assert not d.fill_pattern_field.isHidden()
        d.preset.setCurrentText("RemoveSolderMask · concentric rings")
        assert d.recipe().pattern == "concentric"
        assert d.cross.isHidden()
        assert "Concentric rings" in d.recipe_lbl.text()
        d.fill_pattern.setCurrentIndex(d.fill_pattern.findData("hatch"))
        assert d.recipe().pattern == "hatch" and not d.cross.isHidden()
        d.switch_kind("traces")
        assert d.fill_pattern_field.isHidden()
        d.close()
    finally:
        w.close()


def test_the_blue_diode_frames_chosen_pads_outlines_fast():
    from shapely.geometry import Point
    pads = [box(50, 50, 52, 52), Point(80, 60).buffer(0.9)]
    text, secs, power, rate = xtool.show_job(pads)
    assert "G21" in text and "G22" not in text           # the blue diode, not the fiber
    assert 15 < secs < 25 and power == xtool.SHOW_POWER_RANGE[0]
    assert rate > 40                                     # two pads: steady
    assert text.count("G0X") == 1                        # no jumps, dark links
    assert "S0F" in text
    assert len(xtool.few_corners(pads[1])) - 1 == xtool.SHOW_CORNERS
    assert len(xtool.few_corners(pads[0])) == 5          # a square stays one
    assert xtool.show_power(800) == xtool.SHOW_POWER_RANGE[1]
    with pytest.raises(ValueError):
        xtool.show_job([])


def test_selected_pads_make_the_show_button_show_them(qt_app, monkeypatch):
    from gerber2rml.gui2 import stencil_laser as sl
    from gerber2rml.gui2.window import MainWindow
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "mask-show"))
    w = MainWindow()
    try:
        w.load_folder(str(FIX / "mosfet_test"))
        w.action_traces_laser()
        d = w.laser_view
        d.switch_kind("mask")
        assert d.trace_btn.text() == "Show where"
        d.selected.update({0, 1})
        d._paint(estimate=False)
        assert d.trace_btn.text() == "Show 2 in blue"
        sent = []

        class Fake:
            def frame(self, text):
                sent.append(text)

            def wait(self, *_a, **_k):
                return "P_IDLE"
        d.laser = Fake()
        monkeypatch.setattr(d, "_start", lambda work, _msg, done: done(work(None)))
        d.trace()
        assert sent and "G21" in sent[0] and sent[0].count("G1X") >= 20 and "S0F" in sent[0]
        d.close()
    finally:
        w.close()


def _bed_photos(pads, holes, px=8, size=60):
    """A green board before, and after with ``pads`` burnt bright, each over
    its dark hole (x, y, d) - as the camera sees a test fire."""
    import numpy as np
    from shapely.geometry import Point
    before = np.zeros((size * px, size * px, 3), np.uint8)
    before[..., 1] = 160
    yy, xx = np.mgrid[0:size * px, 0:size * px] / px
    after = before.copy()
    for p in pads:
        x0, y0, x1, y1 = p.bounds
        m = (xx >= x0) & (xx <= x1) & (yy >= y0) & (yy <= y1)
        after[m] = (230, 200, 180)
    for x, y, d in holes:
        m = (xx - x) ** 2 + (yy - y) ** 2 <= (d / 2) ** 2
        before[m] = after[m] = (20, 30, 40)
    return before, after


def test_test_openings_show_how_far_off_the_job_is_and_which_way():
    """Burnt openings 0.5 mm toward the front of their holes, as on the
    analog synth: the fit says move 0.5 mm back, no turn."""
    from gerber2rml.engine import xtool_camera as cam
    holes = [(10, 10, 0.8), (50, 12, 0.8), (30, 45, 1.0)]
    pads = [box(x - 1, y + 0.5 - 1, x + 1, y + 0.5 + 1) for x, y, _d in holes]
    before, after = _bed_photos(pads, holes)
    fit = cam.fit_test_openings(before, after, 8, [
        (p, (p.centroid.x, p.centroid.y, d)) for p, (_x, _y, d) in zip(pads, holes)])
    assert len(fit.offsets) == 3
    assert fit.dx == pytest.approx(0, abs=0.08)
    assert fit.dy == pytest.approx(-0.5, abs=0.08)
    assert abs(fit.turn) < 0.1


def test_test_openings_find_a_turn_when_spread_out():
    import math
    from gerber2rml.engine import xtool_camera as cam
    holes = [(8, 30, 0.8), (52, 30, 0.8), (30, 10, 0.8), (30, 50, 0.8)]
    c, t = (30, 30), math.radians(-0.6)       # drawn turned 0.6 degrees off
    pads = []
    for x, y, _d in holes:
        dx, dy = x - c[0], y - c[1]
        px, py = (c[0] + dx * math.cos(t) - dy * math.sin(t),
                  c[1] + dx * math.sin(t) + dy * math.cos(t))
        pads.append(box(px - 1, py - 1, px + 1, py + 1))
    before, after = _bed_photos(pads, holes)
    fit = cam.fit_test_openings(before, after, 8, [
        (p, (p.centroid.x, p.centroid.y, d)) for p, (_x, _y, d) in zip(pads, holes)])
    assert fit.turn == pytest.approx(0.6, abs=0.1)
    assert math.hypot(fit.dx, fit.dy) < 0.1


def test_a_hole_off_its_pad_is_left_out_of_the_fit():
    from gerber2rml.engine import xtool_camera as cam
    holes = [(10, 10, 0.8), (50, 12, 0.8), (30, 45, 1.0), (12, 40, 0.8)]
    pads = [box(x - 1, y + 0.5 - 1, x + 1, y + 0.5 + 1) for x, y, _d in holes]
    holes[2] = (30.6, 45, 1.0)                 # the mill put this one 0.6 mm off
    before, after = _bed_photos(pads, holes)
    fit = cam.fit_test_openings(before, after, 8, [
        (p, (p.centroid.x, p.centroid.y, d)) for p, (_x, _y, d) in zip(pads, holes)])
    assert fit.used == 3 and len(fit.offsets) == 4
    assert fit.dx == pytest.approx(0, abs=0.08)
    assert fit.dy == pytest.approx(-0.5, abs=0.08)


def test_the_page_moves_the_job_onto_the_holes_after_a_test_fire(qt_app, monkeypatch):
    """The page's part: the fit's move and turn land the measured openings'
    middle where the fit says, whatever the turn did to the rest."""
    from types import SimpleNamespace
    from gerber2rml.gui2 import stencil_laser as sl
    from gerber2rml.gui2.window import MainWindow
    from gerber2rml.engine import xtool
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "mask-testfire"))
    w = MainWindow()
    try:
        w.load_folder(str(FIX / "mosfet_test"))
        w.action_traces_laser()
        d = w.laser_view
        d.switch_kind("mask")
        assert d.preset.currentText() == "RemoveSolderMask · concentric rings"
        d.selected.update({0, 3, 6})
        tests = d._test_openings()
        assert tests                           # these pads have holes
        shapes = sl._bed_shapes(d.art, d.origin(), {0, 3, 6})
        c = (sum(p.centroid.x for p in shapes) / 3, sum(p.centroid.y for p in shapes) / 3)
        fit = SimpleNamespace(dx=0.3, dy=-0.5, turn=0.4, centre=c, used=3,
                              offsets=[((0, 0), (0.3, -0.5))] * 3, worst=0.6)
        msg = d._line_up_on(fit, 3)
        now = sl._bed_shapes(d.art, d.origin(), {0, 3, 6})
        m = (sum(p.centroid.x for p in now) / 3, sum(p.centroid.y for p in now) / 3)
        assert m == pytest.approx((c[0] + 0.3, c[1] - 0.5), abs=0.01)
        assert d.fine == pytest.approx(0.4) and "moved" in msg
        # Lined up once: a rework of selected pads is not a test fire again.
        assert not d.line_up.isChecked() and d._test_openings() == []
        d.switch_kind("traces")
        d.switch_kind("mask")
        assert d.line_up.isChecked()            # a new job: line it up again
        d.close()
    finally:
        w.close()


@pytest.mark.parametrize("pad", range(4))
def test_a_real_test_fire_finds_the_pad_behind_its_opening(pad):
    """The env board's test fire (2026-11-22): every pad about 0.2 mm right
    of and 0.6 mm behind where its opening burnt. Measuring the hole in the
    photo after the burn got two of four wrong; the pad's ring and hole in
    the photo from before gets all four."""
    import json
    import numpy as np
    from PIL import Image
    from shapely.geometry import Point
    from gerber2rml.engine import xtool_camera as cam
    F = FIX / "mask_testfire"
    meta = json.loads((F / "pads.json").read_text())
    x, y = meta["pads"][pad]["opening"]
    before = np.asarray(Image.open(F / f"pad{pad}_before.png").convert("RGB"))
    after = np.asarray(Image.open(F / f"pad{pad}_after.png").convert("RGB"))
    fit = cam.fit_test_openings(before, after, meta["px_per_mm"],
                                [(Point(x, y).buffer(0.75), (x, y, meta["hole_d"]))],
                                search_mm=2.5)
    assert fit is not None and len(fit.offsets) == 1
    (_c, (dx, dy)), = fit.offsets
    assert dx == pytest.approx(0.2, abs=0.15)
    assert dy == pytest.approx(-0.6, abs=0.15)


def test_calibrate_on_a_mask_picks_spread_pads_with_holes(qt_app, monkeypatch):
    from gerber2rml.gui2 import stencil_laser as sl, laser_autocal as ac
    from gerber2rml.gui2.window import MainWindow
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "mask-calibrate"))
    w = MainWindow()
    try:
        w.load_folder(str(FIX / "mosfet_test"))
        w.action_traces_laser()
        d = w.laser_view
        d.switch_kind("mask")
        assert not d.autocal_btn.isHidden()
        picks = ac.pick_test_pads(d)
        assert 3 <= len(picks) <= 5 and len(set(picks)) == len(picks)
        shapes = sl._bed_shapes(d.art, d.origin(), set(picks))
        xs = [p.centroid.x for p in shapes]
        ys = [p.centroid.y for p in shapes]
        assert max(xs) - min(xs) > 10 and max(ys) - min(ys) > 5   # spread out
        d.close()
    finally:
        w.close()


def test_a_mounting_holes_opening_is_left_out():
    """The synth's M3 holes (2026-11-23): a 3.0 mm opening inside a 3.2 mm
    hole only fires the beam through the board. A pad's opening round a
    small hole stays."""
    from shapely.geometry import Point
    mount = Point(5, 5).buffer(1.6)
    pad_hole = Point(20, 5).buffer(0.4)
    openings = [Point(5, 5).buffer(1.5), box(19.1, 4.1, 20.9, 5.9)]
    kept, out = xtool.drop_hole_only(openings, [mount, pad_hole])
    assert out == 1 and kept == [openings[1]]


def test_the_page_leaves_mounting_holes_out_of_the_mask(qt_app, monkeypatch):
    from gerber2rml.gui2 import stencil_laser as sl
    from gerber2rml.gui2.window import MainWindow
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "mask-mounting"))
    w = MainWindow()
    try:
        w.load_folder(str(FIX / "mosfet_test"))
        art = w._laser_art_for("mask", side="bottom")
        drilled = __import__("shapely.ops", fromlist=["x"]).unary_union(art.features)
        assert all(o.intersection(drilled).area < 0.85 * o.area for o in art.apertures)
    finally:
        w.close()
