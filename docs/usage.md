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

Sources, merged by name (later overrides earlier):

| Layer | Where | Who owns it |
|---|---|---|
| Built-in | in the code | us |
| **Site** | next to `SRM-CAM.exe` (installed) or `examples/presets.json` (source) | the lab owner — needs admin to change |
| Personal | `~/.gerber2rml/presets.json` | whoever clicked **Save** |

**Site presets** are how a course hands the same approved numbers to every
seat instead of talking thirty people through them. Copy
`presets.example.json` to `presets.json` in the install folder and edit it.
Keys starting with `_` are settings, not profiles:

- `"_hide_builtins": true` — show **only** the site profiles.
- `"_comment": "..."` — JSON has no comments; this is the stand-in.

Point `SRM_CAM_PRESETS` at another path to read the site layer from a shared
network folder instead.

## Novice and Professional modes

**Mode** menu. Novice is the default on a fresh install.

**Novice** is the shortest path from Gerbers to three files you can send from
VPanel: load → drill → traces → cut out → export. It puts away job parameters,
double-sided, bed leveling, rework, machine control, and the output-format and
mirroring options. Diagnostics and the Guide stay — a beginner needs the
pre-flight check and the walkthrough more than anyone.

**Professional** is every control, i.e. the UI as it has always been.

Novice is a strict subset, not a second program: same widgets, same handlers,
same exports. The same settings produce byte-identical files in either mode
(`tests/test_mode.py`), so a student's board and a teacher's board come out the
same.

Switching is a menu item, not a password — this manages complexity, it is not
a security boundary. To pin a machine to one mode, set the `SRM_CAM_MODE`
environment variable to `novice` or `pro` (system-wide, or in the shortcut that
launches the app); the menu then shows the active mode greyed out.

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
bed or bowed board. Set the **G54 Z** origin in VPanel (only Z — X/Y stay at the
machine origin; keep machine Z above −50 mm), then build a grid and probe.

> **This is the one feature that needs the Arduino.** Traces, drilling, cut-out,
> double-sided registration, rework and every export work on a bare SRM-20 with
> nothing fitted to it — see [Milling without the Arduino](#milling-without-the-arduino).

### Hardware setup (one-time)

Auto bed leveling drives the machine over its internal SPI bus and senses contact
with a touch probe, so it needs a small board fitted inside the SRM-20:

1. **Open the SRM-20's back panel** and seat an **Arduino Uno**, on its SPI
   shield, on the controller's **SPI remote header** — the connector Roland put
   there for exactly this (full wiring in
   [2026-06-25-srm20-spi-and-bed-leveling.md](2026-06-25-srm20-spi-and-bed-leveling.md)).
   Nothing is drilled, cut or soldered: the shield plugs in, and unplugging it
   returns the machine to stock.
2. **Flash the provided firmware:** `hardware/srm20_spi_probe/srm20_spi_probe.ino`
   (needs the bundled `hardware/SRM20SPIRemote` library).
3. **Probe wiring:** connect **D7 → the copper board** (the workpiece — it floats
   HIGH on the Uno's internal pull-up). That is the only clip: the tool is already
   grounded through the collet/spindle to the machine frame, which the Uno shares.
   Put paper or tape under the board so it's **electrically isolated from the bed**:
   the only path to ground is the bit touching copper, which pulls D7 LOW = contact.

> With an alligator clip during probing: **red → copper board** (D7, the signal
> side). No clip on the tool — the ground path is the machine itself.

### Probing

In the GUI, connect to the Uno, build a grid, and **Probe over SPI** — the bit
taps each point and records its true height into the table; the engrave depth then
follows the surface. You can also save/load the height map as CSV.

## Keeping the copper and the machine in sync

The machine cuts where the **G54 work origin** says, and nothing tells it where
your copper actually is. Normally a person jogs the spindle to the corner of the
stock and calls that zero — a sheared edge, judged by eye, differently by every
student. Two things go wrong:

- the cut lands a millimetre or two off the copper, or off it entirely;
- worse, if the origin moves *between passes*, traces / drill / cut-out stop
  registering **with each other**. Every pass looks fine and the board is scrap.

Neither needs the Arduino to fix. Three parts:

### 1 · Let the machine drill its own datum

**Copper stock → Export bed fixture (pin holes)...** (Professional mode) writes a
program that drills **three Ø3 mm dowel-pin holes** into the sacrificial bed,
plus a `.txt` telling the operator what to do with them. Press pins in, push the
copper against them, tape it down — the stock's front-left corner now lands on
the work origin **every time**, with nothing measured by eye.

It works because anything the machine cuts is *already* in machine coordinates.
A jig you bolt down sits somewhere unknown until you measure it; a hole the
machine drilled sits exactly where it was told.

Three pins, not four — **3-2-1 locating**: two along the bottom edge fix rotation
and Y, one on the left edge fixes X. A fourth has nothing left to constrain and
can only fight the others. Pins rather than a milled corner because an inside
corner packs with chips, and a chip behind the stock is the exact error being
removed here.

Cut **once per sacrificial bed**, by whoever owns the machine — which is why it
is Professional-only. Students get the pins, not the ability to drill more holes
in a shared bed.

### 2 · Never move XY again

Re-zero **Z** after every bit change. Never XY. The fixture makes this practical:
there is no reason to touch XY once the pins are in.

### 3 · Prove it before you cut — the dry run

Every export writes **`<name>_airpass.nc`**, and it is step 0 in the run plan.
Spindle **off**, bit held 5 mm up, tracing the board outline at a feed slow
enough to watch. If the stock is misplaced you see the bit leave the copper and
you stop — having spent seconds instead of a board.

This is the part that actually answers *"is it aligned?"*, it needs no hardware
at all, and it is worth running before **every** job, fixture or not.

> **One thing to check on your machine:** whether the SRM-20 keeps its user
> origin across a power cycle. If it does, set XY zero once per term against the
> fixture and never again. If it does not, the daily ritual is "seat the bit in
> pin hole 1, set origin" — still far better than finding a sheared stock corner
> by eye, because a drilled hole is a crisp feature you can drop a bit into.

## Milling without the Arduino

A bare, unmodified SRM-20 with nothing but VPanel is a fully supported setup, and
it is what **Novice mode assumes** — the machine link is hidden there entirely.
Everything below works with no board fitted to the machine:

| Works unchanged | Needs the Arduino |
|---|---|
| Trace isolation, drilling, cut-out | Automatic probing over SPI |
| Double-sided registration — dowel pins *and* fiducials | Live DRO / click-to-jog |
| Rework, photo check, 3D simulation, diagnostics | Electrical touch-off (`Probe Z`) |
| Bed fixture + the dry-run outline (see above) | `Corner = tool` |
| Presets, calibration coupon, every export | |

**Bed leveling still works without it** — manually. Build the grid, click
**Export probe files...**, and the app writes one tiny G-code program per point
plus a checklist. Run each in VPanel, read the Z off the display at contact, and
type it into the **Z** column of the leveling table (X/Y are read-only; Z is
yours to fill). From there the height map, the depth advice and the warped export
behave exactly as they do after an automatic probe.

It is slower — that clunkiness is precisely what motivated the SPI work — but no
capability is lost, and nothing in the exported toolpaths differs.

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
