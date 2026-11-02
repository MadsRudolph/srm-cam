"""The jog pad: X, Y and Z on one small cross, in the machine bar.

The way to move the head by hand: click an arrow, or light Keys and use the
keyboard while you watch the bit - the arrow keys for X and Y, Page Up and Page
Down for Z. Every move is relative and does not lift
(:meth:`machine.MachineLink.jog_by`), so stepping across the bed leaves the bit
at the height it was set to. Click to jog is the other way to move, for a long
trip to a spot on the stage, and lifts first.

The pad only says what was asked for. The bar and the window decide whether it
may happen - the bit on the copper, the edge of the travel - so the arrows, the
keys and the stage all answer to the same rules.
"""
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
                               QButtonGroup, QPushButton)

from gerber2rml.gui2 import theme, widgets

STEPS = (0.01, 0.1, 1.0, 10.0)
DEFAULT_STEP = 1.0
BTN = 19                # px: three of these and their gaps fill the bar's row
Z_DOWN_MAX = 1.0        # mm: one press never takes the bit down further

# The arrow keys' meaning, as (x, y) directions. Up is +Y, away from you.
KEY_DIRECTIONS = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0),
                  Qt.Key_Up: (0, 1), Qt.Key_Down: (0, -1)}


class JogPad(QWidget):
    xy_requested = Signal(float, float)   # mm, relative
    z_requested = Signal(int)             # +1 up, -1 down
    keys_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(1)
        self.xy = {}
        for (dx, dy), text, cell, tip in (
                ((0, 1), "▲", (0, 1), "+Y, away from you. Up arrow with Arrow keys "
                                      "lit."),
                ((-1, 0), "◀", (1, 0), "-X, left. Left arrow with Arrow keys lit."),
                ((1, 0), "▶", (1, 2), "+X, right. Right arrow with Arrow keys lit."),
                ((0, -1), "▼", (2, 1), "-Y, toward you. Down arrow with Arrow keys "
                                       "lit.")):
            b = self._key(text, tip)
            b.clicked.connect(lambda _c=False, d=(dx, dy): self._xy(d))
            self.xy[(dx, dy)] = b
            grid.addWidget(b, *cell)
        centre = widgets.eyebrow("XY")
        centre.setAlignment(Qt.AlignCenter)
        grid.addWidget(centre, 1, 1)
        h.addLayout(grid)

        z = QVBoxLayout()
        z.setContentsMargins(0, 0, 0, 0)
        z.setSpacing(1)
        self.z_up = self._key("▲", "Raise the bit one step. Page Up does the "
                                   "same. Raising always works.")
        self.z_down = self._key("▼", "Lower the bit one step, at most "
                                     "%g mm. Page Down does the same. Refused "
                                     "while the Z readout says Touch."
                                % Z_DOWN_MAX)
        self.z_up.clicked.connect(lambda: self.z_requested.emit(+1))
        self.z_down.clicked.connect(lambda: self.z_requested.emit(-1))
        label = widgets.eyebrow("Z")
        label.setAlignment(Qt.AlignCenter)
        z.addWidget(self.z_up)
        z.addWidget(label)
        z.addWidget(self.z_down)
        h.addLayout(z)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(2)
        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(1)
        self.step_group = QButtonGroup(self)
        self.step_group.setExclusive(True)
        self.chips = {}
        for s in STEPS:
            b = QPushButton("%g" % s)
            b.setObjectName("key")
            b.setCheckable(True)
            b.setFixedHeight(BTN + 4)
            b.setMinimumWidth(34)
            b.setFont(theme.font("small"))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip("Each press moves %g mm." % s)
            b.setChecked(s == DEFAULT_STEP)
            self.step_group.addButton(b)
            self.chips[s] = b
            chips.addWidget(b)
        side.addLayout(chips)
        self.keys_btn = widgets.button(
            "Arrow keys",
            tip="While this is lit, the arrow keys move the head in X and Y "
                "anywhere in the window, except while you are typing in a "
                "box. Shift is ten times the step, Ctrl a tenth. Page Up and "
                "Page Down move Z. It goes off by itself on STOP, on "
                "disconnect and when a run starts.")
        self.keys_btn.setObjectName("jogkeys")
        self.keys_btn.setCheckable(True)
        self.keys_btn.setFixedHeight(BTN + 8)
        self.keys_btn.toggled.connect(self.keys_toggled)
        side.addWidget(self.keys_btn)
        h.addLayout(side)

        self._flashing = None
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(120)
        self._flash_timer.timeout.connect(self._end_flash)

    @staticmethod
    def _key(text, tip):
        b = widgets.button(text, kind="key", tip=tip)
        b.setFixedSize(BTN, BTN)
        return b

    def step(self):
        for s, b in self.chips.items():
            if b.isChecked():
                return s
        return DEFAULT_STEP

    def z_step(self, direction):
        """One Z press, mm. Up takes the whole step; down never more than
        ``Z_DOWN_MAX``: ten millimetres down is how a bit meets the copper."""
        s = self.step()
        return s if direction > 0 else min(s, Z_DOWN_MAX)

    def keys_on(self):
        return self.keys_btn.isChecked()

    def _xy(self, direction, factor=1.0):
        size = self.step() * factor
        self.xy_requested.emit(direction[0] * size, direction[1] * size)

    def press_key(self, key, modifiers=Qt.NoModifier):
        """An arrow key with Arrow keys lit. True when it was one of ours."""
        direction = KEY_DIRECTIONS.get(key)
        if direction is None:
            return False
        factor = (10.0 if modifiers & Qt.ShiftModifier else
                  0.1 if modifiers & Qt.ControlModifier else 1.0)
        self._flash(self.xy[direction])
        self._xy(direction, factor)
        return True

    def _flash(self, button):
        """Show which arrow the key just pressed."""
        self._end_flash()
        button.setDown(True)
        self._flashing = button
        self._flash_timer.start()

    def _end_flash(self):
        if self._flashing is not None:
            self._flashing.setDown(False)
            self._flashing = None
