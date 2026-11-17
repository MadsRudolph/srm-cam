"""A board bigger than its stock one way (the synth's brain: 101.6 mm on
100 mm copper). The sheet's edges are its edges that way: they are not cut,
and the strip that hangs off goes where it cuts no copper in two."""
import pytest
from shapely.geometry import box

from gerber2rml.config import CutoutJob
from gerber2rml.engine import simmachine as sm
from gerber2rml.engine import spi_probe
from gerber2rml.engine.autorun import (AutoRun, RunFailed, spans_stock,
                                       strip_damage)
from gerber2rml.engine.cutout import cut_outline
from tests.test_autorun import FAST, Board, Log, ring

W, H = 60.0, 81.6           # on 100 x 80 stock: 1.6 mm longer than it


def test_spans_stock_per_axis():
    assert spans_stock(60, 81.6, 100, 80) == (False, True)
    assert spans_stock(100.2, 50, 100, 80) == (True, False)
    assert spans_stock(60, 70, 100, 80) == (False, False)


def test_a_strip_of_pour_edge_costs_nothing_and_a_pad_in_it_does():
    pour = box(0.5, 0.5, 59.5, 81.1)
    strip = box(-1, -1, 61, 1.6)
    assert strip_damage([pour], strip) == 0
    # A pad in the top strip, in its own clearance in the pour.
    pad = box(20, 80.4, 22, 81.4)
    copper = pour.difference(box(19.5, 79.9, 22.5, 82)).union(pad)
    assert strip_damage([copper], box(-1, 80.0, 61, 83)) == 1


def test_the_cut_out_cuts_only_the_sides_on_the_stock():
    stock = (0.0, 0.0, 100.0, 80.0)
    outline = box(20.0, 80.0 - H, 20.0 + W, 80.0)       # back edge flush
    paths = cut_outline(outline, CutoutJob(tabs=0), stock=stock)
    cut = [m for tp in paths for m in tp if m.z < 0]
    assert cut
    r = CutoutJob().bit_diameter / 2.0
    # Nothing below the surface off the copper, nothing along front or back.
    assert all(0.0 <= m.y <= 80.0 for m in cut)
    assert {round(m.x, 3) for m in cut} == {round(20.0 - r, 3),
                                            round(20.0 + W + r, 3)}


class Spanning(Board):
    """A 60 x 81.6 board: a pour to 0.5 mm of its edge, holes inside, and
    the cut-out down its left and right sides. ``pad_at`` puts a pad in the
    1.6 mm strip at the front ("min") or back ("max")."""

    def __init__(self, pad_at=()):
        super().__init__(False)
        self.pad_at = pad_at
        self.flush = None

    def place(self, pose, margin_mm, flush=None):
        self.flush = flush
        fx, fy = flush or (None, None)
        ox = margin_mm if fx is None else 0.0
        oy = (margin_mm if fy is None else
              0.0 if fy == "min" else pose.h - H)
        self.off = (pose.x + ox, pose.y + oy)

    def bottom_steps(self):
        return [("drill", "Drilling"), ("cutout", "Cut-out")]

    def toolpaths(self, key):
        p = self._p
        if key == "drill":
            return [ring(*p(10, 10)), ring(*p(50, 70))], 4.0, 15.0
        stock = (self.pose.x, self.pose.y, self.pose.x + self.pose.w,
                 self.pose.y + self.pose.h)
        x0, y0 = p(0, 0)
        return cut_outline(box(x0, y0, x0 + W, y0 + H), CutoutJob(tabs=0),
                           stock=stock), 10.0, 5.0

    def area(self, side):
        return (*self._p(0, 0), *self._p(W, H))

    extent = area

    def copper_nets(self, side="bottom", fitted=True):
        if side == "top":
            return None, None
        g = box(*self._p(0.5, 0.5), *self._p(W - 0.5, H - 0.5))
        for at in self.pad_at:
            # A pad in the strip, in its own clearance in the pour.
            y = 0.2 if at == "min" else H - 1.2
            g = g.difference(box(*self._p(19.5, y - 0.5),
                                 *self._p(22.5, y + 1.5)))
            g = g.union(box(*self._p(20, y), *self._p(22, y + 1.0)))
        return g, None


def _run(source):
    sm.machine(speedup=1e6, corner=(41300, 27800), angle_deg=0.0,
               size=(100000, 80000))
    ser = spi_probe.open_link("SIM")
    log = Log()
    run = AutoRun(ser, sm.printer(), source, log, click_mm=(90, 70),
                  stock_mm=(100, 80), double=False, runner_opts=FAST,
                  level=False)
    source.pose = None
    real = run._find_stock

    def find(key):
        real(key)
        source.pose = run.pose
    run._find_stock = find
    return run, log


def test_a_board_longer_than_the_stock_runs_with_the_empty_strip_off_the_front():
    src = Spanning()
    run, log = _run(src)
    assert run.run() is True and run.whole
    assert src.flush == (None, "max")
    assert ("cutout", "done") in log.steps


def test_a_pad_in_the_front_strip_puts_the_board_on_the_front_edge():
    src = Spanning(pad_at=("min",))
    run, log = _run(src)
    assert run.run() is True
    assert src.flush == (None, "min")


def test_copper_in_both_strips_is_refused():
    run, log = _run(Spanning(pad_at=("min", "max")))
    with pytest.raises(RunFailed, match="cut copper in two"):
        run.run()
