"""Two tiers, one code path.

The property that matters is the one the brief calls non-negotiable: what a
student produces in the simpler tier is byte for byte what a teacher produces
in the full one. If those two ever diverge there are two programs, and the one
students use is the one nobody tests.

These deliberately drive the tier through ``SRM_CAM_MODE`` rather than through
the stored preference. Two reasons: it is what a lab pinning its seats actually
does, and it keeps the test run out of the developer's real QSettings.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractButton

from gerber2rml.engine import bracket as br
from gerber2rml.gui2 import tier
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


def _window(monkeypatch, mode):
    monkeypatch.setenv("SRM_CAM_MODE", mode)
    w = MainWindow()
    w.resize(1400, 900)
    w.load_folder(str(FIXT))
    return w


def _visible_controls(w):
    """Everything clickable that the tier has not put away.

    ``isHidden()`` is True only for something explicitly hidden, which is
    exactly what the tier does — so this reports the tier's decisions and not
    the accident of which stack page happens to be on top.
    """
    out = {b.text() for b in w.findChildren(QAbstractButton)
           if not b.isHidden() and b.text()}
    out |= {a.text() for a in w.findChildren(QAction)
            if a.isVisible() and a.text()}
    return out


def test_the_environment_pin_is_honoured(monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "novice")
    assert tier.current_tier() == tier.ESSENTIAL
    monkeypatch.setenv("SRM_CAM_MODE", "professional")
    assert tier.current_tier() == tier.FULL
    monkeypatch.setenv("SRM_CAM_MODE", "full")
    assert tier.current_tier() == tier.FULL
    assert tier.set_tier(tier.ESSENTIAL) is False       # pinned: menu is inert


def test_the_first_interfaces_vocabulary_still_works(monkeypatch):
    """A lab that already pinned its seats with the original interface's words
    should not have to do it twice."""
    for word, expect in (("novice", tier.ESSENTIAL), ("pro", tier.FULL)):
        monkeypatch.setenv("SRM_CAM_MODE", word)
        assert tier.current_tier() == expect


def test_essential_is_the_default(monkeypatch):
    monkeypatch.delenv("SRM_CAM_MODE", raising=False)
    monkeypatch.setattr(tier, "_settings", lambda: _NoSettings())
    assert tier.current_tier() == tier.ESSENTIAL


class _NoSettings:
    """A QSettings stand-in, so the default-tier test never touches the real
    one on the developer's machine."""

    def value(self, _key, default=None):
        return default

    def setValue(self, _key, _value):
        pass


def test_the_two_tiers_export_identical_bytes(qt_app, monkeypatch, tmp_path):
    """The whole point. Same settings, same files, down to the byte."""
    a, b = tmp_path / "essential", tmp_path / "full"
    w1 = _window(monkeypatch, "novice")
    try:
        assert not tier.is_full()
        w1.export_to(a)
    finally:
        w1.close()
    w2 = _window(monkeypatch, "pro")
    try:
        assert tier.is_full()
        w2.export_to(b)
    finally:
        w2.close()

    names_a = sorted(p.name for p in a.iterdir())
    names_b = sorted(p.name for p in b.iterdir())
    assert names_a == names_b, (names_a, names_b)
    for name in names_a:
        # The run plan names its own folder; everything else must match byte
        # for byte.
        if name.endswith("_runplan.txt"):
            continue
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_the_plan_is_the_same_in_both_tiers(qt_app, monkeypatch):
    """Novice shows three rows, but the run needs the whole plan. The only
    difference is that its Run it all step is always there."""
    w1 = _window(monkeypatch, "novice")
    try:
        essential = [(s.key, s.ordinal, s.file) for s in w1.plan]
    finally:
        w1.close()
    w2 = _window(monkeypatch, "pro")
    try:
        w2.action_autorun(True)
        full = [(s.key, s.ordinal, s.file) for s in w2.plan]
        w2.action_autorun(False)
    finally:
        w2.close()
    assert essential == full


