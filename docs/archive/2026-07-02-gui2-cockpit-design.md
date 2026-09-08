# GUI 2.0 — "Cockpit" design

*2026-07-02 — agreed direction from the post-MegaPCB brainstorm.*

## Why (evidence from a real production day)

A full double-sided MegaPCB run surfaced these failures of the current UI, all
observed live:

1. **Frame confusion is dangerous.** The drill preview looked mirrored versus
   the physical board ("AS MILLED" badge over a design-frame canvas); the
   Mirror/Preview controls do nothing in double-sided mode. Every serious scare
   of the day was a coordinate-frame presentation problem, not a CAM problem.
2. **The workflow lives in the operator's head.** The app writes `runplan.txt`
   (align → drill → bottom traces → cutout → flip → top traces) but the UI is
   organized by category, so "what do I run next in VPanel, with which bit, at
   which spindle speed" is manual bookkeeping.
3. **Job parameters are invisible.** The `DataclassForm`s exist but are hidden;
   presets are the only editor. `target_width` could not be typed into the UI.
4. **Machine controls are scattered** across the top strip, the Bed Leveling
   page, the run-progress row and a floating 3D window.
5. **Inapplicable settings stay visible** and get greyed out one bug report at
   a time.

What works and must be preserved: **click-to-jog** (the canvas as a remote
control for the bed), the live DRO/overlay/trail, run tracking, and the
preview's information density.

## The concept: jog-first canvas, runplan spine

### 1. Runplan spine (replaces the category sidebar)

The left rail *is* the run plan — the same steps `runplan.txt` encodes, with
live state:

- Steps: setup/stock → bed leveling → align holes → drill → bottom traces →
  cutout → flip → top traces (+ per-board extras: fiducial probe, rework).
- Each step knows: the op, the exported file, the required bit, the spindle
  RPM, and its state (pending / exported / running / done). Run tracking
  (`RunProgress`) feeds state automatically; manual override always possible.
- Between-step boundaries surface the physical ritual: "change to 0.8 mm
  drill", "set VPanel spindle to 7000", "re-zero Z after bit change".
- **Never blocking.** Any step or tool is clickable at any time; state is
  informational. (Agreed explicitly — real runs jump around.)
- Rework is a tool invoked on a step, not a page. Selecting a step shows its
  toolpaths on the canvas and its parameters in the inspector.

### 2. One frame, one switcher

- Canvas default is **Bed (as cut)** — machine coordinates, always. This is
  the frame VPanel, the DRO and the operator's hands live in, and the only
  frame in which click-to-jog is truthful.
- **Design X-ray** becomes an explicit inspection toggle (registration
  checking), visually distinct (tinted background, not just a badge).
- Mirror / Preview-frame / View dropdowns collapse into this one control.
  The frame badge can then never disagree with the canvas.

### 3. Jog-first canvas

- Click-to-jog is the primary interaction whenever the machine is connected;
  select/move/measure stay as explicit modes.
- **Snap-to-feature jog** (phase 1, shipped): a jog click snaps to the nearest
  *displayed* hole or dowel/fiducial pin within the ruler's snap tolerance, so
  "jog to that hole" lands exactly on the hole. Ctrl+click jogs to the raw
  position. Snapping uses the canvas's own drawn markers — guaranteed to be in
  the canvas frame, immune to layout/frame drift.
- Jog-guided steps: fiducial probing walks pin-to-pin (click → travel → probe
  → next); a "spot-check corners" action for post-drill verification.

### 4. Inspector (right panel)

Context panel for the selected thing: the active step's job parameters
(editable — presets become starting points), the bit cross-section graphic,
a clicked fiducial's coordinates, a rework region's depth.

### 5. Machine dock (bottom strip)

Connect, DRO readout, Probe Z, jog toggle, Align overlay, tracking progress,
STOP — persistent in every context.

### 3D window

Stays a separate window for now (dual-monitor use at the mill), but obeys the
same frame rules and keeps the LIVE link. Docking as a canvas tab is a later
spike (known GL-embedding quirk documented in `_open_sim_window`).

## Migration (strangler, each phase ships green)

1. **Snap-to-feature jog** (this change) — immediate value in the current GUI.
2. **Machine dock** — relocate the scattered machine controls into one strip.
3. **Frame unification** — Bed (as cut) default + X-ray toggle; delete
   Mirror/Preview/View special cases; every view renders through one frame
   resolver.
4. **Runplan spine** — replace the sidebar; step schema + state tracking from
   RunProgress; between-step prompts.
5. **Inspector** — expose the job forms contextually; presets as templates.
6. **3D docking spike** — optional.

## Decisions log

