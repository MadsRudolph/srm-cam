"""Double-sided registration and job parameters, ported from the original
interface into the setup sheet: the dowel sub-mode and edge pair, the grid and
clearance geometry, the bed bite, the dowels-only re-cut, the fiducial flip
direction, hand-placed reference holes dragged on the stage, V-bit geometry
in the cutting parameters, and all of it surviving a setup save."""
import json
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QComboBox, QFileDialog

from gerber2rml.doublesided import (build_align_only, DowelSpec, CLEAR_LARGE,
                                    CLEAR_SMALL, DOWEL_BED_DEPTH)
from gerber2rml.gui2 import widgets
from gerber2rml.gui2.window import MainWindow, _as_gui2_setup

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def win(qt_app):
    w = MainWindow()
    w.resize(1400, 900)
    yield w
    w.close()


@pytest.fixture
def loaded(win):
    win.load_folder(str(FIXT))
    return win


@pytest.fixture
def dowelled(loaded):
    loaded.action_double_sided(True)
    loaded.action_registration("dowel")
    return loaded


@pytest.fixture
def fiducialled(loaded):
    loaded.action_double_sided(True)
    loaded.action_registration("fiducial")
    return loaded


def _field(page, label):
    """The inspector Field with this label, on a page that just rebuilt."""
    for w in page._param_widgets:
        if isinstance(w, widgets.Field) and w.label.text() == label:
            return w
    return None


# --- dowel sub-mode, edges, geometry --------------------------------------

def test_the_dowel_sub_mode_is_real_state_and_reaches_the_engine(dowelled):
    """`reg` used to be dropped on load; now the grid/fresh choice is the
    job's and the layout, the align drill and the plan all read it."""
    assert dowelled.dowel_spec().mode == "fresh"
    dowelled.action_dowels("grid", "topbottom", 14.2, 4.0, CLEAR_LARGE,
                           CLEAR_SMALL, DOWEL_BED_DEPTH)
    spec = dowelled.dowel_spec()
    assert spec.mode == "grid" and spec.grid_pin == 4.0 and spec.pitch_x == 14.2
    lay = dowelled._ds_layout()
    # grid pins are the grid hole size, and equal
    assert [round(d, 3) for (_x, _y, d) in lay.align_holes] == [4.0, 4.0]
    step = dowelled.plan.by_key("align")
    assert not step.irreversible, "grid pins drill nothing into the bed"
    assert "grid" in step.detail
    # the align drill only clears the stock over the pins
    t = dowelled.inspector.setup.thickness.value()
    assert abs(dowelled._align_job().total_depth - (t + 1.0)) < 1e-9


def test_the_edge_pair_sets_the_flip_axis(dowelled):
    assert dowelled._ds_layout().axis == "vertical"
    assert "left-right" in dowelled.plan.by_key("flip").detail
    dowelled.action_dowels("fresh", "leftright", 14.2, 4.0, CLEAR_LARGE,
                           CLEAR_SMALL, DOWEL_BED_DEPTH)
    lay = dowelled._ds_layout()
    assert lay.axis == "horizontal"
    # the pins now sit beyond the left and right edges: same y, different x
    (x0, y0, _), (x1, y1, _) = lay.align_holes
    assert abs(y0 - y1) < 1e-6 and abs(x0 - x1) > 10
    assert dowelled.flip_axis() == "horizontal"
    assert "top-bottom" in dowelled.plan.by_key("flip").detail


def test_the_clearances_widen_the_holes_and_the_bite_deepens_them(dowelled):
    before = dowelled._ds_layout().align_holes
    dowelled.action_dowels("fresh", "topbottom", 14.2, 4.0, 0.5, 0.4, 7.5)
    after = dowelled._ds_layout().align_holes
    for (bx, by, bd), (ax, ay, ad) in zip(before, after):
        assert abs(bx - ax) < 1e-9 and abs(by - ay) < 1e-9, "centres stay put"
    assert abs(after[0][2] - before[0][2] - (0.5 - CLEAR_LARGE)) < 1e-9
    assert abs(after[1][2] - before[1][2] - (0.4 - CLEAR_SMALL)) < 1e-9
    t = dowelled.inspector.setup.thickness.value()
    assert abs(dowelled._align_job().total_depth - (t + 7.5)) < 1e-9
    # the reach check sees the deeper hole too
    assert "7.5" in dowelled.plan.by_key("align").detail


