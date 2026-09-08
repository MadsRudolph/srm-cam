# Media plan: screenshots, photos and video for the setup sheet

*Written 2026-09-08, the evening the port audit closed. Every screenshot
on the guide site predates today's changes, and the CNC section of the
shared lab README (DTU-EKB/DTU-PCB-prototyping) still describes the
original interface: a Guide button, Traces/Drill/Cut-out tabs, a
"Simulate 3D" page, a "Bed Leveling" page. Both need new pictures and, for
the README, new words. This is the plan for getting them in one lab day
and one desk day.*

## What comes out of it

| Output | Where it goes | What it needs |
|---|---|---|
| A fresh set of app screenshots, rendered the same way every time | `website/img/`, and `images-for-guides/cnc-images/` in the lab repo | the screenshot script, the fixture board, no camera |
| Photos of the machine, the setup and finished boards | guide pages, README, the site's front page | one lab visit |
| Short clips of each hands-on step, and one 60 to 90 s cut of the whole workflow | guide pages (mp4 in `website/video/`), README (GIFs), the front page | the same lab visit |
| The lab README's CNC section rewritten for the setup sheet | a branch and pull request on DTU-EKB/DTU-PCB-prototyping | the pictures above |

## Part 1: screenshots, by script

The current set was grabbed as whole widgets at a device scale of 2 by an
ad-hoc script that was never committed. Today's port changed the bar
(Pause, Probe Z, Zero Z, the run readout), the header (four chips), the
menus (KiCad, F1, the machine lessons, Measure, Simulate a file) and
several pages, so every one of the twenty images is stale. Rather than
grab them by hand again, the next step is a committed script,
`scripts/shoot_screens.py`, that opens the app offscreen, loads
`tests/fixtures/mosfet_test`, drives it into each state, and writes every
PNG at 2x. Then a screenshot is a `git pull` and one command, and the
pictures can never drift from the app again.

**Rules for every shot.** Window 1400 × 900 logical, device scale 2,
the app's own dark theme, the fixture board "buck" (a real design with
27 holes, and no student's name on it), the workspace path shown as
`Documents\SRM-CAM\…` rather than a checkout path, Essential tier unless
the picture is about a Full-only control, English UI, nothing selected
that would not be selected at that moment in a real job.

**The list.** Name, state to drive, what the picture must show, where it
is used. Names keep the existing ones so the pages need no edits.

| File | State | Must show | Used on |
|---|---|---|---|
| `gui2_setup.png` | board loaded, "Set up the job" selected | rail, stage with the board on the bed, inspector's setup page | getting-started, README |
| `gui2_rail.png` | same, rail only | the plan with the dry run, the numbered steps, the export button | getting-started |
| `gui2_inspector_step.png` | "Isolation traces" selected, inspector only | cutting parameters, the tool combo with flat / V-bit | getting-started |
| `gui2_inspector_copper.png` | setup page, copper section | sheet size, corner, "Centre it on the copper" | holding-the-copper |
| `gui2_bar.png` | linked to a fake port is not possible offscreen: grab the bar unlinked, and once with a stub link if the script can stand one up | ports, Connect, Z jog, Probe Z, Zero Z, Pause, Spindle, Click to jog, STOP | getting-started, machine-control |
| `gui2_tiers.png` | Interface → What the two tiers differ by… | the tier sheet | getting-started |
| `gui2_traces.png` | "Isolation traces" selected, stage only, Fit the work | the isolation paths on the copper, the ✕ shorts if any | index, README |
| `gui2_checks.png` | "Check before cutting" selected | the findings list including the narrow-gap and screw entries | milling-a-board |
| `gui2_drill.png` | "Drill" selected | drill paths and the single-bit interpolation note | milling-a-board |
| `gui2_runsheet.png` | after export | the run sheet with Open the folder, Copy the plan, **Give feedback**, Back to the board | milling-a-board, README |
| `gui2_level.png` | Level the bed, a loaded height map CSV, Full tier | the grid, the drift check, "Check the mesh…", the surface overlay | bed-leveling |
| `gui2_xray.png` | double-sided, Design X-ray frame | both faces, the flip axis | double-sided |
| `gui2_rail_double.png` | double-sided rail | align, bottom, flip, top, cut-out last | double-sided |
| `gui2_flipfit.png` | fiducial registration, flip-fit page | the flip direction control and the fit | double-sided |
| `gui2_panel_setup.png`, `gui2_panel_cutout.png` | two boards on one sheet | the arrangement, the shared cut-out | panels |
| `gui2_rework.png` | rework page with two boxes, one with Level ticked | the table with the Level column, Probe the boxes, Propose boxes from the photo | photo-and-rework |
| **new** `gui2_measure.png` | Measure mode, a ruler corner to corner | the readout chip | reference |
| **new** `gui2_photo.png` | a photo on the bed with the sliders open | opacity and fade sliders, numbered anchors | photo-and-rework |
| **new** `gui2_basics.png` | Help → The machine, in five minutes | the six lessons | getting-started |
| **new** `gui2_update.png` | the update sheet from a stubbed release | "SRM-CAM 0.5.1 is available" | getting-started |
| **new** `gui2_kicad.png` | KiCad → Set up the build-area plugin… | the installed sheet | getting-started, README |
| **new** `gui2_tracking.png` | a run followed, the readout on the bar | percentage, time left | machine-control |

