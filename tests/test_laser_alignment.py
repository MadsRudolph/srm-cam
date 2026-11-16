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
