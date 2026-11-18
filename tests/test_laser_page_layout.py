"""The laser page as a page of the main window, beside its rail.

* It fits a 1366 px laptop screen next to the 316 px rail: the bars above and
  below the bed wrap onto two rows, and the side panel only scrolls up and down.
* The main window opens boards; the page's own Open buttons are for
  ``srm-cam-laser`` on its own.
* ``stop()`` / ``is_running()`` for the main window's Escape, and
  ``kind_changed`` so the rail follows the job tabs.
* The job follows the main window's stencil kerf, and the page's recipe is the
  one place the isolation rings are set.
* Novice sees the page for running a job, not for calibrating the laser.
* A panel of several boards comes as one job with one outline per board.
"""
from uiscale import ui_scale
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QWidget
from shapely.geometry import MultiPolygon, box

from gerber2rml.engine import stencil, xtool

FIX = Path(__file__).parent / "fixtures"
BUCK = FIX / "mosfet_test"
WROOM = FIX / "stencil_wroom"


@pytest.fixture
def sl(monkeypatch):
    from gerber2rml.gui2 import stencil_laser
    monkeypatch.setattr(stencil_laser, "_SETTINGS", ("SRM-CAM-tests", "laser-page-layout"))
    return stencil_laser


class _Host(QWidget):
    """What the page asks of the main window, and nothing else."""

    def __init__(self):
        super().__init__()
        self._stencil_kerf = stencil.DEFAULT_KERF
        self._mask_shrink = 0.0
        self._laser_offsets = 12
        self._laser_token = self._laser_job_token()

    def _laser_job_token(self):
        return (self._laser_offsets,)

    def action_laser_offsets(self, value):
        self._laser_offsets = max(1, int(value))

    def _laser_art_for(self, kind, *, side=None):
        if kind == "stencil":
            return stencil.build_stencil(WROOM, kerf=self._stencil_kerf)
        if kind == "traces":
            return xtool.build_laser_traces(BUCK, side=side or "bottom", mirror=True,
                                            offsets=self._laser_offsets)
        raise ValueError(f"No {kind} in this test")


def _page(sl, art, host=None, embedded=True):
    host = host if host is not None else _Host()
    d = sl.StencilLaserDialog(art, host, name="test", jobs=host._laser_art_for,
                              embedded=embedded)
    return host, d


def _traces():
    return xtool.build_laser_traces(BUCK, mirror=True)


# ------------------------------------------------------------ the width

def test_the_embedded_page_fits_a_laptop_beside_the_rail(qt_app, sl):
    host, d = _page(sl, _traces())
    try:
        assert d.minimumSizeHint().width() <= 1050 * ui_scale()
        w = int(1050 * ui_scale())
        host.resize(w, 700)
        d.resize(w, 700)
        host.show()
        d.show()
        QCoreApplication.processEvents()
        assert d.width() <= w
        assert not d.header.one_row and not d.foot.one_row     # two rows each
        bar = d.inspector.horizontalScrollBar()
        assert not bar.isVisible()
        panel = d.inspector.widget()
        assert panel.minimumSizeHint().width() <= d.inspector.viewport().width()
        # With room, each bar goes back to one row.
        host.resize(2000, 900)
        d.resize(2000, 900)
        QCoreApplication.processEvents()
        assert d.header.one_row and d.foot.one_row
    finally:
        d.close()
        host.close()


def test_the_page_on_its_own_still_opens(qt_app, sl):
    d = sl.StencilLaserDialog()
    try:
        assert d.minimumSizeHint().width() <= 1366 * ui_scale()   # no rail beside it
        assert not d.open_row.isHidden()            # it opens its own boards
    finally:
        d.close()


# ------------------------------------------------------------ one board, one place

def test_the_main_window_opens_boards_not_the_page(qt_app, sl):
    host, d = _page(sl, _traces())
    try:
        assert d.open_row.isHidden()
        assert d.gerber_btn.isHidden() is False     # the row hides them, not each
    finally:
        d.close()


# ------------------------------------------------------------ Escape and the rail

def test_stop_and_is_running(qt_app, sl):
    stopped = []
    _host, d = _page(sl, _traces())
    d.laser = type("L", (), {"stop": lambda self: stopped.append(1)})()
    try:
        assert d.is_running() is False
        d.stop()
        assert stopped == [1] and "Stopped" in d.status.text()
    finally:
        d.close()


