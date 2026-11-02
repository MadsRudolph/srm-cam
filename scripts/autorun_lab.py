"""The machine experiments Automatic mode depends on (E1-E5).

Automatic mode sends RML straight to the "Roland SRM-20" printer, with no
VPanel, and trusts the origin set over SPI. Nothing proves either of those on
the real machine yet. Each test below answers one question. Spindle OFF, XY air
moves only: the test origin's Z is wherever the head is now (put it at the
top first), so RML Z 0 is "stay at this height".

    python scripts/autorun_lab.py state            # read-only
    python scripts/autorun_lab.py e1e2             # print + origin + ^IN
    python scripts/autorun_lab.py e4               # STOP mid-job

| Test | Question |
|---|---|
| E1 | Does RML sent RAW to the printer move the machine with VPanel closed? |
| E2 | Does RML obey the origin set with SPI ``O``? |
| E3 | What do status / spooler show while it runs, and when it ends? (trace) |
| E4 | Do purge + ``%`` + ``K`` stop a job, and does the queued rest stay unrun? |
| E5 | Does ``^IN`` reset that origin? |

The original origin is put back afterwards. Every trace goes to
``scripts/lab_runs/<test>_<stamp>.log``.
"""
import argparse
import math
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gerber2rml.engine import rmlspool, spi_probe  # noqa: E402
from gerber2rml.engine.runner import JobRunner  # noqa: E402

LOGS = Path(__file__).resolve().parent / "lab_runs"


class Lab:
    def __init__(self, port, test):
        LOGS.mkdir(exist_ok=True)
        self.log_path = LOGS / f"{test}_{time.strftime('%Y%m%d_%H%M%S')}.log"
        self.log_f = self.log_path.open("w", encoding="utf-8")
        self.ser = spi_probe.open_link(port)
        name = rmlspool.find_mill()
        if not name:
            raise SystemExit("no 'Roland SRM-20' printer")
        self.printer = rmlspool.SpoolPrinter(name)
        self.t0 = time.monotonic()

    def say(self, text):
        line = f"[{time.monotonic() - self.t0:7.2f}] {text}"
        print(line, flush=True)
        self.log_f.write(line + "\n")
        self.log_f.flush()

    def snap(self):
        st = spi_probe.machine_status(self.ser) or {}
        pos = spi_probe.query_position(self.ser)
        return pos, st, self.printer.pending()

    def trace(self, seconds, every=0.2):
        """E3: pos, moving bit, spooler queue, until still or ``seconds``."""
        end = time.monotonic() + seconds
        still = None
        last = None
        while time.monotonic() < end:
            pos, st, q = self.snap()
            p = "?" if pos is None else f"{pos[0]:.2f},{pos[1]:.2f},{pos[2]:.2f}"
            self.say(f"pos {p} moving={st.get('moving')} queued={q} "
                     f"sys=0x{st.get('system', 0):08X}")
            moved = pos and last and math.dist(pos[:3], last[:3]) > 0.02
            if pos and abs(pos[2] - self.z0) > self.zguard:
                self.stop_all(f"Z moved more than {self.zguard} mm")
                raise SystemExit("Z moved - stopped")
            if pos and last and not moved and not st.get("moving") and not q:
                still = still or time.monotonic()
                if time.monotonic() - still > 2.0:
                    return pos
            else:
                still = None
            last = pos or last
            time.sleep(every)
        return last

    def preflight(self):
        ver, feats = spi_probe.firmware_version(self.ser)
        pos, st, q = self.snap()
        org = spi_probe.get_origin(self.ser)
        vp = "VPanel" in subprocess.run(
            ["tasklist"], capture_output=True, text=True).stdout
        self.say(f"firmware v{ver} origin-cmd={'origin' in feats}")
        self.say(f"pos {pos}  origin {org}  queued {q}  VPanel running={vp}")
        self.say(f"status {st}")
        self.z0 = pos[2] if pos else 0.0
        return ver, feats, pos, st, org

    def require_safe(self, feats, st, pos):
        if "origin" not in feats:
            raise SystemExit("firmware v4 needed (O command)")
        if st.get("cover"):
            raise SystemExit("close the cover first")
        if st.get("spindle"):
            raise SystemExit("spindle is running")
        if pos is None:
            raise SystemExit("cannot read the position")

    def stop_all(self, why):
        self.say(f"STOP: {why}")
        JobRunner(self.ser, self.printer, lambda: False).stop()

    def close(self):
        self.ser.close()
        self.log_f.close()
        print(f"\nlog: {self.log_path}")


def cmd_state(lab, _a):
    lab.preflight()


