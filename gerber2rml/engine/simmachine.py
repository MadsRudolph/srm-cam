"""A simulated SRM-20: the Arduino link and the printer, against a virtual bed.

The autonomous run is a machine program. Until it has run on a machine it
has only been read, and the machine is not always there. This is the machine
when it is not: a serial object that speaks the firmware's line protocol
(``hardware/srm20_spi_probe``) and a printer that runs RML, sharing one
virtual bed with a taped stock on it.

The stock is real enough to find. It is a rotated rectangle of copper at a
known height with a little bow in it; a probe that touches it reads LOW,
anywhere else reads nothing. Cuts are remembered: a drill or cut-out that
goes through leaves a hole on both faces, a trace cut removes copper on the
face it cut. ``flip()`` turns the stock over (left-right) and puts it back a
little off where it was, the way hands do. So fiducials drilled in the first
half are holes the second half has to find.

Open it with the port name ``SIM`` - :func:`gerber2rml.engine.spi_probe.
open_link` hands back :func:`serial_for` instead of a pyserial port - and
the spooler side with :func:`printer`. One machine per process.

Units are machine microns, Z up, the head's home at Z 0, as the firmware's.
"""
import math
import re
import threading
import time

SIM_PORT = "SIM"
BIT_R = 400                      # the one bit: 0.8 mm
MOVING, SPINDLE, COVER = 0x800, 0x10000, 0x20000


def is_sim(port):
    return str(port or "").upper().startswith(SIM_PORT)


