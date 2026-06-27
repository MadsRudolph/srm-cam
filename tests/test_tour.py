import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import matplotlib
matplotlib.use("Agg")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from gerber2rml.gui.app import MainWindow
from gerber2rml.gui.tour import TourController
from gerber2rml.gui.tour.steps import TourStep, CORE_STEPS, BRANCHES
from gerber2rml.gui.tour.overlay import place_callout

_app = QApplication.instance() or QApplication([])


def _settings(tmp_path):
    return QSettings(str(tmp_path / "tour.ini"), QSettings.IniFormat)


# ---- pure placement helper ------------------------------------------------
def test_place_callout_prefers_below_when_it_fits():
    pos = place_callout((100, 100, 50, 20), (200, 80), (0, 0, 1000, 1000))
    assert pos == (100, 132)                     # ty + th + gap(12)


def test_place_callout_flips_off_a_bottom_edge():
    # 'below' would overflow the bottom -> a fitting side is chosen instead
    x, y = place_callout((10, 950, 40, 40), (100, 100), (0, 0, 1000, 1000),
                         preferred="below")
    assert 0 <= y and y + 100 <= 1000


def test_place_callout_clamps_when_too_big_to_fit():
    pos = place_callout((0, 0, 10, 10), (50, 50), (0, 0, 40, 40))
    x, y = pos
    assert x + 50 >= 40 - 1 and x <= 0          # clamped into the small bounds


# ---- step-list integrity (targets/signals resolve on the real window) -----
def test_core_steps_resolve_on_window():
    win = MainWindow()
    for st in CORE_STEPS:
        if st.target:
            assert hasattr(win, st.target), f"missing target {st.target}"
        if st.is_gated:
            attr, sig = st.advance_signal.split(".")
            assert hasattr(getattr(win, attr), sig), st.advance_signal


def test_branch_steps_resolve_on_window():
    win = MainWindow()
    for name, (page, steps) in BRANCHES.items():
        assert 0 <= page < win.sidebar.count()
        for st in steps:
            if st.target:
                assert hasattr(win, st.target), f"{name}: {st.target}"
            if st.reveal:
                assert hasattr(win, st.reveal)
            if st.is_gated:
                attr, sig = st.advance_signal.split(".")
                assert hasattr(getattr(win, attr), sig), f"{name}: {st.advance_signal}"


# ---- controller behaviour -------------------------------------------------
def test_start_builds_overlay_and_shows_first_step(tmp_path):
    win = MainWindow()
    tc = TourController(win, settings=_settings(tmp_path))
    tc.start()
    assert tc.active
    assert tc._i == 0
    assert tc._overlay is not None and tc._callout is not None
    tc.skip()
    assert not tc.active


def test_explain_then_gated_advance(tmp_path):
    win = MainWindow()
    tc = TourController(win, settings=_settings(tmp_path))
    tc.start()
    tc._next()                       # welcome -> load (explain)
    assert tc._i == 1
    tc._next()                       # load -> preset (gated)
    assert tc._i == 2 and tc._steps[2].is_gated
    win.apply_preset_btn.click()     # firing the gated signal advances the tour
    assert tc._i == 3
    tc.skip()


def test_skip_marks_seen(tmp_path):
    win = MainWindow()
    s = _settings(tmp_path)
    tc = TourController(win, settings=s)
    tc.start()
    tc.skip()
    assert s.value("tour/seen", False, type=bool) is True
    assert tc.has_seen()


def test_maybe_autostart_only_first_time(tmp_path):
    win = MainWindow()
    s = _settings(tmp_path)
    TourController(win, settings=s).maybe_autostart()   # fresh -> runs... check via new
    fresh = TourController(win, settings=_settings(tmp_path / "a"))
    fresh.maybe_autostart()
    assert fresh.active
    fresh.skip()

    s.setValue("tour/seen", True)
    seen = TourController(win, settings=s)
    seen.maybe_autostart()
    assert not seen.active


def test_missing_target_is_skipped(tmp_path):
    win = MainWindow()
    tc = TourController(win, settings=_settings(tmp_path))
    steps = [TourStep(target="no_such_widget_btn", title="x", body="y", explain_only=True),
             TourStep(target="load_btn", title="ok", body="z", explain_only=True)]
    tc.start(steps=steps)
    assert tc._i == 1                # first (missing) step auto-skipped
    tc.skip()


def test_core_end_offers_branches(tmp_path):
    win = MainWindow()
    tc = TourController(win, settings=_settings(tmp_path))
    tc.start()
    tc._offer_branches()
    assert tc._callout._menu_btns            # menu buttons present
    assert not tc._is_branch
    tc.skip()


def test_bed_leveling_branch_covers_hardware():
    page, steps = BRANCHES["Bed leveling"]
    assert page == 2
    titles = " ".join(s.title.lower() for s in steps)
    assert "arduino" in titles and "clip" in titles
    assert "coordinate" in titles and "g54" in titles                # coord-system cards
    assert steps[0].advance_signal == "connect_btn.clicked"           # connect gated
    assert any(s.advance_signal == "level_probe_btn.clicked" for s in steps)  # probe gated
    clip = next(s for s in steps if "clip" in s.title.lower())
    assert clip.target == "" and clip.explain_only                   # physical step
    body = " ".join(s.body.lower() for s in steps)
    assert "red" in body and "black" in body                         # clip polarity spelled out
    assert "machine" in body and "user" in body and "g54" in body    # three systems named
    assert "-50" in body or "−50" in body                       # machine-Z safety floor


def test_page_guide_buttons_jump_to_their_branch(tmp_path):
    win = MainWindow()
    win.tour.settings = _settings(tmp_path)        # don't touch real settings
    for btn, name in [(win.guide_level_btn, "Bed leveling"),
                      (win.guide_rework_btn, "Rework"),
                      (win.guide_double_btn, "Double-sided")]:
        btn.click()
        assert win.tour.active
        assert win.tour._steps == BRANCHES[name][1]   # started that section directly
        win.tour.skip()
        assert not win.tour.active


def test_start_branch_ignores_unknown_name(tmp_path):
    win = MainWindow()
    tc = TourController(win, settings=_settings(tmp_path))
    tc.start_branch("Nope")
    assert not tc.active


def test_branch_reveal_ticks_checkbox(tmp_path):
    win = MainWindow()
    win.double_sided_chk.setChecked(False)
    tc = TourController(win, settings=_settings(tmp_path))
    tc.start()
    tc._start_branch("Double-sided")
    assert tc._is_branch and tc._i == 0
    tc._next()                               # -> regmethod step (reveal=double_sided_chk)
    assert win.double_sided_chk.isChecked()
    tc.skip()
