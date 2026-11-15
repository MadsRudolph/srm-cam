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


def test_off_by_default_and_hidden(win, tmp_path):
    setup = win.inspector.setup
    assert not setup.stencil.isChecked()
    assert setup.stencil_cut_btn.isHidden()
    win.export_to(tmp_path)
    assert not list(tmp_path.glob("*stencil*"))


def test_ticked_the_export_writes_the_stencil(win, tmp_path):
    setup = win.inspector.setup
    setup.stencil.setChecked(True)
    assert not setup.stencil_cut_btn.isHidden()
    assert "B.Paste" in win.stencil_status()[1]
    written = win.export_to(tmp_path)
    assert written
    dxf = list(tmp_path.glob("*_stencil_bottom_mirrored.dxf"))
    assert len(dxf) == 1 and dxf[0].name in win.stencil_status()[1]


def test_the_kerf_box_reaches_the_file(win, tmp_path):
    setup = win.inspector.setup
    setup.stencil.setChecked(True)
    setup.stencil_kerf.setValue(0.0)
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
