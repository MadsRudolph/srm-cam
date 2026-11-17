# SRM-CAM on macOS, with the machine link

Everything the Windows build does, on a Mac: the Arduino SPI probe (DRO, jog,
Probe Z / Zero Z, bed levelling, Automatic mode) and sending RML straight to
the SRM-20. Same code as Windows and Linux; the macOS patch lives on the
`macos-machine-link` branch:

| File | What changes |
|---|---|
| `gerber2rml/platform.py` | `machine_link` is True on `darwin`; no `usermod` hint; Fusion style on macOS; `handoff_address()` |
| `gerber2rml/engine/rmlspool.py` | `CupsPrinter` - the spooler API over CUPS; `SpoolPrinter` is it on macOS; queue setup, state and resume |
| `gerber2rml/engine/runner.py` | one note when a job sits in the queue and the mill never moves (all platforms) |
| `gerber2rml/doctor.py` | `--setup-mill` makes the CUPS queue from a terminal |
| `gerber2rml/gui2/macmill.py` | Machine ▸ Set up the mill on this Mac…, and the queue checks before a run |
| `gerber2rml/gui2/handoff.py` | a running SRM-CAM takes boards from KiCad and from a second launch |
| `gerber2rml/engine/bracket.py` | where a board sits in the bracket's corner, and the snap; keeping every move clear of the tongue and bars |
| `gerber2rml/engine/autorun.py` | the run's bracket check by paths; a board left in the sheet |
| `gerber2rml/engine/mountfid.py` | the board's own mounting holes as reference holes |
| `gerber2rml/gui2/app.py`, `window.py`, `autorun.py`, `stage.py` | wiring for the above; corner placement, snap and Reset position; arrows drawn as SVG |
| `gerber2rml/gui2/theme.py`, `style.py` | macOS fonts at the end of the fallback stacks; arrow images |
| `gerber2rml/gui2/kicadsetup.py`, `engine/kicadplugin.py` | the plugin learns where SRM-CAM is (`launch.json`) |
| `gerber2rml/gui2/updatecheck.py` | Check for updates rebuilds a Mac copy from its checkout |
| `gerber2rml/loader.py`, `engine/drc.py`, `engine/pinch.py`, `engine/traces.py` | true pad shapes, net names, gaps the cutter's own width |
| `kicad-plugin/` | **Send to SRM-CAM** and **Set design rules for SRM-CAM** (plugin 1.5.0) |
| `packaging/` | `build-macos.sh` (app, DMG, signing, notarising), `update-macos.sh`, entitlements |

Linux stays without the link, as upstream decided.

## Install (from source)

PySide6 needs a Python it has wheels for; 3.12 is the safe choice.

```bash
brew install python@3.12 libusb
git clone https://github.com/MadsRudolph/srm-cam.git && cd srm-cam
git checkout macos-machine-link          # or wherever the patch lives
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[gui,dev]"
python -m gerber2rml.doctor
packaging/build-macos.sh                  # dist/SRM-CAM.app
```

## From KiCad to the mill

1. SRM-CAM offers, once, to add its buttons to KiCad (or **KiCad ▸ Set up
   the build-area plugin…**). Restart KiCad.
2. In the PCB editor: **Tools ▸ External Plugins ▸ Send to SRM-CAM** (also a
   toolbar button). It plots the board **as it is on screen** - unsaved edits
   included, from a copy, so the board file and its plot settings are not
   touched - into a `srm-cam` folder beside the board, with every layer
   SRM-CAM reads (B.Cu, F.Cu, Edge.Cuts, masks, silkscreen, PTH/NPTH drill).
3. SRM-CAM comes to the front with the board loaded. If it was not running it
   is started; if it was, the board goes to that window, which holds the
   serial port. While a run is going the board is **not** loaded, and the
   button says so.
4. Measure the board thickness, check the tool, Next → Check → Run.

Thickness and the checks are deliberately not skipped: the thickness sets the
drill and cut-out depth, and is "measured with calipers, not assumed".

The plot is made inside KiCad (`srm20area/plot.py`): no `kicad-cli`
process, so no extra KiCad icons in the Dock. Only a KiCad whose scripting
API does not match falls back to `kicad-cli` on a copy of the board. Checked
against KiCad 10.0.3, where both give the same files.

