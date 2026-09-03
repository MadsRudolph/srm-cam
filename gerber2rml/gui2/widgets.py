"""The small parts everything else is assembled from.

Kept in one file so the type scale and the spacing system are applied once
rather than per panel. Every label in the application goes through one of these
constructors, which is what stops the scale collapsing back to "13 px, four
weights" as the app grows.

There are no icon fonts and no emoji here. The handful of glyphs that earn
their place (a chevron, a state dot, a caution mark) are drawn with
:class:`QPainter` at the size they are used, so they stay sharp and stay
monochrome unless they are carrying a status.
"""
from PySide6.QtCore import Qt, QSize, QRectF, Signal, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPainterPath, QPolygonF
from PySide6.QtWidgets import (
    QLabel, QFrame, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSizePolicy,
    QGraphicsOpacityEffect, QButtonGroup)

from gerber2rml.gui2 import theme


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def _label(text, role, obj, *, wrap=False, colour=None, mono=False):
    lb = QLabel(text)
    lb.setObjectName(obj)
    lb.setFont(theme.font(role, mono=mono))
    lb.setWordWrap(wrap)
    if colour:
        lb.setStyleSheet(f"color: {colour};")
    return lb


def eyebrow(text):
    """A tracked all-caps section label. The smallest type in the app, and the
    only thing allowed to be set in caps — caps are a structural signal here,
    not emphasis."""
    return _label(text, "label", "eyebrow")


def title(text):
    return _label(text, "title", "title")


def head(text):
    return _label(text, "head", "head")


def body(text, *, wrap=True):
    return _label(text, "body", "value", wrap=wrap)


def hint(text, *, wrap=True):
    return _label(text, "small", "hint", wrap=wrap)


def micro(text):
    return _label(text, "micro", "unit")


def mono(text, *, strong=False):
    return _label(text, "small", "monoHi" if strong else "mono", mono=True)


def value(text, *, role="head"):
    return _label(text, role, "value")


def empty_note(text):
    return _label(text, "body", "empty", wrap=True)


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def rule(*, strong=False):
    f = QFrame()
    f.setObjectName("ruleStrong" if strong else "rule")
    f.setFixedHeight(1)
    return f


def vrule():
    f = QFrame()
    f.setObjectName("ruleV")
    f.setFixedWidth(1)
    return f


def spacer(h=None, w=None):
    s = QWidget()
    if h is not None:
        s.setFixedHeight(h)
    if w is not None:
        s.setFixedWidth(w)
    if h is None and w is None:
        s.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return s


def stretch():
    s = QWidget()
    s.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    return s


class Card(QFrame):
    """A panel that groups things. One level of nesting only — a card inside a
    card is a sign the grouping is wrong, and it reads as noise."""

    def __init__(self, *, quiet=False, pad=None, gap=None, parent=None):
        super().__init__(parent)
        self.setObjectName("cardQuiet" if quiet else "card")
        p = theme.GAP_M if pad is None else pad
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(p, p, p, p)
        self.box.setSpacing(theme.GAP_S if gap is None else gap)

    def add(self, w):
        self.box.addWidget(w)
        return w

    def row(self, *widgets, gap=None, margins=(0, 0, 0, 0)):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(*margins)
        h.setSpacing(theme.GAP_S if gap is None else gap)
        for item in widgets:
            if item is None:
                h.addStretch(1)
            else:
                h.addWidget(item)
        self.box.addWidget(w)
        return w


class Section(QWidget):
    """An eyebrow, a hairline, and whatever you put under it.

    This is the whole hierarchy mechanism in the panels: a label the size of a
    caption, a rule, and generous space. No boxes, no accent bars.
    """

    def __init__(self, name, *, parent=None, gap=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.GAP_S)
        headrow = QWidget()
        h = QHBoxLayout(headrow)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        self.label = eyebrow(name)
        h.addWidget(self.label)
        h.addWidget(rule(), 1)
        v.addWidget(headrow)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(theme.GAP_S if gap is None else gap)
        v.addLayout(self.body)

    def add(self, w):
        self.body.addWidget(w)
        return w

    def add_layout(self, lay):
        self.body.addLayout(lay)
        return lay


