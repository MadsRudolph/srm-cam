"""Cut a stencil on the xTool F1 Ultra without xTool's software.

The F1 Ultra plugged in by USB shows up as a network adapter, with the laser at
:data:`HOST`. It takes a whole job as text, the same G-code dialect xTool's own
software writes ("GS002"), by HTTP POST, and can start it by itself. That was
worked out on the lab's machine (firmware 40.52, Nov 2026) from xTool Studio's
job templates; solder-stencil-tests/docs/OPEN_CONTROL.md has the details.

Why not just use XCS: a stencil warps if one spot gets 30 passes in a row. The
heat has to be spread out. XCS runs a job's passes back to back and cannot pause
between them, so this module writes one job file that does:

    for each round:  for each zone:  N passes over that zone's holes, then rest

Each zone is one angular sector of the holes, so while one zone is cut the others
cool. The rest is the beam parked with the laser off (S0) and the galvo crawling
slowly: the firmware ignores G4 dwells, and S0 was checked to leave no trace on
steel even with the fiber selected. The finished file is one upload; anything on
the PC that can talk to the laser can run it.

Units on the wire: mm, S = power 0..1000, F = mm/min, G0Q = frequency in kHz,
G22 = fiber (the "red" source), G21 = blue diode. Coordinates are the XCS canvas:
mm from the bed's top-left corner, Y down, 0..234.
"""
import http.client
import json
import math
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

HOST = "201.234.3.1"
HTTP_PORT = 8080
BED_MM = 234.0
FOCUS_OFFSET = 8.0          # focus Z = XCS material thickness + 8 (xTool Studio)
CRAWL_MM_S = 1.0            # galvo speed while resting with the laser off


@dataclass(frozen=True)
class Recipe:
    """How to cut. The defaults are 0.1 mm 304 stainless, dialled in on the
    lab's F1 Ultra: through in 30 passes, flat with ~25 s between a zone's bursts."""
    power: float = 100.0        # %
    speed: float = 550.0        # mm/s
    frequency: float = 30.0     # kHz
    total_passes: int = 30
    passes_per_burst: int = 5
    rest_s: float = 6.0         # laser-off pause after every burst
    zones: int = 4
    mark_power: float = 50.0    # the board outline is marked, not cut
    mark_passes: int = 1

    @property
    def rounds(self):
        return math.ceil(self.total_passes / self.passes_per_burst)


DEFAULT_RECIPE = Recipe()


# ---------------------------------------------------------------------------
# Geometry: artwork frame -> bed
# ---------------------------------------------------------------------------

def to_bed(ring_coords, origin, height):
    """Artwork coordinates (mm, Y up, outline's lower-left at 0,0) to the bed
    (mm, Y down). ``origin`` is where the outline's top-left corner sits on the
    bed, as XCS shows the X and Y of the stencil DXF placed on its camera image."""
    ox, oy = origin
    return [(ox + x, oy + (height - y)) for x, y in ring_coords]


def stencil_paths(art, origin, only=None):
    """(holes, outline) as closed point lists on the bed. ``only``, a set of
    indices into ``art.apertures``, keeps just those holes: a re-cut."""
    _, h = art.size
    holes = []
    for k, poly in enumerate(art.apertures):
        if only is not None and k not in only:
            continue
        for ring in (poly.exterior, *poly.interiors):
            holes.append(to_bed(list(ring.coords), origin, h))
    outline = [to_bed(list(r.coords), origin, h)
               for r in (art.outline.exterior, *art.outline.interiors)]
    return holes, outline


def rotated(art, quarter_turns, degrees=0.0):
    """The artwork turned clockwise as seen on the bed, by 90 degrees a step
    and ``degrees`` more, with its outline's bounding box back at (0, 0)."""
    from dataclasses import replace as _replace
    from shapely.affinity import rotate, translate
    from shapely.geometry import Point
    angle = (quarter_turns % 4) * 90 + degrees
    if abs(angle % 360) < 1e-9:
        return art
    # The artwork frame is Y up; clockwise on the Y-down bed is negative here.
    turn = lambda g: rotate(g, -angle, origin=(0, 0))
    outline = turn(art.outline)
    x0, y0, _, _ = outline.bounds
    move = lambda g: translate(g, -x0, -y0)
    out = _replace(art, outline=move(outline),
                   apertures=[move(turn(p)) for p in art.apertures])
    if hasattr(art, "_ring_cache"):
        out = _replace(out, _ring_cache=None)
    if getattr(art, "features", None):
        out = _replace(out, features=[move(turn(p)) for p in art.features])
    if getattr(art, "copper", None) is not None:
        out = _replace(out, copper=move(turn(art.copper)))
    if getattr(art, "drills", None):
        moved = []
        for x, y, d in art.drills:
            p = move(turn(Point(x, y)))
            moved.append((p.x, p.y, d))
        out = _replace(out, drills=moved)
    return out


def snap_to_grid(point, step=10.0, extent=220.0):
    """The calibrated point nearest ``point``: autofocus measures on the
    factory's 10 mm grid."""
    return tuple(min(max(round(v / step) * step, 0.0), extent) for v in point)


def check_on_bed(paths):
    xs = [x for p in paths for x, _ in p]
    ys = [y for p in paths for _, y in p]
    if min(xs) < 0 or min(ys) < 0 or max(xs) > BED_MM or max(ys) > BED_MM:
        raise ValueError(f"The job runs off the laser's {BED_MM:g} mm field: "
                         f"X {min(xs):.1f}..{max(xs):.1f}, Y {min(ys):.1f}..{max(ys):.1f}.")


def zones(paths, n):
    """Split paths into up to ``n`` angular sectors around their common centre,
    each in nearest-neighbour order. Empty sectors are dropped."""
    if n <= 1 or len(paths) <= 1:
        return [list(paths)]
    cs = [_centroid(p) for p in paths]
    cx = sum(c[0] for c in cs) / len(cs)
    cy = sum(c[1] for c in cs) / len(cs)
    out = [[] for _ in range(n)]
    for p, (x, y) in zip(paths, cs):
        a = (math.atan2(y - cy, x - cx) + math.pi / n) % (2 * math.pi)
        out[int(a / (2 * math.pi / n)) % n].append(p)
    return [_nearest_order(z) for z in out if z]


def _centroid(p):
    pts = p[:-1] if len(p) > 1 and p[0] == p[-1] else p
    return sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)


def _nearest_order(paths):
    left, order = list(paths), []
    while left:
        lx, ly = order[-1][-1] if order else (0.0, 0.0)
        k = min(range(len(left)),
                key=lambda j: (left[j][0][0] - lx) ** 2 + (left[j][0][1] - ly) ** 2)
        order.append(left.pop(k))
    return order


