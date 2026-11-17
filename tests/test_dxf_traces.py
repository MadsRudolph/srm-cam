"""Copper traces from a DXF for the laser page (engine/dxf_traces.py)."""
import math
from pathlib import Path

import pytest

from gerber2rml.engine import dxf_traces, xtool

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "laser_proof_test"


# -- a tiny DXF writer, enough to draw boards the way CAD exports do ---------

def _dxf(entities, units=4):
    head = ["0", "SECTION", "2", "HEADER", "9", "$INSUNITS", "70", str(units),
            "0", "ENDSEC"]
    body = ["0", "SECTION", "2", "ENTITIES", *entities, "0", "ENDSEC", "0", "EOF"]
    return "\n".join(head + body) + "\n"


def line(layer, a, b):
    return ["0", "LINE", "8", layer, "10", f"{a[0]}", "20", f"{a[1]}",
            "11", f"{b[0]}", "21", f"{b[1]}"]


def circle(layer, c, r, z=1.0):
    return ["0", "CIRCLE", "8", layer, "10", f"{c[0]}", "20", f"{c[1]}",
            "40", f"{r}", "230", f"{z}"]


def arc(layer, c, r, a0, a1, z=1.0):
    return ["0", "ARC", "8", layer, "10", f"{c[0]}", "20", f"{c[1]}",
            "40", f"{r}", "50", f"{a0}", "51", f"{a1}", "230", f"{z}"]


def lwpoly(layer, pts, closed=False, width=0.0, bulges=None):
    out = ["0", "LWPOLYLINE", "8", layer, "90", str(len(pts)),
           "70", "1" if closed else "0", "43", f"{width}"]
    for i, (x, y) in enumerate(pts):
        out += ["10", f"{x}", "20", f"{y}"]
        if bulges and bulges[i]:
            out += ["42", f"{bulges[i]}"]
    return out


def rect(layer, x0, y0, x1, y1):
    return lwpoly(layer, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], closed=True)


def write(tmp_path, entities, name="board.dxf", units=4):
    p = tmp_path / name
    p.write_text(_dxf(entities, units), encoding="ascii")
    return p


def proof_board_entities():
    """examples/laser_proof_test drawn as a CAD program exports it."""
    e = lwpoly("Edge.Cuts", [(0, 0), (40, 0), (40, 30), (0, 30)], closed=True)
    tracks = [[(4, 4), (16.19, 4), (16.19, 11.19)],
              [(36, 4), (23.81, 4), (23.81, 11.19)],
              [(4, 26), (16.19, 26), (16.19, 18.81)],
              [(30, 26), (23.81, 26), (23.81, 18.81)],
              [(18.73, 11.19), (18.73, 7)], [(21.27, 11.19), (21.27, 7)],
              [(18.73, 18.81), (18.73, 23)], [(21.27, 18.81), (21.27, 23)]]
    for t in tracks:
        e += lwpoly("F.Cu", t, width=0.5)
    for c in [(4, 4), (36, 4), (4, 26), (30, 26)]:
        e += circle("F.Cu", c, 1.3) + circle("F.Cu", c, 0.5)        # pad + hole
    for x in (16.19, 18.73, 21.27, 23.81):
        for y in (11.19, 18.81):
            e += circle("F.Cu", (x, y), 0.85) + circle("F.Cu", (x, y), 0.4)
    for x, y in [(18.73, 7), (21.27, 7), (18.73, 23), (21.27, 23)]:
        e += rect("F.Cu", x - 0.75, y - 0.75, x + 0.75, y + 0.75)
    e += circle("F.Cu", (36, 26), 0.5)                              # fiducial
    e += ["0", "TEXT", "8", "F.SilkS", "10", "1", "20", "1", "1", "label"]
    return e


# -- the example board, both ways --------------------------------------------

def test_the_dxf_board_matches_its_gerbers(tmp_path):
    dxf = dxf_traces.build_dxf_traces(write(tmp_path, proof_board_entities()),
                                      side="top")
    gbr = xtool.build_laser_traces(EXAMPLE, side="top", mirror=False)
    assert dxf.kind == "traces" and dxf.side == "top" and not dxf.mirrored
    assert dxf.size == pytest.approx(gbr.size, abs=1e-6)
    assert dxf.copper.symmetric_difference(gbr.copper).area < 0.02 * gbr.copper.area
    got = sorted((round(x, 2), round(y, 2), round(d, 2)) for x, y, d in dxf.drills)
    want = sorted((round(x, 2), round(y, 2), round(d, 2)) for x, y, d in gbr.drills)
    assert got == want
    assert len(dxf.features) == 12
    assert dxf.apertures                    # isolation to cut


