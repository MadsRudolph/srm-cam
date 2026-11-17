"""Registration through arbitrary references and corrected camera coordinates."""
from math import cos, radians, sin

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from shapely.geometry import Point, box

from gerber2rml.engine import xtool, xtool_camera as cam
from gerber2rml.gui2 import stencil_laser as sl


def transformed(points, angle=3.7, shift=(4.25, -2.8)):
    c, s = cos(radians(angle)), sin(radians(angle))
    return [(c*x - s*y + shift[0], s*x + c*y + shift[1]) for x, y in points]


def test_point_fit_recovers_rigid_motion_without_holes():
    source = [(15, 20), (60, 23), (42, 70)]
    target = transformed(source)
    result = cam.fit_reference_points(source, target)
    assert result.rms < 1e-10
    assert result.transform.scale == 1
    for p, q in zip(source, target):
        assert result.transform.apply(*p) == pytest.approx(q)


@pytest.mark.parametrize("source,target,message", [
    ([], [], "at least two"),
    ([(0, 0)], [(1, 1)], "at least two"),
    ([(0, 0), (1, 1)], [(3, 3), (4, 4)], "5 mm"),
    ([(0, 0), (10, 0), (0, 0)], [(1, 1), (11, 1), (1, 1)], "overlap"),
    ([(0, 0), (20, 0)], [(0, 0), (25, 0)], "disagrees"),
    ([(0, 0), (20, 0)], [(0, 0), (float('nan'), 0)], "finite"),
    ([(0, 0), (20, 0), (0, 20)], [(0, 0), (20, 0), (0, -20)], "disagrees"),
])
def test_bad_reference_geometry_is_rejected(source, target, message):
    with pytest.raises(cam.CameraError, match=message):
        cam.fit_reference_points(source, target)


@pytest.fixture
def dialog(qt_app, monkeypatch):
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "alignment"))
    art = xtool.LaserArt(kind="traces", outline=box(0, 0, 60, 40),
                         apertures=[box(10, 10, 12, 12), box(40, 25, 42, 27)],
                         features=[Point(8, 8).buffer(1), Point(50, 30).buffer(1)])
    d = sl.StencilLaserDialog(art)
    d.x.setValue(55)
    d.y.setValue(65)
    d.show_bed(np.full((880, 880, 3), 190, dtype=np.uint8))
    yield d
    d.close()


def pick_pairs(d, sources, targets):
    d.reference_snap.setCurrentIndex(d.reference_snap.findData("free"))
    d.pick_refs_btn.click()
    for p, q in zip(sources, targets):
        d._pick_reference(QPointF(*p))
        assert not d.item.isVisible()  # The drawing cannot obscure the photo pick.
        d._pick_reference(QPointF(*q))
        assert d.item.isVisible()


@pytest.mark.parametrize("quarter,fine", [(0, 0), (1, 2.3), (3, -4.2)])
def test_manual_picks_move_actual_job_and_preserve_scale(dialog, quarter, fine):
    d = dialog
    d._turn_to(quarter, fine)
    base = [(3, 3), (55, 5), (7, 35)]
    source = [d._reference_to_bed(p) for p in base]
    target = transformed(source)
    selected = {1}
    d.selected = selected.copy()
    pick_pairs(d, source, target)
    d.apply_reference_alignment()
    assert "RMS" in d.status.text()
    assert not d.view.pick_reference
    assert d.selected == selected  # Alignment selection never changes etching.
    for p, q in zip(base, target):
        assert d._reference_to_bed(p) == pytest.approx(q, abs=0.002)
    # This is the actual aperture geometry used for preview/export/run.
    original_centre = (11, 11)
    expected = d._reference_to_bed(original_centre)
    centre = d.art.apertures[0].centroid
    actual = xtool.to_bed([(centre.x, centre.y)], d.origin(), d.art.size[1])[0]
    assert actual == pytest.approx(expected, abs=1e-8)


def test_inconsistent_picks_do_not_move_job(dialog):
    d = dialog
    source = [(60, 70), (100, 70), (60, 100)]
    target = [(65, 75), (105, 75), (80, 100)]
    pick_pairs(d, source, target)
    before = d.origin(), d.turns, d.fine
    d.apply_reference_alignment()
    assert (d.origin(), d.turns, d.fine) == before
    assert "disagrees" in d.status.text()


