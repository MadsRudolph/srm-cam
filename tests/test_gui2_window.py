"""The second interface, built offscreen and driven through a whole job.

Style follows ``tests/test_window.py``: ``QT_QPA_PLATFORM=offscreen``, and
``SRM_CAM_HOME`` pointed at a temp directory by ``conftest.py`` so a run never
touches the real workspace.

Beyond "does it work", these cover the properties §3 of the brief calls
non-negotiable — the ones a redesign is most likely to lose quietly:

* the stop control is never hidden, disabled, or nested inside anything a mode
  can put away;
* the dry run is step 0 and the cut-out is last;
* a board that will short says so before anything is written, and keeps saying
  it;
* the XY origin is never offered as something to zero;
* nothing implies the spindle speed is settable over the link;
* the four awkward states are designed rather than incidental.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from gerber2rml.gui2 import dialogs, style, tier
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"
GUI2 = Path(__file__).parent.parent / "gerber2rml" / "gui2"


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


# ---------------------------------------------------------------- it works
def test_the_stylesheet_parses_without_warning(qt_app):
    """Qt discards the WHOLE stylesheet on a parse error and only logs about
    it, so a malformed rule would silently unstyle the entire application."""
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtWidgets import QCheckBox, QPushButton, QComboBox
    msgs = []
    qInstallMessageHandler(lambda mode, ctx, m: msgs.append(m))
    try:
        qt_app.setStyleSheet(style.STYLESHEET)
        for W in (QCheckBox, QPushButton, QComboBox):
            w = W()
            w.ensurePolished()
            w.show()
            qt_app.processEvents()
            w.close()
    finally:
        qInstallMessageHandler(None)
    assert not [m for m in msgs
                if "parse" in m.lower() and "stylesheet" in m.lower()]


def test_window_builds(win):
    assert win.stage is not None
    assert win.traveller is not None
    assert win.plan is not None


def test_load_preview_and_export(loaded, tmp_path):
    loaded.select_step("traces_run")
    assert loaded.stage._cuts, "the traces preview drew nothing"
    written = loaded.export_to(tmp_path)
    assert any(Path(p).suffix == ".nc" for p in written)
    assert any(Path(p).name.endswith("_runplan.txt") for p in written)


def test_the_job_is_named_after_the_kicad_project(loaded):
    assert loaded.state.name == "buck"


def test_the_run_sheet_replaces_the_board_after_an_export(loaded, tmp_path):
    """The success state of an export is the run plan, on screen — not a
    message box and not a text file nobody opens."""
    loaded.export_to(tmp_path)
    assert loaded.centre.currentWidget() is loaded.sheet
    text = loaded.sheet.text()
    assert "buck_traces.nc" in text
    assert "NEVER re-zero XY" in text
    assert "Dry run" in text


# ------------------------------------------------------------ machine safety
def test_stop_is_always_visible_and_always_enabled(win):
    """It is never hidden by a tier, a view, a step or a disconnection.

    The first interface put its stop button inside a dock that its beginner
    mode hid, which is why guided levelling had to be pulled out of that mode
    entirely. Here it is a structural part of the window.
    """
    for which in (tier.ESSENTIAL, tier.FULL):
        tier.set_tier(which)
        win._sync_tier()
        for key in [s.key for s in win.plan]:
            win.select_step(key)
            assert win.bar.stop_btn.isEnabled()
            assert not win.bar.stop_btn.isHidden()


def test_stop_lives_outside_every_hideable_container(win):
    """Structural, not incidental: assert the button is not a descendant of the
    rail, the inspector or the centre stack, any of which can change or hide."""
    parents = []
    w = win.bar.stop_btn.parentWidget()
    while w is not None:
        parents.append(w)
        w = w.parentWidget()
    for container in (win.traveller, win.inspector, win.centre, win.stage):
        assert container not in parents


def test_escape_stops_the_machine_even_under_a_modal_dialog(win):
    """The behaviour, not the binding.

    This used to assert that Escape was a ``Qt.ApplicationShortcut``, and it
    passed while the property it stood for was false: Qt refuses to deliver a
    shortcut owned by a window while a modal dialog is up, so with a dialog
    focused the key reached the dialog's ``reject()`` and the machine kept
    moving. Measured at the time: the stop handler was called zero times.

    That gap is exactly where it matters, because ``zero_z`` and ``touch_off``
    drive the tool for up to a minute on a worker thread while the UI stays
    live. So the test now presses the key in the three contexts that exist and
    counts real calls.
    """
    from PySide6.QtWidgets import QLineEdit
    from PySide6.QtTest import QTest
    from gerber2rml.gui2 import dialogs

    calls = []
    original = win.bar._stop
    win.bar._stop = lambda: (calls.append(1), original())
    # Something must be stoppable, or the no-link guidance path is taken.
    win.link.mark_external(True)
    try:
        for label, modal in (("no dialog", None), ("non-modal", False),
                             ("modal", True)):
            calls.clear()
            target, dlg = win, None
            if modal is not None:
                dlg = dialogs.Sheet(win, "Test")
                dlg.setModal(modal)
                dlg.show()
                target = QLineEdit(dlg)
                target.show()
                target.setFocus()
            QTest.keyClick(target, Qt.Key_Escape)
            assert len(calls) == 1, (
                f"Escape fired the stop {len(calls)} times with {label} - "
                f"it must fire exactly once, from anywhere")
            if dlg is not None:
                dlg.close()
    finally:
        win.bar._stop = original
        win.link.mark_external(False)


def test_stop_says_something_useful_with_no_link(win):
    """Never a dead grey button. With nothing connected there is still an
    answer, and it is the one that actually stops this machine."""
    said = []
    win.say = lambda level, text: said.append((level, text))
    win.bar.message.connect(lambda lvl, t: said.append((lvl, t)))
    win.bar._stop()
    assert said
    assert "emergency stop" in said[-1][1].lower() or "lid" in said[-1][1].lower()


def _control_texts(root):
    """Every string a user can click on, anywhere in the window."""
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QAbstractButton, QMenu
    out = [b.text() for b in root.findChildren(QAbstractButton)]
    out += [a.text() for a in root.findChildren(QAction)]
    for menu in root.menuBar().findChildren(QMenu):
        out += [a.text() for a in menu.actions()]
    return [t for t in out if t]


def test_nothing_offers_to_zero_the_xy_origin(loaded):
    """The screw fixture, the dowel registration and the ability to re-run any
    pass all depend on the XY origin surviving the whole job, so no control may
    offer to move it.

    Checked against what is actually clickable rather than against the source:
    prose telling the operator to NEVER re-zero XY is exactly what we want, and
    a source grep cannot tell that apart from a button that does it.
    """
    offenders = [t for t in _control_texts(loaded)
                 if "zero" in t.lower() and "xy" in t.lower()]
    assert not offenders, offenders
    zeroing = [t for t in _control_texts(loaded) if "zero" in t.lower()]
    assert zeroing, "there should still be a way to zero Z"
    for t in zeroing:
        assert "z" in t.lower()


def test_nothing_implies_the_spindle_speed_is_settable(win):
    """``turnSpindle``'s RPM argument is ignored by this machine — 500 and 3000
    produce identical speed. A control implying otherwise would be a lie."""
    from PySide6.QtWidgets import QAbstractSpinBox, QSlider
    for w in win.bar.findChildren(QWidget):
        label = (w.text() if hasattr(w, "text") else "") or ""
        if isinstance(w, (QAbstractSpinBox, QSlider)):
            assert "rpm" not in label.lower()
            assert "speed" not in (w.toolTip() or "").lower() or \
                "vpanel" in (w.toolTip() or "").lower()
    assert "vpanel" in win.bar.spindle_btn.toolTip().lower()


def test_the_screw_checkbox_raises_the_lift_height(loaded):
    """The failure it prevents is silent: the XY is right, the depths are
    right, the preview is right, and the spindle drives into a screw head on
    the first traverse."""
    from gerber2rml.engine import spoilboard
    loaded.state.trace.travel_z = 2.0
    loaded.state.drill.travel_z = 2.0
    loaded.state.cutout.travel_z = 2.0
    loaded.action_screws_toggled(True)
    need = spoilboard.min_travel_z()
    for job in (loaded.state.trace, loaded.state.drill, loaded.state.cutout):
        assert job.travel_z >= need


def test_the_screw_checkbox_never_lowers_a_value_someone_set(loaded):
    loaded.state.trace.travel_z = 9.0
    loaded.action_screws_toggled(True)
    assert loaded.state.trace.travel_z == 9.0


# ----------------------------------------------------------------- findings
def test_a_board_that_will_short_says_so_and_keeps_saying_it(loaded):
    """The finding must not be a status-bar message that expires. It is on the
    rail, and it stays there until the thing it is about stops being true."""
    assert loaded._shorts, "the demo board is supposed to have shorts"
    banner = loaded.traveller.banner
    assert not banner.isHidden()
    assert "shorted" in banner.head.text().lower()
    assert str(len(loaded._shorts)) in banner.head.text()
    # walking the whole plan never clears it: it is not a transient message
    for key in [s.key for s in loaded.plan]:
        loaded.select_step(key)
        assert not banner.isHidden()


def test_the_shorts_are_marked_on_the_trace_view(loaded):
    loaded.select_step("traces_run")
    assert loaded.stage._shorts
    loaded.select_step("drill_run")
    assert not loaded.stage._shorts     # they are a trace-pass finding


def test_the_checks_are_on_screen_not_in_a_dismissable_box(loaded):
    loaded.select_step("checks")
    assert loaded.inspector.stack.currentWidget() is loaded.inspector.checks
    assert loaded._checks
    titles = [c.title for c in loaded._checks]
    assert any("Nets closer than the bit" == t for t in titles)


# ------------------------------------------------------------------- states
def test_the_empty_state_is_designed(win):
    """Not an absence: the bed at true size with its origin marked, and a
    sentence saying what to do."""
    assert not win.stage.has_board()
    assert win.stage._empty_title
    assert win.stage._empty_body
    assert not win.traveller.export_btn.isEnabled()
    assert win.traveller.export_btn.toolTip()


def test_the_disconnected_state_says_what_still_works(win):
    """A bare SRM-20 driven from VPanel is a fully supported setup, and the
    interface should say so rather than showing a row of grey buttons."""
    assert not win.link.is_connected()
    assert win.bar.offline_note.isVisibleTo(win.bar)
    assert "vpanel" in win.bar.offline_note.text().lower()
    assert not win.bar.live.isVisibleTo(win.bar)


def test_a_failed_export_explains_itself_without_a_raw_exception(loaded,
                                                                monkeypatch):
    """Twenty-six dialogs in the first interface have ``str(e)`` for a body.
    Every failure here has to carry a sentence a person can act on."""
    seen = {}

    def fake(parent, headline, exc=None, guidance=""):
        seen.update(headline=headline, exc=exc, guidance=guidance)

    monkeypatch.setattr(dialogs, "report_error", fake)
    written = loaded.export_to("\0 not a path")
    assert written == []
    assert seen["headline"] and "exported" in seen["headline"]
    assert len(seen["guidance"]) > 40
    assert seen["guidance"] != str(seen["exc"])


def test_a_folder_that_is_not_a_board_explains_what_one_looks_like(
        win, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(dialogs, "report_error",
                        lambda p, h, e=None, g="": seen.update(h=h, g=g))
    win.load_folder(str(tmp_path))
    assert "board" in seen["h"].lower()
    assert "edge.cuts" in seen["g"].lower()


def test_error_reporting_is_the_only_error_path_in_the_interface():
    """No bare message boxes anywhere in gui2 — every failure goes through
    ``dialogs.report_error``, which is the one place the raw exception gets
    folded away under a sentence a person can act on.

    Two files are allowed to name QMessageBox: ``dialogs.py``, which is the
    error path, and ``app.py``, whose last-resort panic runs when the window
    could not be built at all and so cannot use anything from this package.
    ``style.py`` merely styles the class.
    """
    allowed = {"dialogs.py", "app.py", "style.py"}
    offenders = []
    for f in sorted(GUI2.rglob("*.py")):
        if f.name in allowed:
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "QMessageBox" not in line:
                continue
            if "``QMessageBox``" in line:          # prose about the old one
                continue
            offenders.append(f"{f.name}:{i}")
    assert not offenders, offenders


# ------------------------------------------------------- one thing selects
def test_the_traveller_is_the_only_selector(loaded):
    """Selecting a step sets the stage and the inspector together, from one
    handler, so the two cannot disagree about which operation is on screen."""
    loaded.select_step("cutout_run")
    assert loaded.traveller.current() == "cutout_run"
    assert loaded.inspector.stack.currentWidget() is loaded.inspector.step
    assert loaded.inspector.step.step.key == "cutout_run"
    assert loaded.stage._cuts


def test_only_one_row_is_ever_selected(loaded):
    for key in ("setup", "traces_run", "level", "checks"):
        loaded.select_step(key)
        lit = [k for k, r in loaded.traveller._rows.items() if r.selected]
        assert lit == [key], lit


def test_the_panels_do_not_resize_as_you_walk_the_plan(loaded):
    """The first interface's settings column grows from 513 px to 1032 px as
    you walk its run plan, and overwrites any splitter position you set."""
    widths = set()
    for key in [s.key for s in loaded.plan]:
        loaded.select_step(key)
        widths.add((loaded.traveller.width(), loaded.inspector.width()))
    assert len(widths) == 1, widths


def test_every_step_is_reachable_at_any_time(loaded):
    """A map, not a gate — real runs jump around."""
    for key in reversed([s.key for s in loaded.plan]):
        loaded.select_step(key)
        assert loaded.traveller.current() == key


# ------------------------------------------------------------- double-sided
def test_double_sided_shows_the_face_being_cut(loaded):
    loaded.action_double_sided(True)
    loaded.select_step("bottom_traces")
    bottom = loaded.stage._holes
    loaded.select_step("top_traces")
    top = loaded.stage._holes
    assert bottom and top
    assert bottom != top, ("the top pass is cut after the flip, so its holes "
                           "are not where the bottom pass's were")


def test_double_sided_export_writes_the_planned_files(loaded, tmp_path):
    loaded.action_double_sided(True)
    written = loaded.export_to(tmp_path)
    names = [Path(p).name for p in written if Path(p).suffix == ".nc"]
    assert loaded.plan.files == names
    assert any("top_traces" in n for n in names)


# -------------------------------------------------------------------- misc
def test_the_stage_defaults_to_the_machine_frame(win):
    """Bed coordinates: the frame VPanel, the position readout and the
    operator's hands are in, and the only one in which click-to-jog is true."""
    assert win.stage.frame == "bed"


