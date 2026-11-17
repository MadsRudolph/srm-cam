# SRM-CAM — usage & reference

Detailed reference moved out of the README. The in-app **Guide** (first-launch
tour, replayable per section) covers most of this interactively.

## Running on Linux

The Linux build is an AppImage — one file, `chmod +x`, run. See the README for
the download link. It carries its own Qt, so the distribution's version does
not matter, and it needs no root.

Everything that turns Gerbers into toolpaths works exactly as it does on
Windows: load, check, place, level, export. The run plan, the shorts check and
the double-sided flow are all the same code and produce the same files.

**The machine link is Windows-only.** No Connect, no DRO, no jogging, no
probing the bed over the Arduino. This is deliberate: the CNC PC is Windows,
that link has only ever been run there, and an unverified motion path is not
something to hand someone standing next to a spinning tool.

### Levelling a board you prepared on Linux

A height map is a file, so you do not lose levelling — only measuring.

1. On the CNC PC, probe the bed as usual and use **Save CSV** to write the
   grid to a file.
2. Keep that CSV with the board's session files.
3. On Linux, open the Bed leveling page and use **Load CSV**. Export as normal: the
   toolpaths are warped through the loaded grid exactly as if you had probed
   them on this machine.

A bed does not move between sessions, so one probe run serves every job on that
sheet.

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

## Several boards on one sheet

Two or more Gerber folders, cut from one piece of copper in one run.

- **Add:** File ▸ *Add another board to the sheet…* (Ctrl+Shift+O), or *Add
  another board…* on the setup page. The same folder twice makes two of the
  board (`buck`, `buck 2`).
- **Place:** click a board on the bed to pick it; drag it and only that one
  moves. *Where … sits on the bed* moves the picked board. *Centre it on the
  bed* moves the whole sheet's worth together; *Lay them side by side* lines
  them up 4 mm apart.
- **Files:** one set, named after every board (`buck+buck_2_traces.nc`) unless
  you type a job name. One trace pass, one drill file, one cut-out that frees
  each board in turn. The dry run traces every outline.
- **Butted boards:** boards closer than the cut-out bit share one cut, centred
  in the gap, so the panel needs no waste between them; each loses half of
  what the cutter takes beyond the gap (0.4 mm a side for touching boards and
  a 0.8 mm bit). *Butt them together* does this for the whole row.
- **Sheet edge:** once the copper sheet's size and corner are set, a board
  edge that lies on the sheet's edge (within 0.5 mm) is not cut — the sheet
  edge is the board edge there.
- **Checks:** boards must not overlap (the export refuses). Between one and
  two bit widths apart the two cut-outs overlap harmlessly; under
  `2 × bit + 1 mm` is a warning: the strip of waste between them can break
  loose.
- **Single-sided only.** A double-sided job is one board registered to its
  holes; add boards to a single-sided job.
- Setups (`.srmcam`) save every board with its own placement and rotation.

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

*This section is the original interface (`SRM-CAM --original`). The current one has its own Novice and Pro: see [Novice & Pro](https://madsrudolph.github.io/srm-cam/getting-started.html#tiers).*

**Mode** menu. Novice is the default on a fresh install.

**Novice** is the short path from Gerbers to files you can send from VPanel:
load → level → drill → traces → cut out → export. It puts away job parameters,
double-sided, rework, the bed-leveling workbench, live DRO / jog / streaming,
and the output-format and mirroring options.

What it deliberately keeps:

| Kept in Novice | Why |
|---|---|
| Diagnostics, Guide | A beginner needs the pre-flight check and the walkthrough more than anyone. |
| **Level the bed** (one guided button) | Probing is the biggest thing the Arduino buys a beginner: it makes cut depth follow the real surface, and that is what decides whether isolation actually separates traces. |
| **Corner = tool** | Without it the only way to say where the copper is, is to type machine coordinates nobody can know — so the design, and the probe grid that follows it, land somewhere arbitrary. |
| **Screw fixture** | A student who screws the copper down *without* the raised travel height crashes the spindle. The checkbox is what prevents that, so hiding it would make Novice the more dangerous mode. |

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
   [2026-06-25-srm20-spi-and-bed-leveling.md](archive/2026-06-25-srm20-spi-and-bed-leveling.md)).
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

### 4 · Bolt it down — the spoilboard screw grid

Tape and clamps let the stock creep, and a clamp is one more thing in the
cutter's way. The bed's MDF spoilboard is drilled on a regular grid and every
hole lines up with a thread in the metal plate underneath, so the copper can be
held with M4 screws straight into the plate instead.

**Copper stock → tick `Copper screwed down (M4)` → `Export screw fixture...`**

It writes `<name>_screws.nc` plus a procedure. Run it **first**, drop the screws
in, re-zero Z, then run the job — the stock is then fixed for every pass.

