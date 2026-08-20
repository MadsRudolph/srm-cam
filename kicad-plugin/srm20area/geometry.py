"""The machine, as numbers. Pure — no pcbnew, so it imports anywhere.

Kept deliberately small: this is the one place that says how big an SRM-20's
build area is, and `tests/test_kicadplugin.py` asserts it still agrees with
`gerber2rml.backends.SRM20_BED`, which is what SRM-CAM checks exports against.
Two tools, one definition of the machine.
"""

# X/Y operation strokes from the SRM-20 manual: how far the spindle centre
# travels. This is the hard limit — no part of a board can sit outside it.
BED_X, BED_Y = 203.2, 152.4

# What a board can sensibly be, as opposed to what the machine can reach. The
# stock has to be held down (tape or screws around the edges) and the cut-out
# pass drives the tool all the way around the outline, so the last few mm of
# travel in every direction are not board area.
HOLD_DOWN_MARGIN = 7.0

# The layer the rectangles land on. Advisory geometry, deliberately NOT
# Edge.Cuts: the outline is the placement boundary and goes to the fab, and
# these must never be mistaken for it.
LAYER = "User.Drawings"

# Everything the plugin draws goes in one named group, so re-running finds the
# previous set and replaces it instead of stacking a second copy.
GROUP = "srm20_build_area"


def usable():
    """The recommended maximum board size, in mm."""
    return (BED_X - 2 * HOLD_DOWN_MARGIN, BED_Y - 2 * HOLD_DOWN_MARGIN)


def rectangles():
    """What to draw, outermost first: (width, height, line width, label)."""
    uw, uh = usable()
    return [
        (BED_X, BED_Y, 0.2, "SRM-20 build area  %g x %g" % (BED_X, BED_Y)),
        (uw, uh, 0.1, "recommended max board  %g x %g" % (uw, uh)),
    ]


def room_to_grow(width, height):
    """How much bigger a board could get before it stops fitting.

    Returns (dw, dh); negative means it is already over. Measured against the
    recommended size rather than the raw stroke, because a board that only
    fits with no hold-down margin does not really fit.
    """
    uw, uh = usable()
    return (uw - width, uh - height)


def verdict(width, height):
    """A sentence about whether a board of this size fits the machine."""
    dw, dh = room_to_grow(width, height)
    if dw < 0 or dh < 0:
        over = []
        if dw < 0:
            over.append("%.0f mm too wide" % -dw)
        if dh < 0:
            over.append("%.0f mm too tall" % -dh)
        uw, uh = usable()
        return ("Too big: %s. This board will not mill on an SRM-20 "
                "(recommended max %g x %g mm)." % (" and ".join(over), uw, uh))
    return ("Fits. Room to grow: %.0f mm wider, %.0f mm taller before it "
            "reaches the recommended maximum." % (dw, dh))
