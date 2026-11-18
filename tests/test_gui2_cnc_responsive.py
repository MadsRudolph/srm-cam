"""The CNC view stays responsive, and every move can be taken back.

A ground-poured board took a second or more of shapely for each of two
things the window did on every move: the copper checks, and the isolation
pass on the stage. The checks are now carried along with a board that only
moved, turned or mirrored; the isolation pass of a large board is built on
a worker while the window keeps running. And a move, a turn or a mirror is
one Ctrl+Z away.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from gerber2rml.engine.traces import isolate
from gerber2rml.gui2 import window as window_mod
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def loaded(qt_app):
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.set_tier("full")
    w.load_folder(str(FIXT))
    yield w
    w._wait_toolpaths()
    w.close()


def _where(w):
    st = w.state
    return round(st.place_x, 6), round(st.place_y, 6), st.rotate, bool(st.mirror)


def _traces(w):
    return next(s for s in w.plan if s.kind == "run" and s.op == "traces")


# ------------------------------------------------------------------ undo
def test_a_drag_is_one_undo_and_one_redo(loaded):
    w = loaded
    start = _where(w)
    w.stage.placement_changed.emit(12.5, -3.0)
    moved = _where(w)
    assert moved != start
    assert w.undo_act.isEnabled() and w.undo_btn.isEnabled()
    w.undo_act.trigger()
    assert _where(w) == start
    assert w.inspector.setup.place_x.value() == pytest.approx(start[0])
    assert not w.undo_act.isEnabled() and w.redo_act.isEnabled()
    w.redo_act.trigger()
    assert _where(w) == moved


def test_typed_positions_in_a_burst_are_one_step(loaded):
    w = loaded
    start = _where(w)
    for k in range(1, 6):                   # a spin arrow held down
        w.action_place(start[0] + k, start[1])
    w.action_undo()
    assert _where(w) == start
    assert not w.placement_undo.can_undo()


def test_a_turn_and_a_mirror_are_undone_in_order(loaded):
    w = loaded
    start = _where(w)
    w.action_rotate(90)
    turned = _where(w)
    w.action_mirror(not w.state.mirror)
    assert _where(w)[3] != start[3]
    w.action_undo()
    assert _where(w) == turned
    assert w.inspector.setup.mirror.isChecked() == start[3]
    w.action_undo()
    assert _where(w) == start


def test_the_button_undoes_as_ctrl_z_does(loaded):
    w = loaded
    start = _where(w)
    w.stage.placement_changed.emit(5.0, 5.0)
    w.undo_btn.click()
    assert _where(w) == start


def test_ctrl_z_is_on_the_window_and_redo_on_two_keys(loaded):
    keys = [s.toString() for s in loaded.redo_act.shortcuts()]
    assert loaded.undo_act.shortcut().toString() == "Ctrl+Z"
    assert "Ctrl+Shift+Z" in keys and "Ctrl+Y" in keys


def test_a_number_field_keeps_its_own_ctrl_z(loaded):
    """Qt asks the focused field first; a spin box claims Ctrl+Z, so the
    window's undo does not fire while a number is being typed."""
    edit = loaded.inspector.setup.place_x.lineEdit()
    ev = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Z, Qt.ControlModifier)
    QApplication.sendEvent(edit, ev)
    assert ev.isAccepted()


def test_nothing_to_undo_says_so(loaded):
    said = []
    loaded.say = lambda level, text: said.append(text)
    loaded.action_undo()
    assert said == ["Nothing to undo."]


def test_a_new_board_starts_a_new_history(loaded):
    loaded.stage.placement_changed.emit(3.0, 0.0)
    loaded.load_folder(str(FIXT))
    assert not loaded.placement_undo.can_undo()


def test_a_panel_move_puts_back_only_the_board_that_moved(qt_app):
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    try:
        w.load_folder(str(FIXT))
        w.add_folder(str(FIXT))
        before = [(m.place_x, m.place_y) for m in w.state.boards]
        w.action_select_board(0)
        w.stage.placement_changed.emit(0.0, 20.0)
        assert [(m.place_x, m.place_y) for m in w.state.boards] != before
        w.action_undo()
        assert [(m.place_x, m.place_y) for m in w.state.boards] == \
            pytest.approx(before)
    finally:
        w.close()


# ---------------------------------------------------------- responsiveness
def test_a_moved_board_keeps_its_copper_checks(loaded, monkeypatch):
    w = loaded
    calls = []
    real = window_mod.isolation_bridges
    monkeypatch.setattr(window_mod, "isolation_bridges",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    w.refresh_checks()
    first = list(w._shorts)
    calls.clear()
    w.stage.placement_changed.emit(7.0, 3.0)
    w.action_place(w.state.place_x + 1.0, w.state.place_y)
    w.action_rotate(90)
    w.action_mirror(not w.state.mirror)
    assert calls == []                      # moved, turned, mirrored: reused
    assert len(w._shorts) == len(first)
    w.state.trace.bit_diameter += 0.1       # another bit: worked out again
    w.action_params_changed()
    assert calls


def test_the_carried_checks_match_a_fresh_run(loaded):
    w = loaded
    w.refresh_checks()
    w.action_rotate(270)
    w.action_place(w.state.place_x + 9.0, w.state.place_y + 4.0)
    carried = w._copper_drc(w._cut_copper())
    w._drc_memo = None
    fresh = w._copper_drc(w._cut_copper())
    assert sorted(s["gap"] for s in carried[0]) == \
        pytest.approx(sorted(s["gap"] for s in fresh[0]))
    for a, b in ((carried[2], fresh[2]), (carried[3], fresh[3])):
        if a is None or b is None:
            assert a is b
        else:
            assert a.symmetric_difference(b).area < 1e-6


def test_a_large_board_is_isolated_off_the_gui_thread(loaded, monkeypatch):
    w = loaded
    monkeypatch.setattr(MainWindow, "BACKGROUND_COORDS", 0)
    step = _traces(w)
    w._paths_cache = {}
    w._iso_memo = []
    w.select_step(step.key)
    assert w._toolpath_busy()               # handed to the worker...
    assert step.key not in w._paths_cache   # ...and nothing stale drawn
    w._wait_toolpaths()
    assert not w._toolpath_busy()
    paths = w._paths_cache[step.key][0]
    want = isolate(w.state.board.copper, w.cutting_trace(),
                   outline=w.state.board.outline)
    assert paths == want                    # the very same pass


def test_the_latest_move_wins(loaded, monkeypatch):
    w = loaded
    monkeypatch.setattr(MainWindow, "BACKGROUND_COORDS", 0)
    step = _traces(w)
    w.select_step(step.key)
    w.stage.placement_changed.emit(30.0, 0.0)     # while it is building
    w.stage.placement_changed.emit(0.0, 15.0)
    w._wait_toolpaths()
    w._wait_toolpaths()
    paths = w._paths_cache[step.key][0]
    want = isolate(w.state.board.copper, w.cutting_trace(),
                   outline=w.state.board.outline)
    assert paths == want                    # for where the board is now


def test_a_small_board_is_drawn_at_once(loaded):
    step = _traces(loaded)
    loaded._paths_cache = {}
    loaded._iso_memo = []
    loaded.select_step(step.key)
    assert not loaded._toolpath_busy()
    assert step.key in loaded._paths_cache