def test_the_xray_frame_is_unmistakable(win):
    win._on_frame("xray")
    assert win.stage.frame == "xray"
    assert win.xray_act.isChecked()
    win._on_frame("bed")


def test_the_setup_can_be_saved_and_loaded(loaded, tmp_path, monkeypatch):
    import json
    from dataclasses import asdict
    path = tmp_path / "s.srmcam"
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(path), ""))
    loaded.state.trace.offsets = 3
    loaded.action_save_setup()
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["trace"]["offsets"] == 3
    assert data["name"] == "buck"


# ---------------------------------------------------------------- fiducials
def _fill_measured(page, transform):
    """Type a measured position per reference hole, via ``transform(x, y)``."""
    from PySide6.QtWidgets import QTableWidgetItem
    for r, (x, y) in enumerate(page._nominal):
        mx, my = transform(x, y)
        page.table.setItem(r, 3, QTableWidgetItem(f"{mx:.4f}"))
        page.table.setItem(r, 4, QTableWidgetItem(f"{my:.4f}"))


def test_a_fiducial_flip_can_be_measured_and_fitted(loaded, tmp_path):
    """Without pins there is nothing making the flip close, so the top traces
    an export writes are NOMINAL until the real position has been measured.
    This is the step that turns them into the real ones."""
    import math
    loaded.action_double_sided(True)
    loaded.action_registration("fiducial")
    loaded.export_to(tmp_path)
    before = (tmp_path / "buck_top_traces.nc").read_bytes()

    loaded.select_step("fitflip")
    page = loaded.flipfit_page
    assert loaded.inspector.stack.currentWidget() is page
    page._build()
    assert len(page._nominal) >= 2

    # the board landed 0.4 degrees round and 0.3 mm over
    th = math.radians(0.4)
    _fill_measured(page, lambda x, y: (x * math.cos(th) - y * math.sin(th) + 0.3,
                                       x * math.sin(th) + y * math.cos(th)))
    assert len(page.measured()) == len(page._nominal)
    assert page.fit_btn.isEnabled()
    assert "good" in page.verdict.text().lower()

    page._apply()
    after = (tmp_path / "buck_top_traces.nc").read_bytes()
    assert after != before, "the fit did not change the top traces"


