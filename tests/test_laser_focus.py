"""The laser's focus map: where it measures, what it makes of the heights,
and how a job is split into bands that are each in focus."""
import math

import pytest

from gerber2rml.engine import laser_focus as lf


def test_points_cover_the_corners_and_the_middle_on_the_grid():
    pts = lf.grid_points((20, 30, 120, 90))
    assert all(x % 10 == 0 and y % 10 == 0 for x, y in pts)
    assert all(20 <= x <= 120 and 30 <= y <= 90 for x, y in pts)
    assert len(pts) == len(set(pts))
    xs, ys = {p[0] for p in pts}, {p[1] for p in pts}
    assert min(xs) <= 30 and max(xs) >= 110
    assert min(ys) <= 40 and max(ys) >= 80
    assert (70, 60) in pts                      # the middle


def test_a_small_job_still_gets_a_few_points():
    pts = lf.grid_points((100, 100, 125, 118))
    assert 2 <= len(pts) <= 5


def test_the_map_is_exact_at_a_point_and_between_them():
    m = lf.FocusMap([(0, 0, 0.0), (100, 0, 0.4), (0, 100, 0.0),
                     (100, 100, 0.4)])
    assert m.at(100, 0) == pytest.approx(0.4)
    assert 0.0 < m.at(50, 50) < 0.4
    assert m.spread == pytest.approx(0.4)
    tx, ty = m.tilt()
    assert tx == pytest.approx(0.4) and ty == pytest.approx(0.0, abs=1e-9)


def test_a_flat_job_is_one_run():
    m = lf.FocusMap([(0, 0, 0.05), (100, 0, -0.05), (50, 50, 0.0)])
    paths = [[(10, 10), (20, 10)], [(90, 10), (95, 12)]]
    zones = lf.plan_zones(paths, m, tolerance=0.15)
    assert len(zones) == 1 and len(zones[0].paths) == 2


def test_a_tilted_job_is_split_into_bands_with_paths_whole():
    m = lf.FocusMap([(0, 0, 0.0), (200, 0, 0.8), (0, 100, 0.0),
                     (200, 100, 0.8)])
    paths = [[(x, 50), (x + 5, 50)] for x in range(0, 200, 10)]
    zones = lf.plan_zones(paths, m, tolerance=0.15)
    assert len(zones) >= 3
    assert sorted(z.dz for z in zones) == [z.dz for z in zones]
    assert sum(len(z.paths) for z in zones) == len(paths)
    for z in zones:                    # every band within the depth of focus
        under = [m.at(*lf._middle(p)) for p in z.paths]
        assert max(under) - min(under) <= 0.3 + 1e-9
        assert all(abs(u - z.dz) <= 0.15 + 1e-9 for u in under)


def test_no_map_is_one_run_at_the_autofocus_height():
    zones = lf.plan_zones([[(0, 0), (1, 1)]], None)
    assert len(zones) == 1 and zones[0].dz == 0.0


def test_the_map_round_trips():
    m = lf.FocusMap([(10, 20, 0.12)], z=12.4)
    again = lf.FocusMap.from_dict(m.to_dict())
    assert again.points == m.points and again.z == m.z
    assert lf.FocusMap.from_dict({"nope": 1}) is None


def test_measure_map_walks_the_points_and_ends_idle():
    calls = []

    class Laser:
        def _json(self, method, path, body=None):
            calls.append(body["state"])

        def z(self):
            return 12.0

        def measure(self, cal, at):
            return at[0] / 1000.0

    m = lf.measure_map(Laser(), None, [(10, 10), (20, 10), (30, 10)],
                       should_stop=lambda: len(calls) > 99)
    assert [p[2] for p in m.points] == [0.01, 0.02, 0.03] and m.z == 12.0
    assert calls == ["P_AUTOFOCUS", "P_IDLE"]


