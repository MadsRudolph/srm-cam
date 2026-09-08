"""The checks, export extras and view tools ported from the original
interface: narrow copper gaps, the exact screw-vs-toolpath check, the standing
hand-picked screw review, the single-sided design X-ray, the ruler, simulating
an exported file, centring on the copper, the preview picture and summary
beside the job, and the tool-wear ledger. Nothing here touches a serial port
or opens a real 3D window."""
import json
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QAction
from shapely.geometry import box

from gerber2rml.engine import spoilboard
from gerber2rml.gui2.stage import Stage
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"
BED = (203.2, 152.4)


@pytest.fixture
def win(qt_app):
    w = MainWindow()
    w.resize(1400, 900)
    yield w
    w.close()


@pytest.fixture
def loaded(win):
    win.load_folder(str(FIXT))
    return win


def _on_a_sheet(win):
    """The copper over the whole travel, the job centred on it, so the
    automatic screw picker has holes to choose from."""
    win.action_stock(BED[0], BED[1], 0.0, 0.0)
    win.action_autoplace()


def _view_menu(win):
    return [a for a in win.menuBar().actions()[1].menu().actions()
            if a.text()]


# --- narrow copper gaps -------------------------------------------------------

def test_narrow_gaps_are_a_finding_of_their_own(loaded):
    """A sliver too narrow for the cutter is not a short: it may lie between
    two pads of ONE net. It gets its own line, next to the short."""
    assert loaded._gaps is not None and not loaded._gaps.is_empty
    titles = [c.title for c in loaded._checks]
    gap = [t for t in titles if "too narrow to isolate" in t]
    assert gap, titles
    assert "Nets closer than the bit" in titles       # the short is still there
    n = len(loaded._gaps.geoms)
    assert gap[0].startswith(str(n))
    detail = [c.detail for c in loaded._checks if c.title == gap[0]][0]
    assert "drawn red" in detail and "smaller bit" in detail


def test_narrow_gaps_are_drawn_red_on_the_trace_view_only(loaded):
    loaded.select_step("traces_run")
    assert loaded.stage._gaps is not None and loaded.stage._p_gaps is not None
    assert any("too narrow" in t for _c, t in loaded.stage._legend)
    loaded.select_step("drill_run")
    assert loaded.stage._gaps is None
    assert not any("too narrow" in t for _c, t in loaded.stage._legend)


def test_a_board_with_no_slivers_has_no_gap_finding(loaded):
    loaded._gaps = None
    assert loaded._gap_checks() == []


# --- screws against the real toolpaths -----------------------------------------

def test_the_screws_are_checked_against_the_real_toolpaths(loaded):
    """Not the copper keep-out: the cut-out runs OUTSIDE the outline, where
    the screws go, and a screw in that band passed the keep-out."""
    _on_a_sheet(loaded)
    loaded.action_screws_toggled(True)
    checks = loaded._screw_checks()
    ok = [c for c in checks if c.title == "No pass reaches a screw head"]
    assert ok, [(c.level, c.title) for c in checks]
    assert "cut-out" in ok[0].detail and "traces" in ok[0].detail


def test_a_screw_in_the_cutters_path_fails_the_check(loaded):
    _on_a_sheet(loaded)
    loaded.action_screws_toggled(True)
    loaded.select_step("traces_run")
    paths = loaded._paths_cache["traces_run"][0]
    cut = next(m for tp in paths for m in tp if not m.rapid)
    loaded._manual_screws = [(cut.x, cut.y)]
    loaded.refresh_checks()
    hit = [c for c in loaded._checks
           if c.title == "The cutter would hit a screw head"]
    assert hit and hit[0].level == "fail"
    assert "traces path" in hit[0].detail
    assert "another hole" in hit[0].detail             # it says what to do


def test_the_exact_check_uses_the_cache_the_stage_drew_from(loaded):
    """One toolpath build serves both the picture and the check."""
    _on_a_sheet(loaded)
    loaded.action_screws_toggled(True)
    loaded.select_step("traces_run")
    before = loaded._paths_cache["traces_run"]
    sweeps = loaded._pass_sweeps()
    assert loaded._paths_cache["traces_run"] is before
    assert set(sweeps) >= {"traces", "drill", "cutout"}
    assert sweeps["traces"] is not None and sweeps["cutout"] is not None


# --- hand-picked screws as a standing check -------------------------------------

