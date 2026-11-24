"""A solder mask that hides the pads (black): the job is lined up on the
holes it leaves clear, by a ring burnt round each (2026-11-24)."""
import time

import numpy as np
import pytest
from shapely.geometry import Point, box

from gerber2rml.engine import xtool, xtool_camera as cam
from gerber2rml.gui2 import laser_autocal as ac
from gerber2rml.gui2 import stencil_laser as sl

MASK = (28, 28, 30)             # black ink
COPPER = (200, 140, 100)        # what a burnt ring shows
MOUNTS = [(4, 4, 3.2), (96, 4, 3.2), (96, 56, 3.2), (4, 56, 3.2)]
PADS = [(30, 20, 1.0), (70, 45, 1.0), (50, 30, 0.8)]


def _disc(img, px, at, r, colour):
    """Paint a disc (bed mm) into ``img``, touching only its own corner."""
    k = int(np.ceil(r * px)) + 2
    cx, cy = at[0] * px, at[1] * px
    j0, i0 = int(cy) - k, int(cx) - k
    yy, xx = np.mgrid[j0:j0 + 2 * k + 1, i0:i0 + 2 * k + 1]
    m = (xx - cx) ** 2 + (yy - cy) ** 2 <= (r * px) ** 2
    img[j0:j0 + 2 * k + 1, i0:i0 + 2 * k + 1][m] = colour


def _ring(img, px, at, r0, r1, colour):
    k = int(np.ceil(r1 * px)) + 2
    cx, cy = at[0] * px, at[1] * px
    j0, i0 = int(cy) - k, int(cx) - k
    yy, xx = np.mgrid[j0:j0 + 2 * k + 1, i0:i0 + 2 * k + 1]
    rr = np.hypot(xx - cx, yy - cy) / px
    img[j0:j0 + 2 * k + 1, i0:i0 + 2 * k + 1][(rr >= r0) & (rr <= r1)] = colour


@pytest.mark.parametrize("hole", [(8, 8, 8), (110, 110, 105)])
def test_a_hole_is_found_whether_it_reads_dark_or_bright(hole):
    px = 16
    img = np.zeros((40 * px, 40 * px, 3), np.uint8)
    img[...] = MASK if hole[0] > 50 else COPPER
    _disc(img, px, (20.37, 19.81), 1.6, hole)
    got = cam.hole_centre(img.astype(np.float32).mean(axis=2), px, 3.2,
                          (20.0, 20.0))
    assert got == pytest.approx((20.37, 19.81), abs=0.05)


def test_no_hole_is_found_where_nothing_stands_out():
    px = 16
    img = np.full((40 * px, 40 * px), 30.0, np.float32)
    assert cam.hole_centre(img, px, 3.2, (20.0, 20.0)) is None


@pytest.mark.parametrize("hole", [(5, 5, 5), (120, 120, 115)])
def test_rings_round_clear_holes_say_how_far_the_job_is_off(hole):
    """Rings the camera shows 0.3 mm off, holes really 0.5 mm off the job:
    the job moves by the holes' error alone."""
    px, size = 16, 70
    before = np.zeros((size * px, size * px, 3), np.uint8)
    before[...] = MASK
    cam_err, job_err = (0.3, -0.2), (0.4, 0.3)
    holes = [(10, 10, 3.2), (58, 12, 3.2), (56, 55, 3.2), (12, 57, 3.2)]
    for x, y, d in holes:
        _disc(before, px, (x + job_err[0] + cam_err[0],
                           y + job_err[1] + cam_err[1]), d / 2, hole)
    after = before.copy()
    rings = xtool.rings_round_holes(holes)
    for (x, y, d), (ring, pieces) in zip(holes, rings):
        assert all(not p.interiors for p in pieces)      # the fill's rings close
        assert sum(p.area for p in pieces) == pytest.approx(ring.area, rel=1e-6)
        assert not ring.intersects(Point(x, y).buffer(d / 2 + 0.7))
        r0 = d / 2 + xtool.RING_GAP_MM
        _ring(after, px, (x + cam_err[0], y + cam_err[1]), r0,
              r0 + xtool.RING_WIDTH_MM, COPPER)
    tests = [(ring, h) for (ring, _p), h in zip(rings, holes)]
    fit = cam.fit_marks_to_holes(before, after, px, tests, either=True)
    assert fit is not None and fit.used == 4 and fit.agrees
    assert (fit.dx, fit.dy) == pytest.approx(job_err, abs=0.06)
    assert abs(fit.turn) < 0.1


