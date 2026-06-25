# Dev log — faster probing, leveled rework, live run progress

**Date:** 2026-06-25
**Scope:** a batch of operator-facing improvements built while running the real
"Mega PCB" (full-bed, double-sided) job: making grid probing much faster, fixing
the height-map overlay frame, a hover read-out on the 3D bed view, a breadcrumb
trail of the bit's path, a settable (and height-map-following) rework depth, and
a live run-progress bar that counts down the time left.

Like the sibling logs this is a feature-by-feature record with the *why*, not
just a changelog. Persistent machine facts live in the project memory
(`srm20-*` notes).

---

## 1. Faster grid probing — two-phase approach (firmware)

**File:** [`hardware/srm20_spi_probe/srm20_spi_probe.ino`](../hardware/srm20_spi_probe/srm20_spi_probe.ino)

The probe descent was the whole cost. Every point fine-stepped **25 µm at a
time** from the datum lift all the way down to the copper — ~120 stop-and-go
steps for a 3 mm lift, *the same 120 steps regardless of how far the surface
actually was*. On a 49-point grid that's a lot of dead time crossing air.

**Fix — learn the surface once, then rapid to it:**
- The **first** point of a run still fine-steps the whole way down (it has to
  discover where the copper is).
- **Every point after** rapids straight down to `APPROACH_CLEAR_UM` (**1 mm**)
  above the highest copper seen so far in a *single* move, then fine-steps only
  that last millimetre. The between-point lift also only backs up to that plane,
  not the full datum height.

So a 2–3 mm datum lift now costs about the same as a 1 mm one, with **no loss of
25 µm touch accuracy**. Safety is unchanged: the runaway floor
(`refSurfaceZ − OUTLIER_MARGIN_UM`, 1.2 mm) still trips on a missed-copper plunge,
and if a point's copper is somehow *higher* than the approach plane the firmware
backs off to full safe Z and slow-probes from there — it never plunges from a low
rapid. `APPROACH_CLEAR_UM` is a named constant; raise it for a more tilted bed.

**Operator action:** re-flash the sketch to pick this up. The serial protocol is
unchanged, so the host (GUI, Resume, height map) behaves identically — just
faster. You can't reflash mid-run without losing the datum, so finish the run
you're on first.

---

## 2. Height-map overlay was drawn in the wrong frame (preview-only)

**File:** [`gerber2rml/gui/app.py`](../gerber2rml/gui/app.py) — `_update_level_overlay`, `_on_bed_3d`

On a **double-sided bottom (mirrored)** run the colored heat-map overlay sat
*offset* from the board. The cause was purely cosmetic: the overlay sampled the
surface over `state.board.outline.bounds` (the raw, un-mirrored **design** frame)
while the probe grid and PCB are drawn in the **displayed/machine** frame. On a
single-sided board at origin the two frames coincide, so it was invisible there.

**Fix:** sample the overlay (and the 3D bed view) over `_level_bounds()` — the
exact footprint the probe grid is laid over — so mesh, grid and PCB share one
frame.

**Important:** this never touched the exported G-code. `apply_leveling` evaluates
`hmap(m.x, m.y)` at each real toolpath coordinate; it does not sample over a
rectangle. The probe points and the cut moves were always in the same frame, so
the leveling in the NC was correct all along — only the *picture* was misplaced.

---

## 3. Hover read-out on the 3D bed view

**File:** [`gerber2rml/gui/bedviz.py`](../gerber2rml/gui/bedviz.py)

Move the mouse over any white probe marker and a tooltip shows everything about
that point: its index, exact X/Y (mm), Z deviation (µm and mm), and where it sits
within the measured band (% of range, lo…hi). Each marker is projected
world→screen through the view's MVP matrix on every mouse-move and the nearest
within 18 px wins, so the read-out tracks the dots as you orbit and rescale Z.

**Two pyqtgraph 0.14 gotchas worth remembering:**
- `GLViewWidget.projectionMatrix()` now **requires** `(region, viewport)` args —
  call it as `projectionMatrix(vp, vp)` with `vp = view.getViewport()`.
- PySide6's `QMatrix4x4 * QVector4D` operator throws here. Do the projection in
  **numpy** from `QMatrix4x4.data()` (column-major) instead.

Pure helpers `_hover_text` / `_nearest_index` are unit-tested, and a projection
round-trip test (project a marker → pick at that pixel → get the same index)
guards the math.