def test_a_bad_fiducial_fit_says_do_not_cut(loaded, tmp_path):
    """The residual is the answer, not the fit — a rigid fit through a few
    points always produces a transform."""
    loaded.action_double_sided(True)
    loaded.action_registration("fiducial")
    loaded.select_step("fitflip")
    page = loaded.flipfit_page
    page._build()
    # one hole mis-probed by a millimetre: no rigid motion explains it
    _fill_measured(page, lambda x, y: (x, y))
    from PySide6.QtWidgets import QTableWidgetItem
    page.table.setItem(0, 3, QTableWidgetItem(f"{page._nominal[0][0] + 1.2:.4f}"))
    page._fit_preview()
    assert "too far out" in page.verdict.text().lower()


def test_the_plan_warns_that_top_traces_are_nominal_until_fitted(loaded):
    loaded.action_double_sided(True)
    loaded.action_registration("fiducial")
    step = loaded.plan.by_key("fitflip")
    assert step is not None
    assert "nominal" in step.caution.lower()
    keys = [s.key for s in loaded.plan]
    assert keys.index("flip") < keys.index("fitflip") < keys.index("top_traces")


def test_the_probe_grid_lands_on_the_copper_being_cut(loaded):
    """On a double-sided job the layout shifts the board to make room for the
    registration holes, so the board's own bounds are not where the copper is.
    A probe point that misses the copper is a bit descending until the runaway
    guard stops it."""
    loaded.action_double_sided(True)
    loaded.select_step("level")
    loaded.level_page.nx.setValue(4)
    loaded.level_page.ny.setValue(4)
    loaded.level_page._build()
    pts = loaded.level_page._points
    assert pts
    x0, y0, x1, y1 = loaded.work_bounds()
    for (x, y) in pts:
        assert x0 <= x <= x1 and y0 <= y <= y1, ((x, y), (x0, y0, x1, y1))


