# SRM-20 build area — KiCad plugin

Adds one button to KiCad's PCB editor:
**Tools → External Plugins → Show SRM-20 build area**.

It draws two rectangles on **User.Drawings**, centred on your board, and tells
you whether the board fits the mill:

| Rectangle | Meaning |
|---|---|
| `SRM-20 build area 203.2 × 152.4` | how far the spindle travels — the hard limit |
| `recommended max board 189.2 × 138.4` | what a board can sensibly be, leaving 7 mm a side to hold the stock down and run the cut-out pass around the outline |

A board that does not fit is normally discovered at the machine, with the layout
already finished. This puts the answer on screen while there is still time to
act on it.

## Install

**From SRM-CAM** — *KiCad → Set up the build-area plugin…*. It copies this
folder into every KiCad version it finds and tells you where it went. SRM-CAM
also offers this once, at launch, if KiCad is present and the plugin is not.

**By hand**, if you would rather:

```bash
cp -r kicad-plugin "$APPDATA/kicad/10.0/scripting/plugins/srm20_build_area"
```

Restart KiCad either way — plugins are loaded at startup.

## Using it

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
| `__init__.py` | KiCad's entry point — registers the action, and never breaks PCB-editor startup if something goes wrong |
| `action_srm20_area.py` | the button and its dialogs |
| `srm20area/geometry.py` | **pure** — the machine's numbers, no pcbnew, so it imports and tests anywhere |
| `srm20area/draw.py` | the only module that touches pcbnew |
| `VERSION` | what SRM-CAM compares against to know an installed copy is stale |

`BED_X, BED_Y` in `geometry.py` are the same numbers as
`gerber2rml.backends.SRM20_BED`, which SRM-CAM checks exports against.
`tests/test_kicadplugin.py` asserts they still agree — if they ever drift,
KiCad would tell a student their board fits while SRM-CAM refuses to cut it.
