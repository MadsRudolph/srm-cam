"""Run it, in the bracket: the board goes into the bracket's corner by
itself (Novice), snaps back into it when dragged near, and Reset position
puts it there."""
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from gerber2rml.engine import bracket as br
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def novice(qt_app, monkeypatch, tmp_path):
    from gerber2rml import platform as plat
    monkeypatch.setattr(plat, "documents_dir", lambda *a, **k: tmp_path)
    monkeypatch.setenv("SRM_CAM_MODE", "novice")
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    # The bracket's place and "centre" are saved settings, shared with every
    # other test that touches them: say what these tests assume.
    w.autorun_page.centre_chk.setChecked(False)
    w.autorun_page.set_bracket(br.DEFAULT)
    yield w
    w.close()


def _target(w):
    p = w.autorun_page
    return br.corner_place(extent=w.work_extent(), **p._corner_args())


def test_a_new_board_lands_in_the_corner_when_run_it_opens(novice):
    w = novice
    w.load_folder(str(FIXT))
    w.autorun_page.w_spin.setValue(150)
    w.autorun_page.h_spin.setValue(130)
    w.select_step("autorun")
    b = w.work_extent()
    assert (b[0], b[1]) == pytest.approx(_target(w))
    sx, sy, sw, sh = w.stock
    assert sx <= b[0] and b[2] <= sx + sw and sy <= b[1] and b[3] <= sy + sh


def test_dragged_away_it_stays_and_reset_brings_it_back(novice):
    w = novice
    w.load_folder(str(FIXT))
    w.autorun_page.w_spin.setValue(150)
    w.autorun_page.h_spin.setValue(130)
    w.select_step("autorun")
    w._on_drag(-10.0, -8.0)
    b = w.work_extent()
    assert (b[0], b[1]) != pytest.approx(_target(w))
    w.autorun_page._sync_outline()               # a resync does not undo it
    assert w.work_extent()[0] == pytest.approx(b[0])
    w.autorun_page.reset_position()
    b = w.work_extent()
    assert (b[0], b[1]) == pytest.approx(_target(w))


def test_the_stage_snaps_a_drag_near_the_corner(novice):
    w = novice
    w.load_folder(str(FIXT))
    w.autorun_page.w_spin.setValue(150)
    w.autorun_page.h_spin.setValue(130)
    w.select_step("autorun")
    snap = w.stage._place_snap
    assert snap is not None
    assert snap(1.5, -2.0) == pytest.approx((0.0, 0.0))
    assert snap(-20.0, -20.0) == pytest.approx((-20.0, -20.0))


def test_single_sided_is_remembered_for_the_board_folder(novice, tmp_path):
    """F.Cu is also where people draw wire links. Unticked once, a board
    sent from KiCad again must not come back double-sided."""
    import shutil
    from gerber2rml.gui2 import workspace
    w = novice
    w.remember_board_choices = True              # as the app sets it
    folder = tmp_path / "srm-cam"
    shutil.copytree(FIXT, folder)
    w.load_folder(str(folder))
    w._detect_sides()
    detected = w._double
    key = w._sides_key()
    try:
        assert workspace.setting(key, "") in ("", None)   # a guess is not a choice
        w.inspector.setup.double.setChecked(not detected)  # the operator's word
        w.load_folder(str(folder))
        w._detect_sides()
        assert w._double is (not detected)
    finally:
        workspace._settings().remove(key)
        workspace._settings().remove(w._refs_key())


def test_reference_holes_inside_the_corners_shrink_what_must_fit(novice):
    w = novice
    w.load_folder(str(FIXT))
    w.inspector.setup.double.setChecked(True)
    w.select_step("autorun")
    p = w.autorun_page
    assert p.ref_row.isVisible() and p.ref_box.currentData() == "waste"
    outside = w.work_extent()
    p.ref_box.setCurrentIndex(p.ref_box.findData("onboard"))
    assert w._fid_placement == "onboard"
    inside = w.work_extent()
    assert inside[2] - inside[0] < outside[2] - outside[0]
    assert inside == pytest.approx(w.work_bounds())    # only the board now
    p.ref_box.setCurrentIndex(p.ref_box.findData("waste"))
    assert w._fid_placement == "waste"
    w.inspector.setup.double.setChecked(False)
    p._sync_outline()
    assert not p.ref_row.isVisible()                   # single-sided: none


def test_the_marks_of_a_double_sided_board_are_on_the_board(novice):
    """The double-sided layout moves the board over for its reference holes.
    The X of a short and the red of a narrow gap have to move with it: they
    used to be worked out on the unmoved board and land beside it."""
    from shapely.geometry import Point
    w = novice
    w.load_folder(str(FIXT))                  # 13 shorts, with pads as boxes
    for double in (False, True):
        w.inspector.setup.double.setChecked(double)
        w.refresh_checks()
        copper = w._cut_copper()
        assert len(w._shorts) == 13
        for s in w._shorts:
            pt = Point(s["x"], s["y"])
            assert not copper.contains(pt)                 # in the gap...
            assert copper.distance(pt) < 0.45              # ...between two nets
        x0, y0, x1, y1 = w.work_bounds()
        gx0, gy0, gx1, gy1 = w._gaps.bounds
        assert x0 <= gx0 and gx1 <= x1 and y0 <= gy0 and gy1 <= y1
    lay = w._ds_layout()
    assert lay.bottom_copper.bounds != pytest.approx(
        w.state.board.copper.bounds)          # the layout really did move it


def test_in_novice_the_sheet_the_bracket_and_the_board_are_there_at_import(
        novice):
    """Novice's stock is always in the bracket, so the L, the sheet in it
    and the board on the sheet are the picture from the moment a board is
    loaded - not first on Run it."""
    w = novice
    w.autorun_page.w_spin.setValue(150)
    w.autorun_page.h_spin.setValue(130)
    assert w.open_from_outside(str(FIXT))              # as the KiCad button
    assert w.traveller.current() == "setup"            # still on Your board
    x, y, corner = w.autorun_page.datum()
    sx, sy, sw, sh = w.stock
    assert (sx + sw, sy + sh) == pytest.approx((x, y))  # back-right in the L
    b = w.work_extent()
    assert (b[0], b[1]) == pytest.approx(_target(w))
    assert w.stage._bracket is not None                # drawn...
    assert w.stage._bracket[3] is None                 # ...but not draggable
    w.select_step("autorun")
    QApplication.processEvents()
    assert w.stage._bracket[3] is not None             # here it is
    w.select_step("checks")
    QApplication.processEvents()
    assert w.stage._bracket is not None and w.stage._bracket[3] is None


def test_in_pro_loading_a_board_leaves_the_sheet_alone(qt_app, monkeypatch,
                                                       tmp_path):
    from gerber2rml import platform as plat
    monkeypatch.setattr(plat, "documents_dir", lambda *a, **k: tmp_path)
    w = MainWindow()                                   # the suite pins Pro
    w.show()
    stock = tuple(w.stock)
    assert w.open_from_outside(str(FIXT))
    assert tuple(w.stock) == stock
    assert w.stage._bracket is None
    w.close()


def test_a_programmatic_load_keeps_the_placement_it_was_given(novice):
    """load_folder is what tests and setups call: it moves nothing, which is
    what keeps the two tiers' exports byte for byte the same."""
    w = novice
    stock = tuple(w.stock)
    w.load_folder(str(FIXT))
    assert tuple(w.stock) == stock
    assert w.stage._bracket is None
