"""Feed-ladder test card: dial in the fastest clean XY feed on scrap.

One small card mills the SAME isolation-style pattern in a row of blocks,
each block at a stepped XY feed, with the feed value engraved next to it.
Cut it on scrap FR-4, pick the fastest block whose channel edges are still
clean and whose channel width still measures ~bit diameter — that feed
becomes the production setting.

Per block (all at trace depth):
  * a serpentine — long runs + direction reversals (the bulk of real jobs)
  * two pad rings — small-radius curves where chatter shows first
  * a tight pair — two channels 1.25 x bit apart, leaving a thin land that
    tears or smears when the feed is too high
  * the feed value, engraved in 7-segment strokes at the block's own feed
    (label quality is itself a data point)

The card runs in whatever G54 frame is active: zero Z on the scrap surface
and make sure the scrap covers the card's bbox (returned by the builder).
"""
import math
from gerber2rml.toolpath import Move

# 7-segment strokes on a 2x4 box: (x0,y0)-(x1,y1) per segment
_SEG = {
    "a": ((0, 4), (2, 4)), "b": ((2, 2), (2, 4)), "c": ((2, 0), (2, 2)),
    "d": ((0, 0), (2, 0)), "e": ((0, 0), (0, 2)), "f": ((0, 2), (0, 4)),
    "g": ((0, 2), (2, 2)),
}
_DIGIT = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
    "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg",
}


def _line(p0, p1, z, travel_z):
    return [Move(p0[0], p0[1], travel_z, rapid=True), Move(p0[0], p0[1], z),
            Move(p1[0], p1[1], z),
            Move(p1[0], p1[1], travel_z, rapid=True)]


def _poly(pts, z, travel_z):
    tp = [Move(pts[0][0], pts[0][1], travel_z, rapid=True),
          Move(pts[0][0], pts[0][1], z)]
    tp += [Move(x, y, z) for (x, y) in pts[1:]]
    tp.append(Move(pts[-1][0], pts[-1][1], travel_z, rapid=True))
    return tp


def _circle(cx, cy, r, z, travel_z, n=36):
    pts = [(cx + r * math.cos(2 * math.pi * k / n),
            cy + r * math.sin(2 * math.pi * k / n)) for k in range(n + 1)]
    return _poly(pts, z, travel_z)


def _digits(text, ox, oy, scale, z, travel_z):
    paths, x = [], ox
    for ch in text:
        for seg in _DIGIT.get(ch, ""):
            (x0, y0), (x1, y1) = _SEG[seg]
            paths.append(_line((x + x0 * scale, oy + y0 * scale),
                               (x + x1 * scale, oy + y1 * scale), z, travel_z))
        x += 3 * scale
    return paths


def _block(ox, oy, bit, z, travel_z):
    """One test block at origin (ox, oy); footprint ~12.5 x 12.5 mm."""
    paths = []
    pitch = 2.0 * bit                       # serpentine channels don't overlap
    pts, y = [], 0.0
    for i in range(4):
        row = [(ox, oy + y), (ox + 12.0, oy + y)]
        pts += row if i % 2 == 0 else row[::-1]
        y += pitch
    paths.append(_poly(pts, z, travel_z))
    cy = oy + 4 * pitch + 2.2
    paths.append(_circle(ox + 3.0, cy, 1.5, z, travel_z))
    paths.append(_circle(ox + 8.5, cy, 1.0, z, travel_z))
    gap = 1.25 * bit                        # thin land between the two channels
    ty = cy + 2.6
    paths.append(_line((ox, ty), (ox + 10.0, ty), z, travel_z))
    paths.append(_line((ox, ty + gap), (ox + 10.0, ty + gap), z, travel_z))
    return paths


def feed_ladder_card(feeds=(4.0, 6.0, 8.0, 10.0, 12.0, 15.0), origin=(20.0, 20.0),
                     bit_diameter=0.8, cut_depth=0.15, travel_z=1.0, cols=3):
    """Build the card. Returns (toolpaths, xy_feeds, bbox): one feed per
    toolpath (ready for the gcode backend's ``xy_feeds``), and the (x0, y0,
    x1, y1) the scrap must cover."""
    z = -cut_depth
    ox0, oy0 = origin
    cell_w, cell_h = 17.0, 18.5
    paths, per_path = [], []
    for i, f in enumerate(feeds):
        cx = ox0 + (i % cols) * cell_w
        cy = oy0 + (i // cols) * cell_h
        blk = _block(cx, cy, bit_diameter, z, travel_z)
        label = str(int(f)) if float(f).is_integer() else str(f)
        blk += _digits(label, cx, cy + 13.2, 0.9, z, travel_z)
        paths += blk
        per_path += [float(f)] * len(blk)
    xs = [m.x for tp in paths for m in tp]
    ys = [m.y for tp in paths for m in tp]
    margin = bit_diameter / 2.0 + 1.0
    bbox = (min(xs) - margin, min(ys) - margin,
            max(xs) + margin, max(ys) + margin)
    return paths, per_path, bbox


def render_feed_ladder(machine="Roland SRM-20 (G-code)", plunge_feed=1.0,
                       travel_z=1.0, **card_kwargs):
    """Render the card to machine text. G-code only (needs per-path feeds)."""
    from gerber2rml.backends import BACKENDS
    paths, per_path, bbox = feed_ladder_card(travel_z=travel_z, **card_kwargs)
    backend = BACKENDS[machine]
    if "gcode" not in backend.render.__module__:
        raise ValueError("feed ladder needs the G-code backend (per-path feeds)")
    text = backend.render(paths, xy_feed=per_path[0], plunge_feed=plunge_feed,
                          travel_z=travel_z, xy_feeds=per_path)
    return text, bbox