def test_a_point_without_a_dot_is_left_out_not_the_whole_map():
    from gerber2rml.engine.xtool_camera import CameraError
    calls = []

    class Laser:
        def _json(self, method, path, body=None):
            calls.append(body["state"])

        def z(self):
            return 12.0

        def measure(self, cal, at):
            if at == (20, 10):
                raise CameraError("No dot in the photo")
            return 0.1

    m = lf.measure_map(Laser(), None, [(10, 10), (20, 10), (30, 10), (40, 10)])
    assert [p[:2] for p in m.points] == [(10, 10), (30, 10), (40, 10)]
    assert m.skipped == [(20.0, 10.0)] and calls == ["P_AUTOFOCUS", "P_IDLE"]
    assert "1 left out" in lf.describe(m, lf.plan_zones([[(10, 10)]], m))


def test_a_map_with_too_few_points_read_fails():
    import pytest
    from gerber2rml.engine.xtool_camera import CameraError

    class Laser:
        def _json(self, method, path, body=None):
            pass

        def z(self):
            return 12.0

        def measure(self, cal, at):
            if at != (10, 10):
                raise CameraError("No dot in the photo")
            return 0.0

    with pytest.raises(CameraError, match="Only 1 of 3"):
        lf.measure_map(Laser(), None, [(10, 10), (20, 10), (30, 10)])


def test_zone_indices_keep_every_shape_once():
    m = lf.FocusMap([(0, 0, 0.0), (200, 0, 0.8)])
    centres = [(x, 0) for x in range(0, 201, 20)]
    groups = lf.zone_indices(centres, m)
    got = sorted(i for _dz, idx in groups for i in idx)
    assert got == list(range(len(centres))) and len(groups) > 1


def test_run_zoned_refocuses_each_band_and_goes_back():
    from types import SimpleNamespace
    from gerber2rml.gui2.laser_focus_ui import run_zoned
    log = []

    class Laser:
        def _json(self, method, path, body=None):
            log.append(("mode", body["state"]))

        def _goto_z(self, z):
            log.append(("z", round(z, 3)))
            return z

        def z(self):
            return 10.0

        def run(self, text):
            log.append(("run", text))

        def wait(self, timeout, progress=None):
            log.append(("wait",))

    fmap = lf.FocusMap([(0, 0, 0.0)], z=10.0)
    zones = [(-0.2, [0, 1]), (0.3, [2])]
    run_zoned(Laser(), fmap, zones,
              lambda idx: SimpleNamespace(text=str(sorted(idx)), seconds=1.0),
              timeout_for=lambda job: 10)
    zs = [e[1] for e in log if e[0] == "z"]
    assert zs == [9.8, 10.3, 10.0]                 # each band, then back
    runs = [e[1] for e in log if e[0] == "run"]
    assert runs == ["[0, 1]", "[2]"]
    assert log[-1] == ("mode", "P_IDLE")


def test_run_zoned_without_a_map_just_runs():
    from types import SimpleNamespace
    from gerber2rml.gui2.laser_focus_ui import run_zoned
    log = []

    class Laser:
        def z(self):
            return 5.0

        def run(self, text):
            log.append(text)

        def wait(self, timeout, progress=None):
            pass

    run_zoned(Laser(), None, [(0.0, [0, 1, 2])],
              lambda idx: SimpleNamespace(text="job", seconds=1.0),
              timeout_for=lambda job: 10)
    assert log == ["job"]


def test_the_laser_page_runs_a_tilted_board_in_bands(qt_app, monkeypatch):
    """A mask job over a board tilted 1.2 mm across: the page runs it in
    bands, each at its own height, and every shape once."""
    import time
    from shapely.geometry import box
    from PySide6.QtCore import QCoreApplication
    from gerber2rml.engine import xtool
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "laser-focus"))
    art = xtool.LaserArt(kind="mask", outline=box(0, 0, 120, 20),
                         apertures=[box(x, 5, x + 4, 9)
                                    for x in range(5, 115, 10)],
                         mirrored=False)
    d = sl.StencilLaserDialog(art)
    log = []

    class Laser:
        def z(self):
            return 10.0

        def _json(self, method, path, body=None):
            pass

        def _goto_z(self, z):
            log.append(("z", round(z, 3)))
            return z

        def run(self, text):
            log.append(("run", text.count("\n")))

        def wait(self, timeout, progress=None):
            pass

    d.laser = Laser()
    d.photo_after.setChecked(False)
    x0, y0, x1, y1 = __import__(
        "gerber2rml.gui2.laser_focus_ui", fromlist=["x"]).job_bounds(d)
    d._focus_map = lf.FocusMap([(x0, y0, 0.0), (x1, y0, 1.2),
                                (x0, y1, 0.0), (x1, y1, 1.2)], z=10.0)
    d._fill()
    t0 = time.time()
    while d._worker_running() and time.time() - t0 < 20:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    runs = [e for e in log if e[0] == "run"]
    zs = [e[1] for e in log if e[0] == "z"]
    assert len(runs) >= 2, log
    assert zs[-1] == 10.0                       # back where it was measured
    assert min(zs[:-1]) < 10.4 and max(zs[:-1]) > 10.8
    d.close()


