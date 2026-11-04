"""The laser file for solder mask.

What it has to get right: every loop closed and the sizes real, in a file read
back the way a laser's software would read it; the openings on the milled pads,
mirrored with the outline; a pad too small for the shrink said out loud; a missing
layer a sentence and not a crash. And the app: off by default, in both tiers, and
never at the cost of the machine files.

Fixtures: ``mask_shapes`` is a KiCad 10 plot of one of each pad shape
(``shapes.kicad_pcb`` is its source). ``esp32solder_mask`` is a real board, whose
``kicad-cli pcb export dxf`` at a pad clearance of -0.1 gave 78 openings, the
0.9 × 1.5 mm pads coming out 0.7 × 1.3.
"""
import math
from pathlib import Path

import pytest
from shapely.affinity import translate
from shapely.geometry import Point, Polygon

from gerber2rml.engine import soldermask as sm
from gerber2rml.loader import load_board

FIXTURES = Path(__file__).parent / "fixtures"
SHAPES = FIXTURES / "mask_shapes"
ESP = FIXTURES / "esp32solder_mask"
BUCK = FIXTURES / "mosfet_test"


def read_dxf(path):
    """The entities of a DXF, read from its group codes alone.

    Deliberately not the writer's own structures: this is what a program that
    has never heard of us sees."""
    lines = Path(path).read_text(encoding="ascii").split("\n")
    pairs = [(lines[i].strip(), lines[i + 1].strip())
             for i in range(0, len(lines) - 1, 2)]
    start = pairs.index(("2", "ENTITIES"))
    out, cur = [], None
    for code, value in pairs[start + 1:]:
        if code == "0":
            if cur is not None:
                out.append(cur)
            cur = None if value == "ENDSEC" else {"type": value, "pts": []}
            if value == "ENDSEC":
                break
        elif cur is not None:
            if code == "10":
                cur["pts"].append([float(value), None])
            elif code == "20":
                cur["pts"][-1][1] = float(value)
            else:
                cur[code] = value
    return out


def header_value(path, name):
    lines = Path(path).read_text(encoding="ascii").split("\n")
    return lines[lines.index(name) + 2].strip()


def loops(path, layer):
    return [e for e in read_dxf(path) if e.get("8") == layer]


def size(poly):
    x0, y0, x1, y1 = poly.bounds
    return x1 - x0, y1 - y0


def opening_at(art, x, y):
    hits = [p for p in art.openings if p.contains(Point(x, y))]
    assert len(hits) == 1, f"{len(hits)} openings at {x}, {y}"
    return hits[0]


# ---------------------------------------------------------------- the file

def test_every_loop_in_the_file_is_closed(tmp_path):
    path = sm.write_mask_files(ESP, tmp_path, "esp")[0][0]
    ents = read_dxf(path)
    assert ents and all(e["type"] == "LWPOLYLINE" for e in ents)
    for e in ents:
        assert e["70"] == "1"                       # the closed flag
        assert e["pts"][0] == e["pts"][-1]          # and closed in the points
        assert int(e["90"]) == len(e["pts"])
        assert Polygon(e["pts"]).is_valid


def test_the_file_is_millimetres_with_two_named_layers(tmp_path):
    path = sm.write_mask_files(ESP, tmp_path, "esp")[0][0]
    assert header_value(path, "$INSUNITS") == "4"       # millimetres
    assert header_value(path, "$MEASUREMENT") == "1"    # metric
    assert {e["8"] for e in read_dxf(path)} == {sm.LAYER_OPENINGS, sm.LAYER_OUTLINE}
    # Told apart by colour as well, for software that goes by that.
    colours = {e["8"]: e["62"] for e in read_dxf(path)}
    assert colours[sm.LAYER_OPENINGS] != colours[sm.LAYER_OUTLINE]


def test_a_real_board_gives_78_openings_and_the_sizes_kicad_gives(tmp_path):
    path = sm.write_mask_files(ESP, tmp_path, "esp")[0][0]
    openings = loops(path, sm.LAYER_OPENINGS)
    assert len(openings) == 78
    outline = loops(path, sm.LAYER_OUTLINE)
    assert len(outline) == 1
    w, h = size(Polygon(outline[0]["pts"]))
    assert w == pytest.approx(54.0, abs=1e-3) and h == pytest.approx(45.8, abs=1e-3)
    # The module's 0.9 x 1.5 pads, read back from the file, one way or the other.
    small = [sorted(size(Polygon(e["pts"]))) for e in openings]
    assert sum(1 for a, b in small
               if a == pytest.approx(0.7, abs=1e-3)
               and b == pytest.approx(1.3, abs=1e-3)) == 38


