"""Calibrate: find the board, autofocus, camera and holes, focus map, then a
report - one press, with Cut left to the person (2026-11-19)."""
import time

import pytest
from shapely.geometry import box

from gerber2rml.engine import laser_focus as lf
from gerber2rml.engine import xtool
from gerber2rml.gui2 import laser_autocal as ac


@pytest.fixture
def page(qt_app, monkeypatch):
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "laser-autocal"))
    art = xtool.LaserArt(kind="traces", outline=box(0, 0, 120, 80),
                         apertures=[box(5, 5, 9, 9)], mirrored=False)
    d = sl.StencilLaserDialog(art)
    yield d
    # A job's thread says it is finished just before it ends: let it end
    # before the page goes, or deleting the page under it can crash.
    if d._worker is not None:
        d._worker.wait(10000)
    d.close()


def _step(page, state=None, result="ok", warn=False):
    """A stand-in for one of the page's steps: a worker that ends at once."""
    def run(*_a, **_k):
        def done(_r):
            if state:
                state()
            return result
        if warn:
            page._start(lambda _p: (_ for _ in ()).throw(RuntimeError(result)),
                        "…", done)
        else:
            page._start(lambda _p: None, "…", done)
    return run


def _wait(qt_app, page, secs=10):
    t0 = time.monotonic()
    while getattr(page, "_autocal_report", None) is None \
            and time.monotonic() - t0 < secs:
        qt_app.processEvents()
        time.sleep(0.01)
    return page._autocal_report


def _all_good(page, monkeypatch, fmap_spread=0.2):
    page._autocal_report = None
    monkeypatch.setattr(ac, "find_board", lambda p: _step(
        p, lambda: setattr(p, "_autocal_found", True),
        "Board found on 4 of 4 holes")())
    monkeypatch.setattr(page, "autofocus", _step(page, result="In focus."))
    monkeypatch.setattr(page, "proof", _step(page, lambda: setattr(
        page, "_last_proof", {"camera": (0.1, -0.2), "job": (0.3, 0.1),
                              "turn": 0.1, "holes": (20, 20)}),
        "Proof on 6 marks."))
    fmap = lf.FocusMap([(60, 60, 0.0), (100, 60, fmap_spread), (80, 90, 0.1)],
                       20.0, [])
    monkeypatch.setattr(ac._lfu, "measure", lambda p: _step(
        p, lambda: setattr(p, "_focus_map", fmap), "Focus map: fine.")())


def test_calibrate_runs_every_step_and_says_ready(qt_app, page, monkeypatch):
    _all_good(page, monkeypatch)
    ac.start(page)
    r = _wait(qt_app, page)
    assert r["ok"] and r["complete"]
    assert r["verdict"].startswith("Ready to cut")
    assert [l[:3] for l in r["lines"]] == ["✓ F", "✓ A", "✓ C", "✓ F"]
    assert "Ready to cut" in page.proof_note.text()
    assert page.cut_btn.isEnabled()


def test_a_failed_step_stops_the_run_and_cuts_nothing(qt_app, page, monkeypatch):
    _all_good(page, monkeypatch)
    monkeypatch.setattr(page, "proof", _step(page, result="The proof marks "
                                             "did not show", warn=True))
    mapped = []
    monkeypatch.setattr(ac._lfu, "measure", lambda p: mapped.append(1))
    cut = []
    monkeypatch.setattr(page, "cut", lambda *a: cut.append(1))
    ac.start(page)
    r = _wait(qt_app, page)
    assert not r["complete"] and "Camera and holes" in r["verdict"]
    assert r["lines"][-1].startswith("✗ Camera and holes")
    assert mapped == [] and cut == []


def test_a_bowed_sheet_is_called_out(qt_app, page, monkeypatch):
    _all_good(page, monkeypatch, fmap_spread=1.6)
    ac.start(page)
    r = _wait(qt_app, page)
    assert r["complete"] and not r["ok"]
    assert any("out of flat" in w for w in r["warnings"])


def test_calibrate_is_only_for_a_loaded_traces_job(qt_app, monkeypatch):
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "laser-autocal"))
    d = sl.StencilLaserDialog(None)              # nothing loaded
    started = []
    monkeypatch.setattr(ac, "AutoCalibration", lambda p: started.append(1))
    ac.start(d)
    assert started == []
    d.close()


def _drilled_page(qt_app, monkeypatch, holes):
    from shapely.geometry import Point
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "laser-autocal"))
    feats = [Point(x, y).buffer(d / 2, 32) for x, y, d in holes]
    art = xtool.LaserArt(kind="traces", outline=box(0, 0, 100, 60),
                         apertures=[box(40, 25, 60, 35)], mirrored=False,
                         features=feats, drills=list(holes))
    return sl.StencilLaserDialog(art)


def _photo_with_holes(paths, px=ac.WIDE_PX_PER_MM):
    """The bed, light, with the holes dark where ``paths`` (bed rings) are."""
    import numpy as np
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF
    n = int(220 * px)
    img = QImage(n, n, QImage.Format_RGB888)
    img.fill(QColor(200, 150, 90))               # copper
    p = QPainter(img)
    p.setBrush(QColor(20, 20, 20))
    p.setPen(QColor(20, 20, 20))
    for ring in paths:
        p.drawPolygon(QPolygonF([QPointF(x * px, y * px) for x, y in ring]))
    p.end()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(n, img.bytesPerLine())
    return a[:, :n * 3].reshape(n, n, 3).copy()


def test_the_board_is_found_anywhere_on_the_bed(qt_app, monkeypatch):
    holes = [(4, 4, 3.2), (96, 4, 3.2), (96, 56, 3.2), (4, 56, 3.2),
             (30, 20, 1.0), (70, 45, 1.2)]
    d = _drilled_page(qt_app, monkeypatch, holes)
    # Where the board really is: turned a quarter, far from the middle.
    art = xtool.rotated(d.base_art, d.turns + 1, d.fine)
    w, h = art.size
    real = d._hole_paths(art, (40.0, 20.0))
    photo = _photo_with_holes(real)
    monkeypatch.setattr(d, "_photo", lambda *a, **k: photo)
    d.x.setValue(150.0)                          # the drawing is elsewhere
    d.y.setValue(150.0)
    msgs = []
    monkeypatch.setattr(d, "_done", lambda m, w: msgs.append((m, w)))
    ac.find_board(d)
    t0 = time.monotonic()
    while not msgs and time.monotonic() - t0 < 60:
        qt_app.processEvents()
        time.sleep(0.02)
    assert msgs and not msgs[0][1], msgs
    assert d._autocal_found is True
    import numpy as np
    got = d._middle(d._hole_paths())
    want = d._middle(real)
    assert np.hypot(*(got - want)) < 0.5         # the lock refines the rest
    if d._worker is not None:
        d._worker.wait(10000)
    d.close()
