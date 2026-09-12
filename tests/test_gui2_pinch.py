"""The narrow-gap override in the second interface: the control, and what the
app says once it is on.

The engine side is covered in test_pinch.py. What matters here is that the
operator can reach it, and that with it on the app stops calling the gaps
shorts — they are cut — and starts naming what the cut costs instead.
"""
from pathlib import Path

import pytest
from PySide6.QtWidgets import QCheckBox

from gerber2rml.gui2.window import MainWindow

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


def _boxes(win):
    return win.inspector.step.findChildren(QCheckBox)


def _box(win):
    for b in _boxes(win):
        if "narrow" in b.text().lower():
            return b
    return None


def test_the_traces_step_offers_the_override(loaded, qt_app):
    loaded.select_step("traces_run")
    box = _box(loaded)
    assert box is not None, [b.text() for b in _boxes(loaded)]
    assert not box.isChecked(), "it has to be asked for"
    assert "trims pads" in box.text().lower()


def test_ticking_it_reaches_the_job(loaded, qt_app):
    loaded.select_step("traces_run")
    box = _box(loaded)
    box.setChecked(True)
    assert loaded.state.trace.cut_pinches is True
    box.setChecked(False)
    assert loaded.state.trace.cut_pinches is False


def test_the_drill_step_does_not_offer_it(loaded, qt_app):
    # It is an isolation decision; a drill has no gaps to squeeze into.
    loaded.select_step("drill_run")
    assert _box(loaded) is None


def test_the_banner_stops_calling_them_shorts_once_they_are_cut(loaded, qt_app):
    loaded.state.trace.bit_diameter = 0.8      # wide enough to bridge this board
    loaded.refresh_checks()
    assert loaded._shorts, "the fixture should show shorts with a 0.8 mm bit"
    loaded._sync_banner()
    banner = loaded.traveller.banner
    before = banner.head.text()

    loaded.state.trace.cut_pinches = True
    loaded.refresh_checks()
    loaded._sync_banner()
    after = banner.head.text()

    assert "shorted" in before.lower()
    assert "shorted" not in after.lower()
    assert "cut through" in after.lower()
    assert "nothing is left shorted" in banner.detail.text().lower()


def test_the_checks_page_names_the_price_instead_of_the_short(loaded, qt_app):
    loaded.state.trace.bit_diameter = 0.8
    loaded.state.trace.cut_pinches = True
    loaded.refresh_checks()
    titles = {c.title for c in loaded._checks}
    assert "Narrow gaps cut through" in titles
    assert "Nets closer than the bit" not in titles
    detail = next(c.detail for c in loaded._checks
                  if c.title == "Narrow gaps cut through")
    assert "mm" in detail and "pads" in detail.lower()


def test_the_banner_never_outlives_the_setting_it_describes(loaded, qt_app,
                                                            monkeypatch):
    """A failing pre-flight must not leave the old headline standing.

    The banner said "41 narrow gaps cut through" while the box that turns
    that on was unticked: the checks had raised, returned early, and skipped
    the banner, so it still described the previous setting.
    """
    from gerber2rml.engine import diagnostics as diag
    loaded.state.trace.bit_diameter = 0.8
    loaded.state.trace.cut_pinches = True
    loaded.refresh_checks()
    assert "cut through" in loaded.traveller.banner.head.text().lower()

    loaded.state.trace.cut_pinches = False
    monkeypatch.setattr(loaded, "report_error", lambda *a, **kw: None)
    monkeypatch.setattr(diag, "preflight",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    loaded.refresh_checks()
    assert "cut through" not in loaded.traveller.banner.head.text().lower()
    assert "shorted" in loaded.traveller.banner.head.text().lower()
