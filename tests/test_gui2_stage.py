"""The canvas: it has to stay responsive, and it has to stay truthful.

Both halves matter and they pull against each other. A trace pass for a
full-bed board is around twenty thousand path elements stroked at their real
cut width — roughly 190 ms per repaint — so the canvas caches what it has drawn
and blits it. Every caching bug in a viewer looks the same from the outside:
the picture stops matching the thing it is a picture of. So each test that
asserts something is fast is paired with one that asserts the pixels still
change when they should.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from gerber2rml import doublesided
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def win(qt_app):
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.load_folder(str(FIXT))
    yield w
    w.close()


def _press(stage, pt):
    stage.mousePressEvent(QMouseEvent(
        QMouseEvent.MouseButtonPress, pt, Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier))


def _move(stage, pt):
    stage.mouseMoveEvent(QMouseEvent(
        QMouseEvent.MouseMove, pt, Qt.NoButton, Qt.LeftButton, Qt.NoModifier))


def _release(stage, pt):
    stage.mouseReleaseEvent(QMouseEvent(
        QMouseEvent.MouseButtonRelease, pt, Qt.LeftButton, Qt.NoButton,
        Qt.NoModifier))


def _centre_of_work(stage):
    x0, y0, x1, y1 = stage._work_bounds()
    return stage.to_px((x0 + x1) / 2, (y0 + y1) / 2)


def _drag(stage, dx_px=60, dy_px=-40, steps=12):
    start = _centre_of_work(stage)
    _press(stage, start)
    for i in range(1, steps + 1):
        _move(stage, start + QPointF(dx_px * i / steps, dy_px * i / steps))
    _release(stage, start + QPointF(dx_px, dy_px))


# --------------------------------------------------------------- the drag
def test_a_drag_commits_once_not_once_per_mouse_move(win):
    """It used to emit on every mouse-move, and the receiver re-read the
    Gerbers off disk and re-ran the isolation offsetter each time."""
    commits, previews = [], []
    win.stage.placement_changed.connect(lambda x, y: commits.append((x, y)))
    win.stage.placement_dragging.connect(lambda x, y: previews.append((x, y)))
    _drag(win.stage, steps=12)
    assert len(commits) == 1, commits
    assert len(previews) == 12, len(previews)


def test_the_placement_only_changes_when_the_drag_lands(win):
    before = (win.state.place_x, win.state.place_y)
    stage = win.stage
    start = _centre_of_work(stage)
    _press(stage, start)
    _move(stage, start + QPointF(50, -30))
    assert (win.state.place_x, win.state.place_y) == before, \
        "the geometry moved while the mouse was still down"
    assert stage._drag_offset != (0.0, 0.0), "nothing is being previewed"
    _release(stage, start + QPointF(50, -30))
    assert (win.state.place_x, win.state.place_y) != before


def test_a_drag_moves_the_board_in_the_direction_it_was_dragged(win):
    x0 = win.state.place_x
    y0 = win.state.place_y
    _drag(win.stage, dx_px=80, dy_px=-50)          # right, and up the screen
    assert win.state.place_x > x0
    assert win.state.place_y > y0                  # screen-up is bed-forward


def test_a_drag_never_rebuilds_the_double_sided_layout(win, monkeypatch):
    """Building the layout re-reads the Gerbers, mirrors both copper layers and
    reflects them. Moving it is a handful of translates. Rebuilding it per
    mouse-move is what made a full-bed board crawl behind the cursor."""
    win.action_double_sided(True)
    win.select_step("bottom_traces")
    builds = []
    real = doublesided.layout_double_sided
    monkeypatch.setattr(doublesided, "layout_double_sided",
                        lambda *a, **k: (builds.append(1), real(*a, **k))[1])
    _drag(win.stage, steps=15)
    assert builds == [], f"the layout was rebuilt {len(builds)} times"


def test_dragging_leaves_the_machine_where_it_is(win):
    """The bed does not move when you slide the job across it."""
    stage = win.stage
    origin_before = QPointF(stage._origin)
    _drag(stage)
    assert stage._origin == origin_before


# ------------------------------------------------------- the drawn scene
def _render(stage):
    stage.repaint()
    return stage.grab().toImage()


def _differs(a, b):
    """Every pixel, not a sample of them.

    Travel moves are a one-pixel dotted line; a sampling comparison walked
    straight past them and reported that hiding them had changed nothing.
    """
    if a.size() != b.size():
        return True
    for y in range(a.height()):
        for x in range(a.width()):
            if a.pixel(x, y) != b.pixel(x, y):
                return True
    return False


def test_the_scene_is_cached_between_identical_repaints(win):
    win.select_step("traces_run")
    _render(win.stage)
    raster = win.stage._scene_raster
    assert raster is not None
    _render(win.stage)
    assert win.stage._scene_raster is raster, "the scene was re-rendered"


def test_selecting_the_same_step_again_keeps_the_cached_scene(win):
    win.select_step("traces_run")
    _render(win.stage)
    raster = win.stage._scene_raster
    win.select_step("traces_run")
    _render(win.stage)
    assert win.stage._scene_raster is raster


@pytest.mark.parametrize("change", [
    "step", "travel", "frame", "probe", "zoom", "stock",
])
def test_the_cached_scene_is_dropped_when_it_stops_being_true(win, change):
    """Every caching bug in a viewer looks the same from the outside: the
    picture stops matching the thing it is a picture of."""
    win.select_step("traces_run")
    before = _render(win.stage)
    if change == "step":
        win.select_step("drill_run")
    elif change == "travel":
        win.stage.set_travel_visible(False)
    elif change == "frame":
        win._on_frame("xray")
    elif change == "probe":
        win.stage.set_probe_points([(20, 20), (40, 40), (60, 25)])
    elif change == "zoom":
        win.stage._scale *= 1.6
        win.stage._invalidate()
    elif change == "stock":
        win.stage.set_stock((0, 0, 150, 120))
    after = _render(win.stage)
    assert _differs(before, after), f"the canvas did not react to: {change}"


def test_the_live_tool_marker_moves_without_re_rendering_the_scene(win):
    """The position poll runs three times a second while the machine is
    connected. If that dropped the cached scene, a linked machine would make
    the whole canvas re-stroke twenty thousand path elements at 3 Hz."""
    win.select_step("traces_run")
    win.stage.set_tool((30.0, 30.0))
    before = _render(win.stage)
    raster = win.stage._scene_raster
    win.stage.set_tool((90.0, 70.0))
    after = _render(win.stage)
    assert win.stage._scene_raster is raster, "the scene was needlessly redrawn"
    assert _differs(before, after), "the tool marker did not move"


def test_the_board_still_appears_where_it_was_dragged_to(win):
    """The end-to-end check on the whole caching scheme: after a drag lands,
    what is on the canvas is the board at its new placement — not the frozen
    picture the drag was blitting."""
    win.select_step("traces_run")
    before = _render(win.stage)
    _drag(win.stage, dx_px=70, dy_px=-45)
    win.stage._invalidate()
    after = _render(win.stage)
    assert _differs(before, after)
    assert win.stage._drag_raster is None
    assert win.stage._pan_raster is None
