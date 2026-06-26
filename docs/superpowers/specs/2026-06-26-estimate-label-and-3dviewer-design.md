# Persistent estimate label + 3D Viewer tab — design

**Date:** 2026-06-26
**Status:** approved, ready for implementation

Two small GUI additions, one PR.

## 1. Persistent per-op run-time estimate

**Problem:** `_estimate_str` already computes "~3m 44s" for the current op, but
it's only flashed in the status bar for a few seconds. There's no persistent
estimate; the live Run bar only shows time once tracking is armed.

**Design:**
- `PreviewCanvas` gains `self.est_lbl` (a muted QLabel) on the bottom control bar,
  right end (after the slider), plus `set_estimate(text)` to set it.
- `MainWindow.generate_preview` calls `self.preview.set_estimate(...)` for the
  current op every refresh, using `estimate_toolpaths_seconds` + `format_duration`
  → e.g. `est ~3m 44s`. Covers single-sided traces/drill/cut-out and double-sided
  single-side (Bottom/Top) views. For the double-sided **both-sides** registration
  view (no single cut op) it shows `—`.
- Tooltip on the label: "Estimated cut time — optimistic; excludes spin-up, tool
  changes, pauses and accel/decel." (ties to the known calibration TODO so the low
  number isn't read as exact.)
- Display only: no change to the estimator math.

## 2. "3D Viewer" sidebar tab

**Problem:** the 3D views (toolpath simulation, bed height-map) open as separate
windows; once closed there's no obvious central place to re-open them.

**Design:**
- A 5th sidebar entry **"3D Viewer"** with a page of launch buttons wired to the
  **existing** handlers (no new view code):
  - **Simulate 3D (toolpaths)** → `_on_simulate_3d`
  - **Open & simulate file…** → `_on_simulate_file`
  - **3D bed / height-map view** → `_on_bed_3d`
- Views open as separate windows exactly as today.
- The existing contextual buttons on the Project and Bed-Leveling pages stay.
- Help text: each view's prerequisite (a loaded board for simulate; a probed/
  loaded height map for the bed view) and that the 3D views need PyOpenGL.

## Testing

- **Canvas** (`tests/test_canvas.py`): `set_estimate("est ~3m")` updates
  `est_lbl.text()`.
- **Window** (`tests/test_window.py`):
  - after load + `generate_preview` on Traces, `preview.est_lbl.text()` contains a
    duration; switching to Drill changes it.
  - sidebar has 5 rows; the 3D Viewer page exposes the three launch buttons and
    they are enabled.
  - the 3D-tab buttons call the same handlers (assert clicking triggers the
    handler, with the window-open monkeypatched).

## Out of scope (YAGNI)

- Embedding the 3D view inline in the tab (kept as separate windows).
- Whole-job total estimate near Export (per-op only).
- Any change to the estimator's accuracy (accel/decel calibration is its own task).
