"""No-go zones on the Run it page, and the copper check for a board left in
the sheet.

A zone is a clamp clicked on its bed hole, or a box dragged round anything
else. It lasts only as long as the session (the clamps come off with every
board), is drawn on the bed in its own layer, and is handed
to the run. The engine's side is in test_autorun_nogo.py."""
from pathlib import Path

import pytest

from gerber2rml.engine import bracket as br
from gerber2rml.gui2 import autorun as page_mod
from gerber2rml.gui2 import workspace
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def win(qt_app, monkeypatch, tmp_path):
    from gerber2rml import platform as plat
    monkeypatch.setattr(plat, "documents_dir", lambda *a, **k: tmp_path)
    workspace.set_setting("autorun/nogo", "")
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.action_autorun(True)               # Run it is opt-in outside Novice
    w.autorun_page.centre_chk.setChecked(False)
    w.autorun_page.set_bracket(br.DEFAULT)
    yield w
    w.autorun_page._clear_nogo()
    w.action_autorun(False)
    w.close()


def test_zones_survive_the_settings_string():
    zones = [(10.0, 20.0, 30.5, 40.25), (1.0, 2.0, 3.0, 4.0)]
    assert page_mod.nogo_from_text(page_mod.nogo_to_text(zones)) == zones
    assert page_mod.nogo_from_text("") == []
    # A mangled entry is dropped, not turned into a zone somewhere else.
    assert page_mod.nogo_from_text("1,2;5,6,7,8") == [(5.0, 6.0, 7.0, 8.0)]
    # Three numbers are a clamp: centre and diameter.
    assert page_mod.nogo_from_text("1,2,26") == [(1.0, 2.0, 26.0)]


def test_a_click_while_marking_puts_a_clamp_on_the_stock_edge(win):
    from gerber2rml.engine import nogo
    page = win.autorun_page
    page.nogo_btn.setChecked(True)
    from gerber2rml.engine import spoilboard
    # A bed hole 8 mm in front of the stock: the clamp's boss reaches it.
    # An outer-ring hole: drawn on the bed, though no bracket screw uses it.
    hx, hy = spoilboard.measured_grid().centre(8, 0)
    win.stock = (hx - 50.0, hy + 8.0, 100.0, 60.0)
    sx, sy, sw, sh = win.stock
    win.stage.box_clicked.emit(hx + 3.0, hy)      # near the screw
    (z,) = page.nogo()
    assert nogo.is_clamp(z) and z[2] == nogo.CLAMP_D_MM
    # In front of the sheet: turned clockwise onto it, so left of the screw.
    assert z[0] < hx and z[3:] == pytest.approx((hx, hy))
    assert z[1] + z[2] / 2 == pytest.approx(sy + nogo.CLAMP_LIP_MM, abs=0.01)
    assert win.stage._nogo == [z]
    assert win.stage.nogo_at((z[0], z[1])) == 0
    # Without the button lit a click is nothing.
    page.nogo_btn.setChecked(False)
    win.stage.box_clicked.emit(sx + 10, sy + 1.0)
    assert len(page.nogo()) == 1


def test_a_box_dragged_while_the_button_is_lit_becomes_a_zone(win):
    page = win.autorun_page
    assert page.nogo() == [] and not page.nogo_clear_btn.isEnabled()
    page.nogo_btn.setChecked(True)
    win._on_region(40.0, 30.0, 20.0, 10.0)        # dragged up and to the left
    assert page.nogo() == [(20.0, 10.0, 40.0, 30.0)]
    assert win.stage._nogo == [(20.0, 10.0, 40.0, 30.0)]
    assert "1 no-go zone" in page.nogo_lbl.text()
    # Not saved: the next session starts with none.
    assert workspace.setting("autorun/nogo", "") == ""


def test_a_box_dragged_without_the_button_is_not_a_zone(win):
    win._on_region(40.0, 30.0, 20.0, 10.0)
    assert win.autorun_page.nogo() == []