- Spine is informational, never blocking (user, 2026-07-02).
- Bed/machine frame is the universal canvas default; X-ray is an inspection
  mode (follows from click-to-jog being the flagship interaction).
- 3D remains a separate window for now.
- Migration is incremental PRs on main, no long-lived rewrite branch.

## Queued feature: hole-based flip registration

Requested 2026-07-02: when fiducials can't be used (no waste for them, or the
operator simply didn't plan them), align the two sides using **already-drilled
board holes** as the reference points.

- The math is already in place: `engine.fiducial.fit_transform` accepts any
  2-4 point pairs with spread; the nominal positions of drilled holes after
  the flip are `reflect_holes(mlay.holes, axis, flip_pos)` — exactly what the
  Top drill view already renders.
- UI sketch: in the flip-alignment flow, a "use board holes" option — pick
  2-4 holes by clicking them on the preview (phase-1 snap-to-hole makes the
  pick exact). Auto-suggest well-spread large-diameter holes (spread drives
  fit accuracy; the probe/bit must fit the hole, so prefer >= bit diameter).
  The dialog then works exactly like the fiducial one: jog the bit into each
  hole on the flipped board, Capture, fit, warp the top traces.
- Guidance to bake into the flow: far-apart holes, larger diameters, and the
  Top view (reflected frame) to identify the same physical hole after the
  flip.

## Queued feature: auto-probe fiducials over SPI

The manual fiducial capture (jog, drop the bit into each hole, Capture) is the
most tedious step of the fiducial flip — requested repeatedly during the first
real fiducial run (2026-07-02).

**Constraint that rules out wall-probing:** milled holes are NOT plated — the
hole wall is bare FR-4, an insulator, so lateral touches inside the hole give
no electrical signal. All probing must contact the TOP COPPER only. (Also,
the standard 0.8 mm fiducial equals the bit diameter: zero lateral clearance.)

Two rim-probing methods that respect this, using only ``touch_off``/``jog_to``:

- **V-bit cone probing** (tool already loaded for V-bit jobs): the cone maps
  lateral offset to contact HEIGHT — centred, it descends deepest before the
  flank meets the copper rim; off-centre, contact comes earlier. Touch off in
  a small cross/star around the nominal (~5–9 points), fit the Z bowl, its
  minimum is the centre. A 30° cone amplifies offset→Z by ~1/tan(15°) ≈ 3.7×,
  so ~0.01 mm centring is realistic.
- **Flat-bit window search** (bit strictly smaller than the hole, e.g. 0.4 mm
  in a 0.8 fiducial, or 0.8 mm in ≥1.2 mm board holes for hole-based
  registration): touch depth is binary — rim contact at surface height until
  the whole face is inside, then a deep plunge. Binary-search the X and Y
  edges of the falls-in window; the midpoints are the centre.

A same-size bit in a same-size hole (0.8 in 0.8) is the one degenerate case —
the flow should detect it and ask for the V-bit or bigger reference holes.
Four holes ≈ 2 minutes, no operator jogging. Combined with hole-based
registration (above), the fiducial flip becomes LESS labor than dowels:
flip → auto-align → cut.

## Flagship feature: the Blind Flip (self-registering double-sided)

Goal (user, 2026-07-03): dowel-grade ease for boards that can't fit dowels.
Dowels are easy because the BED holds the knowledge; every fiducial method
fails by making the OPERATOR the information carrier. After drilling, the
BOARD holds the knowledge: its hole pattern is an asymmetric fingerprint the
machine can read electrically (rim probing works on unplated holes).

Flow: flip any way, place anywhere reasonable, clamp, click Auto-align:
1. Coarse: probe falls-in/cone signatures near 2-3 large nominal holes;
   constellation-match against the known hole set under BOTH flip hypotheses —
   board content is asymmetric, so the wrong axis misses by mm while the right
   one matches to um. Flip direction is DETECTED, never chosen (kills the
   2026-07-03 symmetry trap structurally).
2. Fine: drive to 3-4 well-spread holes, centre-find (V-bit cone probe or
   smaller-bit window search — rim contact only), fit_transform.
3. Auto: travel-limit check FIRST ("slide 10 mm right" before probing),
   then the leveling grid over the as-placed board, then export leveled +
   warped top traces. AS PLACED preview + jog-verify as the human check.

No extra drilling, no typing, no direction choice, one button. Ingredients
all exist: spi_probe touch_off/jog_to, rim-probe methods (above), fit
pipeline, AS PLACED views, offline travel check (validated 2026-07-03).

## Open questions

- Step schema: encode bit/spindle per step in presets, or infer from jobs?
- Where does bed leveling live in the spine for single-sided boards?
- Should the spine estimate wall-clock for the remaining steps (sum of
  per-file estimates minus tracked progress)?
