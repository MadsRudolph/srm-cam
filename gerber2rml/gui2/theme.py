"""The palette and the type scale, in one place.

This is the second interface's answer to ``gui/theme.py``, and it makes two
decisions that one did not.

**1. The chrome has no colour.** The first interface applies a cyan accent
evenly to buttons, headings, checkboxes, links, tab underlines and section
titles, which means colour has stopped carrying information: when something
finally goes wrong the red has to compete with cyan already covering the
screen. Here the interface furniture is neutral all the way through, and every
chromatic token below answers a question:

    copper       this is the material
    path/far     metal comes off here / on the other face
    hole         a hole gets drilled here
    short        the cutter physically cannot separate these nets
    probe        the surface gets measured here
    fixture      brass: a pin or a screw holds the work
    danger       this stops work, or cannot be undone
    caution      look at this before you cut
    verified     this has been checked and it passed
    live         the wire to the machine is live

Emphasis without hue is done with weight, size and a near-white fill: the
primary button is the brightest object on its panel, and it is the only one.

**2. The type scale has a range.** The first interface lives between 11 px and
14 px and attempts hierarchy with four font weights inside a 3 px band. The
scale here runs 10 → 34 and pairs two families that mean different things:

    DIN (Bahnschrift)     the instrument voice — headings, numerals, labels.
                          It is the typeface on machine plates and road signs
                          for the same reason we want it: it is legible small,
                          condensed enough to set a numeral column, and it does
                          not look like a web app.
    Grotesque (Segoe UI)  prose. Anything a person reads as a sentence.
    Mono (Cascadia)       machine facts only — coordinates, file names, G-code.
                          If it is in mono, the machine said it.

Rules for adding to this file, inherited from ``gui/theme.py`` because they
were right:

* **Name by ROLE, not by colour.** Two roles that happen to share a value still
  get two names.
* **Nothing outside this module hardcodes a colour.**
  ``tests/test_gui2_theme.py`` enforces it, including the stylesheet.
"""

# ---------------------------------------------------------------------------
# Ground — a real range, deepest to lightest.
# ---------------------------------------------------------------------------
# The first interface's surfaces span #14171c → #262c35: six greys inside a
# band too narrow to read as depth, so panels are told apart by their borders
# rather than by their tone. These are spaced far enough apart to stack.
INK = "#08090b"             # the deepest ground: the stage, behind everything
BASE = "#101318"            # the window itself
PANEL = "#161a20"           # a panel sitting on the window
PANEL_HI = "#1c2129"        # a panel sitting on a panel (cards, rows)
RAISED = "#242b34"          # controls at rest: fields, secondary buttons
RAISED_HI = "#2d3641"       # ...hovered
SUNK = "#0d1015"            # wells, tables, anything recessed

# ---------------------------------------------------------------------------
# Rules. Hairlines, not boxes — the layout is held by alignment and space, and
# a rule is only drawn where two things genuinely need separating.
# ---------------------------------------------------------------------------
RULE = "#1f242b"            # the quiet divider
RULE_HI = "#2b323b"         # a divider that bounds an interactive thing
RULE_STRONG = "#3b4550"     # a divider carrying real weight (region edges)

# ---------------------------------------------------------------------------
# Text — four steps, each with a job.
# ---------------------------------------------------------------------------
TEXT = "#eef2f6"            # what you are reading now
TEXT_2 = "#aab3bd"          # labels, secondary facts
TEXT_3 = "#767f89"          # hints, units, captions
TEXT_4 = "#4d555e"          # disabled, and the "nothing here yet" voice
ON_LIGHT = "#08090b"        # ink ON a near-white or bright fill

# ---------------------------------------------------------------------------
# Emphasis without hue. The primary action is a near-white fill; there is one
# per panel, ever.
# ---------------------------------------------------------------------------
PRIMARY = "#e9eef3"
PRIMARY_HI = "#ffffff"
PRIMARY_LO = "#c3cad1"
FOCUS = "#8fa3b8"           # keyboard focus ring — neutral, so it never reads
                            # as a status colour on a control that has one

