"""Calibrate: the whole set-up of a traces job on the laser, as one button.

A student puts the drilled sheet on the bed and presses Calibrate; when the
report says it is good, they press Cut. In between, nothing to drag, nothing
to choose (2026-11-19). The steps are the page's own, run one after the other
exactly as a person would press them:

1. **Find the board.** A photo, and the board's drilled holes looked for over
   the whole bed in all four quarter turns (:func:`find_board`), the job put
   on them. A board without holes keeps where it was put by hand.
2. **Autofocus** at the cross: the job's middle, kept off holes and the
   cut-out (``StencilLaserDialog.focus_point``).
3. **Calibrate and lock onto the holes**: the proof marks correct the camera,
   then the holes in the same photo put the job exactly on them.
4. **The report**: every step with its numbers and a verdict. Cut stays the
   person's to press.

A step that fails stops the run there and says which and why; nothing is cut
by Calibrate.
"""
from PySide6.QtCore import QTimer

from gerber2rml.engine import xtool
from gerber2rml.gui2 import laser_focus_ui as _lfu

# Where a board can be found from: the job's middle at the bed's, and holes
# looked for this far either way - the whole of the 220 mm field.
BED_MIDDLE = (110.0, 110.0)
WIDE_SEARCH_MM = 105.0
WIDE_PX_PER_MM = 4            # coarse is enough: the lock refines it
WIDE_MAX_TURN = 4.0

# What the report calls satisfactory.
HOLES_SHARE_OK = 0.9          # of the holes found on the lock
CAMERA_SHIFT_WARN_MM = 1.5    # a correction this big is worth a look
FOCUS_SPREAD_WARN_MM = 1.0    # a sheet this far out of flat: re-seat it


CLEAR_NEED = 0.75             # of more than four clear holes


def _opaque(page):
    """A mask that hides the pads: only the ticked holes show."""
    fn = getattr(page, "_opaque", None)
    return bool(fn()) if callable(fn) else False


def _holes(page, art=None, origin=None):
    """The holes to find the board by: all of them, or under a mask that
    hides the pads only those ticked as clear."""
    if _opaque(page):
        return page._features(art or page.art, origin or page.origin())
    return page._hole_paths(art, origin)


def find_board(page):
    """Photo, then the board's holes anywhere on the bed; the job is put on
    them. Sets ``page._autocal_found``."""
    from gerber2rml.engine import xtool_camera as cam
    page._autocal_found = None
    if len(page.base_art.drills or page.base_art.features or []) < 2:
        page._autocal_found = "no holes"
        return page.take_photo()
    candidates = []
    for k in range(4):
        art = xtool.rotated(page.base_art, page.turns + k, page.fine)
        w, h = art.size
        origin = (BED_MIDDLE[0] - w / 2.0, BED_MIDDLE[1] - h / 2.0)
        candidates.append((k, art, origin, _holes(page, art, origin)))
    hi = WIDE_PX_PER_MM
    opaque = _opaque(page)
    if opaque and not 2 <= len(candidates[0][3]) <= page.MAX_RING_HOLES:
        page._autocal_found = False
        return page._say(f"Tick 2 to {page.MAX_RING_HOLES} holes the mask "
                         "leaves clear, under Automatic alignment references.",
                         warn=True)
    # A few clear holes: every one must be found, and they may read either
    # way against a black mask. Mounting holes look the same turned half
    # round, so the way the drawing is turned now wins a tie.
    need = ((1.0 if len(candidates[0][3]) <= 4 else CLEAR_NEED) if opaque
            else cam.DRILLED_NEED)
    ways = ("dark", "bright") if opaque else ("dark",)

    def work(_p):
        rgb = page._photo(hi)
        tried = []
        for way in ways:
            for k, _art, _o, holes in candidates:
                a = cam.align(rgb, hi, holes, search_mm=WIDE_SEARCH_MM,
                              max_turn=WIDE_MAX_TURN, need=need, polarity=way)
                tried.append((k, holes, a))
        good = [t for t in tried if t[2].ok]
        pick = max(good or tried, key=lambda t: (
            t[2].found / max(t[2].total, 1), opaque and t[0] == 0, t[2].score))
        return page._photo(), pick, bool(good)

    def done(res):
        rgb, (k, holes, a), good = res
        page.show_bed(rgb)
        if not good:
            page._autocal_found = False
            if opaque:
                return (f"The board was not found on its mounting holes: at best "
                        f"{a.found} of {a.total} matched. Do they stand out "
                        "from the mask in the photo? Drag the drawing onto "
                        "the board, then press Line up at the holes now.")
            return (f"The board was not found on the bed: at best {a.found} of "
                    f"{a.total} holes matched. Check it lies under the camera, "
                    "drilled face up, or drag the drawing onto it and press "
                    "Calibrate again.")
        target = page._middle(holes) + (a.dx, a.dy)
        page._turn_to(page.turns + k, page.fine + a.turn,
                      preserve_selection=True)
        now = _holes(page)
        dx, dy = target - page._middle(now)
        page.x.setValue(round(page.x.value() + dx, 3))
        page.y.setValue(round(page.y.value() + dy, 3))
        page._clear_references()
        turned = (90 * k + a.turn + 180) % 360 - 180
        page._autocal_found = True
        return (f"Board found on {a.found} of {a.total} holes, turned "
                f"{turned:+.1f}°.")
    page._start(work, "Finding the board on the bed…", done)


