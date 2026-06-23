# gerber2rml — standalone Gerber→RML CAM tool for the Roland SRM-20

**Date:** 2026-06-21
**Status:** Design — awaiting approval
**New repo:** `gerber2rml` (GitHub, owner MadsRudolph, private to start)
**Submodule mount in team repo:** `tools/srm-cam/`

## 1. Purpose

A self-contained desktop program that takes the Gerber/Excellon files KiCad already
exports for a board, lets the user pick a CNC machine and adjust milling variables
(bit diameter, cut depth, feeds, offsets, tabs…), and produces ready-to-run
toolpath files. First (and only initial) target machine: the Roland SRM-20, output
in **RML-1**. It replaces today's reliance on the mods website and FlatCAM with one
tool the team owns and controls.

This supersedes the `hardware/roland-cnc/` experiment on branch
`add-mosfet-test-board`; `gcode_to_rml.py` and its test fixtures migrate into the
new repo as the seed of the RML backend.

## 2. Scope

**In scope (v1):**
- Input: a folder of KiCad-exported Gerbers + Excellon drill file.
- Three operations, each exported as its own RML job:
  1. **Trace isolation** (B.Cu), multi-pass.
  2. **Drilling** (Excellon holes).
  3. **Board cutout** (Edge.Cuts) with holding tabs.
- **Single-sided** boards: isolate B.Cu mirrored for bottom-up milling; top nets
  are wire bridges (same as the laser flow / `SRM20_MILL.md`).
- Desktop GUI with editable variables and a toolpath **preview**.
- SRM-20 RML output, behind a **pluggable machine-backend interface** (one backend
  now; adding another machine = one new backend class).

**Out of scope (v1, explicitly):**
- Double-sided milling / flip registration.
- Generic G-code/GRBL output (the seam exists; not implemented yet).
- V-bit toolpaths, copper pour clearing optimisation beyond simple multi-pass.
- Auto tool-change sequencing (operator changes bit + re-zeros Z between jobs).

## 3. Architecture

Pure-logic core with **no GUI dependency** (headless-testable, scriptable later);
a thin PySide6 GUI on top.

```
Gerber/Excellon files ─┐
                       ▼
   loader            gerbonara → shapely geometry (mirror, unit detect)
                       ▼
   toolpath engine   traces  : union copper → buffer(+r, +r+stepover, …) passes
                     drill   : Excellon holes → peck-drill cycles
                     cutout  : Edge.Cuts → buffer(+r) outward + tabs
                       ▼
   machine backend   toolpaths → RML-1 (SRM-20)        ← pluggable seam
                       ▼
   <board>_traces.rml / <board>_drill.rml / <board>_cutout.rml
```

### Module layout

| Module | Responsibility | Depends on |
|---|---|---|
| `gerber2rml/loader.py` | Read Gerber + Excellon → shapely geometry; mirror; detect units | gerbonara, shapely |
| `gerber2rml/engine/traces.py` | Copper → multi-pass isolation toolpaths | shapely |
| `gerber2rml/engine/drill.py` | Excellon → grouped peck-drill sequence | — |
| `gerber2rml/engine/cutout.py` | Edge.Cuts → outline cut + tabs | shapely |
| `gerber2rml/backends/base.py` | Abstract `MachineBackend` interface | — |
| `gerber2rml/backends/srm20.py` | Toolpaths → RML-1 | — |
| `gerber2rml/config.py` | `Job` / `Tool` dataclasses + SRM-20 defaults | — |
| `gerber2rml/gui/` | PySide6 window, fields, matplotlib preview, export | core |
| `tests/` | Unit tests per engine + a golden RML diff vs mods | pytest |

Inter-module contract: plain shapely geometry + `Job` dataclasses. No module reads
another's internals.

## 4. Toolpath engine

- **Traces:** union B.Cu copper; pass *i* path = boundary of
  `copper.buffer(r + i·stepover)`, `r` = bit radius. `offsets = -1` ⇒ buffer until
  no copper-free gap remains (full clear). GEOS handles acute angles / self-intersections.
- **Drill:** group holes by diameter → bit; peck-plunge to board thickness with
  retracts. Hole-larger-than-bit ⇒ warn (no helical interpolation in v1).
- **Cutout:** Edge.Cuts outline buffered **outward** by `r`; insert N tabs (un-cut
  gaps) of configurable width; multi-pass to `thickness + 0.2 mm`.
- Copper-side/invert convention is taken automatically from the Gerber layer — no
  manual black/white inversion step (the thing mods makes you do by hand).

### Exposed variables (per job; SRM-20 defaults)