def test_escape_on_the_page_goes_on_to_the_main_window(qt_app, sl):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    _host, d = _page(sl, _traces())
    try:
        e = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        d.keyPressEvent(e)
        assert not e.isAccepted()
    finally:
        d.close()


def test_the_job_tabs_tell_the_rail(qt_app, sl):
    _host, d = _page(sl, _traces())
    seen = []
    d.kind_changed.connect(seen.append)
    try:
        d.switch_kind("stencil")
        assert d.kind == "stencil" and seen == ["stencil"]
        d.switch_kind("stencil")                    # nothing changed: no word
        assert seen == ["stencil"]
        d.job_switch.changed.emit("traces")         # the page's own tabs
        assert seen == ["stencil", "traces"]
    finally:
        d.close()


# ------------------------------------------------------------ the main window's settings

def test_the_stencil_follows_the_kerf_set_in_the_main_window(qt_app, sl):
    host = _Host()
    host, d = _page(sl, host._laser_art_for("stencil"), host)
    try:
        assert d.base_art.kerf == pytest.approx(stencil.DEFAULT_KERF)
        d.x.setValue(33)
        host._stencil_kerf = 0.15
        d.switch_kind("stencil")                    # the rail's row again
        assert d.base_art.kerf == pytest.approx(0.15)
        assert d.x.value() == pytest.approx(33)     # it stays where it was
        host._stencil_kerf = 0.05
        host.show()
        d.hide()
        d.show()                                    # or coming back to the page
        assert d.base_art.kerf == pytest.approx(0.05)
    finally:
        d.close()
        host.close()


def test_the_recipe_sets_the_rings_for_the_main_window_too(qt_app, sl):
    host = _Host()
    assert host._laser_offsets == 12
    host, d = _page(sl, _traces(), host)
    told = []
    d.rings_changed.connect(told.append)
    try:
        assert host._laser_offsets == d.offsets.value() == d.trace_rings()
        d.offsets.setValue(9)
        assert host._laser_offsets == 9 and told == [9]
        assert d.recipe().offsets == 9
        # The page's own number is no reason for the main window to rebuild it.
        assert host._laser_token == host._laser_job_token()
        d.switch_kind("stencil")
        assert host._laser_offsets == d.trace_rings()
    finally:
        d.close()


# ------------------------------------------------------------ Novice

def test_novice_sees_the_page_for_running_a_job(qt_app, sl, monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "novice")
    _host, d = _page(sl, _traces())
    try:
        for w in (d.save_btn, d.del_btn, d.calibrate_btn, d.manual_refs,
                  d.auto_refs, d.camera_section, d.proof_more):
            assert w.isHidden(), w
        for w in (d.photo_btn, d.focus_btn, d.align_btn, d.cut_btn, d.stop_btn,
                  d.job_switch, d.rot_l, d.rot_r, d.mode, d.proof_btn):
            assert not w.isHidden(), w
        monkeypatch.setenv("SRM_CAM_MODE", "pro")
        d.apply_tier()
        for w in (d.save_btn, d.del_btn, d.calibrate_btn, d.manual_refs,
                  d.auto_refs, d.camera_section, d.proof_more):
            assert not w.isHidden(), w
    finally:
        d.close()


# ------------------------------------------------------------ a panel of boards

def test_a_panel_with_one_outline_per_board(qt_app, sl):
    outline = MultiPolygon([box(0, 0, 30, 20), box(40, 0, 70, 20)])
    art = xtool.LaserArt(kind="mask", outline=outline, mirrored=False,
                         apertures=[box(5, 5, 8, 8), box(45, 5, 48, 8)],
                         features=[box(10, 10, 11, 11).buffer(0)])
    d = sl.StencilLaserDialog(art, None, jobs={"mask": art})
    try:
        assert d.art.size == pytest.approx((70, 20))
        path = d.item.path()
        assert len(path.toSubpathPolygons()) == 2
        r = path.boundingRect()
        assert (r.width(), r.height()) == pytest.approx((70, 20))
        d.rotate(1)
        assert d.art.size == pytest.approx((20, 70))
        assert len(d.item.holes) == 2
        bed = d._reference_to_bed((45.0, 5.0))
        back = d._reference_from_bed(bed)
        assert back == pytest.approx((45.0, 5.0))
    finally:
        d.close()
