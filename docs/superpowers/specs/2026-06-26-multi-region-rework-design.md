# Multi-region rework — design

**Date:** 2026-06-26
**Status:** approved, ready for implementation plan

## Problem

The rework (2nd pass) feature re-cuts copper that an isolation pass left not fully
isolated. Today it handles exactly **one** box: drag a rectangle, set a depth,
export, repeat. With many spots to fix, that's one-selection-one-file at a time —
tedious and produces many files to stream.

Goal: mark **all** the spots at once as distinct coloured boxes, set a depth (and
height-map follow) **per box**, and export them as **one** G-code file.

## Decisions (locked with the user)

| Decision | Choice |
|---|---|
| Region management | A **table** of regions: each drag adds a coloured box + a row (#/colour, size, editable depth, follow toggle, delete). |
| Height-map follow | **Per-region** toggle (each region decides whether to warp to the probed surface). |
| Depth source | A new region takes the current **Rework depth** spin value as its default; editable per-row after. |
| Single vs multi | Not a separate mode — one region is just a list of length 1. The old single-box behaviour is subsumed. |
| Scope per export | Regions clip the **currently-shown op/side** at export (same as today; typically traces). |
| Colours | Assigned from a fixed palette by add-order; deleting does not recolour survivors. |

## Architecture

Region model (one dict per region, owned by `MainWindow`):
`{bbox: (x0,y0,x1,y1), depth: float, follow_level: bool, color: str}`.
Geometry/colour are drawn by the canvas; depth/follow are app concerns. The
canvas stays a renderer + drag source — it does not own rework state.

### 1. Engine — `gerber2rml/engine/select.py`

Add one pure, tested primitive (the existing `clip_toolpaths_to_bbox` is
unchanged and reused):

```python
def clip_toolpaths_to_regions(toolpaths, regions):
    """regions: list of (bbox, cut_z). Clip toolpaths to each region at its
    cut_z and concatenate into one program (regions in given order). Regions
    that capture nothing contribute nothing."""
```

### 2. Canvas — `gerber2rml/gui/canvas.py`

- `self._rework_regions = []` — draw list of `(bbox, color, depth_label)`;
  `set_rework_regions(regions)` stores it and redraws.
- A drag in select-mode no longer *persists* one box. On release it fires a new
  `on_region_added(bbox)` callback (set by the app); the live rubber-band still
  shows during the drag.
- `_add_rework_patches()` draws every stored region in its colour (dashed) with a
  small depth label, plus the in-progress rubber-band. Replaces the single
  `_add_selection_patch()` in the redraw paths.
- `clear_regions()` empties the draw list. The app now owns rework state, so the
  canvas's old single-box `selection_bbox()`/`_selection_bbox` and the
  `on_selection_changed` callback are removed; their consumers (export,
  run-progress, simulate, button-enable) move to the app region list (below).

### 3. App — `gerber2rml/gui/app.py`

- `self._rework_regions = []` (the region dicts) + a `_REWORK_COLORS` palette.
- A **QTableWidget** in the Rework panel: columns
  `# (colour swatch) · size (w×h mm) · depth (editable QDoubleSpinBox) · follow
  (QCheckBox) · delete (QPushButton)`. Editing depth re-labels the box; toggling
  follow updates the region; delete removes it and re-pushes the draw list.
  **Clear** empties all regions.
- `on_region_added(bbox)` handler: append a region with the current spin depth +
  current follow-checkbox default + next palette colour; refresh table + canvas.
- `_rework_clip_regions(toolpaths)`: for each region, clip via the engine at its
  depth, apply that region's height-map leveling if `follow_level` and a probed
  map exists, concatenate. Returns `(paths, n_leveled)`.
- `_on_export_selected` → exports **all** regions to one
  `<name>_<side>_<op>_rework.<ext>`; refuses if there are zero regions or the op
  is drill / no side chosen (same guards as today).
- **Run-progress** ("selection" tracking) and the **rework simulation** switch
  from the single `selection_bbox()` to `_rework_clip_regions`, so they cover the
  whole multi-region rework job. Both refuse when there are zero regions.
- The existing **Rework depth** spin and **Follow height map** checkbox become
  the *defaults for the next drawn region* (labels updated to say so).

## Data flow

```
drag box ─► canvas.on_region_added(bbox)
        ─► app appends {bbox, depth=spin, follow=chk, color=palette[n]}
        ─► app refreshes table + canvas.set_rework_regions(draw_list)
   [edit depth / toggle follow / delete in the table → update region → refresh]
export ─► _rework_clip_regions(toolpaths of current op/side):
            for each region: clip_toolpaths_to_regions(tp, [(bbox,-depth)])
                              + per-region apply_leveling if follow
            concatenate ─► backend.render ─► one <name>_<side>_<op>_rework.<ext>
```

## Error handling

- Export / run-progress / simulate with **zero regions** → clear message, no file.
- A region that captures no toolpaths contributes nothing; if *all* do, the export
  reports "nothing inside the boxes" (today's empty-selection message).
- Depth spin range/decimals mirror the existing Rework depth spin (0–5 mm).
- Deleting the last region disables the export button (driven by region count).

## Testing

- **Engine** (`tests/test_select.py`): two boxes at different depths → one
  concatenated program, each run at its own Z; a box that misses all geometry
  contributes nothing; region order preserved; empty list → empty result.
- **GUI** (`tests/test_window.py`, offscreen): simulating `on_region_added`
  twice grows `_rework_regions` and the table to 2 rows; editing a row's depth
  updates the region; delete shrinks it; export with 2 regions writes one
  `_rework` file whose text contains both depths' Z values; export with 0 regions
  is refused (no file, warning).
- **Canvas** (`tests/test_canvas.py`): `set_rework_regions` with 2 regions adds 2
  rectangle patches; a select-mode drag fires `on_region_added` with the box.

## Out of scope (YAGNI)

- Cross-op rework in one file (e.g. traces + cutout together).
- Click-a-box-on-canvas-to-delete (table delete only).
- Per-region feeds/speeds (only depth + follow vary; feeds come from the op).
- Persisting regions in the saved setup file.
