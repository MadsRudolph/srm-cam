"""The visual layer of the tour: a dim spotlight scrim and a callout box.

The scrim (:class:`Spotlight`) covers the window, dims everything except a
cut-out around the current target, and is *transparent to mouse events* — so
every click passes straight through to the real UI underneath. That is what
lets the gated steps work: the user clicks the actual button, not the overlay.
Only the :class:`Callout` (a normal sibling widget raised above the scrim)
takes input, for its Back / Next / Skip buttons.

:func:`place_callout` is the pure geometry helper that picks which side of the
target the callout sits on; it works on plain tuples so it can be unit-tested
without a running Qt app.
"""
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QColor, QPen

_ACCENT = "#FF9800"
_PAD = 6            # px of breathing room the cut-out leaves around the target
_GAP = 12           # px between the target and the callout


def place_callout(target, size, bounds, preferred="auto", margin=_GAP):
    """Top-left (x, y) for a callout of ``size`` (w, h) next to ``target``
    (x, y, w, h), kept inside ``bounds`` (x, y, w, h).

    Tries the preferred side first, then below/above/right/left; returns the
    first that fits fully. If none fit, clamps the preferred side's position
    into ``bounds`` so the callout is always at least visible. Pure — tuples in,
    tuple out."""
    tx, ty, tw, th = target
    cw, ch = size
    bx, by, bw, bh = bounds
    sides = (["below", "above", "right", "left"] if preferred in ("auto", None)
             else [preferred, "below", "above", "right", "left"])

    def pos_for(side):
        if side == "below":
            return (tx, ty + th + margin)
        if side == "above":
            return (tx, ty - ch - margin)
        if side == "right":
            return (tx + tw + margin, ty)
        return (tx - cw - margin, ty)          # left

    def inside(x, y):
        return bx <= x and by <= y and x + cw <= bx + bw and y + ch <= by + bh

    for side in sides:
        x, y = pos_for(side)
        if inside(x, y):
            return (x, y)
    x, y = pos_for(sides[0])
    x = min(max(x, bx), bx + bw - cw)
    y = min(max(y, by), by + bh - ch)
    return (x, y)


class Spotlight(QWidget):
    """Translucent scrim that dims the window except around ``_spot``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)   # never eat clicks
        self.setAttribute(Qt.WA_TranslucentBackground, True)       # show app through
        self._spot = None        # QRect in local coords, or None for a flat dim

    def set_spot(self, rect):
        self._spot = rect
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dim = QColor(0, 0, 0, 150)
        full = self.rect()
        if self._spot is None:
            p.fillRect(full, dim)
            return
        r = self._spot.adjusted(-_PAD, -_PAD, _PAD, _PAD)
        # dim the four bands around the cut-out; leave the cut-out fully clear
        p.fillRect(QRect(0, 0, full.width(), r.top()), dim)                          # above
        p.fillRect(QRect(0, r.bottom(), full.width(), full.height() - r.bottom()), dim)  # below
        p.fillRect(QRect(0, r.top(), r.left(), r.height()), dim)                     # left
        p.fillRect(QRect(r.right(), r.top(), full.width() - r.right(), r.height()), dim)  # right
        pen = QPen(QColor(_ACCENT))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 8, 8)


_CALLOUT_QSS = f"""
QFrame#tourCallout {{
    background: #242424;
    border: 2px solid {_ACCENT};
    border-radius: 10px;
}}
QFrame#tourCallout QLabel {{ color: #e4e4e6; background: transparent; }}
QLabel#tourTitle {{ color: {_ACCENT}; font-size: 15px; font-weight: 600; }}
QLabel#tourCounter {{ color: #8a8a8a; font-size: 11px; }}
"""


class Callout(QFrame):
    """The text box with Back / Next / Skip (step mode) or custom buttons
    (menu mode). The controller swaps the ``on_back``/``on_next``/``on_skip``
    callbacks per step; menu buttons carry their own callbacks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tourCallout")
        self.setStyleSheet(_CALLOUT_QSS)
        self.setMaximumWidth(360)
        self.on_back = self.on_next = self.on_skip = lambda: None

        self.counter_lbl = QLabel(objectName="tourCounter")
        self.title_lbl = QLabel(objectName="tourTitle")
        self.title_lbl.setWordWrap(True)
        self.body_lbl = QLabel()
        self.body_lbl.setWordWrap(True)

        self.back_btn = QPushButton("Back")
        self.next_btn = QPushButton("Next")
        self.skip_btn = QPushButton("Skip tour")
        self.next_btn.setObjectName("primaryBtn")
        self.back_btn.clicked.connect(lambda: self.on_back())
        self.next_btn.clicked.connect(lambda: self.on_next())
        self.skip_btn.clicked.connect(lambda: self.on_skip())

        self._btnbar = QHBoxLayout()
        self._btnbar.addWidget(self.skip_btn)
        self._btnbar.addStretch(1)
        self._btnbar.addWidget(self.back_btn)
        self._btnbar.addWidget(self.next_btn)
        self._menu_btns = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(self.counter_lbl)
        lay.addWidget(self.title_lbl)
        lay.addWidget(self.body_lbl)
        lay.addLayout(self._btnbar)

    def _clear_menu(self):
        while self._menu_btns:
            b = self._menu_btns.pop()
            b.setParent(None)
            b.deleteLater()

    def show_step(self, title, body, counter, next_enabled, can_back):
        self._clear_menu()
        self.counter_lbl.setText(counter)
        self.counter_lbl.setVisible(True)
        self.title_lbl.setText(title)
        self.body_lbl.setText(body)
        for b in (self.back_btn, self.next_btn, self.skip_btn):
            b.setVisible(True)
        self.back_btn.setEnabled(can_back)
        self.next_btn.setEnabled(next_enabled)
        self.adjustSize()

    def show_menu(self, title, body, buttons):
        """``buttons``: list of (label, callback)."""
        self._clear_menu()
        self.counter_lbl.setVisible(False)
        self.title_lbl.setText(title)
        self.body_lbl.setText(body)
        for b in (self.back_btn, self.next_btn, self.skip_btn):
            b.setVisible(False)
        for label, cb in buttons:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, cb=cb: cb())
            self._btnbar.insertWidget(self._btnbar.count() - 0, btn)
            self._menu_btns.append(btn)
        self.adjustSize()
