"""The solder paste stencil and cutting it on the xTool F1 Ultra.

Fixture: ``stencil_wroom`` is the ESP32-WROOM coupon (esp32-surround-processor),
plotted with kicad-cli: 38 castellation pads and the centre pad's 9 paste windows
on B.Paste. Its holes, with the 80 um kerf, are the same size and pattern as the
stencil cut on the lab's F1 Ultra on 2026-11-15: 0.82 x 1.42 and 0.97 x 0.97 mm.
"""
import json
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from PySide6.QtWidgets import QPushButton

from gerber2rml.engine import stencil, xtool

WROOM = Path(__file__).parent / "fixtures" / "stencil_wroom"


def sizes(polys):
    return Counter(tuple(sorted((round(p.bounds[2] - p.bounds[0], 2),
                                 round(p.bounds[3] - p.bounds[1], 2)))) for p in polys)


@pytest.fixture(scope="module")
def art():
    return stencil.build_stencil(WROOM)


def test_holes_are_the_pads_less_the_kerf(art):
    assert art.side == "bottom" and art.mirrored
    assert sizes(art.apertures) == {(0.82, 1.42): 38, (0.97, 0.97): 9}
    raw = stencil.build_stencil(WROOM, kerf=0)
    assert sizes(raw.apertures) == {(0.9, 1.5): 38, (1.05, 1.05): 9}
    assert art.warnings() == []


def test_frame_is_the_outline_from_the_origin(art):
    x0, y0, x1, y1 = art.outline.bounds
    assert (round(x0, 6), round(y0, 6)) == (0, 0)
    assert art.size == pytest.approx((40.0, 36.0))
    for p in art.apertures:
        assert art.outline.contains(p)


def test_bottom_is_mirrored_and_top_is_not(art):
    plain = stencil.build_stencil(WROOM, mirror=False)
    w = art.size[0]
    a = sorted(round(p.centroid.x, 3) for p in art.apertures)
    b = sorted(round(w - p.centroid.x, 3) for p in plain.apertures)
    assert a == b


def test_missing_and_empty_layers_are_sentences(tmp_path):
    with pytest.raises(stencil.StencilError, match="B.Paste"):
        stencil.build_stencil(tmp_path)
    with pytest.raises(stencil.StencilError, match="empty"):
        stencil.build_stencil(WROOM, side="top")


def test_small_holes_are_reported(art):
    thick = stencil.build_stencil(WROOM, foil=0.4)
    assert thick.poor_release and "area ratio" in thick.warnings()[0]


def test_dxf_has_both_layers(art, tmp_path):
    p = stencil.write_stencil_dxf(art, tmp_path, "wroom")
    assert p.name == "wroom_stencil_bottom_mirrored.dxf"
    text = p.read_text()
    assert text.count("STENCIL_APERTURES") >= 47 and "OUTLINE" in text


# ---------------------------------------------------------------- the job file

def test_bed_frame_puts_top_left_at_origin(art):
    holes, outline = xtool.stencil_paths(art, (50.0, 60.0))
    xs = [x for p in outline for x, _ in p]
    ys = [y for p in outline for _, y in p]
    assert (min(xs), min(ys)) == pytest.approx((50.0, 60.0))
    assert (max(xs), max(ys)) == pytest.approx((90.0, 96.0))


def test_job_cuts_every_hole_the_full_count_in_bursts(art):
    holes, outline = xtool.stencil_paths(art, (50.0, 60.0))
    r = xtool.Recipe()
    job = xtool.stencil_job(holes, outline, r)
    lines = job.text.split("\r\n")
    assert sum(job.zones) == 47 and len(job.zones) == 4
    assert "G22" in lines and "G0Q30" in lines and "G21" not in lines
    # each hole's first cutting move carries the power: 47 holes x 30 passes
    assert sum(1 for l in lines if l.endswith("S1000F33000")) == 47 * 30
    # rests between bursts, never after the last
    rests = [i for i, l in enumerate(lines) if l.endswith("S0F60")]
    assert rests and len({l for l in lines if l.endswith("S0F60")}) <= 2
    bursts = r.rounds * len(job.zones)
    starts = sum(1 for a, b in zip(lines, lines[1:])
                 if b.endswith("S0F60") and not a.endswith("S0F60") and not a.startswith("G0"))
    assert starts == 0       # every rest begins with a jump to the park point
    parks = sum(1 for a, b in zip(lines, lines[1:]) if a.startswith("G0") and b.endswith("S0F60"))
    assert parks == bursts - 1
    # the outline marked once at half power, last
    assert sum(1 for l in lines if l.endswith("S500F33000")) == 1
    assert not any(l.startswith("G4 ") or l.startswith("G4P") for l in lines)
    assert job.seconds > (bursts - 1) * r.rest_s


