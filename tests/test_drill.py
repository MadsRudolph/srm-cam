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


def test_peck_count_is_exact():
    job = DrillJob(cut_depth=0.6, total_depth=1.8, travel_z=2.0)
    tp = drill_holes([(0.0, 0.0, 0.8)], job)[0]
    cut_moves = [m for m in tp if not m.rapid]
    assert len(cut_moves) == 3            # no double-peck at the bottom

def test_single_peck_when_bit_reaches_through():
    job = DrillJob(cut_depth=2.0, total_depth=1.8, travel_z=2.0)
    tp = drill_holes([(0.0, 0.0, 0.8)], job)[0]
    cut_moves = [m for m in tp if not m.rapid]
    assert len(cut_moves) == 1


def test_intermediate_pecks_do_not_lift_to_full_travel_height():
    # The bit must only reach travel_z twice (approach + final retract); the
    # lifts between pecks of one hole stay at the small peck_retract clearance.
    job = DrillJob(cut_depth=0.6, total_depth=1.8, travel_z=2.0, peck_retract=0.5)
    tp = drill_holes([(0.0, 0.0, 0.8)], job)[0]
    rapid_z = [m.z for m in tp if m.rapid]
    assert rapid_z.count(2.0) == 2                 # approach + leave-hole only
    assert 0.5 in rapid_z                          # chip-clearing lift uses it
    assert max(rapid_z) == 2.0                     # nothing above travel height
