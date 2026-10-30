"""The whole autonomous run against the simulated machine: a stock turned
on the bed and off the origin, found, cut, flipped, found again, fitted."""
import math

import pytest

from gerber2rml.engine import simmachine as sm
from gerber2rml.engine import spi_probe, stockfind
from gerber2rml.engine.autorun import AutoRun, Events, JobSource, RunFailed
from gerber2rml.engine.fidfind import hole_test
from gerber2rml.engine.fiducial import apply_to_toolpaths
from gerber2rml.toolpath import Move

FAST = {"still_s": 0.0, "poll_s": 0.0}


def ring(x, y, r=0.4, z=-1.9):
    """A plunge and a circle: a hole of 2 * (r + bit radius)."""
    pts = [Move(x + r * math.cos(k / 8 * math.pi),
                y + r * math.sin(k / 8 * math.pi), z) for k in range(17)]
    return [Move(x + r, y, 2, rapid=True)] + pts + [Move(x + r, y, 2, rapid=True)]


class Board(JobSource):
    """A 40 x 30 board: two holes, a trace, an outline, four fiducials."""
    FID = [(2, 2), (38, 2), (38, 28), (2, 28)]

    def __init__(self, double):
        self.double = double
        self.off = (0.0, 0.0)
        self.fit = None

    def _p(self, x, y):
        return x + self.off[0], y + self.off[1]

    def place(self, pose, margin_mm):
        self.off = (pose.x + margin_mm, pose.y + margin_mm)

    def bottom_steps(self):
        steps = [("drill", "Drilling"), ("traces", "Traces")]
        if self.double:
            return [("align", "Fiducials")] + steps
        return steps + [("cutout", "Cut-out")]

    def top_steps(self):
        return [("top_traces", "Top traces"), ("cutout", "Cut-out")] \
            if self.double else []

    def toolpaths(self, key):
        p = self._p
        if key == "align":
            paths = [ring(*p(x, y)) for x, y in self.FID]
        elif key == "drill":
            paths = [ring(*p(15, 15)), ring(*p(25, 15))]
        elif key in ("traces", "top_traces"):
            a, b = p(10, 10), p(30, 10)
            paths = [[Move(*a, 2, rapid=True), Move(*a, -0.1), Move(*b, -0.1),
                      Move(*b, 2, rapid=True)]]
            if key == "top_traces":
                paths = apply_to_toolpaths(paths, self.fit)
        else:
            c = [p(0, 0), p(40, 0), p(40, 30), p(0, 30), p(0, 0)]
            paths = [[Move(*c[0], 2, rapid=True)]
                     + [Move(x, y, -1.9) for x, y in c]
                     + [Move(*c[-1], 2, rapid=True)]]
            if self.double:
                paths = apply_to_toolpaths(paths, self.fit)
        return paths, 4.0, 1.0

    def area(self, side):
        x0, y0 = self._p(0, 0)
        x1, y1 = self._p(40, 30)
        if side == "top" and self.fit:
            xs, ys = zip(*(self.fit.apply(x, y) for x, y in
                           ((x0, y0), (x1, y0), (x1, y1), (x0, y1))))
            return min(xs), min(ys), max(xs), max(ys)
        return x0, y0, x1, y1

    def fiducials(self):
        bottom = [self._p(x, y) for x, y in self.FID]
        cx = self._p(20, 0)[0]
        return bottom, [(2 * cx - x, y) for x, y in bottom]

    def fiducial_clearance_um(self):
        return 400

    def set_top_fit(self, t):
        self.fit = t


class Log(Events):
    def __init__(self):
        self.steps = []

    def step(self, key, state):
        self.steps.append((key, state))


def _run(double, **kw):
    m = sm.machine(speedup=1e6, corner=(41300, 27800), angle_deg=1.2,
                   size=(100000, 80000))
    ser = spi_probe.open_link("SIM")
    board, log = Board(double), Log()
    run = AutoRun(ser, sm.printer(), board, log, click_mm=(90, 70),
                  stock_mm=(100, 80), double=double, runner_opts=FAST, **kw)
    return m, ser, board, log, run


def test_a_single_sided_board_runs_start_to_finish():
    m, ser, board, log, run = _run(False)
    assert run.run() is True
    assert [k for k, s in log.steps if s == "done"] == [
        "stock", "level", "drill", "traces", "cutout"]
    # The hole is where the design put it, turned with the stock.
    x, y = run.rotation.apply(*board._p(15, 15))
    stockfind.reference_at(ser, int((x + 3) * 1000), int(y * 1000),
                           surface_um=int(run.pose.z * 1000))
    assert hole_test(ser, int(x * 1000), int(y * 1000)) is False


def test_a_double_sided_board_is_flipped_found_and_fitted():
    m, ser, board, log, run = _run(True)
    log.flip = lambda: (m.flip(), True)[1]
    assert run.run() is True
    done = [k for k, s in log.steps if s == "done"]
    assert done == ["stock", "level", "align", "drill", "traces", "flip",
                    "stock_top", "fiducials", "level_top", "top_traces",
                    "cutout"]
    # The fit holds the flip: turned by the stock's new angle, mirrored
    # through the board, every fiducial within the gate.
    assert board.fit is not None
    assert abs(math.degrees(board.fit.theta) - run.pose_top.angle) < 0.1


def test_a_board_moved_after_the_flip_is_still_found():
    m, ser, board, log, run = _run(True)
    log.flip = lambda: (m.flip(shift=(2500, -1800), turn_deg=-1.5), True)[1]
    assert run.run() is True


def test_a_flip_that_is_cancelled_stops_the_run():
    from gerber2rml.engine.runner import RunStopped
    m, ser, board, log, run = _run(True)
    log.flip = lambda: False
    with pytest.raises(RunStopped):
        run.run()
    assert ("top_traces", "running") not in log.steps


def test_levelling_can_be_left_out():
    m, ser, board, log, run = _run(False, level=False)
    probed = []
    log.level = lambda *a: probed.append(a)
    assert run.run() is True
    assert not probed
    assert ("level", "done") in log.steps