def test_off_the_bed_is_refused(art):
    holes, outline = xtool.stencil_paths(art, (210.0, 10.0))
    with pytest.raises(ValueError, match="field"):
        xtool.stencil_job(holes, outline)


def test_trace_is_blue_and_faint(art):
    _, outline = xtool.stencil_paths(art, (50.0, 60.0))
    lines = xtool.trace_job(outline).split("\r\n")
    assert "G21" in lines and "G22" not in lines
    assert any(l.endswith("S60F6000") for l in lines)


# ---------------------------------------------------------------- the laser

class FakeLaser(BaseHTTPRequestHandler):
    calls = []
    z = 18.7

    def _reply(self, data=None):
        body = json.dumps({"code": 0, "msg": "Success", "data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        FakeLaser.calls.append(("GET", self.path, None))
        if self.path.startswith("/device/runningStatus"):
            return self._reply({"curMode": {"mode": "P_WORK_DONE"}})
        self._reply({})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode()
        FakeLaser.calls.append(("POST", self.path, body))
        if self.path == "/focus/control":
            d = json.loads(body)
            if d["action"] == "goTo":
                FakeLaser.z = d["Z"]
            return self._reply({"value": FakeLaser.z})
        self._reply({})

    def log_message(self, *a):
        pass


@pytest.fixture
def laser():
    FakeLaser.calls = []
    srv = HTTPServer(("127.0.0.1", 0), FakeLaser)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield xtool.F1Ultra("127.0.0.1", srv.server_address[1])
    srv.shutdown()


def test_focus_is_thickness_plus_eight_with_capital_z(laser):
    assert laser.focus(12) == pytest.approx(20.0)
    posts = [(p, json.loads(b)) for m, p, b in FakeLaser.calls if m == "POST"]
    assert posts[0] == ("/device/modeSwitch", {"state": "P_AUTOFOCUS"})
    assert ("/focus/control", {"action": "goTo", "Z": 20.0, "stopFirst": 1, "F": 300}) in posts
    assert posts[-1] == ("/device/modeSwitch", {"state": "P_IDLE"})


def test_run_uploads_the_text_and_starts_it(laser, art):
    holes, outline = xtool.stencil_paths(art, (50.0, 60.0))
    job = xtool.stencil_job(holes, outline)
    laser.run(job.text)
    m, path, body = FakeLaser.calls[-1]
    assert path == "/processing/upload?gcodeType=processing&fileType=txt&autoStart=1"
    assert body == job.text


def test_no_laser_is_a_sentence():
    with pytest.raises(xtool.LaserError, match="plugged into this PC"):
        xtool.F1Ultra("127.0.0.1", 1, timeout=1).mode()


# ---------------------------------------------------------------- the app

@pytest.fixture
def win(qt_app, monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.load_folder(str(WROOM))
    yield w
    w.close()


def test_a_board_with_paste_has_a_stencil_row(win, tmp_path):
    assert win.plan.by_key("laser_stencil") is not None
    win.export_to(tmp_path)
    assert list(tmp_path.glob("*_stencil_*.dxf"))


def test_ticked_the_export_writes_the_stencil(win, tmp_path):
    setup = win.inspector.setup
    setup.ctl.action_stencil(True)
    assert "B.Paste" in win.stencil_status()[1]
    written = win.export_to(tmp_path)
    assert written
    dxf = list(tmp_path.glob("*_stencil_bottom_mirrored.dxf"))
    assert len(dxf) == 1 and dxf[0].name in win.stencil_status()[1]


def test_the_kerf_box_reaches_the_file(win, tmp_path):
    setup = win.inspector.setup
    setup.ctl.action_stencil(True)
    setup.ctl.action_stencil_kerf(0.0)
    arts, _ = win._stencil_arts(WROOM)
    assert sizes(arts[0].apertures) == {(0.9, 1.5): 38, (1.05, 1.05): 9}


def test_the_laser_window_builds_the_job_it_shows(win, qt_app):
    from gerber2rml.gui2.stencil_laser import StencilLaserDialog
    arts, _ = win._stencil_arts(WROOM)
    d = StencilLaserDialog(arts[0], win, laser=xtool.F1Ultra("127.0.0.1", 1, timeout=1))
    d.x.setValue(50)
    d.y.setValue(60)
    holes, outline = d.paths()
    job = xtool.stencil_job(holes, outline, d.recipe())
    assert sum(job.zones) == 47 and job.passes == 30
    d.x.setValue(220)                       # off the bed: refused, said
    d.cut()
    assert "field" in d.status.text()
    d.close()


# ---------------------------------------------------------------- the camera

def _fake_calibration():
    """A camera that sees laser (X, Y) at pixel (50 + 4X, 30 + 4Y) when in
    focus, and whose dot climbs 4 px per mm of height. The grid is stored the
    way the F1 Ultra stores it: point (i, j) is laser (220 - 10i, 220 - 10j)."""
    from gerber2rml.engine import xtool_camera as cam
    n = 23
    pts = []
    for j in range(n):
        for i in range(n):
            X, Y = 220 - 10 * i, 220 - 10 * j
            pts.append(f"[{50 + 4 * X:.2f},{30 + 4 * Y:.2f}]")
    calib = {"image_src_w": 1000, "image_src_h": 1000, "grid_num_w": n,
             "data0": "".join(pts)}
    zs = [float(z) for z in range(-50, 55, 5)]
    m = []
    for z in zs:
        row = []
        for j in range(n):
            for i in range(n):
                X, Y = 220 - 10 * i, 220 - 10 * j
                row += [50 + 4 * X, 30 + 4 * Y - 4 * z]
        m.append(row)
    return cam.Calibration(calib, {"z": zs, "map": m})


def test_the_photo_comes_out_in_laser_millimetres():
    import numpy as np
    cal = _fake_calibration()
    rgb = np.zeros((1000, 1000, 3), np.uint8)
    rgb[30 + 4 * 40, 50 + 4 * 60] = 255            # something at laser (60, 40)
    bed = cal.rectify(rgb, px_per_mm=1)
    y, x = np.unravel_index(bed.sum(axis=2).argmax(), bed.shape[:2])
    assert (x, y) == (60, 40)


def test_the_dot_gives_the_height():
    import numpy as np
    cal = _fake_calibration()
    for dz in (-3.0, 0.0, 12.5):
        rgb = np.zeros((1000, 1000, 3), np.uint8)
        px, py = 50 + 4 * 110, 30 + 4 * 110 - 4 * dz
        rgb[int(py) - 2:int(py) + 3, px - 2:px + 3] = (120, 120, 255)
        dot, n = cal.find_dot(rgb)
        assert cal.height(dot) == pytest.approx(dz, abs=0.3)


def test_a_dim_dot_on_a_cut_line_is_still_found():
    """At the machine a dot on the stencil's cut outline scored 282-290 over a
    black background; a fixed 300 called that no dot at all."""
    import numpy as np
    cal = _fake_calibration()
    rgb = np.zeros((1000, 1000, 3), np.uint8)
    px, py = 50 + 4 * 110, 30 + 4 * 110
    rgb[py - 2:py + 3, px - 2:px + 3] = (20, 20, 200)     # 200 + 80 = 280
    dot, _n = cal.find_dot(rgb)
    assert cal.height(dot) == pytest.approx(0.0, abs=0.3)


def test_no_dot_is_a_sentence():
    import numpy as np
    from gerber2rml.engine.xtool_camera import CameraError
    with pytest.raises(CameraError, match="No dot"):
        _fake_calibration().find_dot(np.zeros((1000, 1000, 3), np.uint8))


def test_a_top_only_board_falls_back_to_f_paste(qt_app, monkeypatch, tmp_path):
    """Parts on the top, as on a fab-made board: B.Paste is empty, F.Paste has
    them, so the stencil is F.Paste and not mirrored."""
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    src = tmp_path / "top"
    src.mkdir()
    for p in WROOM.iterdir():
        name = p.name
        if "B_Paste" in name:
            name = name.replace("B_Paste", "F_Paste").replace(".gbp", ".gtp")
        elif "F_Paste" in name:
            name = name.replace("F_Paste", "B_Paste").replace(".gtp", ".gbp")
        (src / name).write_bytes(p.read_bytes())
    w = MainWindow()
    try:
        w.load_folder(str(src))
        arts, notes = w._stencil_arts(src)
        assert len(arts) == 1 and arts[0].side == "top" and not arts[0].mirrored
        assert len(arts[0].apertures) == 47 and notes == []
    finally:
        w.close()


# ---------------------------------------------------------------- placing and re-cutting

def test_a_quarter_turn_swaps_the_size_and_keeps_every_hole(art):
    r = xtool.rotated(art, 1)
    assert r.size == pytest.approx((art.size[1], art.size[0]))
    x0, y0, _, _ = r.outline.bounds
    assert (round(x0, 6), round(y0, 6)) == (0, 0)
    assert len(r.apertures) == len(art.apertures)
    assert sorted(round(p.area, 4) for p in r.apertures) == sorted(
        round(p.area, 4) for p in art.apertures)
    assert xtool.rotated(art, 4) is art


def test_clockwise_on_the_bed(art):
    """A point near the top-left corner on the bed goes to the top-right."""
    from shapely.geometry import Point
    w, h = art.size
    probe = stencil.StencilArtwork(side="bottom", source=None, mirrored=False,
                                   kerf=0, foil=0.1, outline=art.outline,
                                   apertures=[Point(1, h - 1).buffer(0.5)])
    (hole,), _ = xtool.stencil_paths(xtool.rotated(probe, 1), (0, 0))
    cx, cy = xtool._centroid(hole)
    assert (cx, cy) == pytest.approx((h - 1, 1), abs=0.05)


def test_only_the_chosen_holes_are_cut(art):
    holes, outline = xtool.stencil_paths(art, (50, 60), only={0, 5, 7})
    assert len(holes) == 3
    job = xtool.stencil_job(holes, outline)
    assert sum(job.zones) == 3


def test_the_timeline_covers_every_burst(art):
    holes, outline = xtool.stencil_paths(art, (50, 60))
    r = xtool.Recipe()
    job = xtool.stencil_job(holes, outline, r)
    assert len(job.timeline) == r.rounds * len(job.zones) + 1
    assert job.timeline[-1][1] == pytest.approx(job.seconds)
    assert job.at(0.0)[1] == 0 and job.at(job.seconds - 1e-3)[0] == -1
    assert [len(z) for z in job.zone_paths] == job.zones


def test_focus_points_snap_to_the_factory_grid():
    assert xtool.snap_to_grid((83.6, 121.2)) == (80.0, 120.0)
    assert xtool.snap_to_grid((-4, 300)) == (0.0, 220.0)


def test_the_laser_page_selects_turns_and_keeps_presets(qt_app, monkeypatch, art):
    from PySide6.QtCore import QRectF, QSettings
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "stencil-laser"))
    QSettings(*sl._SETTINGS).clear()
    d = sl.StencilLaserDialog(art, laser=xtool.F1Ultra("127.0.0.1", 1, timeout=1))
    d.x.setValue(50)
    d.y.setValue(60)
    # a box round the whole stencil picks every hole; a re-cut has no outline mark
    d._boxed(QRectF(40, 50, 60, 60), False)
    assert len(d.selected) == 47 and d.cut_btn.text() == "Cut 47 selected"
    d.select_none()
    d._boxed(QRectF(40, 50, 60, 60), False)
    d.selected = {0, 1}
    holes, _ = d._holes()
    assert len(holes) == 2
    # a quarter turn keeps the middle where it was
    c = d.centre()
    d.rotate(1)
    assert d.art.size == pytest.approx((36.0, 40.0)) and d.centre() == pytest.approx(c)
    assert not d.selected
    # a saved preset comes back
    d.passes.setValue(42)
    monkeypatch.setattr(sl.QInputDialog, "getText", lambda *a, **k: ("mine", True))
    d.save_preset()
    d.preset.setCurrentText("0.1 mm 304 stainless")
    assert d.passes.value() == 30
    d.preset.setCurrentText("mine")
    assert d.passes.value() == 42 and d.del_btn.isEnabled()
    d.delete_preset()
    assert d.preset.findText("mine") < 0
    QSettings(*sl._SETTINGS).clear()
    d.close()


def test_align_finds_a_moved_and_turned_stencil(qt_app, art):
    """Holes drawn dark on bright foil 4.3 mm right, 2.6 mm down and 1.5 degrees
    clockwise of where the stencil thinks they are come back to within a
    quarter of a millimetre and a few tenths of a degree."""
    import numpy as np
    from gerber2rml.engine import xtool_camera as cam
    ppm = 8
    holes, _ = xtool.stencil_paths(art, (60.0, 70.0))
    c = np.array([q for p in holes for q in p]).mean(axis=0)
    truth = [[(x + 4.3, y + 2.6) for x, y in p] for p in cam._turn(holes, c, 1.5)]
    size = int(160 * ppm)
    ink = cam._raster(truth, (0, 0), (size, size), ppm)
    rgb = np.repeat((220 - 160 * ink)[..., None], 3, axis=2).astype(np.uint8)
    a = cam.align(rgb, ppm, holes)
    assert a.ok and a.found == a.total
    assert (a.dx, a.dy) == pytest.approx((4.3, 2.6), abs=0.25)
    assert a.turn == pytest.approx(1.5, abs=0.3)


def test_align_says_no_on_a_blank_photo(qt_app, art):
    import numpy as np
    from gerber2rml.engine import xtool_camera as cam
    holes, _ = xtool.stencil_paths(art, (60.0, 70.0))
    rng = np.random.default_rng(1)
    rgb = (200 + rng.integers(0, 20, (1280, 1280, 3))).astype(np.uint8)
    assert not cam.align(rgb, 8, holes).ok


def test_the_stencil_can_be_outlined_or_hidden(qt_app, monkeypatch, art):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "stencil-laser"))
    d = sl.StencilLaserDialog(art, laser=xtool.F1Ultra("127.0.0.1", 1, timeout=1))
    d.set_look("outlines")
    assert d.item.isVisible()
    assert all(h.brush().style() == Qt.NoBrush for h in d.item.holes)
    QTest.keyClick(d.view, Qt.Key_H)
    assert d.look == "hidden" and not d.item.isVisible()
    assert not d._focus_mark.isVisible()
    QTest.keyClick(d.view, Qt.Key_H)
    assert d.look == "filled" and d.item.isVisible()
    assert all(h.brush().style() != Qt.NoBrush for h in d.item.holes)
    d.close()