@pytest.fixture
def page(qt_app, monkeypatch):
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "black-mask"))
    holes = MOUNTS + PADS
    art = xtool.LaserArt(
        kind="mask", outline=box(0, 0, 100, 60), mirrored=False,
        apertures=[Point(x, y).buffer(d / 2 + 0.5) for x, y, d in PADS],
        features=[Point(x, y).buffer(d / 2, 32) for x, y, d in holes],
        drills=list(holes))
    d = sl.StencilLaserDialog(art)
    d.x.setValue(60.0)
    d.y.setValue(70.0)
    yield d
    if d._worker is not None:
        d._worker.wait(10000)
    d.close()


def _run(qt_app, d, monkeypatch, start, secs=60):
    msgs = []
    monkeypatch.setattr(d, "_done", lambda m, w: msgs.append((m, w)))
    start()
    t0 = time.monotonic()
    while not msgs and time.monotonic() - t0 < secs:
        qt_app.processEvents()
        time.sleep(0.02)
    assert msgs, "the step never ended"
    return msgs[0]


def test_a_black_mask_ticks_only_the_holes_it_leaves_clear(page):
    d = page
    assert not d.opaque.isChecked()              # a mask you can see through
    assert len(d._clear_holes()) == len(MOUNTS + PADS)
    d.opaque.setChecked(True)
    got = d._clear_holes()
    assert len(got) == 4 and all(h[2] == pytest.approx(3.2, abs=0.01) for h in got)
    assert "ø 3.2" in d.auto_reference_list.item(0).text()
    d.opaque.setChecked(False)
    assert len(d._clear_holes()) == len(MOUNTS + PADS)


