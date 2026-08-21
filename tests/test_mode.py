"""Novice / Professional mode.

The load-bearing claim this file defends is that Novice is a strict SUBSET of
Professional — the same widgets and the same handlers with some put away, not a
second implementation. If that ever stops being true, a student's board and a
teacher's board stop coming out the same, so
:func:`test_novice_and_professional_export_identical_files` is the test to keep
green above all the others here.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import matplotlib
matplotlib.use("Agg")
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from gerber2rml.gui import mode as uimode
from gerber2rml.gui.app import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"
_app = QApplication.instance() or QApplication([])


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Point mode storage at a temp .ini so a test never touches the real
    QSettings (on Windows: the developer's own registry)."""
    ini = tmp_path / "mode.ini"
    monkeypatch.setattr(uimode, "_settings",
                        lambda: QSettings(str(ini), QSettings.Format.IniFormat))
    return ini


def _window(monkeypatch, mode):
    """A MainWindow built in ``mode``. The env override is set before
    construction because __init__ applies the mode as it builds."""
    monkeypatch.setenv("SRM_CAM_MODE", mode)
    return MainWindow()


# ---- the setting itself ---------------------------------------------------

def test_fresh_install_defaults_to_novice(isolated_settings, monkeypatch):
    monkeypatch.delenv("SRM_CAM_MODE", raising=False)
    assert uimode.current_mode() == uimode.NOVICE
    assert not uimode.is_pro()


def test_set_mode_round_trips(isolated_settings, monkeypatch):
    monkeypatch.delenv("SRM_CAM_MODE", raising=False)
    assert uimode.set_mode(uimode.PRO) is True
    assert uimode.current_mode() == uimode.PRO
    assert uimode.set_mode(uimode.NOVICE) is True
    assert uimode.current_mode() == uimode.NOVICE


def test_env_override_wins_and_blocks_writes(isolated_settings, monkeypatch):
    monkeypatch.delenv("SRM_CAM_MODE", raising=False)
    uimode.set_mode(uimode.NOVICE)
    monkeypatch.setenv("SRM_CAM_MODE", "professional")   # the spelling people type
    assert uimode.current_mode() == uimode.PRO
    assert uimode.set_mode(uimode.NOVICE) is False       # pinned: no write
    assert uimode.current_mode() == uimode.PRO


def test_unknown_mode_values_fall_back_to_novice(isolated_settings, monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "wizard")
    assert uimode.forced_mode() is None
    assert uimode.current_mode() == uimode.NOVICE


def test_set_mode_rejects_nonsense(isolated_settings, monkeypatch):
    monkeypatch.delenv("SRM_CAM_MODE", raising=False)
    with pytest.raises(ValueError):
        uimode.set_mode("wizard")


# ---- what the window does with it -----------------------------------------

def test_novice_hides_the_professional_controls(monkeypatch):
    w = _window(monkeypatch, "novice")
    w.show(); _app.processEvents()
    # the big one: feeds, depths, offsets, V-bit geometry
    assert not w.params_group.isVisible()
    # machine control — a Novice sends files from VPanel
    for widget in (w.connect_btn, w.stream_btn, w.jog_chk, w.dro_label,
                   w.level_port_combo, w.stop_btn):
        assert not widget.isVisible(), widget
    # ...but the things a beginner actually needs are all still there
    for widget in (w.load_btn, w.export_btn, w.preset_combo,
                   w.apply_preset_btn, w.thickness_spin, w.tabs,
                   w.diag_btn, w.guide_btn):
        assert widget.isVisible(), widget
    w.close()


def test_professional_shows_everything(monkeypatch):
    w = _window(monkeypatch, "pro")
    w.show(); _app.processEvents()
    for widget in (w.params_group, w.connect_btn, w.stream_btn, w.jog_chk,
                   w.load_btn, w.export_btn, w.diag_btn, w.feedcard_btn,
                   w.save_preset_btn):
        assert widget.isVisible(), widget
    w.close()


