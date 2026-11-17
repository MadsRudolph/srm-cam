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


def test_holes_are_drilled_in_a_short_order_not_file_order():
    import math
    import random
    from gerber2rml.engine.drill import order_holes
    rng = random.Random(1)
    holes = [(rng.uniform(0, 100), rng.uniform(0, 80), 0.8) for _ in range(200)]

    def travel(hs):
        p, t = (0.0, 0.0), 0.0
        for h in hs:
            t += math.dist(p, h[:2])
            p = h[:2]
        return t

    ordered = order_holes(holes)
    assert sorted(ordered) == sorted(holes)          # same holes, new order
    assert travel(ordered) < travel(holes) / 3


def test_drill_paths_follow_the_short_order():
    from types import SimpleNamespace
    from gerber2rml.engine.drill import drill_holes
    job = SimpleNamespace(total_depth=1.8, cut_depth=0.6, travel_z=2.0,
                          peck_retract=0.3)
    holes = [(0, 0, 0.8), (50, 0, 0.8), (1, 0, 0.8), (51, 0, 0.8)]
    xs = [p[0].x for p in drill_holes(holes, job)]
    assert xs == [0, 1, 50, 51]


def test_drill_ladder_plunges_each_row_at_its_own_feed():
    from gerber2rml.engine.testcard import render_drill_ladder, DRILL_FEEDS
    text, bbox, legend = render_drill_ladder()
    fs = {float(w[1:]) for line in text.splitlines() if line.startswith("G1")
          for w in line.split() if w.startswith("F")}
    assert {f * 60 for f in DRILL_FEEDS} <= fs
    assert "Z-1.8" in text
    assert bbox[0] < bbox[2] and bbox[1] < bbox[3]


def test_cutout_ladder_runs_each_row_at_its_own_feed_and_reaches_depth():
    from gerber2rml.engine.testcard import render_cutout_ladder, CUTOUT_FEEDS
    text, bbox, legend = render_cutout_ladder()
    fs = {float(w[1:]) for line in text.splitlines() if line.startswith("G1")
          for w in line.split() if w.startswith("F")}
    assert {f * 60 for f in CUTOUT_FEEDS} <= fs
    zs = [float(w[1:]) for line in text.splitlines() if line.startswith("G1")
          for w in line.split() if w.startswith("Z")]
    assert min(zs) == -2.0