def test_the_outline_starts_at_the_origin_and_holds_every_opening():
    art = sm.build_mask(ESP)
    x0, y0, x1, y1 = art.outline.bounds
    assert (x0, y0) == pytest.approx((0, 0), abs=1e-9)
    for p in art.openings:
        assert art.outline.contains(p)


# -------------------------------------------------------------- pad shapes

@pytest.mark.parametrize("x,y,want_w,want_h,want_area", [
    (38, 25, 1.8, 2.8, 1.8 * 2.8),                   # rectangle, 2 x 3
    (18, 25, 2.3, 2.3, math.pi * 1.15 ** 2),         # circle, 2.5
    (8, 25, 2.8, 1.4, 1.4 * 1.4 + math.pi * 0.7 ** 2),   # oblong, 3 x 1.6
    (28, 15, 2.8, 1.8, 2.8 * 1.8 - (4 - math.pi) * 0.4 ** 2),  # rounded, r 0.5
    (8, 15, 1.8, 1.8, math.pi * 0.9 ** 2),           # through-hole: no hole in it
])
def test_each_pad_shape_comes_in_by_the_shrink(x, y, want_w, want_h, want_area):
    p = opening_at(sm.build_mask(SHAPES), x, y)
    w, h = size(p)
    assert w == pytest.approx(want_w, abs=0.005)
    assert h == pytest.approx(want_h, abs=0.005)
    assert p.area == pytest.approx(want_area, abs=0.01)


def test_a_rotated_rectangle_is_rotated_and_not_its_bounding_box():
    """gerbonara's Rectangle.to_arc_poly draws the bounding box; a pad at 30
    degrees drawn that way burns the ink off well beside the pad."""
    p = opening_at(sm.build_mask(SHAPES), 28, 25)
    assert p.area == pytest.approx(1.8 * 2.8, abs=1e-3)
    w, h = size(p)
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    assert w == pytest.approx(1.8 * c + 2.8 * s, abs=1e-3)
    assert h == pytest.approx(1.8 * s + 2.8 * c, abs=1e-3)


def test_a_rotated_oblong_and_rounded_pad_keep_their_shape():
    art = sm.build_mask(SHAPES)
    oblong = opening_at(art, 38, 15)                 # 3 x 1.6 at 45 degrees
    assert oblong.area == pytest.approx(1.4 * 1.4 + math.pi * 0.7 ** 2, abs=0.01)
    rounded = opening_at(art, 18, 15)                # 3 x 2, r 0.5, at 20 degrees
    assert rounded.area == pytest.approx(2.8 * 1.8 - (4 - math.pi) * 0.4 ** 2,
                                         abs=0.01)


def test_a_drawn_polygon_shrinks_at_every_edge_and_stays_square_inside():
    """A region, not a flash: an L, whose inside corner stays a corner."""
    p = opening_at(sm.build_mask(SHAPES), 20, 4)
    # 45 mm2, perimeter 32, five outside corners and one inside.
    assert p.area == pytest.approx(45 - 32 * 0.1 + 4 * 0.1 ** 2, abs=1e-3)
    assert len(p.exterior.coords) == 7


def test_the_shrink_is_the_operators():
    art = sm.build_mask(SHAPES, shrink=0.2)
    assert size(opening_at(art, 38, 25)) == pytest.approx((1.6, 2.6), abs=1e-6)
    none = sm.build_mask(SHAPES, shrink=0)
    assert size(opening_at(none, 38, 25)) == pytest.approx((2.0, 3.0), abs=1e-6)


def test_a_negative_shrink_is_refused():
    with pytest.raises(sm.MaskError, match="negative"):
        sm.build_mask(SHAPES, shrink=-0.1)


# ------------------------------------------------- what the shrink can cost

def test_a_pad_too_small_for_the_shrink_is_reported_not_dropped():
    art = sm.build_mask(SHAPES)                      # 0.15 mm square at 38, 5
    assert len(art.vanished) == 1
    x, y, w, h = art.vanished[0]
    assert (x, y) == pytest.approx((38, 5), abs=1e-6)
    assert (w, h) == pytest.approx((0.15, 0.15), abs=1e-6)
    said = " ".join(art.warnings())
    assert "vanished" in said and "0.15" in said and "X38.00" in said