Measured on our spoilboard (`gerber2rml/engine/spoilboard.py`):

| | |
|---|---|
| board | 220 x 150 mm |
| holes | 20 across, 13 deep, 4 mm |
| pitch | 10.0 mm, both axes |
| grid origin | machine X 6.42, Y 14.58 (hole 0,0) |
| outer ring | not usable — spoilboard's own mounting screws |

The pitch came from two spans (190 mm / 20 holes and 120 mm / 13) that both give
exactly 10.0, and the anchor puts the 220 mm board 8.58 mm off the left of
travel and 8.22 mm off the right — totalling 16.80 mm, which is exactly
220 - 203.2. Three numbers agreeing is what made it safe to drill against.
It has since been confirmed by drilling: screws went straight into the threads.

**Re-measure if the spoilboard is ever unbolted, resurfaced or replaced.** A
wrong pitch does not fail gracefully — the bit goes through the copper, through
the MDF, and into solid steel.

#### Travel height — the part that bites

The heads stand **3 mm** above the copper. The default travel height is **2 mm**.
A rapid would pass a millimetre *below* the top of every screw.

Ticking the box **raises travel Z to 4 mm on all three operations automatically**,
so you cannot forget. It only ever raises: a higher value you set yourself is
kept. This failure is otherwise invisible — the XY is right, the depths are
right, the preview is right, and the spindle drives into a screw on the first
traverse, because the screws are not in the toolpath geometry.

#### Choosing the holes

The app picks four, spread as widely as the free copper allows — one toward each
corner where it can. Four screws in a line clamp along that line and let the
copper pivot about it, so the *spread* is checked separately from the count.

To choose your own: **`Pick holes`**, then click holes on the bed. Clicking adds,
clicking again removes, and the first click edits the app's suggestion rather
than clearing the board. **`Auto`** goes back to automatic. Any grid hole may be
picked, including ones the automatic pass rejected — you can see the bed and may
have a reason; Diagnostics *reports* a questionable choice rather than refusing
it.

The whole grid is drawn on the work plate whenever the bed is shown, with the
chosen holes marked at true head diameter (8 mm) so you can see whether a head
would land on your traces.

#### What Diagnostics checks

- travel height against the head height;
- four usable positions, and whether they can actually hold the copper flat;
- every screw head against the real swept material of **all three passes** —
  traces, drill and cut-out. The cut-out matters most: it runs *around* the
  outline, so a screw just past the edge is still in the cutter's path.

Screw positions are saved in the setup file. Hand-picked ones are stored
literally, because once the holes are drilled in a piece of copper they are a
fact about it; an untouched automatic choice is stored as "automatic" so it
keeps tracking the design if you move it later.

## Machine control (Professional)

With the Arduino fitted and **Connect** on, the machine dock drives the mill
directly. Every control here uses an SRM-20 SPI command verified on the machine
([audit](archive/2026-08-21-spi-command-audit.md)).

The **dock** keeps what you reach for with a hand on the machine:

| Control | What it does | VPanel equivalent |
|---|---|---|
| **Z ▲ / ▼** + step | Raises/lowers the bit by 0.01–5 mm. **PageUp / PageDown** do the same | its Z jog |
| **Probe Z** | Touches off on the surface and zeroes Z there | — |
| **Spindle** | Starts/stops the tool | its Spindle on/off |
| **Pause** / **Resume** | Holds the machine mid-move and carries on | Pause / Resume |
| **STOP** | Kills the move in flight, stops the spindle, lifts | Stop |
| status strip | `LID OPEN`, `spindle 8600`, `paused`, `ERROR`, `FAULT` | its status display |

Everything else is in the **Machine menu**: click-to-jog, align overlay, tool
trail, zero Z on the machine, move to the view position, stream a job, and the
machine test. They are one click away from every page rather than crowding the
strip — which had grown long enough to push Connect and STOP off the screen.

Z jogging down is refused while the probe says the bit is already touching;
jogging up always works, since backing off contact is the point.

**Spindle speed is still a VPanel setting.** The machine accepts start/stop over
the link but *ignores* the RPM value — 500 and 3000 produce identical speed. Set
the speed on VPanel's slider; use the button here to turn it on and off.

Safety, all enforced in firmware so they survive the app crashing:

- the spindle **will not start with the lid open**, or with the bit resting on
  the probe-wired plate;
- a **deadman** stops it if the app stops talking to the board for 10 s;
- **STOP** halts the queued move rather than waiting for it to finish;
- the status strip turns red for anything that stops work.

The **Spindle** button follows the machine, so it shows a spindle you started
from VPanel too — and disconnecting never stops a spindle SRM-CAM did not start.

### Streaming a job without VPanel