def test_a_click_makes_no_zone(win):
    page = win.autorun_page
    page.nogo_btn.setChecked(True)
    win._on_region(40.0, 30.0, 40.1, 30.1)
    assert page.nogo() == []


def test_the_zone_button_and_the_recut_boxes_are_never_both_lit(win):
    page = win.autorun_page
    page.box_btn.setChecked(True)
    page.nogo_btn.setChecked(True)
    assert not page.box_btn.isChecked()
    page.box_btn.setChecked(True)
    assert not page.nogo_btn.isChecked()


def test_clear_zones_empties_the_bed_and_the_setting(win):
    page = win.autorun_page
    page.add_nogo(20.0, 10.0, 40.0, 30.0)
    page._clear_nogo()
    assert page.nogo() == [] and win.stage._nogo == []
    assert workspace.setting("autorun/nogo", "") == ""


# --- left in the sheet: the outline may hang off the copper -------------------

def _copper_check(w):
    return [c for c in w._stock_checks()
            if "copper" in c.title and "reach" not in c.title]


def _load_with_a_margin(w):
    """The mosfet board with its copper kept 5 mm in from its outline (the
    fixture is poured to within half a millimetre of the edge all round,
    which is work at the edge and would prove nothing here)."""
    from shapely.geometry import box
    w.load_folder(str(FIXT))
    board = w.state.board
    o = board.outline.bounds
    board.copper = box(o[0] + 5, o[1] + 5, o[2] - 5, o[3] - 5)
    board.copper_top = None
    board.holes = [(o[0] + 8, o[1] + 8, 0.8)]
    w._paths_cache = {}
    w.autorun_page.w_spin.setValue(150)
    w.autorun_page.h_spin.setValue(130)
    w.select_step("autorun")


def _slide(w, dx, dy):
    """Move the board by exactly this much. Not a drag on the stage: near
    the bracket's corner a drag snaps back into it (3 mm), which is the
    page's business and not what these tests are about."""
    w.state.move_all(dx, dy)
    w._paths_cache = {}
    w.refresh_checks()


def _hang_outline_off(w):
    """The case from the mill: a board drawn bigger than the sheet (104 mm
    of outline on 100 mm of copper), slid so that what is cut - 94.8 mm of
    it - sits in the middle of the sheet. Its outline then hangs off front
    and back, and its work does not."""
    sx, sy, sw, sh = w.stock
    w.set_no_cutout(True)
    r = w.work_reach()
    _slide(w, sx + 1.0 - r[0], (sy + sh / 2.0) - (r[1] + r[3]) / 2.0)


def _off(box, stock):
    """How far ``box`` hangs off the sheet, at its worst."""
    sx, sy, sw, sh = stock
    return max(sx - box[0], sy - box[1], box[2] - (sx + sw), box[3] - (sy + sh))


def test_cut_out_an_outline_off_the_copper_is_an_error(win):
    w = win
    _load_with_a_margin(w)
    _hang_outline_off(w)
    w.set_no_cutout(False)
    assert _off(w.work_bounds(), w.stock) > 0.1
    # Over by more than the hair the sheet's own edge is allowed to be.
    assert [c.level for c in _copper_check(w)] in (["fail"], ["warn"])


def test_left_in_the_sheet_only_the_work_counts(win):
    w = win
    _load_with_a_margin(w)
    _hang_outline_off(w)
    assert _off(w.work_bounds(), w.stock) > 0.1     # the outline is off it
    assert _off(w.work_reach(), w.stock) < 0        # the work is not
    assert [c.level for c in _copper_check(w)] == ["ok"]


def test_left_in_the_sheet_copper_off_the_sheet_is_still_an_error(win):
    w = win
    _load_with_a_margin(w)
    w.set_no_cutout(True)
    sx, sy, sw, sh = w.stock
    r = w.work_reach()
    _slide(w, 0.0, (sy + sh + 3.0) - r[3])          # the WORK is 3 mm over
    assert _off(w.work_reach(), w.stock) > 0.5
    assert [c.level for c in _copper_check(w)] == ["fail"]


