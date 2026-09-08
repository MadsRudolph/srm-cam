# Media plan: screenshots, screen captures, photos and video

*Written 2026-09-08, the evening the port audit closed. Every picture on
the guide site predates today's changes, and the CNC section of the
shared lab README (DTU-EKB/DTU-PCB-prototyping) still describes the
original interface: a Guide button, Traces/Drill/Cut-out tabs, a
"Simulate 3D" page, a "Bed Leveling" page. Mads shoots all of it by hand:
screenshots of every step in the app and in KiCad, screen captures of
SRM-CAM and VPanel, and real-life video of operating the machine. This is
the shot list and the settings, so nothing is forgotten on the day.*

## What comes out of it

| Output | Where it goes |
|---|---|
| Screenshots: the app at every step, KiCad export and the plugin | `website/img/` and the lab repo's `images-for-guides/cnc-images/` |
| Screen captures: the app walked through a job, VPanel set up and run | `website/video/` as mp4; GIFs of the key moments for the README |
| Photos: the machine, the setup, finished boards | guide pages, README, the site's front page |
| Video: placing the copper, Z zero, probing, cutting, the flip | guide pages, README, one 60 to 90 s workflow cut on the front page |
| The lab README's CNC section rewritten for the setup sheet | a branch and pull request on DTU-EKB/DTU-PCB-prototyping |

## Part 1: screenshots

### Settings, once

- **Scale.** Every picture at 2 device pixels per logical pixel, so it
  stays sharp on a HiDPI screen and in a 600 px figure. On Windows, set
  display scaling to 200 % for the session, or run the app with
  `QT_SCALE_FACTOR=2`. On Linux, `QT_SCALE_FACTOR=2 SRM-CAM`. Check one
  screenshot: the window title bar text should be about 30 px tall.
- **Window.** 1400 × 900 logical for whole-window shots. Panels (the rail,
  the inspector, the bar) are cropped from that at the panel's edge, no
  slack around them.
- **Theme.** The app's own dark theme, which the guide site wears too.
- **Tier.** Essential unless the picture is about a Full-only control;
  then say so in the caption.
- **The board.** `tests/fixtures/mosfet_test` ("buck"): a real design,
  27 holes, no student's name. Copy it to `Documents\SRM-CAM\buck` first,
  so every path on screen reads `Documents\SRM-CAM\…` and not a checkout.
- **Tool.** Snipping Tool (Win+Shift+S) or ShareX on Windows;
  `grim -g "$(slurp)"` on Hyprland. PNG, never JPEG, for screens.
- **Names.** Keep the existing file names so the pages need no edits;
  new pictures get `gui2_<what>.png`, KiCad pictures `kicad_<what>.png`,
  VPanel pictures `vpanel_<what>.png`.

### The app, step by step

Load `buck`, then go through the list in this order; each row says the
state to reach, what must be in the frame, and where the picture is used.