---

## 4. Breadcrumb trail of the bit's path

**Files:** [`gerber2rml/gui/canvas.py`](../gerber2rml/gui/canvas.py), `gerber2rml/gui/app.py`

While the machine is connected, every live DRO sample extends a **fading amber
trail** on the preview, so during a rework pass you can follow where the bit has
already been over the cyan toolpaths. Segments fade from dim (oldest) to bright
(newest). Samples closer than 0.2 mm are dropped (jitter) and the trail is capped
at 4000 points so a long job stays responsive. A **Trail** toggle and **Clear
trail** button live on the machine bar.

---

## 5. Rework: settable depth that follows the height map

**Files:** [`gerber2rml/engine/select.py`](../gerber2rml/engine/select.py), `gerber2rml/gui/app.py`

The box-select rework used to re-cut at the original pass's flat depth, ignoring
the probed surface. Two additions, in the **Rework (2nd pass)** panel:

- **Rework depth** — the *uniform* depth below the copper surface the 2nd pass
  cuts at. `clip_toolpaths_to_bbox` grew an optional `cut_z` override (the
  travel/rapid height is left untouched).
- **Follow height map** (on by default) — warps the clipped pass by the probed
  surface so the cut tracks the real tilt/bow and the depth stays **uniform**
  across the board, instead of a flat plane that bites deep on the high side and
  shallow on the low side. Reuses the same `apply_leveling` the main export uses,
  fed by `_level_heightmap_preview()`.

Per cut point: `Z = −(rework depth) + heightmap(x, y)`. So leave the depth at the
trace depth to faithfully repeat the first pass, or **raise it past that to add
"even more offset"** and be sure stubborn copper cuts through — and because the
whole thing rides the height map, the extra bite is uniform too. Both the
exported NC and the 3D rework simulation go through the shared
`_rework_clip(toolpaths, bbox) → (clipped, leveled)`. With no map present it
falls back cleanly to the old flat behaviour.

---

## 6. Live run-progress bar (DRO-driven) + auto-start

**Files:** [`gerber2rml/engine/progress.py`](../gerber2rml/engine/progress.py) (new), `gerber2rml/gui/app.py`

A **"Run"** bar across the top shows how far the mill has got through a job and
how much time is left. The mill is driven by VPanel — we don't run the cut — but
we already read its **live position** over the SPI link (the same feed that draws
the tool marker). So the bar is **position-driven, not a blind timer**.

`RunProgress` (engine, pure, tested) precomputes the path's cumulative-time
profile — timing **identical to `engine.estimate`**, so a finished run lands on
the same total the planner showed — then projects each live `(x, y, z)` onto the
path:
- **Forward-only:** each update searches a window *ahead* of the last match and
  the elapsed time only increases, so a rapid back over cut copper can't rewind
  the bar.
- **Latches mid-run:** the first read searches the whole path, so arming partway
  through still finds the bit's place.

**UI:** pick the op (Traces / Drill / Cut-out, or tick **selection** for the
rework clip), then either press **Track run** or leave **Auto** on:

- **Auto-start** arms tracking once the DRO shows ~0.75 s of continuous motion
  (a run started in VPanel) — so you just hit Run and the bar starts itself.
  Motion within 2 s of a jog *we* issued is ignored (that's our own move), and a
  finished run re-arms when the next job begins.

**Frame caveat (same as the marker):** progress assumes the live machine position
and the on-screen toolpaths share one frame — which they do in the standard
workflow (the probe grid and tool marker already land on the board). If you set a
VPanel work origin offset from where the board is placed on the bed, the bar
would track from the wrong spot.

---

## Commits (this session, on `main`)

| Commit | What |
|---|---|
| `d66843a` | perf(probe): fast two-phase approach (firmware) |
| `a937aa7` | fix(leveling): draw the heat-map in the displayed frame |
| `f73fce0` | feat(bedviz): hover a probe marker for its exact value |
| `1ee2a09` | feat(rework): breadcrumb trail of the bit's path |
| `61039c9` | feat(rework): settable cut depth for the 2nd pass |
| `e0ff940` | feat(rework): follow the probed height map (uniform depth) |
| `035225d` | feat(progress): live run-progress bar from the DRO |
| `f106669` | feat(progress): auto-start tracking when the bit moves |

All ship with tests; the suite is green (249 tests). Only the probe-speed change
needs a hardware re-flash; everything else is a `git pull`.
