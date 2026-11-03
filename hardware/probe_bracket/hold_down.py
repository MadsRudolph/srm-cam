"""The hold-down concept: small cam clamps with a flat lip, one printed part and
one M4 screw each, as many as a sheet needs. Pushed by hand while tightening. python hold_down.py [W H] writes
hold_down_WxH.json;
    solidcraft-cli run hold_down_160x100.json --save hold_down_160x100.sc

Same frame as build.py: the origin is the inside corner the sheet stops in, on
the bed. A concept to look at: nothing here is proven on the mill.

The boss under a clamp sits off centre on the screw, so pushing the clamp round
by hand pushes the sheet sideways into the bracket. The flat lip above the boss lies on the copper.
The boss stops short of the bed, so tightening the screw tips the clamp onto its
lip and presses the copper down, with no bevel in the way.
"""
import json
import math
import sys
from pathlib import Path

import build
from build import COPPER, c, rect, sketch

CLAMP_D = 26.0      # across the top: big enough to push by hand
LIP = 2.0           # past the boss: a 0.8 mm bit's edge comes within 2.2 mm of the sheet's edge
BOSS_D = CLAMP_D - 2 * LIP
BOSS_GAP = 0.2      # the boss's underside above the bed: what lets it tip
CAM_E = 5.5         # the screw off centre: reach changes 11 mm, more than a pitch
THUMBSCREW_H = 6.5  # the thumbscrew's head above the clamp, as the lab uses them
THUMBSCREW_D = 14.4 # across its head
CLAMP_H = 3.4       # 1.8 mm above the copper, under the bit's 2 mm travel height
EDGE_GAP = 2.5      # a hole closer to the sheet than this is not used

BED = (-200.0, -130.0, 20.0, 20.0)   # the MDF in this frame, holes included
HOLES = (20, 13)
HOLE_ZERO = (-185.0, -115.0)         # hole (0, 0)
HOLE_POS = 5.0                       # the corner screw's hole


def clamp(name, screw, towards):
    """One clamp, its screw at ``screw``, turned so its boss just touches the
    sheet in the direction ``towards``. ``edge`` distance sets the angle."""
    ux, uy, reach = towards
    along = reach - BOSS_D / 2          # centre's offset towards the sheet
    side = math.sqrt(CAM_E ** 2 - along ** 2)
    cx = screw[0] + ux * along - uy * side
    cy = screw[1] + uy * along + ux * side
    out = sketch(c("sketch.circle.center", center=[cx, cy], diameter=BOSS_D),
                 offset=BOSS_GAP, name=name + "Boss")
    out.append(c("solid.extrude", distance=COPPER - BOSS_GAP, operation="new",
                 body_name=name))
    out += sketch(c("sketch.circle.center", center=[cx, cy], diameter=CLAMP_D),
                  offset=COPPER, name=name + "Top")
    out.append(c("solid.extrude", distance=CLAMP_H - COPPER, operation="join",
                 targets=[name]))
    out.append(c("solid.hole", position=[screw[0], screw[1], CLAMP_H],
                 diameter=build.HOLE_D, type="countersink",
                 cs_diameter=build.CSK_D, cs_angle=90, targets=[name]))
    out += sketch(c("sketch.circle.center", center=list(screw), diameter=8.0),
                  offset=CLAMP_H - 0.5, name=name + "Head")
    out.append(c("solid.extrude", distance=0.5, operation="new",
                 body_name=name + "Screw"))
    return out


def hole_outside(edge):
    """The first grid line beyond a sheet edge at ``edge`` (negative), and how
    far it is from that edge."""
    line = HOLE_POS - 10 * math.ceil((HOLE_POS - edge + EDGE_GAP) / 10.0)
    return line, edge - line


def nearest_line(v):
    return HOLE_POS - 10 * round((HOLE_POS - v) / 10.0)


def build_script(w, h):
    script = list(build.script)
    script += sketch(rect(-w, -h, 0, 0), name="Sheet")
    script.append(c("solid.extrude", distance=COPPER, operation="new",
                    body_name="Copper"))
    x0, y0, x1, y1 = BED
    script += sketch(rect(x0, y0, x1, y1),
                     *[c("sketch.circle.center",
                         center=[HOLE_ZERO[0] + 10 * i, HOLE_ZERO[1] + 10 * j],
                         diameter=4.0)
                       for j in range(HOLES[1]) for i in range(HOLES[0])],
                     offset=-6.0, name="Bed")
    script.append(c("solid.extrude", distance=6.0, operation="new",
                    body_name="Spoilboard"))

    lx, lreach = hole_outside(-w)
    fy, freach = hole_outside(-h)
    script += clamp("ClampLeft", (lx, nearest_line(-h * 0.45)),
                    (1.0, 0.0, lreach))
    fronts = (0.3, 0.75) if w > 100 else (0.5,)
    for n, f in enumerate(fronts):
        script += clamp("ClampFront%d" % n, (nearest_line(-w * f), fy),
                        (0.0, 1.0, freach))
    return script


if __name__ == "__main__":
    w, h = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 \
        else (160.0, 100.0)
    out = Path(__file__).with_name("hold_down_%dx%d.json" % (w, h))
    out.write_text(json.dumps({"commands": build_script(w, h)}, indent=1),
                   encoding="utf-8")
