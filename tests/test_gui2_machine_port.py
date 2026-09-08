"""Machine control at the mill, ported from the original interface.

Run tracking with an ETA that starts by itself when the bit moves; Probe Z
and Zero Z as two separately explained touches; the arrow keys jogging the
bit over the stage; a fading trail of where the bit has been; the overlay
trim for a G54 that is not where the design sits; and the status chips.
Every test that needs a machine drives a fake link - nothing here opens a
serial port - and the bar is built with the link capability forced on, so
the same tests mean the same thing on the CNC PC and on Linux.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from gerber2rml import platform as plat
from gerber2rml.gui2 import machine, style, theme, tier
from gerber2rml.gui2.machine import RunTracker, RunReadout, MachineBar
from gerber2rml.gui2.stage import Stage
from gerber2rml.gui2.window import MainWindow
from gerber2rml.toolpath import Move

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


# ------------------------------------------------------------------ fakes
class _Link:
    """What the bar and the tracker see of a link, with a recorder."""

    def __init__(self, connected=True, features=("zeroz", "retouch")):
        self.connected = connected
        self.calls = []
        self.last_jog_t = 0.0
        self.firmware = ({"version": 3, "features": list(features),
                          "port": "COM4"} if connected else None)
        self.surface_z = None
        self._paused = False

    def is_connected(self):
        return self.connected

    def has_feature(self, name):
        return name in (self.firmware or {}).get("features", ())

    def touch_off(self):
        self.calls.append("touch")

    def zero_z(self):
        self.calls.append("zero_z")

    def jog_to(self, x, y):
        self.calls.append(("jog", round(x, 3), round(y, 3)))

    def jog_z(self, dz):
        self.calls.append(("jog_z", dz))

    def pause(self):
        self.calls.append("pause")
        return self.connected

    def resume(self):
        self.calls.append("resume")
        return self.connected

    def can_stop_something(self):
        return self.connected

    def stop_now(self):
        self.calls.append("stop")


def _line(pts, z=-0.15):
    return [Move(pts[0][0], pts[0][1], 2.0, rapid=True)] + \
           [Move(x, y, z) for (x, y) in pts]


@pytest.fixture
def with_link(monkeypatch):
    """The bar with its live controls, whatever platform the tests run on."""
    monkeypatch.setattr(plat, "capabilities",
                        lambda p=None: plat.Capabilities(machine_link=True))


@pytest.fixture
def bar(qt_app, with_link):
    # The app's own stylesheet, because the width budget is measured in it:
    # Fusion's default button padding is wider than the interface's.
    qt_app.setStyleSheet(style.STYLESHEET)
    b = MachineBar(machine.MachineLink())
    b.link = _Link()
    b.said = []
    b.message.connect(lambda level, text: b.said.append((level, text)))
    b._on_linked({"version": 3, "port": "COM4"})
    b._timer.stop()                      # no poll against a fake link
    yield b
    b.close()


@pytest.fixture
def win(qt_app, with_link):
    w = MainWindow()
    w.resize(1400, 900)
    w._chip_timer.stop()                 # the tests call refresh_chips
    yield w
    w.close()


@pytest.fixture
def loaded(win):
    win.load_folder(str(FIXT))
    return win


def _connect(win):
    """Stand the window's real link up without a port: enough for
    is_connected(), with the port-touching calls recorded instead."""
    link = win.link
    link._ser = object()
    link.firmware = {"version": 3, "features": ["zeroz"], "port": "COM4"}
    link.calls = []
    link.jog_to = lambda x, y: link.calls.append(("jog", round(x, 3),
                                                  round(y, 3)))
    win.bar._on_linked(link.firmware)
    win.bar._timer.stop()
    win._on_linked(link.firmware)
    return link


def _run_step(win):
    return next(s for s in win.plan if s.kind == "run" and s.op == "traces")


# ------------------------------------------------------- the tracker logic
def test_the_tracker_follows_a_run_and_counts_down():
    tr = RunTracker(_Link(), now=lambda: 100.0)
    total = tr.arm([_line([(0, 0), (10, 0), (20, 0)])], 4.0, 1.0, "Traces")
    assert total > 0 and tr.is_tracking() and not tr.finished
    f0, _, r0 = tr.feed(0.0, 0.0, -0.15)
    f1, _, r1 = tr.feed(10.0, 0.0, -0.15)
    f2, _, r2 = tr.feed(20.0, 0.0, -0.15)
    assert f0 < f1 < f2 and r0 > r1 > r2
    assert tr.finished and abs(f2 - 1.0) < 1e-6
    tr.disarm()
    assert not tr.is_tracking() and tr.feed(0, 0, 0) is None


def test_tracking_starts_by_itself_once_the_bit_has_been_moving():
    """Three consecutive polls with the bit moving is a run starting in
    VPanel; two is not, and jitter never is."""
    tr = RunTracker(_Link(), now=lambda: 100.0)
    started = []
    def start():
        started.append(1)
        tr.arm([_line([(0, 0), (40, 0)])], 4.0, 1.0, "Traces")
        return True
    tr.feed(0, 0, 0, start=start)
    tr.feed(0.1, 0, 0, start=start)          # jitter
    tr.feed(0.2, 0, 0, start=start)
    assert not started
    tr.feed(1.0, 0, 0, start=start)          # moving...
    tr.feed(2.0, 0, 0, start=start)
    assert not started                       # two reads: not yet
    tr.feed(3.0, 0, 0, start=start)
    assert started == [1] and tr.is_tracking()


def test_our_own_jog_does_not_start_tracking():
    link = _Link()
    clock = [100.0]
    tr = RunTracker(link, now=lambda: clock[0])
    started = []
    start = lambda: started.append(1) or True
    link.last_jog_t = 100.0                  # we just jogged
    for x in range(6):
        tr.feed(float(x), 0, 0, start=start)
    assert not started
    clock[0] = 103.0                         # the grace is over
    for x in range(6, 10):
        tr.feed(float(x), 0, 0, start=start)
    assert started == [1]


def test_auto_start_can_be_turned_off():
    tr = RunTracker(_Link(), now=lambda: 100.0)
    tr.auto = False
    started = []
    for x in range(6):
        tr.feed(float(x), 0, 0, start=lambda: started.append(1) or True)
    assert not started


def test_a_finished_run_that_moves_again_is_the_next_run():
    tr = RunTracker(_Link(), now=lambda: 100.0)
    tr.arm([_line([(0, 0), (10, 0)])], 4.0, 1.0, "Traces")
    tr.feed(10.0, 0, -0.15)
    assert tr.finished
    rearmed = []
    def start():
        rearmed.append(1)
        tr.arm([_line([(0, 0), (10, 0)])], 4.0, 1.0, "Traces")
        return True
    for x in (0.0, 1.0, 2.0, 3.0, 4.0):
        tr.feed(x, 0, -0.15, start=start)
    assert rearmed == [1] and not tr.finished


# --------------------------------------------------------- the readout
def test_the_run_readout_is_only_there_while_a_run_is_followed(qt_app):
    r = RunReadout()
    assert r.isHidden()
    r.set_armed("Isolation traces", 200.0)
    assert not r.isHidden() and "total" in r._value.text()
    r.set_run("Isolation traces", 0.42, 116.0)
    assert "42%" in r._label.text() and "left" in r._value.text()
    r.set_run("Isolation traces", 1.0, 0.0)
    assert r._value.text() == "done"
    r.clear()
    assert r.isHidden()


def test_a_long_step_title_never_widens_the_bar(qt_app):
    r = RunReadout()
    r.set_run("A very long step title that would not fit anywhere", 0.5, 10)
    assert r.minimumWidth() == r.maximumWidth() == r.width() or \
        r.minimumWidth() == r.maximumWidth()
    assert r._label.minimumSizeHint().width() <= r.width()


# ------------------------------------------------------ the bar itself
def test_the_bar_stays_one_row_with_stop_last_and_whole(bar, qt_app):
    """Tracking, both Z touches and the readout all on the live row, and
    the bar still fits the narrower window the A/B was run at."""
    bar.run.set_run("Isolation traces", 0.42, 200)
    bar._on_position(120.0, 100.0, -1.0, True)
    qt_app.processEvents()
    assert bar.minimumSizeHint().width() <= 1280, bar.minimumSizeHint().width()
    assert bar.live.sizeHint().height() <= theme.BAR_H
    lay = bar.layout()
    last = lay.itemAt(lay.count() - 1).widget()
    assert last is bar.stop_btn
    assert not bar.stop_btn.isHidden() and bar.stop_btn.isEnabled()
    assert bar.stop_btn.minimumWidth() >= 112


def test_probe_z_and_zero_z_are_two_buttons_that_say_what_each_changes(bar):
    assert bar.probe_btn.text() == "Probe Z"
    assert bar.zero_btn.text() == "Zero Z"
    probe, zero = bar.probe_btn.toolTip().lower(), bar.zero_btn.toolTip().lower()
    # the app-side capture says the machine is untouched...
    assert "changes nothing on the machine" in probe
    assert "origin is untouched" in probe
    # ...and the firmware write says which origin it moves, and only Z
    assert "firmware" in zero and "origin" in zero and "vpanel" in zero
    assert "xy origin is never moved" in zero


def test_probe_z_touches_off_and_zero_z_writes_the_origin(bar):
    bar.probe_btn.click()
    assert bar.link.calls == ["touch"]
    bar.zero_btn.click()
    assert bar.link.calls == ["touch", "zero_z"]


def test_both_touches_are_refused_while_the_bit_is_on_the_copper(bar):
    bar._on_position(10.0, 10.0, -1.0, True)
    bar.probe_btn.click()
    bar.zero_btn.click()
    assert bar.link.calls == []
    assert all("touching" in t.lower() for _l, t in bar.said[-2:])
    assert bar.dro_z._label.text() == "Touch"
    bar._on_position(10.0, 10.0, 0.0, False)
    assert bar.dro_z._label.text() == "Z"


def test_zero_z_says_so_on_a_firmware_that_cannot_write_the_origin(bar):
    bar.link = _Link(features=())
    bar.zero_btn.click()
    assert bar.link.calls == []
    assert "reflash" in bar.said[-1][1].lower()


def test_the_touch_results_are_reported_in_the_operators_terms(bar):
    bar._on_done("touch", (10.0, 10.0, -12.34))
    assert "origin is unchanged" in bar.said[-1][1]
    bar._on_done("touch", None)
    assert bar.said[-1][0] == "warn" and "clips" in bar.said[-1][1]
    bar._on_done("zero_z", (0.0, 0.0, -12.34))
    assert "Origin Z written" in bar.said[-1][1] and "G54" in bar.said[-1][1]
    bar._on_done("zero_z", None)
    assert bar.said[-1][0] == "warn" and "not written" in bar.said[-1][1]


def test_pause_speaks_through_the_bars_own_log(bar):
    """The hold handler addressed a ``ctl`` the bar never had; every word
    the bar says goes out on its message signal."""
    bar.pause_btn.click()
    assert bar.link.calls == ["pause"]
    assert bar.said[-1] == ("ok", "Held. Resume carries on from here.")


def test_the_port_picker_is_put_away_while_linked(bar):
    assert bar.port_combo.isHidden()
    bar._on_unlinked("disconnected")
    assert not bar.port_combo.isHidden()
    assert bar.run.isHidden()


def test_a_jog_stamps_the_link_so_tracking_ignores_it():
    link = machine.MachineLink()
    assert link.last_jog_t == 0.0
    link._ser = object()
    link.jog_to(10.0, 10.0)
    assert link.last_jog_t > 0.0
    link._q.get_nowait()
    link.jog_z(0.5)
    link._q.get_nowait()


# ---------------------------------------------------- tracking in the app
def test_tracking_follows_the_selected_step_and_shows_on_the_bar(loaded, qt_app):
    _connect(loaded)
    loaded.select_step(_run_step(loaded).key)
    loaded.action_track_run(True)
    assert loaded.tracker.is_tracking()
    assert loaded.tracker.label == _run_step(loaded).title
    assert loaded.track_act.isChecked()
    assert not loaded.bar.run.isHidden()
    assert "total" in loaded.bar.run._value.text()
    # a position lands the readout on the run
    paths = loaded._paths_cache[_run_step(loaded).key][0]
    m = paths[0][1]
    loaded.link.position.emit(m.x, m.y, m.z, False)
    assert "left" in loaded.bar.run._value.text()
    loaded.action_track_run(False)
    assert not loaded.tracker.is_tracking() and loaded.bar.run.isHidden()


def test_tracking_needs_a_numbered_step(loaded):
    _connect(loaded)
    said = []
    loaded.say = lambda level, text: said.append((level, text))
    loaded.select_step("setup")
    loaded.action_track_run(True)
    assert not loaded.tracker.is_tracking()
    assert not loaded.track_act.isChecked()
    assert "numbered step" in said[-1][1]


def test_a_run_starting_in_vpanel_is_tracked_without_a_press(loaded):
    _connect(loaded)
    step = _run_step(loaded)
    loaded.select_step(step.key)
    assert not loaded.tracker.is_tracking()
    paths = loaded._paths_cache[step.key][0]
    m = paths[0][1]
    for i in range(6):                    # the bit sets off along the path
        loaded.link.position.emit(m.x + i, m.y, m.z, False)
    assert loaded.tracker.is_tracking()
    assert loaded.track_act.isChecked()
    assert not loaded.bar.run.isHidden()


def test_auto_tracking_is_a_menu_choice_that_reaches_the_tracker(loaded):
    assert loaded.autotrack_act.isChecked() and loaded.tracker.auto
    loaded.autotrack_act.trigger()
    assert not loaded.tracker.auto


def test_losing_the_link_drops_the_run(loaded):
    _connect(loaded)
    loaded.select_step(_run_step(loaded).key)
    loaded.action_track_run(True)
    loaded.link._ser = None
    loaded.link.unlinked.emit("cable")
    assert not loaded.tracker.is_tracking()
    assert not loaded.track_act.isChecked()


# ---------------------------------------------------- the arrow keys
def test_arrow_keys_jog_the_bit_in_jog_mode_and_the_board_otherwise(loaded, qt_app):
    link = _connect(loaded)
    loaded.link.position.emit(50.0, 40.0, 5.0, False)
    steps, nudges = [], []
    loaded.stage.jog_step_requested.connect(lambda dx, dy: steps.append((dx, dy)))
    loaded.stage.placement_dragging.connect(lambda dx, dy: nudges.append((dx, dy)))
    loaded.stage.show()
    loaded.set_stage_mode("jog")
    QTest.keyClick(loaded.stage, Qt.Key_Right)
    QTest.keyClick(loaded.stage, Qt.Key_Up, Qt.ShiftModifier)
    QTest.keyClick(loaded.stage, Qt.Key_Left, Qt.ControlModifier)
    assert steps == [(1.0, 0.0), (0.0, 10.0), (-0.1, 0.0)]
    assert nudges == []
    # each one was a relative move from the live position, accumulating
    assert link.calls == [("jog", 51.0, 40.0), ("jog", 51.0, 50.0),
                          ("jog", 50.9, 50.0)]
    loaded.stage._nudge_timer.stop()
    loaded.set_stage_mode("place")
    QTest.keyClick(loaded.stage, Qt.Key_Right)
    loaded.stage._nudge_timer.stop()
    assert len(steps) == 3 and nudges == [(0.1, 0.0)]


def test_arrow_jog_refuses_to_leave_the_travel_and_needs_a_position(loaded):
    link = _connect(loaded)
    said = []
    loaded.say = lambda level, text: said.append((level, text))
    loaded._on_jog_step(1.0, 0.0)
    assert link.calls == [] and "position" in said[-1][1].lower()
    loaded.link.position.emit(203.0, 10.0, 5.0, False)
    loaded._on_jog_step(1.0, 0.0)
    assert link.calls == [] and "travel" in said[-1][1].lower()


# ---------------------------------------------------- the trail
def test_the_trail_records_where_the_bit_has_been(qt_app):
    st = Stage()
    st.set_tool((0.0, 0.0))
    st.set_tool((1.0, 0.0))
    st.set_tool((1.05, 0.0))            # jitter, dropped
    st.set_tool((2.0, 0.0), touch=True)
    assert st.trail() == [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    assert st._tool_touch
    st.clear_trail()
    assert st.trail() == []
    st.set_trail_visible(False)
    st.set_tool((3.0, 0.0))
    assert st.trail() == []             # hidden means not recorded either
    st.set_trail_visible(True)
    st.set_tool((4.0, 0.0))
    assert st.trail() == [(4.0, 0.0)]
    st.set_tool(None)
    assert st._tool is None
    st.close()


def test_the_trail_is_capped(qt_app):
    st = Stage()
    for i in range(st.TRAIL_MAX + 50):
        st.set_tool((i * 1.0, 0.0))
    assert len(st.trail()) == st.TRAIL_MAX
    st.close()


def test_the_trail_has_a_view_menu_home(win):
    assert win.trail_act.isChecked()
    win.stage.set_tool((1.0, 1.0)); win.stage.set_tool((2.0, 2.0))
    win.trail_clear_act.trigger()
    assert win.stage.trail() == []
    win.trail_act.trigger()
    assert not win.stage._trail_on


# ---------------------------------------------------- the overlay trim
def test_align_overlay_needs_a_live_position(win):
    said = []
    win.say = lambda level, text: said.append((level, text))
    win.align_act.trigger()             # checks it, then the handler refuses
    assert not win.align_act.isChecked()
    assert "position" in said[-1][1].lower()


def test_the_trim_corrects_the_picture_and_the_jog_but_not_the_job(win):
    link = _connect(win)
    win.link.position.emit(10.0, 10.0, 0.0, False)
    win.align_act.trigger()
    assert win._align_armed and win.stage.mode == "jog"
    win._on_jog_click(12.0, 11.0)      # "the bit is really at this point"
    assert win._overlay_trim == (2.0, 1.0)
    assert not win._align_armed and not win.align_act.isChecked()
    assert link.calls == []            # a pick is not a jog
    assert win.trim_clear_act.isEnabled()
    assert "+2.00" in win.trim_clear_act.text()
    # the drawn bit follows the trim; the bar keeps the raw readout
    win.link.position.emit(10.0, 10.0, 0.0, False)
    assert win.stage._tool == (12.0, 11.0)
    assert win.bar.dro_x._value.text().strip() == "10.00"
    # a click on the design lands the head on the machine point under it
    win._on_jog_click(20.0, 20.0)
    assert link.calls[-1] == ("jog", 18.0, 19.0)
    win.action_clear_trim()
    assert win._overlay_trim == (0.0, 0.0)
    assert not win.trim_clear_act.isEnabled()
    assert win.stage._tool == (10.0, 10.0)


def test_the_trim_is_full_tier_work(win, monkeypatch):
    monkeypatch.delenv("SRM_CAM_MODE")   # conftest pins Full; let it switch
    for which, visible in ((tier.ESSENTIAL, False), (tier.FULL, True)):
        tier.set_tier(which)
        win._sync_tier()
        assert win.align_act.isVisible() is visible
        assert win.trim_clear_act.isVisible() is visible


# ---------------------------------------------------- the chips
def test_the_chips_answer_for_mesh_fit_photo_and_boxes(loaded):
    chips = loaded.chips
    loaded.refresh_chips()
    assert [chips[k].label.text() for k in ("mesh", "fit", "photo", "boxes")] \
        == ["Mesh", "Fit", "Photo", "Boxes"]
    loaded.rework_page.add_region(10, 10, 20, 20)
    loaded.refresh_chips()
    assert chips["boxes"].label.text() == "Boxes 1"
    assert chips["boxes"].dot._state == "ok"
    page = loaded.level_page
    page.nx.setValue(2); page.ny.setValue(2); page._build()
    from PySide6.QtWidgets import QTableWidgetItem
    for r in range(3):
        page.table.setItem(r, 2, QTableWidgetItem("0.0100"))
    loaded.refresh_chips()
    assert chips["mesh"].label.text() == "Mesh 3"
    # measured but not applied is the amber case: the number is there and
    # the map is doing nothing
    assert chips["mesh"].dot._state in ("warn", "ok")


def test_the_chips_hide_full_tier_facts_in_essential(win, monkeypatch):
    monkeypatch.delenv("SRM_CAM_MODE")
    tier.set_tier(tier.ESSENTIAL)
    win._sync_tier()
    assert win.chips["fit"].isHidden() and win.chips["boxes"].isHidden()
    assert not win.chips["mesh"].isHidden()
    tier.set_tier(tier.FULL)
    win._sync_tier()
    assert not win.chips["fit"].isHidden()


def test_the_chips_do_not_widen_the_window(win, qt_app):
    """The header was the widest row before the chips; it must not become
    the reason the window cannot be narrowed to the A/B's 1400 px."""
    qt_app.processEvents()
    head = win.frame_switch.parentWidget()
    assert head.minimumSizeHint().width() <= 1333


def test_nothing_new_offers_to_zero_the_xy_origin(bar):
    texts = [b.text().lower() for b in bar.findChildren(QPushButton)]
    assert not [t for t in texts if "zero" in t and "xy" in t]
    assert "zero z" in texts
