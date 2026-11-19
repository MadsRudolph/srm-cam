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


def find_board(page):
    """Photo, then the board's holes anywhere on the bed; the job is put on
    them. Sets ``page._autocal_found``."""
    from gerber2rml.engine import xtool_camera as cam
    page._autocal_found = None
    if len(page.base_art.drills or []) < 2:
        page._autocal_found = "no holes"
        return page.take_photo()
    candidates = []
    for k in range(4):
        art = xtool.rotated(page.base_art, page.turns + k, page.fine)
        w, h = art.size
        origin = (BED_MIDDLE[0] - w / 2.0, BED_MIDDLE[1] - h / 2.0)
        candidates.append((k, art, origin, page._hole_paths(art, origin)))
    hi = WIDE_PX_PER_MM

    def work(_p):
        rgb = page._photo(hi)
        tried = []
        for k, _art, _o, holes in candidates:
            a = cam.align(rgb, hi, holes, search_mm=WIDE_SEARCH_MM,
                          max_turn=WIDE_MAX_TURN, need=cam.DRILLED_NEED)
            tried.append((k, holes, a))
        good = [t for t in tried if t[2].ok]
        pick = max(good or tried, key=lambda t: (
            t[2].found / max(t[2].total, 1), t[2].score))
        return page._photo(), pick, bool(good)

    def done(res):
        rgb, (k, holes, a), good = res
        page.show_bed(rgb)
        if not good:
            page._autocal_found = False
            return (f"The board was not found on the bed: at best {a.found} of "
                    f"{a.total} holes matched. Check it lies under the camera, "
                    "drilled face up, or drag the drawing onto it and press "
                    "Calibrate again.")
        target = page._middle(holes) + (a.dx, a.dy)
        page._turn_to(page.turns + k, page.fine + a.turn,
                      preserve_selection=True)
        now = page._hole_paths()
        dx, dy = target - page._middle(now)
        page.x.setValue(round(page.x.value() + dx, 3))
        page.y.setValue(round(page.y.value() + dy, 3))
        page._clear_references()
        turned = (90 * k + a.turn + 180) % 360 - 180
        page._autocal_found = True
        return (f"Board found on {a.found} of {a.total} holes, turned "
                f"{turned:+.1f}°.")
    page._start(work, "Finding the board on the bed…", done)


class AutoCalibration:
    """Runs the steps one after another on the page's worker."""

    def __init__(self, page):
        self.page = page
        self.steps = [
            ("Find the board", lambda: find_board(page), self._found),
            ("Autofocus", lambda: page.autofocus(), self._ok),
            ("Camera and holes", page.proof, self._proof),
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
    if getattr(page, "kind", None) != "traces" or getattr(page, "_empty", True):
        return page._say("Calibrate sets up a traces job: load a board first.",
                         warn=True)
    if page._worker_running():
        return page._say("The laser is busy.", warn=True)
    AutoCalibration(page).start()


def after_step(page, msg, warn):
    """Called by the page when any step ends: hands it to a running
    calibration, on the next turn of the event loop."""
    ac = getattr(page, "_autocal", None)
    if ac is not None:
        QTimer.singleShot(0, lambda: ac.step_done(msg, warn))
