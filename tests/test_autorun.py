"""The whole autonomous run against the simulated machine: a stock turned
on the bed and off the origin, found, cut, flipped, found again, fitted."""
import math

import time

import pytest

from gerber2rml.engine import simmachine as sm
from gerber2rml.engine import spi_probe, stockfind
from gerber2rml.engine.autorun import (HOLES_AGAIN, START_AT_CHECK,
                                       START_AT_FIDUCIALS, AutoRun, Events,
                                       JobSource, RunFailed, about)
from gerber2rml.engine.fidfind import hole_test
from gerber2rml.engine.fiducial import Transform, apply_to_toolpaths
from gerber2rml.engine.runner import RunStopped
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

def test_a_dry_run_keeps_the_bit_in_the_air():
    from tests.test_gcode_incremental import _walk
    m, ser, board, log, run = _run(False, level=False, dry_run=True)
    sent = []
    log.job = lambda key, label, prog: sent.append(prog)
    assert run.run() is True
    assert len(sent) == 3
    for prog in sent:
        assert "M3" not in prog.split()
        lowest = min(p[2] for p in _walk(prog)[0])
        # Cut depths are a fraction of a mm: 5 mm up keeps them in the air.
        assert lowest > run.pose.z + 3.0, (lowest, run.pose.z)


def test_the_traces_are_checked_and_cut_again_deeper_before_the_cut_out():
    from tests.test_gcode_incremental import _walk
    m, ser, board, log, run = _run(False, level=False)
    sent, asked = [], []
    log.job = lambda key, label, prog: sent.append((key, prog))
    answers = iter([("again", 0.05), ("again", 0.05), ("go", 0)])

    def check(label, deeper):
        asked.append(deeper)
        return next(answers)
    log.check = check
    assert run.run() is True
    assert asked == [0.0, 0.05, 0.10]
    keys = [k for k, _p in sent]
    assert keys == ["drill", "traces", "traces", "traces", "cutout"]

    def lowest(p):
        return min(z for _x, _y, z in _walk(p)[0])
    t = [lowest(p) for k, p in sent if k == "traces"]
    assert t[0] - t[1] == pytest.approx(0.05, abs=0.002)
    assert t[0] - t[2] == pytest.approx(0.10, abs=0.002)


def test_stop_at_the_check_leaves_the_board_uncut_free():
    from gerber2rml.engine.runner import RunStopped
    m, ser, board, log, run = _run(False, level=False)
    sent = []
    log.job = lambda key, label, prog: sent.append(key)
    log.check = lambda label, deeper: ("stop", 0)
    with pytest.raises(RunStopped):
        run.run()
    assert "cutout" not in sent


def test_a_run_can_start_at_a_later_step():
    m, ser, board, log, run = _run(False, level=False, start_at="traces")
    sent = []
    log.job = lambda key, label, prog: sent.append(key)
    assert run.run() is True
    assert sent == ["traces", "cutout"]
    assert ("drill", "skipped") in log.steps


def test_a_recut_in_boxes_cuts_only_inside_them():
    from tests.test_gcode_incremental import _walk
    m, ser, board, log, run = _run(False, level=False)
    sent = []
    log.job = lambda key, label, prog: sent.append((key, prog))
    first = []

    def check(label, deeper):
        if first:
            return ("go", 0)
        # A box over the middle of where the traces were just cut.
        cuts = [p for p in _walk(sent[-1][1])[0] if p[2] < run.pose.z]
        x0, x1 = min(p[0] for p in cuts), max(p[0] for p in cuts)
        y0, y1 = min(p[1] for p in cuts), max(p[1] for p in cuts)
        q = (x1 - x0) / 4
        box = (x0 + q, y0 - 1, x1 - q, y1 + 1)       # the middle half
        first.append(box)
        return ("again", 0.05, [box])
    log.check = check
    assert run.run() is True
    assert [k for k, _p in sent] == ["drill", "traces", "traces", "cutout"]
    x0, y0, x1, y1 = first[0]
    full = [p for p in _walk(sent[1][1])[0] if p[2] < run.pose.z]
    redo = [p for p in _walk(sent[2][1])[0] if p[2] < run.pose.z]
    span = lambda pts: max(p[0] for p in pts) - min(p[0] for p in pts)
    assert redo and span(redo) < span(full) - 5
    for x, y, _z in redo:
        assert x0 - 0.01 <= x <= x1 + 0.01 and y0 - 0.01 <= y <= y1 + 0.01
    assert min(p[2] for p in redo) < min(p[2] for p in full) - 0.04


def test_a_finished_board_is_brought_to_the_view_position():
    m, ser, board, log, run = _run(False)
    assert run.run() is True
    assert m.pos == [0, 150000, 0]


def test_a_stopped_run_is_not_moved_to_the_view_position(monkeypatch):
    m, ser, board, log, run = _run(False, check_cut=True)
    seen = []
    monkeypatch.setattr(run, "_to_view", lambda: seen.append(1))
    log.check = lambda label, deeper: ("stop", 0.0)
    with pytest.raises(RunStopped):
        run.run()
    assert len(seen) == 1                   # the check's, and no other


def test_the_run_waits_for_the_lid_before_it_cuts_on(monkeypatch):
    m, ser, board, log, run = _run(False)
    lid = [True, True, False]
    monkeypatch.setattr(spi_probe, "machine_status",
                        lambda s: {"cover": lid.pop(0) if lid else False})
    monkeypatch.setattr(time, "sleep", lambda s: None)
    notes = []
    log.note = notes.append
    run._wait_for_lid()
    assert notes == ["Close the lid to carry on."] and not lid


