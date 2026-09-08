"""Bed levelling, the parts ported from the first interface.

Three things the setup sheet's level page lacked and the original had:

* the drift check - re-touch the reference every N points and correct the
  whole grid for how far it moved;
* the mesh check - the flaky point no smooth surface explains, and the
  place where the grid is too coarse, with the missing lines added in one
  click;
* the top traces of a dowel job, re-written to the top face's map. The map
  was measured and never used.

Offscreen, with the probe driver faked: nothing here touches a port.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QPushButton, QTableWidgetItem

from gerber2rml.gui2 import dialogs, leveling
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def loaded(qt_app):
    w = MainWindow()
    w.resize(1200, 800)
    w.load_folder(str(FIXT))
    yield w
    w.close()


def _window(monkeypatch, mode):
    monkeypatch.setenv("SRM_CAM_MODE", mode)
    w = MainWindow()
    w.resize(1200, 800)
    w.load_folder(str(FIXT))
    return w


def _rows(zfn, xs=(10.0, 50.0, 90.0), ys=(10.0, 50.0, 90.0)):
    return [[f"{x:.3f}", f"{y:.3f}", f"{zfn(x, y):.4f}"] for y in ys for x in xs]


def _sheet_stub(monkeypatch, seen, press=None):
    """Record what a Sheet shows, and press the named button if any."""
    def fake_exec(self):
        seen.append({
            "title": self.windowTitle(),
            "text": "\n".join(lb.text() for lb in self.findChildren(QLabel)),
            "buttons": [b.text() for b in self.findChildren(QPushButton)]})
        if press:
            for b in self.findChildren(QPushButton):
                if b.text() == press:
                    b.click()
        return 0
    monkeypatch.setattr(dialogs.Sheet, "exec", fake_exec)


# ------------------------------------------------------------ the drift check
def test_the_probe_run_carries_the_drift_check_and_publishes_the_correction(
        qt_app, monkeypatch):
    """ProbeRun hands ``retouch_every`` to the driver, and when the driver
    corrected the set it re-publishes it BEFORE finishing, so the page can
    refill the table before it advises on it."""
    calls = {}

    def fake_probe_grid(port, points, on_result=None, should_abort=None,
                        retouch_every=0, drift_log=None, **kw):
        calls["retouch_every"] = retouch_every
        res = []
        for pid, x, y in points:
            d = {"id": pid, "x": x, "y": y, "z": -56000 - 30 * pid}
            on_result(dict(d))
            res.append(d)
        drift_log.extend([{"after": 0, "z": -56000}, {"after": 2, "z": -56060}])
        for d in res:
            d["z_raw"] = d["z"]
            d["z"] = -56000
        return res
    import gerber2rml.engine.spi_probe as sp
    monkeypatch.setattr(sp, "probe_grid", fake_probe_grid)
    order = []
    run = leveling.ProbeRun("COMX", [(0, 0, 0), (1, 1000, 0)], lambda: False,
                            retouch_every=4)
    run.point.connect(lambda d: order.append(("point", d["z"])))
    run.drift.connect(lambda um: order.append(("drift", um)))
    run.corrected.connect(lambda res: order.append(("corrected", [r["z"] for r in res])))
    run.finished.connect(lambda msg: order.append(("finished", msg)))
    run._run()                                   # same thread: signals fire inline
    assert calls["retouch_every"] == 4
    assert order == [("point", -56000), ("point", -56030), ("drift", 60.0),
                     ("corrected", [-56000, -56000]), ("finished", "")]


def test_a_run_without_correction_publishes_nothing_extra(qt_app, monkeypatch):
    def fake_probe_grid(port, points, on_result=None, **kw):
        res = [{"id": p, "x": x, "y": y, "z": -1000} for p, x, y in points]
        for d in res:
            on_result(d)
        return res
    import gerber2rml.engine.spi_probe as sp
    monkeypatch.setattr(sp, "probe_grid", fake_probe_grid)
    got = []
    run = leveling.ProbeRun("COMX", [(0, 0, 0)], lambda: False)
    run.corrected.connect(lambda res: got.append("corrected"))
    run.drift.connect(lambda um: got.append("drift"))
    run._run()
    assert got == []


def test_the_corrected_set_refills_the_table_against_the_corrected_datum(loaded):
    page = loaded.level_page
    page.nx.setValue(2); page.ny.setValue(2); page._build()
    loaded.say = lambda l, t: None
    raw = [{"id": i, "x": 0, "y": 0, "z": -56000 - 30 * i} for i in range(4)]
    for d in raw:
        page._on_point(d)
    assert page.table.item(3, 2).text() == "-0.0900"          # drift showed as a slope
    corrected = [dict(d, z_raw=d["z"], z=-56000 - (10 if d["id"] == 2 else 0))
                 for d in raw]
    page._on_corrected(corrected)
    assert [page.table.item(r, 2).text() for r in range(4)] == \
        ["0.0000", "0.0000", "-0.0100", "0.0000"]
    assert page._failed == []
    page._on_drift(90.0)
    said = []
    loaded.say = lambda l, t: said.append((l, t))
    page._on_done("", None)
    assert "moved 90 µm" in said[-1][1] and "corrected" in said[-1][1]
    assert "moved 90 µm" in page.probe_state.text()


def test_the_drift_check_is_off_on_a_firmware_that_cannot_retouch(loaded):
    """Sent to the first firmware the re-touch is ignored, and the run sits
    out the point timeout at every checkpoint. So it is gated on the
    feature the link reported, and the operator is told."""
    page = loaded.level_page
    link = loaded.link
    said = []
    loaded.say = lambda l, t: said.append((l, t))
    page.retouch.setValue(6)
    link.firmware = {"version": 1, "features": ["probe"], "port": "COMX"}
    assert page._retouch_every(link) == 0
    assert said[-1][0] == "warn" and "firmware" in said[-1][1]
    link.firmware = {"version": 2, "features": ["probe", "retouch"], "port": "COMX"}
    assert page._retouch_every(link) == 6
    page.retouch.setValue(0)
    n = len(said)
    assert page._retouch_every(link) == 0 and len(said) == n   # off is silent
    assert page.retouch.text() == "off"


def test_the_drift_check_control_is_full_tier_only(qt_app, monkeypatch):
    w = _window(monkeypatch, "novice")
    try:
        assert w.level_page.retouch_field.isHidden()
    finally:
        w.close()
    w = _window(monkeypatch, "pro")
    try:
        assert not w.level_page.retouch_field.isHidden()
    finally:
        w.close()


def test_the_drift_setting_is_in_the_setup(loaded):
    page = loaded.level_page
    page.retouch.setValue(3)
    data = page.state()
    assert data["retouch"] == 3
    page.retouch.setValue(6)
    page.restore(data)
    assert page.retouch.value() == 3
    page.restore({"rows": [], "nx": 3, "ny": 3})       # an older setup: kept
    assert page.retouch.value() == 3


# ------------------------------------------------------------- the mesh check
def _bowed_with_one_flaky_point():
    """A gentle bow - legitimate warp - with one touch 0.3 mm off. Sixteen
    points, so the fit through the others is not itself pulled by it."""
    line = (10.0, 40.0, 70.0, 100.0)
    rows = _rows(lambda x, y: 0.0005 * (x - 50) ** 2 / 50, xs=line, ys=line)
    rows[5][2] = f"{float(rows[5][2]) + 0.30:.4f}"             # row 6: X40 Y40
    return rows


def test_the_mesh_check_names_the_flaky_point(loaded, monkeypatch):
    page = loaded.level_page
    page.nx.setValue(4); page.ny.setValue(4)
    page._load_table({"rows": _bowed_with_one_flaky_point(), "apply": True,
                      "show": False})
    seen = []
    _sheet_stub(monkeypatch, seen)
    page._mesh_check()
    assert seen and seen[0]["title"] == "How good is this measurement?"
    text = seen[0]["text"]
    assert "1 point sits" in text and "row 6" in text and "X 40.0  Y 40.0" in text
    assert "Re-probe it" in text
    # the point is marked in the table, where it has to be found
    assert page.table.item(5, 2).toolTip()
    assert not page.table.item(4, 2).toolTip()
    assert "1 point no smooth surface can explain" in page.advice.text()
    # ...and cleared again once the table no longer says so
    page._load_table({"rows": _rows(lambda x, y: 0.0, xs=(10.0, 40.0, 70.0, 100.0),
                                    ys=(10.0, 40.0, 70.0, 100.0)),
                      "apply": True, "show": False})
    seen.clear()
    page._mesh_check()
    assert "Every point agrees" in seen[0]["text"]
    assert seen[0]["buttons"] == ["Close"]
    assert not page.table.item(5, 2).toolTip()


def test_the_mesh_check_needs_five_points(loaded, monkeypatch):
    page = loaded.level_page
    page._load_table({"rows": _rows(lambda x, y: 0.0, xs=(10.0, 90.0),
                                    ys=(10.0, 90.0)),
                      "apply": True, "show": False})
    seen, said = [], []
    _sheet_stub(monkeypatch, seen)
    loaded.say = lambda l, t: said.append((l, t))
    page._mesh_check()
    assert not seen and said[-1][0] == "warn" and "five" in said[-1][1]


def test_the_mesh_check_adds_the_missing_lines_in_one_click(loaded, monkeypatch):
    """A step of 0.2 mm between the bottom two rows: the map cannot follow
    it, so a row between them is suggested and inserted, blank, keeping the
    grid whole - and the next probe run offers to measure only those."""
    page = loaded.level_page
    rows = _rows(lambda x, y: 0.2 if y > 30 else 0.0)
    page._load_table({"rows": rows, "apply": True, "show": False})
    assert "too coarse" in page.advice.text()
    seen, said = [], []
    _sheet_stub(monkeypatch, seen, press="Add the missing lines")
    loaded.say = lambda l, t: said.append((l, t))
    page._mesh_check()
    assert "a row at Y = 30.0" in seen[0]["text"]
    assert "Add the missing lines" in seen[0]["buttons"]
    assert page.table.rowCount() == 12
    assert (page.nx.value(), page.ny.value()) == (3, 4)
    assert page._measured() == [True] * 3 + [False] * 3 + [True] * 6
    assert page._points[3:6] == [(10.0, 30.0), (50.0, 30.0), (90.0, 30.0)]
    assert [page.table.item(r, 1).text() for r in range(3, 6)] == ["30.000"] * 3
    assert leveling.resume_selection(page._measured()) == [0, 3, 4, 5]
    assert said[-1][0] == "ok" and "3 probe points added" in said[-1][1]
    # the measured heights were kept, the new rows are blank
    assert page.table.item(0, 2).text() == "0.0000"
    assert page.table.item(4, 2).text() == ""


def test_a_grid_that_would_outgrow_the_table_is_refused(loaded):
    page = loaded.level_page
    page.nx.setValue(3); page.ny.setValue(21); page._build()
    said = []
    loaded.say = lambda l, t: said.append((l, t))
    page._insert_probe_lines([0.5 * (page._points[0][1] + page._points[3][1])])
    assert said[-1][0] == "warn" and page.table.rowCount() == 63


# ------------------------------------------- the top face of a dowel job
def _z_values(path):
    text = Path(path).read_text(encoding="utf-8")
    return sorted({round(float(v), 3) for v in re.findall(r"Z(-?\d+\.?\d*)", text)})


def test_the_top_traces_button_belongs_to_dowel_jobs(loaded):
    page = loaded.level_page
    assert page.top_btn.isHidden()
    loaded.action_double_sided(True)
    assert not page.top_btn.isHidden()
    loaded.action_registration("fiducial")
    assert page.top_btn.isHidden(), "the flip-fit page owns the fiducial case"
    loaded.action_registration("dowel")
    assert not page.top_btn.isHidden()
    loaded.action_double_sided(False)
    assert page.top_btn.isHidden()


def test_the_top_traces_are_rewritten_to_the_top_map(loaded, tmp_path):
    loaded.action_double_sided(True)
    written = loaded.export_to(str(tmp_path))
    top = [Path(p) for p in written if Path(p).name.endswith("_top_traces.nc")]
    assert len(top) == 1
    top = top[0]
    flat = _z_values(top)
    page = loaded.level_page
    # Probe the top: a sheet sloping 0.05 mm across the board.
    page.side_switch.set_current("top")
    page._on_side("top")
    b = loaded.work_bounds()
    x0, y0, x1, y1 = b
    page._load_table({"rows": _rows(lambda x, y: 0.05 * (x - x0) / (x1 - x0),
                                    xs=(x0 + 2, (x0 + x1) / 2, x1 - 2),
                                    ys=(y0 + 2, (y0 + y1) / 2, y1 - 2)),
                      "apply": True, "show": False})
    assert page.height_map(side="top") is not None
    # Whichever face is on screen: the bottom map does not describe the top.
    page.side_switch.set_current("bottom")
    page._on_side("bottom")
    said = []
    loaded.say = lambda l, t: said.append((l, t))
    page._export_top_traces()
    assert said[-1][0] == "ok" and top.name in said[-1][1]
    warped = _z_values(top)
    assert warped != flat
    assert len(warped) > len(flat), "every cut Z should now follow the slope"
    # the other files are untouched
    assert all(Path(p).exists() for p in written)


def test_the_top_export_refuses_a_bottom_only_map(loaded, tmp_path):
    loaded.action_double_sided(True)
    written = loaded.export_to(str(tmp_path))
    top = next(Path(p) for p in written if Path(p).name.endswith("_top_traces.nc"))
    before = top.read_bytes()
    page = loaded.level_page
    page._load_table({"rows": _rows(lambda x, y: 0.001 * x), "apply": True,
                      "show": False})
    assert page.map_side() == "bottom"
    said = []
    loaded.say = lambda l, t: said.append((l, t))
    page._export_top_traces()
    assert said[-1][0] == "warn" and "Switch to Top" in said[-1][1]
    assert top.read_bytes() == before
