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


def feed_ladder_layout(feeds=(4.0, 6.0, 8.0, 10.0, 12.0, 15.0),
                       origin=(20.0, 20.0), bit_diameter=0.8, cols=3):
    """Scoring geometry for a cut card (photo evaluation): per block the feed,
    the serpentine channel centerline, the midline of the thin land between
    the tight channel pair, and the big pad-ring center (a click anchor).

    Also returns the 4 photo anchors — the big-ring centers of the corner-most
    blocks, ordered bottom-left, bottom-right, top-right, top-left (the order
    the anchor dialog asks for). Must be called with the same parameters the
    card was generated with.
    """
    ox0, oy0 = origin
    cell_w, cell_h = 17.0, 18.5
    pitch = 2.0 * bit_diameter
    gap = 1.25 * bit_diameter
    blocks = []
    for i, f in enumerate(feeds):
        cx = ox0 + (i % cols) * cell_w
        cy = oy0 + (i // cols) * cell_h
        serp, y = [], 0.0
        for k in range(4):
            row = [(cx, cy + y), (cx + 12.0, cy + y)]
            serp += row if k % 2 == 0 else row[::-1]
            y += pitch
        ring_y = cy + 4 * pitch + 2.2
        ty = ring_y + 2.6
        blocks.append({
            "feed": float(f),
            "serpentine": serp,
            "land": [(cx + 0.5, ty + gap / 2.0), (cx + 9.5, ty + gap / 2.0)],
            "ring": (cx + 3.0, ring_y),
        })
    xs = sorted({round(b["ring"][0], 3) for b in blocks})
    ys = sorted({round(b["ring"][1], 3) for b in blocks})

    def _corner(want_x, want_y):
        return min(blocks, key=lambda b: (abs(b["ring"][0] - want_x)
                                          + abs(b["ring"][1] - want_y)))["ring"]

    anchors = [("bottom-left big ring", _corner(xs[0], ys[0])),
               ("bottom-right big ring", _corner(xs[-1], ys[0])),
               ("top-right big ring", _corner(xs[-1], ys[-1])),
               ("top-left big ring", _corner(xs[0], ys[-1]))]
    return blocks, anchors


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


# --- Drill ladder: how fast can the bit go into the board? ------------------
DRILL_FEEDS = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0)     # plunge feed, mm/s (rows)
DRILL_PECKS = (0.6, 0.9, 1.8)                    # peck depth, mm (column groups)


def drill_ladder_card(feeds=DRILL_FEEDS, pecks=DRILL_PECKS, origin=(20.0, 20.0),
                      holes_per_cell=4, pitch=2.54, row_pitch=4.0, group_gap=5.0,
                      total_depth=1.8, peck_retract=0.5, travel_z=2.0,
                      bit_diameter=0.8):
    """A grid of plain plunged holes. Row r (front to back, +Y) is plunged at
    ``feeds[r]``; column group g (left to right, +X) pecks ``pecks[g]`` deep.
    A peck of ``total_depth`` or more is a single plunge.

    Cut order is gentlest first: row by row from the front, groups left to
    right. If the bit breaks, the last good hole marks the limit.

    Returns (toolpaths, plunge_feeds, bbox, cells): one plunge feed per
    toolpath, the (x0, y0, x1, y1) the scrap must cover, and per cell
    ``(feed, peck, [(x, y), ...])`` for the legend."""
    from types import SimpleNamespace
    from gerber2rml.engine.drill import drill_holes
    ox, oy = origin
    group_w = (holes_per_cell - 1) * pitch + group_gap
    paths, per_path, cells = [], [], []
    for r, f in enumerate(feeds):
        y = oy + r * row_pitch
        for g, pk in enumerate(pecks):
            x0 = ox + g * group_w
            pts = [(x0 + k * pitch, y) for k in range(holes_per_cell)]
            job = SimpleNamespace(total_depth=total_depth,
                                  cut_depth=min(pk, total_depth),
                                  peck_retract=peck_retract, travel_z=travel_z)
            tps = drill_holes([(x, y, bit_diameter) for x, y in pts], job)
            paths += tps
            per_path += [float(f)] * len(tps)
            cells.append((float(f), float(pk), pts))
    xs = [m.x for tp in paths for m in tp]
    ys = [m.y for tp in paths for m in tp]
    margin = bit_diameter / 2.0 + 2.0
    bbox = (min(xs) - margin, min(ys) - margin,
            max(xs) + margin, max(ys) + margin)
    return paths, per_path, bbox, cells


