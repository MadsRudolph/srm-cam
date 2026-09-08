# What the setup sheet still lacks from the original interface

*Audited 2026-09-08 against `gerber2rml/gui/app.py` (6,888 lines, every
`_on_*` / `action_*` handler) and `gerber2rml/gui2/*`. The setup sheet is
the product; the original is shipped behind `--original` for continuity
only.*

**Ported the same evening.** Everything the audit found missing or partial
crossed over in six batches (commits fe6da0a through cef0538), each with
its own tests: `tests/test_gui2_batch1.py`, `_leveling_port.py`,
`_rework_port.py`, `_doublesided_port.py`, `_machine_port.py`,
`_checks_port.py`. The tables below keep the original findings, with the
status column updated, so the reasoning behind each port stays readable.
What is still not in the setup sheet, on purpose:

- **The guided tour.** Its step explanations live in the steps; its
  machine lessons live under *Help → The machine, in five minutes*.
- **The feed test card.** Dropped in the A/B; not asked for since.
- **Hide the settings panel.** The regions are fixed on purpose (A/B §3.7).
- **The 2D toolpath scrub slider.** The 3D view has the timeline.

Two corrections to the audit itself: "Default depth for the next box"
was already in the setup sheet (`rework.py` *Depth for the next box*), and
the original's "Probe boxes" deepened with the sign inverted relative to
how the height map is applied; the port uses the physically consistent
sign and says so in `rework.deepen_from_probe`'s docstring. Worth checking
on hardware.

Status key: **PORTED** (an equivalent exists), **PARTIAL** (less than the
original; the gap is named), **MISSING** (no equivalent), **DROPPED** (the
A/B write-up says it was left out deliberately, with the reason).

## Job setup

| Feature | Original | Setup sheet | Notes |
|---|---|---|---|
| Load Gerber folder, export (Ctrl+O / Ctrl+E) | `app.py:654,663` | PORTED `window.py:488,495` | |
| Job name, backend, mirror | `app.py:713–719` | PORTED `inspector.py:170,410` | |
| Presets: apply, save | `app.py:1409–1440` | PORTED `inspector.py:177–189` | Save-as is Full-only in both |
| Per-operation parameters | `app.py:1548`, `form.py` | PORTED (2026-09-08) `inspector.py:907–1008` | Missing: tool type (flat / V-bit), tip diameter, included angle, target width, peck retract. A V-bit job is only possible if a preset already defines it, although `tier.py:93` promises "V-bit geometry" in Full |
| V-bit cross-section | `app.py:1543` | PORTED `inspector.py:196` | |
| Stock thickness, auto depth | `app.py:1216` | PORTED `inspector.py:207` | |
| Copper sheet size, corner, draw toggle, corner-from-tool | `app.py:820–853` | PORTED `inspector.py:243–266` | |
| Centre the design on the copper sheet | `app.py:895,5995` | PORTED (2026-09-08) | Only *Centre on the bed* exists (`window.py:672`); not the same when the sheet is not the whole bed |
| Place, drag, nudge, rotate | `app.py:771–800` | PORTED `inspector.py:353–390`, `stage.py:596,889` | |
| Measure tool (drag a line, snaps to corners, edges, holes) | `app.py:810`, `canvas.py:1076` | PORTED (2026-09-08) | `stage.py:428` has snapping, but only for jog clicks |
| "As designed (KiCad top)" preview | `app.py:731` | PORTED (2026-09-08) `window.py:448,774` | X-ray frame is disabled on single-sided jobs, so most users cannot check against the KiCad view |
| Toolpath scrub slider in 2D | `canvas.py:31` | **MISSING** | Only the 3D sim has a timeline |
| Hide the settings panel | `canvas.py:47` | DROPPED | A/B §3.7: regions are fixed on purpose |

## Checks

| Feature | Original | Setup sheet | Notes |
|---|---|---|---|
| Pre-flight diagnostics | `app.py:5527` | PORTED, better `inspector.py:728` | A page, not a message box |
| Shorts banner and export confirm | `app.py:4832` | PORTED, better `window.py:1653` | |
| Narrow copper gaps drawn red | `app.py:3475` | PORTED (2026-09-08) | Slivers too narrow to isolate are a different failure from a short; only the short is reported |
| Screw heads vs the real buffered toolpaths | `app.py:5598,5563` | PORTED (2026-09-08) | Replaced by a copper-keepout approximation (`window.py:1633`) that misses a screw inside the cut-out band |
| Hand-picked screw review | `app.py:5674` | PORTED (2026-09-08) `window.py:2941` | A one-shot toast, not a standing check |

