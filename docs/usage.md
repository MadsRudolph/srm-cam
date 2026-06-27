# SRM-CAM — usage & reference

Detailed reference moved out of the README. The in-app **Guide** (first-launch
tour, replayable per section) covers most of this interactively.

## Operations

Three operations, each exported as its own job:

1. **Trace isolation** (B.Cu, mirrored for bottom-up milling) — multi-pass, or
   full copper clearing with `offsets = -1`.
2. **Drilling** (Excellon) — one file per diameter, or one file using a single bit.
3. **Board cut-out** (Edge.Cuts) with holding tabs.

### Drilling modes

Pick per export on the **Drill** tab (`single bit` checkbox + `bit diameter`):

- **Per-diameter (default):** one file per hole diameter, smallest first
  (`<name>_drill_0.8mm.nc`, …), each **plunge-drilled** with a matching bit.
- **Single bit:** one file, one small end mill. Matching holes are **plunged**;
  larger holes are **interpolated** (tool circles out to size); smaller holes are
  plunged at bit size and flagged in the status bar.

### Isolation preflight & copper clearing

- On the **Traces** tab, gaps narrower than the bit show in **red** with a status
  warning — channels the bit can't isolate (potential shorts).
- **offsets = -1** fully clears background copper (concentric pocketing clipped to
  the outline) — the laser-equivalent "rubout". Slower (many passes).

## G-code (NC) output

**G-code is the default** (machine *"Roland SRM-20 (G-code)"*, `.nc`): real-mm
coordinates, standard **G54** work origin. RML (`.rml`) is a fallback — pick
*"Roland SRM-20"* in the **Machine** dropdown or `--gcode` on the CLI.

VPanel streams the `.nc` like RML (`Cut → Add → Output`) in **NC-code command
mode**. Coordinates reference the **G54** origin (= VPanel's user origin); the
header issues `G49` to clear any stale tool-length offset. Moves are pre-linearised
`G0`/`G1` (no arcs/canned cycles). Validated on hardware 2026-06-22.

## Presets

Reuse a bit + feeds/speeds set across all three operations in one click. In the
GUI: **Preset** dropdown → **Apply** → tweak → **Save** under a new name.

Built-in (opens applied): **`SRM-20 0.8 mm flat`** — one 0.8 mm flat endmill for
traces, drilling and cut-out on a ~1.6 mm board; drill/cut-out depth 1.7 mm
(0.1 mm into the spoilboard). Solid carbide, VPanel spindle ~7000 RPM, dust
extraction + mask for FR-4.

Sources, merged by name (later overrides earlier): built-in → `examples/presets.json`
(team-shared) → `~/.gerber2rml/presets.json` (personal, written by Save).

## Calibration coupon

A bundled 40×30 mm board exercising every operation. Load without KiCad:

```bash
python -m gerber2rml.cli examples/calibration -o out -n calib   # or GUI: File → Open → examples/calibration
```

Isolation pairs at 0.8 mm clearance, a drill size row + 10 mm registration grid
(measure with calipers), a 6 mm roundness ring, and a tabbed cut-out. Regenerate
from `gerber2rml/examples/calibration.py` (`write_coupon(out_dir)`).

## Bed leveling

Probe the copper surface to build a height map so engrave depth follows an uneven
bed or bowed board. Connect the Arduino probe, set the **G54 Z** origin in VPanel
(only Z — X/Y stay at the machine origin; keep machine Z above −50 mm), clip
**red → copper plate, black → drill bit**, then build a grid and probe. See
[2026-06-25-srm20-spi-and-bed-leveling.md](2026-06-25-srm20-spi-and-bed-leveling.md).

## Rework (multi-region 2nd pass)

Mark **all** spots to re-cut and export them as **one** G-code file. On the
**Rework** page: tick **Add areas**, drag a box over each spot (own colour + table
row). Each row has its **own depth** (the **New-box depth** spin sets the next
box's default) and a height-map-follow toggle. **Export rework NC** writes one
`<name>_<side>_<op>_rework.nc`. See
[2026-06-26-multi-region-rework.md](2026-06-26-multi-region-rework.md).

## Double-sided boards

Top/bottom passes align off machine-located holes, never the board edge. Tick
**Double-sided** (needs an **F.Cu** layer), then pick a **Method**:

- **Dowel pins** (default, proven) — the mill drills holes through the stock *into
  the sacrificial bed*; seat pins and flip the board onto them. Zero measurement,
  sub-0.1 mm.
- **Fiducial holes** — the mill drills 2–4 *stock-only* corner holes; flip and
  re-place freely (no pins), probe where they landed, and the top traces warp to
  the best-fit transform. See
  [2026-06-26-fiducial-registration.md](2026-06-26-fiducial-registration.md).

### How the flip works (dowel)

The board flips **left-to-right about a vertical axis**. The bottom is milled
mirrored; reflecting the front copper about that same axis **cancels** the mirror,
so the **top is cut as plain F.Cu** and still registers. The two dowels sit **on
the flip axis** (one above, one below the board), invariant under the flip.

> **Preview vs. export.** The preview shows both layers in the *design* frame (so
> they register on-screen); the exported job carries the real machine geometry
> (mirrored bottom, reflected-to-plain top). Both are correct.

### Registration modes

| | **Fresh-milled dowels** (default) | **Grid-seated pins** |
|---|---|---|
| Pins live in | fresh holes drilled through stock **into the bed** | the bed's **threaded grid** |
| Pins | **Ø2 + Ø3 mm** dowels | **Ø4 mm** grid pins |
| Keyed by | **different diameters** | **asymmetric spacing** (+ mark bottom edge) |
| Depends on grid accuracy | **no** | **yes** (pitch + datum ~±0.2 mm) |

Dowels sit just outside the Edge.Cuts rectangle, in stock the cut-out discards —
zero design-area cost.

### Output files

A `<name>_runplan.txt` (read first) plus `<name>_align.<ext>` (dowel holes),
`<name>_bottom_drill_<dia>mm.<ext>`, `<name>_bottom_traces.<ext>` (mirrored),
`<name>_top_traces.<ext>` (plain F.Cu, reflected), `<name>_cutout.<ext>`.

### Operator sequence (essentials)

Set XY zero once (fresh: stock corner; grid: datum hole), **never re-zero XY**
between jobs, **re-zero Z** after every bit change *and* the flip. Run `_align` →
seat pins → bottom drill + `_bottom_traces` → **flip left-to-right onto pins** →
`_top_traces` → `_cutout` **last**. Exact sizes are in the run-plan.

## Architecture

```
Gerber/Excellon ─► loader (gerbonara→shapely) ─► engine (traces/drill/cutout)
                ─► backend (SRM-20 G-code/RML) ─► <board>_{traces,drill,cutout}.{nc,rml}
```

| Package | Responsibility |
|---|---|
| `gerber2rml/loader.py` | Gerber + Excellon → shapely geometry; mirror; unit detect |
| `gerber2rml/engine/` | traces (isolation), drill (grouped peck), cutout (outline + tabs) |
| `gerber2rml/backends/` | toolpaths → G-code / RML (`BACKENDS` registry) |
| `gerber2rml/config.py` | job/board dataclasses + SRM-20 defaults |
| `gerber2rml/gui/` | PySide6 window, preview, 3D views, guided tour |

Full design notes: [design.md](design.md).