class Machine:
    """The bed, the stock, the head, and what has been cut."""

    def __init__(self, corner=(41300, 27800), angle_deg=1.2,
                 size=(100000, 80000), surface_z=-43300, bow_um=40,
                 speedup=40.0):
        self.lock = threading.RLock()
        self.pos = [0, 0, 0]
        self.origin = [0, 0, 0]
        self.speedup = speedup
        self.corner = list(corner)
        self.angle = math.radians(angle_deg)
        self.w, self.h = size
        self.surface_z = surface_z
        self.bow = bow_um
        self.face = 0                    # 0 = first side up, 1 = flipped
        self.cuts = {}                   # (cu, cv) -> [(u, v, r, faces)]
        self.spindle = 0
        self.halt = threading.Event()
        self.moving = False
        self.lines = []                  # [(faces, [(bu, bv), ...])] as cut
        self._line = None
        self.version = 0                 # bumps on every change worth redrawing
        self.found = None                # the stock as the probe found it

    # -- geometry ------------------------------------------------------------
    def to_stock(self, x, y):
        """Machine (x, y) -> stock (u, v), as seen from above now."""
        dx, dy = x - self.corner[0], y - self.corner[1]
        c, s = math.cos(self.angle), math.sin(self.angle)
        return dx * c + dy * s, -dx * s + dy * c

    def _board(self, u, v):
        """Stock-from-above (u, v) -> the board's own frame (first side up)."""
        return (self.w - u, v) if self.face else (u, v)

    def surface(self, x, y):
        """Copper height under (x, y), or None where there is no copper."""
        u, v = self.to_stock(x, y)
        if not (0 <= u <= self.w and 0 <= v <= self.h):
            return None
        bu, bv = self._board(u, v)
        if self._cut(bu, bv, self.face):
            return None
        fx, fy = u / self.w - 0.5, v / self.h - 0.5
        return int(self.surface_z + self.bow * (1 - 4 * (fx * fx + fy * fy)))

    def _cut(self, bu, bv, face):
        cu, cv = int(bu // 200), int(bv // 200)
        for du in (-3, -2, -1, 0, 1, 2, 3):
            for dv in (-3, -2, -1, 0, 1, 2, 3):
                for (u, v, r, faces) in self.cuts.get((cu + du, cv + dv), ()):
                    if face in faces and (bu - u) ** 2 + (bv - v) ** 2 < r * r:
                        return True
        return False

    def under_bit(self, x, y, r=BIT_R):
        """The highest copper anywhere under a flat bit of radius ``r``
        centred on (x, y) - a bit touches with its whole end, not a point."""
        best = None
        for k in range(9):
            if k == 0:
                px, py = x, y
            else:
                a = (k - 1) * math.pi / 4
                px, py = x + r * math.cos(a), y + r * math.sin(a)
            s = self.surface(px, py)
            if s is not None and (best is None or s > best):
                best = s
        return best

    def touching(self):
        s = self.under_bit(self.pos[0], self.pos[1])
        return s is not None and self.pos[2] <= s

    def record_cut(self, x, y, z):
        s = self.surface(x, y)
        u, v = self.to_stock(x, y)
        if not (0 <= u <= self.w and 0 <= v <= self.h):
            return
        top = s if s is not None else self.surface_z
        depth = top - z
        if depth < 30:
            return
        faces = (0, 1) if depth > 1500 else (self.face,)
        bu, bv = self._board(u, v)
        self.cuts.setdefault((int(bu // 200), int(bv // 200)), []).append(
            (bu, bv, BIT_R, faces))
        if self._line is not None and self._line[0] == faces:
            self._line[1].append((bu, bv))
        else:
            self._line = (faces, [(bu, bv)])
            self.lines.append(self._line)
        self.version += 1

    def to_machine(self, u, v):
        """Stock-from-above (u, v) um -> machine (x, y) um."""
        c, s = math.cos(self.angle), math.sin(self.angle)
        return (self.corner[0] + u * c - v * s, self.corner[1] + u * s + v * c)

    def view(self):
        """Everything the stage draws, in machine mm (see Stage.set_sim)."""
        with self.lock:
            def mm(bu, bv):
                u = self.w - bu if self.face else bu
                x, y = self.to_machine(u, bv)
                return (x / 1000.0, y / 1000.0)
            cuts, under = [], []
            for faces, pts in self.lines:
                line = [mm(*p) for p in pts]
                (cuts if self.face in faces else under).append(line)
            stock = [tuple(c / 1000.0 for c in self.to_machine(u, v))
                     for u, v in ((0, 0), (self.w, 0), (self.w, self.h),
                                  (0, self.h))]
            return {"stock": stock, "cuts": cuts, "under": under,
                    "width": BIT_R * 2 / 1000.0, "found": self.found}

    def flip(self, shift=(450, -300), turn_deg=0.35):
        """Turn the stock over left-right and put it back slightly off."""
        with self.lock:
            self.face ^= 1
            self._line = None
            self.version += 1
            self.corner[0] += shift[0]
            self.corner[1] += shift[1]
            self.angle += math.radians(turn_deg)

    # -- motion --------------------------------------------------------------
    def move_to(self, x, y, z, speed_mm_s=15.0):
        """Travel at speed (scaled by ``speedup``), cutting what it passes."""
        with self.lock:
            x0, y0, z0 = self.pos
        d = math.dist((x0, y0, z0), (x, y, z))
        steps = max(1, int(d // 200))
        dt = (d / 1000.0) / max(speed_mm_s, 0.1) / self.speedup / steps
        for i in range(1, steps + 1):
            if self.halt.is_set():
                return False
            t = i / steps
            p = (x0 + (x - x0) * t, y0 + (y - y0) * t, z0 + (z - z0) * t)
            with self.lock:
                self.pos = [int(p[0]), int(p[1]), int(p[2])]
                n = self.version
                if self.spindle:
                    self.record_cut(*self.pos)
                if self.version == n:
                    self._line = None
            if dt > 0.0005:
                time.sleep(dt)
        return True


_MACHINE = None


def machine(**kw):
    """The process's simulated machine (created on first use)."""
    global _MACHINE
    if _MACHINE is None or kw:
        _MACHINE = Machine(**kw)
    return _MACHINE


# ---------------------------------------------------------------------------
class SimSerial:
    """The Arduino, as far as :mod:`spi_probe` can tell."""

    PROBE_DROP = 6000
    APPROACH = 1000
    HOLE_CLEAR = 400

    def __init__(self, m):
        self.m = m
        self._out = []
        self._buf = b""
        self.datum = None
        self.safe_z = 0
        self.ref = None              # reference surface Z
        self.max_surface = None
        self.abort = False
        self.closed = False

    # pyserial surface
    def write(self, data):
        self._buf += data
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            self._handle(line.decode("ascii", "replace").strip())
        return len(data)

    def readline(self):
        if self._out:
            return (self._out.pop(0) + "\n").encode()
        time.sleep(0.002)
        return b""

    def reset_input_buffer(self):
        self._out.clear()

    def flush(self):
        pass

    def close(self):
        self.closed = True

    # firmware
    def _say(self, s):
        self._out.append(s)

    def _approach(self):
        if self.max_surface is None:
            return self.safe_z
        return min(self.safe_z, self.max_surface + self.APPROACH)

    def _descend(self, x, y, start, floor):
        """Contact Z on the way down from ``start`` to ``floor``, or None."""
        m = self.m
        if not m.move_to(x, y, start):
            return None
        s = m.under_bit(x, y)
        if s is not None and floor <= s <= start:
            m.move_to(x, y, s, 5.0)
            return s
        m.move_to(x, y, floor, 5.0)
        return None

    def _handle(self, s):
        if not s:
            return
        m, c = self.m, s[0]
        args = [int(v) for v in re.findall(r"-?\d+", s[1:])]
        x, y, z = m.pos
        if c in "!%K":
            m.halt.set()
            m.spindle = 0
            self.abort = True
            if c == "!":
                m.halt.clear()
                m.move_to(m.pos[0], m.pos[1], self.safe_z)
                m.halt.set()
            else:
                self._say(f"{c} ok")
            return
        if c not in "QXVG?":
            m.halt.clear()
        if c == "V":
            self._say("V 4 probe,refine,verify,retouch,zeroz,touchbit,stream,"
                      "holetest,status,spindle,jobctl,view,timedmove,guard,"
                      "info,frame,origin,liftfix")
        elif c == "Q":
            self._say(f"Q {x} {y} {z} {1 if m.touching() else 0}")
        elif c == "X":
            sys_word = (MOVING if m.moving else 0) | (SPINDLE if m.spindle else 0)
            self._say(f"X {sys_word} 0 {m.spindle}")
        elif c == "D":
            self.datum, self.safe_z, self.ref = (x, y), z, None
            self.max_surface = None
            self._say(f"D {x} {y} {z}")
        elif c == "Z":
            self.safe_z = args[0]
        elif c == "G":
            self._say("G %d %d %d" % tuple(m.origin))
        elif c == "O":
            if len(args) < 3 or args[2] > 0:
                self._say("E O RANGE")
                return
            m.origin = args[:3]
            self._say("O %d %d %d" % tuple(m.origin))
        elif c == "S":
            rpm = max(0, min(7000, args[0] if args else 0))
            if rpm and m.touching():
                self._say("E S LOW")
                return
            m.spindle = rpm
            self._say(f"S {rpm}")
        elif c == "L":
            m.move_to(x, y, self.safe_z)
            self._say("# lifted")
        elif c == "J":
            jz = min(0, z + 5000)
            m.move_to(x, y, jz)
            m.move_to(args[0], args[1], jz)
            self._say(f"J {args[0]} {args[1]}")
        elif c == "Y":
            m.move_to(x, y, 0)
            m.move_to(x, 140000, 0)
            self._say("Y ok")
        elif c in "TW":
            if m.touching():
                self._say(f"E {c} LOW")
                return
            tz = self._descend(x, y, z, z - self.PROBE_DROP)
            if tz is None:
                m.move_to(x, y, z)
                self._say(f"E {c} NOTOUCH")
                return
            if c == "T":
                self._say(f"T {x} {y} {tz}")
                return
            m.origin = [m.origin[0], m.origin[1], tz]
            m.move_to(x, y, tz + 2000)
            self._say("W %d %d %d" % tuple(m.origin))
        elif c == "P":
            pid, dx, dy = args[:3]
            if self.datum is None:
                self._say(f"E {pid} NODATUM")
                return
            if m.touching():
                self._say(f"E {pid} LOW")
                return
            px, py = self.datum[0] + dx, self.datum[1] + dy
            floor = self.safe_z - self.PROBE_DROP
            if self.ref is not None:
                floor = max(floor, self.ref - 1200)
            tz = self._descend(px, py, self._approach(), floor)
            if tz is None:
                m.move_to(px, py, self.safe_z)
                self._say(f"E {pid} NOTOUCH")
                return
            if self.ref is None:
                self.ref = self.max_surface = tz
            self.max_surface = max(self.max_surface, tz)
            m.move_to(px, py, self._approach())
            self._say(f"R {pid} {dx} {dy} {tz}")
        elif c == "B":
            if self.datum is None:
                self._say("E B NODATUM")
                return
            tz = self._descend(*self.datum, self._approach(),
                               self.safe_z - self.PROBE_DROP)
            self._say(f"B {tz}" if tz is not None else "E B NOTOUCH")
        elif c == "H":
            if self.ref is None:
                self._say("E H NOREF")
                return
            hx, hy = args[:2]
            start = min(self.ref + self.HOLE_CLEAR, self._approach())
            tz = self._descend(hx, hy, start, self.ref - 200)
            m.move_to(hx, hy, start)
            self._say("H 1" if tz is not None else "H 0")
        elif c == "C":
            self._say("C %d %d %d" % tuple(m.origin))
        elif c == "M":
            ox, oy, oz = m.origin
            m.move_to(ox + args[0], oy + args[1], min(0, oz + args[2]))
            self._say(f"M {args[0]} {args[1]} {args[2]}")
        elif c in "~^":
            self._say(f"{c} ok")
        elif c == "F":
            self._say(f"F {args[0] if args else 500}")
        elif c == "A":
            self._say("A 1")
        elif c == "I":
            self._say("I 256")
        elif c == "N":
            dx, dy, dz = (args + [0, 0, 0])[:3]
            m.move_to(x + dx, y + dy, min(0, z + dz))
            self._say(f"N 100 {abs(dx) + abs(dy) + abs(dz)} -1 "
                      "%d %d %d" % tuple(m.pos))


def serial_for(port):
    return SimSerial(machine())


# ---------------------------------------------------------------------------
class SimPrinter:
    """The spooler and the machine running RML, as :mod:`rmlspool` sees it."""

    def __init__(self, m=None):
        self.m = m or machine()
        self._jobs = []
        self._lock = threading.Lock()
        self._worker = None
        self.sent = []               # (name, text) of every job, for tests

    def send(self, data, name="SRM-CAM job"):
        text = data.decode("ascii") if isinstance(data, bytes) else data
        with self._lock:
            self._jobs.append((name, text))
            self.sent.append((name, text))
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, daemon=True,
                                                name="sim-printer")
                self._worker.start()
        return len(self.sent)

    def pending(self):
        with self._lock:
            return len(self._jobs)

    def purge(self):
        with self._lock:
            self._jobs.clear()
        self.m.halt.set()
        return True

    def wait(self, timeout=60.0):
        """Tests: block until the queue is empty."""
        t0 = time.monotonic()
        while self.pending() and time.monotonic() - t0 < timeout:
            time.sleep(0.01)
        return not self.pending()

    def _run(self):
        while True:
            with self._lock:
                if not self._jobs:
                    return
                _name, text = self._jobs[0]
            self.m.halt.clear()
            self.m.moving = True
            try:
                run_rml(self.m, text)
            finally:
                self.m.moving = False
                with self._lock:
                    if self._jobs and self._jobs[0][1] is text:
                        self._jobs.pop(0)


def run_rml(m, text):
    """Execute RML-1 the way the machine would, against ``m``."""
    ox, oy, oz = m.origin
    up = 0
    feed = 15.0
    for cmd in re.split(r";\s*", text.replace("\n", "")):
        if m.halt.is_set():
            m.spindle = 0
            return False
        if not cmd:
            continue
        if cmd.startswith("^IN"):
            continue
        if cmd.startswith("!MC"):
            m.spindle = 7000 if cmd[3:4] == "1" else 0
        elif cmd.startswith("!PZ"):
            up = int(cmd[3:].split(",")[1])
        elif cmd.startswith("VS"):
            feed = float(cmd[2:])
        elif cmd.startswith("PU"):
            x, y = (int(v) for v in cmd[2:].split(","))
            if not m.move_to(m.pos[0], m.pos[1], min(0, oz + up * 10), feed):
                return False
            if not m.move_to(ox + x * 10, oy + y * 10, min(0, oz + up * 10), feed):
                return False
        elif cmd.startswith("Z"):
            x, y, z = (int(v) for v in cmd[1:].split(","))
            if not m.move_to(ox + x * 10, oy + y * 10, min(0, oz + z * 10), feed):
                return False
    m.spindle = 0
    return True


_PRINTER = None


def printer():
    global _PRINTER
    if _PRINTER is None or _PRINTER.m is not machine():
        _PRINTER = SimPrinter(machine())
    return _PRINTER
