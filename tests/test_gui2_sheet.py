"""The sheet: a headline, a body, an action row — and who gets the slack."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QScrollArea  # noqa: E402

from gerber2rml.gui2.dialogs import Sheet  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _sheet(app, widget, *, grow):
    d = Sheet(None, "A headline", width=400)
    d.say("An introduction that stays its own height.")
    d.add(widget, grow=grow)
    d.act("Close", on=d.accept)
    d.show()
    app.processEvents()
    d.resize(400, 300)
    app.processEvents()
    return d


def _rows():
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(QLabel("\n".join(f"row {i}" for i in range(60))))
    sa.setMaximumHeight(2000)
    return sa


def test_a_growing_list_takes_all_the_vertical_slack(app):
    sa = _rows()
    d = _sheet(app, sa, grow=True)
    before = sa.height()
    d.resize(400, 500)
    app.processEvents()
    assert sa.height() >= before + 190, (before, sa.height())
    d.close()


def test_without_grow_an_expanding_widget_only_shares_it(app):
    # The band under the tier sheet's list: Qt deals slack between an
    # expanding widget and the stretch below it. grow=True is the fix.
    #
    # Without grow the list stops at its own size hint and the stretch below
    # takes the rest. Qt makes that hint 24 lines of the widget's font, so
    # where it lands depends on the face: 312 px with the Windows default,
    # 360 px with the macOS one. The sheet is therefore made tall enough
    # (400 px of slack) that the hint is passed whichever font is in use; at
    # 200 px the macOS list had not reached its hint yet and looked as if it
    # were taking everything.
    sa = _rows()
    d = _sheet(app, sa, grow=False)
    before = sa.height()
    d.resize(400, 700)
    app.processEvents()
    assert before < sa.height() < before + 390, (before, sa.height())
    assert sa.height() <= sa.sizeHint().height()
    d.close()


def test_a_run_of_labels_keeps_its_heights(app):
    lb = QLabel("one line of body text")
    d = _sheet(app, lb, grow=False)
    before = lb.height()
    d.resize(400, 500)
    app.processEvents()
    assert lb.height() == before, (before, lb.height())
    d.close()
