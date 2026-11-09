"""The laser file for silkscreen.

What it has to get right: every loop closed and the sizes real, in a file read
back the way a laser's software would read it; the top face as KiCad drew it,
not mirrored, whatever the copper does; artwork past the board edge cut off and
said out loud; a missing layer a sentence and not a crash. And the app: off by
default, in both tiers, and never at the cost of the machine files.

Fixtures: ``mosfet_test`` (buck) is a real board with a populated F.Silkscreen
and no B.Silkscreen. The preload example plots an empty B.Silkscreen.
"""
import math
from pathlib import Path

import pytest
from gerbonara import GerberFile
from shapely.affinity import translate
from shapely.geometry import Polygon

from gerber2rml.engine import silkscreen as ss
from gerber2rml.engine import soldermask as sm
from gerber2rml.loader import _find_layer

from test_soldermask import header_value, loops, read_dxf

FIXTURES = Path(__file__).parent / "fixtures"
BUCK = FIXTURES / "mosfet_test"
BOOST = FIXTURES.parent.parent / "examples" / "preload_example"
CALIB = FIXTURES.parent.parent / "examples" / "calibration"


def _copy(folder, dest, *suffixes, rename=None):
    dest.mkdir(parents=True, exist_ok=True)
    for p in Path(folder).iterdir():
        if p.name.endswith(suffixes):
            name = p.name
            for a, b in (rename or {}).items():
                name = name.replace(a, b)
            (dest / name).write_bytes(p.read_bytes())
    return dest


def _kicad_frame(folder, side="top"):
    """The silkscreen as plotted, and the outline's lower-left corner, in
    KiCad's own frame: what the file must equal once moved to the origin."""
    drawn = sm._layer_to_shapely(GerberFile.open(str(ss.silk_layer_path(folder, side))))
    outline = sm._read_outline(_find_layer(folder, "*-Edge_Cuts.*", "*.gm1"))
    return drawn, outline


# ---------------------------------------------------------------- the file

def test_every_loop_in_the_file_is_closed(tmp_path):
    path = ss.write_silk_files(BUCK, tmp_path, "buck")[0][0]
    ents = read_dxf(path)
    assert ents and all(e["type"] == "LWPOLYLINE" for e in ents)
    for e in ents:
        assert e["70"] == "1"
        assert e["pts"][0] == e["pts"][-1]
        assert int(e["90"]) == len(e["pts"])
        assert Polygon(e["pts"]).is_valid


def test_the_file_is_millimetres_with_two_named_layers(tmp_path):
    path = ss.write_silk_files(BUCK, tmp_path, "buck")[0][0]
    assert header_value(path, "$INSUNITS") == "4"
    assert header_value(path, "$MEASUREMENT") == "1"
    assert {e["8"] for e in read_dxf(path)} == {ss.LAYER_SILK, ss.LAYER_OUTLINE}
    colours = {e["8"]: e["62"] for e in read_dxf(path)}
    assert colours[ss.LAYER_SILK] != colours[ss.LAYER_OUTLINE]
    assert len(loops(path, ss.LAYER_OUTLINE)) == 1


def test_the_file_name_says_the_face_and_the_mirroring(tmp_path):
    path = ss.write_silk_files(BUCK, tmp_path, "buck")[0][0]
    assert path.name == "buck_silk_top_not_mirrored.dxf"


def test_the_artwork_is_all_there_and_where_kicad_put_it():
    """Same area, same place: the file is the plot, moved to the origin and
    not mirrored. Letters with holes keep them."""
    art = ss.build_silk(BUCK)
    drawn, outline = _kicad_frame(BUCK)
    assert not art.mirrored
    x0, y0, *_ = outline.bounds
    moved = translate(drawn, -x0, -y0)
    got = sum(p.area for p in art.shapes)
    assert got == pytest.approx(drawn.area, rel=1e-6)
    assert art.shapes and all(moved.buffer(1e-6).contains(p) for p in art.shapes)
    assert any(p.interiors for p in art.shapes)


def test_the_outline_starts_at_the_origin_and_holds_the_artwork():
    art = ss.build_silk(BUCK)
    x0, y0, *_ = art.outline.bounds
    assert (x0, y0) == pytest.approx((0, 0), abs=1e-9)
    for p in art.shapes:
        assert art.outline.buffer(1e-6).contains(p)
    assert art.warnings() == []


def test_the_top_is_never_mirrored_and_the_bottom_is():
    top = ss.build_silk(BUCK)
    flipped = ss.build_silk(BUCK, mirror=True)
    w = top.outline.bounds[2]
    want = sorted((round(w - p.centroid.x, 3), round(p.centroid.y, 3))
                  for p in top.shapes)
    got = sorted((round(p.centroid.x, 3), round(p.centroid.y, 3))
                 for p in flipped.shapes)
    assert got == pytest.approx(want, abs=2e-3)