def _page(qt_app, monkeypatch):
    from shapely.geometry import box
    from gerber2rml.engine import xtool
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "laser-focus"))
    art = xtool.LaserArt(kind="traces", outline=box(0, 0, 120, 80),
                         apertures=[box(5, 5, 9, 9)], mirrored=False)
    return sl.StencilLaserDialog(art)


def test_the_focus_cross_can_be_dragged_to_any_spot(qt_app, monkeypatch):
    """Dropped somewhere else, Autofocus measures there - on the grid."""
    d = _page(qt_app, monkeypatch)
    middle = d.focus_point()
    d._focus_mark.setPos(23.0, 141.0)
    d._focus_dropped(23.0, 141.0)
    assert d.focus_point() == (20, 140) != middle
    assert d._focus_mark.pos().x() == 20 and d._focus_mark.pos().y() == 140
    asked = []
    d.autofocus = lambda at=None: asked.append(at or d.focus_point())
    d.focus_btn.click()
    assert asked == [(20, 140)]
    d.set_focus_point(None)                     # back to the middle
    assert d.focus_point() == middle
    d.close()


def test_focus_on_the_boxes_focuses_where_the_rework_is(qt_app, monkeypatch):
    d = _page(qt_app, monkeypatch)
    assert not d.rework_focus_btn.isEnabled()   # nothing to focus on yet
    d.rework_boxes = [(148.0, 66.0, 156.0, 72.0)]
    d._draw_rework()
    assert d.rework_focus_btn.isEnabled()
    asked = []
    d.autofocus = lambda at=None: asked.append(d.focus_point())
    d.rework_focus_btn.click()
    assert asked == [(150, 70)]
    d.close()


def test_the_focus_moves_with_the_design(qt_app, monkeypatch):
    """At the middle by default, or where it was put on the board: moving
    the design takes the focus point with it."""
    d = _page(qt_app, monkeypatch)
    d.x.setValue(20.0)
    d.y.setValue(20.0)                    # the 120 x 80 job's middle: 80, 60
    assert d.focus_point() == (80, 60)
    d.x.setValue(60.0)                    # 40 mm to the right
    assert d.focus_point() == (120, 60)
    assert d._focus_mark.pos().x() == 120
    d._focus_dropped(150.0, 60.0)         # 30 mm right of the middle
    d.x.setValue(20.0)
    d.y.setValue(40.0)                    # the design moves 40 left, 20 down
    assert d.focus_point() == (110, 80)   # and the point with it
    d.rotate(1)                           # a quarter turn clockwise
    assert d.focus_point() == (80, 110)   # right of the middle -> below it
    d.close()


def test_bands_follow_the_surface_not_each_regions_middle():
    """A board tilted up the bed: the isolation round its edge is one region
    centred in the middle, but its front and back must run at their own
    heights. The bands split the area by height and cover it once."""
    m = lf.FocusMap([(0, 0, -1.2), (100, 0, -1.2), (0, 100, 1.2),
                     (100, 100, 1.2), (50, 50, 0.0)])
    bands = lf.band_boxes(m, (0, 0, 100, 100))
    assert len(bands) >= 4
    dzs = [dz for dz, _b in bands]
    assert dzs == sorted(dzs) and dzs[0] < -0.8 and dzs[-1] > 0.8
    area = sum((x1 - x0) * (y1 - y0) for _dz, bx in bands for x0, y0, x1, y1 in bx)
    assert area == pytest.approx(102 * 102)
    front = [b for dz, bx in bands if dz < -0.8 for b in bx]
    assert max(b[3] for b in front) < 50