# ---------------------------------------------------------------------------
# Status marks
# ---------------------------------------------------------------------------

STATE_COLOURS = {
    "ok": theme.VERIFIED,
    "warn": theme.CAUTION,
    "fail": theme.DANGER,
    "live": theme.LIVE,
    "idle": theme.TEXT_4,
    "busy": theme.PRIMARY_LO,
}


class Dot(QWidget):
    """A state dot. Small, and never the only carrier of the state — every
    place one of these appears, the word appears beside it. Colour alone fails
    for eight percent of the men who will use this machine, and it fails for
    everyone at a glance across a workshop."""

    def __init__(self, state="idle", size=8, parent=None):
        super().__init__(parent)
        self._state = state
        self._size = size
        self.setFixedSize(size + 4, size + 4)

    def set_state(self, state):
        if state != self._state:
            self._state = state
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(STATE_COLOURS.get(self._state, theme.TEXT_4))
        r = QRectF(2, 2, self._size, self._size)
        if self._state == "idle":
            p.setPen(QPen(c, 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r.adjusted(0.6, 0.6, -0.6, -0.6))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(theme.alpha(c.name(), 0.22)))
            p.drawEllipse(r.adjusted(-2, -2, 2, 2))
            p.setBrush(QBrush(c))
            p.drawEllipse(r)
        p.end()


