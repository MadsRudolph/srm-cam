"""Several boards on one sheet of copper, cut as one job.

The engine is never told. It is handed one board whose copper is every
board's copper, whose outline is every outline and whose holes are all of
them, so isolation, the shorts check, levelling and the checks work as they
always did. What has to change is small and is tested here: the cut-out and
the dry run visit every island, the state keeps a list of placed boards and
composes them, and the export writes one set of files for the lot.
"""
import re
from pathlib import Path

import pytest
from shapely.geometry import MultiPolygon, box

from gerber2rml.app import panel
from gerber2rml.app.state import ProjectState
from gerber2rml.config import CutoutJob
from gerber2rml.engine import airpass
from gerber2rml.engine.cutout import cut_outline
from gerber2rml.gui2 import runplan

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def coupon(tmp_path):
    """A second, different board: the bundled calibration coupon."""
    from gerber2rml.examples.calibration import write_coupon
    d = tmp_path / "coupon"
    write_coupon(d)
    return d


def _two(name="two"):
    st = ProjectState(name=name)
    st.load(FIXT)
    st.add_board(FIXT)
    return st


def _size(bounds):
    return bounds[2] - bounds[0], bounds[3] - bounds[1]


# ---------------------------------------------------------------- the engine
def test_the_cut_out_frees_every_board():
    """Two islands: two rings, each with its own tabs, both ridden outside."""
    two = MultiPolygon([box(0, 0, 20, 10), box(30, 0, 50, 10)])
    job = CutoutJob(bit_diameter=0.8, tabs=2, tab_width=1.5,
                    cut_depth=0.6, total_depth=0.6)
    paths = cut_outline(two, job)
    one = cut_outline(box(0, 0, 20, 10), job)
    assert len(paths) == 2 * len(one)
    xs = [m.x for tp in paths for m in tp if not m.rapid]
    assert min(xs) < 0 and max(xs) > 50
    assert any(x < 21 for x in xs) and any(x > 29 for x in xs)


def test_the_cut_out_finishes_one_board_before_starting_the_next():
    """Each island to full depth first, left to right - not a flight across
    the sheet for every pass of every board."""
    two = MultiPolygon([box(30, 0, 50, 10), box(0, 0, 20, 10)])
    job = CutoutJob(bit_diameter=0.8, tabs=0, cut_depth=0.6, total_depth=1.8)
    paths = cut_outline(two, job)
    sides = ["left" if max(m.x for m in tp) < 25 else "right" for tp in paths]
    assert sides[0] == "left"
    assert sum(1 for a, b in zip(sides, sides[1:]) if a != b) == 1
    assert sides.count("left") == sides.count("right") >= 3


def test_a_single_board_cut_out_is_what_it_was():
    """One ring, cut in passes, as before. The golden files hold the bytes."""
    job = CutoutJob(tabs=4, tab_width=1.5, cut_depth=0.6, total_depth=1.2)
    paths = cut_outline(box(0, 0, 20, 20), job)
    assert len(paths) == 4 * 2               # four segments, two passes


def test_the_dry_run_traces_every_board():
    two = MultiPolygon([box(30, 0, 50, 10), box(0, 0, 20, 10)])
    paths = airpass.air_path(two, height=5.0)
    assert len(paths) == 2
    assert {m.z for tp in paths for m in tp} == {5.0}
    for tp in paths:
        assert (round(tp[0].x, 6), round(tp[0].y, 6)) == \
            (round(tp[-1].x, 6), round(tp[-1].y, 6))
    left, right = paths
    assert max(m.x for m in left) <= 20 and min(m.x for m in right) >= 30


# -------------------------------------------------------------- composition
def test_composing_two_boards_keeps_every_hole_and_both_outlines():
    st = ProjectState()
    st.load(FIXT)
    one = st.board
    st.add_board(FIXT)
    two = st.board
    assert len(two.holes) == 2 * len(one.holes)
    assert two.outline.geom_type == "MultiPolygon"
    assert len(two.outline.geoms) == 2
    assert two.copper.area == pytest.approx(2 * one.copper.area, rel=1e-6)


def test_one_board_is_exactly_what_it_was():
    st = ProjectState()
    st.load(FIXT)
    assert not st.is_panel
    assert st.board is st.boards[0].board()
    assert st.gerber_dir == FIXT and (st.place_x, st.place_y) == (0.0, 0.0)


def test_a_second_board_lands_beside_the_first_with_waste_between():
    st = ProjectState()
    st.load(FIXT)
    a = st.boards[0]
    b = st.add_board(FIXT)
    ax0, ay0, ax1, _ay1 = a.bounds()
    bx0, by0, _bx1, _by1 = b.bounds()
    assert bx0 == pytest.approx(ax1 + panel.PANEL_GAP_MM)
    assert by0 == pytest.approx(ay0)
    assert (a.name, b.name) == ("buck", "buck 2")
    # the newcomer is the one being worked on
    assert st.current == 1 and st.gerber_dir == b.gerber_dir
    assert (st.place_x, st.place_y) == (b.place_x, b.place_y)