# A solder mask job's test fire: pads near each corner and the middle, each
# with a drilled hole, sized like an ordinary pad (2026-11-22, the analog synth).
TEST_PAD_MM = (0.9, 3.5)
TEST_CORNER_INSET = 0.12      # of the board's size, in from each corner


def pick_test_pads(page):
    """Indices of up to five of the job's openings to fire as a test: the
    nearest to each corner of the board and to its middle that has a drilled
    hole inside and a pad's size."""
    from shapely.geometry import Polygon
    from gerber2rml.gui2.stencil_laser import _bed_shapes
    art = page.art
    _, h = art.size
    holes = [Polygon(xtool.to_bed(list(p.exterior.coords), page.origin(), h))
             for p in (art.features or [])]
    shapes = _bed_shapes(art, page.origin())
    ok = []
    for k, poly in enumerate(shapes):
        x0, y0, x1, y1 = poly.bounds
        if not TEST_PAD_MM[0] <= max(x1 - x0, y1 - y0) <= TEST_PAD_MM[1]:
            continue
        if any(poly.contains(q.centroid) for q in holes):
            ok.append((k, poly.centroid))
    if not ok:
        return []
    xs = [c.x for _k, c in ok]
    ys = [c.y for _k, c in ok]
    bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
    ix, iy = TEST_CORNER_INSET * (bx1 - bx0), TEST_CORNER_INSET * (by1 - by0)
    aims = [(bx0 + ix, by0 + iy), (bx1 - ix, by0 + iy), (bx0 + ix, by1 - iy),
            (bx1 - ix, by1 - iy), ((bx0 + bx1) / 2, (by0 + by1) / 2)]
    picks = []
    for ax, ay in aims:
        at = dict(ok)
        k = min((k for k in at if k not in picks),
                key=lambda k: (at[k].x - ax) ** 2 + (at[k].y - ay) ** 2,
                default=None)
        if k is not None:
            picks.append(k)
    return picks


def test_fire(page):
    """Open the test pads, measure them against their copper and move the job
    onto it (the page's own test fire, gui2/stencil_laser.py)."""
    page._last_lineup = None
    picks = pick_test_pads(page)
    if len(picks) < 2:
        return page._say("Fewer than two pads with drilled holes to test on: "
                         "select a few by hand and open them.", warn=True)
    page.selected.clear()
    page.selected.update(picks)
    page.line_up.setChecked(True)
    page._paint(estimate=False)
    page._fill()


class AutoCalibration:
    """Runs the steps one after another on the page's worker."""

    def __init__(self, page):
        self.page = page
        if page.kind == "mask":
            # Find the board, focus, burn a few pads and line up on them.
            # Opening the mask stays the person's to press; any pad that
            # needs more is rework. A mask that hides the pads: rings round
            # the holes it leaves clear instead of pads.
            last = (("Rings at the mounting holes", page.line_up_at_clear_holes,
                     self._lined_up) if _opaque(page) else
                    ("Test pads", lambda: test_fire(page), self._lined_up))
            self.steps = [
                ("Find the board", lambda: find_board(page), self._found),
                ("Autofocus", lambda: page.autofocus(), self._ok),
                last,
            ]
            self.results = []
            self.i = -1
            return
        self.steps = [
            ("Find the board", lambda: find_board(page), self._found),
            ("Autofocus", lambda: page.autofocus(), self._ok),
            ("Camera and holes", page.proof, self._proof),
            # Then as the mask: marks beside five holes, each measured
            # against its own hole, the job moved onto them.
            ("Line up at the holes", page.line_up_at_holes, self._lined_up),
        ]
        # No focus map: on stock lying flat, +-0.3 mm from the middle's
        # focus made no difference in the field test (2026-11-19), and the
        # map's points are one more thing to go wrong. Focus map stays a
        # button for a sheet that is not flat.
        self.results = []          # (name, ok, message)
        self.i = -1

    # -- what makes each step a success ------------------------------------
    def _ok(self, msg, warn):
        return not warn

    def _lined_up(self, msg, warn):
        if getattr(self.page, "kind", None) == "traces" and \
                len(self.page.base_art.drills or []) < 2:
            return True                 # a blank: nothing to line up on
        return not warn and getattr(self.page, "_last_lineup", None) is not None

    def _found(self, msg, warn):
        return not warn and self.page._autocal_found in (True, "no holes")

    def _proof(self, msg, warn):
        lp = self.page._last_proof
        if warn or not lp:
            return False
        has_holes = len(self.page.base_art.drills or []) >= 2
        return "holes" in lp if has_holes else True

    # -- the run -------------------------------------------------------------
    def start(self):
        self.page._autocal = self
        self.page._last_proof = None
        self.page._focus_map = None
        self._next()

    def step_done(self, msg, warn):
        name, _start, check = self.steps[self.i]
        ok = bool(check(msg, warn))
        self.results.append((name, ok, msg))
        if not ok:
            return self._finish()
        self._next()

    def _next(self):
        self.i += 1
        if self.i >= len(self.steps):
            return self._finish()
        _name, start, _check = self.steps[self.i]
        start()
        if not self.page._worker_running():
            # Refused before it began (nothing loaded, no room...): what it
            # said is the reason.
            self.step_done(self.page.status.text(), True)

    def _finish(self):
        page = self.page
        page._autocal = None
        if page.kind == "mask":
            page.selected.clear()           # Open the mask: the whole face
            page._paint(estimate=False)
        report = build_report(page, self.results, len(self.steps))
        page._autocal_report = report
        show_report(page, report)


