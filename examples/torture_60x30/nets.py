"""Which rows of the torture board can a given bit cut? python nets.py [bit_mm ...]

Geometry only, no mill: a gap is open if the bit fits through it, and copper is
left standing if the bit does not eat it. A real bit also wobbles (runout), which
widens every cut, so nets.py also takes a runout and treats the cut as that much wider.
"""
import sys

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

import make_board as mb

RUNOUT = 0.05       # mm added to the bit's width: a decent collet


def net_shape(points, width, pads):
    parts = [LineString(points).buffer(width / 2)]
    for pad in pads:
        parts.append(Point(pad).buffer(mb.PAD_D / 2))
        end = min(points, key=lambda p: Point(p).distance(Point(pad)))
        parts.append(LineString([end, pad]).buffer(width / 2))
    return unary_union(parts)


def rect(x, y, w, h):
    return box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def report(bit):
    cut = bit + RUNOUT
    print("\n%.2f mm bit, cutting %.2f mm wide" % (bit, cut))
    gaps = [g for g, _a, _b in mb.gap_rows() if g >= cut]
    print("  gaps open:   %s" % (", ".join("%.2f" % g for g in gaps) or "none"))
    print("  gaps closed: %s" % (", ".join(
        "%.2f" % g for g, _a, _b in mb.gap_rows() if g < cut) or "none"))
    for name, pads in mb.parts().items():
        shapes = [rect(*p) for p in pads]
        gap = min(a.distance(b) for i, a in enumerate(shapes) for b in shapes[i + 1:])
        print("  %-11s narrowest gap %.2f: %s" % (
            name, gap, "can be cut" if gap >= cut else "NOT with this bit"))


if __name__ == "__main__":
    for bit in [float(v) for v in sys.argv[1:]] or [0.8, 0.5, 0.3, 0.2, 0.1]:
        report(bit)
