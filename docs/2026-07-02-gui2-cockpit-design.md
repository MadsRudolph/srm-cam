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

## Open questions

- Step schema: encode bit/spindle per step in presets, or infer from jobs?
- Where does bed leveling live in the spine for single-sided boards?
- Should the spine estimate wall-clock for the remaining steps (sum of
  per-file estimates minus tracked progress)?
