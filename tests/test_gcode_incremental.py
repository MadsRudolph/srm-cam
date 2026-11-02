"""The automatic run's NC: no origin, incremental moves that add up exactly."""
import math
import random
import re

from gerber2rml.backends.gcode import render_incremental
from gerber2rml.toolpath import Move


def _walk(prog):
    """Follow the program the way the mill does; returns the visited points
    (machine mm) and whether any absolute Z was used."""
    absolute, x, y, z = True, None, None, 0.0
    seen, abs_z = [], False
    for line in prog.splitlines():
        line = re.sub(r"\(.*?\)", "", line)
        codes = re.findall(r"[GM]\d+", line)
        w = {k: float(v) for k, v in re.findall(r"([XYZ])([-0-9.]+)", line)}
        if "G90" in codes:
            absolute = True
        if "G91" in codes:
            absolute = False
        if "G28" in codes:
            z = 0.0
            continue
        if "G04" in codes or not w:
            continue
        if absolute:
            abs_z |= "Z" in w
            x, y = w.get("X", x), w.get("Y", y)
        else:
            x, y, z = x + w.get("X", 0), y + w.get("Y", 0), z + w.get("Z", 0)
        seen.append((x, y, z))
    return seen, abs_z


def test_thousands_of_steps_end_exactly_where_they_should():
    rnd = random.Random(4)
    path = [Move(60, 40, 2, rapid=True)]
    for i in range(3000):
        path.append(Move(60 + rnd.uniform(0, 50), 40 + rnd.uniform(0, 30),
                         -0.1 + rnd.uniform(-0.02, 0.02)))
    path.append(Move(path[-1].x, path[-1].y, 2, rapid=True))
    prog, end = render_incremental([path], 4, 1, z_surface=-43.3)
    seen, abs_z = _walk(prog)
    assert not abs_z
    cuts = [p for p in seen if p[2] < -43]
    want = path[1:-1]
    assert len(cuts) == len(want)
    worst = max(math.dist(c, (m.x, m.y, -43.3 + m.z)) for c, m in zip(cuts, want))
    assert worst < 0.0015             # rounding to whole microns, no drift
    assert math.dist(end, (path[-1].x, path[-1].y)) < 0.001


def test_it_starts_at_the_top_and_never_rapids_diagonally():
    prog, _ = render_incremental([[Move(10, 10, 2, rapid=True),
                                   Move(10, 10, -0.1),
                                   Move(20, 10, -0.1),
                                   Move(20, 10, 2, rapid=True),
                                   Move(30, 30, 2, rapid=True)]],
                                 4, 1, z_surface=-40.0)
    lines = prog.splitlines()
    assert lines.index("G28 Z0.") < lines.index("G0 X10. Y10.")
    for ln in lines:
        if ln.startswith("G0 "):
            assert not ("Z" in ln and ("X" in ln or "Y" in ln)), ln
    assert "M3" in lines and lines[-3:] == ["G90", "M30", "%"]


def test_a_dry_run_keeps_the_spindle_off():
    prog, _ = render_incremental([[Move(10, 10, 2, rapid=True)]], 4, 1,
                                 z_surface=-40.0, spindle=False)
    assert "M3" not in prog.split()