def test_a_hand_picked_screw_is_reviewed_on_the_checks_page(loaded):
    """The toast goes; the finding stays until the choice changes."""
    _on_a_sheet(loaded)
    loaded.action_screws_toggled(True)
    grid = spoilboard.measured_grid()
    # A hole that lands on the design: the picker would never offer it.
    x0, y0, x1, y1 = loaded.work_bounds()
    inside = min(((grid.centre(i, j)) for j in range(grid.ny)
                  for i in range(grid.nx)),
                 key=lambda p: (p[0] - (x0 + x1) / 2) ** 2
                 + (p[1] - (y0 + y1) / 2) ** 2)
    loaded._manual_screws = [inside]
    loaded.refresh_checks()
    review = [c for c in loaded._checks
              if c.title == "A hand-picked screw needs a look"]
    assert review and review[0].level == "warn"
    assert f"X {inside[0]:.1f} Y {inside[1]:.1f}" in review[0].detail
    for key in [s.key for s in loaded.plan]:          # it does not expire
        loaded.select_step(key)
        assert any(c.title == "A hand-picked screw needs a look"
                   for c in loaded._checks)
    loaded.action_reset_screws()
    assert not any("hand-picked" in c.title.lower() for c in loaded._checks)


def test_good_hand_picked_screws_are_confirmed(loaded):
    _on_a_sheet(loaded)
    loaded.action_screws_toggled(True)
    loaded._manual_screws = list(loaded._auto_screws())
    assert loaded._manual_screws
    loaded.refresh_checks()
    ok = [c for c in loaded._checks
          if c.title == "The hand-picked screws are all usable"]
    assert ok and ok[0].level == "ok"


# --- the design X-ray on a single-sided board ------------------------------------

def test_the_xray_is_available_on_a_single_sided_job(loaded):
    assert not loaded._double
    assert loaded.xray_act.isEnabled()
    loaded._on_frame("xray")
    assert loaded.stage.frame == "xray"
    assert loaded.stage._flip_x, "the single-sided X-ray is the KiCad top view"
    loaded._on_frame("bed")
    assert not loaded.stage._flip_x


def test_the_flip_is_a_view_and_the_millimetres_do_not_move(loaded):
    loaded._on_frame("xray")
    st = loaded.stage
    p = st.to_px(50.0, 40.0)
    back = st.to_mm(p)
    assert back.x() == pytest.approx(50.0, abs=1e-6)
    assert back.y() == pytest.approx(40.0, abs=1e-6)
    # ...and it IS mirrored: x grows to the LEFT on screen
    assert st.to_px(60.0, 40.0).x() < st.to_px(50.0, 40.0).x()


def test_the_double_sided_xray_is_real_geometry_not_a_flip(loaded):
    loaded.action_double_sided(True)
    loaded._on_frame("xray")
    assert not loaded.stage._flip_x
    loaded.action_double_sided(False)
    assert loaded.stage._flip_x           # still in X-ray, single-sided now


# --- the ruler --------------------------------------------------------------------

def _stage(qt_app):
    s = Stage()
    s.resize(800, 600)
    s.set_board(box(10, 10, 60, 40), box(10, 10, 60, 40), [(35.0, 25.0, 1.0)])
    s.fit_work()
    return s


def test_the_ruler_snaps_to_corners_and_holes(qt_app):
    s = _stage(qt_app)
    got = []
    s.measured.connect(got.append)
    s.set_mode("measure")
    s._measure_press(QPointF(10.6, 9.5))          # near the front-left corner
    s._measure_move(QPointF(59.4, 40.7))          # near the back-right corner
    s._measure_release()
    assert s.measure_line() == (10.0, 10.0, 60.0, 40.0)
    assert got and got[-1][0] == pytest.approx((50 ** 2 + 30 ** 2) ** 0.5)
    assert got[-1][1:] == (pytest.approx(50.0), pytest.approx(30.0))
    s._measure_press(QPointF(34.6, 25.3))         # the hole
    s._measure_move(QPointF(10.2, 25.0))          # the left EDGE, mid-way
    s._measure_release()
    assert s.measure_line() == (35.0, 25.0, 10.0, 25.0)


def test_a_click_is_not_a_measurement_and_the_mode_owns_the_ruler(qt_app):
    s = _stage(qt_app)
    s.set_mode("measure")
    s._measure_press(QPointF(30.0, 20.0))
    s._measure_release()
    assert s.measure_line() is None
    s._measure_press(QPointF(10.0, 10.0))
    s._measure_move(QPointF(60.0, 10.0))
    s._measure_release()
    assert s.measure_line() is not None
    s.set_mode("place")                           # leaving the mode clears it
    assert s.measure_line() is None


