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
No origin is set anywhere. The jobs are NC (the mill's command set is NC
Code) and start from two known points: Z at the machine top (``G28``), XY
at the first point through G54, which is machine (0, 0) on this mill - the
run moves there once and reads the head back before it cuts anything.
After that every move is incremental, and Z is machine Z: the probed
copper height plus the path's depth (backends/gcode.render_incremental).
"""
import math
import threading
import time

from gerber2rml.backends.gcode import render_incremental
from gerber2rml.engine import spi_probe, stockfind
from gerber2rml.engine.cutout import SHEET_EDGE_MM
from gerber2rml.engine.fidfind import find_hole_center, hole_test
from gerber2rml.engine.fiducial import (Transform, apply_to_toolpaths,
                                        fit_transform, residuals)
from gerber2rml.engine.leadin import fast_approach
from gerber2rml.engine.leveling import HeightMap, apply_leveling, probe_points
from gerber2rml.engine.runner import JobRunner, RunStopped
from gerber2rml.engine.spi_probe import ProbeError
from gerber2rml.engine.select import clip_toolpaths_to_regions
from gerber2rml.toolpath import Move

FIT_WORST_MM = 0.15          # a fiducial further off than this stops the run
LEVEL_GRID = (4, 3)
HOLE_SEARCH_UM = 2500
FITTED_SEARCH_UM = 1000      # once two holes have given the fit
NUDGES = ((0, 0), (1.5, 0), (0, 1.5), (-1.5, 0), (0, -1.5))
DRY_AIR_MM = 5.0             # a dry run cuts this far above the copper
# The bed towards the operator, the head at the back in the left corner. Low Y
# is the opposite: X 2.1, Y 3.1 took the bed furthest away (seen 2026-11-03).
VIEW_MM = (0.0, 150.0)
START_AT_FIDUCIALS = "find_fiducials"
START_AT_CHECK = "check_before_cutout"  # the traces are cut: straight to the check
HOLES_AGAIN = "holes_again"             # the job the check can ask for
PLACE_MARGIN_MM = 3.0        # a board placed for you: this far in from the edges


def _fmt(v):
    s = ("%.3f" % v).rstrip("0")
    return s if s.endswith(".") else s


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

    def extent(self, side):
        """(x0, y0, x1, y1) everything the run cuts covers on that side, in
        the frame of :meth:`area`: reference holes can be outside the board."""
        return self.area(side)

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

    def check(self, traces_label, deeper_mm):
        """The traces are done and the cut-out is next: block until the
        operator has looked. Returns ``("go", 0)`` to cut it out,
        ``("again", mm)`` to cut the traces again that much deeper still
        (``deeper_mm`` is how much deeper they already went), or
        ``("stop", 0)``. ``("again", mm, boxes)`` re-cuts only inside the
        boxes - ``[(x0, y0, x1, y1)]``, machine mm - which is the usual case:
        a spot or two came out shallow, not the whole board."""
        return ("go", 0.0)


def fills_stock(bw, bh, sw, sh, tol=SHEET_EDGE_MM):
    """True when a ``bw`` x ``bh`` board is the ``sw`` x ``sh`` piece of stock
    itself: each side within ``tol``, the same tolerance the cut-out uses to
    call a board edge "on the sheet's edge" and leave it uncut."""
    return abs(bw - sw) <= tol and abs(bh - sh) <= tol


def about(cx, cy, deg):
    """The rotation by ``deg`` about (cx, cy), as a :class:`Transform`."""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return Transform(a, 1.0, cx - (c * cx - s * cy), cy - (s * cx + c * cy))


# How much further from the bracket the top side is held when it is checked
# before the flip: a sheet turned over and pushed back comes home within a
# few tenths, and this must not be what decides it after one side is cut.
FLIP_SPARE_MM = 1.0


def _moved(geom, t):
    """``geom`` through the similarity ``t`` (a fit's Transform)."""
    from shapely import affinity
    c = math.cos(t.theta) * t.scale
    s_ = math.sin(t.theta) * t.scale
    return affinity.affine_transform(geom, [c, -s_, s_, c, t.tx, t.ty])


def _extent(paths):
    """(x0, y0, x1, y1) of every move in ``paths``, or None."""
    xs = [m.x for tp in paths for m in tp]
    ys = [m.y for tp in paths for m in tp]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


class AutoRun:
    """Run the whole job. Call :meth:`run` on a thread."""

    def __init__(self, ser, printer, source, events, *, click_mm, stock_mm,
                 double, bit_mm=0.8, margin_mm=PLACE_MARGIN_MM, rpm=None,
                 should_abort=None, should_pause=None, dry_run=False,
                 runner_opts=None, level=True, surface_hint=None,
                 datum=None, check_cut=True, start_at=None, keepout=None,
                 arms=None, leave_under=False):
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
        self.surface_hint = surface_hint     # copper Z last time, mm
        # (x, y, corner): the stock sits in a corner bracket - no edge walks
        self.datum = datum
        self.keepout = keepout               # (x0, y0, x1, y1) the bit stays out
        # [(x0, y0, x1, y1)]: the bracket's bars, beside the stock. With the
        # usual margins nothing comes near them; a job set flush to the
        # stock's edge can, so every move is held clear of them as well.
        self.arms = list(arms or [])
        # A board that is not cut out may lie under the tongue. Its isolation
        # there is then left uncut and the bit led round - but only once the
        # passes, milled out of the sheet on paper, are seen to join no nets
        # (engine/bracket.py). Off, a job that reaches there is refused.
        self.leave_under = bool(leave_under)
        # Stop before a cut-out so the traces can be looked at first: once
        # the board is cut free it can no longer be re-cut where it lay.
        self.check_cut = check_cut
        # Skip every job before this one (finishing a board that stopped).
        self.start_at = start_at
        self._skipping = start_at is not None
        self.pose = self.pose_top = None
        self.rotation = None
        self.fit = None
        self.z_surf = None           # machine Z of the copper, mm
        self._frame_ok = False
        self.whole = False           # the board is the whole piece of stock
        self._work = None            # what the bit cuts then, nominal mm

    # -- the sequence --------------------------------------------------------
    def run(self):
        done = self._sequence()
        self._to_view()                 # finished: bring the board out
        return done

    def _sequence(self):
        self._find_stock("stock")
        p = self.pose
        x0, y0, x1, y1 = self.src.extent("bottom")
        self.whole = not self.double and fills_stock(x1 - x0, y1 - y0, p.w, p.h)
        self.src.place(self.pose, 0.0 if self.whole else self.margin)
        self.rotation = about(self.pose.x, self.pose.y, self.pose.angle)
        if self.whole:
            # The board IS the piece of stock: its edge is the stock's edge
            # and is not cut (the cut-out leaves out what lies on the sheet's
            # edge). What has to land on the copper, clear of the bracket, is
            # what the bit cuts, so that is what the gates below look at.
            self.ev.note("The board is the whole piece of stock: its edge is "
                         "left as it is, and only what lies inside it is cut.")
            reach = self._cut_reach(self.src.bottom_steps())
            if reach is None:
                raise RunFailed("the board fills the stock, and there is "
                                "nothing inside it to cut.")
            x0, y0, x1, y1 = self._work = reach
        else:
            x0, y0, x1, y1 = self.src.extent("bottom")
        need = ((0.0, 0.0) if self.whole else
                (x1 - x0 + 2 * self.margin, y1 - y0 + 2 * self.margin))
        if need[0] > p.w or need[1] > p.h:
            raise RunFailed("the job needs %.1f × %.1f mm of stock with its "
                            "margins, and this stock is %.1f × %.1f mm. Use a "
                            "bigger piece." % (need[0], need[1], p.w, p.h))
        if (x0 < p.x - 1e-6 or y0 < p.y - 1e-6 or x1 > p.x + p.w + 1e-6
                or y1 > p.y + p.h + 1e-6):
            raise RunFailed(
                "the job hangs off the stock (it spans X %.1f-%.1f, Y "
                "%.1f-%.1f; the stock X %.1f-%.1f, Y %.1f-%.1f). Drag it "
                "onto the stock outline." % (x0, x1, y0, y1, p.x, p.x + p.w,
                                             p.y, p.y + p.h))
        self._check_keepout("bottom")
        if self.double and self.leave_under:
            # Not by its outline, which is under the tongue by design: by
            # what the top side actually has there, laid where a perfect
            # flip puts it. Now, not with one side already cut.
            self._check_flipped()
        elif self.double:
            # Turned over left to right, the job lands mirrored across the
            # stock. Find out now, not with one side already cut.
            mid = 2 * p.x + p.w
            self._clear_of_keepout(mid - x1, y0, mid - x0, y1,
                                   " once the board is flipped")
        bottom, top = self.src.bottom_steps(), self.src.top_steps()
        from_fiducials = self.start_at == START_AT_FIDUCIALS and top
        at_check = self.start_at == START_AT_CHECK
        if from_fiducials:
            # The sheet is already turned over: everything on the top is to do.
            self._skipping = False
        elif not at_check and self.start_at is not None and self.start_at not in [
                k for k, _l in bottom + top]:
            raise RunFailed("there is no step %r to start from"
                            % self.start_at)
        # Started on a top-side step: the bottom is done and the board is
        # already turned over, so neither is asked for again.
        on_top = (from_fiducials or (at_check and bool(top))
                  or self.start_at in [k for k, _l in top])
        if on_top:
            for key, _l in bottom:
                self._step(key, "skipped")
        else:
            hmap = self._level("level", "bottom", self.rotation)
            self._jobs(bottom, self.rotation, hmap)
        if not self.double:
            return True
        if not on_top:
            self._step("flip", "running")
            self._to_view()
            self.ev.note("Turn the board over, left to right, and put it "
                         "back where it was. Then press Continue.")
            if not self.ev.flip():
                raise RunStopped("stopped at the flip")
            self._wait_for_lid()
            self._step("flip", "done")
        self._find_stock("stock_top", again=True)
        self._fiducials()
        hmap = self._level("level_top", "top", None)
        self._jobs(top, None, hmap)
        return True

    def _jobs(self, steps, t, hmap):
        """Run ``steps`` in order; before a cut-out, let the traces be
        checked - and cut again, deeper, as often as asked."""
        traces = None
        for key, label in steps:
            if self._skipping:
                if not (key == self.start_at or (
                        self.start_at == START_AT_CHECK and "cutout" in key)):
                    self._step(key, "skipped")
                    if "traces" in key:
                        traces = (key, label)
                    continue
                self._skipping = False
            if "cutout" in key and traces is not None and (
                    self.check_cut or self.start_at == START_AT_CHECK):
                deeper = 0.0
                while True:
                    self._to_view()
                    answer = self.ev.check(traces[1], deeper)
                    what, mm = answer[0], answer[1]
                    boxes = answer[2] if len(answer) > 2 else None
                    if what == "stop":
                        raise RunStopped("stopped before the cut-out")
                    self._wait_for_lid()
                    if what == "holes":
                        self.ev.note("Drilling the holes again, %.2f mm deeper…"
                                     % float(mm))
                        self._job(HOLES_AGAIN, "Holes again", t, hmap, float(mm))
                        continue
                    if what != "again":
                        break
                    deeper += float(mm)
                    self.ev.note("%s again%s, %.2f mm deeper…" % (
                        traces[1], " in %d boxes" % len(boxes) if boxes
                        else "", deeper))
                    self._job(traces[0], traces[1], t, hmap, deeper, boxes)
            self._job(key, label, t, hmap)
            if "traces" in key:
                traces = (key, label)

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
            if self.datum is not None:
                # Flipped left to right and pushed back into the same
                # bracket, the stock covers the same rectangle again.
                pose = stockfind.from_datum(
                    self.ser, self.datum[:2], self.datum[2], self.size,
                    should_abort=self.should_abort, note=self.ev.note,
                    hint_mm=self.pose.z if again else self.surface_hint)
            else:
                pose = self._find_by_edges(click, again)
            if again:
                self.pose_top = pose
            else:
                self.pose = pose
            self.ev.stock(pose)
            self.ev.note("Stock found: corner %.2f, %.2f mm, turned %+.2f°."
                         % (pose.x, pose.y, pose.angle))
            return pose
        return self._guard(key, go)

    def _find_by_edges(self, click, again):
        return stockfind.find_stock(self.ser, click, self.size,
                                    holes=again,
                                    hint_mm=(self.pose.z if again else
                                             self.surface_hint),
                                    bit_mm=self.bit,
                                    should_abort=self.should_abort,
                                    note=self.ev.note)

    def _to_view(self):
        """Bring the board out to look at it, as a short NC job. The SPI View
        command acked straight after a job and did not move (2026-11-03); NC is
        what the mill is taking at that moment. The stock has not moved, so the
        jobs that follow land where they should, and if the mill will not go
        the check is still worth having."""
        self.ev.note("Bringing the board to the view position…")
        x, y = VIEW_MM
        prog = ("%%\nO0001\n(view position)\nG21\nG91\nG28 Z0.\nG90\nG54\n"
                "G0 X%s Y%s\nM30\n%%\n" % (_fmt(x), _fmt(y)))
        try:
            JobRunner(self.ser, self.printer, self.should_abort,
                      self.should_pause, self.ev.note,
                      **self.runner_opts).run(prog, "view position",
                                              end_mm=VIEW_MM, timeout_s=120)
        except RunStopped as e:
            if self.should_abort():
                raise
            self.ev.note("The mill did not go to the view position: %s." % e)

    def _wait_for_lid(self):
        """Looking at the board means opening the lid, and a job started with
        it open stops at once."""
        said = False
        while (spi_probe.machine_status(self.ser) or {}).get("cover"):
            if not said:
                self.ev.note("Close the lid to carry on.")
                said = True
            if self.should_abort():
                raise RunStopped("stopped")
            time.sleep(0.2)

    def _near_keepout(self, x0, y0, x1, y1):
        kx0, ky0, kx1, ky1 = self.keepout
        b = self.bit
        return x0 - b < kx1 and x1 + b > kx0 and y0 - b < ky1 and y1 + b > ky0

    def _check_keepout(self, side):
        """The job clear of the bracket's probe tongue.

        Its whole extent first, as it always was. A board that reaches under
        the tongue fails that - but if no MOVE of any of its jobs goes there,
        nothing is in the way: then every path is looked at instead, and the
        run goes ahead only when all of them stay out."""
        if self.keepout is None:
            return
        # A whole-stock board reaches the tongue by its outline, by design:
        # what counts for it is what the bit cuts.
        ext = (self._work if self.whole and side == "bottom"
               else self.src.extent(side))
        if not self._near_keepout(*ext) and not self.leave_under:
            return
        steps = (self.src.bottom_steps() if side == "bottom"
                 else self.src.top_steps())
        left = 0.0
        for key, label in steps:
            whole = self.src.toolpaths(key)[0]
            paths, uncut = self._leave_out(key, whole)
            if uncut > 0:
                copper, nets = self.src.copper_nets(side)
                self._prove(label, whole, paths, copper, nets, uncut)
                left += uncut
            self._paths_clear(paths, label)
        if left > 0:
            self.ev.note("%.0f mm of isolation lies under the bracket and is "
                         "left uncut. Milled out on paper, it joins no nets."
                         % left)
        elif self._near_keepout(*ext):
            self.ev.note("The board reaches under the bracket's tongue; no "
                         "cut or move of the %s side goes there." % side)

    def _tongue_grow(self):
        """How far the tool's CENTRE stays from the keepout: its radius and
        a hair. The keepout already holds the tongue's own clearance, and the
        extent check allows the same - a board a bit's width away, with the
        cut-out pass running in that width."""
        return self.bit / 2.0 + 0.05

    def _prove(self, label, whole, paths, copper, nets, uncut, when=""):
        """Raise if leaving ``uncut`` mm of ``whole`` out (giving ``paths``)
        would put two nets on one piece of copper.

        Only what leaving it out joins: nets the whole pass leaves on one
        piece as well are the design's own shorts, found and said by the
        checks, not something done here."""
        from gerber2rml.engine.bracket import joined_nets
        sheet, r = self._stock_rect(), self.bit / 2.0
        before = [set(j) for j in joined_nets(copper, nets, whole, sheet, r)]
        joined = [j for j in joined_nets(copper, nets, paths, sheet, r)
                  if not any(set(j) <= b for b in before)]
        if joined:
            raise RunFailed(
                "%.0f mm of %s lies under the bracket%s and cannot be cut, "
                "and without it these would be one piece of copper: %s. "
                "Move the board away from the bracket, or move those "
                "tracks." % (uncut, label.lower(), when,
                             "; ".join(" + ".join(j) for j in joined)))

    # -- the other side, before it is turned over ----------------------------
    def _expected_flip(self):
        """``(transform, expected)``: where a perfect flip, pushed back into
        the bracket, puts the top side - the layout's top frame to machine
        mm - and where each reference hole lands. The bracket holds the
        sheet square, so the board comes back mirrored across the stock."""
        bottom, top = self.src.fiducials()
        p = self.pose
        expected = [(2 * p.x + p.w - bx, by) for bx, by in bottom]
        if len(top) < 2 or len(top) != len(expected):
            return None, expected
        return fit_transform(top, expected, allow_scale=False), expected

    def _hole_blocked(self, x, y, spare=0.0):
        """Would finding a reference hole at (x, y) take the bit under the
        bracket? The hole itself, the touches beside it that take the
        surface, and the search round it all have to be clear."""
        reach = max(2.5, HOLE_SEARCH_UM / 1000.0)
        for rect, grow in self._zones():
            g = grow + spare + reach
            if (rect[0] - g < x < rect[2] + g
                    and rect[1] - g < y < rect[3] + g):
                return True
        return False

    def _check_flipped(self):
        """The top side, laid where a perfect flip puts it, against the
        bracket: enough reference holes still reachable, and every job clear
        once its isolation under the tongue is left out. The real flip is
        measured later and checked again (:meth:`_check_keepout`); this is
        held ``FLIP_SPARE_MM`` further off, for how far a sheet comes back
        from where it was."""
        from gerber2rml.engine.bracket import avoid, path_hit
        t0, expected = self._expected_flip()
        need = min(3, len(expected))
        reach = [i for i, (x, y) in enumerate(expected)
                 if not self._hole_blocked(x, y, FLIP_SPARE_MM)]
        if len(reach) < need:
            raise RunFailed(
                "once the board is flipped only %d of its %d reference holes "
                "can be reached - the others land under the bracket - and it "
                "takes %d to trust the fit. Move a hole, or the board."
                % (len(reach), len(expected), need))
        if len(reach) < len(expected):
            self.ev.note("%d reference hole(s) land under the bracket once "
                         "the board is flipped and will not be used; %d "
                         "are enough." % (len(expected) - len(reach),
                                          len(reach)))
        if t0 is None:
            return
        zones = [(r, g + FLIP_SPARE_MM) for r, g in self._zones()]
        left = 0.0
        for key, label in self.src.top_steps():
            whole = apply_to_toolpaths(self.src.nominal_top(key), t0)
            paths = whole
            if "traces" in key:
                paths, uncut = avoid(whole, zones, self._stock_rect())
                if uncut > 0:
                    copper, nets = self.src.copper_nets("top", fitted=False)
                    self._prove(label, whole, paths, _moved(copper, t0), nets,
                                uncut, " once the board is flipped")
                    left += uncut
            for rect, grow in zones:
                hit = path_hit(paths, rect, grow)
                if hit:
                    raise RunFailed(
                        "%s, once the board is flipped, would take the bit "
                        "under the bracket (at X %.1f, Y %.1f). Move the "
                        "board away from the bracket, or take what is there "
                        "off the board." % (label, hit[0], hit[1]))
        if left > 0:
            self.ev.note("Once flipped, %.0f mm of the top's isolation lies "
                         "under the bracket and is left uncut. Milled out on "
                         "paper, it joins no nets." % left)

    def _zones(self):
        """The bracket, as what the tool's centre must stay out of."""
        zones = []
        if self.keepout is not None:
            zones.append((self.keepout, self._tongue_grow()))
        zones += [(arm, self.bit / 2.0 + 0.1) for arm in self.arms]
        return zones

    def _stock_rect(self):
        p = self.pose
        return (p.x, p.y, p.x + p.w, p.y + p.h)

    def _leave_out(self, key, paths):
        """An isolation pass with what is under the bracket taken out and
        the bit led round. ``(paths, uncut_mm)``; any other job, or with
        ``leave_under`` off, is returned as it is."""
        if not self.leave_under or "traces" not in key:
            return paths, 0.0
        from gerber2rml.engine.bracket import avoid
        return avoid(paths, self._zones(), self._stock_rect())

    def _paths_clear(self, paths, label):
        """Raise unless every move of ``paths`` stays out from over the
        tongue and off the bracket's bars."""
        from gerber2rml.engine.bracket import path_hit
        if self.keepout is not None:
            hit = path_hit(paths, self.keepout, self._tongue_grow())
            if hit:
                raise RunFailed(
                    "%s would take the bit under the bracket's probe tongue "
                    "(at X %.1f, Y %.1f) and it would hit it. Move the board "
                    "away from the bracket, or take what is there off the "
                    "board." % (label, hit[0], hit[1]))
        for arm in self.arms:
            # Its edge is the stock's edge: the cutter's own radius, and a
            # little, has to stay on the stock.
            hit = path_hit(paths, arm, self.bit / 2.0 + 0.1)
            if hit:
                raise RunFailed(
                    "%s would run off the stock into the bracket (at X %.1f, "
                    "Y %.1f). Move the board away from the bracket."
                    % (label, hit[0], hit[1]))

    def _cut_reach(self, steps):
        """``(x0, y0, x1, y1)`` the bit's edge reaches while cutting in
        ``steps`` (moves below the surface), or None when nothing cuts."""
        xs, ys = [], []
        for key, _label in steps:
            paths = self.src.toolpaths(key)[0]
            for tp in paths:
                for m in tp:
                    if not m.rapid and m.z < 0:
                        xs.append(m.x)
                        ys.append(m.y)
        if not xs:
            return None
        r = self.bit / 2.0
        return min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r

    def _clear_of_keepout(self, x0, y0, x1, y1, when=""):
        if self.keepout is None:
            return
        kx0, ky0, kx1, ky1 = self.keepout
        b = self.bit
        if x0 - b < kx1 and x1 + b > kx0 and y0 - b < ky1 and y1 + b > ky0:
            raise RunFailed(
                "the job runs under the bracket's probe tongue%s (X %.1f-%.1f, "
                "Y %.1f-%.1f) and the bit would hit it. Move the board, or use "
                "a bigger piece." % (when, kx0, kx1, ky0, ky1))

    # -- the surface -----------------------------------------------------------
    def _level(self, key, side, t):
        if not self.do_level:
            return self._guard(key, lambda: self._flat(side))

        def go():
            # A whole-stock board is probed over what is cut, not out at the
            # stock's edge, where the bracket's tongue lies over the copper.
            x0, y0, x1, y1 = (self._work if self.whole and side == "bottom"
                              else self.src.area(side))
            if self.keepout is not None and t is None:
                # No touch under the tongue: the probe would come down on
                # plastic, find no copper, and keep going.
                from gerber2rml.engine.bracket import level_area_clear
                x0, y0, x1, y1 = level_area_clear(
                    (x0, y0, x1, y1), self.keepout, self.bit + 1.5, 2.0)
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
            self.z_surf = z0 / 1000.0
            self.ev.note("Surface probed: %.2f mm from flat." % spread)
            self.ev.level(side, rows, nx, ny)
            return HeightMap.from_points(rows, nx, ny)
        return self._guard(key, go)

    def _flat(self, side):
        """No levelling: Z zero on the copper the stock finder touched."""
        pose = self.pose_top if side == "top" else self.pose
        self.z_surf = pose.z
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
            measured = []           # one per hole; None for one not found
            off_x = off_y = 0.0     # how far the holes found so far were off
            for i, (bx, by) in enumerate(bottom):
                mx, my = self.rotation.apply(bx, by)
                dx, dy = mx - p1.x, my - p1.y
                u = dx * math.cos(a1) + dy * math.sin(a1)
                v = -dx * math.sin(a1) + dy * math.cos(a1)
                px, py = p2.to_machine(p2.w - u, v)    # turned over left-right
                self.ev.note("Finding fiducial %d of %d…" % (i + 1, len(bottom)))
                # The sheet came back off by about the same everywhere, so the
                # last hole says where to look for this one. From two holes on
                # the fit says, turn included, and a short search is enough.
                got = [(tp, mp) for tp, mp in zip(top, measured) if mp]
                if len(got) >= 2:
                    guess = fit_transform([g[0] for g in got],
                                          [g[1] for g in got],
                                          allow_scale=False).apply(*top[i])
                    radius = FITTED_SEARCH_UM
                else:
                    guess = (px + off_x, py + off_y)
                    radius = HOLE_SEARCH_UM
                if self._zones() and self._hole_blocked(guess[0], guess[1]):
                    # Under the bracket this side up: the probe cannot go
                    # there. The others carry the fit.
                    self.ev.note("Fiducial %d is under the bracket now and "
                                 "is not used." % (i + 1))
                    measured.append(None)
                    continue
                try:
                    found = self._locate(guess[0], guess[1], radius)
                except (RunFailed, ProbeError) as e:
                    if self.should_abort():
                        raise
                    # A burr or swarf can close one hole: the others still fit.
                    self.ev.note("Fiducial %d skipped: %s." % (i + 1, e))
                    measured.append(None)
                    continue
                measured.append(found)
                off_x, off_y = found[0] - px, found[1] - py
                self.ev.note("Fiducial %d at X %.2f, Y %.2f: %+.2f, %+.2f from "
                             "where a perfect flip puts it."
                             % (i + 1, found[0], found[1], off_x, off_y))
            got = [(tp, mp) for tp, mp in zip(top, measured) if mp]
            # Two holes fit anything: it takes a third to show one was misread.
            need = min(3, len(bottom))
            if len(got) < need:
                raise RunFailed(
                    "only %d of the %d fiducials were found, and it takes %d "
                    "to trust the fit. Check those holes are open and the "
                    "sheet is seated. Nothing on the top side was cut."
                    % (len(got), len(bottom), need))
            nominal, seen = [g[0] for g in got], [g[1] for g in got]
            t = fit_transform(nominal, seen, allow_scale=False)
            worst = max(residuals(t, nominal, seen))
            if worst > FIT_WORST_MM:
                raise RunFailed("the fiducials disagree by %.2f mm after the "
                                "flip - a hole was misread or the board moved. "
                                "Nothing on the top side was cut." % worst)
            self.fit = t
            self.src.set_top_fit(t)
            self._check_keepout("top")
            self.ev.fit(top, measured, t)
            self.ev.note("Fiducials fit to within %.3f mm, %d of %d found, the "
                         "sheet turned %+.2f°."
                         % (worst, len(got), len(bottom),
                            math.degrees(t.theta)))
            return t
        return self._guard("fiducials", go)

    def _locate(self, x_mm, y_mm, search_um=None):
        """The centre of the hole near (x, y), mm."""
        search_um = search_um or HOLE_SEARCH_UM
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
        # The bit drops in only near the middle, and a milled hole comes out a
        # little under size: rings closer than the nominal clearance, not gaps.
        step = max(200, int(self.src.fiducial_clearance_um() * 0.75))
        start = None
        for ring in range(0, search_um // step + 1):
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
                            % (search_um / 1000, x_mm, y_mm))
        return find_hole_center(self.ser, start[0] / 1000.0, start[1] / 1000.0,
                                should_abort=self.should_abort)

    # -- jobs ----------------------------------------------------------------
    def _check_frame(self, x, y):
        """Move to (x, y) through G54 with Z at the top, and read the head
        back. Every job's XY rests on G54 being machine (0, 0); if someone
        moved it, this is where the run finds out - before anything cuts."""
        prog = ("%%\nO0001\n(frame check)\nG21\nG91\nG28 Z0.\nG90\nG54\n"
                "G0 X%s Y%s\nM30\n%%\n" % (_fmt(x), _fmt(y)))
        self.ev.note("Checking where the mill's G54 origin is…")
        try:
            JobRunner(self.ser, self.printer, self.should_abort,
                      self.should_pause, self.ev.note,
                      **self.runner_opts).run(prog, "frame check",
                                              end_mm=(x, y), timeout_s=120)
        except RunStopped as e:
            if str(e) != "the job ran past its time limit":
                raise
        pos = spi_probe.query_position(self.ser)
        if pos is None or math.hypot(pos[0] - x, pos[1] - y) > 0.1:
            raise RunFailed(
                "the head went to %s, not %.2f, %.2f. The mill's G54 X/Y "
                "origin is not machine 0, 0 - in VPanel, set G54 X/Y back to "
                "machine 0, 0 (only Z is ever zeroed)." % (
                    "?" if pos is None else "%.2f, %.2f" % pos[:2], x, y))
        self._frame_ok = True

    def _job(self, key, label, t, hmap, deeper=0.0, boxes=None):
        def go():
            paths, xy, plunge = self.src.toolpaths(key)
            if t is not None:
                paths = apply_to_toolpaths(paths, t)
            if boxes:
                # The boxes were drawn on the bed, where the cuts are: clip
                # in that frame, after the turn and before the levelling.
                paths = clip_toolpaths_to_regions(
                    paths, [(b, None) for b in boxes])
                if not paths:
                    self.ev.note("None of the boxes holds any of the %s - "
                                 "nothing re-cut." % label.lower())
                    return True
            if deeper:
                # Only the cutting moves go down; travel stays where it was.
                paths = [[Move(m.x, m.y, m.z - deeper if m.z < 0 else m.z,
                               rapid=m.rapid) for m in tp] for tp in paths]
            paths, _uncut = self._leave_out(key, paths)
            # Where the bit will really go, turned and clipped: the last
            # word on the bracket, before anything is sent.
            if self.keepout is not None or self.arms:
                ext = _extent(paths)
                if ext is not None and (self.arms or self._near_keepout(*ext)):
                    self._paths_clear(paths, label)
            # Rapid down to just above the copper; only the last bit of each
            # plunge is fed. On nominal Z, so before the levelling.
            paths = fast_approach(paths)
            if hmap is not None:
                paths = apply_leveling(paths, hmap)
            # A dry run is the whole job in the air: the spindle off AND
            # every cut lifted clear - a still bit plunged into copper
            # snaps.
            prog, end = render_incremental(
                paths, xy_feed=xy, plunge_feed=plunge,
                z_surface=self.z_surf + (DRY_AIR_MM if self.dry_run else 0.0),
                spindle=not self.dry_run,
                name=label + (" (dry run)" if self.dry_run else ""))
            first = next((m for tp in paths for m in tp), None)
            if first is not None and not self._frame_ok:
                self._check_frame(first.x, first.y)
            self.ev.note("%s…" % label)
            self.ev.job(key, label, prog)
            JobRunner(self.ser, self.printer, self.should_abort,
                      self.should_pause, self.ev.note,
                      **self.runner_opts).run(prog, label, end_mm=end)
            # The head ends high and somewhere; the next probe re-finds it.
            return True
        return self._guard(key, go)
