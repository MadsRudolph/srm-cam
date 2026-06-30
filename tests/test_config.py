"""Tests for job config dataclasses."""
import math

from gerber2rml.config import TraceJob, DrillJob, CutoutJob, BoardConfig


def test_trace_defaults_match_srm20():
    j = TraceJob()
    assert j.bit_diameter == 0.4
    assert j.cut_depth == 0.15
    assert j.offsets == 2
    assert j.xy_feed == 4.0
    assert j.plunge_feed == 1.0


# -- V-bit geometry --------------------------------------------------------

def test_flat_tool_is_the_default():
    j = TraceJob()
    assert j.tool_type == "flat"


def test_flat_effective_diameter_is_bit_diameter():
    j = TraceJob(bit_diameter=0.8, cut_depth=0.15)
    assert j.effective_diameter() == 0.8
    assert j.effective_cut_depth() == 0.15


def test_vbit_width_at_depth_follows_the_formula():
    # W = T + 2*D*tan(theta/2)
    j = TraceJob(tool_type="vbit", tip_diameter=0.1, included_angle=30.0)
    d = 0.2
    expected = 0.1 + 2 * d * math.tan(math.radians(30.0) / 2)
    assert math.isclose(j.width_at_depth(d), expected, rel_tol=1e-9)


def test_vbit_depth_is_back_solved_from_target_width():
    # width-first: operator sets target_width, depth is derived
    j = TraceJob(tool_type="vbit", tip_diameter=0.1, included_angle=30.0,
                 target_width=0.2)
    expected_depth = (0.2 - 0.1) / (2 * math.tan(math.radians(30.0) / 2))
    assert math.isclose(j.effective_cut_depth(), expected_depth, rel_tol=1e-9)
    # and the effective diameter at that depth is the target width again
    assert math.isclose(j.effective_diameter(), 0.2, rel_tol=1e-9)


def test_vbit_width_sensitivity_is_two_tan_half_angle():
    j = TraceJob(tool_type="vbit", included_angle=60.0)
    assert math.isclose(j.width_sensitivity(), 2 * math.tan(math.radians(30.0)),
                        rel_tol=1e-9)


def test_vbit_target_below_tip_clamps_to_zero_depth():
    # a target narrower than the tip can't be cut shallower than 0 depth
    j = TraceJob(tool_type="vbit", tip_diameter=0.2, included_angle=30.0,
                 target_width=0.1)
    assert j.effective_cut_depth() == 0.0
    assert j.effective_diameter() == 0.2


def test_cutout_has_tabs():
    c = CutoutJob()
    assert c.bit_diameter == 0.8
    assert c.tabs == 4
    assert c.tab_width == 1.5


def test_board_thickness_default():
    assert BoardConfig().thickness == 1.6


def test_drill_total_depth():
    assert DrillJob().total_depth == 1.8