def test_r_turns_the_artwork_like_the_buttons(qt_app, monkeypatch, art):
    """R is Turn right, Shift+R is Turn left, and neither does anything while
    the buttons are off, as they are during a job."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "stencil-laser"))
    d = sl.StencilLaserDialog(art, laser=xtool.F1Ultra("127.0.0.1", 1, timeout=1))
    start = d.turns
    QTest.keyClick(d.view, Qt.Key_R)
    assert d.turns == (start + 1) % 4
    QTest.keyClick(d.view, Qt.Key_R, Qt.ShiftModifier)
    QTest.keyClick(d.view, Qt.Key_R, Qt.ShiftModifier)
    assert d.turns == (start - 1) % 4
    d.rot_l.setEnabled(False)
    d.rot_r.setEnabled(False)
    QTest.keyClick(d.view, Qt.Key_R)
    assert d.turns == (start - 1) % 4
    d.close()


# ---------------------------------------------------------------- mask and silkscreen

BUCK = Path(__file__).parent / "fixtures" / "mosfet_test"


def test_hatch_fills_a_shape_line_by_line():
    from shapely.geometry import box
    segs = xtool.hatch([box(10, 10, 12, 11)], 0.1, 0)
    assert len(segs) == 10 and all(a[0] < b[0] for a, b in segs)     # one way
    segs = xtool.hatch([box(10, 10, 12, 11)], 0.1, 90)
    assert len(segs) == 20


def test_the_mask_recipe_is_sphawes_remove_solder_mask():
    r = xtool.SPHAWES_REMOVE_MASK
    assert (r.power, r.speed, r.frequency, r.passes, r.lines_per_cm) == (40, 800, 30, 6, 300)
    assert r.cross_hatch and r.one_way and r.interval == pytest.approx(1 / 30)


def test_fill_job_cross_hatches_every_pass():
    from shapely.geometry import box
    job = xtool.fill_job([box(100, 100, 102, 101)], [], xtool.SPHAWES_REMOVE_MASK)
    lines = job.text.split("\r\n")
    cuts = [l for l in lines if l.endswith("S400F48000")]
    assert len(cuts) == 3 * 30 + 3 * 60            # 3 passes each way at 0.033 mm
    assert "G22" in lines and "G0Q30" in lines
    assert len(job.timeline) == 6


def test_drilled_holes_land_in_the_mask_openings():
    from gerber2rml.engine import soldermask
    from gerber2rml.loader import _find_layer
    raw = soldermask._read_outline(_find_layer(BUCK, "*-Edge_Cuts.*", "*.gm1"))
    art = soldermask.build_mask(BUCK, mirror=True)
    feats = xtool.drill_features(BUCK, True, raw)
    assert len(feats) == 27
    assert all(any(o.contains(f.centroid) for o in art.openings) for f in feats)


@pytest.mark.parametrize("action,kind,run,preset,passes", [
    ("action_mask_laser", "mask", "Open the mask",
     "RemoveSolderMask · concentric rings", 4),
    ("action_silk_laser", "silk", "Mark the silkscreen",
     "Silkscreen on mask · 15 % × 2, rings", 2)])
def test_mask_and_silkscreen_open_the_laser_page(qt_app, monkeypatch, action, kind,
                                                 run, preset, passes):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2 import stencil_laser as sl
    from gerber2rml.gui2.window import MainWindow
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "stencil-laser"))
    w = MainWindow()
    try:
        w.load_folder(str(BUCK))
        getattr(w, action)()
        d = w.laser_view
        assert w.mode() == "laser" and w.modes.currentWidget() is d
        assert d.embedded and not d.isWindow()
        assert d.kind == kind and d.cut_btn.text() == run
        assert d.preset.currentText() == preset
        assert len(d.base_art.features) == 27
        d.x.setValue(40)
        d.y.setValue(40)
        job = xtool.fill_job(d._shapes(), [], d.recipe())
        assert job.passes == passes and job.seconds > 0
        d.close()
    finally:
        w.close()


# ---------------------------------------------------------------- laser traces

def test_build_laser_traces_with_drill_spots_and_dxf(tmp_path):
    art_with = xtool.build_laser_traces(BUCK, mirror=True, spot_drills=True)
    art_no = xtool.build_laser_traces(BUCK, mirror=True, spot_drills=False)
    assert art_with.kind == "traces" and art_with.mirrored
    assert len(art_with.drills) == 27 and len(art_with.features) == 27
    # Drill spots open circular apertures inside pads, creating more cleared polygons
    assert len(art_with.apertures) > len(art_no.apertures)
    dxf = xtool.write_traces_dxf(art_with, tmp_path, "buck")
    assert dxf.name == "buck_traces_bottom_mirrored.dxf"
    text = dxf.read_text()
    assert "LASER_TRACES" in text and "OUTLINE" in text


def test_concentric_traces_job_beats_rubout_and_clears_drills():
    art = xtool.build_laser_traces(BUCK, mirror=True, spot_drills=True)
    # 1. Concentric isolation (FlatCAM style)
    con_job = xtool.traces_job(art, (40.0, 40.0), xtool.DEFAULT_TRACES_RECIPE)
    lines = con_job.text.split("\r\n")
    assert "G22" in lines and "G0Q30" in lines and "G21" not in lines
    assert any(l.endswith("S1000F36000") for l in lines)
    # 10 passes, then the edge of the field's 5 more (xtool.EDGE_PASSES).
    assert len(con_job.timeline) == 10 + xtool.EDGE_PASSES
    # Alternating offset sweep order between round 0 and round 1
    groups, _ = xtool.traces_rings(art, (40.0, 40.0), xtool.DEFAULT_TRACES_RECIPE)
    assert len(groups) == 6
    # Verify round 0 starts at offset 0 and round 1 starts at offset -1 (reversed)
    g0_moves = [l for l in lines if l.startswith("G0X") or l.startswith("G1X")]
    first_x0, first_y0 = groups[0][0][0]
    assert g0_moves[0] == f"G0X{first_x0:.3f}Y{first_y0:.3f}"
    # Drill hole centre spotting clears pilot circles inside pads
    art_no = xtool.build_laser_traces(BUCK, mirror=True, spot_drills=False)
    assert len(art.apertures) > len(art_no.apertures)

    # 2. Full rubout (XCS style)
    rub_art = xtool.build_laser_traces(BUCK, mirror=True, strategy="rubout",
                                       lines_per_cm=120.0, spot_drills=True)
    rub_r = xtool.TracesRecipe(strategy="rubout", lines_per_cm=120.0, passes=10)
    rub_job = xtool.traces_job(rub_art, (40.0, 40.0), rub_r)

    def _stats(gcode_lines):
        g0s = [l for l in gcode_lines if l.startswith("G0X")]
        g1s = [l for l in gcode_lines if l.startswith("G1X")]
        return len(g0s), len(g1s)

    con_g0, con_g1 = _stats(lines)
    rub_g0, rub_g1 = _stats(rub_job.text.split("\r\n"))
    assert rub_g0 / con_g0 > 20


def test_laser_dialog_traces_strategies_and_job_switcher(qt_app, monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2 import stencil_laser as sl
    from gerber2rml.gui2.window import MainWindow
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "stencil-laser"))
    w = MainWindow()
    try:
        w.load_folder(str(BUCK))
        w.action_traces_laser()
        d = w.laser_view
        assert w.mode() == "laser" and w.modes.currentWidget() is d
        assert d.embedded and not d.isWindow()
        assert d.kind == "traces" and d.cut_btn.text() == "Etch the traces"
        assert d.job_switch.current() == "traces"
        d.x.setValue(45.0)
        d.y.setValue(55.0)
        n_concentric = len(d.art.apertures)

        # Switch strategy to rubout -> polygon count changes live
        idx_rub = d.strategy.findData("rubout")
        d.strategy.setCurrentIndex(idx_rub)
        assert d.recipe().strategy == "rubout"
        assert d.offsets_field.isHidden()
        assert len(d.art.apertures) != n_concentric

        # Switch back to concentric and change isolation offsets & drill spotting
        idx_con = d.strategy.findData("concentric")
        d.strategy.setCurrentIndex(idx_con)
        assert not d.offsets_field.isHidden()
        d.spot_drills.setChecked(False)
        n_no_drill = len(d.art.apertures)
        d.spot_drills.setChecked(True)
        assert len(d.art.apertures) > n_no_drill

        # Switch jobs right inside the laser window, preserving X/Y
        d.switch_kind("mask")
        assert d.kind == "mask" and d.job_switch.current() == "mask"
        assert d.cut_btn.text() == "Open the mask"
        assert (d.x.value(), d.y.value()) == pytest.approx((45.0, 55.0))

        d.switch_kind("silk")
        assert d.kind == "silk" and d.job_switch.current() == "silk"
        assert d.cut_btn.text() == "Mark the silkscreen"
        assert (d.x.value(), d.y.value()) == pytest.approx((45.0, 55.0))

        # Switching back to traces works and preserves placement
        d.switch_kind("traces")
        assert d.kind == "traces" and d.job_switch.current() == "traces"
        assert (d.x.value(), d.y.value()) == pytest.approx((45.0, 55.0))
        d.close()
    finally:
        w.close()


def test_setup_page_laser_traces_dxf_export(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    try:
        w.load_folder(str(BUCK))
        from gerber2rml.engine import method as fab
        w.action_method(fab.LASER)              # a laser board: its file too
        w.action_laser_offsets(8)
        assert w._laser_offsets == 8
        w.export_to(tmp_path)
        dxf = list(tmp_path.glob("*_traces_bottom_mirrored.dxf"))
        assert len(dxf) == 1 and dxf[0].name in w.laser_traces_status()[1]
    finally:
        w.close()


def test_laser_rail_tab_and_header_button(qt_app, monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2 import stencil_laser as sl
    from gerber2rml.gui2.window import MainWindow
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "stencil-laser"))
    w = MainWindow()
    try:
        w.load_folder(str(BUCK))
        assert w.plan.by_key("laser") is None          # no hub row any more
        (btn,) = [b for b in w.mode_switch.findChildren(QPushButton)
                  if b.text() == "Laser"]
        btn.click()
        d = w.laser_view
        assert w.mode() == "laser" and w.modes.currentWidget() is d
        assert d.embedded and not d.isWindow()
        assert d.kind == "traces"
        d.close()
    finally:
        w.close()


def test_curtain_drive_top_traces_can_be_selected(qt_app, monkeypatch):
    from gerber2rml.gui2 import stencil_laser as sl
    from gerber2rml.gui2.window import MainWindow
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "curtain-laser"))
    w = MainWindow()
    try:
        w.load_folder(str(Path(__file__).parent / "fixtures" / "curtain_drive"))
        w.action_traces_laser()
        d = w.laser_view
        assert w.mode() == "laser" and w.modes.currentWidget() is d
        assert d.embedded and not d.isWindow()
        assert d.art.side == "bottom"
        assert d.art.copper.area < 10  # B.Cu contains only four small shapes.
        d.x.setValue(45)
        d.y.setValue(55)
        d.copper_side.setCurrentIndex(d.copper_side.findData("top"))
        assert d.art.side == "top" and not d.art.mirrored
        assert d.art.copper.area > 3000  # The routed circuit is on F.Cu.
        assert "F.Cu (top)" in d.size_lbl.text()
        assert len(d.item.holes) == len(d.art.apertures) > 4
        assert (d.x.value(), d.y.value()) == pytest.approx((45, 55))
        assert xtool.traces_job(d.art, (45, 55), d.recipe()).seconds > 0
        # Missing jobs must not discard the selected copper face.
        d.switch_kind("stencil")
        assert d.kind == "traces" and d.art.side == "top"
        d.copper_side.setCurrentIndex(d.copper_side.findData("bottom"))
        assert d.art.side == "bottom" and d.art.mirrored
        assert "B.Cu (bottom)" in d.size_lbl.text()
        d.close()
    finally:
        w.close()


def test_the_mask_has_a_top_face_too(qt_app, monkeypatch):
    """A two-sided board gets ink on both faces (the analog synth, 2026-11-22):
    the face switch opens F.Mask as drawn, B.Mask mirrored."""
    from gerber2rml.gui2 import stencil_laser as sl
    from gerber2rml.gui2.window import MainWindow
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "mask-faces"))
    w = MainWindow()
    try:
        w.load_folder(str(Path(__file__).parent / "fixtures" / "mosfet_test"))
        w.action_traces_laser()
        d = w.laser_view
        d.switch_kind("mask")
        assert d.kind == "mask" and d.art.side == "bottom" and d.art.mirrored
        assert d.copper_side_field.isVisibleTo(d)
        assert "B.Mask (bottom)" in d.size_lbl.text()
        n = len(d.art.apertures)
        d.copper_side.setCurrentIndex(d.copper_side.findData("top"))
        assert d.kind == "mask" and d.art.side == "top" and not d.art.mirrored
        assert "F.Mask (top)" in d.size_lbl.text()
        assert len(d.art.apertures) == n > 0
        # Back on the copper the face stays where it was put.
        d.switch_kind("traces")
        assert d.kind == "traces" and d.art.side == "top"
        d.close()
    finally:
        w.close()


def test_vector_passes_remove_moves_that_collapse_at_output_precision():
    paths = [[(0, 0), (0.0001, -0.0001), (1, 0), (1.0001, 0), (0, 0)],
             [(2, 2), (2.0001, 2.0001)], []]
    lines = xtool._passes(paths, power=100, speed=600, n=2)
    assert lines == ["G0X0.000Y0.000", "G1X1.000Y0.000S1000F36000",
                     "G1X0.000Y0.000"] * 2


def test_curtain_vectors_never_emit_a_stationary_cutting_move():
    import re
    folder = Path(__file__).parent / "fixtures" / "curtain_drive"
    art = xtool.build_laser_traces(folder, side="top", mirror=False)
    recipe = xtool.TracesRecipe(passes=1)
    job = xtool.traces_job(art, (40, 40), recipe)
    previous = None
    cuts = 0
    for line in job.text.splitlines():
        match = re.match(r"G([01])X([-\d.]+)Y([-\d.]+)", line)
        if not match:
            continue
        position = float(match[2]), float(match[3])
        if match[1] == "1":
            assert position != previous
            cuts += 1
        previous = position
    assert cuts > 1000
