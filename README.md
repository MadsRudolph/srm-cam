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

**Built-in presets** (the GUI opens with **FR-4** applied):
- `FR-4 (1.6 mm)` — conservative feeds for abrasive glass-fibre on the SRM-20
  (~7000 RPM max): traces 1.5 mm/s feed / 0.5 mm/s plunge, drill/cutout in 0.4 mm
  pecks. Use **solid carbide** bits, set VPanel spindle to max, and run **dust
  extraction + a mask** (FR-4 dust is harmful). Dial up with the calibration coupon.
- `FR-1` — faster feeds (4 mm/s) for soft phenolic blanks.

**Preset sources** (merged by name; later overrides earlier):
1. **Built-in:** embedded in code (`FR-4` default, `FR-1`).
2. **Repo examples:** `examples/presets.json` — team-shared presets (tracked in git).
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

## Double-sided boards

For two-sided PCBs, gerber2rml uses **dowel-pin registration** to align the top and bottom milling passes. Tick the **Double-sided** checkbox in the GUI before exporting (requires an **F.Cu** layer).

### How the flip works

The board flips **left-to-right about a vertical axis** through its centre. The bottom is milled mirrored (bottom-up, copper facing the spindle). Reflecting the front copper about that same axis **cancels** that mirror, so the **top is cut as the plain, un-mirrored F.Cu** and still registers after the flip. The two dowel pins sit **on the flip axis, above and below the board**, and you flip left-to-right onto them.

> **Preview vs. export.** The on-screen preview shows both layers in the *design* frame (the way KiCad overlays them) so they register and the holes land on the pads. The exported RML carries the real machine geometry (mirrored bottom, reflected-to-plain top). Both are correct — they serve different purposes.

### Output files

A double-sided job produces a runplan plus:

- `<name>_align.rml` — drill the two 3.0 mm alignment (dowel) holes, deeper than the board
- `<name>_bottom_drill_<dia>mm.rml` — board holes through the bottom (one per diameter, or one `<name>_bottom_drill.rml` in single-bit mode)
- `<name>_bottom_traces.rml` — isolate bottom copper (B.Cu, mirrored)
- `<name>_top_traces.rml` — isolate top copper (**plain F.Cu**, reflected about the pin axis so it registers after the flip)
- `<name>_cutout.rml` — cut the board outline with holding tabs

### Operator sequence

0. **Zero once:** Set the machine XY origin a single time (e.g. the stock lower-left corner) and do **not** re-zero between jobs — registration comes from the pins.

1. **Drill alignment holes:** Run `_align.rml` to create the two 3.0 mm holes — through the board **and ~4–5 mm into the sacrificial bed** (default 6 mm total, deeper than the board holes). Seat 3.0 mm dowel pins.

2. **Mill bottom side:** Run the `_bottom_drill_*.rml` file(s) (change bit between diameters), then `_bottom_traces.rml` (B.Cu).

3. **Flip and re-register:** Flip the board **left-to-right about the vertical pin line**. It drops back onto the dowels.

4. **Mill top side:** Run `_top_traces.rml`. It's the plain F.Cu, already reflected so it aligns after the flip.

5. **Cut out:** Run `_cutout.rml` last to separate the board.

### Pin placement

The two pins are on a vertical axis through the board centre, **above and below the board**, beyond the 104 mm jig box (or beyond the board if taller), so they never enter the milling area. Leave ~6 mm of waste margin around the design box so the pins have a safe landing zone.

### Validation

Before a real board, mill the bundled calibration coupon double-sided to check registration:

```bash
python -m gerber2rml.cli examples/calibration -o out -n calib
```

The coupon has an F.Cu side with pads on every through-hole plus an asymmetric corner marker. After milling and flipping, the top pads should ring their holes concentrically. Registration is bounded by the SRM-20's repeatability (~0.05–0.1 mm) and dowel-pin fit.