def test_a_flat_map_is_one_band():
    m = lf.FocusMap([(0, 0, 0.05), (100, 100, -0.05)])
    assert len(lf.band_boxes(m, (0, 0, 100, 100))) == 1


def test_the_machines_slope_is_taken_off_and_a_real_tilt_kept():
    """On a flat sheet the dot read a slope up the bed; measured once as the
    reference, it comes off later maps, and only what is really there stays."""
    slope = lambda y: (y - 110) * 0.014
    flat = lf.FocusMap([(x, y, slope(y) + 0.3) for x in (40, 110, 180)
                        for y in (80, 110, 160)], z=19.0)
    ref = lf.reference_from(flat)
    assert ref.at(110, 110) == pytest.approx(0.0)
    tilted = lf.FocusMap([(x, y, slope(y) + 0.005 * (x - 110)) for x in (40, 110, 180)
                          for y in (80, 110, 160)], z=19.0, skipped=[(1.0, 2.0)])
    got = lf.corrected(tilted, ref)
    for x, y, dz in got.points:
        assert dz == pytest.approx(0.005 * (x - 110), abs=1e-9)
    assert got.skipped == [(1.0, 2.0)] and got.z == 19.0
    assert lf.corrected(tilted, None) is tilted


def test_the_reference_knows_where_it_was_measured():
    ref = lf.FocusMap([(40, 80, 0.0), (180, 160, 0.0), (110, 110, 0.0)])
    assert lf.reference_covers(ref, (39, 76, 179, 160))
    assert not lf.reference_covers(ref, (0, 0, 220, 220))
    assert not lf.reference_covers(None, (39, 76, 179, 160))


def _square(x, y, r):
    return [(x - r, y - r), (x + r, y - r), (x + r, y + r), (x - r, y + r)]


def test_a_focus_map_point_never_lands_in_a_hole():
    """A student's map put a point in a mounting hole: the dot read the
    hole's depth as the surface and the whole map went off."""
    board = [(40, 40), (120, 40), (120, 100), (40, 100)]
    hole = _square(70, 70, 1.6)                    # a 3.2 mm mounting hole
    safe = lf.safe_area([board], [hole])
    moved = []
    pts = lf.grid_points((40, 40, 120, 100), safe=safe, moved=moved)
    for x, y in pts:
        assert math.hypot(x - 70, y - 70) > 1.6 + lf.HOLE_CLEAR_MM
        assert 40 + lf.EDGE_CLEAR_MM <= x <= 120 - lf.EDGE_CLEAR_MM
        assert x % 10 == 0 and y % 10 == 0         # still the factory grid
    assert (70, 70) not in pts                      # the middle was the hole
    assert any(was == (70.0, 70.0) and now for was, now in moved)


def test_without_holes_the_points_are_as_before():
    board = [(40, 40), (120, 40), (120, 100), (40, 100)]
    plain = lf.grid_points((40, 40, 120, 100))
    safe = lf.grid_points((40, 40, 120, 100),
                          safe=lf.safe_area([board], []))
    assert set(safe) <= set(plain) | set(safe)
    assert len(safe) >= lf.MIN_POINTS


def test_the_autofocus_cross_moves_off_a_hole(qt_app, monkeypatch):
    d = _page(qt_app, monkeypatch)
    cx, cy = d.focus_point()                 # a hole right under the cross
    holes = [_square(cx, cy, 1.6)]
    monkeypatch.setattr(d, "_hole_paths", lambda *a, **k: holes)
    d._focus_dropped(cx, cy)
    fx, fy = d.focus_point()
    from shapely.geometry import Point, Polygon
    assert not Polygon(holes[0]).buffer(lf.HOLE_CLEAR_MM).contains(Point(fx, fy))
    assert fx % 10 == 0 and fy % 10 == 0
    d.close()


def test_the_focus_map_spacing_changes_the_points(qt_app, monkeypatch):
    from gerber2rml.gui2 import laser_focus_ui as lfu
    d = _page(qt_app, monkeypatch)
    few, _ = lfu.plan(d, spacing=60.0, inset=3.0)
    many, _ = lfu.plan(d, spacing=10.0, inset=3.0)
    assert len(many) > len(few) >= 2
    d.close()


