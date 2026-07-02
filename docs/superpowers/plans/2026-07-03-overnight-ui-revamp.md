# Overnight UI revamp — execution contract (2026-07-03, user asleep)

User directive: wake up to a totally new, revamped UI. Visually distinct,
NOT cluttered, but full control still available (progressive disclosure).
Emphasize usability, new features, intelligence. Work autonomously all night
on branch `feat/gui2-phase3-frame-unification` (stacked on PR #26); commit
after every green step; full pytest before each commit. Do NOT touch the
installed app until the final tested build; then build the installer and
attempt silent install (if UAC blocks it, leave the installer + a one-line
morning instruction).

## Order of work

1. **Finish phase 3 (frame unification)** per
   2026-07-03-gui2-phase3-frame-unification.md — steps 2b..6: migrate the
   remaining branch points (_apply_preview_frame, _display_outline, gating),
   add the visible two-state frame switcher (Bed as cut / Design X-ray) +
   side selector, X-ray canvas tint + disabled machine actions with hints,
   delete mirror/frame-combo view special-casing (mirror becomes
   export-property near Export), session migration for old keys, tour
   re-targeting. This kills the single biggest confusion source.
2. **Runplan spine (phase 4, the "new GUI" feel)**: replace the category
   sidebar with the job's step list — Setup, Bed leveling, Align, Drill,
   Bottom traces, Cutout, Flip, Top traces (+ Rework tool). Steps show
   state chips (pending/exported/running/done — run tracking feeds
   "running/done", export actions mark "exported"); NEVER blocking:
   clicking a step selects its op/view context but every control stays
   reachable. Between-step notes (bit change, spindle RPM) shown in the
   step's detail line. Old pages become sections shown per-step; Bed
   Leveling and Double-Sided content reachable from their steps; a "All
   settings" spine entry keeps full control (progressive disclosure).
3. **Declutter with progressive disclosure**: group boxes get a compact
   default (the 3-5 controls an operator uses) + an "Advanced" expander for
   the rest. No feature removal.
4. **Intelligence**:
   a. Auto travel check after every fiducial fit/export: warp the top
      toolpath extents (code exists in scratchpad travel_check.py logic —
      reimplement in app) vs BACKENDS bed; statusbar + dialog with the
      exact "slide the board X mm" correction. Also run at export time for
      any job; warn if paths exceed the bed.
   b. Contextual next-step hint line under the spine (e.g. "Drill done —
      queue bottom traces in VPanel; same bit").
   c. Preflight chips on the canvas (existing DESIGN EXCEEDS badges stay).
5. **New visual theme**: rewrite apply_dark_theme QSS — new palette
   (deep slate #14171c surfaces, #1c2128 panels, cyan #4dd0e1 accent for
   actions, amber only for machine-live elements, red only STOP), larger
   type for section headers, consistent 8px spacing rhythm, flat buttons
   (drop the orange gradient), restyled spine with state chips. The goal:
   instantly reads as a NEW app. Keep contrast accessible.
6. **Verify**: full pytest; offscreen full-window renders (light content +
   DS mode + spine states) reviewed via Read; update tour texts if
   anchors moved. Bump nothing version-wise (still pre-release branch).
7. **Ship**: build installer; try silent install (Get-Process guard);
   if exit != 0 leave `dist_installer\SRM-CAM-Setup-0.2.1.exe` ready and
   write the morning message: one double-click + the flip-direction /
   board-slide steps from the earlier travel verdict.

## Invariants (regression bait — do not break)
- Machine-frame drill views, AS PLACED warp, reflected pins, probe grid
  over displayed outline, snap-jog on displayed markers, fit-first
  fiducial flow with prefilled dialog, flip-axis selector, leveled
  fiducial export, always-enabled rework export, machine dock contents.
- Session files from all earlier versions must still load (map old keys).
- All 368+ tests stay green; add tests for: frame switcher mapping,
  X-ray action gating, spine step state transitions, travel-check math,
  session migration.

## Morning deliverables checklist
- [ ] Phase 3 complete (switcher, tint, migration, tests)
- [ ] Runplan spine replacing sidebar
- [ ] Progressive disclosure pass
- [ ] Auto travel check + hints
- [ ] New theme applied + screenshots rendered
- [ ] Full suite green, branch pushed
- [ ] Installer built; installed or ready with instruction
- [ ] Morning brief message: what changed, how to use it, the physical
      steps for the top side (installer click, flip check, board slide)