def test_the_key_never_lists_a_colour_that_is_not_on_screen(loaded):
    """A key listing colours the current view does not contain teaches the
    reader that the key is decoration, and then they stop reading it."""
    loaded.action_double_sided(True)
    loaded.select_step("bottom_traces")
    entries = dict((t, c) for c, t in loaded.stage._legend)
    assert "far face" not in entries, "the far face is only painted in X-ray"
    loaded._on_frame("xray")
    entries = dict((t, c) for c, t in loaded.stage._legend)
    assert "far face" in entries
    loaded._on_frame("bed")
    loaded.select_step("setup")
    entries = dict((t, c) for c, t in loaded.stage._legend)
    assert "cutting" not in entries, "no toolpath is drawn on the setup step"


def test_turning_on_double_sided_frames_the_registration_pins(loaded, qt_app):
    """The dowels sit OUTSIDE the board, in the waste the cut-out removes. A
    view framed on the board alone leaves one of them off the canvas, which is
    the one thing a person wants to look at when they turn this on."""
    loaded.action_double_sided(True)
    qt_app.processEvents()
    lay = loaded._ds_layout()
    assert lay is not None
    x0, y0, x1, y1 = loaded.stage._work_bounds()
    for (x, y, d) in lay.align_holes:
        assert x0 - 1e-6 <= x <= x1 + 1e-6 and y0 - 1e-6 <= y <= y1 + 1e-6


