# Fiducial registration for double-sided boards — design

**Date:** 2026-06-26
**Status:** approved, ready for implementation plan

## Problem

Double-sided boards are currently registered with **dowel pins** (`doublesided.py`):
the mill drills two dowel holes through the stock *and into the sacrificial bed*,
metal pins are seated in the bed, and the flipped board drops back onto them.
This is mechanically exact and proven (a full-bed board registered perfectly on
2026-06-25), but it requires drilling the bed and only re-registers at the flip.

A second, complementary method seen in the wild: drill **reference (fiducial)
holes**, and after any re-placement (e.g. a flip), *measure* where those holes
actually landed and correct the toolpath in software. This never drills the bed
and can re-register the board at any time.

We want **both**: keep the dowel workflow as the proven default, and add a
fiducial workflow the operator can opt into and validate on hardware.

## Key insight

Fiducial registration is **the existing dowel layout plus a measured
correction**. The top traces are already pre-reflected about the flip axis so a
*perfect* flip registers. Fiducial mode keeps that identical layout, then applies
one extra transform `T` fitted from where the reference holes actually landed:

- If the flip were perfect, `measured == nominal`, so `T == identity` and the
  result is byte-for-byte the dowel result.
- The **RMS residual** of the fit is therefore a direct, numeric answer to "was
  this flip as good as my dowels?".

This means almost all of the double-sided pipeline (mirror, reflect-to-top-frame,
framing, top-traces export) is reused unchanged.

## Decisions (locked with the user)

| Decision | Choice |
|---|---|
| Keep dowel mode | Yes — unchanged, remains the default |
| Fiducial count | 4 corners default, configurable 2–4 |
| Corner placement | Per-job setting: `onboard` (inside outline) or `waste` (outside outline) |
| Hole depth | Through the stock only (through-hole + small breakthrough); **never** the dowel bed bite |
| Fit model | Rigid (rotation + translation), with an optional uniform-scale toggle. No shear/affine. |
| Measured-coord capture | Type-in **and** Capture-from-DRO (live SPI position) |

### Why through-holes
After the flip, the face that was up is now down. Only a **through-hole** stays
probeable from the new top face, so fiducials must go fully through. Depth =
`board_thickness + small breakthrough` (a drill-tip graze of the bed), versus the
dowel's deliberate ~5 mm bed bite — so the "essentially only the PCB" benefit
holds.

### Why reject affine/shear
A rigid (+optional uniform scale) board model matches physical reality. Full
affine would silently *absorb* real misregistration (skew) as a "correction",
hiding problems instead of revealing them. Uniform scale is offered because it
can absorb genuine thermal/measurement scale; it is **off by default**.

## Architecture

### 1. `gerber2rml/engine/fiducial.py` (new, pure, unit-tested)

The mathematical core. No GUI, no hardware, no file I/O.

- `@dataclass Transform` — rotation θ, uniform scale s, translation (tx, ty);
  `apply(x, y) -> (x, y)`.
- `fit_transform(nominal, measured, allow_scale=False) -> Transform`
  — least-squares similarity (Umeyama). `allow_scale=False` forces s = 1 (rigid).
  Valid for N = 2…4 correspondence pairs.
- `residuals(T, nominal, measured) -> list[float]` and `rms(...) -> float`
  — per-point Euclidean error and its RMS (the flip-quality number).
- `apply_to_toolpaths(toolpaths, T) -> toolpaths` — warps X/Y of every `Move`,
  leaves Z untouched (Z is owned by depth/leveling, not registration).

`nominal` for the double-sided flip = the fiducial hole positions reflected into
the **top-cut frame** (the same `reflect_holes` the top traces already use), so
they are exactly where a perfect flip would put the holes.

### 2. `FiducialSpec` + `layout_double_sided` extension

- New `@dataclass FiducialSpec`: `count` (2–4), `placement` (`"onboard"` |
  `"waste"`), `edge_offset` (waste outset / onboard inset, mm), `hole_diameter`,
  `breakthrough` (mm past the board), `allow_scale` (fit toggle).