# ---------------------------------------------------------------------------
# The material. Copper is the one warm token in the chrome, and it is only ever
# used for copper: the stock on the stage, and the swatch that stands for it.
# ---------------------------------------------------------------------------
COPPER = "#b4763c"
COPPER_HI = "#d59456"
COPPER_DIM = "#6b482a"
COPPER_FILL = "#2a1e13"     # the stock rectangle, filled at reading weight

# ---------------------------------------------------------------------------
# The stage legend. Every one of these appears in the on-canvas key, because a
# colour the user has to guess at is a colour that is not carrying anything.
# ---------------------------------------------------------------------------
PATH = "#e8eff5"            # cutting move, the side facing up right now
PATH_FAR = "#6fa8dc"        # the far face of a double-sided board
TRAVEL = "#4d5762"          # the bit is in the air
OUTLINE = "#98a2ac"         # Edge.Cuts: where the board ends
HOLE = "#b98ad8"            # a drilled hole (violet: used for nothing else)
GHOST = "#5c6874"           # the as-designed overlay, when it is not the cut
PROBE = "#3fd0aa"           # a point the surface will be measured at
FIXTURE = "#e0bb5c"         # brass: dowel pins and hold-down screws
BED = "#12161b"             # the machine bed
BED_EDGE = "#39424c"        # ...and its limit of travel
GRID = "#181d23"            # the 10 mm bed grid
GRID_10 = "#20262d"         # ...every 50 mm
TOOL = "#ff6b4a"            # where the tool is, right now

# ---------------------------------------------------------------------------
# Status. Four, and no more — a fifth would mean the four are not doing their
# jobs. Each has a fill and a border so it can be a chip as well as a mark.
# ---------------------------------------------------------------------------
DANGER = "#ff4d4d"          # stops work, or cannot be undone
DANGER_HI = "#ff7a7a"
DANGER_LO = "#c22c2c"
DANGER_FILL = "#2b1113"
DANGER_EDGE = "#5e1f22"

CAUTION = "#f0a33c"         # look at this before you cut
CAUTION_FILL = "#2a1e0d"
CAUTION_EDGE = "#5c4118"

VERIFIED = "#52c98a"        # checked, and it passed
VERIFIED_FILL = "#0f2419"
VERIFIED_EDGE = "#22503a"

# "the wire is live" is a different question from "this step passed", so it is
# deliberately a different HUE and not just a different green. The first
# interface learned this and answered it with two greens; two greens still have
# to be told apart at a glance, across the room, by someone holding a bit.
LIVE = "#4ea8ff"
LIVE_FILL = "#0c1c2e"
LIVE_EDGE = "#1d466e"

# ---------------------------------------------------------------------------
# The run sheet — the one surface in the app that is a printed document rather
# than an interface, so it gets paper values instead of screen ones.
# ---------------------------------------------------------------------------
SHEET = "#12151a"
SHEET_RULE = "#232930"
SHEET_INK = "#dfe5ec"
SHEET_INK_2 = "#8d97a2"

# ---------------------------------------------------------------------------
# Selection / hover — neutral, low, and never confusable with a status.
# ---------------------------------------------------------------------------
SELECT = "#243040"
SELECT_EDGE = "#3d5069"
HOVER = "#1a1f26"
SCRIM = "#000000"           # dialog backdrops, drawn with alpha in code

# ---------------------------------------------------------------------------
# Type
# ---------------------------------------------------------------------------
# Family stacks, most-wanted first. Bahnschrift is Microsoft's DIN 1451 and
# ships with Windows 10/11; Cascadia ships with Windows Terminal and VS. The
# fallbacks keep the app honest on a machine (or a CI box) without them —
# nothing below depends on a family existing, only on the *scale*.
DISPLAY_FAMILY = ["Bahnschrift SemiBold Condensed", "Bahnschrift SemiBold",
                  "Franklin Gothic Medium", "DIN Alternate", "Oswald",
                  "Segoe UI Semibold", "Sans Serif"]
LABEL_FAMILY = ["Bahnschrift SemiCondensed", "Bahnschrift",
                "Franklin Gothic Medium", "Segoe UI", "Sans Serif"]