def test_novice_is_three_rows_built_around_the_run(qt_app, monkeypatch):
    w = _window(monkeypatch, "novice")
    try:
        assert list(w.traveller._rows) == ["setup", "checks", "autorun"]
        assert w.traveller._rows["autorun"].step.title == "Run it"
        # Its Next button is the way on from the board page.
        w.select_step("setup")
        assert not w.inspector.setup.next_btn.isHidden()
        w.inspector.setup.next_btn.click()
        assert w.inspector.stack.currentWidget() is w.autorun_page
        assert w.traveller.current() == "autorun"
    finally:
        w.close()


def test_pro_has_the_whole_plan_and_no_novice_button(qt_app, monkeypatch):
    w = _window(monkeypatch, "pro")
    try:
        assert list(w.traveller._rows) == [s.key for s in w.plan]
        assert "autorun" not in w.traveller._rows      # chosen, in Pro
        assert w.inspector.setup.next_btn.isHidden()
        assert w.autorun_act.isVisible() and w.export_act.isVisible()
    finally:
        w.close()


def test_novice_has_nothing_to_export(qt_app, monkeypatch):
    w = _window(monkeypatch, "novice")
    try:
        assert w.traveller.export_btn.isHidden()
        assert w.traveller.total_row.isHidden()
        for a in (w.export_act, w.export_folder_act, w.screw_act,
                  w.autorun_act, w.mtest_act):
            assert not a.isVisible(), a.text()
        assert not w.export_act.isEnabled()            # nor by Ctrl+E
        assert w.inspector.setup.add_board_btn.isHidden()
        assert "VPanel" not in w.bar.offline_note.text()
    finally:
        w.close()


def test_novice_setup_asks_only_what_the_run_cannot_find_out(qt_app,
                                                             monkeypatch):
    w = _window(monkeypatch, "novice")
    try:
        w.select_step("setup")
        page = w.inspector.setup
        assert not page.double.isHidden() and not page.ds_section.isHidden()
        assert not page.thickness.isHidden()
        for box in (page.ds_more, page.copper_more, page.place_section,
                    page.advanced):
            assert box.isHidden()
        page.double.setChecked(True)                   # one tick
        assert w._double and page.ds_more.isHidden()
        assert w.plan.by_key("flip") is not None
        # Three rows still, and the run still has both sides to do.
        assert list(w.traveller._rows) == ["setup", "checks", "autorun"]
    finally:
        w.close()


def test_novice_run_page_is_the_bracket_and_a_real_run(qt_app, monkeypatch):
    w = _window(monkeypatch, "novice")
    try:
        w.select_step("autorun")
        page = w.autorun_page
        assert page.bracket() and page.where.isHidden()
        assert page.dry_chk.isHidden() and not page.dry_chk.isChecked()
        assert not page.level_chk.isHidden()
        assert not page.check_chk.isHidden()
        assert not page.offline_box.isHidden()         # offline: says so
    finally:
        w.close()


def test_novice_brings_the_board_onto_the_stock_it_shows(qt_app, monkeypatch):
    w = _window(monkeypatch, "novice")
    try:
        w.select_step("autorun")
        page = w.autorun_page
        page.set_bracket(br.DEFAULT)
        page.w_spin.setValue(160)
        page.h_spin.setValue(120)
        b = w.work_bounds()
        sx, sy, sw, sh = w.stock
        assert b[0] >= sx and b[1] >= sy
        assert b[2] <= sx + sw and b[3] <= sy + sh
    finally:
        w.close()


def test_novice_keeps_the_jog_controls_and_stop(qt_app, monkeypatch):
    w = _window(monkeypatch, "novice")
    try:
        assert not w.bar.pad.isHidden()
        assert not w.bar.jog_btn.isHidden()            # Click to jog
        assert w.bar.stop_btn.isEnabled() and not w.bar.stop_btn.isHidden()
    finally:
        w.close()