| File | How to get there | Must show | Used on |
|---|---|---|---|
| `gui2_setup.png` | Open Gerber folder…, rail on "Set up the job" | whole window: rail, board on the bed, setup page | getting-started, README |
| `gui2_rail.png` | same, crop the rail | dry run, numbered steps, the export button, the total | getting-started |
| `gui2_inspector_copper.png` | setup page, scroll to The copper, crop the inspector | sheet size, corner, "Set the corner from the tool", "Centre it on the copper" | holding-the-copper |
| `gui2_inspector_step.png` | rail on "Isolation traces", crop the inspector | cutting parameters, the Tool combo (flat / V-bit) | getting-started |
| `gui2_traces.png` | "Isolation traces", View → Fit the work, crop the stage | the isolation paths, any ✕ shorts | index, README |
| `gui2_checks.png` | rail on "Check before cutting" | the findings list, including narrow gaps and screws | milling-a-board |
| `gui2_drill.png` | rail on "Drill" | drill paths and the single-bit note | milling-a-board |
| `gui2_measure.png` (new) | View → Measure (Ctrl+M), drag corner to corner | the ruler and its readout chip | reference |
| `gui2_bar.png` | laptop plugged into the Arduino, Connect | crop the bar: ports, Linked, DRO, Z jog, Probe Z, Zero Z, Pause, Spindle, Click to jog, STOP | getting-started, machine-control |
| `gui2_tracking.png` (new) | Machine → Track this step's run, while the traces run | the readout on the bar with the percentage and time left | machine-control |
| `gui2_runsheet.png` | Export the job | the run sheet with Open the folder, Copy the plan, Give feedback, Back to the board | milling-a-board, README |
| `gui2_level.png` | Interface → Full; Level the bed; probe or load a CSV | the grid, the drift check, "Check the mesh…", the surface overlay | bed-leveling |
| `gui2_mesh.png` (new) | Check the mesh… on that map | the sheet with flagged points and the depth advice | bed-leveling |
| `gui2_tiers.png` | Interface → What the two tiers differ by… | the tier sheet | getting-started |
| `gui2_basics.png` (new) | Help → The machine, in five minutes | the six lessons | getting-started |
| `gui2_kicad.png` (new) | KiCad → Set up the build-area plugin… | the "installed" sheet with the path | getting-started, README |
| `gui2_update.png` (new) | Help → Check for updates… on a build older than the latest release | "SRM-CAM x.y.z is available" | getting-started |
| `gui2_photo.png` (new) | View → Lay a photo of the board on the bed…, then the sliders in the View menu | photo on the bed, numbered anchors, opacity and fade sliders | photo-and-rework |
| `gui2_rework.png` | rail → Rework, drag two boxes, tick Level on one | the table with the Level column, Probe the boxes, Propose boxes from the photo | photo-and-rework |
| `gui2_xray.png` | Double-sided ticked, frame switch → Design X-ray | both faces, the flip axis | double-sided |
| `gui2_rail_double.png` | same, crop the rail | align, bottom, flip, top, cut-out last | double-sided |
| `gui2_dowels.png` (new) | Full tier, registration Dowels, setup page | Dowels, Pins sit, the clearances, Into the bed, "Re-cut the dowel holes only…" | double-sided |
| `gui2_flipfit.png` | registration Fiducials, rail → Flip fit | the Flipped control and the fit | double-sided |
| `gui2_panel_setup.png`, `gui2_panel_cutout.png` | File → Add another board to the sheet…, then "Cut the board out" | the arrangement, the shared cut-out | panels |

### KiCad 10

Open the buck project, or any small single-sided board. Same 2x rule.

| File | Where | Must show |
|---|---|---|
| `kicad_clearance.png` | Board Setup → Net Classes | Clearance 1.0 mm or more, Track Width 0.8 mm or more, for a 0.8 mm bit |
| `kicad_plot.png` | File → Fabrication Outputs → Gerbers | B.Cu and Edge.Cuts ticked, millimetres, the output folder |
| `kicad_drill.png` | Generate Drill Files… | Excellon, millimetres |
| `kicad_plugin.png` | Tools → External Plugins → Show SRM-20 build area | the two rectangles on User.Drawings around the board, and the dialog saying whether it fits |
| `kicad_plugin_menu.png` | the External Plugins menu open | the entry, so students know where to look |

### VPanel, on the CNC PC

| File | Where | Must show |
|---|---|---|
| `vpanel_coords.png` | the coordinate dropdown open | Machine / User / G54 |
| `vpanel_command_set.png` | Setup → Command Set | NC Code selected |
| `vpanel_z_origin.png` | after the bit-drop | the Z under Set Origin Point about to be pressed |
| `vpanel_machine_z.png` | dropdown on Machine, bit on the copper | the Z value, about −50 mm or higher |
| `vpanel_cut.png` | Cut → Add → the .nc file → Output | the file list with the three programs in order |

## Part 2: screen captures

Record at 1080p or the display's native size, 30 fps, cursor visible,
no system sounds, no narration on set (captions and voice come later so
the same clip serves the site and the README). OBS or Windows Game Bar
(Win+G) on the CNC PC; `wf-recorder` on Linux. Keep each capture to one
idea; a 15 s clip is easier to place than a 3 minute one.

