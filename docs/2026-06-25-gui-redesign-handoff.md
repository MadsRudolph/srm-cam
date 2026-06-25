# Handoff — GUI redesign / UX pass (for Antigravity)

**Date:** 2026-06-25
**Owner:** Mads
**Goal:** The desktop GUI *works* but doesn't *feel* good. I want you (Antigravity)
to take a fresh, critical look at the whole thing — **flow, usability, information
hierarchy, visual style, interaction feel** — and then propose and implement a
redesign. Treat this as a UX/UI engagement, not a bug fix. Don't just reskin it;
question the layout and the workflow.

This document orients you: what the app is, how to run it, how it's built, where
it flows badly today, and the hard constraints you must not break.

---

## 0. TL;DR of the ask

1. **Run it, use it, screenshot it.** Form your own opinion before reading mine.
2. **Audit** flow, usability, and style. Write your findings down.
3. **Propose** a redesign (layout + visual language + interaction). Show it to me
   before a big rewrite if it's a major departure.
4. **Implement** it incrementally, keeping the test suite green and the export
   logic untouched.

Bias toward making the *common path* (load → set depth → preview → export)
effortless, and tucking the advanced machinery away without burying it.

---

## 1. What this app is

`gerber2rml` (a.k.a. **srm-cam**) is a CAM tool: it turns KiCad **Gerber/Excellon**
files into machine toolpaths (**RML** or **G-code**) for a **Roland SRM-20** desktop
PCB mill. The GUI is the primary way I drive it. A typical session:

1. **Load** a Gerber folder (a board export).
2. Pick a **preset** (FR-4 conservative, etc.) and set the **stock thickness**.
3. Flip through the **Traces / Drill / Cut-out** tabs, eyeballing the live preview.
4. Maybe enable **double-sided** (dowel registration) and/or **bed leveling**.
5. **Connect** to the machine (Arduino-over-SPI) for a live position readout (DRO),
   click-to-jog, and **Probe Z** touch-off.
6. **Export** the toolpaths and run them in Roland VPanel.

So it's part CAM editor, part **live machine cockpit**. That dual nature is part of
why the current UI feels cluttered.

---

## 2. How to run it

Windows, Python 3.12, there's a venv in the repo.

```bash
pip install -e ".[gui]"                 # one-time, installs PySide6 + matplotlib + pyqtgraph
python -m gerber2rml.gui.app            # launch (native desktop OpenGL)
GERBER2RML_GL=software python -m gerber2rml.gui.app   # CPU GL fallback (VM/RDP/no GPU)
```

**Sample boards to load** live in `examples/` — `examples/dowel_test/`,
`examples/level_test/`, `examples/hole_test/` are real Gerber folders. Load one of
these to get a non-empty preview to evaluate against.

**Environment quirks (will bite you):**
- `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1` may be needed to stop an OpenBLAS
  crash on `numpy` import in some shells.
- Headless smoke tests use `QT_QPA_PLATFORM=offscreen`.
- The Windows cp1252 console can't print unicode (●, →, Δ, ⌀) — keep stdout ASCII.
- The 3D views (`Simulate 3D`, bed `3D view`) need `pyqtgraph` + `PyOpenGL`; on
  Windows they force desktop GL (see `_configure_opengl`). If they come up blank,
  that's a known GL-context issue, not your redesign's fault.

**Tests:**
```bash
python -m pytest -q                     # full suite (~186 tests; keep them green)
python -m pytest tests/test_window.py -q # the GUI smoke/behaviour tests
```
`tests/test_window.py` constructs `MainWindow` offscreen and asserts on widget
state and signal wiring — if you rename/move widgets, update it in lockstep.

---

## 3. How it's built (where to work)

All GUI code is in `gerber2rml/gui/`. The business logic is deliberately **GUI-free**
and lives behind `gerber2rml/app/state.py` (`ProjectState`) — **do not** pull CAM
logic into the widgets; the GUI is meant to be thin glue.

| File | What it is | Touch for redesign? |
|------|------------|---------------------|
| `gui/app.py` | `MainWindow` — **all** layout, widgets, handlers, **and the QSS stylesheet** (`_STYLESHEET`, ~line 1393) + `apply_dark_theme`. ~1530 lines. | **Yes — this is the main target.** |
| `gui/canvas.py` | `PreviewCanvas` — matplotlib preview: toolpaths, bed, gaps, tool marker, level heatmap, box-select, drag-to-move, click-to-jog. | Yes — visual style of the preview, marker/overlay design. |
| `gui/form.py` | `DataclassForm` — auto-builds the parameter form from a job dataclass. Drives the Traces/Drill/Cut-out tabs. | Maybe — field grouping/labels/widgets. |
| `gui/bedviz.py` | 3D bed height-map window (pyqtgraph GL). | Style only, low priority. |
| `gui/sim3d.py` | 3D toolpath simulation window. | Style only, low priority. |
| `app/state.py`, `app/preview.py`, `app/presets.py` | GUI-free controller, preview geometry, presets. | **No** (logic) — read for understanding. |