def test_novice_sidebar_is_the_short_path(monkeypatch):
    w = _window(monkeypatch, "novice")
    visible = [w.sidebar.item(i).text() for i in range(w.sidebar.count())
               if not w.sidebar.isRowHidden(i)]
    assert visible == ["1 · Set up board", "2 · Level the bed", "3 · Drill",
                       "4 · Traces", "5 · Cut out", "6 · Check in 3D"]
    w.close()


def test_professional_sidebar_keeps_every_step(monkeypatch):
    w = _window(monkeypatch, "pro")
    visible = [w.sidebar.item(i).text() for i in range(w.sidebar.count())
               if not w.sidebar.isRowHidden(i)]
    assert len(visible) == len(w._SPINE)
    assert visible == [s[0] for s in w._SPINE]
    w.close()


def test_switching_to_professional_restores_the_full_ui(monkeypatch,
                                                        isolated_settings):
    w = _window(monkeypatch, "novice")
    w.show(); _app.processEvents()
    assert not w.params_group.isVisible()

    monkeypatch.delenv("SRM_CAM_MODE", raising=False)   # unpin so the menu works
    w._on_mode_chosen(uimode.PRO)
    _app.processEvents()
    assert w.params_group.isVisible()
    assert w.connect_btn.isVisible()
    assert not any(w.sidebar.isRowHidden(i) for i in range(w.sidebar.count()))
    assert w.act_pro.isChecked()

    w._on_mode_chosen(uimode.NOVICE)
    _app.processEvents()
    assert not w.params_group.isVisible()
    assert w.act_novice.isChecked()
    w.close()


def test_novice_turns_double_sided_off(monkeypatch, isolated_settings):
    """Novice has no flip or align step, so a double-sided job would export a
    second half with no UI behind it."""
    w = _window(monkeypatch, "pro")
    w.double_sided_chk.setChecked(True)
    monkeypatch.delenv("SRM_CAM_MODE", raising=False)
    w._on_mode_chosen(uimode.NOVICE)
    assert not w.double_sided_chk.isChecked()
    w.close()


def test_novice_never_parks_on_a_hidden_step(monkeypatch, isolated_settings):
    w = _window(monkeypatch, "pro")
    w.sidebar.setCurrentRow(8)                 # Rework — professional only
    monkeypatch.delenv("SRM_CAM_MODE", raising=False)
    w._on_mode_chosen(uimode.NOVICE)
    assert w.sidebar.currentRow() not in w._PRO_STEPS
    assert not w.sidebar.isRowHidden(w.sidebar.currentRow())
    w.close()


def test_mode_menu_locks_when_pinned_by_env(monkeypatch):
    w = _window(monkeypatch, "novice")          # SRM_CAM_MODE is set
    assert not w.act_novice.isEnabled()
    assert not w.act_pro.isEnabled()
    assert w.act_novice.isChecked()
    w.close()


def test_mode_menu_is_usable_when_not_pinned(monkeypatch, isolated_settings):
    monkeypatch.delenv("SRM_CAM_MODE", raising=False)
    w = MainWindow()
    assert w.act_novice.isEnabled() and w.act_pro.isEnabled()
    w.close()


# ---- the claim that matters ------------------------------------------------

def test_novice_and_professional_export_identical_files(tmp_path, monkeypatch):
    """Same board, same preset, same bytes. Novice hides controls; it must
    never change what comes out of them."""
    wp = _window(monkeypatch, "pro")
    wp.load_folder(str(FIXT))
    pro_files = wp.export_to(tmp_path / "pro")
    wp.close()

    wn = _window(monkeypatch, "novice")
    wn.load_folder(str(FIXT))
    novice_files = wn.export_to(tmp_path / "novice")
    wn.close()

    assert [p.name for p in pro_files] == [p.name for p in novice_files]
    assert pro_files, "no files exported"
    for a, b in zip(pro_files, novice_files):
        assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8"), \
            f"{a.name} differs between Novice and Professional"