def cmd_e1e2(lab, a):
    _v, feats, pos, st, org = lab.preflight()
    lab.require_safe(feats, st, pos)
    ox, oy = a.ox * 1000, a.oy * 1000
    try:
        got = spi_probe.set_origin(lab.ser, ox, oy, pos[2] * 1000)
        lab.say(f"set origin -> {got}  (read back {spi_probe.get_origin(lab.ser)})")

        # A: no ^IN. Expect the head at origin + (10, 10) mm.
        lab.say("A: '!MC0;VS10;!PZ0,0;PU1000,1000;' -> expect "
                f"({a.ox + 10:.1f}, {a.oy + 10:.1f}) at Z 0")
        lab.printer.send("!MC0;VS10;!VZ10;!PZ0,0;PU1000,1000;", "lab-A")
        pa = lab.trace(40)
        lab.say(f"A ended at {pa}; origin now {spi_probe.get_origin(lab.ser)}")

        # B: with ^IN in front (E5). Expect origin + (20, 10) if ^IN keeps it.
        lab.say("B: '^IN;!MC0;VS10;!PZ0,0;PU2000,1000;' -> expect "
                f"({a.ox + 20:.1f}, {a.oy + 10:.1f})")
        lab.printer.send("^IN;!MC0;VS10;!VZ10;!PZ0,0;PU2000,1000;", "lab-B")
        pb = lab.trace(40)
        lab.say(f"B ended at {pb}; origin now {spi_probe.get_origin(lab.ser)}")

        for tag, p, ex in (("A", pa, (a.ox + 10, a.oy + 10)),
                           ("B", pb, (a.ox + 20, a.oy + 10))):
            if p is None:
                lab.say(f"{tag}: no position")
                continue
            d = math.dist(p[:2], ex)
            lab.say(f"{tag}: off by {d:.2f} mm from expected -> "
                    + ("OBEYS SPI ORIGIN" if d < 0.3 else "DOES NOT"))
    finally:
        if org:
            back = spi_probe.set_origin(lab.ser, *(v * 1000 for v in org))
            lab.say(f"origin restored -> {back}")


def cmd_e4(lab, a):
    _v, feats, pos, st, org = lab.preflight()
    lab.require_safe(feats, st, pos)
    try:
        spi_probe.set_origin(lab.ser, a.ox * 1000, a.oy * 1000, pos[2] * 1000)
        # Slow square; STOP should land in the first leg, the rest never run.
        rml = ("!MC0;VS3;!VZ3;!PZ0,0;PU0,0;PU6000,0;PU6000,4000;"
               "PU0,4000;PU0,0;")
        lab.printer.send(rml, "lab-E4")
        lab.say("slow square sent; stopping after 4 s")
        lab.trace(4)
        runner = JobRunner(lab.ser, lab.printer, lambda: False)
        runner.stop()
        lab.say("STOP sent (purge, %, K, spindle off, !)")
        p = lab.trace(12)
        lab.say(f"after STOP: {p}  queued={lab.printer.pending()}")
        ok = spi_probe.jog_to(lab.ser, a.ox * 1000, a.oy * 1000)
        lab.say(f"jog after STOP acked={ok}; pos {spi_probe.query_position(lab.ser)}")
    finally:
        if org:
            spi_probe.set_origin(lab.ser, *(v * 1000 for v in org))
            lab.say("origin restored")


def cmd_nc(lab, a):
    """Send a few NC lines (``;``-separated) and trace where the head goes.
    The mill's command set is NC Code; RML is refused."""
    _v, feats, pos, st, _org = lab.preflight()
    lab.require_safe(feats, st, pos)
    body = "\n".join(l.strip() for l in a.code.split(";") if l.strip())
    prog = f"%\nO0001\n{body}\nM30\n%\n"
    lab.say("sending:\n" + prog)
    lab.printer.send(prog, "lab-nc")
    p = lab.trace(a.wait)
    lab.say(f"ended at {p}")
    st = spi_probe.machine_status(lab.ser) or {}
    lab.say(f"paused={st.get('paused')} error={st.get('error')} "
            f"cmderr={st.get('cmderr')}")


def cmd_air(lab, a):
    """The automatic run's own NC, cut in the air: the 'copper' is put
    ``--air`` mm below the top, spindle off. Proves the program and the
    runner's end-of-job detection on the real mill."""
    from gerber2rml.backends.gcode import render_incremental
    from gerber2rml.toolpath import Move
    _v, feats, pos, st, _org = lab.preflight()
    lab.require_safe(feats, st, pos)
    sq = [(40, 30), (60, 30), (60, 45), (40, 45), (40, 30)]
    path = [Move(40, 30, 2, rapid=True)] + [Move(x, y, -0.1) for x, y in sq]
    path += [Move(40, 30, 2, rapid=True), Move(42, 32, 2, rapid=True),
             Move(42, 32, -0.1), Move(58, 43, -0.1), Move(58, 43, 2, rapid=True)]
    prog, end = render_incremental([path], 4, 1, z_surface=-a.air,
                                   spindle=False, name="air run")
    lab.say("program:\n" + prog)
    lab.zguard = a.air + 1.0
    t0 = time.monotonic()
    JobRunner(lab.ser, lab.printer, lambda: False,
              note=lab.say).run(prog, "air run", end_mm=end, progress=lambda p:
                                lab.say(f"pos {p[0]:.2f},{p[1]:.2f},{p[2]:.2f}"))
    lab.say(f"runner says done after {time.monotonic() - t0:.1f} s; "
            f"head at {spi_probe.query_position(lab.ser)}, expected end {end}")