# --- how far in from the edge the surface is touched --------------------------

def test_the_levelling_margin_is_remembered_and_follows_the_tick(win):
    page = win.autorun_page
    assert page.level_margin_spin.value() >= 0.5
    page.level_margin_spin.setValue(12.0)
    assert workspace.setting("autorun/level_margin", "") == "12.0"
    page.level_chk.setChecked(False)
    assert not page.level_margin_spin.isEnabled()
    page.level_chk.setChecked(True)
    assert page.level_margin_spin.isEnabled()
    page.level_margin_spin.setValue(2.0)             # as other tests expect


# --- right-click a zone to delete it ------------------------------------------

def test_the_stage_knows_which_zone_is_under_a_point(win):
    page = win.autorun_page
    page.add_nogo(10.0, 10.0, 30.0, 30.0)
    page.add_nogo(20.0, 20.0, 50.0, 50.0)
    assert win.stage.nogo_at((12.0, 12.0)) == 0
    assert win.stage.nogo_at((25.0, 25.0)) == 1      # the one drawn last, on top
    assert win.stage.nogo_at((70.0, 70.0)) is None


def test_deleting_one_zone_leaves_the_others(win):
    page = win.autorun_page
    page.add_nogo(10.0, 10.0, 30.0, 30.0)
    page.add_nogo(60.0, 60.0, 80.0, 80.0)
    page.remove_nogo(0)
    assert page.nogo() == [(60.0, 60.0, 80.0, 80.0)]
    assert win.stage._nogo == [(60.0, 60.0, 80.0, 80.0)]
    page.remove_nogo(7)                              # a stale index: nothing
    assert len(page.nogo()) == 1


def test_a_right_click_on_a_zone_deletes_it_without_asking(win):
    page = win.autorun_page
    page.add_nogo(10.0, 10.0, 30.0, 30.0)
    page.add_nogo(60.0, 60.0, 80.0, 80.0)
    win.stage.nogo_picked.emit(0, None)
    assert page.nogo() == [(60.0, 60.0, 80.0, 80.0)]
    assert win.stage._nogo == [(60.0, 60.0, 80.0, 80.0)]


# --- the checks say when work lies in a zone ----------------------------------

def _nogo_check(w):
    return [c for c in w._nogo_checks()]


def test_with_no_zones_the_checks_say_nothing_about_them(win):
    _load_with_a_margin(win)
    assert _nogo_check(win) == []


def test_a_zone_over_copper_edges_or_a_hole_is_an_error(win):
    w = win
    _load_with_a_margin(w)
    b = w.work_bounds()
    # The hole is 8 mm in from the board's corner; so is this zone.
    w.autorun_page.add_nogo(b[0] + 6, b[1] + 6, b[0] + 10, b[1] + 10)
    c = _nogo_check(w)
    assert [x.level for x in c] == ["fail"]
    assert "1 hole" in c[0].detail and "bottom copper" in c[0].detail
    assert any(k.title == "Work lies in a no-go zone" for k in w._checks)


def test_a_zone_in_the_boards_margin_is_fine(win):
    """Copper starts 5 mm in from the outline; a clamp on the first
    millimetre of the board, 2 mm clear of it, cuts nothing."""
    w = win
    _load_with_a_margin(w)
    b = w.work_bounds()
    w.autorun_page.add_nogo(b[0] + 30, b[1] - 6, b[0] + 40, b[1] + 1.0)
    assert [x.level for x in _nogo_check(w)] == ["ok"]


def test_a_zone_wholly_inside_a_pour_cuts_nothing(win):
    """A cut runs along copper's edge. Under the middle of a pour there is
    none, and a clamp may sit there."""
    w = win
    _load_with_a_margin(w)
    b = w.work_bounds()
    w.autorun_page.add_nogo(b[0] + 40, b[1] + 40, b[0] + 50, b[1] + 50)
    assert [x.level for x in _nogo_check(w)] == ["ok"]