def _length(p):
    return sum(math.dist(a, b) for a, b in zip(p, p[1:]))


# ---------------------------------------------------------------------------
# The job file
# ---------------------------------------------------------------------------

def _head(source, frequency, power_factor):
    return ["# GS002 HEAD", "G0 F180000", "M4 S0", "G1 F180000", "G0 X0 Y0", "",
            "# GS002 VECTOR HEAD", "# motion_start", "G4M1",
            "G22" if source == "fiber" else "G21",
            "G90", f"G0Q{frequency:g}", "G4M1", "M523P40",
            f'# blockConfig={{"powerFactor": {power_factor:g}, "isVector": true, '
            f'"crossDot": false}} ']


_TAIL = ["# END", "# GS002 VECTOR TAIL", "# motion_end", "# GS002 TAIL",
         "G90", "G0 S0", "G0 F180000", "G1 F180000", "M536 U0", "M6 P1", ""]


def _passes(paths, power, speed, n):
    s, f = round(power * 10), round(speed * 60)
    # Geometry finer than the output's 1 µm grid can collapse onto the same
    # coordinate. Do not send stationary laser-on moves to the controller.
    rounded_paths = []
    for path in paths:
        points = []
        for x, y in path:
            point = tuple(0.0 if v == 0 else v
                          for v in (float(f"{x:.3f}"), float(f"{y:.3f}")))
            if not points or point != points[-1]:
                points.append(point)
        if len(points) >= 2:
            rounded_paths.append(points)
    out = []
    for _ in range(n):
        for p in rounded_paths:
            out.append(f"G0X{p[0][0]:.3f}Y{p[0][1]:.3f}")
            for i, (x, y) in enumerate(p[1:]):
                out.append(f"G1X{x:.3f}Y{y:.3f}" + (f"S{s}F{f}" if i == 0 else ""))
    return out


def _rest(at, seconds, seg=5.0):
    """A timed pause: the laser off (S0) and the galvo crawling back and forth."""
    x, y = at
    out, left, fwd = [f"G0X{x:.3f}Y{y:.3f}"], seconds * CRAWL_MM_S, True
    while left > 1e-6:
        step = min(seg, left)
        out.append(f"G1X{x + (step if fwd else 0):.3f}Y{y:.3f}S0F{CRAWL_MM_S * 60:g}")
        left -= step
        fwd = not fwd
    return out


@dataclass
class Job:
    text: str
    zones: list            # hole count per zone
    seconds: float         # estimated run time
    passes: int            # per hole
    zone_paths: list = None    # the paths of each zone, as given
    # (start_s, end_s, zone, round) per burst, -1 for the outline mark; an
    # estimate from the path lengths, for showing progress.
    timeline: list = None

    def at(self, t):
        """(zone, round) the job is probably on ``t`` seconds in, or None."""
        for t0, t1, z, r in self.timeline or ():
            if t0 <= t < t1:
                return z, r
        return None


def stencil_job(holes, outline, recipe=DEFAULT_RECIPE):
    """One GS002 file: every zone ``recipe.rounds`` times with rests, then the
    outline marked."""
    check_on_bed(holes + outline)
    zs = zones(holes, recipe.zones)
    park = min(((x, y) for p in outline for x, y in p), key=lambda q: q[0] + q[1])
    body, secs, timeline = [], 0.0, []
    bursts = [(r, k) for r in range(recipe.rounds) for k in range(len(zs))]
    for i, (r, k) in enumerate(bursts):
        z = zs[k]
        n = min(recipe.passes_per_burst,
                recipe.total_passes - r * recipe.passes_per_burst)
        body += _passes(z, recipe.power, recipe.speed, n)
        dt = n * sum(_length(p) for p in z) / recipe.speed
        timeline.append((secs, secs + dt, k, r))
        secs += dt
        if i < len(bursts) - 1 and recipe.rest_s > 0:
            body += _rest(park, recipe.rest_s)
            secs += recipe.rest_s
    if outline and recipe.mark_passes:
        body += _passes(outline, recipe.mark_power, recipe.speed, recipe.mark_passes)
        dt = recipe.mark_passes * sum(_length(p) for p in outline) / recipe.speed
        timeline.append((secs, secs + dt, -1, recipe.rounds))
        secs += dt
    lines = _head("fiber", recipe.frequency, recipe.power / 100) + body + _TAIL
    return Job(text="\r\n".join(lines), zones=[len(z) for z in zs],
               seconds=secs, passes=recipe.total_passes, zone_paths=zs,
               timeline=timeline)


def trace_job(outline, laps=15, power=6.0, speed=100.0):
    """The blue diode at a power that is visible but does not mark steel,
    running round the outline: XCS's Frame, which this firmware will not take
    from us."""
    check_on_bed(outline)
    lines = _head("blue", 30, power / 100) + _passes(outline, power, speed, laps) + _TAIL
    return "\r\n".join(lines)


# ---------------------------------------------------------------------------
# The laser
# ---------------------------------------------------------------------------

class LaserError(RuntimeError):
    pass


