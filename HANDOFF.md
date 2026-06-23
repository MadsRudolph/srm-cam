# Handoff — Rework selection + 3D toolpath viewer

Branch: `feature/3d-toolpath-viewer-and-rework`

This branch adds three GUI features plus a Windows OpenGL fix. **Status: the 3D
viewer renders correctly in an isolated probe, but the user reports it is still
not working correctly in normal use — this needs to be revisited.** Everything
else (rework selection + clipped export, the file parser, all unit tests) is
working.

> Scope note: this branch intentionally contains **only** the files for these
> features. A separate concurrent work stream was touching `backends/srm20.py`,
> `docs/*`, `legacy/*`, and a couple of other tests; those were deliberately
> left out of this commit.

---

## 1. Rework selection (2nd pass) — WORKING

Re-cut just a region of an isolation/cutout pass when some traces weren't milled
all the way through, instead of re-running the whole job.

- **GUI**: a *Rework (2nd pass)* group in the left panel — `Select area` toggle,
  `Clear`, and `Export selected NC...`. With Traces/Cutout previewed, drag a box
  over the area; a dashed green rectangle persists across slider scrubs/redraws.
  Export writes `<name>_<op>_rework.<ext>` containing only the clipped toolpaths.
- **Engine**: `gerber2rml/engine/select.py` — `clip_toolpaths_to_bbox(toolpaths, bbox)`.
  Liang–Barsky segment clipping trims cut geometry exactly to the box (segments
  passing through the box with no interior vertex are caught), then rebuilds a
  rapid → plunge → cut → retract cycle per retained run. Cut depth is preserved
  (faithful repeat pass).
- **Tests**: `tests/test_select.py` (7), `tests/test_canvas.py` (selection cases).

## 2. 3D toolpath simulator (pyqtgraph/OpenGL) — RENDERS IN PROBE, NEEDS REVISIT

ncviewer.com-style player: orbit/zoom/pan a 3D scene and play a tool head along
the path. Rapids ride up at travel height, cuts dip to depth (Z shows
lift/plunge).

- **GUI**: `Simulate 3D` button (Project group). Simulates the active tab's
  toolpaths; if a rework box is active on Traces/Cutout it plays just the clipped
  path. Drill now uses the real exported drill toolpaths (per-diameter /
  single-bit interpolation) via `_drill_toolpaths`.
- **Window**: `gerber2rml/gui/sim3d.py` — `Simulation3DWindow`. Cyan cuts, dim
  rapids, amber "already-cut" trail, a red endmill cone, Play/Pause, Reset, speed
  slider, scrub timeline, live X/Y/Z/% readout.
- **Engine (pure, tested headless)**: `gerber2rml/engine/simulate.py` — flattens
  Move lists into a continuous path with cumulative arc length and interpolates
  the tool position (`build_path`, `position_at`, `index_at`, `split_segments`).
- **Tests**: `tests/test_simulate.py` (7).

## 3. Open & simulate any exported file — WORKING (parser), viewer same as #2

Load any `.nc` or `.rml` we exported (traces, each drill file, cutout, or a
rework file) and play it — covers drill/cutout/rework uniformly.

- **GUI**: `Open & simulate file...` button (Project group).
- **Engine**: `gerber2rml/engine/gcode_parse.py` — `parse_nc` (modal G0/G1, skips
  G28 homing), `parse_rml` (Z x,y,z moves; rapid/cut from VS/!VZ feed pairing;
  unit scale read from `srm20.SCALE` so it always matches the writer), and
  `parse_file` dispatching by extension.
- **Tests**: `tests/test_gcode_parse.py` (7 round-trip render→parse).

## 4. Windows OpenGL fix — verified in probe

`gerber2rml/gui/app.py::_configure_opengl()` runs **before** `QApplication` is
created and forces the native desktop GL driver (`AA_UseDesktopOpenGL`) + a
compatibility surface format.

- **Why**: Qt on Windows often defaults to an ANGLE (GLES-over-D3D) context.
  pyqtgraph 0.14's desktop GLSL shaders fail to link under ANGLE → `GL_INVALID_VALUE`
  on `glUseProgram` → blank window / error storm (this was the original bug).
- **Env override**: `GERBER2RML_GL=software` (Mesa llvmpipe, for RDP/VM/no-GPU),
  `=angle` (old behaviour), default `desktop`.
- **Probe result**: with desktop GL forced, the sim scene rendered cleanly —
  488×456 frame, 3429 non-background pixels, **0 GL errors**.

---

## ⚠️ Open issue — "still not working correctly"

The isolated probe rendered fine, but the user reports the 3D viewer still isn't
right in actual use. Not yet diagnosed. Things to check when revisiting:

1. **Reproduce precisely**: what does "not working" look like now — still GL
   errors, blank/black window, wrong geometry, no animation, or a crash? Capture
   the exact console output after the `_configure_opengl()` change (the original
   error log predates the fix).
2. **Confirm the fix is actually taking effect**: `_configure_opengl()` only runs
   when `QApplication.instance() is None`. If something constructs a QApplication
   earlier, the attribute is silently ignored. Verify the GL renderer at runtime
   (should be the native GPU, not "ANGLE ...").
3. **Drill visibility**: drill plunges are ~1.8 mm tall on a board tens of mm
   wide — easy to miss from the default camera. Consider a **Z-exaggeration
   slider** and/or hole markers. (This may be what reads as "not working" for the
   drill view specifically.)
4. **GLMeshItem cone** uses `shader='shaded'` (needs normals/lighting); if only
   the cone misbehaves, try `shader='balloon'` or a `GLScatterPlotItem` marker.
5. **Software fallback**: have the user try `GERBER2RML_GL=software` to isolate
   driver vs. code issues.

## How to run

```
python -m gerber2rml.gui.app          # native desktop GL (default)
GERBER2RML_GL=software python -m gerber2rml.gui.app   # CPU fallback
```

## Dependencies added (pyproject.toml, `gui` extra)

`pyqtgraph>=0.13`, `PyOpenGL>=3.1`. Installed in the env:
pyqtgraph 0.14.0, PyOpenGL 3.1.10, PyOpenGL_accelerate 3.1.10.

## Test status

All added tests pass headless (`QT_QPA_PLATFORM=offscreen`): full suite was
121 passed at handoff time (note: that count included the concurrent stream's
changes in the working tree; on this branch alone re-run to confirm).

## Files in this branch's commit

```
gerber2rml/engine/select.py        (new)  rework clipping
gerber2rml/engine/simulate.py      (new)  playback model
gerber2rml/engine/gcode_parse.py   (new)  .nc/.rml parser
gerber2rml/gui/sim3d.py            (new)  3D viewer window
gerber2rml/gui/app.py              (edit) buttons, handlers, GL config
gerber2rml/gui/canvas.py           (edit) box-selection on the 2D preview
pyproject.toml                     (edit) pyqtgraph + PyOpenGL
tests/test_select.py               (new)
tests/test_simulate.py             (new)
tests/test_gcode_parse.py          (new)
tests/test_canvas.py               (edit) selection tests
HANDOFF.md                         (new)  this file
```
