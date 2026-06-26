# Settings panel / preview layout — design

**Date:** 2026-06-26
**Status:** approved, ready for implementation

## Problem

The main window is a horizontal `QSplitter` of `[settings_container | preview]`.
`settings_container` is `sidebar (180px fixed) + a QStackedWidget of scrolling
field pages`, with `setMinimumWidth(450)` and an initial split of `[550, 550]`.
The scroll pages use `setWidgetResizable(True)`, so the field widget is forced to
the panel's width — when the panel is narrower than the fields need, the fields
get **clipped**. The operator then drags the divider wider to see them, which
steals space from the preview. So the divider has to be fiddled with constantly.

## Decision (locked with the user)

**Auto-fit panel + collapse button.** The panel can never shrink below what the
fields need; the preview absorbs all resizing; a top-bar button collapses the
panel for a full-width preview.

## Changes

All in `gerber2rml/gui/app.py`, in the `settings_container` / `QSplitter` block.

1. **Fit width:** set `settings_container.setMinimumWidth(520)` (sidebar 180 +
   ~340 for the widest field row). The field pages can no longer be squeezed
   below their content, so nothing is clipped.
2. **Preview absorbs resizing:** keep `setStretchFactor(0, 0)` (settings) and
   `setStretchFactor(1, 1)` (preview). Mark the preview non-collapsible
   (`splitter.setCollapsible(1, False)`) and the settings collapsible
   (`splitter.setCollapsible(0, True)`).
3. **Initial split:** replace `setSizes([550, 550])` with
   `setSizes([520, 10000])` so the panel opens at its fit width and the preview
   takes the rest.
4. **Collapse toggle:** a small checkable button on the machine bar (label
   ``"◀"`` expanded / ``"▶"`` collapsed, tooltip "Hide/show settings").
   `_on_toggle_panel(collapsed)` hides `settings_container` when collapsed and
   shows it (restored to its previous width) when expanded. Hiding the widget —
   rather than zeroing splitter sizes — is simple and robust; the splitter
   handle disappears with it.

## Error handling / edge cases

- Restoring after collapse re-shows the panel at its prior width (Qt keeps the
  splitter sizes for the still-present widget; `setVisible(True)` is enough).
- Non-collapsible preview means the panel-collapse can never hide the preview.

## Testing

`tests/test_window.py` (offscreen):
- `settings_container.minimumWidth()` is at the fit value (>=520).
- the collapse toggle hides the panel (`isVisible()` False) then restores it
  (`isVisible()` True) and the preview stays visible throughout.

## Out of scope (YAGNI)

- A detachable / pop-out settings window.
- Remembering collapse state across sessions.
- Per-page width tuning beyond one sensible panel min width.