class Chip(QFrame):
    """A short status, as a word plus a dot. Used for the machine link, the
    pre-flight verdict, the tier, and nothing else — a chip per fact would turn
    the header into a dashboard."""

    FILLS = {"ok": (theme.VERIFIED_FILL, theme.VERIFIED_EDGE, theme.VERIFIED),
             "warn": (theme.CAUTION_FILL, theme.CAUTION_EDGE, theme.CAUTION),
             "fail": (theme.DANGER_FILL, theme.DANGER_EDGE, theme.DANGER),
             "live": (theme.LIVE_FILL, theme.LIVE_EDGE, theme.LIVE),
             "idle": (theme.PANEL_HI, theme.RULE_HI, theme.TEXT_3)}

    def __init__(self, text="", state="idle", parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(9, 4, 11, 4)
        h.setSpacing(7)
        self.dot = Dot(state, 7)
        # Named ``label`` and not ``text``: an attribute called ``text`` on a
        # QWidget shadows the ``text()`` method every generic tree walk calls,
        # and the failure is a TypeError a long way from here.
        self.label = QLabel(text)
        self.label.setFont(theme.font("label"))
        h.addWidget(self.dot)
        h.addWidget(self.label)
        self.set(text, state)

    def set(self, text, state):
        self.label.setText(text)
        self.dot.set_state(state)
        fill, edge, ink = self.FILLS.get(state, self.FILLS["idle"])
        self.setObjectName("chip")
        self.setStyleSheet(
            f"QFrame#chip {{ background: {fill}; border: 1px solid {edge};"
            f" border-radius: {theme.RADIUS_CHIP}px; }}")
        self.label.setStyleSheet(f"color: {ink}; background: transparent;")


class Banner(QFrame):
    """A finding that does not expire.

    The first interface put its most valuable finding — "these nets will be
    shorted" — into a status-bar message with a twelve-second timeout, on a
    screen the user was about to scroll. This is the replacement: it stays up
    until the thing it is about stops being true, it carries the count and the
    worst case in the first line, and it offers the action that resolves it.
    """
    acted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(theme.GAP_M, theme.GAP_S + 2, theme.GAP_M,
                             theme.GAP_S + 2)
        v.setSpacing(5)
        top = QWidget()
        h = QHBoxLayout(top)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.dot = Dot("fail", 8)
        self.head = QLabel("")
        self.head.setFont(theme.font("sub"))
        h.addWidget(self.dot)
        h.addWidget(self.head, 1)
        self.action = QPushButton("")
        self.action.setObjectName("ghost")
        self.action.clicked.connect(self.acted)
        self.action.hide()
        h.addWidget(self.action)
        v.addWidget(top)
        self.detail = QLabel("")
        self.detail.setFont(theme.font("small"))
        self.detail.setWordWrap(True)
        v.addWidget(self.detail)
        self.hide()

    def show_finding(self, state, headline, detail="", action=None):
        fill, edge, ink = Chip.FILLS.get(state, Chip.FILLS["idle"])
        self.setStyleSheet(
            f"QFrame#card {{ background: {fill}; border: 1px solid {edge};"
            f" border-radius: {theme.RADIUS}px; }}")
        self.dot.set_state(state)
        self.head.setText(headline)
        self.head.setStyleSheet(f"color: {ink}; background: transparent;")
        self.detail.setText(detail)
        self.detail.setStyleSheet(
            f"color: {theme.TEXT_2}; background: transparent;")
        self.detail.setVisible(bool(detail))
        self.action.setText(action or "")
        self.action.setVisible(bool(action))
        self.show()


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

def button(text, *, kind="", tip="", on=None, enabled=True):
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if tip:
        b.setToolTip(tip)
    if on is not None:
        b.clicked.connect(on)
    b.setEnabled(enabled)
    b.setCursor(Qt.PointingHandCursor)
    if kind == "stop":
        b.setFont(theme.font("head"))
    return b


class Segmented(QWidget):
    """One row, one choice. The frame switch, and the height map's face.

    The first interface has four places that select the operation, two of them
    nested tab bars with the same labels; they can disagree with each other.
    This control exists so that nothing in this interface selects an OPERATION
    except the traveller - both uses here pick which view of one thing you are
    looking at, which is a different question and safe to have twice.
    """
    changed = Signal(str)

    def __init__(self, options, current=None, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(2)
        # Scoped: an unscoped rule here would repaint the buttons inside it.
        self.setObjectName("segBox")
        self.setStyleSheet(
            f"QWidget#segBox {{ background: {theme.SUNK};"
            f" border: 1px solid {theme.RULE}; border-radius: {theme.RADIUS}px; }}")
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._keys = {}
        for key, label, tip in options:
            b = QPushButton(label)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFont(theme.font("label"))
            if tip:
                b.setToolTip(tip)
            self._group.addButton(b)
            self._keys[b] = key
            h.addWidget(b)
            if key == (current or options[0][0]):
                b.setChecked(True)
        self._group.buttonClicked.connect(
            lambda b: self.changed.emit(self._keys[b]))

    def current(self):
        for b, k in self._keys.items():
            if b.isChecked():
                return k
        return None

    def set_current(self, key):
        for b, k in self._keys.items():
            if k == key:
                b.setChecked(True)

    def set_option_enabled(self, key, on):
        """Grey one choice out - for a view that means nothing on this job."""
        for b, k in self._keys.items():
            if k == key:
                b.setEnabled(bool(on))


class Disclosure(QWidget):
    """Progressive disclosure, done as a real control rather than a scrollbar.

    Everything a professional needs is reachable in two clicks; nothing a
    beginner does not need is on the screen when they open the app. The state
    is remembered per key so the person who always wants the feeds open only
    says so once.
    """

    def __init__(self, label, *, key=None, expanded=False, parent=None):
        super().__init__(parent)
        from gerber2rml.gui2 import workspace
        self._key = f"disclosure/{key}" if key else None
        if self._key is not None:
            stored = workspace.setting(self._key, None)
            if stored is not None:
                expanded = str(stored).lower() in ("true", "1")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.GAP_S)
        self._btn = QPushButton()
        self._btn.setObjectName("link")
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setFont(theme.font("label"))
        self._btn.clicked.connect(self._toggle)
        v.addWidget(self._btn)
        self._panel = QWidget()
        self.body = QVBoxLayout(self._panel)
        self.body.setContentsMargins(0, 0, 0, theme.GAP_XS)
        self.body.setSpacing(theme.GAP_S)
        v.addWidget(self._panel)
        self._label = label
        self._expanded = expanded
        self._sync()

    def _sync(self):
        self._btn.setText(("–  " if self._expanded else "+  ") + self._label)
        self._panel.setVisible(self._expanded)

    def _toggle(self):
        self._expanded = not self._expanded
        if self._key:
            from gerber2rml.gui2 import workspace
            workspace.set_setting(self._key, self._expanded)
        self._sync()

    def add(self, w):
        self.body.addWidget(w)
        return w


def _tame(widget):
    """Stop one long item in a combo from setting the width of a whole panel.

    A ``QComboBox`` reports a minimum width wide enough for its longest entry,
    and the built-in tool profile's name is 54 characters. Left alone, that one
    string made the inspector 549 px wide inside a 340 px panel — so the right
    edge of every field in it was simply clipped away. The full text is still
    reachable: it is in the drop-down, and in the tooltip.
    """
    from PySide6.QtWidgets import QComboBox, QAbstractSpinBox
    if isinstance(widget, QComboBox):
        widget.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        widget.setMinimumContentsLength(8)
        widget.setMinimumWidth(96)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    elif isinstance(widget, QAbstractSpinBox):
        widget.setMinimumWidth(84)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class Field(QWidget):
    """A labelled control with its unit and, where the name is not enough, a
    one-line explanation underneath.

    The explanation is part of the field rather than a tooltip whenever the
    control could cause a specific misconception — a tooltip that has to be
    hovered to prevent a mistake has already lost to the mistake.
    """

    def __init__(self, label, widget, *, unit="", help="", parent=None):
        super().__init__(parent)
        _tame(widget)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S)
        self.label = QLabel(label)
        self.label.setFont(theme.font("small"))
        self.label.setStyleSheet(f"color: {theme.TEXT_2};")
        self.label.setFixedWidth(94)
        self.label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        h.addWidget(self.label)
        h.addWidget(widget, 1)
        if unit:
            u = micro(unit)
            u.setMinimumWidth(30)
            h.addWidget(u)
        v.addWidget(row)
        if help:
            v.addWidget(hint(help))
        self.widget = widget


