# Dev log — V-bit (engraving bit) toolpath support

**Date:** 2026-06-30
**Scope:** add V-shaped engraving bits alongside the flat endmill so we can hold
tight (~0.2 mm) isolation traces for SMD boards. Unlike a flat endmill, a V-bit's
cut width *grows with depth*, so the toolpath engine now computes the effective
width dynamically and the pre-flight refuses to run a V-bit on an un-levelled bed.

Feature-by-feature with the *why*, like the sibling logs. Machine facts stay in
the project memory (`srm20-*` notes).

---

## 1. The geometry: width-first, not depth-first

A V-bit has a small flat tip of diameter `T` and walls at a full included angle
`theta`. At a plunge depth `D` the cut widens to:

```
W = T + 2*D*tan(theta/2)
```

For tight traces you care about the *width* `W`, not the depth, so the tool is
driven **width-first**: the operator sets a `target_width` and the engine
back-solves the depth (the inverse of the formula above):

```
D = (target_width - T) / (2*tan(theta/2))     # clamped at 0
```

Everything downstream (isolation offset, stepover, the cut Z, leveling) then
follows from that single derived depth, so a V-bit is just a flat bit whose
effective diameter happens to depend on depth.

**The catch — depth→width sensitivity.** Differentiating the forward formula:

```
dW/dD = 2*tan(theta/2)
```

| Included angle | dW/dD | 25 µm Z error → width error |
|---|---|---|
| 30° | 0.54 | ±13 µm |
| 60° | 1.15 | ±29 µm |
| 90° | 2.00 | ±50 µm |

So a V-bit amplifies any surface-height error straight into trace-width error.
That is the whole reason §3 (bed leveling) matters, and it argues for a **narrow
bit + shallow depth + dense mesh** for 0.2 mm work.

## 2. Tool configuration (`config.py`, `gui/form.py`)

`TraceJob` gained four fields (defaults keep flat behaviour byte-for-byte):

| field | meaning |
|---|---|
| `tool_type` | `"flat"` (default) or `"vbit"` |
| `tip_diameter` | the flat width at the very tip, `T` (mm) |
| `included_angle` | full included angle, `theta` (degrees) |
| `target_width` | desired effective cut width, `W` (mm) — V-bit only |

The geometry lives in four small, unit-tested methods on `TraceJob`:
`width_at_depth(D)`, `depth_for_width(W)`, `effective_cut_depth()`,
`effective_diameter()`, plus `width_sensitivity()` (= `dW/dD`).

`tool_type` is a **string** field, which the auto-generated `DataclassForm` did
not handle (it only knew bool/int/float and would `float("flat")` → crash). The
form now renders strings as a `QComboBox` when given a `choices=` map (the
traces form passes `{"tool_type": ["flat", "vbit"]}`), else a `QLineEdit`. When
`tool_type == "vbit"`, `_sync_vbit_fields()` greys out `cut_depth` and
`bit_diameter` (now derived) and mirrors the computed depth/width into them live;
the tip/angle/target fields grey out for a flat bit. This runs on every trace
edit and after a preset apply.

## 3. Dynamic width in the engine (`engine/traces.py`)

`isolate()` previously used `job.bit_diameter` as a constant for both the buffer
radius and the stepover. It now uses `job.effective_diameter()` and
`job.effective_cut_depth()`. **No call-site changed** — all ~8 callers
(`state`, `doublesided` ×3, `gui/app` ×4, `cli`) pass a `TraceJob`, so they all
pick up V-bit support for free, and a flat job is unaffected (the methods return
`bit_diameter` / `cut_depth` verbatim).

The isolation **pre-flight** (`analysis.find_narrow_gaps`, called from the GUI)
now receives `trace.effective_diameter()` instead of the raw `bit_diameter`, so
a V-bit no longer wrongly flags every 0.2 mm trace as un-millable.

## 4. Bed-leveling adherence (`engine/leveling.py`, `engine/diagnostics.py`)

**No leveling-engine change was needed.** `apply_leveling()` already warps each
move's Z so the cut depth stays uniform *relative to the local probed surface*.
For a V-bit, uniform depth ⇒ uniform width — exactly the invariant we want. The
export path (`doublesided._write(..., leveled=True)`, the GUI's "Apply bed
leveling on export") already runs every trace toolpath through it.

What V-bits add is a **hard requirement** that leveling actually be on, plus a
resolution recommendation:

- `diagnostics.cut_depths()` now reports the V-bit's *derived* depth (so the
  Z-reach check is honest about how far it really plunges).
- `diagnostics.preflight(..., trace=, leveled=)` adds a V-bit check: a **warning**
  if a V-bit job is about to run without a height map applied (it spells out the
  `dW/dD` amplification), and an OK note when leveling is on that reminds the
  operator to use a *dense* mesh so between-point interpolation residual stays
  inside the width budget. The GUI passes `leveled = level_chk.isChecked() and a
  height map exists`.

**Probe-resolution proposal (per `2026-06-25-progress-rework-and-probe-speed.md`).**
The firmware's two-phase approach made grid probing cheap (only the last ~1 mm is
fine-stepped per point), so a denser grid is essentially free in time. For V-bit
work, level over a **bilinear** grid (`HeightMap.from_grid`, i.e. a full
`nx×ny`), not a 3-point plane fit, at a point pitch of **≤ 10 mm** (≈ 7×7+ on a
typical board) so the interpolation residual between points stays well under the
width budget. Pair that with a **narrow bit (≤ 30°)** and **shallow depth** to
keep `dW/dD` small. These are operator/GUI choices, not engine constants — the
shipped `SRM-20 V-bit 30deg / 0.1 mm tip` preset encodes the bit/depth half, and
the preflight nags about the mesh half.

## 5. Preset

A second built-in profile: **`SRM-20 V-bit 30deg / 0.1 mm tip: 0.2 mm SMD traces
(LEVEL FIRST)`** — width-first 0.2 mm target on a 30°/0.1 mm-tip bit (≈ 0.187 mm
plunge), single isolation pass, slower feeds (3.0 / 0.5 mm/s). Drill and cut-out
stay on the 0.8 mm flat bit (a bit change between ops). The flat profile remains
first, so it stays the GUI default.

## 6. Tests

- `test_config.py` — the formula, its inverse, the clamp, and `dW/dD`.
- `test_traces.py` — `isolate()` cuts at the derived depth and isolates by the
  effective width (cross-checked against an equivalent flat bit).
- `test_form.py` — string fields round-trip; `choices` render as a combo.
- `test_diagnostics.py` — `cut_depths` uses the derived depth; the V-bit
  leveling warn/ok checks; flat tools add no V-bit check.
- `test_presets.py` — both built-in profiles, V-bit one is width-first.

Full suite: **322 passing** headless (`QT_QPA_PLATFORM=offscreen`).

## Files touched

```
gerber2rml/config.py            (edit) V-bit fields + geometry methods
gerber2rml/engine/traces.py     (edit) isolate() uses effective width/depth
gerber2rml/engine/diagnostics.py(edit) derived depth + V-bit leveling check
gerber2rml/analysis.py          (—)    unchanged; GUI now feeds it effective dia
gerber2rml/gui/form.py          (edit) string/combo field support + tooltips
gerber2rml/gui/app.py           (edit) tool_type combo, _sync_vbit_fields, preflight args
gerber2rml/app/presets.py       (edit) V-bit built-in preset
tests/test_{config,traces,form,diagnostics,presets}.py  (edit)
```
