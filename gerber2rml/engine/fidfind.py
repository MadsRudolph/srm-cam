"""Automatic fiducial finding: locate a drilled hole's center electrically.

The touch probe senses copper (tool touching copper pulls D7 low). Over the
drilled fiducial hole there is nothing to touch, so a shallow descend
distinguishes hole from copper — the firmware's ``H x y`` test (v2). Center
finding is classic edge bisection: from a start point inside the hole, walk
outward until copper, bisect the edge to ~50 um, do the same on the other
side, midpoint = center; repeat in Y at the found X (and a second X pass at
the found Y for good measure).

Total ~25-35 touch tests per fiducial (~1 min) instead of jogging around by
eye and copying VPanel numbers per hole.
"""
import time

from gerber2rml.engine.spi_probe import ProbeError, _read_line, send_abort


def hole_test(ser, x_um, y_um, timeout=30.0, should_abort=None):
    """``H x y`` -> True (copper contact) / False (hole). Raises on errors."""
    ser.write(f"H {int(x_um)} {int(y_um)}\n".encode())
    line = _read_line(ser, time.monotonic() + timeout, should_abort)
    if should_abort is not None and should_abort():
        send_abort(ser)
        raise ProbeError("aborted")
    if line == "H 1":
        return True
    if line == "H 0":
        return False
    raise ProbeError(f"hole test failed (got {line!r}) — firmware v2 with "
                     f"'holetest' required, and a known surface (probe copper "
                     f"once first)")


def _find_edge(ser, x0, y0, dx, dy, coarse_um=400, span_um=4000, tol_um=50,
               should_abort=None):
    """From (x0, y0) (inside the hole), march along (dx, dy) until copper,
    then bisect the hole->copper edge to ``tol_um``. Returns distance (um)."""
    lo = 0
    hi = None
    d = coarse_um
    while d <= span_um:
        if hole_test(ser, x0 + dx * d, y0 + dy * d, should_abort=should_abort):
            hi = d
            break
        lo = d
        d += coarse_um
    if hi is None:
        raise ProbeError("no copper edge within range — is the tool actually "
                         "over the fiducial hole?")
    while hi - lo > tol_um:
        mid = (lo + hi) // 2
        if hole_test(ser, x0 + dx * mid, y0 + dy * mid,
                     should_abort=should_abort):
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def find_hole_center(ser, x_mm, y_mm, should_abort=None):
    """Locate the hole center starting from (x_mm, y_mm), which must be over
    the hole (jog roughly over it first). Returns (cx_mm, cy_mm).

    Requires: datum latched (``D``), a surface reference (one successful
    probe/``B`` on copper), and the start point actually in the hole.
    """
    x0, y0 = round(x_mm * 1000), round(y_mm * 1000)
    if hole_test(ser, x0, y0, should_abort=should_abort):
        raise ProbeError("copper contact at the start point — jog the tool "
                         "over the fiducial HOLE first")
    right = _find_edge(ser, x0, y0, 1, 0, should_abort=should_abort)
    left = _find_edge(ser, x0, y0, -1, 0, should_abort=should_abort)
    cx = x0 + (right - left) / 2.0
    up = _find_edge(ser, round(cx), y0, 0, 1, should_abort=should_abort)
    down = _find_edge(ser, round(cx), y0, 0, -1, should_abort=should_abort)
    cy = y0 + (up - down) / 2.0
    # second X pass at the true Y: kills the chord error of the first pass
    right = _find_edge(ser, round(cx), round(cy), 1, 0,
                       should_abort=should_abort)
    left = _find_edge(ser, round(cx), round(cy), -1, 0,
                      should_abort=should_abort)
    cx = cx + (right - left) / 2.0
    return cx / 1000.0, cy / 1000.0