| Variable | Traces | Drill | Cutout |
|---|---|---|---|
| Bit diameter | 0.4 mm (1/64") | per hole | 0.8 mm (1/32") |
| Cut depth / pass | 0.10 mm | 0.6 mm peck | 0.6 mm |
| Total depth | — | 1.8 mm | 1.8 mm |
| Isolation offsets | 2 (`-1` = clear all) | — | — |
| Stepover | 0.5 × bit | — | — |
| XY feed (`VS`) | 4 mm/s | 4 mm/s | 4 mm/s |
| Plunge feed (`!VZ`) | 1 mm/s | 1 mm/s | 1 mm/s |
| Travel / jog Z | 2 mm | 2 mm | 2 mm |
| Tabs | — | — | 4 × 1.5 mm |
| Mirror (bottom-up) | ✓ | ✓ | ✓ |

Global: board thickness (1.6 mm), output directory.

## 5. GUI (PySide6)

Single window:
- **Top:** "Load Gerber folder…" button + detected file list (which layer mapped to
  what); machine dropdown (SRM-20 only for now).
- **Left:** tabbed parameter panels (Traces / Drill / Cutout), fields pre-filled
  with defaults from §4.
- **Centre:** matplotlib canvas previewing copper + generated toolpaths per
  operation (toggle layers). Regenerates on parameter change.
- **Bottom:** "Export .rml" → writes the three job files to the output dir, plus a
  short run-plan note (bit order, re-zero reminders) mirroring `SRM20_MILL.md`.

Preview is read-only (no on-canvas editing in v1).

## 6. Machine backend (RML-1) — correctness

The SRM-20 backend generates RML directly. It fixes the bugs found in the current
`gcode_to_rml.py`:

1. **Spindle ON:** header must use `!MC1;` (the RML-1 manual: `!MC0` *disables*
   spindle rotation). Current code uses `!MC0` everywhere — bit never spins.
2. **Feeds:** set XY feed via `VS` and plunge via `!VZ` (the manual's `V` is Z
   up/down speed, not XY). Current single `V15` is wrong and too fast.
3. **Modal handling N/A here** (we emit moves from clean internal toolpaths, not by
   re-parsing modal G-code), which also removes the dropped-modal-line risk.
4. **Units:** SCALE = 100 RML units/mm (SRM-20 RML-1 software resolution =
   0.01 mm/step, manual p.151). NOT 0.025 mm/unit — that is the older
   MODELA/HP-GL RML dialect and makes the job come out at 40% size.
5. **Clean header/footer:** Z-up only at start (no bogus `Z1168,1168,1168` rapid);
   lift before `!MC0`; optional park move.

## 7. Error handling

- Missing/unrecognised layer (no B.Cu, no Edge.Cuts) → clear GUI error, no export.
- Excellon hole with no matching bit → warn, list the diameters, still export the
  rest.
- Inch-unit or unexpected Gerber → detect and either convert or refuse with a
  message (never silently mis-scale).
- Geometry that fails to buffer (degenerate) → report which net/region, continue.

## 8. Testing

- Unit tests per engine module on small synthetic geometries (a square pad, two
  close traces, one hole) with asserted toolpath counts/extents.
- **Golden test:** run one real board (`mosfet_test`) through both this tool and the
  mods website; diff the resulting RML move set to confirm parity before trusting
  it on the machine.
- Backend test: assert `!MC1` present, `VS`/`!VZ` set, correct unit scaling.

## 9. Repo & submodule mechanics

1. Create the new repo `gerber2rml` (MadsRudolph, private). Seed it with the
   migrated `gcode_to_rml.py` + test fixtures, a `pyproject.toml`
   (deps: gerbonara, shapely, PySide6, matplotlib, pytest), README, and the module
   skeleton from §3.
2. In the team repo:
   `git submodule add git@github.com:MadsRudolph/gerber2rml.git tools/srm-cam`
   then commit the `.gitmodules` + gitlink. Remove the loose
   `hardware/roland-cnc/` files (now superseded) in the same change.
3. Document in team-repo `CLAUDE.md` / `hardware/kicad/WORKFLOW.md`: how to
   `git submodule update --init`, and that `tools/srm-cam/` is the SRM-20 path
   alongside the laser flow.

## 10. Milestones (for the implementation plan)

1. New repo scaffold + deps + migrated RML backend (bugs fixed) + backend tests.
2. Loader (gerbonara → shapely, mirror, units).
3. Trace isolation engine + tests.
4. Drill + cutout engines + tests.
5. PySide6 GUI + matplotlib preview wiring.
6. Golden parity test vs mods on `mosfet_test`.
7. Add as submodule at `tools/srm-cam/`; update docs.