# ---------------------------------------------------------- double-sided

def test_a_double_sided_job_without_bottom_silk_gets_the_top_alone(tmp_path):
    done = ss.write_silk_files(BUCK, tmp_path, "buck", double_sided=True)
    assert [p.name for p, _ in done] == ["buck_silk_top_not_mirrored.dxf"]
    # An empty B.Silkscreen, as the example plots, is skipped the same way.
    done = ss.write_silk_files(BOOST, tmp_path, "boost", double_sided=True)
    assert [p.name for p, _ in done] == ["boost_silk_top_not_mirrored.dxf"]


def test_a_double_sided_job_with_bottom_silk_gets_it_mirrored(tmp_path):
    src = _copy(BUCK, tmp_path / "src", "-Edge_Cuts.gm1", "-F_Silkscreen.gto")
    (src / "buck-B_Silkscreen.gbo").write_bytes(
        (BUCK / "buck-F_Silkscreen.gto").read_bytes())
    done = ss.write_silk_files(src, tmp_path / "out", "buck", double_sided=True)
    assert [p.name for p, _ in done] == ["buck_silk_top_not_mirrored.dxf",
                                         "buck_silk_bottom_mirrored.dxf"]
    top, bottom = (a for _, a in done)
    assert bottom.mirrored and not top.mirrored
    # A single-sided job never writes the bottom, even when it is there.
    single = ss.write_silk_files(src, tmp_path / "one", "buck")
    assert len(single) == 1


# ----------------------------------------------------------- missing layers

def test_no_silk_layer_is_a_sentence_saying_what_to_do(tmp_path):
    folder = _copy(BUCK, tmp_path, "-Edge_Cuts.gm1", "-B_Cu.gbl")
    with pytest.raises(ss.SilkError) as e:
        ss.build_silk(folder)
    said = str(e.value)
    assert "F.Silkscreen" in said and "Plot" in said and str(folder) in said


def test_no_outline_is_a_sentence_too(tmp_path):
    folder = _copy(BUCK, tmp_path, "-F_Silkscreen.gto")
    with pytest.raises(ss.SilkError, match="Edge.Cuts"):
        ss.build_silk(folder)


def test_an_empty_silk_layer_is_not_an_empty_file(tmp_path):
    folder = _copy(CALIB, tmp_path, "-Edge_Cuts.gbr", "-F_Silkscreen.gbr")
    with pytest.raises(ss.SilkError, match="empty"):
        ss.write_silk_files(folder, tmp_path, "calib")
    assert not list(tmp_path.glob("*.dxf"))


# -------------------------------------------------------- hand-written Gerbers

EDGE = """%FSLAX46Y46*%
%MOMM*%
%ADD10C,0.1*%
D10*
X0Y0D02*
X20000000Y0D01*
X20000000Y20000000D01*
X0Y20000000D01*
X0Y0D01*
M02*
"""

SILK = """%FSLAX46Y46*%
%MOMM*%
%ADD10C,1.0*%
D10*
X{x0}Y{y}D02*
X{x1}Y{y}D01*
M02*
"""


def test_artwork_past_the_edge_is_cut_off_and_said(tmp_path):
    """A 1 mm line from x=15 to x=25 on a 20 mm board: half of it is air."""
    (tmp_path / "e-Edge_Cuts.gbr").write_text(EDGE)
    (tmp_path / "e-F_Silkscreen.gbr").write_text(
        SILK.format(x0="15000000", x1="25000000", y="10000000"))
    art = ss.build_silk(tmp_path)
    assert art.outline.bounds[2] == pytest.approx(20, abs=1e-6)
    assert max(p.bounds[2] for p in art.shapes) == pytest.approx(20, abs=1e-6)
    assert art.clipped_mm2 == pytest.approx(5 + math.pi / 8, abs=0.01)
    said = " ".join(art.warnings())
    assert "board edge" in said and "F.Silkscreen" in said


def test_artwork_wholly_off_the_board_is_refused(tmp_path):
    (tmp_path / "e-Edge_Cuts.gbr").write_text(EDGE)
    (tmp_path / "e-F_Silkscreen.gbr").write_text(
        SILK.format(x0="30000000", x1="40000000", y="10000000"))
    with pytest.raises(ss.SilkError, match="outside the board"):
        ss.build_silk(tmp_path)