def test_an_opening_left_very_thin_is_reported():
    art = sm.build_mask(SHAPES)                      # 0.3 wide: 0.1 left
    assert any(abs(n[0] - 32) < 1e-6 for n in art.narrow)
    assert "0.20 mm wide" in " ".join(art.warnings())


def test_nothing_to_report_on_an_ordinary_board():
    assert sm.build_mask(ESP).warnings() == []


# ----------------------------------------------------------------- mirroring

def test_the_openings_and_the_outline_mirror_together():
    plain = sm.build_mask(ESP, mirror=False)
    mirrored = sm.build_mask(ESP, mirror=True)
    w = plain.outline.bounds[2]
    assert mirrored.outline.bounds == pytest.approx(plain.outline.bounds, abs=1e-6)
    want = sorted((round(w - p.centroid.x, 3), round(p.centroid.y, 3))
                  for p in plain.openings)
    got = sorted((round(p.centroid.x, 3), round(p.centroid.y, 3))
                 for p in mirrored.openings)
    assert got == pytest.approx(want, abs=2e-3)


def _share_on_milled_copper(folder, mirror):
    """Of the file's openings, how many lie wholly on the copper the mill cuts,
    with the two frames put together at the outline's corner."""
    board = load_board(folder, mirror=True)
    x0, y0, *_ = board.outline.bounds
    art = sm.build_mask(folder, mirror=mirror)
    copper = board.copper.buffer(1e-3)
    return sum(copper.contains(translate(p, x0, y0))
               for p in art.openings) / len(art.openings)


def test_the_mirror_is_the_one_the_mill_cuts_with():
    """The real test of it. Every opening of a real board is on the milled
    copper. Its ground pour catches most of them unmirrored, so a board with no
    pour says it more plainly: the pads are on it one way and not the other."""
    assert _share_on_milled_copper(BUCK, True) == 1.0
    assert _share_on_milled_copper(BUCK, False) < 1.0
    # All but the L drawn on the mask layer alone, which has no copper.
    assert _share_on_milled_copper(SHAPES, True) == pytest.approx(9 / 10)
    assert _share_on_milled_copper(SHAPES, False) < 0.5


def test_the_file_name_says_whether_it_is_mirrored(tmp_path):
    yes = sm.write_mask_files(ESP, tmp_path, "esp", mirror=True)[0][0]
    no = sm.write_mask_files(ESP, tmp_path, "esp", mirror=False)[0][0]
    assert yes.name == "esp_mask_mirrored.dxf"
    assert no.name == "esp_mask_not_mirrored.dxf"


def test_a_double_sided_job_gets_a_file_per_face(tmp_path):
    done = sm.write_mask_files(BUCK, tmp_path, "buck", double_sided=True)
    assert [p.name for p, _ in done] == ["buck_mask_bottom_mirrored.dxf",
                                         "buck_mask_top_not_mirrored.dxf"]
    bottom, top = (a for _, a in done)
    assert bottom.source.name == "buck-B_Mask.gbs" and bottom.mirrored
    assert top.source.name == "buck-F_Mask.gts" and not top.mirrored


# ----------------------------------------------------------- missing layers

def _copy(folder, tmp_path, *suffixes):
    for p in Path(folder).iterdir():
        if p.name.endswith(suffixes):
            (tmp_path / p.name).write_bytes(p.read_bytes())
    return tmp_path


def test_no_mask_layer_is_a_sentence_saying_what_to_do(tmp_path):
    folder = _copy(BUCK, tmp_path, "-Edge_Cuts.gm1", "-B_Cu.gbl")
    with pytest.raises(sm.MaskError) as e:
        sm.build_mask(folder)
    said = str(e.value)
    assert "B.Mask" in said and "Plot" in said and str(folder) in said


def test_the_other_faces_mask_is_named_and_not_used(tmp_path):
    folder = _copy(BUCK, tmp_path, "-Edge_Cuts.gm1", "-F_Mask.gts")
    with pytest.raises(sm.MaskError) as e:
        sm.build_mask(folder)
    assert "buck-F_Mask.gts" in str(e.value) and "other face" in str(e.value)


def test_no_outline_is_a_sentence_too(tmp_path):
    folder = _copy(BUCK, tmp_path, "-B_Mask.gbs")
    with pytest.raises(sm.MaskError, match="Edge.Cuts"):
        sm.build_mask(folder)


