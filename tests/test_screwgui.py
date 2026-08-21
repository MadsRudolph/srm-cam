"""Screw fixture in the GUI: automatic travel height, overlay, export.

The test that matters most here is
:func:`test_screws_raise_travel_z_on_every_operation`. Screw heads stand 3 mm
above the copper and the default travel height is 2 mm, so without that raise
the spindle drives into a screw on the first rapid — with correct XY, correct
depths and a correct-looking preview. Nothing geometric catches it, because the
screws are not in the geometry.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import matplotlib
matplotlib.use("Agg")
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from gerber2rml.engine import spoilboard as sb
from gerber2rml.gui.app import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"
_app = QApplication.instance() or QApplication([])


def _win(monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    w = MainWindow()
    w.load_folder(str(FIXT))
    return w


# ---- the automatic travel height ------------------------------------------

def test_screws_raise_travel_z_on_every_operation(monkeypatch):
    w = _win(monkeypatch)
    w.screws_chk.setChecked(False)
    w._sync_state()
    assert w.state.trace.travel_z == pytest.approx(2.0)   # the default

    w.screws_chk.setChecked(True)
    w._sync_state()
    need = sb.min_travel_z()
    for job in (w.state.trace, w.state.drill, w.state.cutout):
        assert job.travel_z >= need, "a rapid at this height would hit a screw"
    assert need > sb.M4_HEAD_H
    w.close()


def test_travel_z_is_only_ever_raised(monkeypatch):
    """Someone who deliberately set a higher travel keeps it."""
    from dataclasses import replace
    w = _win(monkeypatch)
    w.screws_chk.setChecked(True)
    w._sync_state()
    w.state.trace = replace(w.state.trace, travel_z=9.0)
    w._apply_screw_travel_z()
    assert w.state.trace.travel_z == pytest.approx(9.0)
    w.close()


def test_unticking_restores_the_form_values(monkeypatch):
    w = _win(monkeypatch)
    w.screws_chk.setChecked(True)
    w._sync_state()
    assert w.state.trace.travel_z >= sb.min_travel_z()
    w.screws_chk.setChecked(False)
    w._sync_state()
    assert w.state.trace.travel_z == pytest.approx(2.0)
    w.close()


def test_export_path_gets_the_raised_travel_z(monkeypatch, tmp_path):
    """The raise lives in _sync_state so every path inherits it. This checks
    the one that actually drives the machine."""
    w = _win(monkeypatch)
    w.screws_chk.setChecked(True)
    written = w.export_to(tmp_path)
    nc = [p for p in written if p.name.endswith("_traces.nc")][0]
    zs = []
    for line in nc.read_text(encoding="utf-8").splitlines():
        if line.startswith("G0 Z"):
            zs.append(float(line[4:].rstrip(".") or "0"))
    assert zs, "no rapid Z moves found"
    assert max(zs) >= sb.M4_HEAD_H, "no rapid ever clears a screw head"
    w.close()


# ---- picking and showing the positions ------------------------------------

def test_screw_overlay_appears_and_clears(monkeypatch):
    w = _win(monkeypatch)
    w.stock_x_spin.setValue(30.0); w.stock_y_spin.setValue(30.0)
    w.stock_w_spin.setValue(100.0); w.stock_h_spin.setValue(75.0)
    w.screws_chk.setChecked(True)
    w._update_screw_overlay()
    assert w.preview._screws is not None
    pts, head_d = w.preview._screws
    assert head_d == sb.M4_HEAD_D
    w.screws_chk.setChecked(False)
    w._update_screw_overlay()
    assert w.preview._screws is None
    w.close()


def test_hiding_the_stock_outline_does_not_hide_the_screws(monkeypatch):
    """They follow the copper but are not part of its outline — hiding the
    outline must not hide where the machine is about to drill."""
    w = _win(monkeypatch)
    w.stock_x_spin.setValue(30.0); w.stock_y_spin.setValue(30.0)
    w.stock_w_spin.setValue(100.0); w.stock_h_spin.setValue(75.0)
    w.screws_chk.setChecked(True)
    w.stock_show_chk.setChecked(False)
    w._update_stock_preview()
    assert w.preview._stock is None
    assert w.preview._screws is not None
    w.close()


def test_screws_land_on_real_grid_holes(monkeypatch):
    w = _win(monkeypatch)
    w.stock_x_spin.setValue(30.0); w.stock_y_spin.setValue(30.0)
    w.stock_w_spin.setValue(100.0); w.stock_h_spin.setValue(75.0)
    centres = {(round(x, 2), round(y, 2))
               for (_i, _j, x, y) in sb.measured_grid().holes()}
    for x, y in w._screw_points():
        assert (round(x, 2), round(y, 2)) in centres
    w.close()


# ---- pre-flight ------------------------------------------------------------

def test_diagnostics_flags_a_travel_height_that_would_hit_a_screw(monkeypatch):
    from dataclasses import replace
    w = _win(monkeypatch)
    w.screws_chk.setChecked(True)
    w._sync_state()
    w.state.trace = replace(w.state.trace, travel_z=2.0)   # forced back down
    checks = w._screw_checks()
    bad = [c for c in checks if c.level == "fail"]
    assert bad, "diagnostics missed a spindle-into-screw collision"
    assert any("screw" in c.detail.lower() for c in bad)
    w.close()


def test_diagnostics_passes_when_travel_is_clear(monkeypatch):
    """Copper genuinely bigger than the 104 mm board, so there is room around
    it for four well-spread screws. A 100 x 75 piece under a 104 mm design is
    not a passing case - and diagnostics saying so is the point."""
    w = _win(monkeypatch)
    w.stock_x_spin.setValue(0.0); w.stock_y_spin.setValue(0.0)
    w.stock_w_spin.setValue(150.0); w.stock_h_spin.setValue(130.0)
    w.screws_chk.setChecked(True)
    w._sync_state()
    checks = w._screw_checks()
    assert checks and all(c.level == "ok" for c in checks), \
        [(c.level, c.title, c.detail) for c in checks]
    w.close()


def test_no_screw_checks_when_the_copper_is_not_screwed_down(monkeypatch):
    w = _win(monkeypatch)
    w.screws_chk.setChecked(False)
    assert w._screw_checks() == []
    w.close()


def test_export_refuses_without_a_board(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    w = MainWindow()                       # no board loaded
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[1]))
    w.state.board = None
    w._on_export_screw_fixture()
    assert shown
    w.close()


def test_ticking_with_no_copper_size_explains_itself(monkeypatch):
    """Stock size defaults to 0 x 0, so the box can be ticked with nowhere to
    put a screw. Saying nothing at that point is the confusing outcome."""
    w = _win(monkeypatch)
    w.stock_w_spin.setValue(0.0); w.stock_h_spin.setValue(0.0)
    w.screws_chk.setChecked(True)
    assert w._screw_points() == []
    assert "Size" in w.statusBar().currentMessage()
    w.close()


def test_diagnostics_warns_when_the_screws_cannot_hold_it_flat(monkeypatch):
    """Copper barely larger than the design leaves only a strip clear, so the
    four screws end up in a line. The count looks fine; the clamp is a hinge."""
    w = _win(monkeypatch)
    w.stock_x_spin.setValue(30.0); w.stock_y_spin.setValue(30.0)
    w.stock_w_spin.setValue(100.0); w.stock_h_spin.setValue(75.0)
    w.screws_chk.setChecked(True)
    w._sync_state()
    warns = [c for c in w._screw_checks() if c.level == "warn"]
    assert any("pivot" in c.detail for c in warns),         [(c.level, c.title) for c in w._screw_checks()]
    w.close()


# ---- choosing the holes by hand -------------------------------------------

def _big_copper(w):
    w.stock_x_spin.setValue(0.0); w.stock_y_spin.setValue(0.0)
    w.stock_w_spin.setValue(150.0); w.stock_h_spin.setValue(130.0)


def test_first_click_edits_the_suggestion_rather_than_clearing_it(monkeypatch):
    """Wanting to move one screw must not mean placing all four by hand."""
    w = _win(monkeypatch); _big_copper(w)
    w.screws_chk.setChecked(True)
    auto = list(w._screw_points())
    assert len(auto) == 4

    g = sb.measured_grid()
    hx, hy = g.centre(2, 2)                    # a hole not in the auto set
    w._on_screw_pick(hx + 1.0, hy - 1.0)       # click near it, not dead centre
    picked = w._screw_points()
    assert len(picked) == len(auto) + 1
    assert all(a in picked for a in auto), "the suggestion was thrown away"
    w.close()


def test_clicking_a_chosen_hole_removes_it(monkeypatch):
    w = _win(monkeypatch); _big_copper(w)
    w.screws_chk.setChecked(True)
    auto = list(w._screw_points())
    target = auto[0]
    w._on_screw_pick(target[0] + 0.5, target[1])
    assert target not in w._screw_points()
    assert len(w._screw_points()) == len(auto) - 1
    w.close()


def test_clicks_snap_to_the_grid(monkeypatch):
    """A screw must land on a hole; a click near one means that hole."""
    w = _win(monkeypatch); _big_copper(w)
    g = sb.measured_grid()
    hx, hy = g.centre(4, 4)
    w._on_screw_pick(hx + 2.0, hy + 2.0)
    centres = {(round(x, 2), round(y, 2))
               for j in range(g.ny) for i in range(g.nx)
               for x, y in [g.centre(i, j)]}
    for x, y in w._screw_points():
        assert (round(x, 2), round(y, 2)) in centres
    w.close()


def test_a_click_with_no_hole_near_it_is_ignored(monkeypatch):
    """Snapping is forgiving but not unconditional. Note a click offset only
    in X always lands nearer the NEXT hole - at a 10 mm pitch the only points
    further than half a pitch from every centre are the diagonal middles, and
    anywhere off the plate."""
    w = _win(monkeypatch); _big_copper(w)
    w.screws_chk.setChecked(True)
    before = list(w._screw_points())
    g = sb.measured_grid()
    hx, hy = g.centre(4, 4)

    # dead centre of four holes: 7.07 mm from each, ambiguous, so ignored
    w._on_screw_pick(hx + g.pitch / 2.0, hy + g.pitch / 2.0)
    assert w._screw_points() == before

    # and well off the plate entirely
    w._on_screw_pick(400.0, 400.0)
    assert w._screw_points() == before
    w.close()


def test_auto_button_restores_the_automatic_choice(monkeypatch):
    w = _win(monkeypatch); _big_copper(w)
    w.screws_chk.setChecked(True)
    auto = list(w._screw_points())
    g = sb.measured_grid()
    w._on_screw_pick(*g.centre(2, 2))
    assert w._manual_screws is not None
    w._on_screws_auto()
    assert w._manual_screws is None
    assert w._screw_points() == auto
    w.close()


def test_hand_picked_holes_may_be_bad_but_are_reported(monkeypatch):
    """The operator can see the bed and may have a reason, so a questionable
    pick is reported rather than refused."""
    w = _win(monkeypatch); _big_copper(w)
    w.screws_chk.setChecked(True)
    w._sync_state()
    g = sb.measured_grid()
    under_design = g.centre(4, 4)              # the board sits over 2..106
    w._on_screw_pick(*under_design)
    assert under_design in w._screw_points(), "the pick was refused, not reported"
    warns = [c for c in w._screw_checks() if c.level == "warn"]
    assert any("Hand-picked" in c.title for c in warns),         [(c.level, c.title) for c in w._screw_checks()]
    w.close()


def test_picking_mode_arms_the_canvas(monkeypatch):
    w = _win(monkeypatch)
    w.screws_pick_chk.setChecked(True)
    assert w.preview._screw_pick is True
    assert w.screws_chk.isChecked(), "picking screw holes implies using screws"
    w.screws_pick_chk.setChecked(False)
    assert w.preview._screw_pick is False
    w.close()


# ---- the bed's own holes ---------------------------------------------------

def test_spoilboard_holes_are_drawn_with_the_bed(monkeypatch):
    w = _win(monkeypatch)
    w.show_bed_chk.setChecked(True)
    w.generate_preview()
    assert w.preview._hole_grid is not None
    pts, hole_d = w.preview._hole_grid
    assert hole_d == sb.HOLE_D
    assert len(pts) == sb.NX * sb.NY, "the whole plate, not just the usable subset"
    w.close()


def test_spoilboard_holes_hide_with_the_bed(monkeypatch):
    w = _win(monkeypatch)
    w.show_bed_chk.setChecked(False)
    w.generate_preview()
    assert w.preview._hole_grid is None
    w.close()


def test_screw_controls_are_available_in_novice(monkeypatch):
    """A student who screws the copper down without the raised travel height
    crashes the spindle - the checkbox is what prevents that, so hiding it
    would make Novice the more dangerous mode."""
    monkeypatch.setenv("SRM_CAM_MODE", "novice")
    w = MainWindow()
    w.show(); _app.processEvents()
    for widget in (w.screws_chk, w.screws_btn, w.screws_pick_chk,
                   w.screws_auto_btn):
        assert widget.isVisible(), widget
    w.close()


# ---- the cut-out pass runs OUTSIDE the outline ----------------------------

def test_keepout_extends_past_the_outline_by_the_cutout_bit(monkeypatch):
    """The cut path centreline sits at outline+bit_r and the cutter sweeps a
    further bit_r, so material comes out to a full bit diameter beyond the
    edge. A screw judged only against the outline can sit in that band."""
    w = _win(monkeypatch); _big_copper(w)
    outline = w._display_outline()
    keep = w._screw_keepout()
    bit = w.forms["cutout"].value().bit_diameter
    grew = outline.bounds[0] - keep.bounds[0]
    assert grew == pytest.approx(bit, abs=0.05)
    assert keep.contains(outline)
    w.close()


def test_a_screw_in_the_cutout_band_is_refused(monkeypatch):
    """With the standard 0.8 mm bit the band is narrower than the 10 mm grid,
    so no hole happens to fall in it. Widen the cut-out bit and one does — and
    that is precisely the screw the outline-only check would have accepted and
    the cutter would have hit."""
    from gerber2rml.engine.spoilboard import point_problem
    w = _win(monkeypatch); _big_copper(w)
    w.forms["cutout"].set_field_value("bit_diameter", 6.0)

    outline = w._display_outline()
    keep = w._screw_keepout()
    assert keep.area > outline.area

    # Past the outline by more than a head radius (4 mm), so the outline alone
    # clears it - but still inside the 6 mm band the cutter sweeps.
    x = outline.bounds[2] + 7.0
    y = (outline.bounds[1] + outline.bounds[3]) / 2.0
    stock = w._stock_rect()
    assert point_problem((x, y), stock, keepout=outline) is None,         "sanity: the outline alone would allow this screw"
    problem = point_problem((x, y), stock, keepout=keep)
    assert problem is not None and "cutter" in problem
    w.close()


# ---- screw placement survives save/load ------------------------------------

def test_screw_placement_is_saved_and_restored(monkeypatch, tmp_path):
    """Once the holes are drilled in a piece of copper they are a fact about
    it — and a hand-picked set cannot be recovered by re-running the automatic
    choice."""
    w = _win(monkeypatch); _big_copper(w)
    w.screws_chk.setChecked(True)
    g = sb.measured_grid()
    w._on_screw_pick(*g.centre(3, 3))
    picked = list(w._screw_points())
    assert w._manual_screws is not None

    setup = tmp_path / "s.json"
    w._write_setup(setup)
    w.close()

    w2 = _win(monkeypatch)
    import json
    w2._apply_setup(json.loads(setup.read_text(encoding="utf-8")),
                    session_dir=tmp_path)
    assert w2.screws_chk.isChecked()
    assert w2._manual_screws is not None
    assert [tuple(p) for p in w2._screw_points()] == [tuple(p) for p in picked]
    w2.close()


def test_automatic_choice_stays_automatic_across_save_load(monkeypatch, tmp_path):
    """An untouched setup must keep tracking the design if it moves later, so
    the automatic case is stored as null rather than frozen into a list."""
    import json
    w = _win(monkeypatch); _big_copper(w)
    w.screws_chk.setChecked(True)
    assert w._manual_screws is None

    setup = tmp_path / "auto.json"
    w._write_setup(setup)
    d = json.loads(setup.read_text(encoding="utf-8"))
    assert d["screws"]["manual"] is None
    assert d["screws"]["on"] is True
    w.close()

    w2 = _win(monkeypatch)
    w2._apply_setup(d, session_dir=tmp_path)
    assert w2._manual_screws is None
    w2.close()


def test_old_setups_without_screws_still_load(monkeypatch):
    """Setups written before this feature have no 'screws' key at all."""
    w = _win(monkeypatch)
    w._apply_setup({"name": "old"})
    assert w._manual_screws is None
    assert not w.screws_chk.isChecked()
    w.close()


# ---- all three passes, exactly --------------------------------------------

def test_every_pass_is_checked_against_the_screw_heads(monkeypatch):
    """Traces and drill sit inside the outline today, so the cheap keep-out
    covers them - but that is an assumption about the isolation engine, not a
    fact about screws. Pre-flight checks each pass's real swept material."""
    w = _win(monkeypatch); _big_copper(w)
    w.screws_chk.setChecked(True)
    w._sync_state()
    sweeps = w._pass_sweeps()
    assert set(sweeps) == {"traces", "drill", "cutout"}
    assert all(g is not None for g in sweeps.values()), sweeps

    checks = w._screw_toolpath_check(w._screw_points())
    assert len(checks) == 1
    assert checks[0].level == "ok"
    for op in ("traces", "drill", "cutout"):
        assert op in checks[0].detail, "a pass was silently not checked"
    w.close()