**Styling today:** one big Qt stylesheet string `_STYLESHEET` at the bottom of
`app.py`, plus a Fusion `QPalette` in `apply_dark_theme`. Dark theme, blue (`#3b82f6`)
accent, rounded `QGroupBox` cards. It's a reasonable starting palette but applied
inconsistently. If you want a cleaner system, consider extracting the QSS to its own
file/module and introducing design tokens (colors, radii, spacing) instead of the
magic hex values scattered inline (the DRO/touch labels set inline `setStyleSheet`
with hardcoded colors — see `_DRO_ON`, `_TOUCH_ON`, etc.).

---

## 4. The current layout (so you know what you're changing)

```
┌──────────────────────────────────────────────────────────────────┐
│ MACHINE BAR:  ○ machine offline   bit ○      [Probe Z][Click to jog][Connect] │
├───────────────────────────────┬──────────────────────────────────┤
│  SETTINGS PANEL (scroll, 380+) │                                  │
│  ┌── Board ──────────────────┐ │                                  │
│  │ [Load Gerber][Export]     │ │                                  │
│  │ Name / Preset / Stock     │ │         PREVIEW CANVAS           │
│  │ Auto depth = stock + [bt] │ │        (matplotlib, right)       │
│  └───────────────────────────┘ │                                  │
│  ┌── Operations ─────────────┐ │     frame badge: AS MILLED / …   │
│  │ [Traces][Drill][Cut-out]  │ │                                  │
│  │  ...dataclass form...     │ │                                  │
│  └───────────────────────────┘ │                                  │
│  ☐ Show advanced options       │                                  │
│   └ (collapsible) ───────────┐ │                                  │
│     View / machine            │ │                                  │
│     Placement on bed          │ │                                  │
│     Bed leveling (grid+table) │ │                                  │
│     Double-sided (registration)│ │                                  │
│     Rework (2nd pass)         │ │                                  │
│   └────────────────────────── │ │                                  │
├───────────────────────────────┴──────────────────────────────────┤
│ STATUS BAR: transient messages                                     │
└──────────────────────────────────────────────────────────────────┘
```

- **Left:** a `QScrollArea` (`#settingsPanel`) of stacked `QGroupBox` cards. "Basic"
  cards (Board, Operations) are always visible; everything else hides behind the
  **Show advanced options** checkbox (`_advanced_box`).
- **Right:** `PreviewCanvas` in a `QSplitter` (panel min width 380, default sizes
  `[430, 1100]`).
- **Top:** a `machineBar` widget (DRO label + touch indicator + machine buttons).
- **Bottom:** `statusBar()` for transient feedback.

---

## 5. Where it flows/feels badly (my read — verify and add your own)

These are *symptoms I notice*, not prescriptions. Diagnose freely.

1. **Everything is a flat stack of cards.** The left panel is one long scroll. There's
   no sense of "step 1 → step 2." A first-timer doesn't know the happy path.
2. **The advanced toggle is all-or-nothing.** Flipping "Show advanced options" dumps
   five dense sections (View, Placement, Bed leveling, Double-sided, Rework) at once.
   It's a wall. These are really *different modes*, not one blob.