def test_the_ruler_is_a_stage_mode_like_the_others(loaded):
    loaded.action_measure(True)
    assert loaded.stage.mode == "measure"
    loaded.set_stage_mode("jog")                  # another mode takes over
    assert not loaded.measure_act.isChecked()
    loaded.measure_act.setChecked(True)
    loaded.action_measure(True)
    loaded.action_measure(False)
    assert loaded.stage.mode == "place"


def test_the_ruler_and_the_file_simulation_end_the_view_menu(win):
    texts = [a.text() for a in _view_menu(win)]
    assert texts[-2].startswith("Measure")
    assert texts[-1] == "Simulate a file in 3D…"
    assert win.measure_act.shortcut().toString() == "Ctrl+M"


# --- simulate any exported file ---------------------------------------------------

class _FakeSim:
    made = []

    def __init__(self, paths, title="", parent=None, board=None, bed=None,
                 thickness=1.6):
        self.paths, self.title, self.board, self.bed = paths, title, board, bed
        self.live = None
        _FakeSim.made.append(self)

    def set_live_enabled(self, on): self.live = on
    def show(self): pass
    def raise_(self): pass
    def activateWindow(self): pass
    def close(self): pass
    def deleteLater(self): pass
    def isVisible(self): return True


def _fake_sim3d(monkeypatch):
    """Stand in for the 3D module WITHOUT importing it: under the offscreen
    platform pyqtgraph's GL setup can hang the process rather than fail (see
    test_gui2_sim3d.py), and nothing here is about the GL scene."""
    import sys
    import types
    mod = types.ModuleType("gerber2rml.gui2.sim3d")
    mod.Simulation3DWindow = _FakeSim
    monkeypatch.setitem(sys.modules, "gerber2rml.gui2.sim3d", mod)
    _FakeSim.made = []


def test_an_exported_file_can_be_watched_in_3d(loaded, tmp_path, monkeypatch):
    _fake_sim3d(monkeypatch)
    written = loaded.export_to(tmp_path)
    nc = next(p for p in written if str(p).endswith("_traces.nc"))
    loaded.action_sim_file(str(nc))
    assert len(_FakeSim.made) == 1
    sim = _FakeSim.made[0]
    assert sim.paths and any(sim.paths)
    assert Path(nc).name in sim.title and "as written" in sim.title
    assert sim.board is None, "the file may not belong to the loaded board"
    assert sim.bed == BED


def test_the_parser_reads_the_files_this_program_writes(loaded, tmp_path):
    """The exporter's header says "( ... 1 offset(s), ... )". A comment
    stripper that stopped at the first ")" fed the rest to the word scanner,
    and "Simulate a file" could not open a single file the app had written."""
    from gerber2rml.engine.gcode_parse import parse_file
    written = loaded.export_to(tmp_path)
    for p in written:
        if str(p).endswith(".nc"):
            paths = parse_file(p)
            assert paths and any(paths), p
            assert any(not m.rapid for tp in paths for m in tp), p


def test_a_file_that_is_not_a_toolpath_is_explained(loaded, tmp_path,
                                                    monkeypatch):
    _fake_sim3d(monkeypatch)
    said = []
    monkeypatch.setattr(loaded, "say", lambda lvl, t: said.append((lvl, t)))
    empty = tmp_path / "nothing.nc"
    empty.write_text("G21\nG90\nM30\n")
    loaded.action_sim_file(str(empty))
    assert not _FakeSim.made
    assert said and said[-1][0] == "warn" and "no tool moves" in said[-1][1]
    errors = []
    monkeypatch.setattr(loaded, "report_error",
                        lambda h, e=None, g="": errors.append((h, g)))
    loaded.action_sim_file(str(tmp_path / "missing.nc"))
    assert errors and "could not be read" in errors[-1][0]
    assert ".nc" in errors[-1][1]                   # the guidance says what it wants


# --- centre on the copper, not the bed ----------------------------------------------

def _centre(win):
    x0, y0, x1, y1 = win.job_extent()
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0


def test_centring_on_the_copper_targets_the_sheet(loaded):
    loaded.action_stock(100.0, 80.0, 60.0, 30.0)   # a small sheet, off-centre
    loaded.action_autoplace("copper")
    cx, cy = _centre(loaded)
    assert cx == pytest.approx(60.0 + 50.0, abs=0.01)
    assert cy == pytest.approx(30.0 + 40.0, abs=0.01)