- `layout_double_sided(..., registration="dowel"|"fiducial", fiducials=None)`:
  for `"fiducial"`, the registration holes become the 2–4 corner holes instead of
  the 2 flip-axis dowels. Corner positions from the framed bounds:
  - `waste`: outset diagonally — FL `(gx0-off, gy0-off)`, FR `(gx1+off, gy0-off)`,
    BR `(gx1+off, gy1+off)`, BL `(gx0-off, gy1+off)`.
  - `onboard`: inset diagonally by `edge_offset` from the same corners.
  - count 2 → diagonal pair (FL, BR); 3 → FL, FR, BL; 4 → all.
  Everything else (mirror, reflect, offset) is unchanged; the holes flow through
  `align_holes` and get reflected to the top frame for free.
- `onboard` fiducials land inside the board, so they can collide with copper or
  pads. Avoiding that is the **operator's** responsibility (choose `edge_offset`
  / a corner free of routing); the tool does not auto-check clearance in v1, and
  the run plan notes this.

### 3. Build path (`doublesided.py`)

- Fiducial align-drill depth = `board_thickness + breakthrough` (no bed bite).
- `build_double_sided(..., registration="fiducial", fiducials=FiducialSpec())`:
  drills the corner fiducials, cuts the bottom side as today, and writes a
  **fiducial run plan** that lists the nominal **top-frame** coordinates to probe
  after the flip.
- `build_top_traces(..., measured_fiducials=[...], allow_scale=...)`: computes
  `T = fit_transform(nominal, measured, allow_scale)`, applies it to the top
  toolpaths, and writes the corrected `<name>_top_traces`. Mirrors the existing
  leveled top-traces re-export. (Leveling and the fiducial transform compose:
  transform XY, leveling sets Z.)
- The dowel build path is untouched; `registration` defaults to `"dowel"`.

### 4. GUI (`gui/app.py`)

- A **Dowel / Fiducial** registration selector in the double-sided panel.
  Selecting Fiducial reveals: count, placement (onboard/waste), scale toggle.
- A **Fiducial align** panel: one row per hole showing nominal X/Y, an input for
  measured X/Y, and a **Capture from DRO** button per row (reuses the live SPI
  position already read for the tool marker). A **Fit & export top traces** button
  shows **RMS, per-point residual, and fitted rotation/scale**, then writes the
  corrected top traces.
- Reuses existing top-traces export plumbing.

## Data flow

```
design Gerbers
   └─ layout_double_sided(registration="fiducial", fiducials)
        ├─ bottom_copper / top_copper / outline (as today)
        └─ align_holes = 2–4 corner fiducials   ── reflect ─▶ nominal top-frame pts
   └─ build_double_sided  ─▶ *_align (corner holes, stock-only), bottom jobs, runplan(nominal pts)
            │
        [ operator: cut bottom, flip, probe the 4 holes ]
            │
   measured pts ─▶ fit_transform(nominal, measured, allow_scale) ─▶ T (+ RMS)
   top toolpaths ─▶ apply_to_toolpaths(·, T) ─▶ build_top_traces ─▶ corrected *_top_traces
```

## Error handling

- `fit_transform` with < 2 points, or degenerate/collinear points → raise a clear
  `ValueError` surfaced in the GUI as a message, not a crash.
- Missing/blank measured coords in the GUI → disable Fit until all required rows
  are filled (or fall back to the rows that are filled, min 2).
- Report RMS prominently; high RMS = bad flip, re-seat and re-probe (don't cut).

## Testing

- **Engine:** fit recovers known pure-translate / rotate / rotate+translate /
  +scale transforms (RMS ≈ 0); noisy inputs give expected residuals; N = 2/3/4;
  rigid vs. scale; `apply_to_toolpaths` moves XY only, not Z; degenerate inputs
  raise.
- **Layout:** fiducial placement count & corner positions for onboard/waste;
  reflection into the top frame; align-drill depth has no bed bite.
- **Build:** fiducial build writes the expected files; run plan contains the
  nominal coords; `build_top_traces` with measured points applies `T`.
- **GUI:** smoke test in the `test_window.py` style (selector toggles panel,
  fit+export writes a corrected file).

## Out of scope (YAGNI)

- Full affine / shear correction.
- Automated electrical fiducial-centre-finding **firmware** routine — that's the
  hardware test the operator runs next; the software here needs only manual +
  DRO capture. The auto-centre routine is a clean later add on top.
- Single-sided "recover after removing the board" re-registration — same engine
  would serve it, but it's a separate workflow not requested now.

## Related

- Reuses `doublesided.py` mirror/reflect, `engine/leveling.apply_leveling`,
  the live SPI DRO feed, and the top-traces re-export hook.
- Memory: `estimator-underestimates-no-accel` (unrelated, separate task).
