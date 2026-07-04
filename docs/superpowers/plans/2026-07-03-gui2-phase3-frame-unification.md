# GUI 2.0 phase 3 — frame unification (implementation map)

Branch: `feat/gui2-phase3-frame-unification` (stacked on phase 2 / PR #26).
Design: docs/2026-07-02-gui2-cockpit-design.md §"One frame, one switcher".

## Target model

One user-facing control, `frame_switch`, two states:
- **Bed (as cut)** — DEFAULT. Machine coordinates, always. Single-sided: the
  mirrored as-milled frame (mirror stays an EXPORT property, not a view
  toggle). Double-sided: the machine frame of the selected side (side
  sub-selector Bottom/Top remains, X-ray's "Both" merges into Design X-ray).
  Click-to-jog, snap, rework, probe grid, DRO overlay all live here — this is
  the frame where they are truthful (AS PLACED warp included on Top).
- **Design X-ray** — inspection only. Un-mirrored design frame, both layers
  registered. Tinted canvas background (#232030) + green badge so it cannot
  be mistaken for the cutting frame. Jog/rework/probe-grid actions disabled
  here with an explanatory statusbar hint (never silently).

## Steps (each ships green; run full pytest between)

1. `_resolve_frame()` on MainWindow: returns ("bed"|"xray", side) from the
   new switch + side selector; ALL existing branch points (generate_preview,
   _preview_double_sided, _apply_preview_frame, _display_outline,
   _level_bounds, _diag_bounds, rework gating, pin-drag gating) read it
   instead of double_sided_chk/view_combo/mirror_chk combinations.
2. UI: `frame_switch` (segmented combo) + side selector in View/machine
   group; `mirror_chk` becomes export-only ("Mill mirrored (bottom-up)")
   moved next to Export; `frame_combo` (KiCad-top display flip) deleted —
   its job is subsumed by Design X-ray. view_combo absorbed by side
   selector; keep the attribute as an alias for session/tour compat.
3. Badges from the resolver only: "BED · bottom (as cut)" / "BED · top (as
   placed)" when _top_fit / "DESIGN · X-ray (inspection)". Delete the badge
   text spread across _apply_preview_frame branches.
4. Canvas: `set_inspection(bool)` — X-ray tint + disables jog/select/move
   interactions with hint.
5. Session: save frame_switch/side; map old keys (view, frame, mirror) on
   load for old setups. Tour steps re-targeted (steps.py references
   view_combo/mirror_chk — check test_tour).
6. Tests to update: test_window frame/badge/view tests, preview branch
   tests; add: resolver truth table, X-ray disables jog, old-session
   migration.

## Invariants to preserve (regression bait from this week)
- Drill Bottom/Top views stay machine-frame (holes physically placed).
- AS PLACED top warp + pins reflected-then-fitted.
- Probe grid over displayed (=bed-frame, as-placed) outline.
- Snap-jog uses displayed markers only.
- Estimates/status lines per op unchanged.
