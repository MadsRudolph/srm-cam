"""How a board's copper is made: the flat mill, the ball mill or the laser.

One fact about a board decides a great deal of what the app does with it:
which copper checks make sense and against what width, which tool profile the
mill runs, and which jobs appear on the rail. A board drawn with 0.25 mm gaps
for the laser is not "shorted in 23 places"; it is a laser board, and the mill
only drills it and cuts it out.

Where the method comes from, best first:

``kicad``   The KiCad plugin's *Set design rules for SRM-CAM* window stores the
            method in ``srm-cam/method.json`` beside the board - the folder
            *Send to SRM-CAM* plots the Gerbers into, so it is the folder this
            app opens.
``chosen``  Picked in this app; always possible, whatever the other sources
            say.
``guessed`` From the narrowest gap between two nets on the board: a gap the
            0.8 mm flat endmill fits is a flat-mill board, one the ball mill's
            0.44 mm channel fits is a ball-mill board, and anything narrower
            can only be made on the laser.
``profile`` Nothing better known: the tool profile in use says it, as before
            the method existed.

The ids are the KiCad plugin's (kicad-plugin/srm20area/methods.py), so the
file one writes is the file the other reads.
"""
import json
from dataclasses import dataclass
from pathlib import Path

FLAT = "mill_flat"
BALL = "mill_ball"
LASER = "laser"
IDS = (FLAT, BALL, LASER)

METHOD_FILE = "method.json"

# The narrowest gap between two nets each method can make, mm. The flat bit's
# own width; the ball mill's channel at its 0.08 mm depth
# (docs/bit-capabilities.md); the laser clears about 0.22 mm from each edge,
# and the plugin's laser rules stop at 0.20.
FLOOR = {FLAT: 0.8, BALL: 0.44, LASER: 0.2}


@dataclass(frozen=True)
class Method:
    id: str
    name: str          # what the header and Your board say
    short: str         # the chip
    about: str         # one sentence, for the tooltip


METHODS = {
    FLAT: Method(FLAT, "Flat mill (0.8 mm endmill)", "Flat mill",
                 "Isolation-milled with the 0.8 mm flat endmill. Every gap "
                 "between two nets must be at least the bit's width."),
    BALL: Method(BALL, "Ball mill (0.44 mm channel)", "Ball mill",
                 "Isolation-milled with the 0.8 mm ball mill, 0.08 mm deep: "
                 "a 0.44 mm channel, for fine pitch and SMD."),
    LASER: Method(LASER, "Laser copper (mill drills and cuts out)", "Laser",
                  "The mill drills the holes and cuts the outline, leaving "
                  "tabs so the board stays in the sheet. The whole sheet then "
                  "goes to the xTool, which etches the copper lined up on "
                  "those holes."),
}

SOURCE_WORDS = {"kicad": "from KiCad", "chosen": "chosen",
                "guessed": "guessed", "profile": "from the tool"}


def name(method_id):
    return METHODS[method_id].name


def is_mill(method_id):
    return method_id in (FLAT, BALL)


def from_profile(trace_bit_mm):
    """The method a tool profile implies: a trace channel under 0.6 mm is the
    ball mill's. What the app did before boards had a method."""
    try:
        return BALL if float(trace_bit_mm) < 0.6 else FLAT
    except (TypeError, ValueError):
        return FLAT


# ------------------------------------------------------------- from KiCad
def read_kicad(folder, stem=None):
    """The method KiCad stored for the board plotted into ``folder``, or None.

    ``method.json`` keys its entries by the board file's name. One entry is
    the board; with several (two boards plotted into one folder), the one
    whose name is ``stem`` - the Gerbers' common prefix - is."""
    path = Path(folder) / METHOD_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        boards = data.get("boards") or {}
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(boards, dict) or not boards:
        return None
    entries = list(boards.items())
    if len(entries) > 1 and stem:
        want = str(stem).lower()
        entries = [(k, v) for k, v in entries
                   if Path(k).stem.lower() == want] or entries[:0]
    if len(entries) != 1:
        return None
    entry = entries[0][1]
    mid = entry.get("method") if isinstance(entry, dict) else None
    return mid if mid in IDS else None


# --------------------------------------------------------------- the guess
def narrowest_gap(copper, nets=None, *, limit=FLOOR[FLAT]):
    """The narrowest gap between two nets on ``copper``, mm, or None when
    none is under ``limit``. Uses the same pairing as the shorts check
    (engine/drc.py), so two islands of one pour are not a gap."""
    from gerber2rml.engine.drc import isolation_pairs
    try:
        pairs = isolation_pairs(copper, limit, nets=nets)
    except Exception:                       # noqa: BLE001 - a guess, no more
        return None
    return min((gap for _p, _q, gap in pairs), default=None)


def guess_from_gap(gap):
    """The method a narrowest gap of ``gap`` mm asks for (None: no gap under
    the flat bit at all)."""
    if gap is None or gap >= FLOOR[FLAT] - 0.0005:
        return FLAT
    if gap >= FLOOR[BALL] - 0.0005:
        return BALL
    return LASER


def guess(board):
    """``(method id, narrowest gap or None)`` for a loaded board: both faces
    when it has two."""
    gaps = []
    for copper, nets in ((getattr(board, "copper", None),
                          getattr(board, "copper_nets", None)),
                         (getattr(board, "copper_top", None),
                          getattr(board, "copper_top_nets", None))):
        if copper is None or copper.is_empty:
            continue
        g = narrowest_gap(copper, nets)
        if g is not None:
            gaps.append(g)
    gap = min(gaps) if gaps else None
    return guess_from_gap(gap), gap
