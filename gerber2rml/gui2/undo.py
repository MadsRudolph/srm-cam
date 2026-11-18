"""Undo and redo for where a job sits on the bed.

A small stack of snapshots. A snapshot is whatever the page needs to put the
work back - a tuple or dict of numbers is enough; it is compared with ``==``
and never looked inside.

The page records the state *before* each change, and hands over the state
it has now when stepping back, so redo knows where to return to::

    undo = PlacementUndo()
    undo.push(page.snapshot())                  # just before a change
    ...
    snap = undo.undo(page.snapshot())           # Ctrl+Z
    if snap is not None:
        page.restore(snap)
    snap = undo.redo(page.snapshot())           # Ctrl+Shift+Z / Ctrl+Y

One drag is one step: push once when the drag starts, not per move. Steps
that arrive in a burst - a spin box held down, arrows nudged in a row - fold
into one when they pass the same ``merge`` key within ``merge_ms``::

    undo.push(before, merge="x")

``install(widget, on_undo, on_redo)`` adds the Ctrl+Z, Ctrl+Shift+Z and
Ctrl+Y actions to a widget and returns them; a text or number field with
the keyboard keeps its own Ctrl+Z (Qt hands the key to the field first).
``on_change`` (optional, settable later) is called whenever
``can_undo``/``can_redo`` may have changed, to enable an Undo button. The
stack itself has no Qt in it.
"""
import time

LIMIT = 100           # steps kept; the oldest goes first
MERGE_MS = 800        # pushes with the same merge key this close fold into one


class PlacementUndo:
    def __init__(self, on_change=None, *, limit=LIMIT, merge_ms=MERGE_MS,
                 clock=time.monotonic):
        self.on_change = on_change
        self._undo = []
        self._redo = []
        self._limit = limit
        self._merge_s = merge_ms / 1000.0
        self._clock = clock
        self._last_key = None
        self._last_t = 0.0
        self.restoring = False      # True while the page applies a snapshot

    def _changed(self):
        if self.on_change is not None:
            self.on_change()

    # ------------------------------------------------------------ recording
    def push(self, before, *, merge=None):
        """Record ``before``, the state just ahead of a change. Ignored while
        a snapshot is being restored (the restore is not a new change)."""
        if self.restoring:
            return
        now = self._clock()
        if (merge is not None and merge == self._last_key and self._undo
                and now - self._last_t <= self._merge_s):
            self._last_t = now          # still the same burst: keep its start
            return
        if self._undo and self._undo[-1] == before and merge is None:
            return
        self._undo.append(before)
        del self._undo[:-self._limit]
        self._redo.clear()
        self._last_key, self._last_t = merge, now
        self._changed()

    def break_merge(self):
        """The next push starts a new step whatever its merge key."""
        self._last_key = None

    def clear(self):
        self._undo.clear()
        self._redo.clear()
        self._last_key = None
        self._changed()

    # -------------------------------------------------------------- stepping
    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self, current):
        """The snapshot to go back to, or None. ``current`` goes on redo."""
        while self._undo:
            snap = self._undo.pop()
            if snap == current:         # a step that changed nothing
                continue
            self._redo.append(current)
            self._last_key = None
            self._changed()
            return snap
        self._changed()
        return None

    def redo(self, current):
        """The snapshot undone last, or None. ``current`` goes back on undo."""
        if not self._redo:
            return None
        snap = self._redo.pop()
        self._undo.append(current)
        self._last_key = None
        self._changed()
        return snap


def editing_text():
    """True when the keyboard is in a field that has an undo of its own."""
    from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox,
                                   QLineEdit, QPlainTextEdit, QTextEdit)
    w = QApplication.focusWidget()
    return isinstance(w, (QLineEdit, QAbstractSpinBox, QTextEdit,
                          QPlainTextEdit)) or (
        isinstance(w, QComboBox) and w.isEditable())


def install(widget, on_undo, on_redo):
    """Ctrl+Z, Ctrl+Shift+Z and Ctrl+Y on ``widget`` and its children.
    Returns ``(undo_action, redo_action)``."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QKeySequence
    undo_act = QAction("Undo", widget)
    undo_act.setShortcuts([QKeySequence(QKeySequence.Undo)])
    redo_act = QAction("Redo", widget)
    redo_act.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
    for act, fn in ((undo_act, on_undo), (redo_act, on_redo)):
        act.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        act.triggered.connect(lambda _c=False, fn=fn: None if editing_text() else fn())
        widget.addAction(act)
    return undo_act, redo_act
