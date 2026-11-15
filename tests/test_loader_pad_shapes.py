"""Oval and rounded pads are loaded as what they are.

Their bounding boxes put copper in corners where there is none: beside a
2 mm oval the phantom corner reaches 0.41 mm past the pad, so a track KiCad
placed a legal distance away read as a short - and the isolation pass could
not cut between them either.
"""
import math
from pathlib import Path

import pytest
from shapely.geometry import Point, box

from gerber2rml import loader
from gerber2rml.engine.drc import isolation_bridges

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"
pytestmark = pytest.mark.exact_pads

HEAD = ("%TF.GenerationSoftware,KiCad,Pcbnew,10.0*%\n%FSLAX46Y46*%\n%MOMM*%\n"
        "%LPD*%\nG01*\n")


def _copper(tmp_path, apertures, flashes):
    f = tmp_path / "t-B_Cu.gbl"
    body = "".join("D%d*\nX%dY%dD03*\n" % (d, round(x * 1e6), round(y * 1e6))
                   for d, x, y in flashes)
    f.write_text(HEAD + apertures + body + "M02*\n", encoding="utf-8")
    from gerbonara import GerberFile
    return loader._copper_to_shapely(GerberFile.open(str(f)))


def test_an_oval_pad_is_an_oval(tmp_path):
    c = _copper(tmp_path, "%ADD10O,2.600000X2.000000*%\n", [(10, 10.0, 10.0)])
    want = 2.6 * 2.0 - (4 - math.pi) * 1.0 ** 2          # box less 4 corners
    assert c.area == pytest.approx(want, rel=2e-3)
    assert box(8.7, 9.0, 11.3, 11.0).buffer(1e-6).contains(c)   # inside its box
    assert not c.contains(Point(11.25, 10.95))            # no copper in the corner
    assert c.contains(Point(11.25, 10.0)) and c.contains(Point(10.0, 10.95))


def test_a_rounded_rectangle_has_round_corners(tmp_path):
    am = ("%AMRoundRect*\n0 Rectangle with rounded corners*\n0 $1 Rounding radius*\n"
          "0 $2 $3 $4 $5 $6 $7 $8 $9 X,Y pos of 4 corners*\n"
          "4,1,4,$2,$3,$4,$5,$6,$7,$8,$9,$2,$3,0*\n"
          "1,1,$1+$1,$2,$3*\n1,1,$1+$1,$4,$5*\n1,1,$1+$1,$6,$7*\n1,1,$1+$1,$8,$9*\n"
          "20,1,$1+$1,$2,$3,$4,$5,0*\n20,1,$1+$1,$4,$5,$6,$7,0*\n"
          "20,1,$1+$1,$6,$7,$8,$9,0*\n20,1,$1+$1,$8,$9,$2,$3,0*%\n"
          "%ADD10RoundRect,0.250000X-0.550000X-0.550000X0.550000X-0.550000X"
          "0.550000X0.550000X-0.550000X0.550000X0*%\n")
    c = _copper(tmp_path, am, [(10, 5.0, 5.0)])
    want = 1.6 * 1.6 - (4 - math.pi) * 0.25 ** 2
    assert c.area == pytest.approx(want, rel=2e-3)
    assert not c.contains(Point(5.78, 5.78))              # the corner is round


def test_a_track_a_legal_distance_from_an_oval_is_not_a_short(tmp_path):
    """0.9 mm from the pad's round end, diagonally: fine for a 0.8 mm bit.
    Its box's corner would have been 0.49 mm away."""
    r, gap = 1.0, 0.9
    d = (r + gap + 0.4) / math.sqrt(2)                    # 0.8 mm round "track"
    c = _copper(tmp_path, "%ADD10O,2.600000X2.000000*%\n%ADD11C,0.800000*%\n",
                [(10, 10.0, 10.0), (11, 10.3 + d, 10.0 + d)])
    assert isolation_bridges(c, 0.8) == []
    loader.PAD_SHAPES = "boxes"
    try:
        boxed = _copper(tmp_path, "%ADD10O,2.600000X2.000000*%\n"
                        "%ADD11C,0.800000*%\n",
                        [(10, 10.0, 10.0), (11, 10.3 + d, 10.0 + d)])
    finally:
        loader.PAD_SHAPES = "exact"
    assert len(isolation_bridges(boxed, 0.8)) == 1        # the phantom


def test_the_lab_board_has_no_shorts_once_its_pads_are_their_shape():
    b = loader.load_board(FIXT)
    assert isolation_bridges(b.copper, 0.8) == []
    loader.PAD_SHAPES = "boxes"
    try:
        boxed = loader.load_board(FIXT)
    finally:
        loader.PAD_SHAPES = "exact"
    assert len(isolation_bridges(boxed.copper, 0.8)) == 13
    assert b.copper.area < boxed.copper.area              # corners gone
    assert boxed.copper.buffer(1e-6).contains(b.copper)   # and nothing added


def test_toolpaths_still_build_on_true_shapes():
    from gerber2rml.config import TraceJob
    from gerber2rml.engine.traces import isolate
    b = loader.load_board(FIXT)
    assert isolate(b.copper, TraceJob(), outline=b.outline)