def test_left_in_the_sheet_copper_edges_in_a_zone_are_a_warning_not_an_error(win):
    """The run leaves that isolation uncut and proves it joins nothing; the
    check says so instead of forbidding it. A hole there is still an error."""
    w = win
    _load_with_a_margin(w)
    w.set_no_cutout(True)
    b = w.work_bounds()
    # Over the copper's edge (5 mm in), away from the hole (8 mm in).
    w.autorun_page.add_nogo(b[0] + 40, b[1] + 3, b[0] + 50, b[1] + 7)
    c = _nogo_check(w)
    assert [x.level for x in c] == ["warn"]
    assert "left uncut" in c[0].title
    w.autorun_page.add_nogo(b[0] + 6, b[1] + 6, b[0] + 10, b[1] + 10)
    assert sorted(x.level for x in _nogo_check(w)) == ["fail", "warn"]


def test_cut_out_copper_edges_in_a_zone_say_what_would_let_them_through(win):
    w = win
    _load_with_a_margin(w)
    w.set_no_cutout(False)
    b = w.work_bounds()
    w.autorun_page.add_nogo(b[0] + 40, b[1] + 3, b[0] + 50, b[1] + 7)
    c = _nogo_check(w)
    assert [x.level for x in c] == ["fail"]
    assert "Leave the board in the sheet" in c[0].detail


# --- the touches are drawn, and move ------------------------------------------

def _open_run_it(w):
    _load_with_a_margin(w)
    w.autorun_page.level_chk.setChecked(True)
    w.autorun_page.level_margin_spin.setValue(2.0)
    return w.autorun_page


def test_run_it_draws_the_twelve_touches_on_the_bed(win):
    page = _open_run_it(win)
    pts = page.touch_points()
    assert len(pts) == 12
    assert win.stage._probe == pts


def test_the_touches_move_in_when_the_margin_grows(win):
    page = _open_run_it(win)
    before = list(win.stage._probe)
    page.level_margin_spin.setValue(10.0)
    after = list(win.stage._probe)
    assert after != before and len(after) == 12
    assert min(x for x, _y in after) == pytest.approx(
        min(x for x, _y in before) + 8.0)
    page.level_margin_spin.setValue(2.0)


def test_a_touch_under_a_new_zone_moves_off_it_on_the_bed(win):
    page = _open_run_it(win)
    x, y = win.stage._probe[0]
    page.add_nogo(x - 3, y - 3, x + 3, y + 3)
    moved = win.stage._probe
    assert len(moved) == 12 and moved[0] != (x, y)
    mx, my = moved[0]
    g = 0.4 + 2.0
    assert not (x - 3 - g <= mx <= x + 3 + g and y - 3 - g <= my <= y + 3 + g)
    page._clear_nogo()
    assert win.stage._probe[0] == (x, y)


def test_with_levelling_off_no_touches_are_drawn(win):
    page = _open_run_it(win)
    page.level_chk.setChecked(False)
    assert win.stage._probe == []
    page.level_chk.setChecked(True)
    assert len(win.stage._probe) == 12


def test_leaving_run_it_gives_the_bed_its_other_points_back(win):
    w = win
    _load_with_a_margin(w)
    assert len(w.stage._probe) == 12
    w.select_step("checks")
    assert w.stage._probe == []


def test_the_level_page_has_the_same_margin_and_its_grid_follows(win):
    w = win
    _load_with_a_margin(w)
    w.autorun_page.level_margin_spin.setValue(6.0)
    w.select_step("level")
    lp = w.level_page
    assert lp.margin.value() == 6.0
    lp._build()
    # The grid is laid over the part of the board the machine can reach,
    # so its place is compared with itself: 3 mm more margin, 3 mm further in.
    x6 = min(x for x, _y in lp._points)
    y6 = min(y for _x, y in lp._points)
    lp.margin.setValue(9.0)                 # not measured yet: it moves
    assert min(x for x, _y in lp._points) == pytest.approx(x6 + 3.0)
    assert min(y for _x, y in lp._points) == pytest.approx(y6 + 3.0)
    assert workspace.setting("autorun/level_margin", "") == "9.0"
    lp.margin.setValue(2.0)