## Export

| Feature | Original | Setup sheet | Notes |
|---|---|---|---|
| Export, run plan, open folder | `app.py:4876,4798` | PORTED, better `sheet.py` | |
| Screw fixture, bed fixture | `app.py:889,862` | PORTED `window.py:534,536` | Moved to the Machine menu |
| Cut dowels only (re-cut the pin holes deeper) | `app.py:1300,4917` | PORTED (2026-09-08) | `build_align_only` unused; when a pin does not seat there is nothing to do but re-export everything |
| Preview image and board summary (`gerber2rml.report`) | `app.py:701,4775` | PORTED (2026-09-08) | |
| Tool-wear ledger and "WORN" note | `app.py:4903` | PORTED (2026-09-08) | |
| Rework NC export | `app.py:1472` | PORTED `rework.py:127` | |

## Bed levelling

| Feature | Original | Setup sheet | Notes |
|---|---|---|---|
| Grid, probe, per-point files, CSV save/load, clear, overlays, 3D map, apply on export | `app.py:905–998` | PORTED `leveling.py` | Larger grids; points sent relative to the tool |
| Resume probing (only the unfilled points) | `app.py:4521,4507` | PORTED (2026-09-08) | After a STOP every point is re-probed |
| Drift check, re-touch every N points | `app.py:971` | PORTED (2026-09-08) | `ProbeRun` has no retouch |
| Mesh check: outliers, refinement rows | `app.py:982,3676` | PORTED (2026-09-08) `leveling.py:866` | Only the depth recommendation survived |
| Export the top traces levelled after the flip | `app.py:934,4939` | PORTED (2026-09-08) `fiducial.py:639` | Only via the fiducial page. On a dowel job the top-face map is measured and never used |

## Machine control

| Feature | Original | Setup sheet | Notes |
|---|---|---|---|
| STOP, Escape, ports, DRO, jog, spindle, view position, click-to-jog, stream, machine test | various | PORTED `machine.py`, `window.py` | Escape is *fixed* in the setup sheet (`window.py:406`) and still broken in the original with a modal open |
| Probe Z and Zero Z as separate actions | `app.py:1044,1051` | PORTED (2026-09-08) `machine.py:428` | One button; `touch_off` exists on the link with nothing calling it |
| Pause / Resume | `app.py:1084,1090` | PORTED (2026-09-08) | STOP is the only way to hold a job |
| Arrow-key tool jog over the canvas | `app.py:4030` | PORTED (2026-09-08) | Arrows nudge the board placement instead |
| Tool trail | `app.py:1033` | PORTED (2026-09-08) | |
| Align overlay to the bit (trim when G54 is not where the design sits) | `app.py:1145,3993` | PORTED (2026-09-08) | |
| Run-progress tracking, ETA, auto-start on motion | `app.py:1167–1200,4054–4206` | PORTED (2026-09-08) | `engine.progress` unused. A/B §8 justified removing the three stacked bars, not the tracking |
| Workflow status chips | `app.py:4136` | PORTED (2026-09-08) | Rail marks and the machine chip cover part; no single glance at mesh / fit / photo / boxes |

## Photo and rework

| Feature | Original | Setup sheet | Notes |
|---|---|---|---|
| Photo on the bed, phone hand-off, clear, boxes, per-box depth, rework export | various | PORTED `photo.py`, `phonephoto.py`, `rework.py` | |
| Auto-crop a phone photo to the copper | `app.py:6177` | PORTED (2026-09-08) | |
| Choose which holes anchor the photo | `app.py:1494,6102` | PORTED (2026-09-08) | Always auto-picked; the original's tooltip says why that fails on single-sided boards |
| Photo opacity and trace-dim sliders | `app.py:1513,1518` | PORTED (2026-09-08) | Fixed at 0.55 |
| Per-box "follow height map" | `app.py:1462` | PORTED (2026-09-08) | A rework cut on a bowed board ignores the mesh |
| Default depth for the next box | `app.py:1449` | PORTED (2026-09-08) | Minor |
| Detect uncut channels from the photo | `app.py:1525,6455` | PORTED (2026-09-08) | |
| Probe the boxes and deepen by measured error | `app.py:1536,6357` | PORTED (2026-09-08) | The only way to find a too-shallow cut |

