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
   corner. Then copper is checked just inside the right and back edges; if
   it is not there, the stock is smaller than typed and the run stops.

**Nothing on the bed is sensed but copper.** A clamp, a fixture bracket or
the probe clip's tape is invisible to the probe, and the edge walk travels
only 0.4 mm above the copper - so it must never be sent where one stands:

* every move between probe spots goes up first - ``TRAVEL_UM`` above the
  copper once it is known (clears the fixture's knobs), the top before;
* a walk goes no further than the stock could reach (its typed size), and on
  a fresh stock stops at the first spot with no copper - at most one 2 mm
  step past the edge;
* nothing is probed outside the stock except those walks, and ``rows``
  places them on edges that are clear (see :func:`find_stock`).

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
CHECK_UM = 5000              # how far inside the far edges copper is checked
TRAVEL_UM = 10000            # lift above the copper between spots; the jog adds
                             # 5 more: 15 mm clears the DTU fixture knobs
LAB_COPPER_UM = -57200       # the lab's copper with a usual bit: only ever used
                             # by a descent that stops on touch (firmware v5)
TOUCH_BACK_UM = 3000         # up this far after a fast descent touched early
HINT_ABOVE_UM = 5000         # a remembered surface: drop fast to this far above it,
                             # inside the probe's 6 mm reach, so one probe finds it


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


def travel(ser, x_um, y_um, should_abort=None, surface_um=None):
    """Go to (x, y) over everything: up ``TRAVEL_UM`` above the copper (or to
    the top of Z while the copper is unknown), then across. A jog alone lifts
    only 5 mm, which a clamp knob can be taller than."""
    pos = spi_probe.query_position(ser)
    if pos is None:
        raise ProbeError("cannot read where the head is")
    safe = 0 if surface_um is None else min(0, surface_um + TRAVEL_UM)
    if pos[2] * 1000 < safe - 500:
        if spi_probe.timed_move(ser, dz_um=int(safe - pos[2] * 1000),
                                should_abort=should_abort) is None:
            raise ProbeError("the head did not lift")
    if not spi_probe.jog_to(ser, x_um, y_um):
        raise ProbeError("the head did not move")


def seek_surface(ser, x_um, y_um, should_abort=None, note=None,
                 hint_um=None):
    """Go to (x, y) and find the copper below it. Returns its machine Z (um).

    ``hint_um`` is where the copper was last time (the bed and fixture do
    not move): the head drops there fast, to ``HINT_ABOVE_UM`` above it,
    instead of feeling its way down from the top. Stock that much thicker
    than last time is still found from above; thinner is found by stepping
    on down as usual."""
    note = note or (lambda _m: None)
    travel(ser, x_um, y_um, should_abort)
    drop_to_hint(ser, hint_um, should_abort, note)
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


def drop_to_hint(ser, hint_um, should_abort=None, note=None):
    """Fast down from wherever the head is to ``HINT_ABOVE_UM`` above where
    the copper was last time. Never moves up. False if the move failed.

    Firmware v5 halts this at the first touch, so it can run with no remembered
    height too, on the lab's usual one. Older firmware cannot: it only drops on
    a remembered height, and copper higher than that gets hit."""
    note = note or (lambda _m: None)
    _ver, feats = spi_probe.firmware_version(ser)
    stops = "touchstop" in feats
    if hint_um is None:
        if not stops:
            note("No copper height known yet: feeling down from here.")
            return True
        hint_um = LAB_COPPER_UM
    pos = spi_probe.query_position(ser)
    if pos is None:
        note("Fast drop skipped: cannot read where the head is.")
        return False
    target = min(0, int(hint_um) + HINT_ABOVE_UM)
    z = pos[2] * 1000
    if z <= target + 500:
        return True
    note("Dropping fast to Z %.1f mm…" % (target / 1000.0))
    why = []
    if stops:
        r = spi_probe.fast_descend(ser, target, should_abort, last_error=why)
        if r == "touch":
            note("Touched copper on the way down, higher than expected.")
            spi_probe.timed_move(ser, dz_um=TOUCH_BACK_UM,
                                 should_abort=should_abort)
    else:
        r = spi_probe.timed_move(ser, dz_um=int(target - z),
                                 should_abort=should_abort, last_error=why)
    if r is None:
        note("Fast drop failed (%s): feeling down from here."
             % (why[0] if why else "no reply"))
        return False
    return True


def touch_from_anywhere(ser, hint_um=None, should_abort=None):
    """Find the copper under the head from any height, without moving XY.

    Fast to just above ``hint_um`` when the copper's height is known. After
    that, or with no hint, touch-offs: each reaches 6 mm below where it starts
    and comes back up empty, so the next starts ``DROP_STEP_UM`` lower. Returns
    ``(x_mm, y_mm, z_mm)``, or None if it stopped without one."""
    try:
        if not drop_to_hint(ser, hint_um, should_abort):
            return None
        pos = spi_probe.query_position(ser)
        if pos is None:
            return None
        start = int(pos[2] * 1000)
        while True:
            r = _cmd(ser, "T", should_abort, 40.0)
            if r and r.startswith("T "):
                x, y, z = r.split()[1:4]
                return int(x) / 1000.0, int(y) / 1000.0, int(z) / 1000.0
            # Only a clean miss may go lower. On anything else, above all the
            # probe already reading contact, going lower drives the bit in.
            if not (r and r.rstrip().endswith("NOTOUCH")):
                return None
            start -= DROP_STEP_UM
            if start < Z_LIMIT_UM:
                return None
            pos = spi_probe.query_position(ser)
            if pos is None or pos[3]:
                return None
            if spi_probe.timed_move(ser, dz_um=int(start - pos[2] * 1000),
                                    should_abort=should_abort) is None:
                return None
    except ProbeError:
        return None


def reference_at(ser, x_um, y_um, should_abort=None, surface_um=None):
    """Re-take the surface reference at (x, y), which must be copper.

    ``surface_um`` is where the copper is known to be roughly: the head is
    brought down to 3 mm above it first, because a probe only reaches 6 mm
    below where it starts and a jog lifts 5 mm."""
    travel(ser, x_um, y_um, should_abort, surface_um)
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
              surface_um=None, holes=False):
    """Walk from (x0, y0) - on copper - along (dx, dy) to the edge of the
    copper. Returns the distance (um) to it, bisected to ``TOL_UM``.

    ``holes``: the stock was drilled already (the flipped side), so a spot
    with no copper may be a hole, not the edge - look 2 and 4 mm further
    on. Off for a fresh stock: those looks are the walk's furthest reach
    past the edge, where a clamp may stand."""
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
            past = None if not holes else next(
                (d + k for k in (MARCH_UM, 2 * MARCH_UM)
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
        raise StockNotFound("still copper %.0f mm on, further than the "
                            "stock reaches - is the size right, and is the "
                            "bed conducting? The stock must sit on tape or "
                            "paper." % (span_um / 1000))
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
               note=None, bed_mm=(203.2, 152.4), rows=None, holes=False,
               checks=None, measure=False, hint_mm=None):
    """Find the stock the operator clicked on. Returns a :class:`StockPose`.

    ``click_mm`` is the clicked machine (x, y); ``size_mm`` the (w, h) the
    operator typed; ``bit_mm`` the flat bit in the collet. Raises
    :class:`StockNotFound` with the reason.

    ``rows`` places the four walks, for a stock held by clamps or a fixture:
    ``{"corner": (x, y), "left": (v1, v2), "front": (u1, u2),
    "start": (u, v)}`` - the rough front-left corner (machine mm), the
    heights up the left edge and the distances along the front edge to cross
    them at (mm from that corner), and the copper spot the walks start from.
    Without it the walks start at the click and run left and forward from
    it. ``checks`` are the (u, v) spots inside the far edges where copper
    must be (default: 5 mm in from the right and back edges, half-way along).
    ``measure`` walks to the right and back edges when the size is wrong -
    off by default, because those walks cross edges nobody chose.
    ``hint_mm`` is the copper's machine Z last time (see :func:`seek_surface`).

    A flat bit touches with its whole end, so it still reads copper until
    its centre is a radius past the edge: every edge is measured that much
    too far out, and the radius is taken back off."""
    note = note or (lambda _m: None)
    cx, cy = int(click_mm[0] * 1000), int(click_mm[1] * 1000)
    w, h = size_mm
    r = bit_mm * 500.0
    if rows:
        gx, gy = (int(v * 1000) for v in rows["corner"])
        su, sv = (int(v * 1000) for v in rows["start"])
        left_at = [(gx + su, gy + int(v * 1000)) for v in rows["left"]]
        front_at = [(gx + int(u * 1000), gy + sv) for u in rows["front"]]
        cx, cy = gx + su, gy + sv
    else:
        # The two points on an edge set the angle: 50 um of edge error over
        # 10 mm is 0.3 degrees, over 30 mm a third of that.
        sp = int(min(30.0, 0.4 * min(w, h)) * 1000)
        left_at = [(cx, cy), (cx, cy + sp)]
        front_at = [(cx, cy), (cx + sp, cy)]
    surface = seek_surface(ser, cx, cy, should_abort, note,
                           None if hint_mm is None else int(hint_mm * 1000))
    note("Finding the left edge…")
    left = []
    for x, y in left_at:
        reference_at(ser, x, y, should_abort, surface)
        d = find_edge(ser, x, y, -1, 0, int(w * 1000) + 5000, should_abort,
                      surface, holes) - r
        left.append((x - d, y))
    note("Finding the front edge…")
    front = []
    for x, y in front_at:
        reference_at(ser, x, y, should_abort, surface)
        d = find_edge(ser, x, y, 0, -1, int(h * 1000) + 5000, should_abort,
                      surface, holes) - r
        front.append((x, y - d))
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
    try:
        _check_size(ser, pose, should_abort, checks)
    except StockNotFound:
        if not measure:
            raise
        note("That is not the size typed - measuring the stock…")
        mw, mh = measure_size(ser, pose, (cx, cy), surface, r,
                              int(max(bed_mm) * 1000), should_abort)
        e = StockNotFound(
            "the stock measures %.1f × %.1f mm, not %.1f × %.1f. The size "
            "has been filled in - check it and press Start again."
            % (mw, mh, w, h))
        e.measured = (mw, mh)
        raise e
    return pose


CORNERS = ("back-left", "front-left", "back-right", "front-right")


def datum_outline(datum_mm, corner, size_mm):
    """The stock's front-left corner (machine mm) when its ``corner`` sits in
    the bracket at ``datum_mm`` - the same outline :func:`from_datum` uses."""
    if corner not in CORNERS:
        raise ValueError("corner must be one of %s" % (CORNERS,))
    w, h = size_mm
    dx, dy = datum_mm
    return (dx if "left" in corner else dx - w,
            dy if "front" in corner else dy - h)


def from_datum(ser, datum_mm, corner, size_mm, should_abort=None, note=None,
               hint_mm=None):
    """The stock pushed into a fixed corner bracket: its outline is that
    corner and the typed size, so only the copper's height is measured - one
    touch, 15 mm in from the bracket corner (always copper, whatever the
    size). The bracket holds the stock square to the bed (measured -0.10°
    on the DTU fixture, 2026-11-02), so the turn is taken as 0.

    ``datum_mm`` is the bracket's inside corner in machine mm, ``corner``
    which corner of the stock sits in it (:data:`CORNERS`). Returns a
    :class:`StockPose` (front-left corner, like :func:`find_stock`)."""
    note = note or (lambda _m: None)
    w, h = size_mm
    dx, dy = datum_mm
    x0, y0 = datum_outline(datum_mm, corner, size_mm)
    left, front = "left" in corner, "front" in corner
    inset = min(15.0, w / 2.0, h / 2.0)
    sx = dx + (inset if left else -inset)
    sy = dy + (inset if front else -inset)
    note("Touching the copper at X %.1f, Y %.1f…" % (sx, sy))
    z = seek_surface(ser, int(sx * 1000), int(sy * 1000), should_abort, note,
                     None if hint_mm is None else int(hint_mm * 1000))
    return StockPose(x0, y0, 0.0, w, h, z / 1000.0)


def plan(size_mm, rows, checks=None):
    """Where :func:`find_stock` will go with these ``rows``, if the stock
    lies where the rows guess: ``[(kind, (x, y), (x2, y2) or None)]`` in
    machine mm - ``"walk"`` from the start to 3 mm past the edge, ``"spot"``
    for a straight-down touch. For a rehearsal in the air."""
    w, h = size_mm
    gx, gy = rows["corner"]
    su, sv = rows["start"]
    out = [("spot", (gx + su, gy + sv), None)]
    for v in rows["left"]:
        out.append(("walk", (gx + su, gy + v), (gx - 3, gy + v)))
    for u in rows["front"]:
        out.append(("walk", (gx + u, gy + sv), (gx + u, gy - 3)))
    for u, v in checks or _default_checks(w, h):
        out.append(("spot", (gx + u, gy + v), None))
    return out


def _default_checks(w, h):
    c = CHECK_UM / 1000.0
    return ((w - c, h / 2), (w / 2, h - c))


def measure_size(ser, pose, click_um, surface_um, r_um, span_um,
                 should_abort=None):
    """The stock's real (w, h) mm: from the clicked spot, walk along the
    stock's own axes to its far edges."""
    a = math.radians(pose.angle)
    ux, uy = math.cos(a), math.sin(a)
    vx, vy = -math.sin(a), math.cos(a)
    cx, cy = click_um
    dx, dy = cx - pose.x * 1000, cy - pose.y * 1000
    u0, v0 = dx * ux + dy * uy, dx * vx + dy * vy
    reference_at(ser, int(cx), int(cy), should_abort, surface_um)
    du = find_edge(ser, cx, cy, ux, uy, span_um, should_abort, surface_um)
    reference_at(ser, int(cx), int(cy), should_abort, surface_um)
    dv = find_edge(ser, cx, cy, vx, vy, span_um, should_abort, surface_um)
    return ((u0 + du - r_um) / 1000.0, (v0 + dv - r_um) / 1000.0)


def _check_size(ser, pose, should_abort, checks=None):
    """Copper just inside the far edges, touched straight down (re-referenced
    there, so a bowed sheet still reads as copper). Never outside the stock:
    that is where clamps and fixture brackets stand."""
    for u, v in checks or _default_checks(pose.w, pose.h):
        x, y = pose.to_machine(u, v)
        try:
            reference_at(ser, int(x * 1000), int(y * 1000), should_abort,
                         int(pose.z * 1000))
        except ProbeError as e:
            if str(e) == "stopped":
                raise
            raise StockNotFound(
                "no copper at %.0f, %.0f mm on the stock - it is not %.1f × "
                "%.1f mm. Measure it and type the size again."
                % (u, v, pose.w, pose.h))
