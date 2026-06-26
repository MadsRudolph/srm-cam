"""Estimate how long a job will take to run on the machine.

Run time is just distance / speed summed over every move. We know both: the
toolpath geometry (or the emitted G-code) gives the distances, and the job's
feed rates give the speeds. Cut/plunge moves run at their programmed feed; rapid
(G0) moves run at the machine's rapid-traverse rate.

The estimate excludes things the geometry can't see — spindle spin-up, tool
changes, VPanel pauses, and acceleration/deceleration ramps — so the real run is
a little longer. It's meant for planning ("~4 min vs ~40 min"), not billing.

TODO (calibration — known underestimate): an operator report (2026-06-26) puts
the real run ~20-50% LONGER than this estimate. The dominant missing factor is
accel/decel: trace toolpaths are thousands of short segments with constant
direction changes, so the SRM-20 rarely reaches the programmed feed before it
must slow for the next corner — pure distance/speed therefore always runs low.

To fix properly, model a trapezoidal velocity profile per move with an
acceleration constant ``a`` (mm/s^2). A full-stop-at-every-vertex model is
per-segment-independent (segment time depends only on its own length/speed), so
it can be FACTORED INTO A SHARED HELPER used by BOTH this module and
``engine.progress.RunProgress`` — which today mirrors this timing exactly so the
live run-progress bar lands on the planner's total. Keep them in sync or the bar
will diverge.

We can't pick ``a`` yet — it needs ONE real measured run time to fit against
(a job from ``examples/`` + its planner estimate + stopwatch wall-clock). Until
that data exists the constant stays uncalibrated, so behaviour here is unchanged
(no guessed constant). See the ``estimator-underestimates-no-accel`` memory note.
"""
from math import sqrt

# SRM-20 rapid-traverse (G0) rate, mm/s. Matches backends.gcode.DEFAULT_RAPID.
DEFAULT_RAPID = 15.0


def estimate_toolpaths_seconds(toolpaths, xy_feed, plunge_feed,
                               rapid_feed=DEFAULT_RAPID):
    """Estimate run time (seconds) from ``Move`` toolpaths and feeds (mm/s).

    Backend-agnostic: works on the same toolpath lists the RML and G-code
    backends render, so it matches whichever machine is selected. A pure
    downward move at constant XY is treated as a plunge (slower feed)."""
    total = 0.0
    cx = cy = cz = 0.0
    for path in toolpaths:
        for m in path:
            dx, dy, dz = m.x - cx, m.y - cy, m.z - cz
            d = sqrt(dx * dx + dy * dy + dz * dz)
            if d > 1e-9:
                if m.rapid:
                    speed = rapid_feed
                elif abs(dx) < 1e-6 and abs(dy) < 1e-6 and dz < 0:
                    speed = plunge_feed          # straight down = plunge
                else:
                    speed = xy_feed
                if speed > 0:
                    total += d / speed
            cx, cy, cz = m.x, m.y, m.z
    return total


def estimate_nc_seconds(text, rapid_feed=DEFAULT_RAPID):
    """Estimate run time (seconds) of an RS-274 ``.nc`` program.

    Sums move distance / speed. ``G1`` moves use the modal ``F`` feed (mm/min in
    the file -> mm/s here); ``G0`` rapids use ``rapid_feed``. Homing (``G28``)
    carries no cut geometry and is skipped."""
    import re
    word = re.compile(r"([A-Za-z])\s*(-?\d*\.?\d+)")
    x = y = z = 0.0
    feed = None            # mm/s (modal F / 60)
    motion = None          # 0 = rapid, 1 = feed
    total = 0.0
    for raw in text.splitlines():
        line = re.sub(r"\(.*?\)", "", raw).strip()       # drop ( comments )
        if not line:
            continue
        codes = [(l.upper(), float(v)) for (l, v) in word.findall(line)]
        gset = {int(v) for (l, v) in codes if l == "G"}
        if 28 in gset:                                   # homing -> not a cut move
            continue
        if 0 in gset:
            motion = 0
        if 1 in gset:
            motion = 1
        nx, ny, nz = x, y, z
        for (l, v) in codes:
            if l == "X":
                nx = v
            elif l == "Y":
                ny = v
            elif l == "Z":
                nz = v
            elif l == "F":
                feed = v / 60.0
        d = sqrt((nx - x) ** 2 + (ny - y) ** 2 + (nz - z) ** 2)
        if d > 1e-9 and motion is not None:
            speed = rapid_feed if motion == 0 else (feed or rapid_feed)
            if speed > 0:
                total += d / speed
        x, y, z = nx, ny, nz
    return total


def estimate_file_seconds(path, rapid_feed=DEFAULT_RAPID):
    """Estimate run time (seconds) of an exported toolpath FILE, or ``None`` if
    the format isn't a time-estimable G-code program (e.g. a run-plan .txt)."""
    from pathlib import Path
    p = Path(path)
    if p.suffix.lower() != ".nc":
        return None
    return estimate_nc_seconds(p.read_text(), rapid_feed)


def format_duration(seconds):
    """Human run time: ``45s`` / ``3m 20s`` / ``1h 04m``."""
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"