BODY_FAMILY = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Sans Serif"]
MONO_FAMILY = ["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Monospace"]

# The scale. Named by ROLE so a size change is one decision, not forty.
# The span (10 → 34) is the point: the first interface's entire UI lives
# between 11 and 14, which is why nothing on it reads as a heading.
SIZE_HERO = 34              # a step numeral on the run sheet
SIZE_TITLE = 22             # the name of the thing on screen
SIZE_HEAD = 15              # a section
SIZE_SUB = 13.5             # a step name in the traveller
SIZE_BODY = 12.5            # prose
SIZE_SMALL = 11.5           # field labels, secondary rows
SIZE_LABEL = 10             # tracked all-caps eyebrow labels
SIZE_MICRO = 9.5            # units, footnotes, the legend

TRACK_LABEL = 1.6           # letter-spacing (px) for the eyebrow labels; caps
                            # at 10 px are unreadable set solid

# ---------------------------------------------------------------------------
# Metrics — the spacing system. One unit, and multiples of it, so that every
# gap in the app is explicable.
# ---------------------------------------------------------------------------
UNIT = 4
GAP_XS = UNIT               # 4  — inside a control
GAP_S = UNIT * 2            # 8  — between related rows
GAP_M = UNIT * 3            # 12 — between fields
GAP_L = UNIT * 5            # 20 — between sections
GAP_XL = UNIT * 8           # 32 — between regions

RAIL_W = 316                # the traveller
INSPECTOR_W = 352           # the inspector
BAR_H = 66                  # the machine bar
HEADER_H = 56               # the title bar
RADIUS = 3                  # one radius, small. Rounding everything by 8 px is
                            # decoration; 3 px reads as a machined edge.
RADIUS_CHIP = 2


def font(role="body", *, weight=None, mono=False, caps=False):
    """A :class:`QFont` for a named role in the scale.

    Roles map to ``SIZE_*``. ``mono=True`` swaps to the machine face — use it
    only for things the machine said (coordinates, file names, G-code), because
    that is the signal it carries here.
    """
    from PySide6.QtGui import QFont
    sizes = {"hero": SIZE_HERO, "title": SIZE_TITLE, "head": SIZE_HEAD,
             "sub": SIZE_SUB, "body": SIZE_BODY, "small": SIZE_SMALL,
             "label": SIZE_LABEL, "micro": SIZE_MICRO}
    size = sizes[role]
    if mono:
        fams = MONO_FAMILY
    elif role in ("hero", "title"):
        fams = DISPLAY_FAMILY
    elif role in ("head", "sub", "label"):
        fams = LABEL_FAMILY
    else:
        fams = BODY_FAMILY
    f = QFont(fams[0])
    f.setFamilies(fams)
    f.setPointSizeF(size * 0.75)          # px-ish scale -> points at 96 dpi
    if weight is not None:
        f.setWeight(weight)
    elif role in ("hero", "title", "head", "label"):
        f.setWeight(QFont.DemiBold)
    if caps or role == "label":
        f.setCapitalization(QFont.AllUppercase)
        f.setLetterSpacing(QFont.AbsoluteSpacing, TRACK_LABEL)
    # Numerals must line up in a column. Every table and readout in this app is
    # numbers, and proportional figures make a column of them look broken.
    f.setStyleStrategy(QFont.PreferQuality)
    return f


def gl_rgba(hex_colour, a=1.0):
    """``#rrggbb`` as the ``(r, g, b, a)`` floats OpenGL wants.

    The 3D view is the one place that cannot take a CSS string, and hand-typed
    tuples there would be colours with no name — exactly what this module
    exists to prevent.
    """
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0,
            int(h[4:6], 16) / 255.0, float(a))


def alpha(hex_colour, a):
    """``#rrggbb`` at alpha ``a`` (0..1) as a :class:`QColor`.

    Keeps translucency out of the palette: a colour used at two opacities is
    still ONE role, and giving it two tokens would say otherwise.
    """
    from PySide6.QtGui import QColor
    c = QColor(hex_colour)
    c.setAlphaF(a)
    return c