## What the cutter can separate

The mill isolates two nets by driving its cutter between them, so the design
rules have to keep everything at least the cutter's width apart: 0.8 mm for
the lab's flat endmill.

- **In KiCad** the clearance lives in three places - Board Setup ▸ Design
  Rules ▸ Constraints, every Net Class, and every zone's own Clearance.
  *Tools ▸ External Plugins ▸ Set SRM-20 design rules* raises all three to
  the cutter's width and refills the zones; *Send to SRM-CAM* checks them
  first and offers the same. Run DRC afterwards and move what it marks.
- **Holes are the same argument with the drill.** It cannot make a hole
  smaller than itself, so the same action raises the via holes - the
  board's minimum drill, the net classes', and the vias already placed - to
  the drill (0.8 mm), sets new vias to 1.8 mm across, and makes a placed via
  bigger only if less than 0.3 mm of copper would be left round the hole.
  Footprint pads are left as they are. Nothing is ever lowered or shrunk.
- **A gap exactly the cutter's width is fine.** SRM-CAM cuts it with one
  pass down its middle (`engine/drc.py`, `exact_fit_pairs`). Upstream
  reported such gaps as shorts when the arithmetic came out as 0.7999999,
  and did not cut them at all when it came out as 0.8.
- **Oval and rounded pads are their real shape** (`loader.py`). Upstream
  loads them as bounding boxes, whose corners invent copper up to 0.41 mm
  closer to the neighbours than the pad is.
- **One net is not a short.** With the Gerber's net names (KiCad's X2
  attributes), two pieces of one net, or a loose island of pour beside a
  net, are not reported - only copper that would join two different nets.
- **An inside corner is not a gap.** Where a track joins another at an
  angle the round cutter cannot reach into the point, and that copper stays
  as part of the track. It used to be drawn red and counted with the gaps
  too narrow to isolate; now only a gap between two separate pieces of
  copper is (`analysis.split_narrow_gaps`).
- The X of each finding is drawn on *Check it* in Novice (there is no Traces
  step there), on the board where it is drawn, double-sided layouts included.

## The board in the bracket

In Novice the stock is always in the corner bracket, so the L, the sheet in
it and the board on the sheet are the picture from the moment a board is
opened - from KiCad, the dialog or the demo - on every step. (In Pro, as
upstream: on **Run it** only.) A new board goes into the bracket's corner by
itself: 3 mm in from the two edges the bracket holds,
and further from the edge with the probe tongue, so the bit clears the tongue
as the run requires. Dragged near the corner it snaps back into it (3 mm, per
axis); dragged elsewhere it stays. **Reset position** puts it back. If the
sheet typed is too small for the board to sit there whole, the app says how
big the sheet needs to be and how big the outline may be in KiCad. On the
lab's 160 × 100 mm sheet that is 157 × 94.5 mm.

A double-sided board's reference (fiducial) holes count: in the waste they
are drilled 4 mm outside the corners and must land on the copper too. The
**Reference holes** list on Run it (and on Your board in Pro) has two other
ways, for a sheet barely bigger than the board:

- **Inside the board's corners** - the same holes, 4 mm inside; they stay in
  the finished board.
- **The board's own mounting holes** - nothing extra is drilled
  (`engine/mountfid.py`). The app picks holes the board already has: at
  least two of one size, 1.6 to 4 mm across with a 0.8 mm bit (the bit plus
  0.8 mm, so it drops in; not so wide that the height touches 2.5 mm from
  the centre land in the hole), and at least half the board's longer side
  apart. One per corner where there is one. If the board has none that will
  do, it says so and nothing changes.

A single-sided board has no reference holes. The choice, like single or
double sided, is remembered for the board's folder.

### A board as big as the sheet

**Leave the board in the sheet (no cut-out)**, on Run it, is for a board
about the size of the sheet - the lab's are 160 × 100 mm.
Nothing is cut round the outline, so the board needs no room for that: it is
put against the two edges of the sheet AWAY from the bracket, and may reach
right up to the bracket, under its probe tongue included.