3. **The machine cockpit and the CAM editor are tangled.** The top machine bar (live
   DRO, jog, probe) is a different *mode of work* (you're at the mill, hands on)
   than setting up a job (you're at the desk). They share one cramped screen.
4. **Inconsistent control density & alignment.** Some rows are `QFormLayout` (right-
   aligned labels), others are ad-hoc `QHBoxLayout` `_row(...)`. Spinboxes, line
   edits, and combos don't share consistent width/sizing. The bed-leveling group
   crams nx/ny/4 buttons/port/checkbox/another button into two `_row`s.
5. **Status/feedback is weak.** Almost all feedback is a transient `statusBar`
   message that vanishes in 5–10 s. Connection state, leveling readiness, "is a
   board loaded?", export success — these deserve persistent, visible affordances.
6. **The preview's job vs. the controls' job is unclear.** The frame badge
   ("AS MILLED / AS DESIGNED") is good but easy to miss; the relationship between
   the View/Preview-orientation combos and what's on screen takes learning.
7. **Visual style is competent-but-flat.** Dark, blue-accented, rounded cards —
   fine, but inconsistent inline colors, no clear typographic scale, icons are the
   default Qt standard pixmaps (generic). It reads as "developer tool," and I want
   it to feel more deliberate and premium.
8. **Modal `QMessageBox` overuse.** Lots of warnings/confirms interrupt flow
   (`QMessageBox.warning/critical/question` everywhere). Some should be inline,
   non-blocking, or prevented by disabling the action.

Things that are **good and should survive** any redesign:
- The live preview is the heart of the app — keep it big and central.
- Auto-depth from measured stock thickness is a nice touch.
- The tool-position overlay + touch indicator (red on contact) is genuinely useful.
- The frame badge concept (telling you milled vs designed) is worth keeping/strengthening.

---

## 6. Concrete directions worth exploring (optional — your call)

You don't have to take these, but they're the kind of move I'm after:

- **A step / mode structure** instead of one scroll: e.g. a left rail or top
  segmented control for **Setup → Preview → Machine → Export**, or group the
  advanced sections into named modes the user opts into one at a time, rather than
  one mega-toggle.
- **Separate "desk" vs "mill" surfaces.** Consider promoting the machine cockpit
  (DRO, jog, probe, bed leveling) into its own panel/tab/dock that you switch to
  when you're physically at the machine, so the job-setup view stays calm.
- **A real design-token layer.** Extract QSS to its own file; define a small set of
  color/spacing/radius/typography tokens; apply them consistently (kill the inline
  `setStyleSheet` hex). Tighten the type scale (group titles vs labels vs values).
- **Persistent state chips/badges** for: board loaded (name + size), machine
  connected (port + live state), leveling ready (n points), double-sided on. So the
  user always knows the mode without hunting.
- **Better empty state.** With no board loaded, the preview is blank and the panel
  is full of disabled controls. A clear "Load a Gerber folder to begin" empty state
  would orient new users.
- **Custom iconography** over the default `QStyle.standardIcon` pixmaps.
- **Replace blocking dialogs** with inline validation / disabled actions where you
  can (e.g. disable Export until a board is loaded, instead of warning after click).

---

## 7. Hard constraints (do not break these)

- **Do not change CAM output.** Anything that alters exported geometry/G-code is
  out of scope. The dialed-in numbers are sacred: dowel clearances (**big +0.20,
  small +0.15 mm**), `DOWEL_BED_DEPTH = 5.0`, single-bit drilling default. Leave
  `doublesided.py`, `engine/`, `backends/`, `config.py` alone unless purely for
  reading.
- **Keep the GUI thin.** Logic stays in `app/state.py` and the engines. Don't move
  computation into widgets.
- **Keep the test suite green** (`pytest -q`, ~186 tests). `tests/test_window.py`
  asserts on widget existence, default states, and signal connections — when you
  restructure widgets, update those assertions rather than deleting coverage. If you
  rename a widget the tests reference (e.g. `level_table`, `connect_btn`,
  `auto_depth_chk`, `thickness_spin`, `tabs`), grep for it first.
- **Preserve every existing capability.** Redesign the *surfacing* of features, but
  don't drop features: load/export, presets, stock + auto-depth, the three op tabs,
  mirror, frame orientation, show-bed fit check, placement (spin + drag), bed
  leveling (grid/probe/CSV/heatmap/3D), double-sided (fresh + grid registration,
  clearances, "Cut dowels only"), rework box-select export, 3D simulate, export
  image, DRO/connect/jog/Probe-Z/touch indicator.
- **Don't push or commit to `main` without me.** Work on a branch
  (`feat/gui-redesign` or similar); show me before merging. Small, reviewable
  commits per coherent change.
- **The machine/SPI behavior is touchy** (single-read SPI garbage, Uno reset on port
  open, DRO jump-filter). If you touch `_DROPoller` / `_ProbeWorker` wiring, keep the
  threading model intact — see `docs/2026-06-25-srm20-spi-and-bed-leveling.md` and
  the `srm20-spi-remote-interface` memory note for why it's built the way it is. I
  can't have you test the live machine path, so be conservative there; focus the
  redesign on layout/style/flow, not the serial internals.

---

## 8. Suggested working order

1. `pip install -e ".[gui]"`, launch, load `examples/dowel_test/`, click through
   every tab, the advanced sections, and (if a machine isn't attached) at least
   read the machine-bar code path. **Screenshot the current state.**
2. Write a short **findings doc** (`docs/gui-audit-<date>.md`): what flows badly,
   ranked, with screenshots. Confirm/expand on §5.
3. Sketch a **target layout** (even ASCII/mock is fine) and a **design-token**
   palette. Run the big direction by me before a full rewrite.
4. Implement in passes: (a) extract + systematize the style layer; (b) restructure
   layout/flow; (c) polish interactions, empty states, feedback, icons. Keep tests
   green at each commit.
5. Re-screenshot before/after and summarize what changed and why.

---

## 9. Pointers / further reading

- `docs/2026-06-25-srm20-spi-and-bed-leveling.md` — why the machine cockpit, bed
  leveling, and dowel features exist and how they behave (the *why* behind the
  clutter).
- `docs/HANDOFF.md`, `docs/design.md`, `README.md` — architecture overview and the
  GUI-free-core philosophy.
- `docs/gui-manual-check.md` — existing manual-QA checklist for the GUI.
- Memory notes (`srm20-*`) capture machine facts dialed in on real hardware — don't
  contradict them.

The bar: when you're done, loading a board and exporting a job should feel obvious
and calm, the advanced/machine work should feel like deliberate modes rather than a
pile of cards, and the whole thing should look like a considered product, not a
control panel that grew by accretion.