def build_report(page, results, total):
    """``{"ok", "verdict", "lines", "warnings"}`` from the steps' results and
    what the page now holds."""
    lines = [f"{'✓' if ok else '✗'} {name}: {msg}" for name, ok, msg in results]
    warnings = []
    failed = next((name for name, ok, _m in results if not ok), None)
    lp = page._last_proof or {}
    if "camera" in lp:
        cx, cy = lp["camera"]
        if (cx * cx + cy * cy) ** 0.5 > CAMERA_SHIFT_WARN_MM:
            warnings.append("The camera's correction changed by more than "
                            f"{CAMERA_SHIFT_WARN_MM:g} mm: look at the photo "
                            "closely before cutting.")
    if "holes" in lp:
        found, of = lp["holes"]
        if of and found / of < HOLES_SHARE_OK:
            warnings.append(f"Only {found} of {of} holes were seen on the lock: "
                            "check the pads sit round the holes in the photo.")
    fmap = getattr(page, "_focus_map", None)
    if fmap is not None and fmap.points:
        dz = [p[2] for p in fmap.points]
        if max(dz) - min(dz) > FOCUS_SPREAD_WARN_MM:
            warnings.append(f"The sheet is {max(dz) - min(dz):.2f} mm out of "
                            "flat: press it down or tape it, and Calibrate "
                            "again.")
    if failed:
        verdict = (f"Stopped at {failed}. Nothing was cut. Fix what it says, "
                   "then press Calibrate again.")
    elif len(results) < total:
        verdict = "Stopped before the end. Nothing was cut."
    elif warnings:
        verdict = "Calibrated, with things to check before you press Cut."
    elif getattr(page, "kind", None) == "mask":
        verdict = (("Lined up on the rings round the mounting holes: open two "
                    "pads far apart to check, then press Open the mask."
                    if _opaque(page) else
                    "Lined up on the test pads: look at them, then press Open "
                    "the mask.") + " Rework any pad that needs more.")
    else:
        verdict = "Ready to cut: look at the photo, then press Cut."
    return {"ok": not failed and len(results) == total and not warnings,
            "complete": not failed and len(results) == total,
            "verdict": verdict, "lines": lines, "warnings": warnings}


def show_report(page, report):
    from gerber2rml.gui2 import laserlog
    laserlog.write("calibrate report", **report)
    text = "\n".join([report["verdict"], ""] + report["lines"]
                     + ([""] + ["⚠ " + w for w in report["warnings"]]
                        if report["warnings"] else []))
    page.proof_note.setText(text)
    page.proof_note.setVisible(True)
    page._say(report["verdict"], warn=not report["ok"])


def start(page):
    """Calibrate the job on the page from scratch."""
    if getattr(page, "kind", None) not in ("traces", "mask") \
            or getattr(page, "_empty", True):
        return page._say("Calibrate sets up a traces or solder mask job: load "
                         "a board first.", warn=True)
    if page._worker_running():
        return page._say("The laser is busy.", warn=True)
    AutoCalibration(page).start()


def after_step(page, msg, warn):
    """Called by the page when any step ends: hands it to a running
    calibration, on the next turn of the event loop."""
    ac = getattr(page, "_autocal", None)
    if ac is not None:
        QTimer.singleShot(0, lambda: ac.step_done(msg, warn))
