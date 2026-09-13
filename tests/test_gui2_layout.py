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


def _page_widths(qt_app, boards, name):
    """{step key: width its side-panel page asks for} for one job."""
    from PySide6.QtWidgets import QScrollArea
    w = MainWindow()
    w.resize(1680, 1010)
    w.load_folder(str(FIXT))
    for _ in range(boards - 1):
        w.state.add_board(str(FIXT))
    w.state.name = name
    w.refresh_plan()
    w.refresh_checks()
    w.refresh_preview()
    w.show()
    qt_app.processEvents()
    out = {}
    for step in w.plan.steps:
        w.select_step(step.key)
        qt_app.processEvents()
        qt_app.processEvents()
        page = w.inspector.stack.currentWidget()
        sa = page if isinstance(page, QScrollArea) else page.findChild(QScrollArea)
        if sa is not None and sa.widget() is not None:
            out[step.key] = sa.widget().minimumSizeHint().width()
    w.close()
    return out


def test_no_side_panel_page_widens_for_a_sheet_or_a_long_name(qt_app):
    """The pages must not grow with the job.

    Two boards put four placement buttons abreast, and a two-board job's file
    name ("feedback_circuit+feedback_circuit_2_airpass.nc") has nothing to wrap
    at; each laid the side panel out wider than it is, and since it does not
    scroll sideways every hint and button past the edge was cut off mid-word.

    Compared against the same page on a plain one-board job rather than a
    pixel count: the test platform's fonts are far wider than Windows', and
    what went wrong was the growth, not the number.
    """
    plain = _page_widths(qt_app, 1, "buck")
    sheet = _page_widths(qt_app, 2, "feedback_circuit+feedback_circuit_2")
    for key, width in sheet.items():
        if key in plain:
            # 5%: the two-by-two grid is as wide as its widest label, a few
            # px. The four abreast it replaced was +80%, the file name +30%.
            assert width <= plain[key] * 1.05, (
                f"{key}: {width} px on a two-board sheet, {plain[key]} px alone")


def test_the_placement_buttons_are_two_by_two(win, qt_app):
    from PySide6.QtWidgets import QGridLayout
    setup = win.inspector.setup
    grid = setup.autoplace_btn.parentWidget().layout()
    assert isinstance(grid, QGridLayout)
    spots = {b: grid.getItemPosition(grid.indexOf(b))[:2]
             for b in (setup.autoplace_btn, setup.centre_copper_btn,
                       setup.arrange_btn, setup.butt_btn)}
    assert sorted(spots.values()) == [(0, 0), (0, 1), (1, 0), (1, 1)]


def test_a_file_name_gives_up_characters_not_width(qt_app):
    from gerber2rml.gui2.widgets import ElidedLabel
    name = "feedback_circuit+feedback_circuit_2_airpass.nc — not written yet"
    label = ElidedLabel(name)
    assert label.minimumSizeHint().width() <= 20
    label.resize(120, 20)
    assert label.text() == name, "text() is the whole name, for anything that reads it"
    assert label.toolTip() == name
