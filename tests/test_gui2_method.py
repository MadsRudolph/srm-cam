"""The method in the window: the chip, the checks, the rail and the export
follow how the board is made, and the operator can always choose."""
import json
import shutil
from pathlib import Path

import pytest

from gerber2rml.engine import method as fab
from gerber2rml.gui2.window import MainWindow

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def win(qt_app):
    w = MainWindow()
    w.resize(1400, 900)
    yield w
    w.close()


def _laser_board(tmp_path):
    """The mosfet board, with KiCad's method file saying laser."""
    d = tmp_path / "board"
    shutil.copytree(FIX / "mosfet_test", d)
    (d / "method.json").write_text(json.dumps(
        {"boards": {"buck.kicad_pcb": {"method": "laser"}}}))
    return d


def test_a_board_from_kicad_is_made_its_way(win, tmp_path):
    win.load_folder(str(_laser_board(tmp_path)))
    assert win.method_id() == fab.FLAT          # a plain load: the tool says
    win._detect_method()
    assert win.method_id() == fab.LASER
    assert win._method_source == "kicad"
    assert "Laser" in win.method_chip.label.text()
    assert "KiCad" in win.method_chip.label.text()


def test_the_guess_without_kicad(win):
    win.load_folder(str(FIX / "mosfet_test"))
    win._detect_method()
    assert win.method_id() == fab.guess(win.state.board)[0]
    assert win._method_source == "guessed"


def test_choosing_a_method_always_works(win):
    win.load_folder(str(FIX / "mosfet_test"))
    win._detect_method()
    win.method_acts[fab.BALL].trigger()
    assert win.method_id() == fab.BALL and win._method_source == "chosen"
    # The ball mill's profile came with it.
    assert win.state.trace.effective_diameter() < 0.6
    win.inspector.setup.method.setCurrentIndex(
        win.inspector.setup.method.findData(fab.FLAT))
    assert win.method_id() == fab.FLAT
    assert win.state.trace.effective_diameter() >= 0.6


def test_a_laser_board_is_not_judged_by_the_cutter(win):
    # The test pads are boxes (conftest), which puts this board's nets
    # closer than the flat bit in places.
    win.load_folder(str(FIX / "mosfet_test"))
    win.action_method(fab.FLAT)
    assert win._shorts, "the fixture should have spots too close for 0.8"
    assert any(c.title == "Nets closer than the bit" for c in win._checks)
    win.action_method(fab.LASER)
    titles = [c.title for c in win._checks if c.level != "ok"]
    assert "Nets closer than the bit" not in titles
    assert not any("too narrow to isolate" in t for t in titles)
    assert win._gaps is None


def test_the_laser_rail_and_its_rows(win, tmp_path):
    win.load_folder(str(_laser_board(tmp_path)))
    win._detect_method()
    keys = [s.key for s in win.plan]
    assert "traces_run" not in keys
    assert "laser_traces" in keys and "laser" not in keys
    assert keys.index("cutout_run") < keys.index("laser_traces")
    # Picking a laser row brings the laser up beside the rail.
    win.select_step("laser_traces")
    assert win.mode() == "laser"
    assert win.traveller.current() == "laser_traces"
    win.select_step("setup")
    assert win.mode() == "cnc"


def test_a_laser_board_turns_double_sided_off_and_back(win):
    win.load_folder(str(FIX / "mosfet_test"))
    win.inspector.setup.double.setChecked(True)
    assert win._double
    win.action_method(fab.LASER)
    assert not win._double
    assert not win.inspector.setup.ds_section.isVisibleTo(win.inspector.setup)
    win.action_method(fab.FLAT)
    assert win._double


def test_a_laser_export_drills_and_cuts_out(win, tmp_path):
    win.load_folder(str(FIX / "mosfet_test"))
    win.action_method(fab.LASER)
    names = [Path(p).name for p in win.export_to(str(tmp_path / "out"))]
    assert not any(n.endswith("_traces.nc") for n in names)
    assert any("cutout" in n for n in names)
    assert not any("airpass" in n for n in names)
    assert any(p.suffix == ".dxf" and "traces" in p.name
               for p in (tmp_path / "out").iterdir())


def test_novice_rail_has_the_laser_rows(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("SRM_CAM_MODE", "novice")
    w = MainWindow()
    try:
        w.load_folder(str(_laser_board(tmp_path)))
        w._detect_method()
        rail = [s.key for s in w.novice_rail()]
        assert rail[:4] == ["setup", "checks", "autorun", "laser_traces"]
        assert all(k.startswith("laser_") for k in rail[3:])
    finally:
        w.close()


def test_the_setup_file_keeps_the_method(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win.load_folder(str(FIX / "mosfet_test"))
    win.action_method(fab.LASER)
    path = tmp_path / "job.srmcam"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(path), ""))
    win.action_save_setup()
    data = json.loads(path.read_text())
    assert data["method"] == fab.LASER
    win.action_method(fab.FLAT)
    win.load_setup(str(path))
    assert win.method_id() == fab.LASER


def test_rows_of_boards_fit_the_sheet(win):
    win.load_folder(str(FIX / "mosfet_test"))
    win.add_folder(str(FIX / "mosfet_test"))
    win.add_folder(str(FIX / "mosfet_test"))
    win.action_stock(240.0, 240.0, 0.0, 0.0)
    win.action_arrange()
    x0, y0, x1, y1 = win.work_extent()
    assert x1 <= 240.0 + 1e-6, "the row ran past the sheet"


def test_the_whole_sheet_goes_to_the_laser(win):
    win.load_folder(str(FIX / "mosfet_test"))
    win.add_folder(str(FIX / "mosfet_test"))
    win.action_arrange()
    win.action_method(fab.LASER)
    one = win.state.boards[0]
    win._laser_member = 0
    single = win._laser_art_for("traces")
    win._laser_member = None
    art = win._laser_art_for("traces")
    assert len(art.outline.geoms) == 2
    assert len(art.drills) == 2 * len(single.drills)
    assert "2 boards" in art.note