# ------------------------------------------------------------- one-bit jobs
def test_the_whole_interface_agrees_when_one_bit_does_the_job(loaded, tmp_path):
    """The lab profile is one 0.8 mm endmill for traces, holes and outline. The
    rail, the step page, the job header and the printed sheet must all say that
    once — and none of them may tell you to change a bit."""
    for job in (loaded.state.trace, loaded.state.drill, loaded.state.cutout):
        job.bit_diameter = 0.8
    loaded.refresh_plan()
    assert loaded.plan.single_tool

    # no hands-on step anywhere tells you to change the bit
    changes = [s for s in loaded.plan
               if s.kind == "handoff" and "change to" in s.title.lower()]
    assert not changes, [s.title for s in changes]

    # the job header states the tool as a fact about the job
    assert "0.80 mm flat endmill" in loaded.traveller.job_facts.text()

    # the step page stops telling you to re-zero after a bit change
    loaded.select_step("cutout_run")
    note = loaded.inspector.step.zero_note.text().lower()
    assert "never re-zero xy" in note
    assert "after every bit change" not in note

    # ...and so does the printed sheet
    loaded.export_to(tmp_path)
    text = loaded.sheet.text()
    assert "NEVER re-zero XY" in text
    assert "Z is zeroed once" in text
    assert "after every bit change" not in text.lower()