**Stream (exp.)** sends a job move-by-move over the link. A **wet run** now
starts and stops the spindle itself, holds on **Pause**, and aborts if the lid
opens mid-job. It still needs the speed set in VPanel first, and it is still
experimental: always do the dry run on a new job.

## Machine test — what this machine can actually do

**Machine test…** in the machine dock (Professional) probes the SRM-20's SPI
command set and reports PASS / FAIL / UNKNOWN per command, with a **Copy report**
button. Needs firmware v3 (`hardware/srm20_spi_probe`).

It exists because the app has only ever used 5 of the machine's 17 SPI commands,
and the rest — spindle control, the full status word, pause/resume/stop, View —
are what a VPanel-free workflow would be built on. Some Roland commands are
already known not to work on this machine, so each one gets tested before
anything relies on it. See
[2026-08-21-spi-command-audit.md](archive/2026-08-21-spi-command-audit.md).

| Arming | What runs |
|---|---|
| (none) | Read-only: firmware + machine version, status word, framing delay, cover-bit check, idle job-control acks |
| **Allow motion** | Move to View, interrupt a move, pause/resume, speed calibration. Each returns the head where it started — keep 20 mm of clear travel in Y |
| **Allow spindle** | Runs the tool at 3000 RPM for a few seconds. **Remove the tool** and close the lid |

**Run the cover test first.** Open and close the lid while it runs: if the
`cover` flag follows in the live status strip, the machine's status bits are
real and the firmware's safety guard works. If it never changes, disarm the
guard before probing — a stuck bit would abort good probe runs.

`scripts/srm20_bench.py` does the same from the command line and adds the long
sweeps (SPI framing delay vs read corruption; speed units vs mm/s).

## Milling without the Arduino

A bare, unmodified SRM-20 with nothing but VPanel is a fully supported setup.
Novice mode hides the machine *dock* — live DRO, jog, streaming — but since the
lab fitted the Arduino it does offer the two things the link makes possible for
a beginner: one-button bed leveling and `Corner = tool`. On a machine with no
board fitted those two are simply unavailable; everything else works unchanged:

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
[2026-06-26-multi-region-rework.md](archive/2026-06-26-multi-region-rework.md).

## Drilling a board made elsewhere (laser-etched traces)

For a board whose copper is already finished, e.g. etched on the fiber laser, and
only needs its holes. Load its Gerber folder as usual, then open **Drill a board
made elsewhere** on the rail (single-sided jobs only).

**Gerbers for a laser board etched on F.Cu** (the copper faces up on the bed):

| File | kicad-cli |
|---|---|
| copper | `pcb export gerbers --layers "F.Cu,Edge.Cuts"`, then rename `-F_Cu.gbr` to `-B_Cu.gbr` (the loader reads B.Cu) |
| holes | `pcb export drill --excellon-separate-th --drill-origin absolute` |

Load them with **Mirror for bottom-up milling off**. The picture then matches the
laser preview. Proven on a 90 × 72 mm board, 120 holes, worst pad 0.034 mm.

1. Clamp the board anywhere on the bed. Make the picture match the copper as it
   lies there (toggle **Mirror** under *Set up the job* if needed), and drag it to
   roughly where it sits.
2. **Suggest three** picks three holes far apart and well out of line, or tick
   **Pick on the board** and click your own.
3. For each pad: **Go to it**, then centre the bit over the pad by eye and
   **Capture**. You can also type the position in. After two pads, **Go to it**
   aims by the fit; on a measured pad it goes to the measured centre, to check it.
   **Find it for me** locates the centre electrically:
   - needs a copper-free circle at the pad (a mounting hole in a pour works well)
     and the probe clip on the copper around it;
   - start with the bit over the circle about **2 mm above the copper**, never at
     Z0: its first move is sideways at the starting height;
   - where there is no copper the bit presses 0.2 mm into bare laminate, which
     the drill removes.
4. At three pads the fit is applied. The stage draws the board where it really
   is, and **Worst pad** says how far the pads disagree (good < 0.10 mm, too far
   out ≥ 0.25 mm).
5. **Write the drill file** writes `<name>_drill_fitted.nc`: every hole moved onto
   the measured board. Zero Z with the drill bit and run it. Do not move the
   board or reset XY after measuring.

Three pads are required because two fit a mirrored board just as well as the
right one. The third catches it, but only if each pad is found by **which pin it
is**, not by where it sits in the picture. Engine: `engine/boardfit.py`, reusing
the rigid fit from `engine/fiducial.py`.

## Solder mask: the laser file

For a board that gets solder mask after milling. The operator's steps are on the
guide's [Solder mask](../website/solder-mask.html) page; this is what the option does.

**Solder mask › Also make the laser file (DXF)**, on the first page of the job in
both Novice and Pro, off by default. While it is ticked the file is written:

- by **Export the job** (Pro), beside the `.nc` files, and listed on the run sheet;
- by **Start** on the Run it page, into the run's folder (`SRM-CAM/runs/...`);
- by **Write the laser file now…**, any time, into a folder you pick.

A problem with the file never costs the machine files or stops a run. It is said
on the setup page, on the run sheet and in the run's log.

| | |
|---|---|
| Read from | The loaded Gerber folder: `*-B_Mask.*` (or `.gbs`) and `*-Edge_Cuts.*` (or `.gm1`), not the `.kicad_pcb` |
| Written | `<name>_mask_mirrored.dxf`, or `<name>_mask_not_mirrored.dxf` when **Mirror for bottom-up milling** is off |
| Contents | Closed `LWPOLYLINE`s on layer `MASK_OPENINGS`, and the outline on layer `OUTLINE`, in mm at 1:1. The outline's lower-left corner is at 0, 0 |
| Shrink | **Shrink by**, 0.10 mm per side by default, saved with the setup |

**The board side** comes from the job, as it does for the copper: the loader always
mills B.Cu, so a single-sided job reads B.Mask. No B.Mask in the folder is a message
naming the fix, and an F.Mask found instead is named but not used. A laser board
loaded through the F.Cu-renamed-to-B.Cu route above needs its F.Mask renamed the same
way, with Mirror off, which gives an unmirrored file.

A double-sided job gets one file per face, `<name>_mask_bottom_mirrored.dxf` and
`<name>_mask_top_not_mirrored.dxf`. The workflow has not been tried on two faces. A
panel gets one file per distinct board.

**Mirroring.** KiCad plots every layer from the top, and the milled face lies copper
side up on the laser as it did on the mill, so the mask is mirrored once with the
same x → −x as `load_board`, the outline with it. Do not flip it again in the xTool
software.

**Pad shapes** are the apertures' real shapes, including rotated pads, so the
loader's bounding-box approximation for obrounds and macros is not used here.
Openings are shrunk after the layer is unioned, so an opening drawn in several pieces
shrinks only at its real edge. An opening that vanishes in the shrink, or comes out
under 0.20 mm wide, is reported with its position. Engine: `engine/soldermask.py`,
with no new dependency: the DXF is written by hand.

Checked against `kicad-cli pcb export dxf --mode-single -l "B.Mask,Edge.Cuts" --uc
--ou mm --drill-shape-opt 0` at a pad clearance of -0.1, on a real board and on one
pad of each shape (`tests/fixtures/mask_shapes`): the same openings, centres equal,
worst difference between outlines of an opening 0.03 mm, which is KiCad's coarser
arcs. KiCad's plot draws the outline as the two sides of its line width; this file
has one line, on the board's edge.

## Silkscreen: the laser file

For a board whose component side gets its silkscreen marked by the fiber laser
after milling. It works like the solder mask file above and shares its reader and
DXF writer.

**Silkscreen › Also make the laser file (DXF)**, on the first page of the job in
both Novice and Pro, off by default. While it is ticked the file is written by
**Export the job**, by **Start** into the run's folder, and by **Write the
silkscreen file now…**. A problem with it never costs the machine files or stops a
run.

| | |
|---|---|
| Read from | The loaded Gerber folder: `*-F_Silkscreen.*` (or `.gto`) and `*-Edge_Cuts.*` (or `.gm1`) |
| Written | `<name>_silk_top_not_mirrored.dxf` |
| Contents | Closed `LWPOLYLINE`s on layer `SILKSCREEN`, and the outline on layer `OUTLINE`, in mm at 1:1. The outline's lower-left corner is at 0, 0 |

**Not mirrored**, whatever **Mirror for bottom-up milling** says. The mill cuts B.Cu;
the silkscreen goes on the other face, which lies face up on the laser exactly as
KiCad plotted it. This is the same file as the kicad-cli flow's `_silk_top.dxf`.

A double-sided job also gets `<name>_silk_bottom_mirrored.dxf` when the folder has a
B.Silkscreen with something on it. An empty or missing B.Silkscreen is normal and
writes nothing. A panel gets one file per distinct board.

**Shapes.** Silkscreen is drawn with round pens, so each stroke is buffered to its
real width and the strokes are unioned: overlapping lines become one shape, and the
inside of a letter like O stays a loop of its own, which the laser's fill leaves
unmarked. Nothing is shrunk. Artwork past the board edge is cut off at the outline
and the clipped area is reported. Engine: `engine/silkscreen.py`.

## Copper traces, solder mask, and silkscreen on the xTool

The Setup page lets you send any laser job directly to the xTool F1 Ultra (no
XCS required). The laser is a page of the main window, not a window of its own:
**CNC | Laser** in the header (Ctrl+1 / Ctrl+2) swaps between the
mill and the laser, and each page stays as you left it. The laser page has a
**Traces | Mask | Silk | Stencil** switcher at the top of the right panel so you
can step through all four jobs without losing board placement, focus, or camera
alignment. It follows the board loaded on the mill's page.