def test_a_screw_in_a_toolpath_is_caught_even_if_hand_picked(monkeypatch):
    """The case the outline proxy would miss if a pass ever left the outline -
    and the case a hand-picked hole creates today."""
    w = _win(monkeypatch); _big_copper(w)
    w.screws_chk.setChecked(True)
    w._sync_state()
    g = sb.measured_grid()
    w._manual_screws = [g.centre(4, 4)]        # squarely under the board
    checks = w._screw_toolpath_check(w._screw_points())
    assert checks[0].level == "fail"
    assert "would hit the screw" in checks[0].detail
    w.close()


def test_toolpath_check_is_silent_without_screws(monkeypatch):
    w = _win(monkeypatch)
    assert w._screw_toolpath_check([]) == []
    w.close()


def test_vbit_width_is_used_rather_than_the_shank(monkeypatch):
    """A V-bit's cut width grows with depth, so the swept material is wider
    than the tool's nominal diameter. Asking the job keeps that honest."""
    w = _win(monkeypatch); _big_copper(w)
    w.forms["traces"].set_field_value("tool_type", "vbit")
    w._sync_state()
    job = w._job_for_op("traces")
    assert hasattr(job, "effective_diameter")
    assert job.effective_diameter() != job.bit_diameter
    assert w._pass_sweeps()["traces"] is not None
    w.close()