def render_drill_ladder(machine="Roland SRM-20 (G-code)", xy_feed=4.0,
                        **card_kwargs):
    """Render the drill ladder to NC text. Returns (text, bbox, legend)."""
    from gerber2rml.backends import BACKENDS
    paths, per_path, bbox, cells = drill_ladder_card(**card_kwargs)
    backend = BACKENDS[machine]
    if "gcode" not in backend.render.__module__:
        raise ValueError("drill ladder needs the G-code backend (per-path feeds)")
    travel_z = card_kwargs.get("travel_z", 2.0)
    text = backend.render(paths, xy_feed=xy_feed, plunge_feed=per_path[0],
                          travel_z=travel_z, plunge_feeds=per_path,
                          header=["drill ladder test card",
                                  "rows front to back = plunge feed, "
                                  "groups left to right = peck depth"])
    lines = ["Drill ladder - plunge feed x peck depth",
             f"Scrap must cover X {bbox[0]:.1f}..{bbox[2]:.1f}  "
             f"Y {bbox[1]:.1f}..{bbox[3]:.1f} (machine mm); zero Z on the scrap.",
             "Cut order: front row first, groups left to right (gentlest first).",
             "",
             f"{'row':>3}  {'plunge mm/s':>11}  {'peck mm':>7}  first hole X,Y"]
    pecks = card_kwargs.get("pecks", DRILL_PECKS)
    for i, (f, pk, pts) in enumerate(cells):
        lines.append(f"{i // len(pecks) + 1:>3}  {f:>11g}  {pk:>7g}  "
                     f"{pts[0][0]:.2f}, {pts[0][1]:.2f}")
    return text, bbox, "\n".join(lines) + "\n"


# --- Cut-out ladder: how few passes, how fast? -------------------------------
CUTOUT_FEEDS = (4.0, 6.0, 8.0, 10.0, 12.0)       # XY feed, mm/s (rows)
CUTOUT_PASSES = (3, 2, 1)                        # passes to full depth (columns)


def cutout_ladder_card(feeds=CUTOUT_FEEDS, passes=CUTOUT_PASSES,
                       origin=(104.0, 100.43), slot_len=10.0, col_gap=4.0,
                       row_pitch=5.0, total_depth=2.0, travel_z=2.0,
                       bit_diameter=0.8):
    """Straight full-width slots, cut the way the cut-out cuts: plunge at the
    start, run along at depth, step down, run back. Row r (front to back, +Y)
    runs at ``feeds[r]``; column c (left to right) reaches ``total_depth`` in
    ``passes[c]`` equal passes. Gentlest first: front row, left to right.

    Returns (toolpaths, xy_feeds, bbox, cells) like the drill ladder."""
    ox, oy = origin
    paths, per_path, cells = [], [], []
    for r, f in enumerate(feeds):
        y = oy + r * row_pitch
        for c, n in enumerate(passes):
            x0 = ox + c * (slot_len + col_gap)
            x1 = x0 + slot_len
            tp = [Move(x0, y, travel_z, rapid=True)]
            here = x0
            for k in range(1, n + 1):
                depth = total_depth * k / n
                tp.append(Move(here, y, -depth))             # step down
                here = x1 if here == x0 else x0
                tp.append(Move(here, y, -depth))             # run along
            tp.append(Move(here, y, travel_z, rapid=True))
            paths.append(tp)
            per_path.append(float(f))
            cells.append((float(f), int(n), (x0, y), (x1, y)))
    margin = bit_diameter / 2.0 + 2.0
    xs = [m.x for tp in paths for m in tp]
    ys = [m.y for tp in paths for m in tp]
    bbox = (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)
    return paths, per_path, bbox, cells


def render_cutout_ladder(machine="Roland SRM-20 (G-code)", plunge_feed=5.0,
                         **card_kwargs):
    """Render the cut-out ladder to NC text. Returns (text, bbox, legend)."""
    from gerber2rml.backends import BACKENDS
    paths, per_path, bbox, cells = cutout_ladder_card(**card_kwargs)
    backend = BACKENDS[machine]
    if "gcode" not in backend.render.__module__:
        raise ValueError("cut-out ladder needs the G-code backend (per-path feeds)")
    text = backend.render(paths, xy_feed=per_path[0], plunge_feed=plunge_feed,
                          travel_z=card_kwargs.get("travel_z", 2.0),
                          xy_feeds=per_path,
                          header=["cut-out ladder test card",
                                  "rows front to back = XY feed, "
                                  "columns left to right = passes"])
    depth = card_kwargs.get("total_depth", 2.0)
    lines = ["Cut-out ladder - XY feed x passes to full depth",
             f"Scrap must cover X {bbox[0]:.1f}..{bbox[2]:.1f}  "
             f"Y {bbox[1]:.1f}..{bbox[3]:.1f} (machine mm); zero Z on the scrap.",
             f"Every slot is {depth:g} mm deep. Cut order: front row first, "
             "left to right (gentlest first).",
             "",
             f"{'row':>3}  {'XY mm/s':>7}  {'passes':>6}  {'mm/pass':>7}  slot from X,Y"]
    per_row = len(card_kwargs.get("passes", CUTOUT_PASSES))
    for i, (f, n, a, _b) in enumerate(cells):
        lines.append(f"{i // per_row + 1:>3}  {f:>7g}  {n:>6}  {depth / n:>7.2f}  "
                     f"{a[0]:.2f}, {a[1]:.2f}")
    return text, bbox, "\n".join(lines) + "\n"