def test_auto_reference_selection_is_independent_of_run_selection(dialog):
    d = dialog
    d.selected = {1}
    d.auto_reference_list.item(0).setCheckState(Qt.Unchecked)
    assert len(d._features(d.art, d.origin())) == 1
    assert d.selected == {1}
    d._check_auto_references(False)
    assert not d._features(d.art, d.origin())
    d.align()
    assert "at least two" in d.status.text()
    d.auto_reference_source.setCurrentIndex(d.auto_reference_source.findData("artwork"))
    assert len(d._features(d.art, d.origin())) == 2
    assert d.selected == {1}


def test_photo_offset_reprojects_cached_photo_and_targets_without_moving_job(dialog):
    d = dialog
    calls = []
    class Calibration:
        def rectify(self, raw, ppm, offset):
            calls.append(offset)
            return raw.copy()
    d._cal = Calibration()
    d._raw_rgb = np.full((880, 880, 3), 200, dtype=np.uint8)
    d._reference_pairs = [((5, 5), (80, 90)), ((50, 30), (125, 115))]
    before = d.origin(), d.fine, d.art
    old = d.cam_offset
    d._set_offset((old[0] + 0.6, old[1] - 0.8))
    assert calls[-1] == d.cam_offset
    assert d._reference_pairs[0][1] == pytest.approx((79.4, 90.8))
    assert (d.origin(), d.fine, d.art) == before
    assert d._bed_rgb[0, 0, 0] == 200
    d._set_offset(old)  # Return to the isolated fixture's original correction.


def test_learning_uses_cut_snapshot_even_if_overlay_moves(dialog, monkeypatch):
    d = dialog
    cut = [[(70, 80), (71, 80), (71, 81)], [(100, 90), (101, 90), (101, 91)]]
    d._last_cut_paths = cut
    d.x.setValue(130)
    calls = []
    def align(rgb, ppm, paths, **kwargs):
        calls.append(paths)
        return cam.Alignment(0.5, -0.8, 0, 2, 2, 0.9)
    monkeypatch.setattr(cam, "align", align)
    assert d._residual(d._bed_rgb, 4) is not None
    assert calls == [cut]


def test_two_auto_references_can_align_but_empty_pattern_is_a_message(qt_app):
    holes = [[(20, 20), (22, 20), (22, 22), (20, 22)],
             [(50, 40), (52, 40), (52, 42), (50, 42)]]
    moved = [[(x+2, y+3) for x, y in p] for p in holes]
    mask = cam._raster(moved, (0, 0), (400, 400), 4)
    rgb = np.repeat((220 * (1-mask)).astype(np.uint8)[..., None], 3, axis=2)
    result = cam.align(rgb, 4, holes, search_mm=5, max_turn=1)
    assert result.ok
    assert (result.dx, result.dy) == pytest.approx((2, 3), abs=0.3)
    with pytest.raises(cam.CameraError, match="at least two"):
        cam.align(rgb, 4, [])


def test_photo_correction_sign_in_factory_rectification():
    cal = cam.Calibration.__new__(cam.Calibration)
    cal.n = 3
    cal.src_size = (21, 21)
    cal.grid = np.array([[(20-10*i, 20-10*j) for i in range(3)] for j in range(3)], float)
    raw = np.zeros((21, 21, 3), np.uint8)
    raw[8, 12] = 255
    photo = cal.rectify(raw, 1, offset=(2, -1))
    y, x = np.unravel_index(photo.sum(axis=2).argmax(), photo.shape[:2])
    assert (x, y) == (10, 9)  # Positive correction moves the displayed mark left.


def test_snapping_to_drill_centres_and_removing_a_pair(dialog):
    d = dialog
    d.pick_refs_btn.click()
    exact = xtool.to_bed([(8, 8)], d.origin(), d.art.size[1])[0]
    d._pick_reference(QPointF(exact[0]+0.3, exact[1]-0.2))
    assert d._pending_reference == pytest.approx((8, 8))
    d._pick_reference(QPointF(exact[0]+2, exact[1]+3))
    assert len(d._reference_pairs) == 1
    d.reference_list.setCurrentRow(0)
    d._remove_reference()
    assert not d._reference_pairs
    assert d.selected == set()


