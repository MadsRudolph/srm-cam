"""The autonomous run: stock on the bed in, a finished board out.

One thread, one serial port (handed over from the live link the way probe
runs already are), and a printer to send jobs to. What it needs from the
job - toolpaths, where the board sits, the fiducials - comes from a
:class:`JobSource`, so the sequence here is the same against the real
window and against a test's fake board.

Single-sided::

    find the stock -> place the board on it -> probe the surface
    -> set the origin -> drill -> traces -> cut-out

Double-sided::

    find the stock -> place -> probe -> origin -> fiducials -> drill
    -> bottom traces -> [flip] -> find the stock again -> find every
    fiducial -> fit -> probe the top -> origin -> top traces -> cut-out

The flip is the only time it waits for a person. Every other stop is a gate
that failed - the stock is not the typed size, a fiducial will not fit, a
job did not finish - and it says which, and why.

Frames. The window lays the board out on the bed unrotated ("nominal"),
with its corner at the stock's corner plus a margin. The stock is rarely
square to the bed, so the bottom side's paths are turned about the stock
corner by the angle the stock finder measured. The top side's paths are
already in the machine frame: the fiducial fit maps them there directly.
The origin is set to machine XY (0, 0) - so RML coordinates ARE machine
coordinates - and Z on the copper where the height map is zero.
"""
import math
import threading

from gerber2rml.backends.srm20 import render
from gerber2rml.engine import spi_probe, stockfind
from gerber2rml.engine.fidfind import find_hole_center, hole_test
from gerber2rml.engine.fiducial import (Transform, apply_to_toolpaths,
                                        fit_transform, residuals)
from gerber2rml.engine.leveling import HeightMap, apply_leveling, probe_points
from gerber2rml.engine.runner import JobRunner, RunStopped
from gerber2rml.engine.spi_probe import ProbeError

FIT_WORST_MM = 0.15          # a fiducial further off than this stops the run
LEVEL_GRID = (4, 3)
HOLE_SEARCH_UM = 1500
NUDGES = ((0, 0), (1.5, 0), (0, 1.5), (-1.5, 0), (0, -1.5))


class RunFailed(RuntimeError):
    """A gate failed; the message says which and what to do."""


class JobSource:
    """What the run needs from the job. The window implements this."""

    def bottom_steps(self):
        """``[(key, label)]`` before the flip (all of them, single-sided)."""
        raise NotImplementedError

    def top_steps(self):
        """``[(key, label)]`` after the flip; [] single-sided."""
        return []

    def place(self, pose, margin_mm):
        """Put the board on the stock: its corner at the stock corner plus
        ``margin_mm``, unrotated."""
        raise NotImplementedError

    def toolpaths(self, key):
        """``(paths, xy_feed, plunge_feed)`` for one step. Bottom steps are
        nominal; top steps are already fitted into the machine frame."""
        raise NotImplementedError

    def area(self, side):
        """(x0, y0, x1, y1) the board covers on that side, nominal frame
        for "bottom", fitted machine frame for "top"."""
        raise NotImplementedError

    def fiducials(self):
        """``(bottom, top)``: nominal fiducial centres as drilled, and where
        a perfect flip puts them, pair for pair."""
        return [], []

    def fiducial_clearance_um(self):
        return 400

    def set_top_fit(self, t):
        pass


class Events:
    """What the run tells the window. All optional."""

    def note(self, text):
        pass

    def step(self, key, state):
        """``state``: "running", "done" or "failed"."""

    def stock(self, pose):
        pass

    def flip(self):
        """Block until the board has been flipped. False cancels the run."""
        return True

    def level(self, side, rows, nx, ny):
        """A face was probed: ``rows`` = [(x, y, dz)] in machine mm."""

    def fit(self, nominal, measured, t):
        """The fiducials were found and fitted."""

    def job(self, key, label, rml):
        """A job is about to be sent: its program, exactly as sent."""


def about(cx, cy, deg):
    """The rotation by ``deg`` about (cx, cy), as a :class:`Transform`."""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return Transform(a, 1.0, cx - (c * cx - s * cy), cy - (s * cx + c * cy))


