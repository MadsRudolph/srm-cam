"""Tests for the toolpath playback model (3D simulation backing logic)."""
import os
import math
import pytest
from gerber2rml.toolpath import Move
from gerber2rml.engine.simulate import (
    build_path, split_segments, index_at, position_at, total_length)


def _tp(*pts):
    """One toolpath from (x, y, z, rapid) tuples."""
    return [Move(x, y, z, rapid) for (x, y, z, rapid) in pts]


def test_sim3d_window_draws_board_and_bed():
    """The 3D viewer adds the stock slab + bed when given them (needs OpenGL)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    try:
        from gerber2rml.gui.sim3d import Simulation3DWindow
        tp = [_tp((2, 2, 2.0, True), (2, 2, -0.15, False),
                  (30, 20, -0.15, False), (2, 2, 2.0, True))]
        bare = Simulation3DWindow(tp)
        full = Simulation3DWindow(tp, board=(2, 2, 30, 20), bed=(203.2, 152.4))
    except Exception as e:                       # no pyqtgraph / no GL context
        pytest.skip(f"3D view unavailable: {e}")
    # board slab + bed outline + home marker + board top outline add 4 items
    assert len(full.view.items) == len(bare.view.items) + 4


def test_build_path_concatenates_in_machine_order():
    tps = [_tp((0, 0, 2, True), (0, 0, -0.1, False), (3, 0, -0.1, False)),
           _tp((3, 0, 2, True), (3, 4, 2, True))]
    pts, is_rapid, cum = build_path(tps)
    assert pts[0] == (0, 0, 2) and pts[-1] == (3, 4, 2)
    assert len(pts) == 5 and len(cum) == 5
    assert is_rapid == [True, False, False, True, True]
    # cumulative length: plunge 2.1, cut 3, retract 2.1, traverse 4
    assert math.isclose(cum[-1], 2.1 + 3 + 2.1 + 4, rel_tol=1e-9)


def test_split_segments_colours_by_arriving_move():
    pts, is_rapid, _ = build_path(
        [_tp((0, 0, 2, True), (0, 0, 0, False), (5, 0, 0, False), (5, 0, 2, True))])
    cut, rapid = split_segments(pts, is_rapid)
    # plunge + lateral are feed (G1) moves -> cut; only the retract is a rapid
    assert len(cut) == 2 and ((0, 0, 0), (5, 0, 0)) in cut      # the lateral cut
    assert len(rapid) == 1 and rapid[0] == ((5, 0, 0), (5, 0, 2))  # retract


def test_position_at_endpoints_and_midpoint():
    tps = [_tp((0, 0, 0, False), (10, 0, 0, False))]
    pts, _r, cum = build_path(tps)
    assert position_at(pts, cum, 0) == (0, 0, 0)
    assert position_at(pts, cum, 10) == (10, 0, 0)
    mid = position_at(pts, cum, 5)
    assert math.isclose(mid[0], 5.0) and math.isclose(mid[1], 0.0)


def test_position_clamps_past_the_end():
    tps = [_tp((0, 0, 0, False), (4, 0, 0, False))]
    pts, _r, cum = build_path(tps)
    assert position_at(pts, cum, 999) == (4, 0, 0)


def test_index_at_advances_with_distance():
    tps = [_tp((0, 0, 0, False), (1, 0, 0, False), (2, 0, 0, False))]
    _p, _r, cum = build_path(tps)        # cum = [0, 1, 2]
    assert index_at(cum, 0) == 1
    assert index_at(cum, 0.5) == 1
    assert index_at(cum, 1.5) == 2
    assert index_at(cum, 5) == 3         # clamped to vertex count


def test_total_length_matches_cumulative():
    tps = [_tp((0, 0, 0, False), (3, 4, 0, False))]   # 3-4-5 triangle
    assert math.isclose(total_length(tps), 5.0)


def test_empty_toolpaths_are_safe():
    pts, is_rapid, cum = build_path([])
    assert pts == [] and cum == [0.0]
    assert position_at(pts, cum, 1.0) is None
    assert total_length([]) == 0.0