def test_bright_reference_alignment(qt_app):
    holes = [[(20, 20), (22, 20), (22, 22), (20, 22)],
             [(50, 40), (52, 40), (52, 42), (50, 42)]]
    moved = [[(x+2, y+3) for x, y in p] for p in holes]
    mask = cam._raster(moved, (0, 0), (400, 400), 4)
    rgb = np.repeat((20 + 220 * mask).astype(np.uint8)[..., None], 3, axis=2)
    result = cam.align(rgb, 4, holes, search_mm=5, max_turn=1, polarity="bright")
    assert result.ok
    assert (result.dx, result.dy) == pytest.approx((2, 3), abs=0.3)


# -- proof: the laser's own marks, seen next to the drilled holes ------------

def _scene(shape, ppm, dark=(), marks=(), shift=(0.0, 0.0), sheet=None):
    """A grey sheet (or only ``sheet``, on a dark bed) with dark discs and
    scuffed marks, everything seen ``shift`` mm from where it is."""
    from shapely.affinity import translate
    img = np.full(shape + (3,), 185.0, np.float32)
    if sheet is not None:
        m = cam._raster_polys([translate(sheet, *shift)], (0, 0), shape, ppm)
        img = 40 + (img - 40) * m[..., None]
    for polys, level in ((dark, 25.0), (marks, 120.0)):
        if polys:
            m = cam._raster_polys([translate(q, *shift) for q in polys], (0, 0), shape, ppm)
            img = img * (1 - m[..., None]) + level * m[..., None]
    return img.astype(np.uint8)


def _board():
    copper = box(4, 4, 56, 36)
    drills = [(8.0, 8.0, 0.9), (52.0, 9.0, 0.9), (30.0, 32.0, 0.9), (20.0, 20.0, 0.9)]
    pads = [Point(x, y).buffer(1.2) for x, y, _ in drills]
    from shapely.ops import unary_union
    cu = unary_union(pads + [box(8, 7.7, 52, 8.3)])
    outline = box(0, 0, 60, 40)
    return xtool.LaserArt(
        kind="traces", outline=outline, copper=cu, drills=drills,
        apertures=xtool.traces_apertures(cu, outline, drills),
        features=[Point(x, y).buffer(d / 2) for x, y, d in drills])


def test_spread_picks_far_apart_points():
    pts = [(0, 0), (1, 0), (50, 0), (25, 40), (26, 40)]
    assert set(xtool.spread(pts, 3)) in ({0, 2, 3}, {0, 2, 4}, {1, 2, 3}, {1, 2, 4})
    assert xtool.spread(pts[:2], 3) == [0, 1]


def test_isolation_proof_marks_only_copper_the_job_removes():
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    art, origin = _board(), (50.0, 60.0)
    proof = xtool.proof_on_isolation(art, origin)
    assert proof.where == "isolation" and len(proof.marks) == 3
    _, h = art.size
    cleared = unary_union([type(p)(xtool.to_bed(list(p.exterior.coords), origin, h),
                                   [xtool.to_bed(list(r.coords), origin, h) for r in p.interiors])
                           for p in art.apertures]).buffer(0.01)
    centres = [xtool.to_bed([(x, y)], origin, h)[0] for x, y, _ in art.drills]
    for path in proof.paths:
        line = LineString(path)
        assert cleared.contains(line)
        assert min(line.distance(Point(c)) for c in centres) < xtool.PROOF_RADIUS
    text, secs = xtool.proof_job(proof, passes=3)
    assert "G22" in text and secs < 5


def test_waste_proof_sits_outside_the_outline_and_on_the_bed():
    art, origin = _board(), (50.0, 60.0)
    proof = xtool.proof_in_waste(art, origin)
    board = box(50, 60, 110, 100)
    assert len(proof.marks) >= 2 and len(proof.inside) == len(proof.marks)
    for m, p in zip(proof.marks, proof.inside):
        assert m.distance(board) > 2 and board.contains(Point(p))
    with pytest.raises(ValueError, match="off the laser"):
        xtool.proof_in_waste(art, (1.0, 60.0))