# The DTU fixture (MDF plate, L-brackets at the back corners, knobs in
# front): edges crossed only where nothing stands. mm from the stock's
# front-left corner; u along the front, v up the left side.
FIXTURE_ROWS = {"left": (12.0, 40.0), "front": (55.0, 90.0),
                "start": (70.0, 30.0)}
FIXTURE_CHECKS = ((155.0, 75.0), (40.0, 95.0))


def cmd_stock(lab, a):
    """Find the stock, or with ``--rehearse`` fly its plan 10 mm above the
    copper (one straight-down surface touch at the start spot first)."""
    from gerber2rml.engine import stockfind
    _v, feats, pos, st, _org = lab.preflight()
    lab.require_safe(feats, st, pos)
    lab.zguard = 99.0                     # this one goes down on purpose
    rows = dict(FIXTURE_ROWS, corner=(a.corner[0], a.corner[1]))
    size = (a.size[0], a.size[1])
    start = (rows["corner"][0] + rows["start"][0],
             rows["corner"][1] + rows["start"][1])
    if a.rehearse:
        z = stockfind.seek_surface(
            lab.ser, int(start[0] * 1000), int(start[1] * 1000), note=lab.say,
            hint_um=None if a.surface is None else int(a.surface * 1000))
        lab.say(f"copper at Z {z / 1000:.2f}")
        hover = z + 10000
        for kind, p, q in stockfind.plan(size, rows, FIXTURE_CHECKS):
            stockfind.travel(lab.ser, int(p[0] * 1000), int(p[1] * 1000),
                             surface_um=z)
            here = spi_probe.query_position(lab.ser)
            spi_probe.timed_move(lab.ser, dz_um=int(hover - here[2] * 1000))
            lab.say(f"{kind} at {p[0]:.1f}, {p[1]:.1f}"
                    + (f" -> {q[0]:.1f}, {q[1]:.1f}" if q else ""))
            time.sleep(1.5)
            if q:
                spi_probe.timed_move(lab.ser, dx_um=int((q[0] - p[0]) * 1000),
                                     dy_um=int((q[1] - p[1]) * 1000))
                time.sleep(1.5)
        stockfind.travel(lab.ser, int(start[0] * 1000), int(start[1] * 1000),
                         surface_um=z)
        lab.say("rehearsal done")
        return
    pose = stockfind.find_stock(lab.ser, start, size, bit_mm=0.8,
                                note=lab.say, rows=rows,
                                checks=FIXTURE_CHECKS, hint_mm=a.surface)
    stockfind.travel(lab.ser, int(start[0] * 1000), int(start[1] * 1000),
                     surface_um=int(pose.z * 1000))
    lab.say(f"FOUND corner {pose.x:.2f}, {pose.y:.2f}  angle {pose.angle:+.3f} deg"
            f"  copper Z {pose.z:.2f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("test", choices=["state", "e1e2", "e4", "nc", "air",
                                     "stock"])
    ap.add_argument("--corner", type=float, nargs=2,
                    help="stock: rough front-left corner, machine mm")
    ap.add_argument("--size", type=float, nargs=2, default=(160.0, 100.0))
    ap.add_argument("--rehearse", action="store_true")
    ap.add_argument("--surface", type=float,
                    help="stock: copper Z last time (mm) - drop fast to 5 mm above")
    ap.add_argument("--air", type=float, default=5.0,
                    help="air: pretend the copper is this far below the top")
    ap.add_argument("--code", default="", help="nc: lines split by ';'")
    ap.add_argument("--wait", type=float, default=30.0)
    ap.add_argument("--zguard", type=float, default=1.0,
                    help="STOP if Z leaves its start by more than this (mm)")
    ap.add_argument("--port", default="COM5")
    ap.add_argument("--ox", type=float, default=30.0, help="test origin X mm")
    ap.add_argument("--oy", type=float, default=30.0, help="test origin Y mm")
    a = ap.parse_args()
    lab = Lab(a.port, a.test)
    lab.zguard = a.zguard
    try:
        {"state": cmd_state, "e1e2": cmd_e1e2, "e4": cmd_e4, "nc": cmd_nc, "air": cmd_air,
         "stock": cmd_stock}[a.test](lab, a)
    finally:
        lab.close()


if __name__ == "__main__":
    main()
