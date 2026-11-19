"""The wheel never changes a value box it merely passes over (2026-11-19)."""
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox,
                               QScrollArea, QScrollBar, QVBoxLayout, QWidget)

from gerber2rml.gui2 import wheelguard


def _wheel(w, down=True):
    dy = -120 if down else 120
    e = QWheelEvent(QPointF(5, 5), QPointF(w.mapToGlobal(QPoint(5, 5))),
                    QPoint(0, 0), QPoint(0, dy), Qt.NoButton, Qt.NoModifier,
                    Qt.NoScrollPhase, False)
    QApplication.sendEvent(w, e)


def _panel(qt_app):
    wheelguard.install(qt_app)
    area = QScrollArea()
    inner = QWidget()
    v = QVBoxLayout(inner)
    spin = QDoubleSpinBox()
    spin.setRange(0, 100)
    spin.setValue(50)
    combo = QComboBox()
    combo.addItems(["a", "b", "c"])
    v.addWidget(spin)
    v.addWidget(combo)
    for _ in range(40):
        v.addWidget(QDoubleSpinBox())
    area.setWidget(inner)
    area.resize(200, 150)
    area.show()
    qt_app.processEvents()
    return area, spin, combo


def test_passing_over_a_box_scrolls_the_panel_not_the_value(qt_app):
    area, spin, combo = _panel(qt_app)
    _wheel(spin)
    _wheel(spin.lineEdit())
    _wheel(combo)
    qt_app.processEvents()
    assert spin.value() == 50
    assert combo.currentIndex() == 0
    assert area.verticalScrollBar().value() > 0      # the panel scrolled
    area.close()


def test_a_box_clicked_into_still_takes_the_wheel(qt_app):
    area, spin, combo = _panel(qt_app)
    from PySide6.QtTest import QTest
    area.activateWindow()
    qt_app.processEvents()
    QTest.mouseClick(spin.lineEdit(), Qt.LeftButton)   # clicked into
    qt_app.processEvents()
    _wheel(spin, down=False)
    assert spin.value() == 51
    area.close()


def test_the_wheel_no_longer_gives_a_box_focus(qt_app):
    area, spin, combo = _panel(qt_app)
    assert spin.focusPolicy() == Qt.StrongFocus
    assert combo.focusPolicy() == Qt.StrongFocus
    area.close()


def test_scroll_bars_are_left_alone(qt_app):
    wheelguard.install(qt_app)
    bar = QScrollBar(Qt.Vertical)
    bar.setRange(0, 100)
    bar.show()
    qt_app.processEvents()
    _wheel(bar)
    assert bar.value() > 0
    bar.close()


def test_focus_a_window_gave_on_opening_does_not_arm_a_box(qt_app):
    area, spin, combo = _panel(qt_app)
    spin.setFocus(Qt.ActiveWindowFocusReason)
    qt_app.processEvents()
    _wheel(spin)
    assert spin.value() == 50
    area.close()