Screens that need a machine or a photo (the bar while linked, the run
readout, the photo overlay) are stubbed in the script the way the tests
stub them; nothing here needs the mill.

**KiCad screenshots** for the README: the Plot dialog, Generate Drill
Files, the Net Classes clearance, and the build-area plugin's rectangles
on a board. These are taken by hand on KiCad 10 at 2x, with the fixture
board's project if it exists, otherwise a small demo project. Name them
`kicad_*.png`.

## Part 2: the lab day

**When.** Mads is at DTU Ballerup on Wednesday 9 and Friday 11 September.
Take Friday: it leaves Wednesday to finish the screenshot script and test
the shot list on the demo board, so the lab day is spent shooting, not
debugging.

**Who.** Two people: one operates the machine and the app, one holds the
camera. Ask Jesús or Simon; either knows the machine well enough to
notice a wrong step on camera. A third person is not needed.

**What gets milled.** One single-sided board, chosen so the footage shows
every step in under an hour: 30 to 40 holes, a simple outline with
rounded corners, traces wide enough to be visible on video. The "buck"
fixture board is the natural choice, since it is what every screenshot
shows and the finished board can then be photographed beside the
screenshots. Prepare its Gerbers on the CNC PC before the day.

**Equipment.**

- A phone is enough, at 4K 30 fps, if it is held still: a small tripod or
  a clamp on the bench. Lock focus and exposure before each clip, or the
  spindle's reflections will pump the exposure.
- A second phone for stills and for the phone-photo hand-off shot.
- The lab's lights on, the machine's cover light on. No flash on copper:
  it flares. For finished boards, a sheet of white paper behind the
  board and daylight from a window, held up to the light as the existing
  `doublesided_*.jpg` shots were.
- A clean bench: the machine, the CNC PC, the Arduino and its two clips,
  the endmills in their case, the sacrificial board, the copper stock,
  callipers, tape, the finished board from last time.
- The app updated on the CNC PC before the day, and on the operator's
  laptop.

**Pack list.** Phones charged, tripod, the copper stock, the fixture
board's Gerbers on a USB stick as a fallback, a printed copy of this
shot list.

**Safety on camera.** Cover closed whenever the spindle runs, clips off
the bit before any cut, hands out of the frame while it moves. The video
will be watched by students who copy what they see.

## Part 3: shot list, photos

Numbered so they can be ticked off. Framing notes are for the camera
person. Every photo also gets a plain-language alt text when it is placed.

| # | Subject | Framing | Used for |
|---|---|---|---|
| P1 | The SRM-20 with its cover closed, the CNC PC beside it, VPanel on screen | three-quarter view from the operator's position, whole bench | README top of the CNC section, site index |
| P2 | The bed with the sacrificial board and a piece of copper seated in the clamping brackets | from above, straight down | holding-the-copper |
| P3 | Copper held with tape on the sacrificial board (the alternative hold) | from above | holding-the-copper |
| P4 | The endmill in the collet, tip just touching copper, collet key in hand | close, from the side, focus on the tip | machine-control (the bit-drop Z zero) |
| P5 | The probe clips: red on the copper, black on the bit | close, both clips readable | bed-leveling, README |
| P6 | The Arduino and its USB cable to the laptop | medium | hardware |
| P7 | VPanel's coordinate dropdown showing Machine / User / G54 | screen photo, or a screenshot from the CNC PC if it can be taken | README, machine-control |
| P8 | VPanel Setup with Command Set on NC Code | same | README |
| P9 | The dry run in progress: bit held up over the outline, spindle off | through the cover, lit | milling-a-board |
| P10 | Isolation traces being cut, chips visible | through the cover, close | index, README |
| P11 | The board after traces, before drilling | from above | milling-a-board |
| P12 | Drilling | through the cover | milling-a-board |
| P13 | The cut-out finished, board still held by its tabs | from above | milling-a-board |
| P14 | Snapping the tabs, filing the edge | hands and board | milling-a-board |
| P15 | The finished board held up to the light | backlit, macro | index, README, feedback page |
| P16 | The finished board next to the setup sheet on screen showing the same design | wide | index |
| P17 | A phone taking the board photo for the overlay, the QR on the laptop screen | over the shoulder | photo-and-rework |
| P18 | A board with a missed spot, and the same spot after a rework pass | macro, two frames | photo-and-rework, troubleshooting |
| P19 | A double-sided board on its dowel pins, mid-flip | from above, pins visible | double-sided |
| P20 | A broken endmill next to a good one | macro | troubleshooting, README caution |

