"""Automatic fiducial center finding against a simulated hole."""
import math
import random

import pytest

from gerber2rml.engine.fidfind import find_hole_center, hole_test
from gerber2rml.engine.spi_probe import ProbeError


class HoleSerial:
    """Fake v2 board: 'H x y' -> copper unless inside a circular hole."""
    def __init__(self, cx_mm, cy_mm, r_mm=1.5):
        self.c = (cx_mm * 1000, cy_mm * 1000)
        self.r = r_mm * 1000
        self._out = []
        self.tests = 0

    def write(self, data):
        s = data.decode().strip()
        if s.startswith("H"):
            _, x, y = s.split()
            self.tests += 1
            inside = math.hypot(int(x) - self.c[0], int(y) - self.c[1]) < self.r
            self._out.append(b"H 0\n" if inside else b"H 1\n")

    def readline(self):
        return self._out.pop(0) if self._out else b""

    def close(self):
        pass


def test_finds_center_within_50um():
    s = HoleSerial(50.437, 40.181)                # true center, off-grid
    cx, cy = find_hole_center(s, 50.0, 40.5)      # start ~0.5 mm off
    assert abs(cx - 50.437) < 0.05
    assert abs(cy - 40.181) < 0.05
    assert s.tests < 80                           # bounded number of touches


def test_any_start_in_any_hole_is_found_in_few_touches():
    rng = random.Random(1)
    counts = []
    for _ in range(200):
        r = rng.uniform(0.6, 1.9)
        cx, cy = rng.uniform(10, 90), rng.uniform(10, 70)
        a, off = rng.uniform(0, 2 * math.pi), rng.uniform(0, 0.85) * r
        s = HoleSerial(cx, cy, r_mm=r)
        fx, fy = find_hole_center(s, cx + off * math.cos(a),
                                  cy + off * math.sin(a))
        assert math.hypot(fx - cx, fy - cy) < 0.05
        counts.append(s.tests)
    counts.sort()
    assert counts[len(counts) // 2] <= 30         # was 39 with three passes


class PartlyConnectedSerial(HoleSerial):
    """A hole whose copper on the probed net is `copper(dist_mm, angle_deg)`
    around the centre - a pour that does not reach all the way round."""
    def __init__(self, cx_mm, cy_mm, copper):
        super().__init__(cx_mm, cy_mm)
        self.copper = copper

    def write(self, data):
        s = data.decode().strip()
        if s.startswith("H"):
            _, x, y = s.split()
            self.tests += 1
            dx, dy = int(x) - self.c[0], int(y) - self.c[1]
            a = math.degrees(math.atan2(dy, dx)) % 360
            on = self.copper(math.hypot(dx, dy) / 1000.0, a)
            self._out.append(b"H 1\n" if on else b"H 0\n")


def _south_gap(a):
    return 240 <= a <= 300              # other nets' traces below the hole


@pytest.mark.parametrize("start", [(0.0, 0.0), (0.5, -0.4), (-0.6, 0.3)])
def test_an_isolated_pad_is_centred_on_the_pour_round_it(start):
    # Mounting pad not on the net: the probe only meets the GND pour beyond
    # its clearance, and below the hole there is no GND at all.
    s = PartlyConnectedSerial(
        30.0, 20.0, lambda d, a: d >= 2.7 and not _south_gap(a))
    fx, fy = find_hole_center(s, 30.0 + start[0], 20.0 + start[1])
    assert math.hypot(fx - 30.0, fy - 20.0) < 0.05


def test_copper_further_out_on_one_side_is_left_out_of_the_fit():
    # The rim is on the net except a broken stretch to the south, where the
    # nearest connected copper is a millimetre further out.
    s = PartlyConnectedSerial(
        30.0, 20.0, lambda d, a: d >= (2.6 if _south_gap(a) else 1.5))
    fx, fy = find_hole_center(s, 30.2, 19.8)
    assert math.hypot(fx - 30.0, fy - 20.0) < 0.05


def test_copper_on_one_side_only_refuses():
    s = PartlyConnectedSerial(30.0, 20.0, lambda d, a: d >= 1.5 and a < 100)
    with pytest.raises(ProbeError):
        find_hole_center(s, 30.0, 20.0)


def test_start_on_copper_refuses():
    s = HoleSerial(50.0, 40.0, r_mm=1.5)
    with pytest.raises(ProbeError):
        find_hole_center(s, 55.0, 40.0)           # 5 mm off: on copper


def test_hole_test_parses_and_errors():
    s = HoleSerial(10.0, 10.0)
    assert hole_test(s, 10000, 10000) is False    # in the hole
    assert hole_test(s, 20000, 10000) is True     # on copper

    class Dead:
        def write(self, data): pass
        def readline(self): return b""

    with pytest.raises(ProbeError):
        hole_test(Dead(), 0, 0, timeout=0.05)
