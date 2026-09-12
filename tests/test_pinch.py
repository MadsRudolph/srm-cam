"""The deliberate-damage isolation override (``TraceJob.cut_pinches``).

The property that matters is not "a path was generated" but "the two pieces of
copper are no longer connected", and on a real board that question is about
the STOCK: isolation milling starts from a solid sheet and only removes what
the cutter sweeps, so two pads are shorted whenever standing copper still
joins them. Every test here models the board that way.
"""
from shapely.geometry import LineString, MultiPolygon, box
from shapely.ops import unary_union

from gerber2rml.config import TraceJob
from gerber2rml.engine import pinch
from gerber2rml.engine.drc import isolation_pairs
from gerber2rml.engine.traces import isolate

BIT = 0.8


def _swept(paths, r):
    """The metal a toolpath list removes."""
    areas = []
    for tp in paths:
        cut = [(m.x, m.y) for m in tp if not m.rapid]
        if len(cut) == 1:
            cut = cut * 2
        if len(cut) >= 2:
            areas.append(LineString(cut).buffer(r))
    return unary_union(areas) if areas else None


def _joined(copper, job, a, b):
    """Whether standing copper still connects ``a`` to ``b`` after the job."""
    swept = _swept(isolate(copper, job), job.effective_diameter() / 2.0)
    board = copper.envelope.buffer(2.0)
    if swept is not None:
        board = board.difference(swept)
    for piece in getattr(board, "geoms", [board]):
        if piece.intersects(a.buffer(-1e-6)) and piece.intersects(b.buffer(-1e-6)):
            return True
    return False


def _two_pads(gap):
    a = box(0.0, 0.0, 1.5, 0.6)
    b = box(0.0, 0.6 + gap, 1.5, 1.2 + gap)
    return MultiPolygon([a, b]), a, b


def test_a_gap_narrower_than_the_bit_stays_shorted_without_the_override():
    copper, a, b = _two_pads(0.45)
    plain = TraceJob(bit_diameter=BIT, offsets=2)
    assert _joined(copper, plain, a, b), (
        "0.45 mm against a 0.8 mm cutter should be the short the checks warn about")


def test_the_override_separates_a_gap_narrower_than_the_bit():
    copper, a, b = _two_pads(0.45)
    job = TraceJob(bit_diameter=BIT, offsets=2, cut_pinches=True)
    assert not _joined(copper, job, a, b)


def test_it_separates_every_gap_from_hairline_up_to_the_cut_width():
    # The cut is centred, so it spans g/2 + r: that reaches the far copper for
    # every gap it is asked about. This is the claim the feature rests on.
    for gap in (0.05, 0.15, 0.3, 0.45, 0.6, 0.75, 0.79):
        copper, a, b = _two_pads(gap)
        job = TraceJob(bit_diameter=BIT, offsets=2, cut_pinches=True)
        assert not _joined(copper, job, a, b), f"gap {gap} still shorted"


def test_the_pass_runs_down_the_middle_so_both_sides_pay_the_same():
    copper, a, b = _two_pads(0.45)
    job = TraceJob(bit_diameter=BIT, offsets=2, cut_pinches=True)
    swept = unary_union([ln.buffer(BIT / 2.0)
                         for ln in pinch.pinch_centrelines(copper, job)])
    kept_a = a.difference(swept).area / a.area
    kept_b = b.difference(swept).area / b.area
    assert abs(kept_a - kept_b) < 0.02, (kept_a, kept_b)
    # 0.175 mm off a 0.6 mm pad is about 29%
    assert 0.6 < kept_a < 0.8


def test_a_gap_the_bit_fits_in_needs_no_pinch_pass():
    copper, _a, _b = _two_pads(1.0)      # wider than the 0.8 cutter
    job = TraceJob(bit_diameter=BIT, offsets=2, cut_pinches=True)
    assert pinch.pinch_centrelines(copper, job) == []


def test_the_override_is_off_unless_it_is_asked_for():
    copper, _a, _b = _two_pads(0.45)
    off = TraceJob(bit_diameter=BIT, offsets=2)
    on = TraceJob(bit_diameter=BIT, offsets=2, cut_pinches=True)
    assert TraceJob().cut_pinches is False
    assert len(isolate(copper, on)) > len(isolate(copper, off))


def test_no_island_is_ever_cut_in_two():
    # Trimming a pad is the deal; breaking a net in half is not.
    copper, _a, _b = _two_pads(0.45)
    job = TraceJob(bit_diameter=BIT, offsets=2, cut_pinches=True)
    swept = unary_union([ln.buffer(BIT / 2.0)
                         for ln in pinch.pinch_centrelines(copper, job)])
    for island in pinch._polygons(copper):
        left = island.difference(swept)
        assert len(getattr(left, "geoms", [left])) == 1


