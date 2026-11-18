"""The laser page stays responsive, lives in the main window, and undoes moves.

* The run-time estimate is worked out without writing the job file; the
  number is the one the full job gives.
* Ring rebuilds and estimates go to the thread pool; only the newest answer
  is shown, and a run waits for one still on its way.
* The page is a page of the main window, switched with the mill's page; it
  keeps its place and follows the board loaded there.
* Ctrl+Z / the Undo button put the job back where it was.
"""
from pathlib import Path
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtTest import QTest
from shapely.geometry import box

from gerber2rml.engine import xtool
from gerber2rml.gui2 import background

FIX = Path(__file__).parent / "fixtures"
BUCK = FIX / "mosfet_test"


@pytest.fixture
def sl(monkeypatch):
    from gerber2rml.gui2 import stencil_laser
    monkeypatch.setattr(stencil_laser, "_SETTINGS", ("SRM-CAM-tests", "laser-responsive"))
    return stencil_laser


def _small_art():
    return xtool.LaserArt(kind="mask", outline=box(0, 0, 20, 10),
                          apertures=[box(2, 2, 5, 5), box(8, 2, 12, 6)],
                          mirrored=False)


# ------------------------------------------------------------ the estimate

def test_the_estimate_is_the_full_jobs_time_without_the_file():
    art = xtool.build_laser_traces(BUCK, mirror=True)
    r = xtool.DEFAULT_TRACES_RECIPE
    full = xtool.traces_job(art, (40.0, 40.0), r)
    quick = xtool.traces_job(art, (40.0, 40.0), r, write=False)
    assert quick.text == "" and full.text
    assert quick.seconds == full.seconds and quick.timeline == full.timeline


def test_fill_and_stencil_estimates_match_their_jobs():
    shapes = [box(10, 10, 14, 13), box(20, 10, 23, 16)]
    fr = xtool.SPHAWES_REMOVE_MASK
    assert (xtool.fill_job(shapes, [], fr, write=False).seconds
            == xtool.fill_job(shapes, [], fr).seconds)
    holes = [list(s.exterior.coords) for s in shapes]
    outline = [[(5, 5), (40, 5), (40, 30), (5, 30), (5, 5)]]
    sr = xtool.DEFAULT_RECIPE
    a = xtool.stencil_job(holes, outline, sr, write=False)
    b = xtool.stencil_job(holes, outline, sr)
    assert a.text == "" and a.seconds == b.seconds and a.zones == b.zones


# ------------------------------------------------------------ the thread pool

def _settle(latest):
    latest.wait()
    QCoreApplication.processEvents()


def test_only_the_newest_answer_is_delivered(qt_app, monkeypatch):
    monkeypatch.setattr(background, "INLINE", False)
    got = []
    latest = background.Latest()
    gate = threading.Event()

    def slow():
        gate.wait(5)
        return "old"
    latest.run("x", slow, done=got.append)
    latest.run("x", lambda: "new", done=got.append)
    gate.set()
    _settle(latest)
    assert got == ["new"]
    assert not latest.busy()


def test_a_burst_of_edits_is_worked_out_once(qt_app, monkeypatch):
    monkeypatch.setattr(background, "INLINE", False)
    calls, got = [], []
    latest = background.Latest()
    for k in range(5):
        latest.later("est", 200, lambda k=k: calls.append(k) or k, done=got.append)
    assert latest.pending("est") and not calls
    _settle(latest)
    assert calls == [4] and got == [4]


def test_a_failure_goes_to_failed_on_the_gui_thread(qt_app, monkeypatch):
    monkeypatch.setattr(background, "INLINE", False)
    seen = []
    latest = background.Latest()

    def boom():
        raise ValueError("nope")
    latest.run("x", boom, done=lambda r: seen.append(("done", r)),
               failed=lambda e: seen.append((
                   "failed", str(e),
                   threading.current_thread() is threading.main_thread())))
    _settle(latest)
    assert seen == [("failed", "nope", True)]


def test_ring_count_edits_never_block_and_a_cut_waits_for_them(qt_app, sl, monkeypatch):
    monkeypatch.setattr(background, "INLINE", False)
    art = xtool.build_laser_traces(BUCK, mirror=True)
    d = sl.StencilLaserDialog(art)
    try:
        d._sums.wait()
        before = d.base_art.apertures
        t = time.perf_counter()
        for n in (5, 4, 3):
            d.offsets.setValue(n)
        assert time.perf_counter() - t < 0.5        # nothing worked out yet
        assert d.base_art.apertures is before       # the old trenches stay up
        assert d._sums.pending("rings")
        d._settle()                                  # what a run does first
        QCoreApplication.processEvents()
        assert d.base_art.apertures is not before
        assert d.base_art.note.startswith("3 passes")
    finally:
        d._sums.wait()
        d.close()


# ------------------------------------------------------------ undo

