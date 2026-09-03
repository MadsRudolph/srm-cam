"""Arrow keys move the picked board by an exact amount.

Dragging places a board roughly; the last tenth of a millimetre is easier to
say than to do with a mouse.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def loaded(qt_app):
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.load_folder(str(FIXT))
    yield w
    w.close()


def _key(stage, key, mods=Qt.NoModifier):
    stage.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, key, mods))


def _click(stage, pt):
    stage.mousePressEvent(QMouseEvent(QMouseEvent.MouseButtonPress, pt,
                                      Qt.LeftButton, Qt.LeftButton,
                                      Qt.NoModifier))
    stage.mouseReleaseEvent(QMouseEvent(QMouseEvent.MouseButtonRelease, pt,
                                        Qt.LeftButton, Qt.NoButton,
                                        Qt.NoModifier))


def test_arrow_taps_nudge_the_board_and_commit_once(loaded):
    stage = loaded.stage
    commits = []
    stage.placement_changed.connect(lambda x, y: commits.append((x, y)))
    x0, y0 = loaded.state.place_x, loaded.state.place_y
    _key(stage, Qt.Key_Right)
    _key(stage, Qt.Key_Right)
    _key(stage, Qt.Key_Up)
    assert stage._drag_offset == (0.2, 0.1)          # drawn, not yet committed
    assert (loaded.state.place_x, loaded.state.place_y) == (x0, y0)
    assert stage._nudge_timer.isActive()
    stage._nudge_timer.stop()
    stage._commit_nudge()
    assert commits == [(0.2, 0.1)]
    assert (loaded.state.place_x, loaded.state.place_y) == \
        pytest.approx((x0 + 0.2, y0 + 0.1))


def test_shift_and_ctrl_change_the_step(loaded):
    stage = loaded.stage
    _key(stage, Qt.Key_Left, Qt.ShiftModifier)
    _key(stage, Qt.Key_Down, Qt.ControlModifier)
    assert stage._drag_offset == (-1.0, -0.01)
    stage._nudge_timer.stop()
    stage._commit_nudge()


def test_a_nudge_moves_only_the_picked_board_of_a_panel(loaded):
    loaded.add_folder(str(FIXT))
    st = loaded.state
    stage = loaded.stage
    x0, y0, x1, y1 = stage._members[0].bounds
    _click(stage, stage.to_px((x0 + x1) / 2, (y0 + y1) / 2))   # pick board 1
    assert st.current == 0
    before = [m.bounds() for m in st.boards]
    for _ in range(5):
        _key(stage, Qt.Key_Right)
    stage._nudge_timer.stop()
    stage._commit_nudge()
    after = [m.bounds() for m in st.boards]
    assert after[0][0] == pytest.approx(before[0][0] + 0.5)
    assert after[1] == before[1]


def test_arrows_do_nothing_in_jog_or_box_mode(loaded):
    stage = loaded.stage
    for mode in ("jog", "box", "screws"):
        loaded.set_stage_mode(mode)
        _key(stage, Qt.Key_Right)
        assert stage._drag_offset == (0.0, 0.0)
    loaded.set_stage_mode("place")


def test_a_click_during_a_nudge_commits_it_first(loaded):
    stage = loaded.stage
    commits = []
    stage.placement_changed.connect(lambda x, y: commits.append((x, y)))
    _key(stage, Qt.Key_Right)
    x0, y0, x1, y1 = loaded.state.board.outline.bounds
    _click(stage, stage.to_px((x0 + x1) / 2, (y0 + y1) / 2))
    assert commits == [(0.1, 0.0)]
    assert not stage._nudge_timer.isActive()