def test_change_between_photos_is_found_whatever_the_board_looks_like():
    art, origin, ppm, shape = _board(), (50.0, 60.0), 8, (1200, 1200)
    proof = xtool.proof_on_isolation(art, origin)
    holes = [Point(q).buffer(0.45) for q in xtool._drills_on_bed(art, origin)]
    before = _scene(shape, ppm, dark=holes)
    from shapely.affinity import translate
    after = _scene(shape, ppm, dark=holes,
                   marks=[translate(m, 0.6, -0.9) for m in proof.marks])
    fit = cam.locate_change(before, after, ppm, proof.marks)
    assert fit.ok and fit.found == 3
    assert (fit.dx, fit.dy) == pytest.approx((0.6, -0.9), abs=0.06)
    nothing = cam.locate_change(before, before, ppm, proof.marks)
    assert not nothing.ok and nothing.found == 0


def test_sheet_continues_only_where_there_is_material():
    art, origin, ppm, shape = _board(), (50.0, 60.0), 8, (1200, 1200)
    proof = xtool.proof_in_waste(art, origin)
    whole = _scene(shape, ppm)
    only_board = _scene(shape, ppm, sheet=box(50, 60, 110, 100))
    assert cam.sheet_continues(whole, ppm, proof.spots, proof.inside)
    assert not cam.sheet_continues(only_board, ppm, proof.spots, proof.inside)


@pytest.mark.parametrize("where,sheet", [("isolation", "board"), ("auto", "board"),
                                         ("auto", "sheet"), ("waste", "sheet")])
def test_proof_corrects_the_camera_and_puts_the_job_on_the_holes(
        qt_app, monkeypatch, where, sheet):
    from shapely.affinity import translate
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "proof"))
    ppm_hi, err, off_board = 8, (0.5, -0.7), (0.8, 0.4)

    class Laser:
        fired = None

        def run(self, text):
            Laser.fired = text

        def wait(self, *_a, **_k):
            pass

    d = sl.StencilLaserDialog(_board(), laser=Laser())
    try:
        d._set_offset((0.0, 0.0))
        d.x.setValue(50)
        d.y.setValue(60)
        d.proof_where.setCurrentIndex(d.proof_where.findData(where))
        # The board really lies ``off_board`` from the drawing; the camera shows
        # everything ``err`` from where the laser would hit it.
        real_holes = [translate(Point(q).buffer(0.45), *off_board)
                      for q in xtool._drills_on_bed(d.art, d.origin())]
        stock = (translate(box(50, 60, 110, 100), *off_board) if sheet == "board"
                 else box(20, 30, 140, 130))
        plans, _ = d._proof_plans()
        by = {p.where: p for p in plans}

        def photo(px_per_mm=sl._PX_PER_MM, raw=None, offset=None):
            raw = d._raw_photo() if raw is None else raw
            o = d.cam_offset if offset is None else offset
            marks = []
            if raw == "after":
                first = "G0X%.3fY%.3f" % by["waste"].paths[0][0] if "waste" in by else None
                used = "waste" if first and first in Laser.fired else "isolation"
                marks = by[used].marks
                d._used = used
            size = int(220 * px_per_mm)
            return _scene((size, size), px_per_mm, dark=real_holes, marks=marks,
                          shift=(err[0] - o[0], err[1] - o[1]), sheet=stock)
        monkeypatch.setattr(d, "_raw_photo",
                            lambda: "after" if Laser.fired else "before")
        monkeypatch.setattr(d, "_photo", photo)
        monkeypatch.setattr(d, "_start", lambda fn, text, done=None:
                            d._say(done(fn(lambda *_a: None))))
        x0, y0 = d.x.value(), d.y.value()
        d.proof()
        assert d._last_proof is not None, d.status.text()
        assert d._used == ("waste" if sheet == "sheet" else "isolation")
        assert d._last_proof["where"] == d._used
        assert d.cam_offset == pytest.approx(err, abs=0.08)
        assert (d.x.value() - x0, d.y.value() - y0) == pytest.approx(off_board, abs=0.1)
        assert "Ready to cut" in d.status.text()
    finally:
        d._set_offset((0.0, 0.0))
        d.close()