**Undo** (Ctrl+Z, or the Undo button above the bed) puts the job back where it
was before the last drag, typed position, arrow nudge, right-click centring or
turn; **Redo** is Ctrl+Shift+Z or Ctrl+Y. A drag is one step, and arrow nudges
in a row are one step.

The page works out the trenches and the run time in the background, once an
edit has rested for a moment, so typing a ring count or turning the board never
freezes the window. The old trenches stay up until the new ones are in, and the
Estimate shows **…** while it is being worked out. A run started meanwhile waits
for them, so what is cut is always what is shown.

- **Etch the traces on the xTool…** isolates every net on `B.Cu` (or `F.Cu`
  when `B.Cu` is absent/empty) directly from the Gerber folder. Use **Copper face**
  in the laser window to select **F.Cu — top copper** for a circuit routed on
  the front, such as curtain-drive. The preview labels the chosen layer and
  mirror state; top copper is not mirrored.
- **Open the mask on the xTool…** fills every mask opening, ablating the cured
  ink off the pads.
- **Mark it on the xTool…** fills the silkscreen artwork.

**The board's edge is never lasered as a trace.** Two things used to put it in
the job, and both are taken out when the traces are read:
- **The outline plotted into the copper file.** KiCad's plot option *Plot
  Edge.Cuts on all layers* draws the outline into every copper Gerber as a thin
  line, and read as copper it was isolated all the way round. Lines and arcs that
  lie on the outline are left out when together they cover at least half of it,
  and the page says so. A single stroke that only touches the edge is kept. Best
  fixed in KiCad too: untick that option when plotting.
- **Copper that reaches the edge.** A pour or track running to the outline was
  isolated along the edge as well, where there is nothing to isolate it from.
  That part of every pass is no longer drawn.

The traces DXF still has the outline on its own layer, for placing the job in
XCS. Set that layer to not output there. *Score the board outline afterwards* is
off in every traces preset.

### Native vector isolation and material calibration

XCS turns a Vector Engrave fill into full-board scanlines that cut across narrow
trace gaps and rapid-jump back and forth across copper tracks tens of thousands
of times. SRM-CAM defaults to **Concentric passes (FlatCAM style)**:

| Method | What it does | When to use |
|---|---|---|
| **Concentric passes (FlatCAM)** | Follows copper boundaries outward in concentric vector rings (default geometry: 6 rings ≈ 0.22 mm band), alternating sweep order each round | Native vector isolation, after calibrating on the same copper stock |
| **Moat hatch (cross-hatched band)** | Hatches only the isolation band around copper traces and pads | When you want a cross-hatched moat without full rubout |
| **Full rubout (sphawes / XCS)** | Hatches every empty millimetre inside the board outline | When all unused copper must be removed |

**The proven recipe.** **FR4 1.6 mm · proven** is the default traces preset:
- **Settings:** fiber, **100 %, 1000 mm/s, 30 kHz, 20 passes**, with concentric
  rings (6 rings, 0.04 mm kerf, 285 lines/cm).
- **Result on the lab's F1 Ultra (16 Nov 2026):** the whole curtain-drive board
  came out with every net isolated and no fine trace burnt, in about five minutes
  of laser time, against about two hours on the mill.
- **Other presets:** the rest are still uncalibrated starting points. XCS fill
  settings do not carry over to these vector rings.

**Copper calibration**, for new stock. Open it from **Traces → Recipe →
Calibrate copper vectors…**, or straight away with `srm-cam-laser --calibrate`.
Use a fresh, flat scrap of the same stock and autofocus on its copper. The
coupon is a 40 × 40 mm square; its labels and frame are guides and are never
lasered.

1. **Find the exposure.**
   - **The grid:** 16 small real traces, each two 0.4 mm tracks with a 0.3 mm
     gap and a pad at alternate ends, isolated with the production rings.
   - **Columns and rows:** the columns are speeds (300, 600, 1000, 2000 mm/s)
     and the rows are pass counts (5, 10, 20, 40), all at one power (100 %,
     30 kHz). Both lists can be edited.
   - **One job:** the whole grid runs in about 80 s. Passes go round-robin with
     a 0.5 s laser-off rest each round, so no track gets its passes back to back.
   - **Reading it:** too little dose leaves faint outlines; too much chars the
     board.
   - **Choosing:** pick the cell that cleared the copper with the fewest passes.
     Prove it with a continuity check across the two pads, which should read
     open.

   On the lab's FR4, 600 × 20, 1000 × 20 and 2000 × 40 were best: the same dose
   (passes ÷ speed) window. A single line is not a fair test: it only cuts a
   hairline, too thin to judge whether the copper is cleared.