class AutoRun:
    """Run the whole job. Call :meth:`run` on a thread."""

    def __init__(self, ser, printer, source, events, *, click_mm, stock_mm,
                 double, bit_mm=0.8, margin_mm=3.0, rpm=None,
                 should_abort=None, should_pause=None, dry_run=False,
                 runner_opts=None, level=True):
        self.ser, self.printer = ser, printer
        self.src, self.ev = source, events
        self.click, self.size = click_mm, stock_mm
        self.double, self.bit = double, bit_mm
        self.margin, self.rpm = margin_mm, rpm
        self.should_abort = should_abort or threading.Event().is_set
        self.should_pause = should_pause
        self.dry_run = dry_run
        self.runner_opts = runner_opts or {}
        self.do_level = level
        self.pose = self.pose_top = None
        self.rotation = None
        self.fit = None

    # -- the sequence --------------------------------------------------------
    def run(self):
        self._find_stock("stock")
        self.src.place(self.pose, self.margin)
        self.rotation = about(self.pose.x, self.pose.y, self.pose.angle)
        x0, y0, x1, y1 = self.src.area("bottom")
        need = (x1 - self.pose.x + self.margin, y1 - self.pose.y + self.margin)
        if need[0] > self.pose.w or need[1] > self.pose.h:
            raise RunFailed("the board needs %.1f × %.1f mm of stock with its "
                            "margins, and this stock is %.1f × %.1f mm. Use a "
                            "bigger piece." % (need[0], need[1],
                                               self.pose.w, self.pose.h))
        hmap = self._level("level", "bottom", self.rotation)
        for key, label in self.src.bottom_steps():
            self._job(key, label, self.rotation, hmap)
        if not self.double:
            return True
        self._step("flip", "running")
        self.ev.note("Turn the board over, left to right, and put it back "
                     "where it was. Then press Continue.")
        if not self.ev.flip():
            raise RunStopped("stopped at the flip")
        self._step("flip", "done")
        self._find_stock("stock_top", again=True)
        self._fiducials()
        hmap = self._level("level_top", "top", None)
        for key, label in self.src.top_steps():
            self._job(key, label, None, hmap)
        return True

    def _step(self, key, state):
        self.ev.step(key, state)

    def _guard(self, key, fn):
        self._step(key, "running")
        try:
            out = fn()
        except Exception:
            self._step(key, "failed")
            raise
        self._step(key, "done")
        return out

    # -- stock ---------------------------------------------------------------
    def _find_stock(self, key, again=False):
        def go():
            click = self.click
            if again:
                # Flipped in place: the middle of the stock is still about
                # where it was, so no click is needed the second time.
                click = self.pose.to_machine(self.pose.w / 2, self.pose.h / 2)
            pose = stockfind.find_stock(self.ser, click, self.size,
                                        bit_mm=self.bit,
                                        should_abort=self.should_abort,
                                        note=self.ev.note)
            if again:
                self.pose_top = pose
            else:
                self.pose = pose
            self.ev.stock(pose)
            self.ev.note("Stock found: corner %.2f, %.2f mm, turned %+.2f°."
                         % (pose.x, pose.y, pose.angle))
            return pose
        return self._guard(key, go)

    # -- the surface -----------------------------------------------------------
    def _level(self, key, side, t):
        if not self.do_level:
            return self._guard(key, lambda: self._flat(side))

        def go():
            x0, y0, x1, y1 = self.src.area(side)
            nx, ny = LEVEL_GRID
            nominal = probe_points((x0, y0, x1, y1), nx, ny, margin=2.0)
            pts = [t.apply(*p) if t else p for p in nominal]
            ref_um = int((self.pose_top or self.pose).z * 1000)
            # A grid point can land on a hole the first side drilled (a
            # fiducial sits 2 mm in from the board corner, exactly where the
            # inset grid starts). Such a point steps aside and tries again.
            first = z0 = None
            for ox, oy in NUDGES:
                fx, fy = pts[0][0] + ox, pts[0][1] + oy
                try:
                    z0 = stockfind.reference_at(
                        self.ser, int(fx * 1000), int(fy * 1000),
                        self.should_abort, ref_um)
                    first = (fx, fy)
                    break
                except ProbeError as e:
                    if str(e) == "stopped":
                        raise
            if first is None:
                raise RunFailed("no copper at the first surface point %.1f, "
                                "%.1f. Is the clip still on?" % pts[0])
            rows = [(pts[0][0], pts[0][1], 0.0)]
            for i, (x, y) in enumerate(pts[1:], 1):
                self.ev.note("Probing the surface, point %d of %d…"
                             % (i + 1, len(pts)))
                for ox, oy in NUDGES:
                    dx = int(round((x + ox - first[0]) * 1000))
                    dy = int(round((y + oy - first[1]) * 1000))
                    r = stockfind._cmd(self.ser, "P %d %d %d" % (i, dx, dy),
                                       self.should_abort)
                    if r and r.startswith("R "):
                        break
                else:
                    raise RunFailed("the surface probe failed at %.1f, %.1f "
                                    "(%s). Is the clip still on?" % (x, y, r))
                # Kept at the grid point: 1.5 mm aside is the same surface,
                # and the bilinear map needs the grid square.
                rows.append((x, y, (int(r.split()[4]) - z0) / 1000.0))
            spread = max(r[2] for r in rows) - min(r[2] for r in rows)
            if spread > 1.0:
                raise RunFailed("the copper is %.2f mm out of flat - more than "
                                "the cut can follow. Re-tape the stock flat."
                                % spread)
            got = spi_probe.set_origin(self.ser, 0, 0, z0)
            if got is None:
                raise RunFailed("the machine did not take the origin - the "
                                "firmware must be v4 (Machine ▸ Flash).")
            self.ev.note("Surface probed: %.2f mm from flat. Origin set."
                         % spread)
            self.ev.level(side, rows, nx, ny)
            return HeightMap.from_points(rows, nx, ny)
        return self._guard(key, go)

    def _flat(self, side):
        """No levelling: Z zero on the copper the stock finder touched."""
        pose = self.pose_top if side == "top" else self.pose
        if spi_probe.set_origin(self.ser, 0, 0, int(pose.z * 1000)) is None:
            raise RunFailed("the machine did not take the origin - the "
                            "firmware must be v4 (Machine ▸ Flash).")
        self.ev.note("Not levelling: Z zero is the copper at the clicked spot.")
        return None

    # -- the fiducials ---------------------------------------------------------
    def _fiducials(self):
        def go():
            bottom, top = self.src.fiducials()
            if len(bottom) < 2:
                raise RunFailed("the job has fewer than two fiducials")
            p1, p2 = self.pose, self.pose_top
            a1 = math.radians(p1.angle)
            measured = []
            for i, (bx, by) in enumerate(bottom):
                mx, my = self.rotation.apply(bx, by)
                dx, dy = mx - p1.x, my - p1.y
                u = dx * math.cos(a1) + dy * math.sin(a1)
                v = -dx * math.sin(a1) + dy * math.cos(a1)
                px, py = p2.to_machine(p2.w - u, v)    # turned over left-right
                self.ev.note("Finding fiducial %d of %d…" % (i + 1, len(bottom)))
                measured.append(self._locate(px, py))
            t = fit_transform(top, measured, allow_scale=False)
            worst = max(residuals(t, top, measured))
            if worst > FIT_WORST_MM:
                raise RunFailed("the fiducials disagree by %.2f mm after the "
                                "flip - a hole was misread or the board moved. "
                                "Nothing on the top side was cut." % worst)
            self.fit = t
            self.src.set_top_fit(t)
            self.ev.fit(top, measured, t)
            self.ev.note("Fiducials fit to within %.3f mm." % worst)
            return t
        return self._guard("fiducials", go)

    def _locate(self, x_mm, y_mm):
        """The centre of the hole near (x, y), mm."""
        x0, y0 = int(x_mm * 1000), int(y_mm * 1000)
        ref = int(self.pose_top.z * 1000)
        for ox, oy in ((2500, 0), (-2500, 0), (0, 2500), (0, -2500)):
            try:
                stockfind.reference_at(self.ser, x0 + ox, y0 + oy,
                                       self.should_abort, ref)
                break
            except ProbeError as e:
                if str(e) == "stopped":
                    raise
        else:
            raise RunFailed("no copper around fiducial at %.1f, %.1f"
                            % (x_mm, y_mm))
        step = max(200, self.src.fiducial_clearance_um())
        start = None
        for ring in range(0, HOLE_SEARCH_UM // step + 1):
            r = ring * step
            n = 1 if r == 0 else max(6, int(round(2 * math.pi * r / step)))
            for k in range(n):
                a = 2 * math.pi * k / n
                x, y = x0 + int(r * math.cos(a)), y0 + int(r * math.sin(a))
                if not hole_test(self.ser, x, y,
                                 should_abort=self.should_abort):
                    start = (x, y)
                    break
            if start:
                break
        if start is None:
            raise RunFailed("fiducial not found within %.1f mm of %.1f, %.1f"
                            % (HOLE_SEARCH_UM / 1000, x_mm, y_mm))
        return find_hole_center(self.ser, start[0] / 1000.0, start[1] / 1000.0,
                                should_abort=self.should_abort)

    # -- jobs ----------------------------------------------------------------
    def _job(self, key, label, t, hmap):
        def go():
            paths, xy, plunge = self.src.toolpaths(key)
            if t is not None:
                paths = apply_to_toolpaths(paths, t)
            if hmap is not None:
                paths = apply_leveling(paths, hmap)
            rml = render(paths, xy_feed=xy, plunge_feed=plunge,
                         spindle=not self.dry_run, rpm=self.rpm)
            self.ev.note("%s…" % label)
            self.ev.job(key, label, rml)
            JobRunner(self.ser, self.printer, self.should_abort,
                      self.should_pause, self.ev.note,
                      **self.runner_opts).run(rml, label)
            # The head ends high and somewhere; the next probe re-finds it.
            return True
        return self._guard(key, go)
