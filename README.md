# gerber2rml

Standalone desktop CAM tool that turns KiCad-exported **Gerber + Excellon** files
into ready-to-run toolpaths for the **Roland SRM-20** desktop mill (RML-1 output).

It replaces the team's reliance on the mods website and FlatCAM with a single
program we own and control: load a board's Gerbers, pick the machine, adjust the
milling variables (bit diameter, cut depth, feeds, offsets, tabs), preview, and
export the `.rml` jobs.

## Status

Functional. CLI + PySide6 GUI with live preview, presets, isolation preflight,
report export, single- and double-sided boards, and two drilling modes. The
architecture lives in [`docs/design.md`](docs/design.md).

## What it does

Three operations, each exported as its own RML job:

1. **Trace isolation** (B.Cu, mirrored for bottom-up milling) — multi-pass, or
   full copper clearing with `offsets = -1`.
2. **Drilling** (Excellon holes) — split into one file per diameter, or a single
   file using one bit (plunge + interpolate). See [Drilling modes](#drilling-modes).
3. **Board cutout** (Edge.Cuts) with holding tabs.

Plus **double-sided** boards with dowel-pin registration (see below). SRM-20 is
the only machine today, but output sits behind a pluggable `MachineBackend`
interface so adding another CNC is one new backend.

## Drilling modes

Different hole sizes need different handling on a single-spindle mill. Pick per
export on the **Drill** tab (`single bit` checkbox + `bit diameter` field):

- **Per-diameter (default):** one file per hole diameter, smallest first
  (`<name>_drill_0.8mm.rml`, `<name>_drill_1.0mm.rml`, …), each **plunge-drilled**
  with a matching bit. Change the bit between files.
- **Single bit:** one file using one small end mill. Holes that match the bit are
  **plunged**; holes larger than the bit are **interpolated** (the tool circles
  out the hole to size). No bit changes. Holes smaller than the bit can't be made
  smaller — they're plunged at bit size and flagged in the status bar.

## Architecture

```
Gerber/Excellon ─► loader (gerbonara→shapely) ─► engine (traces/drill/cutout)
                ─► backend (SRM-20 RML) ─► <board>_{traces,drill,cutout}.rml
```

| Package | Responsibility |
|---|---|
| `gerber2rml/loader.py` | Read Gerber + Excellon → shapely geometry; mirror; unit detect |
| `gerber2rml/engine/traces.py` | Copper → multi-pass isolation toolpaths |
| `gerber2rml/engine/drill.py` | Excellon → grouped peck-drill sequence |
| `gerber2rml/engine/cutout.py` | Edge.Cuts → outline cut + tabs |
| `gerber2rml/backends/base.py` | `RenderFn` callable type (machines registered in `backends/__init__.py` `BACKENDS`) |
| `gerber2rml/backends/srm20.py` | Toolpaths → RML-1 |
| `gerber2rml/config.py` | `TraceJob` / `DrillJob` / `CutoutJob` / `BoardConfig` dataclasses + SRM-20 defaults |
| `gerber2rml/gui/` | PySide6 window, fields, matplotlib preview, export |

## Install (development)

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Keep your environment up to date

After every `git pull`, run the **doctor** to install any newly added packages so
the GUI always works — it reads the dependencies from `pyproject.toml`, reports
what's missing, and installs it for you:

```bash
python -m gerber2rml.doctor          # check, then install anything missing
python -m gerber2rml.doctor --check  # only report (don't install)
python -m gerber2rml.doctor --dev    # also install the test (dev) extras
```

It only needs the standard library to start, so it works even on a brand-new
checkout where nothing is installed yet. (After an install it's also available as
the `gerber2rml-doctor` command.)

## Run

Headless CLI (Plan A):

```bash
python -m gerber2rml.cli <gerber-folder> -o out -n <boardname>
# after `pip install`, also available as:  gerber2rml-cli <gerber-folder> -o out -n <boardname>
```

GUI:

```bash
pip install -e ".[gui]"
python -m gerber2rml         # or the `gerber2rml` launcher after install
```

## G-code (NC) output — for VPanel's NC-code mode

**G-code is the default** (machine **"Roland SRM-20 (G-code)"**, `.nc`) — it's what
we run on the SRM-20: real-millimetre coordinates and a standard **G54** work
origin. RML (`.rml`) remains available as a fallback: pick **"Roland SRM-20"** in
the GUI **Machine** dropdown, or drop `--gcode` on the CLI. To emit G-code
explicitly on the CLI:

```bash
python -m gerber2rml.cli <gerber-folder> -o out -n <boardname> --gcode
```

VPanel streams the `.nc` the same way as RML (`Cut -> Add -> Output`) when the
machine is in **NC-code command mode**. Coordinates reference the **G54** work
origin (= VPanel's user origin); the header issues `G49` to clear any tool-length
offset left active by a prior job. Moves are pre-linearised `G0`/`G1` (no arcs or
canned cycles). Validated on hardware 2026-06-22: clean isolation at 0.15 mm with
a sharp flat endmill.

## Tests

```bash
pytest
```

## Calibration & presets

### Calibration coupon

A bundled example you can load immediately to validate the whole pipeline and
your machine setup in a single job. Load it without KiCad:

```bash
python -m gerber2rml.cli examples/calibration -o out -n calib
# or in the GUI: File → Open → <repo>/examples/calibration
```

The coupon is a **40×30 mm PCB** that exercises all operations:

- **Isolation traces:** Three trace pairs at 0.8 mm clearance, checking that
  the 1/64" isolation bit does not bridge.
- **Drilling:** A size row (one 0.8 mm and one 1.0 mm hole) to verify tool
  selection, plus a 10 mm grid of 0.8 mm holes for registration.
- **Registration grid:** Measure hole-to-hole spacing with calipers to verify
  steps/mm and alignment with copper features.
- **Roundness test:** A 6 mm ring/pad to check spindle backlash.
- **Cutout:** Rectangular board outline with holding tabs.

The coupon Gerber/Excellon files are regenerated from `gerber2rml/examples/calibration.py`
(call `write_coupon(out_dir)` in Python). Keeping the generator side-by-side with
the files lets you extend or adapt the coupon for your own validation needs.

### Presets

Reuse a complete bit and feeds/speeds set across all three operations (traces,
drill, cutout) in one click.

**In the GUI:**
- Click the **Preset** dropdown to choose a saved preset.
- Click **Apply** to load it into all three operation tabs at once.
- Modify as needed, then click **Save** to store under a new name.

**Built-in preset** (the GUI opens with it applied):
- `SRM-20 0.8 mm flat` — the one profile we use: a single **0.8 mm flat endmill**
  for traces, drilling and cut-out on a ~1.6 mm board. Drill/cut-out depth is
  **1.7 mm** (0.1 mm through into the spoilboard — not deeper, so the bed isn't
  gouged). Use a **solid carbide** bit, set VPanel spindle to max (~7000 RPM), and
  run **dust extraction + a mask** for FR-4. Dial in with the calibration coupon.

**Preset sources** (merged by name; later overrides earlier):
1. **Built-in:** embedded in code (the `SRM-20 0.8 mm flat` profile).
2. **Repo examples:** `examples/presets.json` — team-shared presets (tracked in git; empty by default).
3. **User home:** `~/.gerber2rml/presets.json` — your personal presets, written by Save.

## Preflight, reports & clearing

### Isolation preflight

When previewing the **Traces** tab, copper-free gaps narrower than the bit are shown in **red** and a warning appears in the status bar. These are channels the bit physically cannot isolate — potential shorts. Fix the layout or use a smaller bit.

### Robust drilling

The loader prefers KiCad's split `-PTH`/`-NPTH` drill files over a stale combined `<board>.drl`, dedupes, and drops holes outside the board outline. Leftover or mismatched drill files in a gerber folder no longer produce phantom holes.

### Report export

The **Export image** button saves the current preview as `<name>_preview.png` plus a `<name>_preview_summary.md` (board size, copper area, hole table) — handy for documentation.

### True copper clearing

Setting **offsets = -1** on the **Traces** tab now fully clears the background copper (concentric pocketing clipped to the board outline, terminating when done) instead of just cutting isolation channels. This is the laser-equivalent "rubout", useful for ground-pour boards. It is slower (many passes).

## Rework (multi-region 2nd pass)

When a first pass leaves copper not fully isolated, mark **all** the spots to
re-cut at once and export them as a **single** G-code file. On the **Rework**
page: tick **Add areas**, then drag a box over each spot — every box appears as a
distinct coloured square and a row in the table. Each row has its **own depth**
(the **New-box depth** spin sets the default for the next box; edit any row after)
and its own **height-map follow** toggle (`lvl`), so stubborn areas can cut deeper
while the rest repeat the first pass. **Export rework NC** writes one
`<name>_<side>_<op>_rework.nc` covering every region; **Clear all** or the per-row
**X** remove regions. The live run-progress bar and the 3D simulation both cover
the whole multi-region job. See
[docs/2026-06-26-multi-region-rework.md](docs/2026-06-26-multi-region-rework.md).

## Double-sided boards

For two-sided PCBs, gerber2rml uses **dowel-pin registration** to align the top and bottom milling passes — it references machine-located holes, never the board edge (sheared FR-4 is never truly square). Tick the **Double-sided** checkbox in the GUI before exporting (requires an **F.Cu** layer) and pick a registration mode in the **Reg.** dropdown.

### How the flip works

The board flips **left-to-right about a vertical axis**. The bottom is milled mirrored (bottom-up, copper facing the spindle). Reflecting the front copper about that same axis **cancels** that mirror, so the **top is cut as the plain, un-mirrored F.Cu** and still registers after the flip. The two dowels sit **on the flip axis, one above and one below the board**, so they are invariant under the flip — the board lifts off the pins, flips, and drops back onto them.

> **Preview vs. export.** The on-screen preview shows both layers in the *design* frame (the way KiCad overlays them) so they register and the holes land on the pads. The exported RML carries the real machine geometry (mirrored bottom, reflected-to-plain top). Both are correct — they serve different purposes.

### Two registration modes

| | **Fresh-milled dowels** (default) | **Grid-seated pins** |
|---|---|---|
| Where the pins live | fresh holes the mill drills through the stock **into the sacrificial bed** | the bed's **threaded grid** holes (nothing fresh drilled) |
| Pins | **Ø2 + Ø3 mm** ground dowel pins | **Ø4 mm** pins in the grid (e.g. M4 grid) |
| Keyed so it can only seat one way | by **different diameters** | by **asymmetric spacing** (+ mark the bottom edge) |
| Alignment depends on the grid | **no** — both sides reference the same machine-made hole | **yes** — needs the pitch + datum origin accurate (~±0.2 mm) |
| Set the grid pitch | — | enter the measured **pitch** and **pin** Ø next to the dropdown |

**Fresh** is the more accurate, foolproof choice and works on any board with a few mm of blank outside the cut. **Grid-seated** trades some accuracy for reusable pins you never re-drill. In both modes the dowels sit **just outside the Edge.Cuts rectangle**, in stock the cut-out discards — they cost zero design area; you only shear the copper blank a little oversized on two edges.

### Output files

A double-sided job produces a `<name>_runplan.txt` (mode-specific, read it first) plus:

- `<name>_align.<ext>` — the two dowel holes (interpolated to size with the endmill)
- `<name>_bottom_drill_<dia>mm.<ext>` — board holes (one per diameter, or one `<name>_bottom_drill.<ext>` in single-bit mode)
- `<name>_bottom_traces.<ext>` — isolate bottom copper (B.Cu, mirrored)
- `<name>_top_traces.<ext>` — isolate top copper (**plain F.Cu**, reflected about the pin axis)
- `<name>_cutout.<ext>` — cut the board outline with holding tabs

### Operator sequence (essentials)

Set XY zero once (fresh: stock corner; grid: the datum grid hole), **never re-zero XY** between jobs, and **re-zero Z** after every bit change *and* after the flip. Run `_align` and seat the pins → bottom drill + `_bottom_traces` → **flip left-to-right onto the pins** → `_top_traces` → `_cutout` **last**. The exact pin sizes, grid cells and stock size are written into the run-plan.

### Validation

Before a real board, mill the bundled calibration coupon double-sided to check registration:

```bash
python -m gerber2rml.cli examples/calibration -o out -n calib
```

The coupon has an F.Cu side with pads on every through-hole plus an asymmetric corner marker. After milling and flipping, the top pads should ring their holes concentrically. Registration is bounded by the SRM-20's repeatability (~0.05–0.1 mm) and dowel-pin fit — so dial the dowel-hole size to your pins on the coupon first.
