"""A 40 x 20 mm double-sided test board for an 80 x 42 mm sheet: python make_board.py

Cut with the one 0.8 mm flat bit, so everything leaves it room: 1 mm traces, 2.4 mm
pads, and gaps over 0.8 mm. An F on top and a B underneath show the flip: each reads
the right way round only if the sheet was turned left to right. Copper on both sides
is joined through the pads, so continuity tests the alignment too.
"""
from pathlib import Path

W, H = 40.0, 20.0
NAME = "ds40x20"
VIAS = [(x, y) for y in (5.0, 15.0) for x in (13.0, 20.0, 27.0, 34.0)]
HOLE_D = 0.8

TOP_TRACES = [[(13, 5), (20, 5)], [(13, 15), (20, 15)],
              [(27, 5), (34, 5)], [(27, 15), (34, 15)]]
BOTTOM_TRACES = [[(13, 5), (13, 15)], [(34, 5), (34, 15)],
                 [(20, 5), (27, 5)], [(20, 15), (27, 15)]]
LETTER_F = [[(3, 4), (3, 16), (9, 16)], [(3, 10), (7, 10)]]
# Drawn from above like all Gerbers, so it reads true from underneath: mirrored.
LETTER_B = [[(9, 4), (9, 16), (4, 16), (3, 15), (3, 11), (4, 10), (9, 10)],
            [(4, 10), (3, 9), (3, 5), (4, 4), (9, 4)]]


def um(v):
    return int(round(v * 1000000))


def header(function):
    return ["%TF.FileFunction," + function + "*%", "%TF.FilePolarity,Positive*%",
            "%FSLAX46Y46*%", "G04 Gerber Fmt 4.6, Leading zero omitted, Abs format (unit mm)*",
            "%MOMM*%", "%LPD*%", "G01*"]


def strokes(paths):
    out = []
    for path in paths:
        (x, y), rest = path[0], path[1:]
        out.append("X%dY%dD02*" % (um(x), um(y)))
        out += ["X%dY%dD01*" % (um(x), um(y)) for x, y in rest]
    return out


def copper(function, paths):
    return "\n".join(header(function) + [
        "%ADD10C,1.000*%", "%ADD11C,2.400*%", "D10*"] + strokes(paths) + ["D11*"]
        + ["X%dY%dD03*" % (um(x), um(y)) for x, y in VIAS] + ["M02*"]) + "\n"


here = Path(__file__).parent
(here / (NAME + "-F_Cu.gbr")).write_text(
    copper("Copper,L1,Top", TOP_TRACES + LETTER_F), encoding="ascii")
(here / (NAME + "-B_Cu.gbr")).write_text(
    copper("Copper,L2,Bot", BOTTOM_TRACES + LETTER_B), encoding="ascii")
(here / (NAME + "-Edge_Cuts.gbr")).write_text("\n".join(header("Profile,NP") + [
    "%ADD10C,0.100*%", "D10*"] + strokes([[(0, 0), (W, 0), (W, H), (0, H), (0, 0)]])
    + ["M02*"]) + "\n", encoding="ascii")
(here / (NAME + ".drl")).write_text("\n".join(
    ["M48", "METRIC", "T1C%.3f" % HOLE_D, "%", "T1"]
    + ["X%.1fY%.1f" % p for p in VIAS] + ["M30"]) + "\n", encoding="ascii")