def test_tour_steps_over_put_away_widgets(monkeypatch):
    """The core tour walks professional controls too. In Novice those are
    hidden, and pointing a spotlight at nothing is worse than skipping."""
    w = _window(monkeypatch, "novice")
    w.show(); _app.processEvents()
    assert w.tour._is_put_away(w.connect_btn)
    assert w.tour._is_put_away(w.double_sided_chk)   # inside a hidden group
    assert not w.tour._is_put_away(w.load_btn)
    w.close()


def test_corner_from_tool_is_offered_in_novice(monkeypatch):
    """This was Professional-only while Novice hid the machine link entirely.
    Once Novice gained guided probing that stopped being true, and without it a
    beginner's only way to say where their copper sits is to TYPE machine
    coordinates they cannot know — so the design, and the probe grid that
    follows it, land somewhere arbitrary."""
    w = _window(monkeypatch, "novice")
    w.show(); _app.processEvents()

    assert w.stock_here_btn.isVisible()
    assert w.stock_center_btn.isVisible()
    w.close()


def test_corner_from_tool_sets_the_stock_corner(monkeypatch):
    w = _window(monkeypatch, "novice")
    w._tool_xyz = (37.5, 22.2, -1.0)      # the spin boxes hold 1 decimal
    w._on_stock_corner_from_tool()
    assert w.stock_x_spin.value() == pytest.approx(37.5, abs=0.05)
    assert w.stock_y_spin.value() == pytest.approx(22.2, abs=0.05)
    assert w.stock_show_chk.isChecked()
    w.close()


def test_corner_from_tool_connects_on_demand(monkeypatch):
    """A Novice has no Connect button - it lives in the professional dock - so
    telling them to press it would make this unusable in the mode that needs it
    most."""
    w = _window(monkeypatch, "novice")
    started = []
    monkeypatch.setattr(w, "_autoselect_port", lambda: True)
    monkeypatch.setattr(w, "_start_dro", lambda: started.append(True))
    w._tool_xyz = None
    w._dro = None
    w._on_stock_corner_from_tool()
    assert started, "did not try to connect when nothing was connected yet"
    w.close()


def test_corner_from_tool_is_available_in_professional(monkeypatch):
    w = _window(monkeypatch, "pro")
    w.show(); _app.processEvents()

    assert w.stock_here_btn.isVisible()
    w.close()


def test_the_tour_does_not_teach_a_control_novices_cannot_see():
    """The tour runs in Novice by default. Telling a beginner to use
    'Corner = tool' points at something that is not on their screen."""
    from gerber2rml.gui.tour import steps

    placement = [s for s in steps.CORE_STEPS if s.target == "stock_center_btn"]

    assert placement, "the placement step should still exist"
    assert "Corner = tool" not in placement[0].body


# ---- guided bed leveling (Novice) -----------------------------------------

def test_novice_gets_the_guided_leveller_not_the_workbench(monkeypatch):
    """Probing is the biggest thing the Arduino buys a beginner: it makes cut
    depth follow the real surface. Novice gets one button for it; the grid /
    retouch / import-export workbench stays professional."""
    w = _window(monkeypatch, "novice")
    w.show(); _app.processEvents()
    w._goto_page(2)                       # the bed-leveling page
    _app.processEvents()
    assert w.novice_level_btn.isVisible()
    assert not w.level_grid_btn.isVisible()
    assert not w.level_table.isVisible()
    assert not w.level_retouch_spin.isVisible()
    w.close()


def test_professional_gets_the_workbench_not_the_guided_button(monkeypatch):
    w = _window(monkeypatch, "pro")
    w.show(); _app.processEvents()
    w._goto_page(2)
    _app.processEvents()
    assert not w.novice_level_btn.isVisible()
    assert w.level_grid_btn.isVisible()
    assert w.level_table.isVisible()
    w.close()