def test_centring_on_the_bed_targets_the_travel_whatever_the_sheet(loaded):
    loaded.action_stock(100.0, 80.0, 60.0, 30.0)
    loaded.action_autoplace("bed")
    cx, cy = _centre(loaded)
    assert cx == pytest.approx(BED[0] / 2.0, abs=0.01)
    assert cy == pytest.approx(BED[1] / 2.0, abs=0.01)


def test_centring_on_a_sheet_nobody_measured_is_refused(loaded, monkeypatch):
    """The default sheet is a picture. Centring on it would be centring on a
    rectangle nobody measured."""
    assert not loaded._stock_set
    said = []
    monkeypatch.setattr(loaded, "say", lambda lvl, t: said.append((lvl, t)))
    before = (loaded.state.place_x, loaded.state.place_y)
    loaded.action_autoplace("copper")
    assert (loaded.state.place_x, loaded.state.place_y) == before
    assert said[-1][0] == "warn" and "The copper" in said[-1][1]


def test_both_centrings_sit_together_in_the_view_menu(win):
    texts = [a.text() for a in _view_menu(win)]
    i = texts.index("Centre the job on the bed")
    assert texts[i + 1] == "Centre the job on the copper"
    acts = {a.text(): a for a in win.findChildren(QAction)}
    assert acts["Centre the job on the copper"].shortcut().toString()
    setup = win.inspector.setup
    assert setup.centre_copper_btn.text() == "Centre it on the copper"


# --- a picture and a summary beside the job --------------------------------------------

def test_the_export_folder_holds_a_picture_and_a_summary(loaded, tmp_path):
    loaded.select_step("traces_run")
    loaded.export_to(tmp_path)
    png = tmp_path / "buck_preview.png"
    md = tmp_path / "buck_summary.md"
    assert png.exists() and png.stat().st_size > 0
    assert md.exists()
    text = md.read_text(encoding="utf-8")
    assert "buck - board summary" in text and "Holes:" in text
    assert loaded.exported_path("buck_summary.md") == md


def test_the_extras_never_fail_the_export(loaded, tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("no picture today")
    monkeypatch.setattr(loaded.stage, "grab", boom)
    written = loaded.export_to(tmp_path)
    assert any(str(p).endswith(".nc") for p in written)
    assert loaded.centre.currentWidget() is loaded.sheet
    assert not (tmp_path / "buck_preview.png").exists()
    assert (tmp_path / "buck_summary.md").exists()   # the other one still comes


# --- the tool-wear ledger ----------------------------------------------------------------

def _ledger():
    from gerber2rml.gui2 import workspace
    return workspace.workspace_root() / "tool_wear.json"


def test_an_export_adds_its_cutting_to_the_tool_ledger(loaded, tmp_path):
    ledger = _ledger()
    if ledger.exists():
        ledger.unlink()
    loaded.export_to(tmp_path)
    data = json.loads(ledger.read_text(encoding="utf-8"))
    key = (f"{loaded.state.trace.tool_type} "
           f"{loaded.state.trace.effective_diameter():.2f}mm")
    assert key in data and data[key] > 0
    first = data[key]
    loaded.export_to(tmp_path)
    assert json.loads(ledger.read_text())[key] == pytest.approx(2 * first,
                                                                 abs=0.2)


def test_a_worn_bit_is_said_at_export(loaded, tmp_path, monkeypatch):
    from gerber2rml.engine import toolwear
    ledger = _ledger()
    key = (f"{loaded.state.trace.tool_type} "
           f"{loaded.state.trace.effective_diameter():.2f}mm")
    ledger.write_text(json.dumps({key: toolwear.WARN_AT_M * 1000.0}))
    said = []
    monkeypatch.setattr(loaded, "say", lambda lvl, t: said.append((lvl, t)))
    loaded.export_to(tmp_path)
    level, text = said[-1]
    assert "files written" in text and "WORN" in text
    assert level == "warn"


def test_a_ledger_that_cannot_be_read_does_not_stop_the_export(loaded, tmp_path,
                                                              monkeypatch):
    from gerber2rml.engine import toolwear
    monkeypatch.setattr(toolwear, "record",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
    written = loaded.export_to(tmp_path)
    assert any(str(p).endswith(".nc") for p in written)
