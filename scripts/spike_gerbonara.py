"""
Throwaway gerbonara API spike — Task 0 of the gerber2rml pipeline plan.

Run from the repo root with the venv active:
    .venv/Scripts/python.exe scripts/spike_gerbonara.py

Purpose: discover the *real* gerbonara 1.x attribute/method names so that
loader.py (Task 4) can be written against verified names rather than guesses.

Results are captured in the ## gerbonara API notes section of gerber2rml/loader.py.
"""

import warnings
import pathlib
import sys

# Suppress the KiCad-generated G90-after-header SyntaxWarning from gerbonara
warnings.filterwarnings("ignore")

from gerbonara import LayerStack

FIXTURE = pathlib.Path(__file__).parent.parent / "tests" / "fixtures" / "mosfet_test"
if not FIXTURE.exists():
    sys.exit(f"Fixture not found: {FIXTURE}")

print("=" * 60)
print(f"gerbonara version: ", end="")
import gerbonara
print(gerbonara.__version__)
print(f"Fixture: {FIXTURE}")
print("=" * 60)

# ── 1. Open a directory of Gerbers ──────────────────────────────────────────
stack = LayerStack.open(FIXTURE)
print(f"\n[1] LayerStack.open(path) -> {type(stack).__name__}")

# ── 2. Available layer keys ──────────────────────────────────────────────────
print("\n[2] stack.graphic_layers keys (the real internal dict):")
for k in stack.graphic_layers:
    print(f"    {k!r}")

# ── 3. Bottom copper layer access ────────────────────────────────────────────
b_cu = stack.graphic_layers[("bottom", "copper")]
# Equivalent sugar:  stack[("bottom", "copper")]  or  stack["bottom copper"]
print(f"\n[3] Bottom copper: stack.graphic_layers[('bottom','copper')]")
print(f"    = {b_cu}")
print(f"    Sugar: stack['bottom copper'] = {stack['bottom copper']}")

# ── 4. Outline / Edge.Cuts layer ─────────────────────────────────────────────
outline = stack.graphic_layers[("mechanical", "outline")]
print(f"\n[4] Outline (Edge.Cuts): stack.graphic_layers[('mechanical','outline')]")
print(f"    = {outline}")
print(f"    stack.outline property is same? {stack.outline is outline}")

# ── 5. Drill data ─────────────────────────────────────────────────────────────
print("\n[5] Drill layers via stack._drill_layers (list of ExcellonFile):")
print(f"    stack.drill_pth  = {stack.drill_pth}")
print(f"    stack.drill_npth = {stack.drill_npth}")
print(f"    stack.drill_mixed = {stack.drill_mixed}")
print(f"    stack._drill_layers = {stack._drill_layers}")
drill_file = stack._drill_layers[0]
print(f"    drill_file.objects is a list: {isinstance(drill_file.objects, list)}")
print(f"    drill_file.objects count: {len(drill_file.objects)}")

# ── 6. Graphic object classes on B.Cu ─────────────────────────────────────────
types = sorted(set(type(o).__name__ for o in b_cu.objects))
counts = {t: sum(1 for o in b_cu.objects if type(o).__name__ == t) for t in types}
print(f"\n[6] Object classes on B.Cu ({len(b_cu.objects)} total):")
for t, n in counts.items():
    print(f"    {t}: {n}")

# ── 7. Line attributes ────────────────────────────────────────────────────────
lines = [o for o in b_cu.objects if type(o).__name__ == "Line"]
line = lines[0]
print(f"\n[7] Sample Line: {repr(line)[:120]}")
print(f"    .x1={line.x1}  .y1={line.y1}  .x2={line.x2}  .y2={line.y2}")
print(f"    .p1={line.p1}  .p2={line.p2}  (tuple convenience properties)")
print(f"    .aperture type: {type(line.aperture).__name__}")
print(f"    .aperture.diameter (= stroke width): {line.aperture.diameter}")

# ── 8. Flash attributes ───────────────────────────────────────────────────────
flashes = [o for o in b_cu.objects if type(o).__name__ == "Flash"]
flash_circle = next(f for f in flashes if type(f.aperture).__name__ == "CircleAperture")
flash_rect   = next(f for f in flashes if type(f.aperture).__name__ == "RectangleAperture")
print(f"\n[8] Sample Flash (circle): .x={flash_circle.x}  .y={flash_circle.y}")
print(f"    aperture type: CircleAperture  .diameter={flash_circle.aperture.diameter}")
print(f"    Sample Flash (rect):   .x={flash_rect.x}  .y={flash_rect.y}")
print(f"    aperture type: RectangleAperture  .w={flash_rect.aperture.w}  .h={flash_rect.aperture.h}")

# Aperture types seen on B.Cu flashes
apt_types = sorted(set(type(f.aperture).__name__ for f in flashes))
print(f"    Aperture types on B.Cu flashes: {apt_types}")

# ── 9. Region attributes ──────────────────────────────────────────────────────
regions = [o for o in b_cu.objects if type(o).__name__ == "Region"]
region = regions[0]
print(f"\n[9] Sample Region:")
print(f"    .outline is a list of (x,y) tuples: {isinstance(region.outline, list)}")
print(f"    len(region.outline): {len(region.outline)}")
print(f"    region.outline[:2]: {region.outline[:2]}")

# ── 10. Drill hit attributes ──────────────────────────────────────────────────
drill_hit = drill_file.objects[0]
print(f"\n[10] Sample drill hit (Flash in ExcellonFile.objects):")
print(f"    type: {type(drill_hit).__name__}")
print(f"    .x={drill_hit.x}  .y={drill_hit.y}")
print(f"    aperture type: {type(drill_hit.aperture).__name__}")
print(f"    aperture.diameter: {drill_hit.aperture.diameter}")

print("\n" + "=" * 60)
print("Spike complete — see gerber2rml/loader.py for API notes")
print("=" * 60)
