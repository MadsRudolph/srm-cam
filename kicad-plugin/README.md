# SRM-20 build area — KiCad plugin

Adds three buttons to KiCad's PCB editor (on the toolbar, and under
Tools → External Plugins):

- **Show SRM-20 build area** (below)
- **Set design rules for SRM-CAM** — pick how the board is made and set the
  rules that method needs ([below](#set-design-rules-for-srm-cam))
- **Send to SRM-CAM** — plots the board as it is on screen, inside KiCad (the
  board file and its plot settings are not touched; `kicad-cli` only as a
  fallback), into a `srm-cam` folder beside it, and opens it in SRM-CAM: in
  the window already running, or a new one. Every layer SRM-CAM reads goes:
  copper, outline, mask, silkscreen and paste (for the stencil job), with the
  PTH/NPTH drill files. Needs SRM-CAM to have installed the plugin, which
  leaves `launch.json` here saying where SRM-CAM is.

## Show SRM-20 build area

It draws two rectangles on **User.Drawings**, centred on your board, and tells
you whether the board fits the mill:

| Rectangle | Meaning |
|---|---|
| `SRM-20 build area 203.2 × 152.4` | how far the spindle travels — the hard limit |
| `recommended max board 189.2 × 138.4` | what a board can sensibly be, leaving 7 mm a side to hold the stock down and run the cut-out pass around the outline |

A board that does not fit is normally discovered at the machine, with the layout
already finished. This puts the answer on screen while there is still time to
act on it.

## Set design rules for SRM-CAM

Opens a small window: pick how the board is made, and it fills in the
rules that method has been cut with. Every number can be changed before
**Apply**; the board's present values stand beside them.

| Method | Track | Clearance | Board minimum | Pour gap / thermal / pour width |
|---|---|---|---|---|
| Mill: 0.8 mm flat endmill | 1.0 | 0.85 | 0.8 | 0.85 / 0.85 / 0.5 |
| Mill: 0.8 mm ball mill (0.44 mm channel) | 0.5 | 0.5 | 0.44 | 0.5 / 0.5 / 0.5 |
| Fiber laser copper, holes and outline on the mill | 0.3 | 0.25 | 0.2 | 0.25 / 0.25 / 0.25 |

All in mm; copper to the board edge 0.5 for each. The laser clears about
0.22 mm round every copper edge (six isolation rings on the laser page), so
a pour 0.25 mm off gives a trench no wider than the gap; at 0.5 mm the
trench came out twice as wide. Every method drills on the mill, so the
smallest hole is SRM-CAM's drill (0.8 mm unless it says otherwise) and vias
get 0.5 mm of copper round the hole.

Apply sets the net classes (track width on Default; a wider class such as
Power keeps its tracks), the board's minimum clearance, drill and edge
clearance, every pour and the defaults for new pours, raises any via hole
under the drill, and refills the pours. Tracks are not moved: run DRC
afterwards. Use it before the first track; it is safe on a routed board too.

Custom rules (Board Setup → Design Rules → Custom Rules) win over all of
this. The window reads the board's `.kicad_dru` and names any rule that
allows a gap the method cannot make, or that holds the pour further off
than the method wants. It does not edit that file.

The method is remembered per board in `srm-cam/method.json` beside it, and
*Send to SRM-CAM* checks the board against that method before plotting. A
board with no method yet is checked against the method its own rules point
to, and the warning says it was guessed: a gap under the ball mill's
0.44 mm channel (Default net class, board minimum, or a pour) means the
laser, one under 0.8 mm the ball mill, and a board still on KiCad's
defaults the mill bit SRM-CAM has selected. The window opens on the same
guess.

## Install

**From SRM-CAM** — *KiCad → Set up the build-area plugin…*. It copies this
folder into every KiCad version it finds and tells you where it went. SRM-CAM
also offers this once, at launch, if KiCad is present and the plugin is not.

**By hand**, if you would rather. KiCad loads user plugins from its data
tree, which is a different place on each OS:

```bash
# Windows
cp -r kicad-plugin "$APPDATA/kicad/10.0/scripting/plugins/srm20_build_area"
# Linux
cp -r kicad-plugin ~/.local/share/kicad/10.0/scripting/plugins/srm20_build_area
# macOS
cp -r kicad-plugin ~/Documents/KiCad/10.0/scripting/plugins/srm20_build_area
```

Restart KiCad either way — plugins are loaded at startup.

## Using the build area

Run it at any point. With an `Edge.Cuts` outline it reports your board's size
and how much room is left; with no outline yet it centres on the placed parts,
which is exactly when *"how big can this get?"* is worth asking. Running it
again replaces the previous rectangles rather than stacking a second set, and
**Ctrl+Z** undoes it.

The rectangles are deliberately **not** on Edge.Cuts. The outline is the
placement boundary and goes to the fab; these are advisory and must never be
mistaken for it. They are plain graphics in a group named `srm20_build_area`,
which is how a re-run finds and replaces them.

## Layout

| File | What it is |
|---|---|
| `__init__.py` | KiCad's entry point — registers the three actions, and never breaks PCB-editor startup if something goes wrong |
| `action_srm20_area.py` | the build-area button and its dialogs |
| `action_send_to_srmcam.py` | the Send to SRM-CAM and Set design rules for SRM-CAM buttons |
| `srm20area/plot.py` | the plot, inside KiCad (pcbnew's plot controller and Excellon writer) |
| `srm20area/rules.py` | reads the board's design rules and sets them |
| `srm20area/rules_dialog.py` | the Set design rules window |
| `srm20area/methods.py` | **pure** — the rules per fabrication method, the send check, the guess, and `method.json` |
| `srm20area/sendto.py` | **pure** — the `kicad-cli` fallback and handing the folder to SRM-CAM |
| `srm20area/geometry.py` | **pure** — the machine's numbers, no pcbnew, so it imports and tests anywhere |
| `srm20area/draw.py` | draws the build area on the board |
| `VERSION` | what SRM-CAM compares against to know an installed copy is stale |

`BED_X, BED_Y` in `geometry.py` are the same numbers as
`gerber2rml.backends.SRM20_BED`, which SRM-CAM checks exports against.
`tests/test_kicadplugin.py` asserts they still agree — if they ever drift,
KiCad would tell a student their board fits while SRM-CAM refuses to cut it.