def test_guided_leveller_refuses_without_a_board(monkeypatch):
    """It must not reach for the serial port, let alone move anything, when
    there is no board to probe under."""
    from PySide6.QtWidgets import QMessageBox
    w = _window(monkeypatch, "novice")
    shown = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: shown.append(a[1:3]))
    probed = []
    monkeypatch.setattr(w, "_on_probe_spi", lambda: probed.append(True))
    w.state.gerber_dir = None
    w._on_novice_level()
    assert shown and "board" in shown[0][0].lower()
    assert not probed, "guided leveller tried to probe with no board loaded"
    w.close()


def test_guided_leveller_picks_the_arduino_port(monkeypatch):
    """The wrong port is the commonest first-time failure. On this lab PC the
    other port is Intel AMT Serial-over-LAN, which will never be a board."""
    import serial.tools.list_ports as lp

    class _P:
        def __init__(self, device, hwid):
            self.device, self.hwid = device, hwid

    monkeypatch.setattr(lp, "comports", lambda: [
        _P("COM3", "PCI VEN_8086 DEV_7AEB"),          # Intel AMT
        _P("COM4", "USB VID:PID=1A86:7523 SER= LOCATION=1-6"),
    ])
    w = _window(monkeypatch, "novice")
    w.level_port_combo.setCurrentText("COM3")     # the wrong one
    assert w._autoselect_port() is True
    assert w.level_port_combo.currentText() == "COM4"
    w.close()


def test_autoselect_keeps_a_deliberate_professional_choice(monkeypatch):
    """A pro who picked a board port on purpose must not have it overwritten."""
    import serial.tools.list_ports as lp

    class _P:
        def __init__(self, device, hwid):
            self.device, self.hwid = device, hwid

    monkeypatch.setattr(lp, "comports", lambda: [
        _P("COM4", "USB VID:PID=1A86:7523"),
        _P("COM9", "USB VID:PID=2341:0043"),
    ])
    w = _window(monkeypatch, "pro")
    w.level_port_combo.setCurrentText("COM9")     # deliberate, and a real board
    assert w._autoselect_port() is True
    assert w.level_port_combo.currentText() == "COM9"
    w.close()


def test_autoselect_reports_when_no_board_is_present(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    import serial.tools.list_ports as lp

    class _P:
        def __init__(self, device, hwid):
            self.device, self.hwid = device, hwid

    monkeypatch.setattr(lp, "comports", lambda: [_P("COM3", "PCI VEN_8086")])
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[1]))
    w = _window(monkeypatch, "novice")
    assert w._autoselect_port() is False
    assert warned and "Arduino" in warned[0]
    w.close()


# ---- seeing where it will probe -------------------------------------------

def test_novice_can_see_the_probe_points_without_moving(monkeypatch):
    """The grid is laid over the placed design, so drawing it also checks the
    design is where the student thinks it is."""
    w = _window(monkeypatch, "novice")
    w.load_folder(str(FIXT))
    probed = []
    monkeypatch.setattr(w, "_on_probe_spi", lambda: probed.append(True))

    w._on_novice_show_probes()
    assert w.level_table.rowCount() >= 4         # a grid got laid out
    assert w.level_gridshow_chk.isChecked()      # ...and is drawn
    assert not probed, "showing the probe points must not start a probe run"
    w.close()


def test_novice_detail_setting_changes_the_grid_size(monkeypatch):
    w = _window(monkeypatch, "novice")
    for idx, expected in ((0, 3), (1, 4), (2, 5)):
        w.novice_grid_combo.setCurrentIndex(idx)
        assert w.level_nx_spin.value() == expected
        assert w.level_ny_spin.value() == expected
    w.close()


def test_show_probes_needs_a_board(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    w = _window(monkeypatch, "novice")
    shown = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: shown.append(a[1]))
    w.state.board = None
    w._on_novice_show_probes()
    assert shown, "should explain rather than lay out a grid over nothing"
    w.close()