def test_the_proof_has_its_drilled_holes(tmp_path):
    art = dxf_traces.build_dxf_traces(write(tmp_path, proof_board_entities()))
    plan = xtool.proof_on_isolation(art, (60.0, 60.0))
    assert plan.marks


def test_the_bottom_face_is_mirrored(tmp_path):
    p = write(tmp_path, proof_board_entities())
    top = dxf_traces.build_dxf_traces(p, side="top")
    bot = dxf_traces.build_dxf_traces(p, side="bottom")
    assert bot.mirrored and bot.side == "bottom"
    # The lopsided hole at (30, 26) lands at 40 - 30 = 10 when mirrored.
    assert any(abs(x - 30) < 1e-6 and abs(y - 26) < 1e-6 for x, y, _ in top.drills)
    assert any(abs(x - 10) < 1e-6 and abs(y - 26) < 1e-6 for x, y, _ in bot.drills)


# -- reading ----------------------------------------------------------------

def test_inches_are_converted(tmp_path):
    e = rect("Outline", 0, 0, 1, 1) + rect("0", 0.25, 0.25, 0.75, 0.75)
    b = dxf_traces.read_dxf(write(tmp_path, e, units=1))
    assert b.outline.area == pytest.approx(25.4 ** 2)
    assert b.copper.area == pytest.approx(12.7 ** 2)
    assert any("inches" in n for n in b.notes)


def test_lines_joined_end_to_end_are_a_filled_pad(tmp_path):
    e = rect("Edge.Cuts", 0, 0, 20, 20)
    e += line("0", (5, 5), (10, 5)) + line("0", (5, 10), (10, 10))   # out of order,
    e += line("0", (10, 10), (10, 5)) + line("0", (5, 5), (5, 10))   # some reversed
    b = dxf_traces.read_dxf(write(tmp_path, e))
    assert b.copper.area == pytest.approx(25.0)


def test_nested_shapes_cut_holes(tmp_path):
    e = rect("Edge.Cuts", 0, 0, 20, 20) + rect("0", 2, 2, 18, 18) + rect("0", 5, 5, 15, 15)
    b = dxf_traces.read_dxf(write(tmp_path, e))
    assert b.copper.area == pytest.approx(16 * 16 - 10 * 10)


def test_a_bulge_draws_a_round_end(tmp_path):
    # A 2 x 4 slot: two straight sides and two half circles (bulge 1).
    pts = [(5, 5), (9, 5), (9, 7), (5, 7)]
    e = rect("Edge.Cuts", 0, 0, 20, 20) + lwpoly("0", pts, closed=True,
                                                 bulges=[0, 1, 0, 1])
    b = dxf_traces.read_dxf(write(tmp_path, e))
    assert b.copper.area == pytest.approx(4 * 2 + math.pi, rel=1e-3)


def test_an_open_line_without_width_is_a_default_track(tmp_path):
    e = rect("Edge.Cuts", 0, 0, 20, 20) + line("0", (2, 10), (18, 10))
    b = dxf_traces.read_dxf(write(tmp_path, e))
    w = dxf_traces.DEFAULT_TRACK_MM
    assert b.copper.area == pytest.approx(16 * w + math.pi * (w / 2) ** 2, rel=1e-2)
    assert any("tracks" in n for n in b.notes)


def test_an_arc_drawn_from_below_is_turned_back(tmp_path):
    # Extrusion -Z: the arc's X runs the other way (Fusion, SolidWorks).
    e = rect("Edge.Cuts", -20, -20, 20, 20)
    e += arc("0", (5, 0), 2, 0, 180, z=-1) + line("0", (-7, 0), (-3, 0))
    b = dxf_traces.read_dxf(write(tmp_path, e))
    assert b.copper.centroid.x == pytest.approx(-5, abs=1e-3)
    assert b.copper.area == pytest.approx(math.pi * 4 / 2, rel=5e-3)  # chords


def test_a_shape_round_everything_is_the_outline(tmp_path):
    e = rect("0", 0, 0, 30, 20) + rect("0", 5, 5, 10, 10) + circle("0", (20, 10), 1)
    b = dxf_traces.read_dxf(write(tmp_path, e))
    assert b.outline.area == pytest.approx(600)
    assert b.copper.area == pytest.approx(25 + math.pi, rel=1e-2)