def test_the_board_is_brought_out_to_be_flipped_and_the_lid_waited_for():
    m, ser, board, log, run = _run(True)
    seen = []

    def flip():
        seen.append(tuple(m.pos))
        m.flip()
        return True
    log.flip = flip
    waits = []
    wait = run._wait_for_lid
    run._wait_for_lid = lambda: (waits.append(1), wait())
    assert run.run() is True
    assert seen == [(0, 150000, 0)]
    assert waits


def test_each_fiducial_is_looked_for_where_the_last_one_says(monkeypatch):
    m, ser, board, log, run = _run(True)
    run.pose = run.pose_top = stockfind.StockPose(30.0, 20.0, 0.0, 100.0, 80.0, -40.0)
    run.rotation = None
    run.rotation = about(30.0, 20.0, 0.0)
    bottom = [(40.0, 30.0), (90.0, 30.0), (90.0, 70.0)]
    board.fiducials = lambda: (bottom, [(90.0, 30.0), (40.0, 30.0), (40.0, 70.0)])
    asked = []

    def locate(x, y, search_um=None):
        asked.append((x, y))
        # Off by 2 mm one way, past the old 1.5 mm search if it were not told.
        return (x + 2.0 - (asked[0][0] - asked[0][0] if len(asked) == 1 else 2.0),
                y - 0.5 + (0.0 if len(asked) == 1 else 0.5))
    monkeypatch.setattr(run, "_locate", locate)
    run._fiducials()
    perfect = [(30.0 + 100.0 - (x - 30.0), y) for x, y in bottom]
    assert asked[0] == pytest.approx(perfect[0])
    assert asked[1] == pytest.approx((perfect[1][0] + 2.0, perfect[1][1] - 0.5))
    assert asked[2] == pytest.approx((perfect[2][0] + 2.0, perfect[2][1] - 0.5))


def test_a_flipped_sheet_can_start_at_the_fiducials(monkeypatch):
    m, ser, board, log, run = _run(True, level=False,
                                   start_at=START_AT_FIDUCIALS)
    sent, found = [], []
    log.job = lambda key, label, prog: sent.append(key)
    log.flip = lambda: pytest.fail("it is already flipped")

    def fiducials():
        found.append(1)
        board.set_top_fit(Transform(theta=0.0, scale=1.0, tx=0.0, ty=0.0))
    monkeypatch.setattr(run, "_fiducials", fiducials)
    assert run.run() is True
    assert found == [1]
    assert sent == [k for k, _l in board.top_steps()]
    assert ("drill", "skipped") in log.steps


def _pose_for_fiducials(run):
    run.pose = run.pose_top = stockfind.StockPose(30.0, 20.0, 0.0, 100.0, 80.0, -40.0)
    run.rotation = about(30.0, 20.0, 0.0)


BOTTOM = [(40.0, 30.0), (90.0, 30.0), (90.0, 70.0), (40.0, 70.0)]
TOP = [(90.0, 30.0), (40.0, 30.0), (40.0, 70.0), (90.0, 70.0)]


def test_one_closed_fiducial_is_skipped_and_the_rest_still_fit(monkeypatch):
    m, ser, board, log, run = _run(True)
    _pose_for_fiducials(run)
    board.fiducials = lambda: (BOTTOM, TOP)
    notes = []
    log.note = notes.append
    tries = []

    def locate(x, y, search_um=None):
        tries.append(search_um)
        if len(tries) == 3:
            raise RunFailed("fiducial not found within 1.0 mm of %.1f, %.1f" % (x, y))
        return x, y
    monkeypatch.setattr(run, "_locate", locate)
    assert run._fiducials() is not None
    assert any("Fiducial 3 skipped" in n for n in notes)
    assert any("3 of 4 found" in n for n in notes)
    assert tries[2] == tries[3] == 1000      # short, once the fit knows where


def test_too_few_fiducials_stop_before_the_top_is_cut(monkeypatch):
    m, ser, board, log, run = _run(True)
    _pose_for_fiducials(run)
    board.fiducials = lambda: (BOTTOM, TOP)
    tries = []

    def locate(x, y, search_um=None):
        tries.append(1)
        if len(tries) > 2:
            raise RunFailed("not found")
        return x, y
    monkeypatch.setattr(run, "_locate", locate)
    with pytest.raises(RunFailed, match="only 2 of the 4"):
        run._fiducials()


def test_starting_at_the_check_cuts_nothing_until_it_is_answered(monkeypatch):
    m, ser, board, log, run = _run(False, level=False, start_at=START_AT_CHECK)
    sent, asked = [], []
    log.job = lambda key, label, prog: sent.append(key)

    def check(label, deeper):
        asked.append((label, list(sent)))
        return ("go", 0.0)
    log.check = check
    assert run.run() is True
    assert asked[0][1] == []                 # nothing cut before the question
    assert sent[-1] == "cutout" and "traces" not in sent


def test_the_check_can_drill_the_holes_again_deeper_and_asks_again(monkeypatch):
    m, ser, board, log, run = _run(False, level=False)
    answers = [("holes", 0.3), ("go", 0.0)]
    log.check = lambda label, deeper: answers.pop(0)
    sent = []
    log.job = lambda key, label, prog: sent.append(key)
    real = board.toolpaths
    monkeypatch.setattr(board, "toolpaths", lambda key: real(
        "drill" if key == HOLES_AGAIN else key))
    assert run.run() is True
    assert not answers
    assert sent[-2:] == [HOLES_AGAIN, "cutout"]