## Part 4: shot list, video

Each clip is one step, 10 to 40 seconds, camera still, no narration on
set. Captions and a voice-over, if any, are added afterwards so the same
clip serves the site and the README. Record every clip twice.

| # | Clip | Length | Notes |
|---|---|---|---|
| V1 | Opening the setup sheet, loading the Gerber folder, the board appearing on the bed | 20 s | screen recording, not camera |
| V2 | Walking the plan: dry run, traces, drill, cut-out selected in turn | 20 s | screen recording |
| V3 | Export, the run sheet appearing | 10 s | screen recording |
| V4 | Seating the copper in the brackets, closing the cover | 20 s | camera, from above |
| V5 | Fitting the bit and the bit-drop Z zero, ending on VPanel's Set Origin | 40 s | camera, close; the one clip students get wrong most |
| V6 | Clips on, probing the grid, the surface drawing itself in the app | 30 s | camera on the machine, then a screen recording of the map |
| V7 | Clips off, the dry run | 20 s | camera through the cover |
| V8 | Traces being cut | 20 s | camera through the cover, then a time-lapse of the whole pass |
| V9 | The bit change and re-zeroing only Z | 30 s | camera |
| V10 | Drilling, then the cut-out, then the board coming free | 30 s | camera |
| V11 | Snapping the tabs, filing, holding the board to the light | 20 s | camera |
| V12 | Pause and Resume from the app during a cut, then STOP | 20 s | camera on the bar and the machine in one frame |
| V13 | The phone-photo hand-off and the overlay landing on the bed | 30 s | camera then screen |
| V14 | Two boxes drawn for a rework, the rework pass running | 30 s | screen then camera |

**The workflow cut.** From V1 to V11, 60 to 90 seconds, no talking, five
captions: Load, Set up, Export, At the machine, Done. It goes at the top
of the site's index page as an mp4 and at the top of the README's CNC
section as a GIF, with a link to the mp4.

## Part 5: after the shoot

- **Stills.** Crop to the subject, straighten, no filters; export at
  2000 px on the long edge as JPEG quality 85. Name them by what they show
  (`bed_copper_seated.jpg`, `probe_clips.jpg`), never by number.
- **Clips.** Trim to the action, 1080p, H.264, 30 fps, under 15 MB each
  for the site. For the README, a GIF of the first 8 to 10 seconds at
  720 px wide and 12 fps, under 8 MB, made with:

```
ffmpeg -i clip.mp4 -t 10 -vf "fps=12,scale=720:-1:flags=lanczos" -loop 0 clip.gif
```

- **Where they live.** Site: `website/img/` for stills, `website/video/`
  for mp4, both committed; Pages serves them. README: `images-for-guides/
  cnc-images/` in the lab repo, GIFs and stills only, with the mp4 linked
  to the site.
- **Alt text and captions** for every picture, written from the student's
  side: what they are looking at and what to notice.

## Part 6: the README rewrite

The CNC section of DTU-EKB/DTU-PCB-prototyping is rewritten around the
setup sheet's flow, keeping the KiCad and VPanel material that is still
right. Mads has maintain access, so this is a branch and a pull request.

Outline of the new section:

1. What the SRM-20 does, one paragraph, P1.
2. Correcting your design: clearance for the bit, the KiCad build-area
   plugin with a screenshot of its rectangles, the narrow-gap check.
3. Exporting from KiCad: unchanged, existing screenshots.
4. SRM-CAM: install (Windows installer, AppImage, the update check),
   load, the plan and the steps, checks, export, the run sheet
   (`gui2_setup`, `gui2_checks`, `gui2_runsheet`). No Guide button, no
   tabs, no 3D Viewer page: "Help → The machine, in five minutes" and F1
   instead.
5. Preparing the board: brackets or tape, P2, P3.
6. Using the SRM-20: the coordinate systems (kept), Z zero with V5 and
   P4, the −50 mm rule (align the README's −55 with the app's −50 or
   explain the margin), the three files in order, Pause versus STOP.
7. Bed levelling: clips (P5), the level page (`gui2_level`), the drift
   check, clips off before cutting.
8. Double-sided: the new dowel controls and flip direction, P19.
9. Rework: photo overlay and boxes, P17, P18, V14.
10. Feedback: the form link, one line.

The site gets the same pictures page by page as listed in Parts 1, 3 and
4, plus the workflow cut on the index.

## Order of work

1. Wednesday: the screenshot script, run it, check every image against
   the list, commit the new set. Tick off the KiCad screenshots.
2. Thursday: the README rewrite drafted with the screenshots in place and
   placeholders for the photos, on a branch in the lab repo.
3. Friday: the lab day, this shot list printed.
4. The following desk day: post-production, the site pages, the README
   pull request, a release tag so the update check has something to
   announce.