The bit must not go where the tongue is, and with this ticked the run sees
to it (`engine/bracket.py`, `engine/autorun.py`):

- every move of every job - cuts, lifts, and the hops between cuts - is
  checked against the tongue and the two bars of the L, before the run
  starts and again on the paths as they are sent;
- isolation that would be under the tongue is **left uncut** and the bit is
  led round the tongue instead of over it. The passes are then milled out of
  the sheet on paper; if what was left out would put two nets on one piece
  of copper, the run does not start and names them. A ground pour's own
  outer edge is the usual thing left out, and joins nothing;
- a **hole** under the tongue, or anything that would run off the stock into
  a bar, stops the run: those cannot be left out;
- the surface is not probed under the tongue.

Cut out as usual, nothing changes: a board that would have work under the
tongue is refused, as upstream does - though now by its paths rather than
its outline, so a board whose outline reaches there but whose work does not
is let through. The picture on the stage still draws the isolation in full;
the stretch left out is said in the run's notes, in millimetres.

**Both faces.** A double-sided board is turned over left to right and lands
mirrored across the sheet, so it is centred across it, and the tongue is
then over the other end. Before anything is cut the run lays the top side
(F.Cu's isolation) where a perfect flip puts it and checks it the same way,
1 mm further off for how far a sheet comes back from where it was; after the
flip is measured it checks the real thing again. A reference hole that lands
under the bracket once flipped is simply not used - three have to be
reachable, or the run does not start. A hole that is under the bracket the
first way up cannot be drilled at all, and has to be moved in KiCad.

Only run in the simulator so far: do a dry run first.

Copper on F.Cu makes a board double-sided when it is opened. Unticking
*This board has copper on both faces* is remembered for that board's folder,
so a board whose F.Cu only shows where wire links go stays single-sided
every time it is sent from KiCad.

## Clamps: no-go zones

The automatic run knows the corner bracket, because the app draws it. It
knows nothing else that stands above the copper. On 2026-11-15 that cost two
bits: the surface probe touches 2 mm in from the board's edge, which on a
board as big as its sheet is where the clamps are, and it goes from touch to
touch in a straight line a few millimetres up.

On **Run it**, *Mark a clamp (no-go zone)* arms the bed:

- **click the bed hole** a clamp is screwed into: the lab's printed cam
  clamp (26 mm disc, screw 5.5 mm off centre, from
  `hardware/probe_bracket/hold_down.py`) is turned **clockwise** onto the
  stock's edge - the first touch going clockwise, so tightening the
  thumbscrew presses it on - with its 2 mm lip over the copper; the bit
  keeps 1 mm from it. Place the real clamp the same way;
- **drag** a box round anything else (screw head, knob); 2 mm from that.

The zones last only until SRM-CAM is closed - the clamps come off with
every board - and are drawn red. **Right-click** a zone to delete it at
once; *Clear zones* removes them all.

The checks say at once when work lies in a zone - *Work lies in a no-go
zone*, with which zone and what is in it - so the board or the clamp can be
moved before Start. That check reads the geometry (the edges of both layers'
copper, since a cut runs along an edge and a pour may lie under a clamp
untouched; every hole and reference hole); the run has the last word, from
its real toolpaths. With zones set, the run (`engine/autorun.py`):

- moves a surface touch that would land in a zone (or within 2 mm of one
  plus the bit's radius) to the nearest free spot, up to 15 mm away and
  still inside the grid; its height is entered at the grid point all the
  same. A touch with no free spot near is not made and takes the height of
  the nearest one that was; with fewer than half left the run stops rather
  than guess;
- leads the head **round** a zone wherever a move between two touches, or
  to a reference hole, would cross it: corner to corner at the height it is
  at, staying on the stock and off the bracket (`engine/nogo.py`). Only when
  the zones leave no way round on the stock does it go over, at the top of
  Z, and the log says so;
- for a board **left in the sheet**, treats a clamp as it treats the
  bracket's tongue: isolation under it is left uncut and the bit led round,
  once the passes, milled out on paper, are seen to join no nets. A poured
  board has an isolation pass all the way round, 0.1 mm inside its edge -
  exactly where clamps hold a board as big as its sheet - and that pass
  joins nothing. If leaving it out would put two nets on one piece of
  copper, the run refuses and names them. The checks show this as a
  warning, *Isolation in a no-go zone will be left uncut*;
- leads a job's **travel** round the zones too: the hop from one hole to
  the next, from one trace to the next, is the run's own choice of line and
  is re-routed (`nogo.detour`) at the height it travels at. The first run
  with zones refused to drill because the straight line between two corner
  holes clipped a clamp's corner; that is not a reason to refuse;
- refuses, before anything is cut, any job that still has a move through a
  zone: a **cut** in one - a hole, or a trace on a board that is cut out -
  or travel with no way round;
- refuses to start if the spot where the copper's height is touched (15 mm
  in from the bracket's corner) or a reference hole is in a zone;
- needs the stock in the bracket: found by its edges, the probe feels along
  exactly where clamps sit.

*Levelling: touches this far in from the edge* (under *Probe the surface
first*, and as *Points this far in from the edge* on the Level page - one
setting for both) sets how far the outer surface touches are kept from the
board's edge: 2 mm by default, more to keep them off clamps on the edge. The
height map carries its outer rows out to the edge.

While Run it is open the bed shows where the run will touch: the twelve
points, moved by the margin, by the board being dragged, and off any zone
drawn over one - worked out by the same function the run uses
(`engine/autorun.py`, `level_grid` and `level_targets`), so what is drawn is
what is done.

Not covered: the Pro workflow's own bed-levelling grid, and jogging by hand.

## The first touch on the copper

Probe Z, Zero Z and the run's first touch drop fast and then feel. The fast
part runs at the machine's rapid (about 19 mm/s), which the firmware's
stop-on-touch cannot bring to rest inside the copper - a first Probe Z on
this Mac drove a bit into the stock, aimed at a "usual" copper height for a
"usual" bit. Now (`stockfind.drop_to_hint`):

- a height measured in this session is dropped to 5 mm above, as before;
- otherwise (no height, or one from another day) the fast drop stops **12 mm**
  above the lab's copper (`LAB_COPPER_UM`): the copper never changes height,
  and a bit sits at most ±10 mm from usual in the collet. Then it feels down,
  6 mm a touch.

The Arduino firmware is unchanged.

## A board bigger than the sheet

With *Leave the board in the sheet (no cut-out)* the board has no edge, and
the isolation along it is not cut either. A ground pour stops half a
millimetre short of the outline, and isolating the pour means a pass all the
way round the board, 0.1 mm inside an edge that is never cut free - minutes
of cutting, under every clamp on the sheet's edge, to separate the pour from
more copper. That pass is left out where the toolpaths are made
(`bracket.leave_edge`, `window._edge_free`), so the bed, the time estimate,
the exported file and the run all show the same passes. It is left out only
when milling both versions out of the sheet on paper shows the same nets on
the same pieces of copper; if a track at the very edge would end up joined
to the pour, the whole pass is kept and the checks say which nets.

The outline is not cut, so it may also hang off the copper: only the work
has to be on it. The copper check
and the run both measure what is cut - both layers' copper, the holes, the
reference holes - instead of the outline, the surface touches stay on the
sheet, and the board stays where it was dragged. A trace or a hole off the
copper is refused as before.

## How far, and how long still

While an automatic run is going, **Run it** shows a bar and one line under
it: the step in hand, the percentage, the time left, the time of day it
should be done, and how long it has taken so far. The same line is on the
machine bar, so it is seen from every page.

The time left starts from the planned feeds and corrects itself: once a step
has finished, how long it really took against its estimate is applied to
everything still to come (`gui2/runclock.py`). The clock stops while the run
waits for a person - at the flip, and at the check before the cut-out - and
a step that runs past its estimate says "at least" rather than counting down
to a time that has already gone.

## The mill: a raw CUPS queue (once per Mac)

On Windows the Roland driver installs the mill as a printer and jobs are
written to it RAW. On a Mac there is no Roland driver; a raw CUPS queue on the
mill's USB device does the same job. It must be named so it contains
`SRM-20` - that is how the app finds it.

Mill switched on, USB plugged in, then **Machine ▸ Set up the mill on this
Mac…** (macOS asks for an administrator password in its own dialog). Pressing
Start in Automatic mode with no queue offers the same. From a terminal:

```bash
python -m gerber2rml.doctor --setup-mill
```

Either way it finds the mill with `lpinfo --include-schemes usb -v` (a
`usb://Roland%20DG/SRM-20?serial=...` URI) and runs, as admin:

```bash
lpadmin -p SRM-20 -E -v "usb://Roland%20DG/SRM-20?serial=..." -m raw
cupsenable SRM-20
cupsaccept SRM-20
```

CUPS may print that raw queues are deprecated. They still work on macOS. If
`-m raw` is refused, the setup retries without a model, which is the same raw
queue. Check with `lpstat -p SRM-20`.

Before every Automatic run the app checks the queue:

- **paused** (CUPS stops a queue by itself after a failed job - mill off or
  unplugged): offers to resume it;
- **old jobs waiting** from an earlier run - they would cut first: offers to
  clear them;

and does not start until each is settled. During a run, a job that sits in
the queue for 30 s while the mill never moves is reported once.

Before the first job, as on Windows (README, "Required before first use"):
the settings SRM-CAM relies on - Setup > Command Set **NC Code**, G54 origin,
the spindle speed - live on the mill and were only reachable from VPanel,
which is Windows-only. SRM-CAM now reads them over USB the way VPanel does
(**Machine ▸ The mill's settings…**, and by itself before every automatic
run): a mill in RML-1 is set to NC Code and the run's log says so, the
spindle speed is VPanel's Spindle slider in percent, and a G54 that is not at
machine 0, 0 is reported before anything is probed. G54 itself can be read
but not yet set from here; that still takes VPanel. The bytes, the captures
they came from and the checklist for the first try at the mill are in
[vpanel-settings.md](vpanel-settings.md). **Reading and the spindle speed have
been tried against the mill from a Mac and work; the command set has not
been written from one yet.** If a job is refused all the same, the run
says so (the mill holds in pause with its error bit up).

This needs direct USB access: `pyusb` (installed with the `gui` extra) and
libusb (`brew install libusb`; the packaged app carries its own copy).

How a job travels: `lp -d SRM-20 -o raw` queues it, `lpstat -o SRM-20` is
`pending()`, `cancel -a SRM-20` is `purge()`. STOP does what it does on
Windows, in the same order (`engine/runner.py`): purge what CUPS still holds,
then stop motion, cancel, spindle off and abort over the Arduino. Cancelling
the CUPS job cannot recall bytes already in the mill's own buffer - the
Arduino abort is what stops those, exactly as on Windows.

## The Arduino

Plug it in; it appears as `/dev/cu.usbmodem…` (or `/dev/cu.usbserial…` for a
CH340/FTDI clone) and is ranked first by its USB vendor id. No drivers, no
group to join. Firmware flashing uses the Arduino IDE's bundled `arduino-cli`
from `/Applications/Arduino IDE.app`, or one on `PATH`.

## Building

```bash
packaging/build-macos.sh              # dist/SRM-CAM.app, ad-hoc signed
packaging/build-macos.sh --dmg        # + dist_installer/SRM-CAM-<version>.dmg
packaging/build-macos.sh --release    # Developer ID, hardened runtime, DMG, notarised
```

`--recreate` rebuilds the build venv after a dependency change. There is no
macOS lock file yet, so the build installs `packaging/requirements-build.txt`
(unpinned).

An ad-hoc build opens without a warning on the Mac that built it. On another
Mac the first launch needs right-click → **Open** - unless it is a release.

### Signed releases (once per Mac)

A release opens on any Mac without a Gatekeeper warning. It needs a paid
Apple Developer account and two things in this Mac's keychain:

1. **A Developer ID Application certificate.** Xcode ▸ Settings ▸ Accounts ▸
   your team ▸ Manage Certificates… ▸ + ▸ *Developer ID Application*. (An
   *Apple Development* certificate is not enough: Apple only notarises
   Developer ID signatures.) Check with
   `security find-identity -v -p codesigning`.
2. **Notary credentials**, stored under the profile name `srm-cam`. Make an
   app-specific password at account.apple.com ▸ Sign-In and Security, then:

   ```bash
   xcrun notarytool store-credentials srm-cam --apple-id <your Apple ID> --team-id <team ID>
   ```

   The team ID is on developer.apple.com ▸ Account ▸ Membership details.

Then `packaging/build-macos.sh --release`. It signs every binary inside out
with the hardened runtime and `packaging/macos-entitlements.plist`, builds the
DMG, sends it to Apple (a few minutes), and staples the ticket.
`SRM_CAM_SIGN_ID` picks a certificate when there are several;
`SRM_CAM_SIGN_ID=-` signs ad-hoc with the hardened runtime, to test the
entitlements without a certificate.

## Updating

**Help ▸ Check for updates…** finds a new upstream release and offers
**Update now**: Terminal opens and runs `packaging/update-macos.sh --install`
in the checkout the app was built from. By hand:

```bash
packaging/update-macos.sh             # fetch, rebase, doctor, tests, build
packaging/update-macos.sh --install   # ... and replace /Applications/SRM-CAM.app
```

The tests take about a minute: the script installs `pytest-xdist` and runs
them in parallel (`-n auto --dist worksteal`; serially they take seven). A
plain build is about 20 s, 40 s with hardened signing and a DMG.

It stops, changing nothing, if the checkout has uncommitted changes or the
patch no longer rebases cleanly, and before building if a test fails. A
conflict is most likely in
`platform.py`, `engine/rmlspool.py` or the menus in `gui2/window.py`.

## Known limitations

- VPanel does not exist for macOS. Command Set and the spindle speed are set
  from SRM-CAM instead (vpanel-settings.md); the spindle speed is proven at
  the mill, the command-set write is not yet.
  Setting the G54 origin, and clearing a job the mill refused, still need
  VPanel on a Windows PC.
- OpenGL is deprecated on macOS but works (pyqtgraph gets a 2.1 context); the
  3D simulator and height-map views render.
- The native macOS widget style clips the stylesheet's check boxes, so the app
  uses Qt's Fusion style on macOS.
- The Windows fonts (Bahnschrift, Segoe UI, Cascadia) fall back to DIN
  Alternate/Condensed, Avenir Next Condensed, Helvetica Neue and Menlo. The
  stylesheet carries the whole fallback list (`gui2/style.py`); with only
  the first name, buttons fell through to the system font and the machine
  bar was 1401 px wide. It is 1308 px now, against 1280 on Windows, so the
  window cannot be made narrower than about 1310 px on a Mac.
- The test suite passes on macOS (Python 3.12, pytest 9). Upstream `a3fdd07`
  has five failures there: three layout tests fixed by the font list above
  (one keeps a macOS width budget of 1333 px, one no longer depends on the
  system font's height), and two that passed nested tuples to
  `pytest.approx`, which pytest 9 refuses.

## First test at the mill

Nothing goes to the mill until someone is standing at it.

1. Mill on, USB in, Machine ▸ Set up the mill on this Mac… →
   `lpstat -p SRM-20` shows the queue enabled. Then Machine ▸ The mill's
   settings… and the checklist in vpanel-settings.md.
2. Arduino in → first in the port list → Connect → the DRO shows a position.
3. Jog XY and Z in small steps; Probe Z; Zero Z.
4. A **dry run** (spindle off, in the air) from the Pro workflow: the mill
   moves as expected, `lpstat -o SRM-20` empties, the run reports done.
5. STOP in the middle of a dry run: the mill stops and lifts, and
   `lpstat -o SRM-20` is empty.
6. Switch the mill off, send a dry run: after 30 s the run says the job is
   waiting in the queue. STOP; switch on; the next Start offers to resume the
   queue and clear the old job.
7. A small levelling grid on scrap.
8. Send to SRM-CAM from KiCad with a real board → it opens loaded.
9. *Leave the board in the sheet* with a board that reaches under the
   tongue, as a **dry run** first: the bit goes round the tongue, never over
   it, and the notes say how much isolation was left uncut.
10. A double-sided board with mounting holes, Reference holes = the board's
   own mounting holes, on scrap: after the flip the probe finds each hole
   and the top lines up with the bottom. (Only run in the simulator so far.)
11. Only then a real job on scrap, then Automatic mode.