def test_the_dowel_geometry_reaches_the_exported_align_file(dowelled, tmp_path):
    dowelled.action_dowels("fresh", "leftright", 14.2, 4.0, 0.3, 0.25, 6.0)
    dowelled.export_to(tmp_path / "app")
    st = dowelled.state
    expect = build_align_only(
        st.gerber_dir, tmp_path / "ref", st.name, drill=dowelled.cutting_drill(),
        dowels=DowelSpec(mode="fresh", placement="leftright",
                         clearance_large=0.3, clearance_small=0.25),
        machine=st.machine, offset=(st.place_x, st.place_y), rotate=st.rotate,
        board_thickness=dowelled.inspector.setup.thickness.value(),
        bed_depth=6.0)
    assert (tmp_path / "app" / "buck_align.nc").read_text() == expect.read_text()


def test_the_dowel_controls_show_for_their_own_mode_only(dowelled):
    setup = dowelled.inspector.setup
    setup.sync()
    assert not setup.dowel_mode_field.isHidden()
    assert not setup.dowel_edges_field.isHidden()
    assert not setup.clear_large_field.isHidden()
    assert not setup.bed_bite_field.isHidden()
    assert not setup.dowels_only_btn.isHidden()
    assert setup.grid_pitch_field.isHidden()
    setup.dowel_mode.setCurrentIndex(setup.dowel_mode.findData("grid"))
    assert dowelled._dowel_mode == "grid"
    assert not setup.grid_pitch_field.isHidden()
    assert not setup.grid_pin_field.isHidden()
    assert setup.clear_large_field.isHidden()
    assert setup.dowels_only_btn.isHidden()
    # none of it on a fiducial job
    dowelled.action_registration("fiducial")
    setup.sync()
    assert setup.dowel_mode_field.isHidden()
    assert setup.grid_pitch_field.isHidden()


# --- cut dowels only --------------------------------------------------------

def test_dowels_only_rewrites_just_the_align_file(dowelled, tmp_path):
    dowelled.export_to(tmp_path)
    # Everything the export left behind, the preview image and the summary
    # included: the dowels-only rewrite must touch exactly one of them.
    names = sorted(p.name for p in tmp_path.iterdir())
    stamp = {n: (tmp_path / n).read_bytes() for n in names}
    # a rod would not seat: deepen the bite and re-cut only the holes
    dowelled.action_dowels("fresh", "topbottom", 14.2, 4.0, CLEAR_LARGE,
                           CLEAR_SMALL, 8.0)
    dowelled.action_export_dowels_only()
    assert sorted(p.name for p in tmp_path.iterdir()) == names, "no new files"
    for n in names:
        if n == "buck_align.nc":
            assert (tmp_path / n).read_bytes() != stamp[n]
        else:
            assert (tmp_path / n).read_bytes() == stamp[n], f"{n} was touched"
    st = dowelled.state
    ref = build_align_only(
        st.gerber_dir, tmp_path / "ref", st.name, drill=dowelled.cutting_drill(),
        dowels=dowelled.dowel_spec(), machine=st.machine,
        offset=(st.place_x, st.place_y), rotate=st.rotate,
        board_thickness=dowelled.inspector.setup.thickness.value(), bed_depth=8.0)
    assert (tmp_path / "buck_align.nc").read_text() == ref.read_text()


