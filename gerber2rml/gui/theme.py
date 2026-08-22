"""The palette, in one place.

Before this file the GUI carried 97 distinct colour literals across 236 uses:
five different pure reds on one canvas, thirteen greys none of which was a
token, and a matplotlib background (``#1e1e1e``) that was visibly warmer than
the Qt chrome sitting next to it — while ``photodlg`` used the chrome colour
for the same job, so the app's two plot surfaces did not match each other.

Rules for adding to this file:

* **Name by ROLE, not by colour.** ``DANGER`` survives a redesign; ``RED_3``
  does not. Two roles that happen to share a value still get two names — that
  is how you find out later that they were never meant to be the same.
* **Nothing outside this module hardcodes a colour.** ``tests/test_theme.py``
  enforces it.

The stylesheet is rendered with :class:`string.Template`, so it refers to these
names as ``$ACCENT`` rather than ``{ACCENT}`` — CSS is full of braces and
``str.format`` would mean escaping every one of them.
"""

# --- app chrome: the slate the whole UI sits on ----------------------------
BG = "#14171c"              # window background
BG_DEEP = "#0d1418"         # the darkest ground; also ink on an accent fill
SURFACE = "#1b2027"         # panels, tab panes
SURFACE_ALT = "#181c22"     # secondary panels
SURFACE_SUNK = "#191d23"    # disabled fields
FIELD = "#232a33"           # text inputs, combos, unchecked boxes
FIELD_ALT = "#23262c"       # status chips, off state
RAISED = "#262c35"          # hairline borders, tab pane edge
RAISED_ALT = "#2a2f36"      # the machine bed fill on the canvas
SLATE_DEEP = "#1f242c"
SLATE_MID = "#2b3440"

BORDER = "#313a46"          # the standard 1px border
BORDER_HARD = "#3d4754"     # checkbox and input outlines
BORDER_DIM = "#34383f"      # chip outline, off state
BED_EDGE = "#4a5158"        # machine-bed outline on the canvas

# --- text ------------------------------------------------------------------
TEXT = "#dde3ea"            # primary
TEXT_2 = "#a5adb9"          # labels
TEXT_3 = "#8b94a1"          # secondary / hints
TEXT_4 = "#98a2b3"
TEXT_MUTED = "#7c828c"      # chip text, off state
TEXT_OFF = "#525b66"        # disabled
ON_BRIGHT = "#1e1e1e"       # ink ON a bright chip: gold pins, red badges
AXIS_LABEL = "#8a9099"      # matplotlib axis titles
TICK = "#d4d4d4"            # matplotlib tick labels

# --- accent: cyan ----------------------------------------------------------
ACCENT = "#4dd0e1"
ACCENT_HI = "#80e5f2"       # hover
ACCENT_DIM = "#26c6da"      # badges
ACCENT_DEEP = "#26b8cc"     # pressed
ACCENT_TEXT = "#8fb8c9"     # section headings, help text
ACCENT_BG = "#14232a"       # help-text panel fill
ACCENT_BG_2 = "#12262b"
ACCENT_LINE = "#1e3a42"     # help-text panel border
ACCENT_MUTE = "#52707a"

# --- status ----------------------------------------------------------------
DANGER = "#d64541"          # STOP, danger borders
DANGER_HI = "#e8615d"
DANGER_LO = "#a83531"
DANGER_BG = "#4a2326"       # danger button fill
DANGER_BG_HI = "#5e2b2f"
DANGER_BG_LO = "#3a1c1f"
DANGER_OFF = "#3a2224"      # STOP while disconnected
DANGER_TEXT = "#ff9b97"
DANGER_TEXT_HI = "#ffbdba"
DANGER_MUTE = "#8b6a6c"

WARN = "#ffb000"            # warnings, the AS-MILLED frame badge
OK = "#6be49a"              # chip lit
OK_BG = "#1d3a2a"
OK_BORDER = "#2c5a40"

# --- the machine link ------------------------------------------------------
# Deliberately NOT the same green as OK: this one means "the wire is live",
# which is a different question from "this step is done".
LINK_LIVE = "#39ff14"
TOUCH_ON = "#ff3b3b"        # the probe is touching copper
TOUCH_OFF = LINK_LIVE       # ...and is not

# --- the canvas ------------------------------------------------------------
# Matches BG. It used to be #1e1e1e, a fifth grey and visibly warmer than the
# chrome around it, while photodlg already used the chrome colour for the same
# surface — so the app's two plot surfaces disagreed with each other.
CANVAS_BG = BG
GRID_MAJOR = "#45454a"
GRID_MINOR = "#2b2b2e"
TICK_MINOR = "#666666"

# --- toolpaths: the legend, such as it is ----------------------------------
CUT = "#00ffff"             # material-removing moves
CUT_TOP = "#ff55ff"         # the far side of a double-sided board
RAPID = "#555555"           # travel moves
OUTLINE = "#9aa0a6"         # the board edge
COPPER = "#b87333"          # the stock, drawn as copper
PIN = "#ffd700"             # dowel pins
SCREW = "#ffd24a"           # spoilboard fixing screws
GHOST = "#ffffff"           # the as-designed overlay
PROBE_POINT = "#ff9a3c"     # where the bed will be measured
HOLE = "#ff5555"            # drilled holes
REGION_FILL = "#4da3ff"     # rework boxes
REGION_MARK = "#1e3a5f"
BADGE_INFO = "#88bbff"

# --- things that will not fit, or will not work ----------------------------
# FIT_BAD_BED and FIT_BAD_STOCK share a value today. They are two names because
# they are two different failures — the design overhangs the MACHINE, versus
# the design overhangs your PIECE OF COPPER — and a reader who wants to tell
# them apart on the canvas now has one place to do it.
FIT_OK = "#33cc88"
FIT_BAD_BED = "#ff4444"
FIT_BAD_STOCK = "#ff4444"
STOCK_EDGE = "#d9943f"
SHORT = "#ff2222"           # nets the cutter cannot separate
OVERFLOW = "#ff0000"        # the area that falls outside what can be cut

# --- qualitative series ----------------------------------------------------
# Rework boxes are categorical, not ordinal: the colours only have to be
# telling apart from each other, so this is a hue-spread series rather than
# six independent decisions.
REWORK_SERIES = ["#ff5252", "#42a5f5", "#66bb6a", "#ffa726",
                 "#ab47bc", "#26c6da", "#ec407a", "#d4e157"]

# --- the live machine strip ------------------------------------------------
DRO_TEXT = "#888"           # position readout, idle
DRO_DIM = "#aab"
STATUS_FAULT = "#e08585"    # the strip when the machine reports a problem
STATUS_SPIN = "#e0c185"     # ...and when the spindle is running