## Panels and double-sided

| Feature | Original | Setup sheet | Notes |
|---|---|---|---|
| Double-sided, registration method, fiducial count / placement / offset / diameter, fit, fit-and-export, auto finder | various | PORTED `inspector.py:423–481`, `fiducial.py` | The setup sheet also re-warps the cut-out |
| Multi-board panels | – | Setup sheet only | |
| Dowel sub-mode: fresh-milled vs grid-seated pins | `app.py:1247` | PORTED (2026-09-08) | `window.py:187` drops it on load |
| Dowel edge pair (flip axis) | `app.py:1254` | PORTED (2026-09-08) | |
| Grid pitch, pin diameter, per-pin clearances, bed-bite depth | `app.py:1268–1294` | PORTED (2026-09-08) | Bite depth hardcoded (`window.py:1245`) |
| Manual fiducial placement (drag pins) | `app.py:1336,3166` | PORTED (2026-09-08) | The escape hatch for boards too big for the corner schemes |
| Fiducial flip direction | `app.py:1387` | PORTED (2026-09-08) | The fit cannot detect a wrong flip; a wrong assumption mirrors the top side |

## Setups and sessions

| Feature | Original | Setup sheet | Notes |
|---|---|---|---|
| Save / load setup, height map inside it | `app.py:5178,5249` | PORTED (2026-09-08) `window.py:2613,2668` | Not saved: rework boxes, photo and anchors, fiducial flip / scale / manual points, all dowel geometry. Losing the rework boxes on a restart costs real work |
| Reads the other interface's setups | – | Setup sheet only `window.py:180` | |
| Workspace folders, tiers | `workspace.py`, `mode.py` | PORTED | Separate QSettings scope, so nothing remembered is shared between the two |

## Help, tour, updates, KiCad

| Feature | Original | Setup sheet | Notes |
|---|---|---|---|
| Guided tour, first launch and replay | `gui/tour/` | DROPPED | A/B §8: explanations moved into the steps. The tour's levelling branch taught G54 vs MACHINE coordinates, the Z travel limit and where to clip the probe leads; that content has no home now |
| F1 / link to the web guide | `app.py:2446` | PORTED (2026-09-08) | No route from the app to the guide at all |
| Check for updates, launch probe | `app.py:2456` | PORTED `updatecheck.py` | |
| KiCad plugin setup and launch offer | `app.py:2796,2805` | PORTED `kicadsetup.py` | |
| Feed test card, auto-scored | `app.py:679,6276` | DROPPED | A/B §8, no reason given |
| 3D sim of the current step, live cursor | `app.py:705,5746` | PORTED `window.py:523,2131` | |
| 3D sim of only the rework-clipped paths | `app.py:5795` | PORTED (2026-09-08) | |
| Open and simulate any exported file | `app.py:708,5766` | PORTED (2026-09-08) | The only way to check what was actually written |

## Ranked as of the audit: what a student at the mill would have missed most

*All twenty, and the partial items after them, were ported the same day; the order is kept because it is the order they were tested in.*

1. **The guided tour.** The only thing that taught the machine itself, not just the steps.
2. **Run-progress tracking with ETA.** "How much longer" is the question asked most at the mill.
3. **Resume probing after a STOP.** Using STOP correctly should not cost the whole grid.
4. **Pause / Resume.** Without it people reach for VPanel.
5. **Probe boxes.** The only way to find a too-shallow cut.
6. **F1 / link to the web guide.**
7. **Per-box follow-height-map in rework.**
8. **Measure tool.**
9. **Photo opacity, trace dim, hand-picked anchors.**
10. **Cut dowels only, with a settable bite depth.**
11. **Dowel sub-mode, edge pair, clearances.**
12. **Fiducial flip direction.**
13. **Manual fiducial placement.**
14. **Exact screw-vs-toolpath check.**
15. **Detect rework boxes from the photo.**
16. **Simulate an arbitrary file.**
17. **Drift check while probing.**
18. **Narrow-gap overlay.**
19. **Arrow-key jog, tool trail, align overlay to bit.**
20. **Preview image and summary, tool-wear ledger, auto-crop, centre on the copper.**

Partial items, worst first: levelled top traces on a dowel job (measured and silently unused), V-bit geometry not editable, mesh outlier check gone, setup files dropping rework and photo state, X-ray disabled for single-sided boards, Probe Z and Zero Z collapsed into one, status chips, screw review as a toast.