def test_an_empty_mask_layer_is_not_an_empty_file(tmp_path):
    """The bundled test boards plot an empty mask so gerbonara has its layer."""
    folder = _copy(FIXTURES.parent.parent / "examples" / "calibration", tmp_path,
                   "-Edge_Cuts.gbr", "-B_Mask.gbr")
    with pytest.raises(sm.MaskError, match="empty"):
        sm.build_mask(folder)
    assert not list(tmp_path.glob("*.dxf"))


# -------------------------------------------------------- hand-written Gerbers

GERBER = """%FSLAX46Y46*%
%MO{unit}*%
%ADD10C,{big}*%
%ADD11C,{small}*%
%LPD*%
D10*
X{x}Y{y}D03*
%LPC*%
D11*
X{x}Y{y}D03*
M02*
"""

EDGE = """%FSLAX46Y46*%
%MO{unit}*%
%ADD10C,0.1*%
D10*
X0Y0D02*
X{w}Y0D01*
X{w}Y{w}D01*
X0Y{w}D01*
X0Y0D01*
M02*
"""


def test_a_clear_flash_leaves_a_ring_of_two_closed_loops(tmp_path):
    """Clear objects subtract, and the hole in a ring stays a loop of its own."""
    (tmp_path / "r-B_Mask.gbr").write_text(GERBER.format(
        unit="MM", big="4.0", small="2.0", x="5000000", y="5000000"))
    (tmp_path / "r-Edge_Cuts.gbr").write_text(EDGE.format(unit="MM", w="10000000"))
    art = sm.build_mask(tmp_path, mirror=False)
    assert len(art.openings) == 1
    assert len(art.openings[0].interiors) == 1
    assert art.openings[0].area == pytest.approx(
        math.pi * (1.9 ** 2 - 1.1 ** 2), abs=0.02)
    path = sm.write_mask_dxf(art, tmp_path, "r")
    assert len(loops(path, sm.LAYER_OPENINGS)) == 2


def test_a_plot_in_inches_comes_out_in_millimetres(tmp_path):
    (tmp_path / "i-B_Mask.gbr").write_text(GERBER.format(
        unit="IN", big="0.1", small="0.0", x="1000000", y="1000000"))
    (tmp_path / "i-Edge_Cuts.gbr").write_text(EDGE.format(unit="IN", w="2000000"))
    art = sm.build_mask(tmp_path, mirror=False, shrink=0.1)
    assert art.outline.bounds[2] == pytest.approx(50.8, abs=1e-3)
    p = art.openings[0]
    assert size(p)[0] == pytest.approx(2.54 - 0.2, abs=0.005)
    assert p.centroid.x == pytest.approx(25.4, abs=1e-3)


# ------------------------------------------------------------------- the app

