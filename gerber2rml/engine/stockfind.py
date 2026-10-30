"""Find the copper stock on the bed with the touch probe.

The operator puts the stock down, clips the probe to it and clicks roughly
where it is. From there:

1. **The surface.** The firmware never drops more than 6 mm below where a
   probe starts (``PROBE_MAX_DROP_UM``), and the head starts tens of
   millimetres up. So it latches a datum, probes, and on no contact steps
   down 5.5 mm and tries again - each step is inside the 6 mm it has just
   proven empty.
2. **Two edges.** From the click it walks left (-X) and toward the front
   (-Y), copper to no copper, and bisects each edge to ~50 um - twice per
   edge, 10 mm apart, so each edge is a line and the stock's turn on the bed
   comes out of it. The edge test is the firmware's hole test (``H``): a
   shallow descent referenced to the copper just measured, so off the stock,
   over the bed, nothing plunges. The reference is re-taken as the walk goes,
   because a bowed sheet drifts out of the test's 0.2 mm window.
3. **The corner and the size.** The two lines cross at the front-left
   corner. The far corners are then checked: just inside them must be
   copper, just outside must not, or the stock is not the size the operator
   typed and the run stops there.

The bed must not conduct (tape hold, the default) and the clip must be on
the stock's copper - otherwise there is no edge to find, and the walk says so.
"""
import math
from dataclasses import dataclass

from gerber2rml.engine import spi_probe
from gerber2rml.engine.fidfind import hole_test
from gerber2rml.engine.spi_probe import ProbeError, _read_line

DROP_STEP_UM = 5500          # inside the firmware's 6 mm probe floor
Z_LIMIT_UM = -58000          # the deepest the head may go looking (Z travel)
MARCH_UM = 2000
TOL_UM = 50
REREF_UM = 20000
CHECK_UM = 1500              # how far inside/outside the far corners to test


@dataclass
class StockPose:
    """Where the stock is: front-left corner (mm, machine), its turn on the
    bed (degrees, CCW), its size (mm) and the copper's machine Z (mm)."""
    x: float
    y: float
    angle: float
    w: float
    h: float
    z: float

    def to_machine(self, u, v):
        """Stock (u, v) mm -> machine (x, y) mm."""
        a = math.radians(self.angle)
        return (self.x + u * math.cos(a) - v * math.sin(a),
                self.y + u * math.sin(a) + v * math.cos(a))


class StockNotFound(ProbeError):
    pass


def _cmd(ser, line, should_abort, timeout=120.0):
    import time
    ser.write((line + "\n").encode())
    reply = _read_line(ser, time.monotonic() + timeout, should_abort)
    if should_abort is not None and should_abort():
        spi_probe.send_abort(ser)
        raise ProbeError("stopped")
    return reply


def seek_surface(ser, x_um, y_um, should_abort=None, note=None):
    """Go to (x, y) and find the copper below it. Returns its machine Z (um)."""
    note = note or (lambda _m: None)
    if not spi_probe.jog_to(ser, x_um, y_um):
        raise ProbeError("the head did not go to the clicked spot")
    while True:
        r = _cmd(ser, "D", should_abort, 5.0)
        if not r or not r.startswith("D "):
            raise ProbeError("the machine did not latch a datum (%r)" % (r,))
        z = int(r.split()[3])
        note("Looking for the copper surface, Z %.1f mm…" % (z / 1000.0))
        r = _cmd(ser, "P 900 0 0", should_abort)
        if r and r.startswith("R "):
            return int(r.split()[4])
        if r and r.rstrip().endswith("LOW"):
            raise StockNotFound(
                "the probe already reads contact. Check the clip is on the "
                "stock's copper and not touching the bit or the bed.")
        if z - DROP_STEP_UM < Z_LIMIT_UM:
            raise StockNotFound(
                "no copper under the clicked spot, all the way down. Click on "
                "the stock, and check the clip is on its copper.")
        spi_probe.timed_move(ser, dz_um=-DROP_STEP_UM,
                             should_abort=should_abort)


def reference_at(ser, x_um, y_um, should_abort=None, surface_um=None):
    """Re-take the surface reference at (x, y), which must be copper.

    ``surface_um`` is where the copper is known to be roughly: the head is
    brought down to 3 mm above it first, because a probe only reaches 6 mm
    below where it starts and a jog lifts 5 mm."""
    if not spi_probe.jog_to(ser, x_um, y_um):
        raise ProbeError("the head did not move")
    if surface_um is not None:
        pos = spi_probe.query_position(ser)
        if pos is not None and pos[2] * 1000 - surface_um > 4000:
            spi_probe.timed_move(ser, dz_um=int(surface_um + 3000
                                                - pos[2] * 1000),
                                 should_abort=should_abort)
    r = _cmd(ser, "D", should_abort, 5.0)
    if not r or not r.startswith("D "):
        raise ProbeError("the machine did not latch a datum (%r)" % (r,))
    r = _cmd(ser, "P 901 0 0", should_abort)
    if not (r and r.startswith("R ")):
        raise ProbeError("lost the copper at %.2f, %.2f (%r)"
                         % (x_um / 1000, y_um / 1000, r))
    return int(r.split()[4])


