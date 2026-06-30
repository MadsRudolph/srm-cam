"""Tests for the ramped lead-in (engine/leadin.py)."""
import math
from gerber2rml.toolpath import Move
from gerber2rml.engine.leadin import apply_lead_in

CZ = -0.15            # cut depth (negative Z)


def _square_ring(side=10.0, travel=2.0):
    c = [(0, 0), (side, 0), (side, side), (0, side), (0, 0)]
    tp = [Move(0, 0, travel, rapid=True), Move(0, 0, CZ)]
    tp += [Move(x, y, CZ) for (x, y) in c[1:]]
    tp.append(Move(0, 0, travel, rapid=True))
    return tp


def _cuts(tp):
    return [m for m in tp if not m.rapid]


def test_drill_plunge_is_left_alone():
    # rapid down, plunge straight to depth, retract -- no lateral cut to ramp on.
    drill = [Move(5, 5, 2.0, rapid=True), Move(5, 5, -1.8),
             Move(5, 5, 2.0, rapid=True)]
    assert apply_lead_in([drill])[0] == drill


def test_pecking_plunge_is_left_alone():
    peck = [Move(5, 5, 2.0, rapid=True), Move(5, 5, -0.6), Move(5, 5, -1.2),
            Move(5, 5, -1.8), Move(5, 5, 2.0, rapid=True)]
    assert apply_lead_in([peck])[0] == peck


def test_entry_is_no_longer_a_full_vertical_plunge():
    out = apply_lead_in([_square_ring()], ramp_len=2.0)[0]
    # No move should drop straight to full depth at constant XY (the old plunge).
    prev = None
    for m in out:
        if prev is not None and not m.rapid:
            same_xy = abs(m.x - prev.x) < 1e-9 and abs(m.y - prev.y) < 1e-9
            assert not (same_xy and abs(m.z - CZ) < 1e-9 and prev.z > CZ + 1e-9), \
                "found a vertical plunge straight to full depth"
        prev = m


def test_first_cut_moves_descend_gradually_to_full_depth():
    out = apply_lead_in([_square_ring()], ramp_len=4.0)[0]
    cz_seq = [m.z for m in _cuts(out)]
    # starts shallower than full depth and reaches full depth, monotonic down
    assert cz_seq[0] > CZ + 1e-9
    assert min(cz_seq) <= CZ + 1e-9
    ramp = []
    for z in cz_seq:
        ramp.append(z)
        if z <= CZ + 1e-9:
            break
    assert all(ramp[i] >= ramp[i + 1] - 1e-9 for i in range(len(ramp) - 1))


def test_ring_is_still_fully_cut_at_depth():
    out = apply_lead_in([_square_ring()], ramp_len=2.0)[0]
    assert abs(min(m.z for m in out) - CZ) < 1e-9          # never deeper than cut_z
    # every original corner is cut at full depth somewhere in the path
    at_depth = {(round(m.x, 3), round(m.y, 3)) for m in out
                if not m.rapid and abs(m.z - CZ) < 1e-9}
    for corner in [(0, 0), (10, 0), (10, 10), (0, 10)]:
        assert corner in at_depth


def test_short_ring_shorter_than_ramp_still_valid():
    out = apply_lead_in([_square_ring(side=0.3)], ramp_len=5.0)[0]
    assert abs(min(m.z for m in out) - CZ) < 1e-9          # reaches full depth
    assert out[0].rapid                                     # still starts with a rapid