# --- left in the sheet, the board has no edge to isolate from -----------------

def _trace_cuts(w):
    paths = w._toolpaths_for(w.plan.by_key("traces_run"))[0]
    return [(m.x, m.y) for tp in paths for m in tp if not m.rapid and m.z < 0]


def _edge_gap(w):
    o = w.state.board.outline.bounds
    xs, ys = zip(*_trace_cuts(w))
    return min(min(xs) - o[0], min(ys) - o[1], o[2] - max(xs), o[3] - max(ys))


def test_cut_out_a_poured_board_is_isolated_right_up_to_its_edge(win):
    w = win
    w.load_folder(str(FIXT))
    w.select_step("autorun")
    w.set_no_cutout(False)
    assert _edge_gap(w) < 0.3                     # the pour's own outline
    assert w._edge_checks() == []


def test_left_in_the_sheet_the_edge_pass_is_gone_and_the_checks_say_so(win):
    w = win
    w.load_folder(str(FIXT))
    w.select_step("autorun")
    w.set_no_cutout(True)
    assert _edge_gap(w) > 0.8                     # nothing along the edge
    c = w._edge_checks()
    assert [x.level for x in c] == ["ok"]
    assert "left uncut" in c[0].title and "joins no" in c[0].detail
    # Back to cutting it out: the edge pass is back with it.
    w.set_no_cutout(False)
    assert _edge_gap(w) < 0.3


def test_an_edge_pass_that_would_join_nets_is_kept_and_said(win, monkeypatch):
    from gerber2rml.engine import bracket as br_mod
    w = win
    w.load_folder(str(FIXT))
    w.select_step("autorun")
    real = br_mod.joined_nets
    calls = []

    def fake(copper, nets, paths, sheet, radius):
        calls.append(1)
        # The whole pass keeps them apart; the trimmed one would not.
        return [] if len(calls) % 2 else [["GND", "+5V"]]

    monkeypatch.setattr(br_mod, "joined_nets", fake)
    w.set_no_cutout(True)
    assert _edge_gap(w) < 0.3                     # still cut
    c = w._edge_checks()
    assert [x.level for x in c] == ["warn"]
    assert "GND + +5V" in c[0].detail
    monkeypatch.setattr(br_mod, "joined_nets", real)
    w.set_no_cutout(False)


def test_a_clamp_on_the_edge_of_a_board_left_in_the_sheet_is_no_concern(win):
    """With the edge pass gone, a clamp on the board's edge has nothing
    under it: the check that warned about isolation there is satisfied."""
    w = win
    w.load_folder(str(FIXT))
    w.select_step("autorun")
    w.set_no_cutout(True)
    _trace_cuts(w)                                # the passes are made
    b = w.work_bounds()
    mid = (b[1] + b[3]) / 2.0
    w.autorun_page.add_nogo(b[0] - 8.0, mid - 4.0, b[0] - 1.5, mid + 4.0)
    assert [x.level for x in w._nogo_checks()] == ["ok"]


def test_the_checks_take_a_clamp_as_the_disc_it_is(win, qt_app):
    """A marked clamp is ``(cx, cy, d)``, not a box: the check that says
    which work lies in a zone read it as one and raised an IndexError."""
    win.load_folder(str(FIXT))
    win.select_step("autorun")
    page = win.autorun_page
    b = win.work_bounds()
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    page._nogo = [(cx, cy, 26.0)]
    page._save_nogo()                         # runs the checks: no error
    found = win._nogo_checks()
    assert found and "clamp 1" in found[0].detail
    page._nogo = [(b[2] + 60.0, b[3] + 60.0, 26.0)]   # nowhere near the work
    far = win._nogo_checks()
    assert [c.level for c in far] == ["ok"]