def test_a_pad_that_loses_most_of_itself_is_reported():
    # A 0.5 mm finger pinched from both sides: the two passes take nearly all
    # of it, and the operator has to be told before the spindle starts.
    finger = box(0.0, 0.0, 1.5, 0.5)
    below = box(0.0, -0.95, 1.5, -0.45)     # 0.45 mm under
    above = box(0.0, 0.95, 1.5, 1.45)       # 0.45 mm over
    copper = MultiPolygon([below, finger, above])
    job = TraceJob(bit_diameter=BIT, offsets=2, cut_pinches=True)
    losses = pinch.pinch_losses(copper, job)
    assert losses, "the finger should be flagged as eaten"
    assert losses[0]["lost"] > 0.5
    assert round(losses[0]["y"], 2) == 0.25      # the finger, not its neighbours


def test_a_modest_trim_is_not_reported_as_a_loss():
    copper, _a, _b = _two_pads(0.45)         # ~29% off each pad
    job = TraceJob(bit_diameter=BIT, offsets=2, cut_pinches=True)
    assert pinch.pinch_losses(copper, job) == []


def test_two_separate_pinches_between_one_pair_are_two_cuts():
    # Joining them would run the cutter straight across whatever lies between.
    a = box(0.0, 0.0, 12.0, 0.6)
    b = MultiPolygon([box(0.0, 1.05, 2.0, 1.65), box(10.0, 1.05, 12.0, 1.65)])
    copper = unary_union([a, b])
    job = TraceJob(bit_diameter=BIT, offsets=2, cut_pinches=True)
    lines = pinch.pinch_centrelines(copper, job)
    assert len(lines) >= 2
    for ln in lines:
        assert ln.length < 6.0, "a cut spanning both pinches would cross the middle"


def test_the_mosfet_board_comes_out_with_no_shorts_at_all():
    """End to end on a real board: 13 gaps a 0.8 mm cutter cannot enter.

    This is the whole point of the option, so it is checked on real Gerbers
    and not just on boxes - pours that run alongside each other, pads that
    pinch at a single point, and channels that bend.
    """
    from gerber2rml.app.panel import read_board
    copper = read_board("tests/fixtures/mosfet_test").board().copper
    pairs = isolation_pairs(copper, BIT)
    assert len(pairs) >= 10, "fixture should still have plenty of tight gaps"

    plain = TraceJob(bit_diameter=BIT, offsets=2)
    on = TraceJob(bit_diameter=BIT, offsets=2, cut_pinches=True)
    assert sum(_joined(copper, plain, a, b) for a, b, _g in pairs) > 0
    assert sum(_joined(copper, on, a, b) for a, b, _g in pairs) == 0

    # ...and it gets there without cutting any net in half.
    swept = unary_union([ln.buffer(BIT / 2.0)
                         for ln in pinch.pinch_centrelines(copper, on)])
    for island in pinch._polygons(copper):
        left = island.difference(swept)
        assert len(getattr(left, "geoms", [left])) == 1
        assert left.area > 0.5 * island.area, "a pad lost more than half"


def test_a_straight_gap_is_cut_in_one_straight_motion():
    # The tool has no business chattering down a straight channel: sampling
    # the outline every 0.05 mm is how the line is FOUND, not how it should
    # be cut.
    copper, _a, _b = _two_pads(0.45)
    job = TraceJob(bit_diameter=BIT, offsets=2, cut_pinches=True)
    lines = pinch.pinch_centrelines(copper, job)
    assert len(lines) == 1
    assert len(lines[0].coords) == 2, list(lines[0].coords)


def test_the_passes_on_a_real_board_are_not_jagged():
    import math
    from gerber2rml.app.panel import read_board
    copper = read_board("tests/fixtures/mosfet_test").board().copper
    job = TraceJob(bit_diameter=BIT, offsets=2, cut_pinches=True)
    lines = pinch.pinch_centrelines(copper, job)
    points = sum(len(ln.coords) for ln in lines)
    assert points / len(lines) < 8, f"{points / len(lines):.1f} points per pass"
    for ln in lines:
        cs = list(ln.coords)
        for i in range(1, len(cs) - 1):
            one = math.atan2(cs[i][1] - cs[i - 1][1], cs[i][0] - cs[i - 1][0])
            two = math.atan2(cs[i + 1][1] - cs[i][1], cs[i + 1][0] - cs[i][0])
            turn = abs(math.degrees(math.atan2(math.sin(two - one),
                                               math.cos(two - one))))
            assert turn < 90, f"the cut doubles back on itself ({turn:.0f} deg)"