def test_no_outline_at_all_uses_the_copper_plus_a_margin(tmp_path):
    b = dxf_traces.read_dxf(write(tmp_path, rect("0", 5, 5, 10, 10) + rect("0", 15, 5, 20, 10)))
    assert b.outline.bounds == pytest.approx((4, 4, 21, 11))
    assert any("No board outline" in n for n in b.notes)


def test_the_outline_drawn_on_the_copper_layer_is_not_copper(tmp_path):
    e = rect("Edge.Cuts", 0, 0, 20, 20) + rect("F.Cu", 0, 0, 20, 20) + rect("F.Cu", 5, 5, 8, 8)
    b = dxf_traces.read_dxf(write(tmp_path, e))
    assert b.copper.area == pytest.approx(9)


def test_circles_on_a_drill_layer_are_drills(tmp_path):
    e = rect("Edge.Cuts", 0, 0, 20, 20) + rect("F.Cu", 2, 2, 6, 6)
    e += circle("Drill", (15, 15), 0.5) + circle("NPTH", (4, 15), 1.6)
    b = dxf_traces.read_dxf(write(tmp_path, e))
    got = [v for d in sorted(b.drills) for v in d]
    assert got == pytest.approx([4, 15, 3.2, 15, 15, 1.0])


def test_named_copper_layers_leave_the_rest_out_and_pick_the_face(tmp_path):
    e = rect("Edge.Cuts", 0, 0, 20, 20) + rect("F.Cu", 2, 2, 4, 4)
    e += rect("B.Cu", 10, 10, 15, 15) + rect("Dwgs.User", 5, 5, 9, 9)
    p = write(tmp_path, e)
    top = dxf_traces.read_dxf(p, side="top")
    bot = dxf_traces.read_dxf(p, side="bottom")
    assert top.copper.area == pytest.approx(4)
    assert bot.copper.area == pytest.approx(25)
    assert top.faces == ("top", "bottom")
    assert any("Dwgs.User" in n for n in top.notes)


def test_blocks_are_placed_turned_and_scaled(tmp_path):
    blocks = ["0", "SECTION", "2", "BLOCKS",
              "0", "BLOCK", "8", "0", "2", "PAD", "10", "0", "20", "0",
              *rect("0", 0, 0, 2, 1),
              "0", "ENDBLK", "0", "ENDSEC"]
    ins = ["0", "INSERT", "8", "F.Cu", "2", "PAD", "10", "10", "20", "10",
           "41", "2", "42", "2", "50", "90"]
    text = _dxf(rect("Edge.Cuts", 0, 0, 20, 20) + ins)
    text = text.replace("0\nSECTION\n2\nENTITIES", "\n".join(blocks) + "\n0\nSECTION\n2\nENTITIES")
    p = tmp_path / "b.dxf"
    p.write_text(text, encoding="ascii")
    b = dxf_traces.read_dxf(p)
    assert b.copper.area == pytest.approx(8)
    assert b.copper.bounds == pytest.approx((8, 10, 10, 14))


def test_a_spline_is_followed(tmp_path):
    # A closed degree-1 spline is its control polygon: a 4 x 4 square.
    ctrl = [(2, 2), (6, 2), (6, 6), (2, 6), (2, 2)]
    sp = ["0", "SPLINE", "8", "0", "70", "1", "71", "1"]
    for k in [0, 0, 1, 2, 3, 4, 4]:
        sp += ["40", str(k)]
    for x, y in ctrl:
        sp += ["10", str(x), "20", str(y)]
    b = dxf_traces.read_dxf(write(tmp_path, rect("Edge.Cuts", 0, 0, 10, 10) + sp))
    assert b.copper.area == pytest.approx(16, rel=1e-3)


def test_unknown_entities_are_named(tmp_path):
    e = rect("Edge.Cuts", 0, 0, 10, 10) + rect("0", 2, 2, 4, 4) + ["0", "HATCH", "8", "0"]
    b = dxf_traces.read_dxf(write(tmp_path, e))
    assert any("HATCH" in n for n in b.notes)


def test_a_binary_dxf_says_so(tmp_path):
    p = tmp_path / "bin.dxf"
    p.write_bytes(b"AutoCAD Binary DXF\r\n\x1a\x00rest")
    with pytest.raises(xtool.TracesError, match="binary"):
        dxf_traces.build_dxf_traces(p)


def test_not_a_dxf_says_so(tmp_path):
    p = tmp_path / "x.dxf"
    p.write_text("hello\nworld\n")
    with pytest.raises(xtool.TracesError):
        dxf_traces.build_dxf_traces(p)


