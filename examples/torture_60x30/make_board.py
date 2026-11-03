"""A single-sided torture test, 60 x 30 mm: python make_board.py

What is the finest copper this mill can really make? Three columns, read with the
legend (legend.png):

  gaps    two 0.5 mm traces, closer together each row. A meter across their two
          pads says whether the gap is really open.
  widths  one trace with a pad at each end, thinner each row. A meter across the
          pads says whether it survived in one piece.
  parts   real footprints: SOIC 1.27, TSSOP 0.65, 0.5 mm pitch, SOT-23, 0603, 0402.

An isolation cut cannot be narrower than the bit, so which rows can be cut at all
depends on the bit: nets.py reports that for any bit, before any copper is spent.
"""
from pathlib import Path

W, H = 60.0, 30.0
NAME = "torture"
GAPS = (0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.25, 0.2)
WIDTHS = (1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.2, 0.15)
GAP_TRACE = 0.5
ROW_YS = [3.0 + 3.2 * i for i in range(8)]   # row 1 is at the front
PAD_D = 1.6
HOLES = [(1.5, 1.5), (58.5, 1.5), (58.5, 28.5), (1.5, 28.5)]
HOLE_D = 1.0


def gap_rows():
    """[(gap, net a, net b)]: a net is (points, width, pad centres)."""
    out = []
    for gap, y in zip(GAPS, ROW_YS):
        half = (gap + GAP_TRACE) / 2
        # Each trace stops short of the other's pad, so only the gap is tested.
        a = ([(5.0, y + half), (18.5, y + half)], GAP_TRACE, [(4.0, y + half + 0.4)])
        b = ([(6.5, y - half), (20.0, y - half)], GAP_TRACE, [(21.0, y - half - 0.4)])
        out.append((gap, a, b))
    return out


def width_rows():
    # Run into the pad centres: a thin trace's end would stop short of the pad.
    return [(w, ([(24.0, y), (37.0, y)], w, [(24.0, y), (37.0, y)]))
            for w, y in zip(WIDTHS, ROW_YS)]


def row(cx, cy, n, pitch, dy, w, h):
    """Two facing rows of n rectangular pads, as (x, y, w, h)."""
    x0 = cx - pitch * (n - 1) / 2
    return [(x0 + pitch * i, cy + s * dy, w, h) for s in (-1, 1) for i in range(n)]


def parts():
    return {
        "SOIC 1.27": row(46.0, 24.5, 4, 1.27, 2.7, 0.6, 1.5),
        "TSSOP 0.65": row(54.5, 24.5, 4, 0.65, 2.85, 0.3, 1.2),
        "0.5 pitch": row(49.0, 14.5, 10, 0.5, 2.0, 0.25, 1.2),
        "SOT-23": [(44.05, 5.0, 0.8, 0.9), (45.95, 5.0, 0.8, 0.9), (45.0, 7.0, 0.8, 0.9)],
        "0603": [(50.2, 6.0, 0.9, 0.9), (51.8, 6.0, 0.9, 0.9)],
        "0402": [(55.5, 6.0, 0.55, 0.6), (56.5, 6.0, 0.55, 0.6)],
    }


def um(v):
    return int(round(v * 1000000))


def write_gerbers(folder):
    apertures, body, codes = [], [], {}

    def code(key, text):
        if key not in codes:
            codes[key] = 10 + len(codes)
            apertures.append("%%ADD%d%s*%%" % (codes[key], text))
        return codes[key]

    def net(points, width, pads):
        body.append("D%d*" % code(("c", width), "C,%.3f" % width))
        (x, y), rest = points[0], points[1:]
        body.append("X%dY%dD02*" % (um(x), um(y)))
        body.extend("X%dY%dD01*" % (um(x), um(y)) for x, y in rest)
        body.append("D%d*" % code(("c", PAD_D), "C,%.3f" % PAD_D))
        body.extend("X%dY%dD03*" % (um(x), um(y)) for x, y in pads)
        # The pad joins its trace: draw the short link at the trace's width.
        return points, pads

    for _g, a, b in gap_rows():
        for points, width, pads in (a, b):
            net(points, width, pads)
            ends = points[0] if pads[0][0] < points[0][0] + 1 else points[-1]
            body.append("D%d*" % code(("c", width), "C,%.3f" % width))
            body.append("X%dY%dD02*" % (um(ends[0]), um(ends[1])))
            body.append("X%dY%dD01*" % (um(pads[0][0]), um(pads[0][1])))
    for _w, (points, width, pads) in width_rows():
        net(points, width, pads)
    for pads in parts().values():
        for x, y, w, h in pads:
            body.append("D%d*" % code(("r", w, h), "R,%.3fX%.3f" % (w, h)))
            body.append("X%dY%dD03*" % (um(x), um(y)))

    head = ["%TF.FilePolarity,Positive*%", "%FSLAX46Y46*%",
            "G04 Gerber Fmt 4.6, Leading zero omitted, Abs format (unit mm)*",
            "%MOMM*%", "%LPD*%", "G01*"]
    (folder / (NAME + "-B_Cu.gbr")).write_text("\n".join(
        ["%TF.FileFunction,Copper,L2,Bot*%"] + head + apertures + body + ["M02*"])
        + "\n", encoding="ascii")
    (folder / (NAME + "-Edge_Cuts.gbr")).write_text("\n".join(
        ["%TF.FileFunction,Profile,NP*%"] + head + ["%ADD10C,0.100*%", "D10*"]
        + ["X0Y0D02*", "X%dY0D01*" % um(W), "X%dY%dD01*" % (um(W), um(H)),
           "X0Y%dD01*" % um(H), "X0Y0D01*", "M02*"]) + "\n", encoding="ascii")
    (folder / (NAME + ".drl")).write_text("\n".join(
        ["M48", "METRIC", "T1C%.3f" % HOLE_D, "%", "T1"]
        + ["X%.1fY%.1f" % p for p in HOLES] + ["M30"]) + "\n", encoding="ascii")


if __name__ == "__main__":
    write_gerbers(Path(__file__).parent)