def test_a_different_board_keeps_its_own_name(coupon):
    st = ProjectState()
    st.load(FIXT)
    assert st.add_board(coupon).name == "calib"


def test_placing_one_board_leaves_the_other_where_it_was():
    st = _two()
    first = st.boards[0].bounds()
    st.set_placement(st.place_x, st.place_y + 25.0)      # board 2 is current
    assert st.boards[0].bounds() == first
    assert st.boards[1].bounds()[1] == pytest.approx(first[1] + 25.0)
    st.select_board(0)
    assert (st.place_x, st.place_y) == (0.0, 0.0)


def test_turning_one_board_leaves_the_other_alone():
    st = _two()
    w, h = _size(st.boards[0].bounds())
    st.set_rotation(90)
    assert _size(st.boards[1].bounds()) == pytest.approx((h, w))
    assert st.boards[0].rotate == 0
    assert _size(st.boards[0].bounds()) == pytest.approx((w, h))


def test_the_placed_board_is_the_same_object_until_it_moves():
    """The stage keys its built paths and its raster on identity."""
    st = _two()
    m = st.boards[1]
    assert m.board() is m.board()
    was = m.board()
    st.set_placement(st.place_x + 1.0, st.place_y)
    assert m.board() is not was


def test_moving_everything_keeps_the_panel_together():
    st = _two()
    before = [m.bounds() for m in st.boards]
    st.move_all(10.0, -5.0)
    for b0, m in zip(before, st.boards):
        assert m.bounds() == pytest.approx(
            (b0[0] + 10, b0[1] - 5, b0[2] + 10, b0[3] - 5))


def test_arranging_lays_the_boards_out_in_a_row():
    st = _two()
    st.add_board(FIXT)
    st.set_placement(0.0, 0.0)              # the third, dropped on the first
    assert panel.clearances(st.boards)[0][3]
    st.arrange()
    pairs = panel.clearances(st.boards)
    assert not any(ov for *_r, ov in pairs)
    assert min(gap for _a, _b, gap, _ov in pairs) == pytest.approx(
        panel.PANEL_GAP_MM)


def test_clearances_name_the_worst_pair_first():
    st = _two()
    st.add_board(FIXT)
    st.set_placement(0.0, 0.0)
    a, b, gap, overlap = panel.clearances(st.boards)[0]
    assert {a, b} == {"buck", "buck 3"}
    assert overlap and gap == 0.0


def test_removing_a_board_leaves_a_plain_job():
    st = _two()
    st.remove_board(1)
    assert not st.is_panel and st.current == 0
    assert st.board is st.boards[0].board()
    st.remove_board(0)
    assert st.board is None and st.gerber_dir is None


def test_removing_a_board_before_the_current_one_keeps_the_selection():
    st = _two()
    st.add_board(FIXT)
    st.select_board(2)
    st.remove_board(0)
    assert st.current == 1 and st.boards[1].name == "buck 3"


def test_mirroring_re_reads_every_board():
    st = _two()
    before = st.boards[1].board().copper
    st.mirror = False
    st.reload()
    after = st.boards[1].board().copper
    assert after.symmetric_difference(before).area > 1.0


# ------------------------------------------------------------------ export
def test_the_export_cuts_every_board_in_one_set_of_files(tmp_path):
    st = _two()
    written = st.export(tmp_path)
    names = [Path(p).name for p in written]
    assert names.count("two_traces.nc") == 1 and "two_cutout.nc" in names
    # the plan the interface shows is the files the engine wrote, in order
    assert runplan.build(st).files == [n for n in names if n.endswith(".nc")]
    text = (tmp_path / "two_traces.nc").read_text(encoding="utf-8")
    xs = [float(v) for v in re.findall(r"X(-?\d+\.?\d*)", text)]
    assert max(xs) > st.boards[1].bounds()[0]           # reaches board 2
    assert min(xs) < st.boards[0].bounds()[2]           # and board 1
    assert len(st.toolpaths("drill")) == 2 * len(st.boards[0].board().holes)


def test_the_run_plan_says_where_each_board_is(tmp_path):
    st = _two()
    st.export(tmp_path)
    rp = (tmp_path / "two_runplan.txt").read_text(encoding="utf-8")
    assert "Boards on the sheet" in rp and "buck 2:" in rp
    x0, y0, _x1, _y1 = st.boards[1].bounds()
    assert f"X{x0:.2f} Y{y0:.2f}" in rp