class F1Ultra:
    """The laser over its USB network link. Every call is one short HTTP request."""

    def __init__(self, host=HOST, port=HTTP_PORT, timeout=10):
        self.host, self.port, self.timeout = host, port, timeout

    def _req(self, method, path, body=None, ctype="application/json", timeout=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        c = http.client.HTTPConnection(self.host, self.port,
                                       timeout=timeout or self.timeout)
        try:
            c.request(method, path, body=body.encode() if isinstance(body, str) else body,
                      headers={"Content-Type": ctype} if body is not None else {})
            r = c.getresponse()
            text = r.read().decode("utf-8", "replace")
        except OSError as e:
            raise LaserError(f"No answer from the laser at {self.host} ({e}). Is it "
                             f"switched on and plugged into this PC by USB?") from e
        finally:
            c.close()
        if r.status != 200:
            raise LaserError(f"{method} {path}: HTTP {r.status} {text[:200]}")
        return text

    def _json(self, *a, **kw):
        d = json.loads(self._req(*a, **kw))
        if d.get("code") != 0:
            raise LaserError(f"{a[1]}: {d.get('msg', d)}")
        return d.get("data")

    def info(self):
        return self._json("GET", "/device/machineInfo")

    def mode(self):
        return self._json("GET", "/device/runningStatus")["curMode"]["mode"]

    def z(self):
        return self._json("POST", "/focus/control", {"action": "coord"})["value"]

    def focus(self, thickness, timeout=30):
        """Move the head as XCS does for a material ``thickness`` (what its
        autofocus reports). Returns the Z reached."""
        target = round(thickness + FOCUS_OFFSET, 3)
        self._json("POST", "/device/modeSwitch", {"state": "P_AUTOFOCUS"})
        try:
            self._json("POST", "/focus/control",
                       {"action": "goTo", "Z": target, "stopFirst": 1, "F": 300},
                       timeout=60)
            t0 = time.time()
            while True:
                z = self.z()
                if abs(z - target) < 0.05:
                    return z
                if time.time() - t0 > timeout:
                    raise LaserError(f"Focus stopped at Z {z:.2f}, not {target:.2f}.")
                time.sleep(0.3)
        finally:
            self._json("POST", "/device/modeSwitch", {"state": "P_IDLE"})

    def run(self, gcode, *, autostart=True):
        q = "/processing/upload?gcodeType=processing&fileType=txt"
        self._json("POST", q + ("&autoStart=1" if autostart else ""), gcode,
                   ctype="text/plain", timeout=60)

    def wait(self, timeout, progress=None, poll=0.5):
        """Until the job is done. ``progress(elapsed_s)`` is called while it runs."""
        t0, started = time.time(), False
        while time.time() - t0 < timeout:
            m = self.mode()
            if m not in ("P_IDLE", "P_WORK_DONE"):
                started = True
            elif started or time.time() - t0 > 5:
                return m
            if progress:
                progress(time.time() - t0)
            time.sleep(poll)
        raise LaserError(f"The job did not finish within {timeout:.0f} s.")

    def stop(self):
        self._req("POST", "/processing/stop", "")

    # -- camera, lights, autofocus (engine/xtool_camera.py does the maths) --
    CAMERA_PORT = 8329
    FILL_LIGHT = 136            # the machine's own default brightness

    def _raw(self, port, path, *, method="GET", body=None, timeout=40):
        c = http.client.HTTPConnection(self.host, port, timeout=timeout)
        try:
            data = json.dumps(body) if isinstance(body, dict) else body
            c.request(method, path, body=data,
                      headers={"Content-Type": "application/json"} if data else {})
            r = c.getresponse()
            out = r.read()
        except OSError as e:
            raise LaserError(f"No answer from the laser at {self.host} ({e}).") from e
        finally:
            c.close()
        if r.status != 200:
            raise LaserError(f"{path}: HTTP {r.status}")
        return out

    def download(self, filename):
        """One of the machine's own files, e.g. ``global_calib.json``."""
        return self._raw(self.port, f"/file?action=download&filename={filename}"
                                    f"&filetype=3")

    def calibration(self):
        from gerber2rml.engine.xtool_camera import Calibration
        return Calibration(self.download("global_calib.json"),
                           self.download("global_ir.json"))

    def gcode(self, line):
        """One line straight to the motion controller."""
        from urllib.parse import quote
        return self._raw(self.port, f"/cmd?cmd={quote(line)}", timeout=10)

    def lights(self, on):
        self._json("POST", "/peripheral/fill_light",
                   {"action": "set_bri", "idx": 0,
                    "value": self.FILL_LIGHT if on else 0})
        self._json("POST", "/peripheral/ir_led",
                   {"action": "on" if on else "off", "index": 0})
        self._raw(self.CAMERA_PORT, "/camera/exposure?stream=0", method="POST",
                  body={"value": 0 if on else 10})

    def snap(self):
        """The camera's full-size JPEG."""
        if self.mode() == "P_SLEEP":
            self._json("POST", "/device/modeSwitch", {"state": "P_IDLE"})
            time.sleep(0.5)
        return self._raw(self.CAMERA_PORT,
                         "/camera/snap?width=4656&height=3496&timeOut=30000",
                         timeout=60)

    def _goto_z(self, target, timeout=30):
        self._json("POST", "/focus/control",
                   {"action": "goTo", "Z": round(target, 3), "stopFirst": 1, "F": 300},
                   timeout=60)
        t0 = time.time()
        while time.time() - t0 < timeout:
            z = self.z()
            if abs(z - target) < 0.05:
                return z
            time.sleep(0.3)
        raise LaserError(f"The head stopped at Z {self.z():.2f}, not {target:.2f}.")

    def measure(self, cal, at=None):
        """mm the surface under ``at`` (a 10 mm grid point; the middle of the
        bed by default) is above focus, by the blue dot. Call inside autofocus
        mode."""
        from gerber2rml.engine.xtool_camera import DOT_AT, decode_jpeg
        at = snap_to_grid(at or DOT_AT)
        self.lights(False)
        try:
            self.gcode(f"G0X{at[0]:g}Y{at[1]:g}F60000")
            time.sleep(0.3)
            self.gcode("M3S30")             # the blue diode at a glow
            time.sleep(0.5)
            photo = self._raw(self.CAMERA_PORT,
                              "/camera/snap?width=4656&height=3496&timeOut=30000",
                              timeout=60)
        finally:
            self.gcode("M3S0")
            self.gcode("M5")
            self.lights(True)
        dot, _n = cal.find_dot(decode_jpeg(photo), at)
        return cal.height(dot, at)

    def autofocus(self, cal, at=None, tolerance=0.1, tries=4):
        """Move the head until the surface under ``at`` is in focus. Returns
        the Z reached; the XCS thickness is that minus 8."""
        self._json("POST", "/device/modeSwitch", {"state": "P_AUTOFOCUS"})
        try:
            for _ in range(tries):
                dz = self.measure(cal, at)
                if abs(dz) <= tolerance:
                    return self.z()
                self._goto_z(self.z() + dz)
            return self.z()
        finally:
            self._json("POST", "/device/modeSwitch", {"state": "P_IDLE"})


# ---------------------------------------------------------------------------
# Any laser job from a Gerber folder: stencil, solder mask, silkscreen
# ---------------------------------------------------------------------------

@dataclass
class LaserArt:
    """What the laser page shows and runs, whatever the job: shapes in the
    artwork frame (mm, Y up, the outline's lower-left corner at 0, 0), the
    outline, and what Align locks onto.

    ``kind`` is "stencil" (cut through, in zones), "traces" (copper traces,
    isolated by concentric rings, moat hatch, or full rubout), "mask" (open
    the solder mask over the pads: filled) or "silk" (mark the silkscreen:
    filled). ``features`` are the shapes Align looks for in a photo when the
    job's own shapes are not there yet: the drilled holes."""
    kind: str
    apertures: list
    outline: object
    mirrored: bool = False
    note: str = ""
    notes: list = None
    features: list = None
    kerf: float = 0.0
    copper: object = None
    drills: list = None
    side: str = "bottom"
    _ring_cache: dict = field(default=None, repr=False, compare=False)

    @property
    def size(self):
        x0, y0, x1, y1 = self.outline.bounds
        return x1 - x0, y1 - y0

    def warnings(self):
        return list(self.notes or [])


def drill_features(folder, mirror, outline_raw):
    """The board's drilled holes as circles in the artwork frame: mirrored and
    shifted exactly as the mask and silkscreen are (see engine/soldermask.py),
    so Align can lock onto them before anything has been lasered."""
    from shapely.affinity import scale as _scale, translate as _translate
    from shapely.geometry import Point
    from gerber2rml.loader import select_drill_holes
    holes = select_drill_holes(folder, outline_raw)
    o = outline_raw
    if mirror:
        o = _scale(o, xfact=-1, yfact=1, origin=(0, 0))
    x0, y0, _, _ = o.bounds
    out = []
    for x, y, d in holes:
        c = Point(-x if mirror else x, y).buffer(max(d, 0.3) / 2, quad_segs=8)
        out.append(_translate(c, -x0, -y0))
    return out


# ---------------------------------------------------------------------------
# Filled jobs: hatch lines inside every shape
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FillRecipe:
    """How to fill. ``lines_per_cm`` as XCS calls it (its "density");
    ``cross_hatch`` turns each pass 90 degrees from the last; ``one_way``
    draws every line the same way, as XCS's uni-directional scan."""
    power: float = 40.0
    speed: float = 800.0
    frequency: float = 30.0
    passes: int = 6
    lines_per_cm: float = 300.0
    cross_hatch: bool = True
    one_way: bool = True
    mark_outline: bool = False
    mark_power: float = 10.0

    @property
    def interval(self):
        return 10.0 / self.lines_per_cm


# sphawes/fiber-laser-pcb-fab settings.json, the presets the lab imports into XCS
SPHAWES_REMOVE_MASK = FillRecipe(power=40, speed=800, frequency=30, passes=6,
                                 lines_per_cm=300)
SPHAWES_TRACES = FillRecipe(power=100, speed=600, frequency=30, passes=10,
                            lines_per_cm=240)


def hatch(polys, interval, angle_deg=0.0, one_way=True):
    """Hatch lines filling shapely ``polys`` (bed mm), ``interval`` apart, at
    ``angle_deg``, as (start, end) segments in drawing order: line by line
    across the whole job, so the beam sweeps instead of jumping shape to shape.
    ``one_way`` keeps every line in the same direction."""
    from shapely.affinity import rotate as _rotate
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import unary_union
    shape = unary_union([p for p in polys if not p.is_empty])
    if shape.is_empty:
        return []
    c = shape.centroid
    flat = _rotate(shape, -angle_deg, origin=c)          # hatch horizontally
    x0, y0, x1, y1 = flat.bounds
    segs = []
    y = y0 + interval / 2
    flip = False
    while y < y1:
        cut = flat.intersection(LineString([(x0 - 1, y), (x1 + 1, y)]))
        parts = list(cut.geoms) if isinstance(cut, MultiLineString) else (
            [cut] if isinstance(cut, LineString) and not cut.is_empty else [])
        row = []
        for ln in parts:
            (ax, ay), (bx, by) = ln.coords[0], ln.coords[-1]
            if ax > bx:
                (ax, ay), (bx, by) = (bx, by), (ax, ay)
            row.append(((ax, ay), (bx, by)))
        row.sort(key=lambda sg: sg[0][0])
        if not one_way and flip:
            row = [(b, a) for a, b in reversed(row)]
        segs += row
        flip = not flip
        y += interval
    if not segs:
        return []
    from shapely.geometry import MultiPoint
    import math as _m
    t = _m.radians(angle_deg)
    cs, sn = _m.cos(t), _m.sin(t)

    def back(p):                                     # undo the flattening turn
        dx, dy = p[0] - c.x, p[1] - c.y
        return (c.x + dx * cs - dy * sn, c.y + dx * sn + dy * cs)
    return [(back(a), back(b)) for a, b in segs]


def fill_job(shapes, outline, recipe=SPHAWES_REMOVE_MASK, base_angle=0.0):
    """One GS002 file that fills every shape (shapely Polygons, bed mm) with
    ``recipe.passes`` hatch passes, each at right angles to the last when
    ``cross_hatch``; then, if asked, the outline marked once."""
    check_on_bed([list(p.exterior.coords) for p in shapes] + outline)
    s_val, feed = round(recipe.power * 10), round(recipe.speed * 60)
    body, secs, timeline = [], 0.0, []
    cached = {}
    for k in range(recipe.passes):
        ang = base_angle + (90.0 * (k % 2) if recipe.cross_hatch else 0.0)
        if ang not in cached:
            segs = hatch(shapes, recipe.interval, ang, recipe.one_way)
            dt = sum(math.dist(a, b) for a, b in segs) / recipe.speed
            lines_k = []
            for a, b in segs:
                lines_k.append(f"G0X{a[0]:.3f}Y{a[1]:.3f}")
                lines_k.append(f"G1X{b[0]:.3f}Y{b[1]:.3f}S{s_val}F{feed}")
            cached[ang] = (lines_k, dt)
        lines_k, dt = cached[ang]
        body += lines_k
        timeline.append((secs, secs + dt, 0, k))
        secs += dt
    if outline and recipe.mark_outline:
        body += _passes(outline, recipe.mark_power, recipe.speed, 1)
        dt = sum(_length(p) for p in outline) / recipe.speed
        timeline.append((secs, secs + dt, -1, recipe.passes))
        secs += dt
    lines = _head("fiber", recipe.frequency, recipe.power / 100) + body + _TAIL
    return Job(text="\r\n".join(lines), zones=[len(shapes)], seconds=secs,
               passes=recipe.passes, zone_paths=[shapes], timeline=timeline)


# ---------------------------------------------------------------------------
# PCB traces: FlatCAM-style concentric isolation, moat hatch, or full rubout
# ---------------------------------------------------------------------------

DEFAULT_TRACE_KERF = 0.04       # mm, fiber spot size on copper
DEFAULT_TRACE_OFFSETS = 6       # concentric rings (~0.22 mm moat at 285 l/cm)
DEFAULT_TRACE_DENSITY = 285.0   # lines/cm -> stepover ~0.035 mm

_COPPER_PATTERNS = {"bottom": ("*-B_Cu.*", "*.gbl"),
                    "top": ("*-F_Cu.*", "*.gtl")}
_COPPER_NAME = {"bottom": "B.Cu", "top": "F.Cu"}


class TracesError(ValueError):
    """Why this folder cannot give a laser traces job, in words for the operator."""


@dataclass(frozen=True)
class TracesRecipe:
    """How to isolate or clear PCB copper on the F1 Ultra.

    ``strategy``:
    - ``"concentric"`` (default): FlatCAM-style concentric offset rings around
      every trace and pad, swept round by round so heat stays spread out and
      the beam never jumps line-by-line across traces.
    - ``"moat"``: hatch only a fixed-width moat band around the copper.
    - ``"rubout"``: hatch every empty millimetre of the board (like XCS).
    """
    strategy: str = "concentric"
    power: float = 100.0
    speed: float = 600.0
    frequency: float = 30.0
    passes: int = 10
    offsets: int = DEFAULT_TRACE_OFFSETS
    kerf: float = DEFAULT_TRACE_KERF
    lines_per_cm: float = DEFAULT_TRACE_DENSITY
    rest_s: float = 0.0
    spot_drills: bool = True
    cross_hatch: bool = True
    one_way: bool = True
    mark_outline: bool = False
    mark_power: float = 10.0

    @property
    def stepover(self):
        return 10.0 / self.lines_per_cm

    @property
    def interval(self):
        return self.stepover

    @property
    def isolation_mm(self):
        return self.kerf + max(0, self.offsets - 1) * self.stepover


DEFAULT_TRACES_RECIPE = TracesRecipe()
# Proven on the lab's F1 Ultra, 2026-11-16: FR4 1.6 mm, copper isolation with
# the concentric rings. Found with the exposure grid (best cells 600 x 20,
# 1000 x 20 and 2000 x 40, the same dose window) and then run on the whole
# curtain-drive board: every net isolated, no fine trace burnt, about five
# minutes against two hours on the mill.
FR4_TRACES_RECIPE = TracesRecipe(power=100.0, speed=1000.0, frequency=30.0, passes=20)
WIDE_TRACES_RECIPE = TracesRecipe(offsets=10)
MOAT_HATCH_RECIPE = TracesRecipe(strategy="moat", lines_per_cm=240.0)
RUBOUT_TRACES_RECIPE = TracesRecipe(strategy="rubout", lines_per_cm=240.0)


def copper_layer_path(folder, side="bottom"):
    """The copper Gerber for ``side`` in ``folder``, or None."""
    from gerber2rml.loader import _find_layer
    return _find_layer(folder, *_COPPER_PATTERNS[side])


def _drill_spots(drills):
    """Union of pilot hole circles (≤ 0.5 mm dia) for spotting pads."""
    from shapely.geometry import Point
    from shapely.ops import unary_union
    if not drills:
        return None
    return unary_union([Point(x, y).buffer(min(max(d, 0.3) / 2, 0.25), quad_segs=16)
                        for x, y, d in drills])


def traces_apertures(copper, outline, drills=(), *, strategy="concentric",
                     offsets=DEFAULT_TRACE_OFFSETS, kerf=DEFAULT_TRACE_KERF,
                     lines_per_cm=DEFAULT_TRACE_DENSITY, spot_drills=True):
    """Polygons of cleared copper in the artwork frame, for preview, selection,
    DXF export, and moat/rubout hatching."""
    from gerber2rml.engine import soldermask
    if copper is None or copper.is_empty:
        return []
    spots = _drill_spots(drills) if spot_drills and drills else None
    cu = copper.difference(spots) if spots is not None else copper
    if strategy == "rubout":
        cleared = outline.difference(cu)
    else:
        step = 10.0 / lines_per_cm
        iso_w = max(kerf + max(0, offsets - 1) * step, kerf)
        cleared = cu.buffer(iso_w).intersection(outline).difference(cu)
        if spots is not None:
            cleared = cleared.union(spots.intersection(copper).intersection(outline))
    return [p for p in soldermask._polygons(cleared)
            if p.area >= soldermask._SLIVER_MM2]


OUTLINE_STROKE_TOL = 0.05       # mm: a stroke this near the outline is the outline
OUTLINE_STROKE_SHARE = 0.5      # of the outline's length, before it is believed


def copper_without_outline(layer, outline):
    """A copper Gerber's geometry with the board outline taken out of it.

    KiCad's plot option "Plot Edge.Cuts on all layers" draws the outline into
    every copper file as a thin line. Read as copper, it gets isolated like a
    track: the laser runs all the way round the board for nothing. Lines and
    arcs that lie on the outline are left out, but only when together they
    cover most of it - a stray stroke that happens to touch the edge is
    copper. Returns ``(geometry, mm of outline left out)``."""
    from gerbonara.graphic_objects import Arc, Line
    from gerbonara.utils import MM
    from shapely.geometry import LineString, Point
    from gerber2rml.engine import soldermask
    edge = outline.boundary
    keep, dropped, length = [], [], 0.0
    for obj in layer.objects:
        on = False
        if isinstance(obj, (Line, Arc)):
            o = obj.converted(MM)
            a, b = (o.x1, o.y1), (o.x2, o.y2)
            if (Point(a).distance(edge) <= OUTLINE_STROKE_TOL
                    and Point(b).distance(edge) <= OUTLINE_STROKE_TOL):
                pts = [a, b]
                if isinstance(obj, Arc):
                    try:
                        pts = [(q.x1, q.y1) for q in o.approximate(0.05, MM)] + [b]
                    except Exception:           # noqa: BLE001 - then by its ends
                        pts = [a, b]
                on = all(Point(q).distance(edge) <= OUTLINE_STROKE_TOL for q in pts)
                if on and math.dist(a, b) > 1e-9:
                    length += LineString(pts).length
        (dropped if on else keep).append(obj)
    if not dropped or length < OUTLINE_STROKE_SHARE * edge.length:
        return soldermask._layer_to_shapely(layer), 0.0

    class _Kept:
        objects = keep
    return soldermask._layer_to_shapely(_Kept), length


def build_laser_traces(folder, *, side="bottom", mirror=True,
                       offsets=DEFAULT_TRACE_OFFSETS, kerf=DEFAULT_TRACE_KERF,
                       lines_per_cm=DEFAULT_TRACE_DENSITY,
                       strategy="concentric", spot_drills=True):
    """Read one face's copper, outline, and drills from a Gerber folder into a
    :class:`LaserArt` ready for the xTool laser page or DXF export."""
    from gerbonara import GerberFile
    from gerber2rml.engine import soldermask
    from gerber2rml.loader import _find_layer, select_drill_holes

    folder = Path(folder)
    path = copper_layer_path(folder, side)
    if path is None:
        other = "top" if side == "bottom" else "bottom"
        there = copper_layer_path(folder, other)
        raise TracesError(
            f"No {_COPPER_NAME[side]} Gerber in {folder}, so there is nothing "
            f"to etch."
            + (f" There is an {_COPPER_NAME[other]} ({there.name}), which is "
               f"the other face." if there else "")
            + f" Plot {_COPPER_NAME[side]} into this folder and try again.")
    edge = _find_layer(folder, "*-Edge_Cuts.*", "*.gm1")
    if edge is None:
        raise TracesError(f"No board outline (Edge.Cuts) Gerber in {folder}.")
    outline_raw = soldermask._read_outline(edge)
    if outline_raw.is_empty:
        raise TracesError(f"{edge.name} has no outline in it.")
    copper, in_copper = copper_without_outline(GerberFile.open(str(path)),
                                               outline_raw)
    if copper.is_empty:
        raise TracesError(f"{path.name} is empty: {_COPPER_NAME[side]} has no "
                          f"copper on it.")
    notes = []
    if in_copper:
        notes.append(f"{path.name} has the board outline drawn in it (KiCad: "
                     f"Edge.Cuts plotted on all layers). It is left out, so "
                     f"the laser does not go round the board's edge.")
    try:
        raw_drills = select_drill_holes(folder, outline_raw)
    except Exception:
        raw_drills = []
    return traces_art(copper, outline_raw, raw_drills, side=side, mirror=mirror,
                      notes=notes, offsets=offsets, kerf=kerf,
                      lines_per_cm=lines_per_cm, strategy=strategy,
                      spot_drills=spot_drills)


def traces_art(copper, outline_raw, raw_drills, *, side="bottom", mirror=True,
               notes=None, offsets=DEFAULT_TRACE_OFFSETS,
               kerf=DEFAULT_TRACE_KERF, lines_per_cm=DEFAULT_TRACE_DENSITY,
               strategy="concentric", spot_drills=True):
    """Copper, outline and drills as drawn (mm, Y up, any origin) into a
    traces :class:`LaserArt`: mirrored if asked, the outline's lower-left
    corner moved to 0, 0. A Gerber folder and a DXF both end here."""
    from shapely.affinity import scale, translate
    notes = list(notes or [])
    outline = outline_raw
    if mirror:
        outline = scale(outline, xfact=-1, yfact=1, origin=(0, 0))
        copper = scale(copper, xfact=-1, yfact=1, origin=(0, 0))
    x0, y0, _, _ = outline.bounds
    outline = translate(outline, -x0, -y0)
    copper = translate(copper, -x0, -y0).intersection(outline)

    drills = [((-x if mirror else x) - x0, y - y0, d) for x, y, d in raw_drills]
    from shapely.geometry import Point
    features = [Point(x, y).buffer(max(d, 0.3) / 2, quad_segs=8)
                for x, y, d in drills]
    apertures = traces_apertures(
        copper, outline, drills, strategy=strategy, offsets=offsets,
        kerf=kerf, lines_per_cm=lines_per_cm, spot_drills=spot_drills)
    if strategy == "rubout":
        note = "full rubout"
    else:
        iso_mm = kerf + max(0, offsets - 1) * (10.0 / lines_per_cm)
        note = f"{offsets} passes ({iso_mm:.2f} mm gap)"
    return LaserArt(kind="traces", apertures=apertures, outline=outline,
                    mirrored=mirror, note=note, notes=notes, features=features,
                    kerf=kerf, copper=copper, drills=drills, side=side)


def traces_filename(art, name):
    state = "mirrored" if art.mirrored else "not_mirrored"
    return f"{name}_traces_{art.side}_{state}.dxf"


def write_traces_dxf(art, out_dir, name):
    from gerber2rml.engine import soldermask
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / traces_filename(art, name)
    path.write_text(
        soldermask.shapes_dxf_text(art.apertures, art.outline,
                                   soldermask.LAYER_TRACES),
        encoding="ascii")
    return path


EDGE_RING_MM = 0.02     # an isolation pass this near the board's edge is on it


def _clip_ring_to(coords, clip):
    """Closed ring coordinate list clipped to ``clip`` (artwork frame)."""
    from shapely.geometry import LineString, MultiLineString
    if clip is None:
        return [coords]
    line = LineString(coords)
    if line.is_empty:
        return []
    if clip.contains(line):
        return [coords]
    if not line.intersects(clip):
        return []
    cut = line.intersection(clip)
    parts = list(cut.geoms) if isinstance(cut, MultiLineString) else (
        [cut] if isinstance(cut, LineString) else [])
    return [list(p.coords) for p in parts if not p.is_empty and p.length > 1e-4]


def boxes_region(boxes):
    """Rework boxes ``[(x0, y0, x1, y1), ...]`` (bed mm, any corner order)
    as one shapely geometry on the bed, or None when there are none."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    shapes = [box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
              for x0, y0, x1, y1 in (boxes or ())
              if abs(x1 - x0) > 1e-6 and abs(y1 - y0) > 1e-6]
    return unary_union(shapes) if shapes else None


def _boxes_in_art(boxes, origin, height):
    """Bed boxes in the artwork frame (Y up), as :func:`to_bed` inverted."""
    ox, oy = origin
    return [(x0 - ox, height - (y0 - oy), x1 - ox, height - (y1 - oy))
            for x0, y0, x1, y1 in boxes]


def traces_rings(art, origin, recipe=DEFAULT_TRACES_RECIPE, only=None,
                 boxes=None):
    """Concentric isolation rings per offset, in bed coordinates, ordered by
    nearest neighbour. Cached in the artwork frame so dragging or tweaking
    power/speed/passes stays instantaneous. ``boxes`` (bed mm) keeps only
    what lies inside them: a rework of the spots that did not cut through."""
    from shapely.geometry import Point
    from shapely.ops import unary_union
    from gerber2rml.engine import soldermask

    if art.copper is None or art.copper.is_empty:
        _, outline = stencil_paths(art, origin)
        return [], outline

    only_key = frozenset(only) if only else None
    _, h_art = art.size
    art_boxes = (tuple(tuple(round(v, 4) for v in b)
                       for b in _boxes_in_art(boxes, origin, h_art))
                 if boxes else None)
    key = (recipe.offsets, round(recipe.kerf, 4), round(recipe.lines_per_cm, 2),
           bool(recipe.spot_drills), only_key, art_boxes)
    cache = art._ring_cache
    if cache is None:
        cache = {}
        art._ring_cache = cache

    if key not in cache:
        spots = (_drill_spots(art.drills)
                 if recipe.spot_drills and art.drills else None)
        cu = art.copper.difference(spots) if spots is not None else art.copper
        clip = None
        if only_key:
            sel = [art.apertures[k] for k in only_key
                   if 0 <= k < len(art.apertures)]
            if sel:
                clip = unary_union(sel).buffer(recipe.stepover * 1.5)
        if art_boxes:
            region = boxes_region(art_boxes)
            if region is None:
                cache[key] = []
            else:
                clip = region if clip is None else clip.intersection(region)
        # Where copper reaches the board's edge, the grown shape is cut off
        # by the outline and its ring would follow the edge. There is nothing
        # past the edge to isolate from, so that part is not drawn.
        from shapely.geometry import LineString
        inside = art.outline.buffer(-EDGE_RING_MM)
        edge = art.outline.boundary

        def kept(coords):
            parts = _clip_ring_to(coords, clip)
            out = []
            for part in parts:
                if LineString(part).distance(edge) > EDGE_RING_MM:
                    out.append(part)            # nowhere near the edge
                else:
                    out += _clip_ring_to(part, inside)
            return out
        groups = []
        for i in (range(recipe.offsets) if key not in cache else ()):
            d_i = recipe.kerf / 2 + i * recipe.stepover
            grown = cu.buffer(d_i).intersection(art.outline)
            rings = []
            for poly in soldermask._polygons(grown):
                rings += kept(list(poly.exterior.coords))
                for intr in poly.interiors:
                    rings += kept(list(intr.coords))
            if rings:
                groups.append(_nearest_order(rings))
        cache.setdefault(key, groups)

    _, h = art.size
    bed_groups = [[to_bed(rg, origin, h) for rg in grp] for grp in cache[key]]
    outline = [to_bed(list(r.coords), origin, h)
               for r in (art.outline.exterior, *art.outline.interiors)]
    return bed_groups, outline


def traces_job(art, origin, recipe=DEFAULT_TRACES_RECIPE, only=None,
               boxes=None):
    """One GS002 file to etch PCB copper traces on the F1 Ultra.

    ``boxes`` (bed mm): a rework. Only the passes inside the boxes are run,
    as the CNC's rework clips its pass, and the outline is not scored again."""
    from dataclasses import replace as _replace
    from shapely.geometry import Polygon
    region = None
    if boxes:
        region = boxes_region(boxes)
        if region is None:
            raise ValueError("Draw a rework box over the traces first.")
        recipe = _replace(recipe, mark_outline=False)

    if recipe.strategy in ("moat", "rubout"):
        _, h = art.size
        pick = only or None
        shapes = []
        for k, poly in enumerate(art.apertures):
            if pick is not None and k not in pick:
                continue
            shape = Polygon(to_bed(list(poly.exterior.coords), origin, h),
                            [to_bed(list(r.coords), origin, h)
                             for r in poly.interiors])
            if region is not None:
                from gerber2rml.engine import soldermask
                shapes += soldermask._polygons(shape.intersection(region))
            else:
                shapes.append(shape)
        if region is not None and not shapes:
            raise ValueError("No isolation inside the rework boxes.")
        _, outline = stencil_paths(art, origin)
        fill_r = FillRecipe(
            power=recipe.power, speed=recipe.speed, frequency=recipe.frequency,
            passes=recipe.passes, lines_per_cm=recipe.lines_per_cm,
            cross_hatch=recipe.cross_hatch, one_way=recipe.one_way,
            mark_outline=recipe.mark_outline, mark_power=recipe.mark_power)
        return fill_job(shapes, outline, fill_r)

    groups, outline = traces_rings(art, origin, recipe, only=only, boxes=boxes)
    all_rings = [rg for grp in groups for rg in grp]
    if region is not None and not all_rings:
        raise ValueError("No isolation inside the rework boxes.")
    check_on_bed(all_rings + outline)
    park = min(((x, y) for p in outline for x, y in p), key=lambda q: q[0] + q[1])
    body, secs, timeline = [], 0.0, []
    for rnd in range(recipe.passes):
        order = groups if rnd % 2 == 0 else list(reversed(groups))
        round_rings = [rg for grp in order for rg in grp]
        body += _passes(round_rings, recipe.power, recipe.speed, 1)
        dt = sum(_length(p) for p in round_rings) / recipe.speed
        timeline.append((secs, secs + dt, 0, rnd))
        secs += dt
        if rnd < recipe.passes - 1 and recipe.rest_s > 0:
            body += _rest(park, recipe.rest_s)
            secs += recipe.rest_s
    if outline and recipe.mark_outline:
        body += _passes(outline, recipe.mark_power, recipe.speed, 1)
        dt = sum(_length(p) for p in outline) / recipe.speed
        timeline.append((secs, secs + dt, -1, recipe.passes))
        secs += dt
    lines = _head("fiber", recipe.frequency, recipe.power / 100) + body + _TAIL
    return Job(text="\r\n".join(lines), zones=[len(all_rings)], seconds=secs,
               passes=recipe.passes, zone_paths=[all_rings], timeline=timeline)


# ---------------------------------------------------------------------------
# Proof: a few faint marks next to the drilled holes, before the real job
# ---------------------------------------------------------------------------

PROOF_RADIUS = 2.5      # mm round a hole: how much of its isolation is marked
PROOF_PASSES = 3
PROOF_WASTE_MARGIN = 3.0
PROOF_WASTE_SIZE = 1.5


@dataclass
class Proof:
    """Marks for the laser to make so a photo can show where it really fires.
    ``paths`` are what it draws and ``marks`` the areas that should change in
    the photo, both on the bed. ``where`` is "isolation" (copper the job
    removes anyway) or "waste" (the sheet beside the board). ``inside`` are
    points on the board matching the waste marks, for judging the sheet."""
    where: str
    paths: list
    marks: list
    inside: list = None

    @property
    def spots(self):
        return [(m.centroid.x, m.centroid.y) for m in self.marks]


def spread(points, n=3):
    """Up to ``n`` indices into ``points`` that lie far apart: the two
    farthest, then whichever is farthest from those already picked."""
    pts = [tuple(p[:2]) for p in points]
    if len(pts) <= n:
        return list(range(len(pts)))
    best = max(((math.dist(a, b), i, j) for i, a in enumerate(pts)
                for j, b in enumerate(pts) if i < j))
    picked = [best[1], best[2]]
    while len(picked) < n:
        k = max((i for i in range(len(pts)) if i not in picked),
                key=lambda i: min(math.dist(pts[i], pts[j]) for j in picked))
        picked.append(k)
    return picked


def _drills_on_bed(art, origin):
    _, h = art.size
    return [to_bed([(x, y)], origin, h)[0] for x, y, _d in (art.drills or [])]


def _isolation_anchors(art, origin, recipe, step=2.0):
    """Points along the first isolation ring every ``step`` mm, on the bed:
    where marks can go on a board with no holes yet."""
    groups, _ = traces_rings(art, origin, recipe)
    out = []
    for ring in (groups[0] if groups else []):
        run = 0.0
        for a, b in zip(ring, ring[1:]):
            run += math.dist(a, b)
            if run >= step:
                out.append(b)
                run = 0.0
    return out


def proof_on_isolation(art, origin, recipe=None, *, radius=PROOF_RADIUS, n=3):
    """Marks on copper the traces job removes anyway: the isolation rings
    within ``radius`` of up to ``n`` drilled holes that lie far apart, or on
    a blank with no holes, of points far apart along the isolation."""
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    recipe = recipe or DEFAULT_TRACES_RECIPE
    centres = _drills_on_bed(art, origin)
    if len(centres) < 2:
        centres = _isolation_anchors(art, origin, recipe)
    if len(centres) < 2:
        raise ValueError("There is no isolation on this job to mark.")
    _, h = art.size
    cleared = unary_union([
        Polygon(to_bed(list(p.exterior.coords), origin, h),
                [to_bed(list(r.coords), origin, h) for r in p.interiors])
        for p in art.apertures]).buffer(0)
    bands = {}
    for i, c in enumerate(centres):
        band = cleared.intersection(Point(c).buffer(radius, quad_segs=16))
        if not band.is_empty and band.area > 0.05:
            bands[i] = band
    if len(bands) < 2:
        raise ValueError("Fewer than two places on the job have isolation "
                         "round them, so there is nothing to mark there.")
    keys = list(bands)
    keys = [keys[k] for k in spread([centres[i] for i in keys], n)]
    discs = unary_union([Point(centres[i]).buffer(radius, quad_segs=16) for i in keys])
    groups, _ = traces_rings(art, origin, recipe)
    bx0, by0, bx1, by1 = discs.bounds
    paths = []
    for grp in groups:
        for ring in grp:
            xs, ys = [q[0] for q in ring], [q[1] for q in ring]
            if max(xs) < bx0 or min(xs) > bx1 or max(ys) < by0 or min(ys) > by1:
                continue
            paths += _clip_ring_to(ring, discs)
    if not paths:
        raise ValueError("No isolation passes fall where the marks would go.")
    return Proof("isolation", paths, [bands[i] for i in keys])


def proof_in_waste(art, origin, recipe=None, *, margin=PROOF_WASTE_MARGIN,
                   size=PROOF_WASTE_SIZE, n=3):
    """Small filled squares in the sheet beside the board, ``margin`` outside
    its outline, next to up to ``n`` drilled holes that lie far apart (or the
    outline's corners on a board without holes)."""
    from shapely.geometry import Point, Polygon, box
    recipe = recipe or DEFAULT_TRACES_RECIPE
    _, h = art.size
    outline = Polygon(to_bed(list(art.outline.exterior.coords), origin, h)).buffer(0)
    near = _drills_on_bed(art, origin)
    if len(near) < 2:
        x0, y0, x1, y1 = outline.bounds
        near = [(x0, y0), (x1, y1), (x0, y1), (x1, y0)]
    near = [near[k] for k in spread(near, n)]
    lane = outline.buffer(margin + size / 2).exterior
    edge = outline.exterior
    marks, inside, paths = [], [], []
    step = max(recipe.stepover, 0.02)
    for c in near:
        q = lane.interpolate(lane.project(Point(c)))
        if any(q.distance(m.centroid) < 3 * size for m in marks):
            continue
        sq = box(q.x - size / 2, q.y - size / 2, q.x + size / 2, q.y + size / 2)
        e = edge.interpolate(edge.project(q))
        d = math.dist((q.x, q.y), (e.x, e.y)) or 1.0
        back = margin + size / 2            # as far inside the edge as outside
        inside.append((e.x + (e.x - q.x) / d * back, e.y + (e.y - q.y) / d * back))
        marks.append(sq)
        y, flip = q.y - size / 2, False
        while y <= q.y + size / 2 + 1e-9:
            a, b = (q.x - size / 2, y), (q.x + size / 2, y)
            paths.append([b, a] if flip else [a, b])
            y, flip = y + step, not flip
    if len(marks) < 2:
        raise ValueError("There is no room for two proof marks beside the board.")
    check_on_bed(paths)
    return Proof("waste", paths, marks, inside)


CALIBRATION_AREA = (40.0, 30.0)     # mm: the page's area with no job loaded
PROOF_AREA_INSET = 3.0


def calibration_art():
    """The laser page with nothing loaded: an empty 40 x 30 mm area to drag
    onto the material, where the camera calibration makes its marks."""
    from shapely.geometry import Polygon, box
    w, h = CALIBRATION_AREA
    return LaserArt(kind="traces", apertures=[], outline=box(0, 0, w, h),
                    note="calibration area", copper=Polygon(), drills=[],
                    features=[], side="top")


def proof_in_area(art, origin, recipe=None, *, inset=PROOF_AREA_INSET,
                  size=PROOF_WASTE_SIZE, n=3):
    """Small filled squares inside the outline, ``inset`` from three of its
    corners: the marks for a calibration with no job, on the material the
    area was dragged onto."""
    from shapely.geometry import Polygon, box
    recipe = recipe or DEFAULT_TRACES_RECIPE
    _, h = art.size
    outline = Polygon(to_bed(list(art.outline.exterior.coords), origin, h)).buffer(0)
    x0, y0, x1, y1 = outline.bounds
    d = inset + size / 2
    corners = [(x0 + d, y0 + d), (x1 - d, y1 - d), (x0 + d, y1 - d), (x1 - d, y0 + d)]
    corners = [corners[k] for k in spread(corners, n)]
    marks, paths = [], []
    step = max(recipe.stepover, 0.02)
    for cx, cy in corners:
        marks.append(box(cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2))
        y, flip = cy - size / 2, False
        while y <= cy + size / 2 + 1e-9:
            a, b = (cx - size / 2, y), (cx + size / 2, y)
            paths.append([b, a] if flip else [a, b])
            y, flip = y + step, not flip
    check_on_bed(paths)
    return Proof("area", paths, marks)


def proof_job(proof, recipe=None, passes=PROOF_PASSES):
    """The GS002 file that makes a proof's marks, and how long it takes."""
    recipe = recipe or DEFAULT_TRACES_RECIPE
    check_on_bed(proof.paths)
    passes = max(1, int(passes))
    lines = (_head("fiber", recipe.frequency, recipe.power / 100)
             + _passes(proof.paths, recipe.power, recipe.speed, passes) + _TAIL)
    secs = passes * sum(_length(p) for p in proof.paths) / recipe.speed
    return "\r\n".join(lines), secs
