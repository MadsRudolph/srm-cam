"""Per-diameter drill splitting + single-bit interpolation (TDD)."""
from gerber2rml.config import DrillJob
from gerber2rml.engine.drill import (
    group_holes_by_diameter, format_diameter, drill_single_bit, drill_jobs,
)


def test_group_holes_by_diameter_ascending():
    holes = [(0, 0, 1.0), (1, 1, 0.8), (2, 2, 1.0), (3, 3, 0.8), (4, 4, 0.8)]
    groups = group_holes_by_diameter(holes)
    assert [d for d, _ in groups] == [0.8, 1.0]        # ascending
    assert len(groups[0][1]) == 3 and len(groups[1][1]) == 2


def test_format_diameter():
    assert format_diameter(0.8) == "0.8"
    assert format_diameter(1.0) == "1.0"
    assert format_diameter(1.52) == "1.52"


def test_drill_jobs_splits_per_diameter():
    holes = [(0, 0, 0.8), (1, 1, 1.0), (2, 2, 0.8)]
    files = drill_jobs(holes, DrillJob(), "b_drill")
    names = [f for f, _ in files]
    assert names == ["b_drill_0.8mm.rml", "b_drill_1.0mm.rml"]   # smallest first


def test_drill_jobs_single_bit_one_file():
    holes = [(0, 0, 0.8), (1, 1, 1.2)]
    files = drill_jobs(holes, DrillJob(single_bit=True, bit_diameter=0.8), "b_drill")
    assert [f for f, _ in files] == ["b_drill.rml"]


def test_single_bit_plunges_small_interpolates_large():
    job = DrillJob(single_bit=True, bit_diameter=0.8)
    # a 0.8 mm hole fits the bit -> straight plunge (few moves, all at one x,y)
    small = drill_single_bit([(5.0, 5.0, 0.8)], job)[0]
    xs = {round(m.x, 3) for m in small}
    assert xs == {5.0}                                  # never moves off centre

    # a 2.0 mm hole is larger than the bit -> interpolated circle (path sweeps XY)
    big = drill_single_bit([(5.0, 5.0, 2.0)], job)[0]
    xs_big = {round(m.x, 3) for m in big}
    assert len(xs_big) > 5                               # traces a circle
    # circle radius = (hole - bit)/2 = 0.6 -> max offset from centre ~0.6 mm
    max_off = max(abs(m.x - 5.0) for m in big)
    assert abs(max_off - 0.6) < 0.05