@pytest.fixture
def win(qt_app, monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.load_folder(str(BUCK))
    yield w
    w.close()


def test_off_by_default_and_the_export_is_what_it_was(win, tmp_path):
    assert not win.inspector.setup.solder_mask.isChecked()
    assert win.inspector.setup.mask_shrink.value() == sm.DEFAULT_SHRINK
    win.export_to(tmp_path)
    assert not list(tmp_path.glob("*.dxf"))
    assert win.sheet.text().count("solder mask") == 0


def test_ticked_the_export_writes_it_beside_the_machine_files(win, tmp_path):
    win.inspector.setup.solder_mask.setChecked(True)
    written = win.export_to(tmp_path)
    assert written and all(Path(p).exists() for p in written)
    path = tmp_path / "buck_mask_mirrored.dxf"
    assert path.exists() and loops(path, sm.LAYER_OPENINGS)
    assert win.exported_path(path.name) == path
    assert path.name in win.sheet.text()
    assert "buck_mask_mirrored.dxf" in win.mask_status()[1]


def test_the_machine_files_do_not_change_with_it(win, tmp_path):
    a, b = tmp_path / "off", tmp_path / "on"
    win.export_to(a)
    win.inspector.setup.solder_mask.setChecked(True)
    win.export_to(b)
    names = {p.name for p in b.iterdir()} - {"buck_mask_mirrored.dxf"}
    assert names == {p.name for p in a.iterdir()}
    for n in names:
        if n.endswith(".nc"):
            assert (a / n).read_bytes() == (b / n).read_bytes(), n


def test_the_shrink_box_reaches_the_file(win, tmp_path):
    setup = win.inspector.setup
    setup.solder_mask.setChecked(True)
    setup.mask_shrink.setValue(0.2)
    paths, _notes = win.write_mask_to(tmp_path)
    fine = sm.build_mask(BUCK, shrink=0.2)
    got = loops(paths[0], sm.LAYER_OPENINGS)
    assert sum(Polygon(e["pts"]).area for e in got) == pytest.approx(
        sum(p.area for p in fine.openings), abs=1e-2)


def test_mirror_off_writes_an_unmirrored_file(win, tmp_path):
    win.inspector.setup.solder_mask.setChecked(True)
    win.inspector.setup.mirror.setChecked(False)
    assert "Not mirrored" in win.mask_status()[1]
    paths, _notes = win.write_mask_to(tmp_path)
    assert paths[0].name == "buck_mask_not_mirrored.dxf"


def test_a_folder_with_no_mask_says_so_and_the_machine_files_still_come(
        qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    src = tmp_path / "src"
    src.mkdir()
    for p in BUCK.iterdir():
        if "Mask" not in p.name:
            (src / p.name).write_bytes(p.read_bytes())
    w = MainWindow()
    try:
        w.load_folder(str(src))
        setup = w.inspector.setup
        setup.solder_mask.setChecked(True)
        level, text = w.mask_status()
        assert level == "warn" and "B.Mask" in text
        assert "B.Mask" in setup.mask_note.text()
        out = tmp_path / "out"
        written = w.export_to(out)
        assert written and any(p.suffix == ".nc" for p in map(Path, written))
        assert not list(out.glob("*.dxf"))
        assert "No B.Mask" in w.sheet.text()
    finally:
        w.close()


def test_a_pad_lost_to_the_shrink_reaches_the_operator(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    try:
        w.load_folder(str(BUCK))
        w.inspector.setup.solder_mask.setChecked(True)
        w.inspector.setup.mask_shrink.setValue(sm.MAX_SHRINK)
        real = sm.write_mask_files

        def lost(folder, out_dir, name, **kw):
            kw.pop("double_sided", None)
            return real(SHAPES, out_dir, name, **kw)
        monkeypatch.setattr(sm, "write_mask_files", lost)
        _paths, notes = w.write_mask_to(tmp_path)
        assert any("vanished" in n for n in notes)
        assert w.mask_status()[0] == "warn"
    finally:
        w.close()


def test_novice_has_the_box_too(qt_app, monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "novice")
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    try:
        w.load_folder(str(BUCK))
        setup = w.inspector.setup
        setup.sync()
        assert not setup.mask_section.isHidden()
        assert setup.mask_write_btn.isHidden()      # not until it is asked for
        setup.solder_mask.setChecked(True)
        assert not setup.mask_write_btn.isHidden()
    finally:
        w.close()


def test_a_panel_gets_one_file_per_board_and_one_for_a_repeat(win, tmp_path):
    win.add_folder(str(BUCK))                       # the same board again
    win.add_folder(str(SHAPES))
    win.inspector.setup.solder_mask.setChecked(True)
    paths, _notes = win.write_mask_to(tmp_path)
    assert [p.name for p in paths] == ["buck_mask_mirrored.dxf",
                                       "shapes_mask_mirrored.dxf"]


def test_the_write_it_now_button_asks_where_and_writes(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win.inspector.setup.solder_mask.setChecked(True)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        lambda *a, **k: str(tmp_path))
    win.inspector.setup.mask_write_btn.click()
    assert (tmp_path / "buck_mask_mirrored.dxf").exists()
    assert not list(tmp_path.glob("*.nc"))          # the laser file and nothing else


def test_changing_the_mirror_forgets_what_was_written(win, tmp_path):
    win.inspector.setup.solder_mask.setChecked(True)
    win.write_mask_to(tmp_path)
    assert "buck_mask_mirrored.dxf" in win.mask_status()[1]
    win.inspector.setup.mirror.setChecked(False)
    status = win.mask_status()[1]
    assert "buck_mask_mirrored.dxf" not in status and "Not mirrored" in status


def test_the_setup_file_keeps_it(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    setup = win.inspector.setup
    setup.solder_mask.setChecked(True)
    setup.mask_shrink.setValue(0.15)
    path = tmp_path / "job.srmcam"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(path), ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(path), ""))
    win.action_save_setup()
    setup.solder_mask.setChecked(False)
    setup.mask_shrink.setValue(0.1)
    win.action_load_setup()
    assert setup.solder_mask.isChecked()
    assert setup.mask_shrink.value() == pytest.approx(0.15)
