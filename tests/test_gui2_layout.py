"""The rail is a fixed width, so everything put in it has to fit that width.

The left rail is pinned to 316 px. A finding banner with a button beside its
headline asked for 572, the rail could not grow to meet it and there is no
horizontal scrolling, so the steps either side were simply cut off - reported
from the lab as "a lot of text and buttons are not visible".

Nothing here checks how it looks. It checks the one thing that made the app
unusable: that no widget in the rail is asked to draw itself in less room than
it needs.
"""
from pathlib import Path

import pytest
from PySide6.QtWidgets import QWidget

from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def win(qt_app):
    w = MainWindow()
    w.resize(1680, 1010)          # the lab PC's screen, maximised
    yield w
    w.close()


def _cramped(panel):
    """[(short_by, widget)] for everything on show that does not fit."""
    out = []
    for c in panel.findChildren(QWidget):
        if not c.isVisible():
            continue
        short = c.minimumSizeHint().width() - c.width()
        if short > 1:
            out.append((short, c))
    return sorted(out, key=lambda t: -t[0])


def test_the_rail_fits_a_finding_on_a_two_board_sheet(win, qt_app):
    win.load_folder(str(FIXT))
    win.state.add_board(str(FIXT))
    win.state.trace.bit_diameter = 0.8        # wide enough to raise a finding
    win.refresh_plan()
    win.refresh_checks()
    win.refresh_preview()
    win.show()
    qt_app.processEvents()
    qt_app.processEvents()

    assert win.traveller.banner.head.text(), "expected a finding to be showing"
    cramped = _cramped(win.traveller)
    assert not cramped, (
        f"{len(cramped)} widget(s) clipped, worst short by {cramped[0][0]} px: "
        f"{type(cramped[0][1]).__name__}")


def test_the_banner_headline_wraps_rather_than_widening_the_rail(win, qt_app):
    win.load_folder(str(FIXT))
    win.show()
    qt_app.processEvents()
    banner = win.traveller.banner
    banner.show_finding("fail", "26 spots will be shorted",
                        "Worst gap 0.45 mm against a 0.80 mm cutter.",
                        action="See the checks")
    qt_app.processEvents()
    assert banner.head.wordWrap()
    assert banner.minimumSizeHint().width() <= win.traveller.width(), (
        "the banner must fit the rail it lives in")