def test_a_stroked_square_keeps_its_hole(tmp_path):
    """Like the inside of an O: a loop of its own, so the fill leaves it bare."""
    (tmp_path / "s-Edge_Cuts.gbr").write_text(EDGE)
    (tmp_path / "s-F_Silkscreen.gbr").write_text("""%FSLAX46Y46*%
%MOMM*%
%ADD10C,0.5*%
D10*
X5000000Y5000000D02*
X15000000Y5000000D01*
X15000000Y15000000D01*
X5000000Y15000000D01*
X5000000Y5000000D01*
M02*
""")
    art = ss.build_silk(tmp_path)
    assert len(art.shapes) == 1 and len(art.shapes[0].interiors) == 1
    path = ss.write_silk_dxf(art, tmp_path, "s")
    assert len(loops(path, ss.LAYER_SILK)) == 2


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
    assert not win.inspector.setup.silkscreen.isChecked()
    win.export_to(tmp_path)
    assert not list(tmp_path.glob("*.dxf"))
    assert "silkscreen" not in win.sheet.text()


def test_ticked_the_export_writes_it_beside_the_machine_files(win, tmp_path):
    win.inspector.setup.silkscreen.setChecked(True)
    written = win.export_to(tmp_path)
    assert written and all(Path(p).exists() for p in written)
    path = tmp_path / "buck_silk_top_not_mirrored.dxf"
    assert path.exists() and loops(path, ss.LAYER_SILK)
    assert win.exported_path(path.name) == path
    assert path.name in win.sheet.text()
    assert path.name in win.silk_status()[1]


def test_both_laser_files_together(win, tmp_path):
    win.inspector.setup.solder_mask.setChecked(True)
    win.inspector.setup.silkscreen.setChecked(True)
    win.export_to(tmp_path)
    assert {p.name for p in tmp_path.glob("*.dxf")} == {
        "buck_mask_mirrored.dxf", "buck_silk_top_not_mirrored.dxf"}
    text = win.sheet.text()
    assert "solder mask" in text and "silkscreen" in text


def test_the_machine_files_do_not_change_with_it(win, tmp_path):
    a, b = tmp_path / "off", tmp_path / "on"
    win.export_to(a)
    win.inspector.setup.silkscreen.setChecked(True)
    win.export_to(b)
    names = {p.name for p in b.iterdir()} - {"buck_silk_top_not_mirrored.dxf"}
    assert names == {p.name for p in a.iterdir()}
    for n in names:
        if n.endswith(".nc"):
            assert (a / n).read_bytes() == (b / n).read_bytes(), n


def test_mirror_off_does_not_change_the_silkscreen(win, tmp_path):
    win.inspector.setup.silkscreen.setChecked(True)
    win.inspector.setup.mirror.setChecked(False)
    paths, _notes = win.write_silk_to(tmp_path)
    assert [p.name for p in paths] == ["buck_silk_top_not_mirrored.dxf"]


def test_a_folder_with_no_silk_says_so_and_the_machine_files_still_come(
        qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    src = tmp_path / "src"
    src.mkdir()
    for p in BUCK.iterdir():
        if "Silkscreen" not in p.name:
            (src / p.name).write_bytes(p.read_bytes())
    w = MainWindow()
    try:
        w.load_folder(str(src))
        setup = w.inspector.setup
        setup.silkscreen.setChecked(True)
        level, text = w.silk_status()
        assert level == "warn" and "F.Silkscreen" in text
        assert "F.Silkscreen" in setup.silk_note.text()
        out = tmp_path / "out"
        written = w.export_to(out)
        assert written and any(p.suffix == ".nc" for p in map(Path, written))
        assert not list(out.glob("*.dxf"))
        assert "No F.Silkscreen" in w.sheet.text()
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
        assert not setup.silk_section.isHidden()
        assert setup.silk_write_btn.isHidden()
        setup.silkscreen.setChecked(True)
        assert not setup.silk_write_btn.isHidden()
    finally:
        w.close()


def test_a_panel_gets_one_file_per_board_and_one_for_a_repeat(win, tmp_path):
    win.add_folder(str(BUCK))
    win.add_folder(str(BOOST))
    win.inspector.setup.silkscreen.setChecked(True)
    paths, _notes = win.write_silk_to(tmp_path)
    assert [p.name for p in paths] == ["buck_silk_top_not_mirrored.dxf",
                                       "boost_v2_silk_top_not_mirrored.dxf"]


def test_the_write_it_now_button_asks_where_and_writes(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win.inspector.setup.silkscreen.setChecked(True)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        lambda *a, **k: str(tmp_path))
    win.inspector.setup.silk_write_btn.click()
    assert (tmp_path / "buck_silk_top_not_mirrored.dxf").exists()
    assert not list(tmp_path.glob("*.nc"))


def test_the_setup_file_keeps_it(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    setup = win.inspector.setup
    setup.silkscreen.setChecked(True)
    path = tmp_path / "job.srmcam"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(path), ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(path), ""))
    win.action_save_setup()
    setup.silkscreen.setChecked(False)
    win.action_load_setup()
    assert setup.silkscreen.isChecked()