def test_novice_can_open_what_the_run_measured(qt_app, monkeypatch):
    """The height map has no row in Novice, but it can be looked at."""
    w = _window(monkeypatch, "novice")
    try:
        w.select_step("autorun")
        w.autorun_page._show("level")
        assert w.inspector.stack.currentWidget() is w.level_page
        assert not any(r.selected for r in w.traveller._rows.values())
        w.refresh_plan()                               # stays where it is
        assert w.inspector.stack.currentWidget() is w.level_page
    finally:
        w.close()


def test_the_simulated_mill_is_a_pro_thing(qt_app, monkeypatch):
    from gerber2rml.gui2 import machine
    w = _window(monkeypatch, "novice")
    try:
        assert machine.SHOW_SIM is False
    finally:
        w.close()


def _novice_run(qt_app, w, double):
    import time
    from gerber2rml.engine import simmachine as sm
    sm.machine(speedup=1e6, corner=(42490, 9470), angle_deg=0.0,
               size=(150000, 120000))

    def wait(cond, secs=120):
        t0 = time.monotonic()
        while not cond() and time.monotonic() - t0 < secs:
            qt_app.processEvents()
            time.sleep(0.01)
        return cond()
    w.link.connect_to("SIM")
    assert wait(w.link.is_connected, 10)
    w.inspector.setup.double.setChecked(double)
    w.select_step("autorun")
    page = w.autorun_page
    assert wait(page.offline_box.isHidden, 5)
    page.set_bracket(br.Bracket(3, 12, "back-left"))
    page.w_spin.setValue(150)
    page.h_spin.setValue(120)
    page.level_chk.setChecked(False)
    done = []
    page.finished.connect(lambda ok, msg: done.append((ok, msg)))
    page.start()

    def step():
        if not page.flip_btn.isHidden():
            page.flip_btn.click()
        if not page.check_box.isHidden():
            # The run has the port: that is not "not connected".
            assert page.offline_box.isHidden()
            assert not w.bar.connect_btn.isEnabled()
            assert "run has the machine" in w.bar.offline_note.text()
            page.cut_btn.click()
        return bool(done)
    assert wait(step), "the run never finished"
    assert done[0][0], done[0][1]
    assert sm.machine().lines
    assert "VPanel" not in w.bar.offline_note.text()
    assert wait(w.link.is_connected, 15)      # and it has the machine back
    w.link.disconnect_from("test")
    if w.link._thread is not None:
        w.link._q.put(None)
        w.link._thread.join(2)


def test_novice_runs_a_single_sided_board_end_to_end(qt_app, monkeypatch,
                                                     tmp_path):
    from gerber2rml import platform as plat
    monkeypatch.setattr(plat, "documents_dir", lambda *a, **k: tmp_path)
    w = _window(monkeypatch, "novice")
    try:
        _novice_run(qt_app, w, False)
    finally:
        w.close()


def test_novice_runs_a_double_sided_board_end_to_end(qt_app, monkeypatch,
                                                     tmp_path):
    from gerber2rml import platform as plat
    monkeypatch.setattr(plat, "documents_dir", lambda *a, **k: tmp_path)
    w = _window(monkeypatch, "novice")
    try:
        _novice_run(qt_app, w, True)
    finally:
        w.close()


def test_essential_puts_away_the_experimental_stream(qt_app, monkeypatch):
    """Streaming is gated on uncalibrated speed units and is not the way this
    lab runs jobs, so it is not on the beginner's happy path."""
    w = _window(monkeypatch, "novice")
    try:
        assert not w.stream_act.isVisible()
    finally:
        w.close()
    w = _window(monkeypatch, "pro")
    try:
        assert w.stream_act.isVisible()
        assert "experimental" in w.stream_act.text().lower()
    finally:
        w.close()


def test_the_menu_says_exactly_what_the_other_tier_adds():
    """Nobody should have to guess whether the control they remember is gone or
    merely put away."""
    assert len(tier.ADDED_BY_FULL) >= 5
    assert all(len(t) > 30 for t in tier.ADDED_BY_FULL)
    assert len(tier.KEPT_IN_ESSENTIAL) >= 4
    for name, why in tier.KEPT_IN_ESSENTIAL:
        assert name and len(why) > 40, name