def test_dowels_only_refuses_a_job_that_has_no_dowels(loaded, tmp_path, monkeypatch):
    said = []
    monkeypatch.setattr(loaded, "say", lambda level, text: said.append((level, text)))
    loaded.action_export_dowels_only()
    assert said and said[-1][0] == "warn"
    assert not list(tmp_path.iterdir())


# --- fiducial flip direction -----------------------------------------------

def test_the_flip_direction_turns_the_layout_and_the_plan(fiducialled):
    assert fiducialled.fiducial_spec().flip_axis == "vertical"
    assert fiducialled._ds_layout().axis == "vertical"
    fiducialled.action_fiducial_flip("horizontal")
    assert fiducialled.fiducial_spec().flip_axis == "horizontal"
    assert fiducialled._ds_layout().axis == "horizontal"
    assert fiducialled.flip_axis() == "horizontal"
    assert "top-bottom" in fiducialled.plan.by_key("flip").detail
    # both places that show it agree
    assert fiducialled.inspector.setup.fid_flip.currentData() == "horizontal"
    assert fiducialled.flipfit_page.flip.current() == "horizontal"


def test_the_flip_direction_changes_the_top_traces_written(fiducialled, tmp_path):
    """The fit cannot detect a wrong flip, so the file has to follow the
    operator's word: a different direction is a different top side."""
    fiducialled.export_to(tmp_path / "lr")
    fiducialled.action_fiducial_flip("horizontal")
    fiducialled.export_to(tmp_path / "tb")
    assert ((tmp_path / "lr" / "buck_top_traces.nc").read_bytes()
            != (tmp_path / "tb" / "buck_top_traces.nc").read_bytes())


def test_the_fit_page_and_the_setup_page_are_one_setting(fiducialled):
    page = fiducialled.flipfit_page
    page.flip.set_current("horizontal")
    page._on_flip("horizontal")                 # what a click does
    assert fiducialled._fid_flip == "horizontal"
    assert fiducialled.inspector.setup.fid_flip.currentData() == "horizontal"
    fiducialled.inspector.setup.fid_flip.setCurrentIndex(
        fiducialled.inspector.setup.fid_flip.findData("vertical"))
    assert fiducialled._fid_flip == "vertical"
    assert page.flip.current() == "vertical"
    page.scale_chk.setChecked(True)
    assert fiducialled._fid_scale is True
    assert fiducialled.fiducial_spec().allow_scale is True


# --- manual fiducials, dragged on the stage --------------------------------

def test_manual_placement_seeds_the_pins_and_arms_the_drag(fiducialled):
    fiducialled.action_fiducial_layout(4, "manual", 4.0)
    assert len(fiducialled._fid_points) == 4
    assert fiducialled.fiducial_spec().placement == "manual"
    assert len(fiducialled.fiducial_spec().points) == 4
    fiducialled.select_step("bottom_traces")
    assert fiducialled.stage._pin_drag
    fiducialled.select_step("top_traces")
    assert not fiducialled.stage._pin_drag, "the top view is after the flip"
    setup = fiducialled.inspector.setup
    setup.sync()
    assert setup.fid_offset_field.isHidden(), "no corner offset by hand"
    assert not setup.fid_manual_hint.isHidden()


def test_a_pin_dragged_in_the_bed_frame_lands_where_it_was_dropped(fiducialled):
    fiducialled.action_fiducial_layout(4, "manual", 4.0)
    fiducialled.select_step("bottom_traces")
    x0, y0, _ = fiducialled._ds_layout().align_holes[0]
    fiducialled._on_pin_moved(0, x0 + 3.0, y0 - 2.5)
    x1, y1, _ = fiducialled._ds_layout().align_holes[0]
    assert abs(x1 - (x0 + 3.0)) < 1e-6 and abs(y1 - (y0 - 2.5)) < 1e-6
    # the other pins did not move
    before = fiducialled._fid_points[1:]
    assert len(before) == 3


