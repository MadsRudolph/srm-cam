"""The field test: focus, or the laser's field, at a board's edges?
(drums1, 2026-11-19: perfect in the middle, unfinished at the sides.)"""
import time

import pytest

from gerber2rml.engine import laser_fieldtest as ft


def test_the_test_fits_the_stock_and_its_coupons_do_not_touch():
    art, heights = ft.field_test_art()
    w, h = art.size
    assert (w, h) == ft.SIZE and w <= 160 and h <= 100
    cs = ft.coupons()
    assert len(cs) == 15 + 3 * 2 * 4
    shapes = [s for c in cs for s in ft.coupon_shapes(c.x, c.y)]
    assert len(shapes) == len(art.apertures) == len(heights)
    from shapely.geometry import box
    inside = box(2, 2, w - 2, h - 2)
    for s in shapes:
        assert inside.contains(s)
    blobs = [c for c in cs]
    for i, a in enumerate(blobs):
        for b in blobs[i + 1:]:
            assert max(abs(a.x - b.x), abs(a.y - b.y)) >= 8.0


def test_every_ladder_has_each_height_once():
    by = {}
    for c in ft.coupons():
        if c.dz:
            by.setdefault(c.label.split(",")[0], []).append(c.dz)
    assert len(by) == 6
    assert all(sorted(v) == sorted(ft.LADDER_DZ) for v in by.values())


def test_groups_are_one_per_height():
    _art, heights = ft.field_test_art()
    g = ft.groups(heights)
    assert [dz for dz, _i in g] == [-0.6, -0.3, 0.0, 0.3, 0.6]
    assert sum(len(i) for _dz, i in g) == len(heights)


@pytest.fixture
def page(qt_app, monkeypatch):
    from gerber2rml.engine import xtool
    from shapely.geometry import box
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "laser-fieldtest"))
    art = xtool.LaserArt(kind="traces", outline=box(0, 0, 120, 80),
                         apertures=[box(5, 5, 9, 9)], mirrored=False)
    d = sl.StencilLaserDialog(art)
    yield d
    d.close()


def test_the_field_test_is_cut_one_height_at_a_time(qt_app, page, monkeypatch):
    from gerber2rml.gui2 import laser_fieldtest_ui as ftu
    log = []

    class Laser:
        def _json(self, method, path, body=None):
            log.append(("mode", body["state"]))

        def _goto_z(self, z):
            log.append(("z", round(z, 3)))
            return z

        def z(self):
            return 19.0

        def run(self, text):
            log.append(("run",))

        def wait(self, timeout, progress=None):
            pass

    page.laser = Laser()
    page.photo_after.setChecked(False)
    ftu.load(page)
    assert ftu.active(page) and page.name_lbl.text() == "Field test"
    page.cut()
    t0 = time.monotonic()
    while page._worker_running() and time.monotonic() - t0 < 30:
        qt_app.processEvents()
        time.sleep(0.01)
    qt_app.processEvents()
    zs = [e[1] for e in log if e[0] == "z"]
    assert zs == [18.4, 18.7, 19.0, 19.3, 19.6, 19.0]   # each height, then back
    assert len([e for e in log if e[0] == "run"]) == 5
    # Written down, so a result can be traced afterwards.
    from gerber2rml.gui2 import laserlog
    text = laserlog.path().read_text(encoding="utf-8")
    assert "etch" in text and '"field_test": true' not in text  # json per line
    assert "field_test: true" in text
    assert "bands: [[-0.6, 12], [-0.3, 12], [0.0, 30], [0.3, 12], [0.6, 12]]" in text
    assert "done" in text


def test_another_job_is_not_the_field_test(qt_app, page):
    from gerber2rml.gui2 import laser_fieldtest_ui as ftu
    ftu.load(page)
    from gerber2rml.engine import xtool
    from shapely.geometry import box
    page.show_job(xtool.LaserArt(kind="traces", outline=box(0, 0, 50, 50),
                                 apertures=[box(5, 5, 9, 9)]), "board")
    assert not ftu.active(page)