def test_the_ring_line_up_moves_the_job_onto_its_clear_holes(
        qt_app, page, monkeypatch):
    d = page
    d.opaque.setChecked(True)
    px = sl.TEST_FIRE_PX_PER_MM
    n = int(220 * px)
    job_err, cam_err = (0.45, -0.3), (0.2, 0.25)
    drawn = d._clear_holes()
    before = np.zeros((n, n, 3), np.uint8)
    before[...] = MASK
    for x, y, r in drawn:
        _disc(before, px, (x + job_err[0] + cam_err[0],
                           y + job_err[1] + cam_err[1]), r / 2, (110, 110, 105))
    after = before.copy()
    for x, y, r in drawn:
        r0 = r / 2 + xtool.RING_GAP_MM
        _ring(after, px, (x + cam_err[0], y + cam_err[1]), r0,
              r0 + xtool.RING_WIDTH_MM, COPPER)
    sent = []
    monkeypatch.setattr(d, "_raw_photo", lambda like=None: "b" if sent else "a")
    monkeypatch.setattr(d, "_photo", lambda ppm=sl._PX_PER_MM, raw=None: (
        after if raw == "b" else before)[::px // ppm, ::px // ppm].copy())
    monkeypatch.setattr(d.laser, "run", lambda text: sent.append(text))
    monkeypatch.setattr(d.laser, "wait", lambda *a, **k: None)
    msg, warn = _run(qt_app, d, monkeypatch, d.line_up_at_clear_holes)
    assert not warn and "Lined up at 4 of 4 holes" in msg, msg
    assert len(sent) == 1 and "G1" in sent[0]
    for (x, y, _r), (nx, ny, _n) in zip(drawn, d._clear_holes()):
        assert (nx - x, ny - y) == pytest.approx(job_err, abs=0.08)
    assert not d.line_up.isChecked()             # rework stays put
    assert d._last_lineup is not None


def test_rings_no_hole_answers_do_not_move_the_job(qt_app, page, monkeypatch):
    d = page
    d.opaque.setChecked(True)
    px = sl.TEST_FIRE_PX_PER_MM
    n = int(220 * px)
    blank = np.zeros((n, n, 3), np.uint8)
    blank[...] = MASK                            # holes that do not show
    monkeypatch.setattr(d, "_raw_photo", lambda like=None: "a")
    monkeypatch.setattr(d, "_photo", lambda ppm=sl._PX_PER_MM, raw=None:
                        blank[::px // ppm, ::px // ppm].copy())
    monkeypatch.setattr(d.laser, "run", lambda text: None)
    monkeypatch.setattr(d.laser, "wait", lambda *a, **k: None)
    at = (d.x.value(), d.y.value())
    msg, _warn = _run(qt_app, d, monkeypatch, d.line_up_at_clear_holes)
    assert "NOT moved" in msg
    assert (d.x.value(), d.y.value()) == at
    assert d._last_lineup is None


def test_the_ring_line_up_needs_two_ticked_holes(page):
    d = page
    d.opaque.setChecked(True)
    d._check_auto_references(False)
    d.line_up_at_clear_holes()
    assert "Tick 2 to 8 holes" in d.status.text()


def test_rings_are_never_burnt_round_every_pad(qt_app, monkeypatch):
    """A board without mounting holes: ticking the box leaves every hole
    ticked, and that many are refused."""
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "black-mask"))
    holes = [(5 + 7 * i, 10 + (i % 3) * 15, 1.0) for i in range(12)]
    art = xtool.LaserArt(
        kind="mask", outline=box(0, 0, 100, 60), mirrored=False,
        apertures=[Point(x, y).buffer(1.0) for x, y, _d in holes],
        features=[Point(x, y).buffer(d / 2, 32) for x, y, d in holes],
        drills=list(holes))
    d = sl.StencilLaserDialog(art)
    sent = []
    monkeypatch.setattr(d.laser, "run", lambda text: sent.append(text))
    d.opaque.setChecked(True)
    assert "no two holes 2 mm or wider" in d.status.text()
    d.line_up_at_clear_holes()
    assert "12 are ticked" in d.status.text() and not sent
    d.close()


def test_calibrate_finds_a_black_board_on_its_clear_holes(
        qt_app, page, monkeypatch):
    """Only the mounting holes show, bright against the mask; the pads'
    holes are under the ink."""
    d = page
    d.opaque.setChecked(True)
    px = ac.WIDE_PX_PER_MM
    n = int(220 * px)
    art = xtool.rotated(d.base_art, d.turns, d.fine)
    real = d._features(art, (95.0, 30.0))        # where the board really is
    assert len(real) == 4
    photo = np.zeros((n, n, 3), np.uint8)
    photo[...] = (150, 150, 150)                 # the bed
    photo[int(30 * px):int(90 * px), int(95 * px):int(195 * px)] = MASK
    for ring in real:
        xs, ys = [q[0] for q in ring], [q[1] for q in ring]
        _disc(photo, px, ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2),
              1.6, (150, 150, 150))
    monkeypatch.setattr(d, "_photo", lambda *a, **k: photo)
    msg, warn = _run(qt_app, d, monkeypatch, lambda: ac.find_board(d))
    assert not warn and d._autocal_found is True, msg
    got = d._middle(d._features(d.art, d.origin()))
    assert np.hypot(*(got - d._middle(real))) < 0.5


def test_calibrate_on_a_black_mask_burns_rings_not_pads(qt_app, page, monkeypatch):
    page.opaque.setChecked(True)
    steps = [s[0] for s in ac.AutoCalibration(page).steps]
    assert steps == ["Find the board", "Autofocus", "Rings at the mounting holes"]
    page.opaque.setChecked(False)
    steps = [s[0] for s in ac.AutoCalibration(page).steps]
    assert steps[-1] == "Test pads"
