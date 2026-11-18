"""The laser's focus map: where it measures, what it makes of the heights,
and how a job is split into bands that are each in focus."""
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
    """A mask job over a board tilted 0.6 mm across: the page runs it in
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
    d._focus_map = lf.FocusMap([(x0, y0, 0.0), (x1, y0, 0.6),
                                (x0, y1, 0.0), (x1, y1, 0.6)], z=10.0)
    d._fill()
    t0 = time.time()
    while d._worker_running() and time.time() - t0 < 20:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    runs = [e for e in log if e[0] == "run"]
    zs = [e[1] for e in log if e[0] == "z"]
    assert len(runs) >= 2, log
    assert zs[-1] == 10.0                       # back where it was measured
    assert min(zs[:-1]) < 10.2 and max(zs[:-1]) > 10.4
    d.close()
