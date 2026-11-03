"""The probe bracket as a SolidCraft command script: python build.py

Writes probe_bracket.json. Open or rebuild it with
    solidcraft-cli run probe_bracket.json --save probe_bracket.sc --out probe_bracket.stl

Origin: the inside corner the stock stops in, on the bed. +Z is up. The back-right
bracket, so the stock lies towards -X and -Y. Mm throughout.
"""
import json
from pathlib import Path

BAR_W = 10.0        # the arm, wall to wall
ARM = 61.0          # outside length
H = 3.0             # height; nothing stands above it, so it prints flat on its top
PITCH = 10.0
HOLE_D = 4.4        # M4 clearance
CSK_D = 8.4         # the lab's M4 head is 8 mm across

COPPER = 1.6
WIRE_D = 0.7        # bare core, the thinnest it may be; sets how deep the groove is
WIRE_MAX = 1.0      # the thickest: it only presses harder, and sets the groove's width
PRESS = 0.6         # how far the sheet lifts the wire

REACH = 4.0         # how far the tongue reaches over the copper
GAP = 0.4           # between the tongue and the arm
BEAM_Z = 1.9        # underside of the tongue, 0.3 clear of the copper
TIP_X = -2.5        # free end
ROOT_X = -20.0      # where it starts to bend
ROOT_END_X = -26.0  # where its root block ends
HEAD_END_X = -13.5  # the thick part under the free end
SIDE_RAMP = 3.0     # lead-in for a sheet slid along the back wall

WIRE_Y = -1.7
FLAT_Y = -2.9       # where the front ramp starts
WIRE_BOTTOM = COPPER - PRESS
CEILING = WIRE_BOTTOM + WIRE_D
PROUD = 0.25        # of the wire below the head
HEAD_Z = WIRE_BOTTOM + PROUD
GROOVE_W = WIRE_MAX + 0.2
GROOVE_X = (-11.4, -4.6)
WIRE_HOLE_D = 1.8   # takes the 1.5 mm insulated wire too
RELIEF_D = 2.4      # strain relief: weave the insulated wire through these
RELIEF = ((-16.0, 6.0), (-24.0, 6.0))
RELIEF_CHANNEL = 1.9  # wide and deep, under the arm: the 1.5 mm wire stays below
                      # the bottom face, so the bracket still sits flat

# The corner hole, then at the pitch along each arm. Holes 2-4 of the back arm
# are left out: nothing screws there and the wire's relief holes use the space.
HOLE_C = BAR_W / 2
BACK = (0, 4, 5)
SIDE = (1, 2, 3, 4, 5)


def c(command, **params):
    return {"command": command, "params": params}


def sketch(*items, plane="XY", **kw):
    return [c("sketch.create", plane=plane, **kw), *items, c("sketch.finish")]


def poly(*pts):
    return c("sketch.line", points=[list(p) for p in pts], closed=True)


def rect(x0, y0, x1, y1):
    return poly((x0, y0), (x1, y0), (x1, y1), (x0, y1))


inner = ARM - BAR_W
script = []

# The L.
script += sketch(poly((BAR_W, BAR_W), (-inner, BAR_W), (-inner, 0), (0, 0),
                      (0, -inner), (BAR_W, -inner)), name="L")
script.append(c("solid.extrude", distance=H, body_name="Bracket"))

# The tongue and the block it grows from, off the arm's inside wall.
script += sketch(poly((ROOT_END_X, 0), (ROOT_END_X, -REACH), (TIP_X, -REACH),
                      (TIP_X, -GAP), (ROOT_X, -GAP), (ROOT_X, 0)),
                 offset=BEAM_Z, name="Tongue")
script.append(c("solid.extrude", distance=H - BEAM_Z, operation="join"))

# The head under its free end: the front ramp is what the sheet's edge meets.
script += sketch(poly((-GAP, BEAM_Z), (-GAP, HEAD_Z), (FLAT_Y, HEAD_Z),
                      (-REACH, BEAM_Z)),
                 plane={"origin": [TIP_X, 0, 0], "x_dir": [0, 1, 0],
                        "y_dir": [0, 0, 1]}, name="Head")
script.append(c("solid.extrude", distance=TIP_X - HEAD_END_X,
                direction="negative", operation="join"))

# The side ramp, for a sheet slid along the back wall into the corner.
script += sketch(poly((HEAD_END_X, HEAD_Z), (HEAD_END_X, BEAM_Z),
                      (HEAD_END_X - SIDE_RAMP, BEAM_Z)),
                 plane={"origin": [0, -GAP, 0], "x_dir": [1, 0, 0],
                        "y_dir": [0, 0, 1]}, name="SideRamp")
script.append(c("solid.extrude", distance=-FLAT_Y - GAP, operation="join"))

# The wire's groove and the two holes it comes up through.
script += sketch(rect(GROOVE_X[0], WIRE_Y - GROOVE_W / 2,
                      GROOVE_X[1], WIRE_Y + GROOVE_W / 2),
                 offset=0.5, name="Groove")
script.append(c("solid.extrude", distance=CEILING - 0.5, operation="cut"))
script += sketch(*[c("sketch.circle.center", center=[x, WIRE_Y],
                     diameter=WIRE_HOLE_D) for x in GROOVE_X],
                 offset=CEILING - 0.2, name="WireHoles")
script.append(c("solid.extrude", distance=H - CEILING + 0.4, operation="cut"))

# Strain relief.
script += sketch(*[c("sketch.circle.center", center=list(p), diameter=RELIEF_D)
                   for p in RELIEF], name="Relief")
script.append(c("solid.extrude", distance=H, operation="cut"))
script += sketch(rect(RELIEF[1][0], RELIEF[1][1] - RELIEF_CHANNEL / 2,
                      RELIEF[0][0], RELIEF[0][1] + RELIEF_CHANNEL / 2),
                 name="ReliefChannel")
script.append(c("solid.extrude", distance=RELIEF_CHANNEL, operation="cut"))

# The screws.
points = [(HOLE_C - PITCH * k, HOLE_C) for k in BACK] + \
         [(HOLE_C, HOLE_C - PITCH * k) for k in SIDE]
for x, y in points:
    script.append(c("solid.hole", position=[x, y, H], diameter=HOLE_D,
                    type="countersink", cs_diameter=CSK_D, cs_angle=90))

out = Path(__file__).with_name("probe_bracket.json")
out.write_text(json.dumps({"commands": script}, indent=1), encoding="utf-8")
print("wire bottom %.2f, ceiling %.2f, roof %.2f, head %.2f"
      % (WIRE_BOTTOM, CEILING, H - CEILING, HEAD_Z))