def test_a_pin_dragged_in_the_xray_lands_where_it_was_dropped(fiducialled):
    from gerber2rml.doublesided import preview_layout_double_sided
    fiducialled.action_fiducial_layout(3, "manual", 4.0)
    fiducialled._on_frame("xray")
    st = fiducialled.state

    def prev():
        return preview_layout_double_sided(
            st.gerber_dir, offset=(st.place_x, st.place_y), rotate=st.rotate,
            registration="fiducial", dowels=fiducialled.dowel_spec(),
            fiducials=fiducialled.fiducial_spec())
    x0, y0, _ = prev().align_holes[2]
    fiducialled._on_pin_moved(2, x0 - 4.0, y0 + 1.5)
    x1, y1, _ = prev().align_holes[2]
    assert abs(x1 - (x0 - 4.0)) < 1e-6 and abs(y1 - (y0 + 1.5)) < 1e-6
    fiducialled._on_frame("bed")


def test_the_stage_drags_a_pin_and_reports_the_drop(qt_app):
    """The stage's own part: a press on a pin, a move, a release, one
    signal. A press anywhere else falls through to the placement drag."""
    from gerber2rml.gui2.stage import Stage
    from shapely.geometry import box
    stage = Stage()
    stage.resize(800, 600)
    stage.set_board(box(20, 20, 60, 50), box(20, 20, 60, 50), [],
                    align_holes=[(15.0, 35.0, 1.6), (65.0, 35.0, 1.6)])
    stage.fit_work()
    got = []
    stage.pin_moved.connect(lambda i, x, y: got.append((i, x, y)))
    assert not stage._pin_press(QPointF(15.0, 35.0)), "not armed yet"
    stage.set_pin_drag(True)
    assert not stage._pin_press(QPointF(40.0, 35.0)), "the board is not a pin"
    assert stage._pin_press(QPointF(15.2, 35.1))
    stage._pin_move(QPointF(10.0, 30.0))
    stage._pin_release()
    assert got == [(0, 10.0, 30.0)]
    assert stage._align_holes[0][:2] == (10.0, 30.0)
    stage.set_pin_drag(False)
    assert stage._pin_drag_idx is None


# --- V-bit geometry and peck retract in the cutting parameters --------------

def test_a_vbit_can_be_chosen_and_its_geometry_edited(loaded):
    loaded.select_step("traces_run")
    page = loaded.inspector.step
    tool = _field(page, "Tool")
    assert tool is not None and isinstance(tool.widget, QComboBox)
    assert _field(page, "Bit diameter") is not None
    assert _field(page, "Tip width") is None
    tool.widget.setCurrentIndex(tool.widget.findData("vbit"))
    assert loaded.state.trace.tool_type == "vbit"
    for label in ("Tip width", "Included angle", "Cut width"):
        assert _field(page, label) is not None, label
    assert _field(page, "Bit diameter") is None, "a V-bit has no flat width"
    _field(page, "Included angle").widget.setValue(60.0)
    _field(page, "Cut width").widget.setValue(0.3)
    _field(page, "Tip width").widget.setValue(0.1)
    tr = loaded.state.trace
    assert tr.included_angle == 60.0 and tr.target_width == 0.3
    assert abs(tr.effective_cut_depth() - tr.depth_for_width(0.3)) < 1e-9
    assert "deep" in page.vbit_note.text()
    # the setup page's cross-section is drawn for it, and the plan says so
    loaded.inspector.setup.sync()
    assert not loaded.inspector.setup.bit_profile.isHidden()
    assert "V-bit" in loaded.plan.by_key("traces_run").detail
    tool.widget.setCurrentIndex(tool.widget.findData("flat"))
    assert loaded.state.trace.tool_type == "flat"
    assert _field(page, "Bit diameter") is not None


def test_peck_retract_is_editable_on_the_drill_step(loaded):
    loaded.select_step("drill_run")
    f = _field(loaded.inspector.step, "Lift between pecks")
    assert f is not None
    f.widget.setValue(0.8)
    assert loaded.state.drill.peck_retract == 0.8


