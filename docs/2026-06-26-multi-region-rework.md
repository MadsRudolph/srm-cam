# Dev log — multi-region rework

**Date:** 2026-06-26
**Scope:** turn the single-box rework 2nd pass into a **multi-region** one — mark
every spot that needs re-cutting as its own coloured box with its own depth and
height-map-follow toggle, and export them all as **one** G-code file.

Spec: [`docs/superpowers/specs/2026-06-26-multi-region-rework-design.md`](superpowers/specs/2026-06-26-multi-region-rework-design.md).
Plan: [`docs/superpowers/plans/2026-06-26-multi-region-rework.md`](superpowers/plans/2026-06-26-multi-region-rework.md).

---

## Why

Bed leveling still left a few traces not cut all the way through. The old rework
flow handled exactly one box: select, set depth, export, repeat — many selections,
many files. The fix: mark them all, set a depth per spot, export once.

## What changed

- **Engine** (`engine/select.py`): new pure `clip_toolpaths_to_regions(toolpaths,
  regions)` where `regions = [(bbox, cut_z), ...]` — clips per box via the existing
  `clip_toolpaths_to_bbox` and concatenates into one program. Empty boxes
  contribute nothing.
- **Canvas** (`gui/canvas.py`): now a multi-region renderer + drag source. It
  draws a list of `(bbox, color, label)` rectangles (each with its depth label)
  and fires `on_region_added(bbox)` on each committed drag. The old single-box
  `selection_bbox()` / `clear_selection()` / `on_selection_changed` are gone — the
  app owns rework state.
- **App** (`gui/app.py`): a region list `[{bbox, depth, follow, color}]` and a
  **table** in the Rework panel — `# (colour) · size · depth (editable) · lvl ·
  delete`. The **New-box depth** spin and **Follow height map** checkbox are now
  the *defaults for the next drawn box*; each box overrides them in the table.
  `_rework_clip_regions` clips every region at its depth, applies that region's
  height-map follow, and concatenates. Export writes one
  `<name>_<side>_<op>_rework.<ext>`. The run-progress "selection" tracking and the
  3D rework simulation both use the full region set now.

## Behaviour notes

- Regions clip the **currently-shown op/side** at export (unchanged — typically
  traces; drill isn't reworkable; a double-sided board needs a single side shown).
- Colours come from a fixed palette by add-order; deleting doesn't recolour the
  survivors.
- One region behaves exactly like the old single box, so nothing is lost.

## Tests

- Engine: two boxes at different depths → one concatenated program at the two Z
  values; empty boxes skipped; empty list → empty.
- Canvas: `set_rework_regions` draws/clears the rectangles; a select-drag fires
  `on_region_added`.
- GUI: add/delete/clear regions and the table track them; per-row depth edit
  updates the region; export with two regions writes one file containing both
  depths; export with zero regions is refused. Suite green.

## Not done (YAGNI)

- Cross-op rework in one file (traces + cutout together).
- Click-a-box-on-canvas-to-delete (table delete only).
- Per-region feeds/speeds; persisting regions in the saved setup.
