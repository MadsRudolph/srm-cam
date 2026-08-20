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
    assert visible == ["1 · Set up board", "2 · Drill", "3 · Traces",
                       "4 · Cut out", "5 · Check in 3D"]
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


def test_corner_from_tool_is_not_offered_without_the_machine_link(monkeypatch):
    """'Corner = tool' reads the live tool position over the Arduino link, and
    Novice hides the machine dock entirely — so in Novice it is a button that
    cannot work. 'Center design' is pure placement and stays."""
    w = _window(monkeypatch, "novice")
    w.show(); _app.processEvents()

    assert not w.stock_here_btn.isVisible()
    assert w.stock_center_btn.isVisible()
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
