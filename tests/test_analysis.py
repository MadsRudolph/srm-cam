"""Tests for isolation preflight analysis."""

from shapely.geometry import box
from gerber2rml.analysis import find_narrow_gaps


def test_flags_gap_narrower_than_bit():
    """A copper-free channel narrower than the bit diameter should be flagged."""
    outline = box(0, 0, 20, 20)
    copper = box(2, 2, 9.7, 18).union(box(10.3, 2, 18, 18))  # 0.6 mm gap
    gaps = find_narrow_gaps(copper, outline, bit_diameter=0.8)
    assert not gaps.is_empty  # 0.6 mm < 0.8 mm bit -> flagged


def test_no_flag_when_gap_wide_enough():
    """A copper-free channel wider than the bit diameter should not be flagged."""
    outline = box(0, 0, 20, 20)
    copper = box(2, 2, 8, 18).union(box(12, 2, 18, 18))  # 4 mm gap
    gaps = find_narrow_gaps(copper, outline, bit_diameter=0.8)
    assert gaps.is_empty