class Readout(QWidget):
    """A machine fact: a small label over a big monospaced number.

    Used for the position display and the run estimate. The number is the thing
    being read from across a bench, so it gets the size, and the label — which
    you learn once — gets the smallest type in the app.
    """

    def __init__(self, label, text="—", *, width=None, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        self._label = QLabel(label)
        self._label.setFont(theme.font("label"))
        self._label.setStyleSheet(f"color: {theme.TEXT_3};")
        self._value = QLabel(text)
        self._value.setFont(theme.font("head", mono=True))
        self._value.setStyleSheet(f"color: {theme.TEXT};")
        v.addWidget(self._label)
        v.addWidget(self._value)
        if width:
            self.setFixedWidth(width)

    def set(self, text, *, colour=None):
        self._value.setText(text)
        self._value.setStyleSheet(f"color: {colour or theme.TEXT};")

    def set_label(self, text):
        self._label.setText(text)


def dim(widget, amount=0.45):
    """Fade a widget without disabling it — for things that are still true but
    no longer the point (a finished step, a stale estimate)."""
    eff = QGraphicsOpacityEffect(widget)
    eff.setOpacity(amount)
    widget.setGraphicsEffect(eff)
    return widget


def caution_mark(painter, rect, colour):
    """The one drawn glyph shared between panels: a triangle with a bar.

    Drawn rather than typed because the alternatives are an emoji (an instant
    tell) or an icon font (a dependency and a licence) for a single shape.
    """
    p = QPainterPath()
    poly = QPolygonF([QPointF(rect.center().x(), rect.top()),
                      QPointF(rect.right(), rect.bottom()),
                      QPointF(rect.left(), rect.bottom())])
    p.addPolygon(poly)
    p.closeSubpath()
    painter.setPen(QPen(QColor(colour), 1.4))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(p)
    x = rect.center().x()
    painter.drawLine(QPointF(x, rect.top() + rect.height() * 0.38),
                     QPointF(x, rect.top() + rect.height() * 0.68))
    painter.drawPoint(QPointF(x, rect.bottom() - rect.height() * 0.14))
