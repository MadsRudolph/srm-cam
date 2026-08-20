"""Draw the build area into a board. The only module that touches pcbnew.

Everything lands on User.Drawings inside one named group, which makes the two
things that matter easy: the placement engine never reads it, and re-running
finds the previous set and replaces it instead of stacking a second copy.
"""
import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM

from . import geometry as g

# Edge.Cuts is drawn with a stroke of real width, so the outline's bounding box
# is the board plus one line width. Take it back off before reporting a size.
OUTLINE_SLOP = 0.5


def _anchor(board):
    """Where to centre the rectangles, and what that was measured from.

    The outline if there is one. Otherwise the placed parts — a board with no
    Edge.Cuts yet is exactly when "how big can this get?" is worth asking, so
    that case has to work rather than refuse.
    """
    box = board.GetBoardEdgesBoundingBox()
    if box.GetWidth() > 0:
        centre = box.GetCenter()
        return ToMM(centre.x), ToMM(centre.y), box, "the board outline"

    footprints = list(board.Footprints())
    if footprints:
        bb = footprints[0].GetBoundingBox(False)
        for fp in footprints[1:]:
            bb.Merge(fp.GetBoundingBox(False))
        centre = bb.GetCenter()
        return ToMM(centre.x), ToMM(centre.y), None, "the placed parts (no outline yet)"

    return 150.0, 100.0, None, "the sheet (empty board)"


def clear(board):
    """Remove a previous build area. Returns how many items went."""
    removed = 0
    for group in list(board.Groups()):
        if group.GetName() != g.GROUP:
            continue
        items = list(group.GetItems())
        group.RemoveAll()             # detach first, or the group is left
        for item in items:            # holding dangling pointers
            board.Delete(item)
            removed += 1
        board.Delete(group)
    return removed


def _rect(board, group, cx, cy, w, h, width, label):
    rect = pcbnew.PCB_SHAPE(board)
    rect.SetShape(pcbnew.SHAPE_T_RECT)
    rect.SetStart(VECTOR2I(FromMM(cx - w / 2), FromMM(cy - h / 2)))
    rect.SetEnd(VECTOR2I(FromMM(cx + w / 2), FromMM(cy + h / 2)))
    rect.SetLayer(pcbnew.Dwgs_User)
    rect.SetWidth(FromMM(width))
    rect.SetFilled(False)
    board.Add(rect)
    group.AddItem(rect)

    text = pcbnew.PCB_TEXT(board)
    text.SetText(label)
    text.SetPosition(VECTOR2I(FromMM(cx - w / 2 + 1.5), FromMM(cy - h / 2 - 1.8)))
    text.SetLayer(pcbnew.Dwgs_User)
    text.SetTextSize(VECTOR2I(FromMM(2.0), FromMM(2.0)))
    text.SetTextThickness(FromMM(0.3))
    text.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    board.Add(text)
    group.AddItem(text)


def show(board):
    """Draw (or redraw) the build area. Returns stats for the summary."""
    cx, cy, box, anchored = _anchor(board)
    clear(board)

    group = pcbnew.PCB_GROUP(board)
    group.SetName(g.GROUP)
    board.Add(group)
    for w, h, width, label in g.rectangles():
        _rect(board, group, cx, cy, w, h, width, label)

    stats = {"anchored": anchored}
    if box is not None:
        stats["outline"] = (ToMM(box.GetWidth()) - OUTLINE_SLOP,
                            ToMM(box.GetHeight()) - OUTLINE_SLOP)
    return stats


def summary(stats):
    """What to tell the user after drawing."""
    uw, uh = g.usable()
    lines = [
        "Drawn on %s: the SRM-20 build area (%g x %g mm) and the recommended "
        "maximum board (%g x %g mm)." % (g.LAYER, g.BED_X, g.BED_Y, uw, uh),
        "Centred on: %s" % stats["anchored"],
    ]
    if "outline" in stats:
        w, h = stats["outline"]
        lines.append("")
        lines.append("Your board: %.0f x %.0f mm" % (w, h))
        lines.append(g.verdict(w, h))
    else:
        lines.append("")
        lines.append("No board outline yet — draw one on Edge.Cuts and run "
                     "this again to be told whether it fits.")
    return "\n".join(lines)