def find_edge(ser, x0, y0, dx, dy, span_um, should_abort=None,
              surface_um=None):
    """Walk from (x0, y0) - on copper - along (dx, dy) to the edge of the
    copper. Returns the distance (um) to it, bisected to ``TOL_UM``."""
    def copper(d):
        return hole_test(ser, x0 + dx * d, y0 + dy * d,
                         should_abort=should_abort)
    lo, hi, d, since = 0, None, MARCH_UM, 0
    while d <= span_um:
        if since >= REREF_UM:
            reference_at(ser, int(x0 + dx * lo), int(y0 + dy * lo),
                         should_abort, surface_um)
            since = 0
        if not copper(d):
            # A hole drilled on the first side reads the same as the edge.
            # The edge is no copper from here on; a hole has copper past it.
            past = next((d + k for k in (MARCH_UM, 2 * MARCH_UM)
                         if d + k <= span_um and copper(d + k)), None)
            if past is None:
                hi = d
                break
            since += past - lo
            lo, d = past, past + MARCH_UM
            continue
        since += d - lo
        lo, d = d, d + MARCH_UM
    if hi is None:
        raise StockNotFound("copper all the way, %.0f mm - is the bed "
                            "conducting? The stock must sit on tape or paper."
                            % (span_um / 1000))
    while hi - lo > TOL_UM:
        mid = (lo + hi) // 2
        if copper(mid):
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _line(p, q):
    """(point, unit direction) through two points."""
    d = (q[0] - p[0], q[1] - p[1])
    n = math.hypot(*d)
    return p, (d[0] / n, d[1] / n)


def _cross(l1, l2):
    (p, d), (q, e) = l1, l2
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-9:
        raise StockNotFound("the two edges came out parallel")
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return p[0] + t * d[0], p[1] + t * d[1]


def find_stock(ser, click_mm, size_mm, bit_mm=0.8, should_abort=None,
               note=None, bed_mm=(203.2, 152.4)):
    """Find the stock the operator clicked on. Returns a :class:`StockPose`.

    ``click_mm`` is the clicked machine (x, y); ``size_mm`` the (w, h) the
    operator typed; ``bit_mm`` the flat bit in the collet. Raises
    :class:`StockNotFound` with the reason.

    A flat bit touches with its whole end, so it still reads copper until
    its centre is a radius past the edge: every edge is measured that much
    too far out, and the radius is taken back off."""
    note = note or (lambda _m: None)
    cx, cy = int(click_mm[0] * 1000), int(click_mm[1] * 1000)
    w, h = size_mm
    r = bit_mm * 500.0
    surface = seek_surface(ser, cx, cy, should_abort, note)
    # The two points on an edge set the angle: 50 um of edge error over
    # 10 mm is 0.3 degrees, over 30 mm a third of that.
    sp = int(min(30.0, 0.4 * min(w, h)) * 1000)
    span = int(max(bed_mm) * 1000)
    note("Finding the left edge…")
    left = []
    for oy in (0, sp):
        reference_at(ser, cx, cy + oy, should_abort, surface)
        d = find_edge(ser, cx, cy + oy, -1, 0, span, should_abort,
                      surface) - r
        left.append((cx - d, cy + oy))
    note("Finding the front edge…")
    front = []
    for ox in (0, sp):
        reference_at(ser, cx + ox, cy, should_abort, surface)
        d = find_edge(ser, cx + ox, cy, 0, -1, span, should_abort,
                      surface) - r
        front.append((cx + ox, cy - d))
    lx, ly = _cross(_line(*left), _line(*front))
    fd = _line(*front)[1]
    angle = math.degrees(math.atan2(fd[1], fd[0]))
    ld = _line(*left)[1]
    skew = abs(90.0 - abs(math.degrees(math.atan2(ld[1], ld[0])) - angle))
    if skew > 2.0:
        raise StockNotFound("the edges are %.1f° off square - is something "
                            "lying against the stock?" % skew)
    pose = StockPose(lx / 1000.0, ly / 1000.0, angle, w, h, surface / 1000.0)
    note("Checking the size…")
    _check_size(ser, pose, should_abort)
    return pose


def _check_size(ser, pose, should_abort):
    c = CHECK_UM / 1000.0
    for u, v, want, what in ((pose.w - c, pose.h / 2, True, "width"),
                             (pose.w + c, pose.h / 2, False, "width"),
                             (pose.w / 2, pose.h - c, True, "height"),
                             (pose.w / 2, pose.h + c, False, "height")):
        x, y = pose.to_machine(u, v)
        if want:
            # Inside: re-reference there, so a bowed sheet reads as copper.
            try:
                reference_at(ser, int(x * 1000), int(y * 1000), should_abort,
                             int(pose.z * 1000))
                got = True
            except ProbeError as e:
                if str(e) == "stopped":
                    raise
                got = False
        else:
            got = hole_test(ser, int(x * 1000), int(y * 1000),
                            should_abort=should_abort)
        if got != want:
            raise StockNotFound(
                "the stock is not %.1f × %.1f mm - its %s does not match. "
                "Measure it and type the size again." % (pose.w, pose.h, what))
