"""Peck-drill engine tests (TDD)."""
from gerber2rml.config import DrillJob
from gerber2rml.engine.drill import drill_holes


def test_peck_count_reaches_total_depth():
    job = DrillJob(cut_depth=0.6, total_depth=1.8, travel_z=2.0)
    paths = drill_holes([(5.0, 5.0, 0.8)], job)
    assert len(paths) == 1
    tp = paths[0]
    depths = [m.z for m in tp if not m.rapid]
    assert min(depths) <= -1.8                 # reaches through the board
    assert tp[0].rapid and tp[0].z == 2.0      # starts lifted over the hole
    assert tp[-1].rapid and tp[-1].z == 2.0    # ends lifted


def test_one_path_per_hole():
    job = DrillJob()
    holes = [(1, 1, 0.8), (2, 2, 0.8), (3, 3, 1.0)]
    assert len(drill_holes(holes, job)) == 3