def test_a_drag_a_turn_and_a_nudge_are_undone_in_turn(qt_app, sl):
    d = sl.StencilLaserDialog(_small_art())
    try:
        d.x.setValue(50)
        d.y.setValue(50)
        d.undo.clear()
        assert not d.undo_btn.isEnabled()
        start = d._place()
        for k in range(5):                    # one drag, many moves
            d.item.setPos(60 + k, 70)
        d._drag_done()
        dragged = d._place()
        assert d.undo_btn.isEnabled()
        d.rotate(1)
        turned = d._place()
        d._nudge(1, 0)
        d._nudge(1, 0)                        # nudges in a row: one step
        d.undo_place()
        assert d._place() == turned
        d.undo_place()
        assert d._place() == dragged and d.turns == 0
        d.undo_place()
        assert d._place() == start
        assert (d.item.pos().x(), d.item.pos().y()) == (50, 50)
        assert not d.undo_btn.isEnabled() and d.redo_btn.isEnabled()
        d.redo_place()
        assert d._place() == dragged
    finally:
        d.close()


def test_a_typed_position_is_one_step_back(qt_app, sl):
    d = sl.StencilLaserDialog(_small_art())
    try:
        d.x.setValue(30)
        d.y.setValue(30)
        d.undo.clear()
        d.undo.break_merge()
        d.x.setValue(80)
        assert d._place()[0] == 80
        d.undo_place()
        assert d._place()[:2] == (30, 30)
    finally:
        d.close()


def test_ctrl_z_on_the_bed_undoes_a_move(qt_app, sl):
    d = sl.StencilLaserDialog(_small_art())
    try:
        d.show()
        d.x.setValue(40)
        d.y.setValue(40)
        d.undo.clear()
        d.view.setFocus()
        QCoreApplication.processEvents()
        d._nudge(10, 0)
        assert d._place()[0] == 50
        QTest.keyClick(d.view, Qt.Key_Z, Qt.ControlModifier)
        assert d._place()[0] == 40
        QTest.keyClick(d.view, Qt.Key_Y, Qt.ControlModifier)
        assert d._place()[0] == 50
    finally:
        d.close()


# ------------------------------------------------------------ in the main window