def test_the_laser_pages_own_dxf_reads_back(tmp_path):
    """What 'Write laser traces' exports is readable (outline layer named)."""
    gbr = xtool.build_laser_traces(EXAMPLE, side="top", mirror=False)
    out = xtool.write_traces_dxf(gbr, tmp_path, "proof")
    b = dxf_traces.read_dxf(out)
    assert b.outline.area == pytest.approx(gbr.outline.area, rel=1e-3)


# -- on the laser page ------------------------------------------------------

@pytest.fixture
def page(qt_app, monkeypatch):
    from shapely.geometry import box
    from gerber2rml.gui2 import stencil_laser as sl
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "dxf"))
    art = xtool.LaserArt(kind="mask", outline=box(0, 0, 20, 20),
                         apertures=[box(5, 5, 8, 8)])
    d = sl.StencilLaserDialog(art, name="other board")
    yield d
    d.close()


def test_a_dxf_opened_on_the_page_becomes_the_traces_job(page, tmp_path):
    p = write(tmp_path, proof_board_entities(), name="proof.dxf")
    page.load_dxf_art(dxf_traces.build_dxf_traces(p), p)
    assert page.kind == "traces"
    assert page.name_lbl.text() == "proof.dxf"
    assert page.base_art.side == "top" and not page.base_art.mirrored
    assert len(page.base_art.drills) == 12
    assert not page.proof_btn.isHidden()            # the proof can run on it
    assert page.art.apertures


def test_the_copper_face_switch_mirrors_the_dxf(page, tmp_path):
    p = write(tmp_path, proof_board_entities(), name="proof.dxf")
    page.load_dxf_art(dxf_traces.build_dxf_traces(p), p)
    page.copper_side.setCurrentIndex(page.copper_side.findData("bottom"))
    assert page.base_art.mirrored and page.base_art.side == "bottom"
    assert len(page.base_art.drills) == 12


# -- KiCad's copper export: outlines as LINEs, a pour, lines drawn twice -----

def _lines(layer, pts):
    """A closed outline as separate LINEs, as KiCad writes it."""
    out = []
    for a, b in zip(pts, pts[1:] + pts[:1]):
        out += line(layer, a, b)
    return out


