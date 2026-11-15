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
from dataclasses import dataclass, replace

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


def stencil_paths(art, origin):
    """(holes, outline) as closed point lists on the bed."""
    _, h = art.size
    holes = []
    for poly in art.apertures:
        for ring in (poly.exterior, *poly.interiors):
            holes.append(to_bed(list(ring.coords), origin, h))
    outline = [to_bed(list(r.coords), origin, h)
               for r in (art.outline.exterior, *art.outline.interiors)]
    return holes, outline


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
    out = []
    for _ in range(n):
        for p in paths:
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


def stencil_job(holes, outline, recipe=DEFAULT_RECIPE):
    """One GS002 file: every zone ``recipe.rounds`` times with rests, then the
    outline marked."""
    check_on_bed(holes + outline)
    zs = zones(holes, recipe.zones)
    park = min(((x, y) for p in outline for x, y in p), key=lambda q: q[0] + q[1])
    body, secs = [], 0.0
    bursts = [(r, z) for r in range(recipe.rounds) for z in zs]
    for i, (r, z) in enumerate(bursts):
        n = min(recipe.passes_per_burst,
                recipe.total_passes - r * recipe.passes_per_burst)
        body += _passes(z, recipe.power, recipe.speed, n)
        secs += n * sum(_length(p) for p in z) / recipe.speed
        if i < len(bursts) - 1 and recipe.rest_s > 0:
            body += _rest(park, recipe.rest_s)
            secs += recipe.rest_s
    if outline and recipe.mark_passes:
        body += _passes(outline, recipe.mark_power, recipe.speed, recipe.mark_passes)
        secs += recipe.mark_passes * sum(_length(p) for p in outline) / recipe.speed
    lines = _head("fiber", recipe.frequency, recipe.power / 100) + body + _TAIL
    return Job(text="\r\n".join(lines), zones=[len(z) for z in zs],
               seconds=secs, passes=recipe.total_passes)


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
