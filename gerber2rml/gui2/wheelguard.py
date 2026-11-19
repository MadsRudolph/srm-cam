"""The mouse wheel scrolls the page; it never changes a value by accident.

Qt's spin boxes, combo boxes and sliders take the wheel the moment the
pointer is over them, focused or not. Scrolling down a side panel full of
them, the wheel catches one on the way past and turns a depth, a power or a
speed without a word - "very annoying and very easy to do" (2026-11-19), and
at a mill or a laser, worse than annoying.

So, for the whole application at once (:func:`install`):

* those controls no longer take keyboard focus from the wheel - a click or
  Tab does it (``Qt.StrongFocus`` in place of ``Qt.WheelFocus``);
* the wheel changes one only while it has focus - after a click into it;
* otherwise the wheel goes on to whatever holds the control, so the panel
  under the pointer scrolls as if the control were not there.

Views that zoom with the wheel (the bed, the laser page, the 3D view) are
none of these and are untouched; neither are scroll bars.
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider,
                               QAbstractSpinBox, QApplication,
                               QComboBox, QScrollBar)


def _guarded(w):
    """The value control ``w`` is, or is inside (a spin box's line edit)."""
    for _ in range(2):
        if w is None:
            return None
        if isinstance(w, (QAbstractSpinBox, QComboBox)) or (
                isinstance(w, QAbstractSlider) and not isinstance(w, QScrollBar)):
            return w
        w = w.parentWidget()
    return None


class WheelGuard(QObject):
    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Polish:
            w = _guarded(obj) if obj.isWidgetType() else None
            if w is obj and w.focusPolicy() == Qt.WheelFocus:
                w.setFocusPolicy(Qt.StrongFocus)
            return False
        if t != QEvent.Wheel or not obj.isWidgetType():
            return False
        w = _guarded(obj)
        if w is None or w.hasFocus():
            return False
        # Not this control's: to the scroll area holding it, which scrolls.
        # Sent straight there - an event sent on from a filter does not
        # travel up the parents by itself as the original would have.
        area = w.parentWidget()
        while area is not None and not isinstance(area, QAbstractScrollArea):
            area = area.parentWidget()
        if area is not None:
            QApplication.sendEvent(area.viewport(), event)
        return True


_GUARD = None


def install(app=None):
    """Guard every value control in ``app`` (the running application). Safe
    to call more than once."""
    global _GUARD
    app = app or QApplication.instance()
    if app is None or _GUARD is not None:
        return _GUARD
    _GUARD = WheelGuard(app)
    app.installEventFilter(_GUARD)
    return _GUARD