| # | Capture | Length | What happens |
|---|---|---|---|
| S1 | Load | 15 s | Open Gerber folder… → the board appears on the bed, the plan fills in |
| S2 | Walk the plan | 20 s | click dry run, traces, drill, cut-out on the rail; the stage and inspector follow |
| S3 | Checks | 15 s | the checks page, one finding opened, Copy report |
| S4 | Export | 10 s | Export the job → the run sheet, then Open the folder |
| S5 | Place the copper | 20 s | sheet size typed, "Set the corner from the tool", "Centre it on the copper", drag the board |
| S6 | Level | 30 s | Full tier, Level the bed, the grid built, probing with the surface drawing itself, Check the mesh… |
| S7 | Track a run | 20 s | the readout on the bar counting down during a real pass |
| S8 | Pause and STOP | 15 s | Pause, Resume, then STOP and the bit raised with Page Up |
| S9 | Photo overlay | 30 s | Take one with a phone… → the QR → the photo landing → the sliders |
| S10 | Rework | 30 s | two boxes drawn, Level ticked, Export the rework program… |
| S11 | Double-sided | 40 s | Double-sided ticked, Dowels, the X-ray frame, the rail with the flip step |
| S12 | Feedback | 10 s | Give feedback on the run sheet → the form in the browser |
| S13 | VPanel setup | 30 s | command set, coordinate dropdown, Set Origin Point Z |
| S14 | VPanel run | 20 s | Cut → Add → Output, the job starting |

## Part 3: real-life video

Camera still on a tripod or clamp, phone at 4K 30 fps, focus and
exposure locked before each clip (the spindle's reflections pump the
exposure otherwise). Lab lights on, the machine's cover light on, no
flash. Record every clip twice. Hands out of the frame while anything
moves; cover closed whenever the spindle runs; clips off the bit before
any cut. Students copy what they see.

| # | Clip | Length | Framing | Used on |
|---|---|---|---|---|
| V1 | Seating the copper in the clamping brackets on the sacrificial board, closing the cover | 20 s | from above | holding-the-copper |
| V2 | Taping copper down as the alternative hold | 15 s | from above | holding-the-copper |
| V3 | Fitting the endmill: collet, key, the bit seated | 20 s | close, from the side | machine-control |
| V4 | The bit-drop Z zero: lower to nearly touching, loosen, drop, press, tighten without lifting, Set Origin Z on screen | 40 s | close on the tip, then the screen | machine-control, README; the clip students get wrong most |
| V5 | Reading the Machine Z for headroom, raising the work surface when it is too low | 20 s | screen then bed | machine-control, troubleshooting |
| V6 | Probe clips on: red to copper, black to the bit; the Arduino cable to the laptop | 20 s | close, both clips readable | bed-leveling |
| V7 | Probing: the bit tapping the grid, the map on the laptop beside it | 30 s | machine and laptop in one frame | bed-leveling |
| V8 | Clips off, then the dry run tracing the outline with the spindle off | 20 s | through the cover | milling-a-board |
| V9 | Traces being cut, chips flying; a time-lapse of the whole pass | 20 s + lapse | through the cover, close | index, README |
| V10 | The bit change between passes and re-zeroing only Z | 30 s | close | milling-a-board |
| V11 | Drilling, the cut-out, the board coming free on its tabs | 30 s | through the cover | milling-a-board |
| V12 | Snapping the tabs, filing the edge, holding the board to the light | 20 s | hands, then backlit | milling-a-board, index |
| V13 | Pause from the app mid-cut, Resume, then STOP | 20 s | bar and machine in one frame | machine-control |
| V14 | Double-sided: the align pass drilling the dowel holes, pins pressed in | 30 s | from above | double-sided |
| V15 | Double-sided: the flip. Lift the board, turn it about the pin axis, seat it back on the pins, re-zero only Z | 40 s | from above, pins visible throughout | double-sided, README |
| V16 | Double-sided: the top traces running, then both faces held to the light | 30 s | through the cover, then backlit | double-sided |
| V17 | Taking the board photo with the phone at the QR, the overlay landing | 30 s | over the shoulder | photo-and-rework |
| V18 | A missed spot found in the photo, the rework pass cutting only there | 30 s | screen then through the cover | photo-and-rework |

**The workflow cut.** V1, V3, V4, V8, V9, V11, V12 with S1, S2 and S4
between them, 60 to 90 seconds, no talking, five captions: Load, Set up,
Export, At the machine, Done. It goes at the top of the site's index as
an mp4 and at the top of the README's CNC section as a GIF that links to
the mp4.

## Part 4: photos

Stills, same lighting rules; a sheet of white paper behind a board held
up to a window for the backlit ones.