def test_a_two_tool_job_gets_its_bit_change_step_back(loaded):
    """The V-bit profile really does change tools, and then the step is real."""
    loaded.state.trace.tool_type = "vbit"
    loaded.refresh_plan()
    assert not loaded.plan.single_tool
    changes = [s for s in loaded.plan
               if s.kind == "handoff" and "change to" in s.title.lower()]
    assert len(changes) == 1
    assert "never re-zero xy" in changes[0].detail.lower()


# ----------------------------------------------------------- auto-placing
def _sheet_covering_the_bed(win):
    """Put the copper over the whole travel, for tests about CENTRING.

    Centring targets the copper, so a test about equal margins needs a sheet
    the job fits on - otherwise it is a test about a board too big for its
    stock, which is a different thing and has its own test. A sheet the size
    of the bed makes the two targets the same, which is what these assertions
    were written against.
    """
    bx, by = 203.2, 152.4
    win.action_stock(bx, by, 0.0, 0.0)


def _margins(win):
    """Room around the job, measured against what centring actually targets.

    Which is the COPPER, not the bed: centring on the machine's travel puts
    the job in the middle of the machine, and on a sheet clamped off to one
    side that is the middle of bare spoilboard. The sheet is clipped to the
    travel first, because metal the spindle cannot reach is no use either.
    """
    x0, y0, x1, y1 = win.job_extent()
    (tx0, ty0, tx1, ty1), _what = win._centring_target()
    return x0 - tx0, tx1 - x1, y0 - ty0, ty1 - y1   # left, right, front, back


def test_centring_puts_equal_margins_on_all_four_sides(loaded):
    """A board that nearly fills the bed does not want nudging into place a
    millimetre at a time — it wants centring, once."""
    _sheet_covering_the_bed(loaded)
    loaded.state.set_placement(3.0, 91.0)          # somewhere unhelpful
    loaded.action_autoplace()
    left, right, front, back = _margins(loaded)
    assert left == pytest.approx(right, abs=0.01)
    assert front == pytest.approx(back, abs=0.01)
    assert left > 0 and front > 0


