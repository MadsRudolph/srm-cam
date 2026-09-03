"""Several boards on one sheet, in the second interface.

The properties worth holding: a press picks the board under it and a drag
moves that board alone; the checks say when two boards cannot be cut apart
and the export refuses to write them; centring keeps the panel's shape; a
double-sided job stays one board; and a saved setup brings every board back
where it was.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def win(qt_app):
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    yield w
    w.close()


@pytest.fixture
def two(win):
    win.load_folder(str(FIXT))
    win.add_folder(str(FIXT))
    return win


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


def _centre_px(stage, member):
    x0, y0, x1, y1 = stage._members[member].bounds
    return stage.to_px((x0 + x1) / 2, (y0 + y1) / 2)


def _drag_member(win, i, dx_px=60, dy_px=-40, steps=6):
    stage = win.stage
    start = _centre_px(stage, i)
    _press(stage, start)
    for k in range(1, steps + 1):
        _move(stage, start + QPointF(dx_px * k / steps, dy_px * k / steps))
    _release(stage, start + QPointF(dx_px, dy_px))


# ------------------------------------------------------------- the sheet
def test_a_second_board_lands_beside_the_first(two):
    st = two.state
    assert st.is_panel and len(st.boards) == 2
    assert st.name == "buck+buck_2"
    assert two.stage.members() == ["buck", "buck 2"]
    a, b = (m.bounds() for m in st.boards)
    assert b[0] > a[2]


def test_the_rail_says_how_many_boards(two):
    assert "2 boards" in two.traveller.job_facts.text()
    two.action_remove_board()
    assert "boards" not in two.traveller.job_facts.text()


def test_a_typed_name_survives_boards_coming_and_going(win):
    win.load_folder(str(FIXT))
    win.action_name("mine")
    win.add_folder(str(FIXT))
    assert win.state.name == "mine"
    win.action_remove_board()
    assert win.state.name == "mine"


def test_the_setup_page_lists_the_boards_and_names_the_picked_one(two):
    page = two.inspector.setup
    assert page.boards.isVisibleTo(two) and page.boards.count() == 2
    assert page.boards.currentRow() == 1
    assert "buck 2" in page.place_section.label.text()
    assert page.src_section.label.text() == "The boards"


# ---------------------------------------------------------- picking, moving
def test_dragging_one_board_moves_only_that_board(two):
    st = two.state
    before = [m.bounds() for m in st.boards]
    _drag_member(two, 0, dx_px=80, dy_px=-50)      # right, and up the screen
    after = [m.bounds() for m in st.boards]
    assert after[0][0] > before[0][0] and after[0][1] > before[0][1]
    assert after[1] == before[1]
    assert st.current == 0                         # the press picked it


def test_clicking_a_board_picks_it_for_the_setup_page(two):
    st = two.state
    assert st.current == 1
    c = _centre_px(two.stage, 0)
    _press(two.stage, c)
    _release(two.stage, c)
    assert st.current == 0
    assert two.inspector.setup.boards.currentRow() == 0
    assert "buck sits" in two.inspector.setup.place_section.label.text()
    assert (two.inspector.setup.place_x.value(),
            two.inspector.setup.place_y.value()) == (0.0, 0.0)


def test_a_press_between_boards_moves_nothing(two):
    st = two.state
    stage = two.stage
    a, b = st.boards[0].bounds(), st.boards[1].bounds()
    pt = stage.to_px((a[2] + b[0]) / 2, (a[1] + a[3]) / 2)
    before = [m.bounds() for m in st.boards]
    _press(stage, pt)
    _move(stage, pt + QPointF(50, 0))
    _release(stage, pt + QPointF(50, 0))
    assert [m.bounds() for m in st.boards] == before


def test_the_placement_spinners_move_the_picked_board(two):
    st = two.state
    first = st.boards[0].bounds()
    two.action_place(st.place_x, st.place_y + 30.0)
    assert st.boards[0].bounds() == first
    assert st.boards[1].bounds()[1] == pytest.approx(first[1] + 30.0)


def test_centring_moves_the_panel_as_one(two):
    st = two.state
    two.action_stock(203.2, 152.4, 0.0, 0.0)
    a0, b0 = (m.bounds() for m in st.boards)
    rel = (b0[0] - a0[0], b0[1] - a0[1])
    two.action_autoplace()
    a1, b1 = (m.bounds() for m in st.boards)
    assert (b1[0] - a1[0], b1[1] - a1[1]) == pytest.approx(rel)
    x0, _y0, x1, _y1 = two.job_extent()
    assert x0 == pytest.approx(203.2 - x1, abs=0.01)


def test_laying_them_side_by_side_separates_overlapping_boards(two):
    def panel_fails():
        return [c.title for c in two._checks
                if c.level == "fail" and "boards" in c.title.lower()]
    two.action_place(0.0, 0.0)                     # board 2 onto board 1
    two.refresh_checks()
    assert panel_fails() == ["Two boards overlap"]
    two.action_arrange()
    two.refresh_checks()
    assert panel_fails() == []
    a, b = (m.bounds() for m in two.state.boards)
    assert b[0] == pytest.approx(a[2] + 4.0)


# --------------------------------------------------------------- the checks
def test_overlapping_boards_fail_the_checks_and_block_the_export(
        two, tmp_path, monkeypatch):
    two.action_place(0.0, 0.0)
    two.refresh_checks()
    assert any("overlap" in c.title.lower()
               for c in two._checks if c.level == "fail")
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(tmp_path))
    said = []
    monkeypatch.setattr(two, "say", lambda level, text: said.append((level, text)))
    two.action_export()
    assert not list(tmp_path.glob("*.nc"))
    assert said and said[-1][0] == "fail"
    assert two.traveller.current() == "checks"


def test_boards_too_close_to_cut_apart_are_refused(two):
    st = two.state
    a = st.boards[0].bounds()
    m = st.boards[1]
    bit = st.cutout.bit_diameter
    two.action_place(m.place_x + (a[2] + bit / 2) - m.bounds()[0], m.place_y)
    two.refresh_checks()
    assert any("too close" in c.title.lower()
               for c in two._checks if c.level == "fail")


def test_a_thin_strip_of_waste_is_a_warning(two):
    st = two.state
    a = st.boards[0].bounds()
    m = st.boards[1]
    bit = st.cutout.bit_diameter
    two.action_place(m.place_x + (a[2] + 2 * bit + 0.3) - m.bounds()[0],
                     m.place_y)
    two.refresh_checks()
    warns = [c for c in two._checks
             if c.level == "warn" and "nearly touching" in c.title]
    assert warns and "0.30 mm wide" in warns[0].detail


def test_a_comfortable_gap_passes(two):
    two.refresh_checks()
    ok = [c for c in two._checks
          if c.title == "The boards keep clear of each other"]
    assert ok and "4.0 mm apart" in ok[0].detail


def test_the_probe_grid_spans_every_board(two):
    x0, _y0, x1, _y1 = two.work_bounds()
    assert x0 <= two.state.boards[0].bounds()[0] + 1e-6
    assert x1 >= two.state.boards[1].bounds()[2] - 1e-6


# ------------------------------------------------------------ double-sided
def test_double_sided_is_refused_on_a_panel(two):
    two.inspector.setup.double.setChecked(True)
    assert not two._double
    assert not two.inspector.setup.double.isChecked()


def test_adding_a_board_to_a_double_sided_job_is_refused(win):
    win.load_folder(str(FIXT))
    win.action_double_sided(True)
    win.add_folder(str(FIXT))
    assert len(win.state.boards) == 1 and win._double


# ------------------------------------------------------------------ output
def test_the_export_writes_one_set_of_files_and_the_sheet_lists_the_boards(
        two, tmp_path):
    two.select_step("cutout_run")
    assert two.stage._cuts
    written = two.export_to(tmp_path)
    names = [Path(p).name for p in written]
    assert "buck+buck_2_traces.nc" in names
    assert names.count("buck+buck_2_cutout.nc") == 1
    text = two.sheet.text()
    assert "2 boards on the sheet" in text and "buck 2:" in text


def test_the_legend_names_the_picked_board_only_on_a_panel(two):
    two.select_step("traces_run")
    assert any("being moved" in t for _c, t in two.stage._legend)
    two.action_remove_board()
    two.select_step("traces_run")
    assert not any("being moved" in t for _c, t in two.stage._legend)


def test_taking_a_board_off_leaves_a_plain_job(two):
    two.action_remove_board()
    st = two.state
    assert not st.is_panel and st.name == "buck"
    assert two.stage.members() == []
    assert not two.inspector.setup.boards.isVisibleTo(two)


def test_the_setup_round_trips_the_panel(two, tmp_path, monkeypatch):
    st = two.state
    two.action_place(50.0, 20.0)
    two.action_rotate(90)
    path = tmp_path / "p.srmcam"
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(path), ""))
    two.action_save_setup()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["boards"]) == 2 and data["boards"][1]["rotate"] == 90
    fresh = MainWindow()
    try:
        monkeypatch.setattr(
            "PySide6.QtWidgets.QFileDialog.getOpenFileName",
            lambda *a, **k: (str(path), ""))
        fresh.action_load_setup()
        back = fresh.state
        assert len(back.boards) == 2 and back.current == 1
        assert back.boards[1].rotate == 90
        assert (back.boards[1].place_x, back.boards[1].place_y) == (50.0, 20.0)
        assert back.boards[0].bounds() == st.boards[0].bounds()
        assert back.name == "buck+buck_2"
        assert fresh.stage.members() == ["buck", "buck 2"]
    finally:
        fresh.close()