def test_proof_that_leaves_no_mark_moves_nothing(qt_app, monkeypatch):
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "proof"))

    class Laser:
        def run(self, text): pass
        def wait(self, *_a, **_k): pass

    d = sl.StencilLaserDialog(_board(), laser=Laser())
    try:
        d._set_offset((0.0, 0.0))
        d.x.setValue(50)
        d.y.setValue(60)
        d.proof_where.setCurrentIndex(d.proof_where.findData("isolation"))
        blank = _scene((1760, 1760), 8)
        monkeypatch.setattr(d, "_raw_photo", lambda: "raw")
        monkeypatch.setattr(d, "_photo", lambda px=sl._PX_PER_MM, raw=None, offset=None:
                            blank[::8 // px, ::8 // px])
        monkeypatch.setattr(d, "_start", lambda fn, text, done=None:
                            d._say(done(fn(lambda *_a: None))))
        d.proof()
        assert d._last_proof is None
        assert d.cam_offset == (0.0, 0.0) and (d.x.value(), d.y.value()) == (50, 60)
        assert "did not show" in d.status.text()
    finally:
        d.close()


def test_the_camera_calibration_is_offered_on_every_traces_job(dialog):
    # The fixture's board has no drills: a blank. The calibration is still
    # there; it only corrects the camera.
    assert not dialog.proof_btn.isHidden()
    assert dialog.proof_btn.text() == "Calibrate the camera"


@pytest.mark.parametrize("where,sheet", [("isolation", "board"), ("auto", "sheet")])
def test_on_a_blank_the_calibration_corrects_the_camera_and_moves_nothing(
        qt_app, monkeypatch, where, sheet):
    """No drilled holes yet: the marks still correct the camera; the job
    stays where it was put."""
    from dataclasses import replace
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "proof-blank"))
    err = (0.5, -0.7)

    class Laser:
        fired = None

        def run(self, text):
            Laser.fired = text

        def wait(self, *_a, **_k):
            pass

    blank = replace(_board(), drills=[], features=[])
    d = sl.StencilLaserDialog(blank, laser=Laser())
    try:
        d._set_offset((0.0, 0.0))
        d.x.setValue(50)
        d.y.setValue(60)
        assert d.proof_btn.text() == "Calibrate the camera"
        d.proof_where.setCurrentIndex(d.proof_where.findData(where))
        stock = box(50, 60, 110, 100) if sheet == "board" else box(20, 30, 140, 130)
        plans, _ = d._proof_plans()
        by = {p.where: p for p in plans}

        def photo(px_per_mm=sl._PX_PER_MM, raw=None, offset=None):
            raw = d._raw_photo() if raw is None else raw
            o = d.cam_offset if offset is None else offset
            marks = []
            if raw == "after":
                first = "G0X%.3fY%.3f" % by["waste"].paths[0][0] if "waste" in by else None
                used = "waste" if first and first in Laser.fired else "isolation"
                marks = by[used].marks
            size = int(220 * px_per_mm)
            return _scene((size, size), px_per_mm, dark=[], marks=marks,
                          shift=(err[0] - o[0], err[1] - o[1]), sheet=stock)
        monkeypatch.setattr(d, "_raw_photo",
                            lambda: "after" if Laser.fired else "before")
        monkeypatch.setattr(d, "_photo", photo)
        monkeypatch.setattr(d, "_start", lambda fn, text, done=None:
                            d._say(done(fn(lambda *_a: None))))
        x0, y0 = d.x.value(), d.y.value()
        d.proof()
        assert d._last_proof is not None, d.status.text()
        assert d.cam_offset == pytest.approx(err, abs=0.08)
        assert (d.x.value(), d.y.value()) == (x0, y0)
        assert "stays where it is" in d.status.text()
    finally:
        d._set_offset((0.0, 0.0))
        d.close()