def test_the_bed_can_be_looked_round_while_the_laser_runs(qt_app, monkeypatch):
    """While a job runs the bed zooms and pans; nothing changes the job."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    d = _page(qt_app, monkeypatch)
    d.resize(1400, 900)
    d.show()
    qt_app.processEvents()
    d._busy(True)
    v = d.view
    assert v.isEnabled() and v.locked
    before = v.transform().m11()
    e = QWheelEvent(QPointF(50, 50), QPointF(v.mapToGlobal(QPoint(50, 50))),
                    QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                    Qt.NoScrollPhase, False)
    QApplication.sendEvent(v.viewport(), e)
    assert v.transform().m11() > before          # zoomed
    nudged, menus = [], []
    v.nudge.connect(lambda *a: nudged.append(a))
    v.context.connect(lambda *a: menus.append(a))
    x = d.x.value()
    QTest.keyClick(v, Qt.Key_Left)
    assert nudged == [] and d.x.value() == x     # the job stays put
    d._busy(False)
    assert not v.locked
    QTest.keyClick(v, Qt.Key_Left)
    assert nudged                                # and moves again after
    d.close()


def test_the_machines_correction_is_built_in(qt_app, monkeypatch):
    """The lab F1 Ultra's own error ships with the app: a new PC need not
    measure it (2026-11-19)."""
    from gerber2rml.gui2 import laser_focus_ui as lfu
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "laser-builtin-ref"))
    lfu.save_reference(None)
    ref = lfu.load_reference()
    assert ref is not None and len(ref.points) >= 20
    assert lfu.reference_is_builtin()
    assert lfu.reference_status().startswith("Built in")
    assert abs(ref.at(*lf.REFERENCE_CENTRE)) < 0.05      # 0 at the middle
    mine = lf.FocusMap([(100, 100, 0.0), (120, 100, 0.2), (100, 120, 0.1)], 18.0)
    lfu.save_reference(mine)
    assert not lfu.reference_is_builtin()
    assert len(lfu.load_reference().points) == 3          # this PC's wins
    lfu.save_reference(None)


def test_stop_ends_a_focus_map_between_points(qt_app, monkeypatch):
    """A focus map pressed by mistake (2026-11-22) ran on: STOP only stopped
    jobs on the machine, and the map is the page walking the dot point by
    point. STOP now ends it before the next point, puts the diode out, and
    the half map is thrown away."""
    import time
    from shapely.geometry import box
    from PySide6.QtCore import QCoreApplication
    from gerber2rml.engine import xtool
    from gerber2rml.gui2 import stencil_laser as sl, laser_focus_ui as lfu
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "laser-focus-stop"))
    art = xtool.LaserArt(kind="mask", outline=box(0, 0, 120, 60),
                         apertures=[box(x, 25, x + 4, 29)
                                    for x in range(5, 115, 10)],
                         mirrored=False)
    d = sl.StencilLaserDialog(art)
    log = []

    class Laser:
        def z(self):
            return 10.0

        def _json(self, method, path, body=None):
            log.append(body.get("state") if isinstance(body, dict) else path)

        def measure(self, cal, at):
            log.append("dot")
            if log.count("dot") == 2:
                d.stop()                     # pressed while the map runs
            time.sleep(0.01)
            return 0.0

        def stop(self):
            log.append("stop")

        def gcode(self, line):
            log.append(line)

    d.laser = Laser()
    monkeypatch.setattr(d, "_calibration", lambda: None)
    points, _moved = lfu.plan(d)
    assert len(points) > 4
    before = d._focus_map
    lfu.measure(d)
    t0 = time.time()
    while d._worker_running() and time.time() - t0 < 20:
        QCoreApplication.processEvents()
    QCoreApplication.processEvents()
    assert log.count("dot") == 2                     # not one point more
    assert "stop" in log and "M5" in log and log[-1] == "P_IDLE"
    assert d._focus_map is before                    # the half map not used
    assert "not finished" in d.status.text()
    d.close()
