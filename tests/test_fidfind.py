"""Automatic fiducial center finding against a simulated hole."""
import math

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