| # | Subject | Framing | Used on |
|---|---|---|---|
| P1 | The SRM-20, cover closed, the CNC PC with VPanel beside it | three-quarter, whole bench | README, index |
| P2 | Copper seated in the brackets on the sacrificial board | from above | holding-the-copper |
| P3 | Copper taped down | from above | holding-the-copper |
| P4 | The bit tip on the copper, collet key in hand | close, side | machine-control |
| P5 | The probe clips on copper and bit | close | bed-leveling, README |
| P6 | The Arduino and its cable | medium | hardware |
| P7 | The board after traces, before drilling | from above | milling-a-board |
| P8 | The cut-out done, board on its tabs | from above | milling-a-board |
| P9 | The finished board to the light | backlit, macro | index, README, feedback page |
| P10 | The finished board beside the setup sheet showing the same design | wide | index |
| P11 | A double-sided board on its pins mid-flip | from above | double-sided |
| P12 | Both faces of a finished double-sided board to the light | two frames | double-sided, README |
| P13 | A missed spot, and the same spot after rework | macro, two frames | photo-and-rework, troubleshooting |
| P14 | A broken endmill beside a good one | macro | troubleshooting, README caution |
| P15 | The endmill case with the sizes labelled | from above | hardware |

## Part 5: the day

**When.** Friday 11 September at DTU Ballerup: Wednesday is for the
screenshots and screen captures that need no machine, so the lab day is
only the machine work. **Who.** Mads operating, one person on camera;
Jesús or Simon know the machine well enough to catch a wrong step in the
frame. **What gets milled.** The buck board, single-sided, and one
double-sided board on dowels for V14 to V16 and P11, P12. Prepare both
Gerber folders on the CNC PC and on a USB stick beforehand. Have the
finished board from last time along for P9 and P10 in case the day's
board is imperfect.

**Pack.** Two phones charged, tripod or clamp, copper stock for two
boards, a spare endmill, the dowel pins, white paper, callipers, tape,
this document printed with the V and P columns to tick.

**Order on the day.** Bench and machine shots first while everything is
clean (P1, P2, P3, P6, P15). Then the single-sided job start to finish
with the camera running for every step (V1 to V13, P4, P5, P7, P8). Then
the double-sided job (V14 to V16, P11, P12). Then the boards to the light
(P9, P10, P13). The broken-bit shot last (P14).

## Part 6: after the shoot

- **Screens.** PNG as captured, cropped to the panel edge; no scaling.
- **Stills.** Crop, straighten, no filters; 2000 px on the long edge,
  JPEG quality 85; named by what they show, never by number.
- **Clips.** Trim to the action, 1080p H.264 30 fps, under 15 MB each;
  README GIFs at 720 px wide, 12 fps, 8 to 10 s, under 8 MB:

```
ffmpeg -i clip.mp4 -t 10 -vf "fps=12,scale=720:-1:flags=lanczos" -loop 0 clip.gif
```

- **Where they live.** Site: `website/img/` and `website/video/`,
  committed, served by Pages. README: `images-for-guides/cnc-images/` in
  the lab repo, stills and GIFs only, mp4s linked to the site.
- **Alt text and captions** for every picture, from the student's side:
  what they are looking at and what to notice.

## Part 7: the README rewrite

The CNC section of DTU-EKB/DTU-PCB-prototyping is rewritten around the
setup sheet, keeping the KiCad and VPanel material that is still right.
Mads has maintain access: a branch and a pull request.

1. What the SRM-20 does, one paragraph, P1.
2. Correcting your design: clearance for the bit (`kicad_clearance`),
   the build-area plugin (`kicad_plugin`), the narrow-gap check.
3. Exporting from KiCad: `kicad_plot`, `kicad_drill`.
4. SRM-CAM: install and the update check, load, the plan, checks, export,
   the run sheet (`gui2_setup`, `gui2_checks`, `gui2_runsheet`, S1 to S4
   as one GIF). No Guide button, no tabs, no 3D Viewer page: F1 and
   "Help → The machine, in five minutes" instead.
5. Preparing the board: P2, P3, V1.
6. Using the SRM-20: the coordinate systems (kept, `vpanel_coords`),
   Z zero (V4, `vpanel_z_origin`), the headroom rule (align the README's
   −55 mm with the app's −50 mm, or explain the margin), the files in
   order (`vpanel_cut`), Pause versus STOP (V13).
7. Bed levelling: P5, V6, V7, `gui2_level`, the drift check, clips off
   before cutting (kept).
8. Double-sided: the dowel controls (`gui2_dowels`), the flip direction,
   V15, P11, P12.
9. Rework: photo overlay and boxes, V17, V18, P13.
10. Feedback: the form link, one line.

The site gets the same material page by page as listed above, and the
workflow cut on the index.
