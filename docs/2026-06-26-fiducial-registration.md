# Dev log — fiducial registration for double-sided boards

**Date:** 2026-06-26
**Scope:** a second, opt-in way to register the two sides of a double-sided
board — drill 2–4 corner *fiducial* holes, flip and re-place the board freely,
probe where the holes actually landed, and warp the top traces to the measured
fit. The proven dowel-pin workflow is untouched and stays the default.

Spec: [`docs/superpowers/specs/2026-06-26-fiducial-registration-design.md`](superpowers/specs/2026-06-26-fiducial-registration-design.md).
Plan: [`docs/superpowers/plans/2026-06-26-fiducial-registration.md`](superpowers/plans/2026-06-26-fiducial-registration.md).

---

## Why a second method

Dowels are mechanical: the holes go through the stock **and into the sacrificial
bed**, pins seat in the bed, and the flipped board drops back onto them. No
measurement, sub-0.1 mm, proven on a full-bed board (2026-06-25). The trade-offs:
it drills the bed, and it only re-registers *at the flip*.

The fiducial method drills **stock-only** corner holes and re-registers by
*measurement*: after the flip you probe the holes and the software corrects the
top toolpaths. No bed drilling, and you can re-align after removing or bumping
the board. The cost is that accuracy now depends on how precisely you find each
hole centre — eyeballing the spindle over a hole is the weak link; an automated
electrical centre-find (future firmware) would close that gap.

## The key idea — dowel layout + a measured correction

The top traces are already pre-reflected about the flip axis so a *perfect* flip
registers. Fiducial mode keeps that identical layout and applies **one extra
transform `T`** fitted from where the reference holes actually landed:

- perfect flip → `measured == nominal` → `T == identity` → byte-for-byte the
  dowel result.
- the **RMS residual** of the fit is a direct, numeric "how good was this flip
  vs. my dowels?" readout.

So the whole double-sided pipeline (mirror, reflect, framing, top-traces export)
is reused unchanged; fiducials just replace the two dowel holes as the
registration holes.

## What was built

- **`engine/fiducial.py`** (pure, tested): `fit_transform(nominal, measured,
  allow_scale=False)` — closed-form 2D similarity least squares (Umeyama),
  **rigid by default** (rotation + translation), optional uniform scale; `residuals`
  / `rms`; `apply_to_toolpaths` (warps X/Y, leaves Z to depth/leveling). Shear is
  never modelled — it would silently absorb real misregistration.
- **`FiducialSpec` + layout switch** in `doublesided.py`: `registration="dowel"
  |"fiducial"`. Fiducials go in 2–4 corners, `placement="onboard"` (inset inside
  the board — permanent holes, works for full-bed boards) or `"waste"` (outset
  beyond the board — clean board, needs bigger stock). `nominal_top_fiducials()`
  reflects them into the top-cut frame.
- **Through-holes, stock-only depth** = `board_thickness + breakthrough` (a
  drill-tip graze, *not* the dowel's ~5 mm bed bite). Through is required: after
  the flip only a through-hole stays probeable from the new top face.
- **Build path**: `build_double_sided(registration="fiducial", fiducials=…)`
  drills the corners and writes a fiducial run plan listing the nominal probe
  coords; `build_top_traces(measured_fiducials=…, allow_scale=…)` fits `T` and
  warps the top traces. Composes with bed leveling (T sets XY, leveling sets Z).
- **GUI**: a **Method** selector (Dowel pins / Fiducial holes) in the
  Double-Sided panel; fiducial reveals count (2–4), placement, corner offset and
  a scale toggle. The preview draws the 4 corner holes. A **Fit & export top…**
  button opens a dialog to type or **Capture-from-DRO** each measured hole, shows
  RMS / rotation / scale, and exports the warped top traces.

## Operator flow

1. Method = **Fiducial holes**, set count/placement, export. Cut `_align` (corner
   holes, stock-only) → bottom drill → `_bottom_traces`.
2. **Flip** left-to-right and re-place the board (no pins). Re-zero Z.
3. Probe each fiducial; **Fit & export top…**, type or Capture the measured X/Y.
4. **Check the RMS** — a high value means a bad re-placement; re-seat and re-probe
   before cutting. Then run the warped `_top_traces`, and `_cutout` last.

## Status / next

- Engine + pipeline + GUI shipped with tests (engine 9, layout/build cases in
  `test_doublesided.py`, GUI smoke tests in `test_window.py`); suite green.
- **To validate on hardware** in the coming days: cut a board fiducial-registered
  and compare top/bottom offset against a dowel-registered twin.
- Future: an **automated electrical fiducial centre-find** firmware routine on
  top of the existing SPI probe — removes the human eyeball, the main accuracy
  limit of the manual method.

## Onboard caveat

`onboard` fiducials sit inside the board, so they can hit copper/pads. Avoiding
that is the operator's job (pick a clear corner / offset); v1 does not auto-check
clearance. The run plan notes this.