2. **Single lines, Spacing, Corners and pads:** use the exposure the grid found.
   These stages take a pass count, so a cell runs at, say, 20 passes in one
   press.
   - **Single lines:** measure the cleared width.
   - **Spacing:** find a pitch that clears continuously.
   - **Corners and pads:** check five real shapes.

   Each stage needs the measurement from the one before. Use fresh copper for
   every stage.

**Run records.** Every run saves its `.gcode` and `.json` in
`Documents/SRM-CAM/exports/copper-calibration/`, or the configured workspace:
- **What is recorded:** the material, the stage and cell (or the whole grid
  with each cell's speed and passes), power, frequency, passes, position, head
  Z, camera correction, the exact job's hash, and whether it completed.
- **Uncertain runs:** interrupted or failed runs are recorded as uncertain, not
  counted.
- **Observations:** **Record observation** saves what you inspected. It does not
  judge isolation from a camera picture.

**Saving a recipe.** After **Clean isolation** on all five corners/pads cells, at
one exposure and one total pass count, **Save measured recipe…** stores the
exposure, cleared width, pitch, rings and that pass count as a traces preset.
Mixed exposures, uneven pass counts and interrupted runs cannot become a
preset.

**The laser page on its own.** `srm-cam-laser [gerber-folder]` opens the laser
page straight on a board, without SRM-CAM's milling steps:
- **Which job:** it starts on traces from the face with the most copper, so a
  fab-made board like curtain-drive opens on F.Cu. It falls back to mask,
  silkscreen or stencil if the folder has no copper.
- **With no folder:** it reopens the last one, or asks for one.
- **Options:** `--job mask|silk|stencil` opens on that job, and `--calibrate`
  opens the copper calibration window.

When a drill file is present, **Etch drill hole centres inside pads** (on by
default) clears the copper at each hole centre so drill bits self-centre and
`Drill a board made elsewhere` can probe isolated pads.

What changes across the four jobs:

| | Traces | Stencil | Solder mask | Silkscreen |
|---|---|---|---|---|
| Laser work | concentric vector rings (or moat/rubout) | outline cut, 30 passes in zones | filled, hatch lines | filled, hatch lines |
| Default preset | FR4 1.6 mm · proven (100 %, 1000 mm/s × 20) | 0.1 mm 304 stainless | RemoveSolderMask (sphawes) | RemoveSolderMask (sphawes) |
| Align locks onto | the drilled holes (if present) | the holes it cut | the drilled holes | the drilled holes |
| Learn the camera offset | no (uses the stencil's) | yes | no (uses the stencil's) | no (uses the stencil's) |

**The fill presets** are the ones in sphawes/fiber-laser-pcb-fab's
`settings.json`, which the lab imports into XCS:
- **RemoveSolderMask:** fiber, 40 %, 800 mm/s, 30 kHz, 300 lines/cm, 6 passes,
  one way, cross-hatched.
- **Traces:** 100 %, 600 mm/s, 240 lines/cm, 10 passes.

XCS draws these as a raster. Here each shape gets vector hatch lines at the same
spacing, power and speed:
- Each pass is at right angles to the last.
- Every line runs the same way.
- The lines run across the whole job, not shape by shape.

Under **Adjust the numbers** are power, speed, frequency, passes, line density,
cross hatch, one way, and a faint score of the board outline.

**Align** uses the board's drill file, in the same frame and mirroring as the
artwork. A drilled hole shows as a dark dot in the photo, through the ink too.
On the test board, all 27 drilled holes fall inside their mask openings.

The camera offset learned on a stencil applies to these jobs too.

## Solder paste stencil: cut on the xTool F1 Ultra

The holes for a paste stencil cut from 0.1 mm stainless foil by the fiber laser,
from the same Gerber folder. It shares the solder mask file's reader and DXF writer.
SRM-CAM can also **cut it**, sending the job to the F1 Ultra itself, because XCS
cannot spread the heat out and a stencil cut in one go warps.

**Solder paste stencil › Also make the stencil file (DXF)**, on the first page of
the job, off by default. While it is ticked, **Export the job** writes the DXF too.
**Write the stencil file now…** writes it on its own, and **Cut it on the xTool…**
opens the laser window.

| | |
|---|---|
| Read from | `*-B_Paste.*` (or `.gbp`), plus `*-F_Paste.*` (or `.gtp`) for a double-sided job, and `*-Edge_Cuts.*` |
| Written | `<name>_stencil_bottom_mirrored.dxf` |
| Contents | Closed `LWPOLYLINE`s on layer `STENCIL_APERTURES`, the outline on layer `OUTLINE`, mm at 1:1 |

**Kerf.** The beam removes about 0.08 mm of steel around its path. That figure was
measured on the lab's machine in 0.1 mm 304 stainless. So each hole is drawn half
the kerf smaller per side, and comes out pad-sized.

**Mirrored like the copper.** B.Paste goes on the milled face, which lies face up
when the stencil goes on, so it is mirrored once. A double-sided job's F.Paste is
not mirrored.

**Holes that print.** A hole whose area ratio, area ÷ (perimeter × 0.1 mm), is under
0.66 may hold on to its paste. It is reported, not dropped. So is a pad smaller than
the kerf, which gets no hole.

### Cutting it

**Cut it on the xTool…** opens the laser page. The F1 Ultra must be plugged into
this PC by USB. It shows up as a network adapter, with the laser at 201.234.3.1.
XCS is not needed.

The page is laid out like XCS: a toolbar over the bed picture, cards on the right
(Stencil, Focus, Recipe, Run), and a status bar with the cursor's X/Y and the
focus.

1. **📷 Photo** shows the bed as the laser's camera sees it, straightened with the
   machine's own calibration files. The rulers are the laser's mm.
2. **◎ Autofocus** measures the height under the pink cross and moves the head
   until that point is within 0.1 mm of focus:
   - It does this the way XCS does: a blue dot glows there, the camera finds it,
     and its row in the picture is read against the factory height table.
   - The cross sits at the stencil's middle, on the factory's 10 mm grid.
     Right-click → **Autofocus here** measures somewhere else.
   - You can also type XCS's thickness and press **Set**.
3. The photo refreshes after focus or a thickness change. Place the stencil:
   - Drag it.
   - Nudge it with the arrow keys: 0.1 mm, or 1 mm with Shift, or 10 mm with Ctrl.
   - Type X/Y, which is the top-left corner of the outline.
   - Right-click → **Centre the stencil here**.
   - **Turn ◂ / Turn ▸** turns it a quarter at a time about its middle.

   The camera rides on the head, so the photo is true for the foil's surface
   however high the plate is.
4. **Show where** runs the blue diode round the outline at 6 %. That is visible
   but does not mark steel.
5. **Cut** runs one job at the focus the head is at:
   - The holes are split into zones, and each zone is cut in bursts with
     laser-off rests between them.
   - The holes of the zone being cut light up green, with the time left beside
     them.
   - A photo is taken at the end, unless you untick it.

   **Stop** stops it at once.

**Re-cutting.** Turn on **⬚ Select holes**. Click a hole, or drag a box round
several; Ctrl or Shift adds to the selection. **Cut** becomes **Cut N selected**:
it cuts only those holes, with the same recipe, and does not mark the outline
again. Hovering over a hole shows its size.

**Looking at the result.** **Filled | Outlines | Hidden** in the header changes
how the stencil is drawn over the photo:
- **Filled** is the stencil as it will be cut.
- **Outlines** draws each hole as a thin line with nothing filled, so the photo
  shows through every hole. Take a photo after cutting and look for pads that
  are not dark all the way through, then select those and re-cut them.
- **Hidden** shows only the photo. **H** switches between hidden and filled.

**The camera's offset.** The factory camera calibration on the lab's machine
shows everything about 0.5 mm left and 0.9 mm up of where the fiber really cuts.
The **Camera** section stores a correction, and every photo is moved by it:
1. Right after a cut, with the stencil still where it was cut, press **Learn
   from this cut**.
2. It finds the holes in a photo and stores the difference.

The photo taken after a cut is checked automatically, and the status says when
the photo is more than 0.3 mm off. Learning uses the recorded laser cut position,
even if the overlay has since moved. The material must still be where it was
cut. Learning is available after a successful stencil cut in this window.
**Correction X/Y** adjusts the stored correction by hand; **Reset** clears it.
Both immediately reproject the current photo without moving the drawing or
the laser job. Picked photo references follow the corrected coordinates.

On the lab's machine, learning from the curtain-drive stencil (114 holes) took
the photo from −0.51, −0.88 mm off down to 0.07 mm.

**Proof on the drilled holes (traces).** For a board that was drilled first,
**Alignment › Proof on the drilled holes** ties the laser to the holes without
relying on a stored camera correction:

1. Drag the drawing roughly onto the board (within about 3 mm) and press it.
2. It takes a photo, makes a few faint marks, and takes a second photo. Only
   what changed between the two counts, so the marks are found whatever the
   board looks like.
3. The marks set the camera correction; the holes, seen through the corrected
   camera, give how far the job is off the board. The job is moved (and turned
   up to 1.5°) onto them. Nothing moves if the marks do not show.

**Where the marks go** (*Proof options › Marks*): in the waste beside the board
when the sheet carries on past the outline, as small 1.5 mm squares 3 mm outside
it; otherwise on the isolation within 2.5 mm of three drilled holes that lie far
apart, which the job removes anyway. *Automatic* judges the waste from the
photo. **Mark passes** (default 3) is how many passes the marks get.

On a double-sided board, run the proof on each face after the flip. Written
2026-11-17 and tested on synthetic photos only: the mark passes needed for the
camera to see a mark on copper, and the waste check, are not yet tried at the
machine.

**The side panel** shows the job, the proof, focus and camera readouts and the
recipe. Position in numbers, proof options, matching points by hand, the
automatic references, the height by hand, the camera correction by hand and the
recipe's numbers are each under a fold that remembers whether it was open.

**Pick matching points (any board).** The **Alignment** section works without
mounting holes or a drill file:

1. Take a photo and press **Pick matching points**.
2. Choose snapping to hole centres or artwork centres, or **Free points /
   corners / marks**. Click a reference in the drawing. The drawing temporarily
   hides so the photo is unobstructed.
3. Click the same physical feature in the photo. Repeat for two distant points,
   preferably three or more distributed over the board. Zoom in with the wheel;
   the photo is displayed at 8 pixels/mm. Numbered drawing/photo markers show
   each pair. **Remove** deletes the selected pair; **Clear** starts over;
   Escape exits picking.
4. Press **Apply point alignment**. The drawing rotates and translates to fit,
   without scaling or mirroring. RMS and worst error are shown. Inconsistent
   pairs (over 0.3 mm residual), duplicates, and references less than 5 mm apart
   are rejected without moving the job. Two points cannot independently verify
   the fit, so add a third to check it.

These references never change the shapes selected for etching. A new photo
clears manual pairs because the board may have moved. Board alignment changes
the job position; it does not teach the camera offset.

**Automatic alignment.** Expand **Automatic alignment references** to choose
drilled holes or artwork shapes, then tick only features that already exist on
the material. Selecting a row highlights that feature in the viewer. Choose
dark holes/marks or bright pads/marks to match the photo. At least two enabled
references are required. Artwork references must physically exist already;
use corners or other visible marks on a blank copper board.

**Align after moving the foil.** If the foil or board has been lifted and put
back, for example to push out slugs before a re-cut:
1. Drag the stencil roughly onto it.
2. Press **Align**. It takes a photo and finds the enabled references.
3. The stencil is moved and turned onto them, including small angles. If the
   board went back a quarter turn round, the other three orientations are
   tried as well.
4. The status says how many holes it found. Nothing moves unless at least 85 %
   of them are found.

On the lab's machine, two different starting points landed within 0.01 mm of
each other and within 0.25 mm of where the holes were cut. Use **Show where**
before cutting.

**Recipes.** The Recipe section only shows the preset. **Adjust the numbers**
folds out power, speed, frequency, passes, per burst, rest, zones and the
outline mark. It says when they differ from the preset, and it holds **Save as
preset…** and **Delete preset**. The two built-in presets are **0.1 mm 304
stainless**, which is the proven one, and **Marking test (1 pass)**.

**Recipes (detail).** The **Recipe** card holds power, speed, frequency, passes, per burst,
rest, zones and the outline mark. There are two built-in presets:
**0.1 mm 304 stainless**, which is the proven one, and **Marking test (1 pass)**.
**Save…** keeps your own under a name, and **Delete** removes it.

**Placement** was checked by firing the dot at known points. (60, 40) came out at
(59.5, 39.2) in the photo, so trust it to about 1 mm and use **Show where** for
the last bit.

**Camera grid.** The factory grid is stored turned half round: its first point
is the laser's (220, 220). `engine/xtool_camera.py` allows for that.

The recipe (100 %, 550 mm/s, 30 kHz, 30 passes in bursts of 5) is the one that cut
the ESP32 stencil flat and through on 2026-11-15. It is under **Recipe** in the
laser window.

The firmware ignores `G4` dwells, so a rest is the galvo crawling at 1 mm/s with
the laser at `S0`. That was checked to leave no trace on steel, with the fiber
selected.

Command line: `srm-cam-stencil <folder> -o out` for the DXF, `--trace X Y`, and
`--cut X Y --thickness T`.

Engines: `engine/stencil.py` (the holes), `engine/xtool.py` (the job file and
the laser) and `engine/xtool_camera.py` (photo and autofocus). The protocol notes are in the solder-stencil-tests repo,
`docs/OPEN_CONTROL.md`.

## Double-sided boards

Top/bottom passes align off machine-located holes, never the board edge. Tick
**Double-sided** (needs an **F.Cu** layer), then pick a **Method**:

- **Dowel pins** (default, proven) — the mill drills holes through the stock *into
  the sacrificial bed*; seat pins and flip the board onto them. Zero measurement,
  sub-0.1 mm.
- **Fiducial holes** — the mill drills 2–4 *stock-only* corner holes; flip and
  re-place freely (no pins), probe where they landed, and the top traces warp to
  the best-fit transform. See
  [2026-06-26-fiducial-registration.md](archive/2026-06-26-fiducial-registration.md).

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
