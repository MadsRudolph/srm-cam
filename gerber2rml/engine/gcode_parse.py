"""Parse exported toolpath files back into Move lists for the 3D simulator.

Lets the operator open *any* file the tool produced -- traces, drill, cutout, or
a rework second-pass file -- and play it in 3D, like loading G-code into
ncviewer.com. Targets the two formats this project writes:

  * ``.nc``  -- RS-274 G-code from :mod:`gerber2rml.backends.gcode`
  * ``.rml`` -- RML-1 from :mod:`gerber2rml.backends.srm20`

Only motion is reconstructed (positions + rapid/cut kind); machine homing
(``G28``) and spindle/feed words carry no toolpath geometry and are skipped. The
rapid-vs-cut flag only drives colour in the viewer, so the heuristics here need
only match this project's own output.
"""
import re
from pathlib import Path
from gerber2rml.toolpath import Move

_WORD = re.compile(r"([A-Za-z!^]+)\s*(-?\d*\.?\d+)?")


def _gvals(codes):
    return {int(float(v)) for (letter, v) in codes if letter == "G" and v}


def parse_nc(text):
    """Parse RS-274 G-code into a single toolpath (list of :class:`Move`).

    Handles modal ``G0``/``G1`` motion in absolute (``G90``) coordinates; lines
    that home the machine (``G28``) are skipped so the path stays in work
    coordinates."""
    moves = []
    x = y = z = 0.0
    motion = None            # 0 = rapid, 1 = feed
    absolute = True
    for raw in text.splitlines():
        line = re.sub(r"\(.*?\)", "", raw).strip()      # drop ( comments )
        if not line:
            continue
        codes = [(l.upper(), v) for (l, v) in _WORD.findall(line)]
        gset = _gvals(codes)
        if 28 in gset:                                  # homing -> not toolpath
            continue
        if 90 in gset:
            absolute = True
        if 91 in gset:
            absolute = False
        if 0 in gset:
            motion = 0
        if 1 in gset:
            motion = 1
        nx, ny, nz, moved = x, y, z, False
        for (letter, v) in codes:
            if v is None:
                continue
            val = float(v)
            if letter == "X":
                nx = val if absolute else x + val; moved = True
            elif letter == "Y":
                ny = val if absolute else y + val; moved = True
            elif letter == "Z":
                nz = val if absolute else z + val; moved = True
        if moved and motion is not None:
            x, y, z = nx, ny, nz
            moves.append(Move(x, y, z, rapid=(motion == 0)))
    return [moves] if moves else []


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_rml(text, scale=None):
    """Parse RML-1 into a single toolpath. ``Z x,y,z;`` are 3-axis moves in
    machine units. The unit scale defaults to the SRM-20 backend's own ``SCALE``
    constant so the parser always matches whatever the writer emitted. A move is
    treated as a rapid when the preceding ``VS``/``!VZ`` feeds match -- exactly
    how the SRM-20 backend brackets rapid moves (both set to the rapid feed)
    versus cuts (XY feed vs plunge feed)."""
    if scale is None:
        from gerber2rml.backends.srm20 import SCALE as scale
    moves = []
    last_vs = last_vz = None
    rapid = False
    for tok in text.replace("\n", "").replace("\r", "").split(";"):
        tok = tok.strip()
        if not tok:
            continue
        if tok.startswith("VS"):
            last_vs = _num(tok[2:])
        elif tok.startswith("!VZ"):
            last_vz = _num(tok[3:])
            if last_vs is not None and last_vz is not None:
                rapid = abs(last_vs - last_vz) < 1e-9
        elif tok[0] == "Z" and "," in tok:
            parts = tok[1:].split(",")
            if len(parts) == 3 and all(_num(p) is not None for p in parts):
                x, y, z = (float(p) / scale for p in parts)
                moves.append(Move(x, y, z, rapid=rapid))
    return [moves] if moves else []


def parse_file(path):
    """Dispatch by extension: ``.rml`` -> RML, everything else -> G-code."""
    p = Path(path)
    text = p.read_text()
    if p.suffix.lower() == ".rml":
        return parse_rml(text)
    return parse_nc(text)