def _sq(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_a_pour_with_a_gap_and_a_trace_in_it(tmp_path):
    # Edge, the pour inside it, a gap cut in the pour, a trace in the gap.
    e = (_lines("B.Cu", _sq(0, 0, 40, 30)) + _lines("B.Cu", _sq(1, 1, 39, 29))
         + _lines("B.Cu", _sq(10, 10, 30, 20)) + _lines("B.Cu", _sq(12, 14, 28, 16)))
    b = dxf_traces.read_dxf(write(tmp_path, e))
    from shapely.geometry import Point
    assert b.outline.area == pytest.approx(1200)
    assert b.copper.contains(Point(5, 5))           # the pour
    assert not b.copper.contains(Point(20, 12))     # the gap
    assert b.copper.contains(Point(20, 15))         # the trace in it
    assert b.copper.area == pytest.approx(38 * 28 - 20 * 10 + 16 * 2)


def test_a_trace_running_into_the_pour_shares_its_corners(tmp_path):
    # A trace from the pour's edge into a gap: the pour's outline runs round
    # the gap and out along the trace, as KiCad merges them. Another trace
    # in the gap touches the first at a corner, so ends meet four at a time
    # at (25, 16), and the fill must not care how they are walked.
    gap = [(10, 16), (10, 20), (30, 20), (30, 10), (10, 10), (10, 14)]
    trace = [(10, 14), (25, 14), (25, 16), (10, 16)]
    other = [(25, 16), (28, 16), (28, 18), (25, 18)]
    e = _lines("Edge.Cuts", _sq(0, 0, 40, 30)) + _lines("B.Cu", _sq(1, 1, 39, 29))
    for path in (gap, trace):
        for a, c in zip(path, path[1:]):
            e += line("B.Cu", a, c)
    e += _lines("B.Cu", other)
    b = dxf_traces.read_dxf(write(tmp_path, e))
    from shapely.geometry import Point
    assert b.copper.contains(Point(20, 15))
    assert not b.copper.contains(Point(20, 12))
    assert b.copper.contains(Point(26.5, 17))       # the trace in the gap
    assert b.copper.area == pytest.approx(38 * 28 - 20 * 10 + 15 * 2 + 3 * 2)


def test_a_line_drawn_twice_is_counted_once(tmp_path):
    e = _lines("Edge.Cuts", _sq(0, 0, 20, 20)) + _lines("0", _sq(5, 5, 10, 10))
    e += line("0", (10, 5), (10, 10)) + circle("0", (15, 15), 1) + circle("0", (15, 15), 1)
    b = dxf_traces.read_dxf(write(tmp_path, e))
    assert b.copper.area == pytest.approx(25 + math.pi, rel=1e-3)
    assert any("drawn twice" in n for n in b.notes)


def test_a_drill_mark_inside_a_drawn_pad_is_a_drill(tmp_path):
    # KiCad's "small" drill marks: a 0.35 mm circle in the pad's middle.
    e = _lines("Edge.Cuts", _sq(0, 0, 20, 20)) + _lines("B.Cu", _sq(4, 4, 6, 6))
    e += circle("B.Cu", (5, 5), 0.175) + _lines("B.Cu", _sq(14, 14, 16, 16))
    e += circle("B.Cu", (15, 15), 0.175)
    b = dxf_traces.read_dxf(write(tmp_path, e))
    assert sorted((round(x, 3), round(y, 3), round(d, 3)) for x, y, d in b.drills) == [
        (5, 5, 0.35), (15, 15, 0.35)]
    assert b.copper.area == pytest.approx(8)        # the pads stay solid


def test_a_bottom_copper_dxf_opens_mirrored(tmp_path):
    e = _lines("Edge.Cuts", _sq(0, 0, 40, 30)) + _lines("B.Cu", _sq(2, 2, 6, 6))
    art = dxf_traces.build_dxf_traces(write(tmp_path, e))
    assert art.side == "bottom" and art.mirrored
    # The pad at x 2..6 lands at 40 - 6 .. 40 - 2 once mirrored.
    assert art.copper.bounds == pytest.approx((34, 2, 38, 6))


# -- mirror and flip a DXF ---------------------------------------------------

def _hole(art, near):
    return min(art.drills, key=lambda d: math.dist(d[:2], near))[:2]


def test_flip_turns_the_drawing_top_to_bottom(tmp_path):
    p = write(tmp_path, proof_board_entities())
    as_drawn = dxf_traces.build_dxf_traces(p, side="top")
    flipped = dxf_traces.build_dxf_traces(p, side="top", flip=True)
    assert flipped.flipped and not flipped.mirrored
    # the lopsided hole at (30, 26) on a 30 mm tall board lands at y = 4
    assert any(math.dist((x, y), (30, 26)) < 1e-6 for x, y, _ in as_drawn.drills)
    assert any(math.dist((x, y), (30, 4)) < 1e-6 for x, y, _ in flipped.drills)
    assert flipped.copper.area == pytest.approx(as_drawn.copper.area)


def test_mirror_can_be_chosen_whatever_the_face(tmp_path):
    p = write(tmp_path, proof_board_entities())
    top_mirrored = dxf_traces.build_dxf_traces(p, side="top", mirror=True)
    assert top_mirrored.mirrored and top_mirrored.side == "top"
    assert any(math.dist((x, y), (10, 26)) < 1e-6 for x, y, _ in top_mirrored.drills)
    both = dxf_traces.build_dxf_traces(p, side="top", mirror=True, flip=True)
    assert any(math.dist((x, y), (10, 4)) < 1e-6 for x, y, _ in both.drills)


def test_the_page_mirrors_and_flips_a_dxf(page, tmp_path):
    p = write(tmp_path, proof_board_entities(), name="proof.dxf")
    page.load_dxf_art(dxf_traces.build_dxf_traces(p), p)
    assert not page.dxf_orient.isHidden()
    assert not page.dxf_mirror.isChecked() and not page.dxf_flip.isChecked()
    page.dxf_flip.setChecked(True)
    assert page.base_art.flipped and not page.base_art.mirrored
    assert len(page.base_art.drills) == 12 and page.art.apertures
    page.dxf_mirror.setChecked(True)
    assert page.base_art.mirrored and page.base_art.flipped
    assert "flipped" in page.size_lbl.text()
    # a new copper face starts from its own mirroring; the flip is kept
    page.copper_side.setCurrentIndex(page.copper_side.findData("bottom"))
    assert page.base_art.mirrored and page.dxf_mirror.isChecked()
    page.dxf_mirror.setChecked(False)
    assert not page.base_art.mirrored and page.base_art.side == "bottom"


def test_the_boxes_are_only_there_for_a_dxf(page):
    assert page.dxf_orient.isHidden()          # a Gerber-style job: none