def test_centring_counts_the_registration_pins(loaded):
    """The dowels sit outside the board, in the waste the cut-out removes. A
    placement that puts the board on the bed but a dowel off it is a job that
    cannot be run."""
    _sheet_covering_the_bed(loaded)
    loaded.action_double_sided(True)
    loaded.action_autoplace()
    lay = loaded._ds_layout()
    bx, by = 203.2, 152.4
    for (x, y, d) in lay.align_holes:
        r = d / 2.0
        assert 0 <= x - r and x + r <= bx, (x, d)
        assert 0 <= y - r and y + r <= by, (y, d)
    left, right, front, back = _margins(loaded)
    assert left == pytest.approx(right, abs=0.01)
    assert front == pytest.approx(back, abs=0.01)


def test_centring_leaves_the_pre_flight_check_happy(loaded):
    _sheet_covering_the_bed(loaded)
    loaded.state.set_placement(-40.0, 120.0)       # hanging off the bed
    loaded.action_autoplace()
    loaded.refresh_checks()
    off = [c for c in loaded._checks if c.title == "Off the bed"]
    assert not off, [c.detail for c in off]


def test_centring_an_oversized_job_says_so_rather_than_pretending(loaded,
                                                                  monkeypatch):
    """It still centres — sharing the overhang is the least-bad placement — but
    it does not report success."""
    said = []
    monkeypatch.setattr(loaded, "say",
                        lambda level, text: said.append((level, text)))
    monkeypatch.setattr(loaded, "job_extent", lambda: (0.0, 0.0, 260.0, 300.0))
    loaded.action_autoplace()
    assert said and said[-1][0] == "fail"
    assert "does not fit on" in said[-1][1]
    assert "rotating" in said[-1][1].lower()


def test_centring_reports_the_room_it_left(loaded):
    _sheet_covering_the_bed(loaded)
    said = []
    loaded.say = lambda level, text: said.append((level, text))
    loaded.action_autoplace()
    assert said[-1][0] == "ok"
    # It names what it centred ON, because the copper and the bed are
    # different targets and which one it used decides whether the job
    # landed on metal.
    assert "centred on the copper" in said[-1][1]
    assert "spare each side" in said[-1][1]


def test_centring_is_reachable_without_the_mouse(loaded):
    acts = [a for a in _control_texts(loaded) if "centre" in a.lower()]
    assert acts, "no control for centring"
    from PySide6.QtGui import QAction
    shortcut = [a.shortcut().toString() for a in loaded.findChildren(QAction)
                if "centre" in a.text().lower() and a.shortcut().toString()]
    assert shortcut, "centring has no keyboard shortcut"


# ------------------------------------------------------------------ _reveal
def test_reveal_spawns_no_file_manager_where_none_can_select(win, tmp_path,
                                                             monkeypatch):
    """On Linux there is no command that selects a file, so _reveal must not
    spawn anything - it falls through to Qt, which opens the parent folder.
    Spawning 'explorer' there is the bug this guards."""
    from gerber2rml.gui2 import window as window_mod
    from gerber2rml import platform as plat
    spawned = []
    monkeypatch.setattr(window_mod.subprocess, "Popen",
                        lambda cmd, *a, **k: spawned.append(cmd))
    monkeypatch.setattr(plat, "reveal_command", lambda p, platform=None: None)
    opened = []
    monkeypatch.setattr(window_mod.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url)))

    win._reveal(tmp_path / "board_traces.nc")

    assert spawned == []
    assert len(opened) == 1


def test_reveal_selects_the_file_where_the_file_manager_can(win, tmp_path,
                                                            monkeypatch):
    from gerber2rml.gui2 import window as window_mod
    from gerber2rml import platform as plat
    spawned = []
    monkeypatch.setattr(window_mod.subprocess, "Popen",
                        lambda cmd, *a, **k: spawned.append(cmd))
    monkeypatch.setattr(plat, "reveal_command",
                        lambda p, platform=None: ["explorer", "/select,", str(p)])

    win._reveal(tmp_path / "board_traces.nc")

    assert len(spawned) == 1
    assert spawned[0][0] == "explorer"