def test_the_laser_is_a_page_of_the_main_window(qt_app, sl, monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    try:
        w.load_folder(str(BUCK))
        assert w.mode() == "cnc" and w.laser_view is None
        w.show_mode("laser")
        d = w.laser_view
        assert d is not None and d.embedded and not d.isWindow()
        assert w.modes.currentWidget() is d
        assert all(wdg.isHidden() for wdg in w._cnc_header)
        d.x.setValue(42)
        d.rotate(1)
        # Escape on the page closes nothing
        d.reject()
        assert w.modes.currentWidget() is d
        w.show_mode("cnc")
        assert w.modes.currentWidget() is w.cnc_body
        assert not w.frame_switch.isHidden()
        w.show_mode("laser")
        assert w.laser_view is d                      # the same page, as left
        assert d.x.value() == pytest.approx(42) and d.turns == 1
    finally:
        w.close()


def test_the_laser_page_follows_the_board_loaded(qt_app, sl, monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    try:
        w.show_mode("laser")
        d = w.laser_view
        assert d._empty                               # nothing loaded yet
        w.show_mode("cnc")
        w.load_folder(str(BUCK))
        w.show_mode("laser")
        assert w.laser_view is d and not d._empty
        assert d.kind == "traces" and d.name_lbl.text()
        w.action_mask_laser()
        assert d.kind == "mask" and w.mode() == "laser"
    finally:
        w.close()


def test_the_main_window_will_not_close_under_a_running_laser(qt_app, sl, monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    try:
        w.load_folder(str(BUCK))
        w.show_mode("laser")
        w.show_mode("cnc")
        monkeypatch.setattr(w.laser_view, "_worker_running", lambda: True)
        w.show()
        w.close()
        assert w.isVisible() and w.mode() == "laser"
        assert "STOP" in w.laser_view.status.text()
    finally:
        monkeypatch.setattr(w.laser_view, "_worker_running", lambda: False)
        w.close()


def test_ctrl_z_belongs_to_the_page_that_is_up(qt_app, sl, monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    try:
        w.show()
        w.load_folder(str(BUCK))
        w.placement_undo.push(w.placement_snapshot())
        assert w.undo_act.isEnabled()
        w.show_mode("laser")
        d = w.laser_view
        assert not w.undo_act.isEnabled() and not w.redo_act.isEnabled()
        d.x.setValue(40)
        d.undo.clear()
        d.view.setFocus()
        QCoreApplication.processEvents()
        d._nudge(10, 0)
        w.activateWindow()                      # shortcuts go to the active window
        QTest.qWaitForWindowActive(w)
        d.view.setFocus()
        QTest.keyClick(d.view, Qt.Key_Z, Qt.ControlModifier)
        assert d.x.value() == pytest.approx(40)
        # loading on the mill side while the laser is up does not take it back
        w.placement_undo.clear()
        w.placement_undo.push(w.placement_snapshot())
        assert not w.undo_act.isEnabled()
        w.show_mode("cnc")
        assert w.undo_act.isEnabled()
    finally:
        w.close()


# ------------------------------------------------------------ undo of everything else

def _rect(x0, y0, x1, y1):
    from PySide6.QtCore import QRectF
    return QRectF(x0, y0, x1 - x0, y1 - y0)


def test_laser_rework_boxes_skips_points_and_mirror_are_undone(qt_app, sl):
    art = xtool.build_laser_traces(BUCK, mirror=True)
    d = sl.StencilLaserDialog(art)
    try:
        d.x.setValue(40)
        d.y.setValue(40)
        d.undo.clear()
        # a rework box, then clicking it away
        d._rework_boxed(_rect(50, 50, 60, 60))
        assert len(d.rework_boxes) == 1
        d._rework_boxed(_rect(55, 55, 55, 55))
        assert d.rework_boxes == []
        d.undo_place()
        assert len(d.rework_boxes) == 1
        d.undo_place()
        assert d.rework_boxes == []
        d.redo_place()
        assert len(d.rework_boxes) == 1
        # a skipped trench
        before = set(d.skipped)
        d._skip_boxed(_rect(40, 40, 140, 140))
        assert d.skipped != before
        d.undo_place()
        assert d.skipped == before
        # the automatic skips turned off
        d.skip_auto.setChecked(not d.skip_auto.isChecked())
        d.undo_place()
        assert d.skipped == before
        # an alignment point pair
        d._reference_pairs.clear()
        d._remember_edit()
        d._reference_pairs.append(((1.0, 2.0), (41.0, 42.0)))
        d.undo_place()
        assert d._reference_pairs == []
        # the mirror
        was = d.base_art.mirrored
        d.mirror_box.setChecked(not d.mirror_box.isChecked())
        assert d.base_art.mirrored != was
        d.undo_place()
        assert d.base_art.mirrored == was and d.mirror_box.isChecked() == was
    finally:
        d.close()


def test_undone_skips_never_land_on_other_trenches(qt_app, sl):
    art = xtool.build_laser_traces(BUCK, mirror=True)
    d = sl.StencilLaserDialog(art)
    try:
        d.x.setValue(40)
        d.y.setValue(40)
        d.undo.clear()
        d._skip_boxed(_rect(40, 40, 140, 140))
        d.offsets.setValue(3)                   # new trenches, numbered afresh
        fresh = set(d.skipped)
        d.undo_place()                          # the skip step
        assert d.skipped == fresh
    finally:
        d.close()


def test_the_mills_boxes_zones_clamps_and_screws_are_undone(qt_app, sl, monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    try:
        w.load_folder(str(BUCK))
        w.placement_undo.clear()
        rw, ar = w.rework_page, w.autorun_page
        rw.add_region(10, 10, 20, 20)
        rw.add_region(30, 10, 40, 20)
        assert len(rw._regions) == 2
        w.action_undo()
        assert len(rw._regions) == 1
        rw._clear()
        assert rw._regions == []
        w.action_undo()
        assert len(rw._regions) == 1
        ar.add_nogo(50, 50, 60, 60)
        assert len(ar._nogo) == 1
        w.action_undo()
        assert ar._nogo == []
        w.action_redo()
        assert len(ar._nogo) == 1
        ar.add_box(5, 5, 9, 9)
        w.action_undo()
        assert ar._boxes == []
        screws = w._manual_screws
        w._on_screw_click(*w._auto_screws()[0]) if w._auto_screws() else None
        if w._auto_screws():
            assert w._manual_screws != screws
            w.action_undo()
            assert w._manual_screws == screws
        # a move is still undone with the rest
        x0 = w.state.place_x
        w.action_place(x0 + 5, w.state.place_y)
        w.action_undo()
        assert w.state.place_x == pytest.approx(x0)
        assert len(rw._regions) == 1 and len(ar._nogo) == 1
    finally:
        w.close()


def test_drill_centres_are_etched_only_while_the_holes_are_not_drilled(
        qt_app, sl, monkeypatch):
    """A mark to drill by: off on a laser board, whose holes the mill drills
    first; on while nothing has drilled them; a tick by hand stays."""
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    try:
        w.load_folder(str(BUCK))
        w.action_method("mill_flat", quiet=True)
        w.show_mode("laser")
        d = w.laser_view
        d.switch_kind("traces")
        assert d.holes_drilled() is False and d.spot_drills.isChecked()
        w.action_method("laser", quiet=True)
        d._sync_spot_drills()
        assert d.holes_drilled() is True and not d.spot_drills.isChecked()
        d.spot_drills.click()                         # by hand: it stays
        d._sync_spot_drills()
        assert d.spot_drills.isChecked()
    finally:
        w.close()
