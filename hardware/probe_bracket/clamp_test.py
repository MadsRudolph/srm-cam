"""One cam clamp, to print: python clamp_test.py writes clamp_test.json;
    solidcraft-cli run clamp_test.json --save clamp_test.sc --out clamp_test.stl

Origin: the clamp's centre, on the plane of the bed. Its numbers are hold_down.py's.
Tested on copper as the first version (2026-11-03): it holds far better than the
beveled discs, but felt flimsy at 22 mm across and 3 mm tall.
"""
import json
from pathlib import Path

import build
from build import COPPER, c, sketch
from hold_down import BOSS_D, BOSS_GAP, CAM_E, CLAMP_D, CLAMP_H


def circle(x, y, d):
    return c("sketch.circle.center", center=[x, y], diameter=d)


script = sketch(circle(0, 0, BOSS_D), offset=BOSS_GAP, name="Boss")
script.append(c("solid.extrude", distance=COPPER - BOSS_GAP, body_name="Clamp"))
script += sketch(circle(0, 0, CLAMP_D), offset=COPPER, name="Top")
script.append(c("solid.extrude", distance=CLAMP_H - COPPER, operation="join",
                targets=["Clamp"]))
# The countersink takes the small shoulder under the thumbscrew's head, and the
# head's flat underside bears on the flat top around it.
script.append(c("solid.hole", position=[-CAM_E, 0, CLAMP_H], diameter=build.HOLE_D,
                type="countersink", cs_diameter=build.CSK_D, cs_angle=90,
                targets=["Clamp"]))

out = Path(__file__).with_name("clamp_test.json")
out.write_text(json.dumps({"commands": script}, indent=1), encoding="utf-8")
