"""Tour content as inert data — no Qt here, so it's trivially testable.

Each :class:`TourStep` *describes* a step; the controller resolves the named
widget on the window at runtime, switches to the right sidebar page, shows the
callout, and (for gated steps) waits for ``advance_signal`` to fire before
moving on. ``target``/``advance_signal`` reference attributes on the
MainWindow by name, so a renamed or absent widget degrades to a skipped step
rather than a crash.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TourStep:
    target: str = ""            # MainWindow attribute name of the spotlighted widget
    title: str = ""             # callout heading
    body: str = ""              # callout text
    page: int = 0               # sidebar row to activate before showing the step
    placement: str = "auto"     # auto|below|above|left|right callout side
    advance_signal: Optional[str] = None   # "attr.signal" to wait on; None = Next/explain
    explain_only: bool = False  # no gating even if it could have one (Next always on)
    reveal: Optional[str] = None  # checkbox attr to tick first, so a hidden target shows

    @property
    def is_gated(self) -> bool:
        return bool(self.advance_signal) and not self.explain_only


# ---- core path: gated end-to-end on the preloaded demo board ---------------
CORE_STEPS = [
    TourStep(
        title="Welcome to SRM-CAM",
        body="Let's mill a board from start to finish. A demo board is already "
             "loaded so you can follow along — do each highlighted action and "
             "the tour moves on. Press Esc or Skip to leave at any time.",
        explain_only=True,
    ),
    TourStep(
        target="load_btn", page=0, explain_only=True,
        title="1 · Load your board",
        body="Normally you'd click here and pick the folder with your Gerber and "
             "Excellon files. The demo board is already loaded, so just click Next.",
    ),
    TourStep(
        target="apply_preset_btn", page=0,
        advance_signal="apply_preset_btn.clicked",
        title="2 · Choose a toolpath preset",
        body="Pick a profile in the dropdown that matches your copper and end mill, "
             "then click Apply (highlighted) to load its feeds, depths and tool "
             "sizes. Click Apply to continue.",
    ),
    TourStep(
        target="tabs", page=0, placement="below",
        advance_signal="tabs.currentChanged",
        title="3 · Preview each operation",
        body="Switch between Traces, Drill and Cut-out to see each milling pass. "
             "Click a different tab to continue.",
    ),
    TourStep(
        target="stock_center_btn", page=0,
        advance_signal="stock_center_btn.clicked",
        title="4 · Place the board on the bed",
        body="Set your copper stock size, then position the design: 'Center design' "
             "centres it on the stock, 'Corner = tool' aligns it to the tool's "
             "current corner. Click 'Center design' to continue.",
    ),
    TourStep(
        target="preview", page=0, placement="left", explain_only=True,
        title="5 · Read the preview",
        body="This is the exact toolpath. Cyan lines are cuts; drag the board to "
             "reposition it on the bed, and use the slider on the viewer bar to "
             "scrub through the path. Looks good? Next.",
    ),
    TourStep(
        target="export_btn", page=0,
        advance_signal="export_btn.clicked",
        title="6 · Export the G-code",
        body="When the preview looks right, click here to write the .nc / .rml "
             "files for the SRM-20. Click Export — that's the whole core workflow!",
    ),
]


# ---- opt-in branches: explain-only, shown on request after the core path ---
BRANCHES = {
    "Double-sided": (1, [
        TourStep(
            target="double_sided_chk", page=1, explain_only=True,
            title="Double-sided milling",
            body="Turn this on to mill both copper layers. You mill the bottom, "
                 "flip the board, then mill the top — and these settings keep the "
                 "two sides aligned.",
        ),
        TourStep(
            target="regmethod_combo", page=1, explain_only=True,
            reveal="double_sided_chk",
            title="Registration method",
            body="Choose how the sides line up: dowel pins (mechanical holes into "
                 "the bed) or fiducial holes (measured with the tool and fitted in "
                 "software).",
        ),
        TourStep(
            target="reg_combo", page=1, explain_only=True,
            reveal="double_sided_chk",
            title="Registration scheme",
            body="Pick the specific dowel/fiducial layout that matches your jig. "
                 "The preview and the flip geometry follow this choice.",
        ),
    ]),
    "Bed leveling": (2, [
        TourStep(
            target="connect_btn", page=2, placement="below",
            advance_signal="connect_btn.clicked",
            title="1 · Connect the Arduino",
            body="Plug in the Arduino that reads the touch probe (close the Arduino "
                 "Serial Monitor first — it holds the port). Click Connect in the top "
                 "bar; the live X/Y/Z readout goes active. Click Connect to continue.",
        ),
        TourStep(
            target="dro_label", page=2, placement="below", explain_only=True,
            title="2 · The coordinate systems",
            body="VPanel's selector lists several; three matter here (per the SRM-20 "
                 "manual). MACHINE — machine-specific, its origin is FIXED and can't "
                 "be moved (Z stroke is 60.5 mm; our −50 mm rule below is in this "
                 "system). USER — origin can be set freely; it's what the bundled "
                 "RML-1 software uses, which we rarely do. G54 — the workpiece system "
                 "used in NC code (G-code), which is what we export — so we set our "
                 "origin in G54.",
        ),
        TourStep(
            target="dro_label", page=2, placement="below", explain_only=True,
            title="3 · Set the G54 Z origin",
            body="Set the Command Set to NC Code (Setup dialog) so G54 is active. In "
                 "the Set-origin-point selector pick G54, jog with the feed buttons "
                 "until the bit just touches the copper, then click [X/Y] and [Z] "
                 "under 'set origin point' to zero it — the manual says align Z0 with "
                 "the material surface. ⚠ Watch the MACHINE Z: never let it drop "
                 "below −50 mm or you hit the travel limit. Then click Next.",
        ),
        TourStep(
            page=2, explain_only=True,
            title="4 · Attach the probe clips",
            body="Clip the RED lead to the copper plate (the PCB blank) and the BLACK "
                 "lead to the drill bit. When the bit touches copper the circuit "
                 "closes — that's how each point's height is sensed. Attach both, "
                 "then click Next.",
        ),
        TourStep(
            target="level_chk", page=2, explain_only=True,
            title="5 · Enable bed leveling",
            body="Turn this on so the engraving depth follows the measured surface and "
                 "stays consistent across an uneven bed or a bowed board.",
        ),
        TourStep(
            target="level_grid_btn", page=2, explain_only=True,
            title="6 · Build a probe grid",
            body="Set how many points across and down, then Build grid to lay the "
                 "probe points out over the board.",
        ),
        TourStep(
            target="level_probe_btn", page=2,
            advance_signal="level_probe_btn.clicked",
            title="7 · Probe the surface",
            body="With the Arduino connected and the clips on, click Probe over SPI — "
                 "the bit taps each grid point and records its true height. Click "
                 "Probe over SPI to continue (or load a saved height map instead).",
        ),
        TourStep(
            target="level_table", page=2, placement="above", explain_only=True,
            title="8 · Read the height map",
            body="Measured heights land here, and the engrave depth then follows the "
                 "surface point-by-point so traces aren't cut too shallow or too deep.",
        ),
    ]),
    "Rework": (3, [
        TourStep(
            target="select_chk", page=3, explain_only=True,
            title="Rework a finished board",
            body="Missed copper leaving a short? Enable selection, then drag boxes "
                 "in the preview over each spot that needs re-cutting.",
        ),
        TourStep(
            target="rework_depth_spin", page=3, explain_only=True,
            title="Per-region depth",
            body="Set the cut depth for new boxes. Each region in the table can have "
                 "its own depth, so you can dig deeper only where needed.",
        ),
        TourStep(
            target="export_sel_btn", page=3, explain_only=True,
            title="Export the rework pass",
            body="Export a single G-code file that re-cuts only those regions — quick "
                 "to run as a second pass without redoing the whole board.",
        ),
    ]),
}