def test_a_single_board_still_takes_the_folder_path(tmp_path, monkeypatch):
    """One board goes through build_jobs, the path the golden files cover."""
    import gerber2rml.app.state as state_mod
    calls = []
    monkeypatch.setattr(state_mod, "build_jobs",
                        lambda *a, **k: (calls.append(k), [])[1])
    st = ProjectState()
    st.load(FIXT)
    st.set_placement(3.0, 4.0)
    st.export(tmp_path)
    assert len(calls) == 1 and calls[0]["offset"] == (3.0, 4.0)


# ------------------------------------------------------- shared-edge cuts
def _runs_at_x(paths, x, tol=1e-3):
    return [tp for tp in paths
            if all(abs(m.x - x) <= tol for m in tp if not m.rapid)]


def test_touching_boards_get_one_cut_between_them():
    """Two rings would merge into one and leave the boards joined."""
    two = MultiPolygon([box(0, 0, 100, 100), box(100, 0, 200, 100)])
    job = CutoutJob(bit_diameter=0.8, tabs=4, tab_width=1.5,
                    cut_depth=0.6, total_depth=1.2)
    paths = cut_outline(two, job)
    seps = _runs_at_x(paths, 100.0)
    assert len(seps) == 2                          # one line, two passes
    assert seps[0] is paths[0], "the separator is cut first"
    ys = {round(m.y, 2) for tp in seps for m in tp if not m.rapid}
    assert ys == {0.0, 100.0}
    cut = [m for tp in paths for m in tp if not m.rapid]
    assert min(m.x for m in cut) == pytest.approx(-0.4)
    assert max(m.x for m in cut) == pytest.approx(200.4)
    # one ring round the lot: nothing else runs down the middle
    assert not [tp for tp in paths if tp not in seps
                and any(99.0 < m.x < 101.0 and 1.0 < m.y < 99.0 for m in tp)]


def test_the_shared_cut_is_centred_in_a_small_gap():
    two = MultiPolygon([box(0, 0, 100, 100), box(100.5, 0, 200.5, 100)])
    job = CutoutJob(bit_diameter=0.8, tabs=0, cut_depth=0.6, total_depth=0.6)
    assert len(_runs_at_x(cut_outline(two, job), 100.25)) == 1


def test_boards_further_apart_than_the_bit_get_their_own_rings():
    two = MultiPolygon([box(0, 0, 100, 100), box(101.0, 0, 201.0, 100)])
    job = CutoutJob(bit_diameter=0.8, tabs=0, cut_depth=0.6, total_depth=0.6)
    paths = cut_outline(two, job)
    assert len(paths) == 2
    xs = {round(m.x, 2) for tp in paths for m in tp if not m.rapid}
    assert {100.4, 100.6} <= xs                    # each ring on its own side


def test_an_edge_on_the_sheet_edge_is_not_cut():
    job = CutoutJob(bit_diameter=0.8, tabs=4, tab_width=1.5,
                    cut_depth=0.6, total_depth=0.6)
    board = box(5.0, 20.0, 105.0, 120.0)
    plain = cut_outline(board, job)
    on_edge = cut_outline(board, job, stock=(5.0, 10.0, 205.0, 160.0))
    cut = [m for tp in on_edge for m in tp if not m.rapid]
    assert min(m.x for m in cut) > 4.9                # the ring at 4.6 is gone
    assert max(m.x for m in cut) == pytest.approx(105.4)
    assert len(on_edge) >= len(plain)                 # still tabbed
    inside = cut_outline(board, job, stock=(0.0, 0.0, 200.0, 160.0))
    assert [[(m.x, m.y, m.z) for m in tp] for tp in inside] == \
        [[(m.x, m.y, m.z) for m in tp] for tp in plain]


def test_a_panel_that_fills_the_sheet_needs_only_the_middle_cut_and_the_ends():
    two = MultiPolygon([box(0, 0, 100, 100), box(100, 0, 200, 100)])
    job = CutoutJob(bit_diameter=0.8, tabs=4, tab_width=1.5,
                    cut_depth=0.6, total_depth=0.6)
    paths = cut_outline(two, job, stock=(0.0, -10.0, 200.0, 150.0))
    cut = [m for tp in paths for m in tp if not m.rapid]
    assert min(m.x for m in cut) > 0.5 and max(m.x for m in cut) < 199.5
    assert _runs_at_x(paths, 100.0)


def test_touching_boards_export_and_overlapping_ones_do_not(tmp_path):
    st = _two()
    st.arrange(0.0)
    written = st.export(tmp_path)
    assert any(Path(p).name.endswith("_cutout.nc") for p in written)
    st.set_placement(st.boards[0].place_x, st.boards[0].place_y)   # on top
    with pytest.raises(ValueError):
        st.export(tmp_path / "again")