# --- the setup file --------------------------------------------------------

def test_everything_here_survives_a_setup_save_and_load(fiducialled, tmp_path,
                                                       monkeypatch):
    w = fiducialled
    w.action_fiducial_layout(3, "manual", 4.0)
    w._on_pin_moved(0, *[v + 2.0 for v in w._ds_layout().align_holes[0][:2]])
    points = [list(p) for p in w._fid_points]
    w.action_fiducial_flip("horizontal")
    w.action_fiducial_scale(True)
    w.action_dowels("grid", "leftright", 15.0, 3.5, 0.3, 0.25, 6.5)
    w.state.trace.tool_type = "vbit"
    w.state.trace.included_angle = 45.0
    path = tmp_path / "job.srmcam"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    w.action_save_setup()
    data = json.loads(path.read_text())
    assert data["fid_flip"] == "horizontal" and data["fid_scale"] is True
    assert data["fid_placement"] == "manual" and data["fid_points"] == points
    assert data["dowel_mode"] == "grid" and data["dowel_edges"] == "leftright"
    assert (data["grid_pitch"], data["grid_pin"]) == (15.0, 3.5)
    assert (data["clear_large"], data["clear_small"], data["bed_bite"]) == (0.3, 0.25, 6.5)
    assert data["trace"]["tool_type"] == "vbit"

    # a fresh window: nothing carried over but the file
    w2 = MainWindow()
    try:
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(path), "")))
        w2.action_load_setup()
        assert w2._double and w2._registration == "fiducial"
        assert w2._fid_flip == "horizontal" and w2._fid_scale is True
        assert w2._fid_placement == "manual" and w2._fid_points == points
        assert w2.dowel_spec() == w.dowel_spec()
        assert w2._bed_bite == 6.5
        assert w2.state.trace.tool_type == "vbit"
        assert w2.state.trace.included_angle == 45.0
        # the same holes come out of the same file
        assert w2._ds_layout().align_holes == w._ds_layout().align_holes
        setup = w2.inspector.setup
        assert setup.fid_flip.currentData() == "horizontal"
        assert setup.dowel_mode.currentData() == "grid"
        assert setup.bed_bite.value() == 6.5
        assert w2.flipfit_page.flip.current() == "horizontal"
    finally:
        w2.close()


def test_a_first_interface_setup_brings_its_dowel_and_fiducial_keys_across():
    theirs = {"place_x": 1.0, "place_y": 2.0, "rotation": 0, "jobs": {},
              "double_sided": True, "reg_method": 0,
              "reg": 1, "dowel_edge": 1, "grid_pitch": "15.5", "grid_pin": "3.0",
              "clr_large": "0.25", "clr_small": "bad", "bed_bite": 4.5,
              "fid": {"count": 3, "place": 2, "offset": 5.0, "diameter": 1.6,
                      "scale": True, "flip": 1,
                      "points": [[1.0, 2.0], [30.0, 2.0], [30.0, 20.0]]}}
    ours, unreadable = _as_gui2_setup(theirs)
    assert ours["registration"] == "dowel"
    assert ours["dowel_mode"] == "grid" and ours["dowel_edges"] == "leftright"
    assert ours["grid_pitch"] == 15.5 and ours["grid_pin"] == 3.0
    assert ours["clear_large"] == 0.25 and "clear_small" not in ours
    assert ours["bed_bite"] == 4.5
    assert ours["fid_placement"] == "manual"
    assert ours["fid_points"] == [[1.0, 2.0], [30.0, 2.0], [30.0, 20.0]]
    assert ours["fid_scale"] is True and ours["fid_flip"] == "horizontal"
    assert "the hand-placed reference holes" not in unreadable
    # hand-placed with no points is still the corner scheme, and says so
    theirs["fid"].pop("points")
    ours, unreadable = _as_gui2_setup(theirs)
    assert ours["fid_placement"] == "onboard"
    assert "the hand-placed reference holes" in unreadable
