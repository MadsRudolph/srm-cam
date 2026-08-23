"""The traveller: the run plan, as the only navigation in the application.

A machine shop hangs a *traveller* beside the job — a numbered sheet listing
every operation in the order it happens, which tool each one needs, and a box
to tick when it is done. It moves with the work. This rail is that sheet.

Two things follow from that, and both are deliberate:

**There is one selector.** Choosing a step here is how you choose an operation,
a side, and what the stage draws. The first interface has four controls that
select the operation and two of them are tab bars with identical labels, which
can disagree; here there is nothing to disagree with.

**It is a map, not a gate.** Every row is clickable at every moment, including
rows you have not reached and rows you have passed. Real runs jump around: a
trace pass gets re-cut, a drill file gets re-sent, someone checks the cut-out
parameters while the traces are still running. Marking a step done is a note to
yourself, never a permission.

The order is not defined in this file. It comes from :mod:`runplan`, which is
tested against the files the engine actually writes.
"""
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QColor, QFontMetricsF, QBrush
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
                               QFrame, QLabel, QSizePolicy)

from gerber2rml.gui2 import theme, widgets
from gerber2rml.engine.estimate import format_duration

NUM_COL = 34            # px: the step-number column, and the rule beside it
ROW_PAD = 9


class StepRow(QWidget):
    """One line of the traveller, painted rather than composed.

    Painted because the number column, the hairline that runs through it and
    the baseline relationship between the step name and its spec are the whole
    design of this rail; assembling them from nested layouts would put four
    widgets and three margins between the intent and the pixels.
    """
    clicked = Signal(str)

    def __init__(self, step, parent=None):
        super().__init__(parent)
        self.step = step
        self.selected = False
        self.done = False
        self.exported = False
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self._hover = False
        self.setToolTip(step.note or step.detail)
        self._measure()

    def _measure(self):
        s = self.step
        h = ROW_PAD * 2
        h += QFontMetricsF(theme.font("sub" if s.kind == "run"
                                      else "small")).height()
        if s.detail:
            h += QFontMetricsF(theme.font(
                "micro" if s.kind == "handoff" else "small")).height() + 1
        if s.caution:
            h += QFontMetricsF(theme.font("micro")).height() + 3
        self.setFixedHeight(int(h) + (2 if s.kind == "run" else -3))

    def set_selected(self, on):
        if on != self.selected:
            self.selected = on
            self.update()

    def set_done(self, on):
        if on != self.done:
            self.done = on
            self.update()

    def set_exported(self, on):
        if on != self.exported:
            self.exported = on
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.step.key)

    def paintEvent(self, _e):
        s = self.step
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()

        if self.selected:
            p.fillRect(r, QColor(theme.SELECT))
            p.fillRect(QRectF(0, 0, 2, r.height()), QColor(theme.PRIMARY))
        elif self._hover:
            p.fillRect(r, QColor(theme.HOVER))

        # the rule that makes a column of numbers read as a column
        if s.kind in ("run", "handoff"):
            p.setPen(QPen(QColor(theme.RULE_HI if self.selected else theme.RULE), 1))
            p.drawLine(QPointF(NUM_COL - 0.5, 0), QPointF(NUM_COL - 0.5, r.height()))

        y = ROW_PAD
        ink = theme.TEXT if (self.selected or s.kind == "run") else theme.TEXT_2
        if self.done:
            ink = theme.TEXT_3

        # -- the number column ------------------------------------------
        if s.numbered:
            f = theme.font("title")
            p.setFont(f)
            fm = QFontMetricsF(f)
            num = str(s.ordinal)
            p.setPen(QPen(QColor(theme.VERIFIED if self.done
                                 else (theme.TEXT if self.selected else theme.TEXT_3)), 1))
            p.drawText(QPointF(NUM_COL - 11 - fm.horizontalAdvance(num),
                               y + fm.ascent() - 1), num)
        elif s.kind == "handoff":
            # A hands-on step has no number because it is not a file. It gets a
            # mark in the same column so the sequence still reads as a sequence.
            p.setPen(QPen(QColor(theme.TEXT_4), 1.4))
            cy = y + 8
            p.drawLine(QPointF(NUM_COL - 20, cy), QPointF(NUM_COL - 11, cy))
        elif s.kind == "tool":
            p.setPen(QPen(QColor(theme.TEXT_3 if not self.selected else theme.TEXT), 1.3))
            cy = y + 7
            x = 13
            p.drawLine(QPointF(x, cy - 4), QPointF(x + 4, cy))
            p.drawLine(QPointF(x + 4, cy), QPointF(x, cy + 4))

        left = NUM_COL + 12 if s.kind in ("run", "handoff") else 28

        # -- title + estimate -------------------------------------------
        f = theme.font("sub" if s.kind == "run" else "body")
        if s.kind == "handoff":
            f = theme.font("small")
            ink = theme.TEXT_2 if not self.selected else theme.TEXT
        p.setFont(f)
        fm = QFontMetricsF(f)
        est = ""
        if s.seconds is not None:
            est = "~" + format_duration(s.seconds)
        est_w = 0
        if est:
            ef = theme.font("small", mono=True)
            efm = QFontMetricsF(ef)
            est_w = efm.horizontalAdvance(est) + 12
            p.setFont(ef)
            p.setPen(QPen(QColor(theme.TEXT_3), 1))
            p.drawText(QPointF(r.width() - 12 - efm.horizontalAdvance(est),
                               y + fm.ascent()), est)
            p.setFont(f)
        avail = r.width() - left - 12 - est_w
        p.setPen(QPen(QColor(ink), 1))
        p.drawText(QPointF(left, y + fm.ascent()),
                   fm.elidedText(s.title, Qt.ElideRight, max(avail, 40)))
        if self.done:
            ty = y + fm.ascent() - fm.xHeight() / 2
            p.setPen(QPen(QColor(theme.TEXT_4), 1))
            p.drawLine(QPointF(left, ty),
                       QPointF(left + min(fm.horizontalAdvance(s.title), avail), ty))
        y += fm.height()

        # -- the spec: bit, depth, passes -------------------------------
        if s.detail:
            f2 = theme.font("micro" if s.kind == "handoff" else "small")
            p.setFont(f2)
            fm2 = QFontMetricsF(f2)
            p.setPen(QPen(QColor(theme.TEXT_3), 1))
            p.drawText(QPointF(left, y + fm2.ascent() + 1),
                       fm2.elidedText(s.detail, Qt.ElideRight,
                                      max(r.width() - left - 12, 40)))
            y += fm2.height() + 1

        # -- the consequence worth reading ------------------------------
        if s.caution:
            f3 = theme.font("micro")
            p.setFont(f3)
            fm3 = QFontMetricsF(f3)
            colour = theme.DANGER if s.irreversible else theme.CAUTION
            box = QRectF(left, y + 2, fm3.horizontalAdvance(s.caution) + 16,
                         fm3.height() + 3)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(theme.alpha(colour, 0.13)))
            p.drawRoundedRect(box, theme.RADIUS_CHIP, theme.RADIUS_CHIP)
            p.setPen(QPen(QColor(colour), 1))
            p.drawText(box, Qt.AlignCenter, s.caution)

        # -- has this been written out yet? -----------------------------
        if s.file and self.exported and not self.done:
            p.setPen(QPen(QColor(theme.VERIFIED), 1.4))
            p.setBrush(Qt.NoBrush)
            cx, cy = r.width() - 6, r.height() / 2
            p.drawLine(QPointF(cx, cy - 5), QPointF(cx, cy + 5))
        p.end()


class Traveller(QWidget):
    """The rail: header, findings, the plan, the total, the one primary button."""

    step_selected = Signal(str)
    export_requested = Signal()
    banner_action = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setFixedWidth(theme.RAIL_W)
        self._rows = {}
        self._current = None
        self._done = set()
        self._exported = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # -- header ------------------------------------------------------
        head = QWidget()
        head.setObjectName("panel")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(theme.GAP_M + 2, theme.GAP_M + 2,
                              theme.GAP_M + 2, theme.GAP_M)
        hv.setSpacing(3)
        self.job_name = QLabel("No job")
        self.job_name.setFont(theme.font("title"))
        self.job_name.setStyleSheet(f"color: {theme.TEXT};")
        hv.addWidget(self.job_name)
        self.job_facts = QLabel("Load a Gerber folder to begin")
        self.job_facts.setFont(theme.font("small"))
        self.job_facts.setStyleSheet(f"color: {theme.TEXT_3};")
        self.job_facts.setWordWrap(True)
        hv.addWidget(self.job_facts)
        outer.addWidget(head)
        outer.addWidget(widgets.rule())

        # -- the finding that does not expire ----------------------------
        self.banner = widgets.Banner()
        self.banner.acted.connect(self.banner_action)
        bwrap = QWidget()
        bl = QVBoxLayout(bwrap)
        bl.setContentsMargins(theme.GAP_S + 2, theme.GAP_S, theme.GAP_S + 2,
                              theme.GAP_S)
        bl.setSpacing(0)
        bl.addWidget(self.banner)
        self._bwrap = bwrap
        bwrap.hide()
        outer.addWidget(bwrap)

        # -- the plan ----------------------------------------------------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("panel")
        self.list = QVBoxLayout(inner)
        self.list.setContentsMargins(0, theme.GAP_XS, 0, theme.GAP_M)
        self.list.setSpacing(0)
        self.scroll.setWidget(inner)
        outer.addWidget(self.scroll, 1)

        # -- the foot: total, and the one primary action -----------------
        outer.addWidget(widgets.rule())
        foot = QWidget()
        foot.setObjectName("panel")
        fv = QVBoxLayout(foot)
        fv.setContentsMargins(theme.GAP_M + 2, theme.GAP_M, theme.GAP_M + 2,
                              theme.GAP_M + 2)
        fv.setSpacing(theme.GAP_S)
        trow = QWidget()
        th = QHBoxLayout(trow)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(theme.GAP_S)
        self.total_label = widgets.eyebrow("Estimated cutting time")
        th.addWidget(self.total_label)
        th.addStretch(1)
        self.total_value = QLabel("—")
        self.total_value.setFont(theme.font("sub", mono=True))
        self.total_value.setStyleSheet(f"color: {theme.TEXT_2};")
        th.addWidget(self.total_value)
        fv.addWidget(trow)
        self.export_btn = widgets.button(
            "Export the job", kind="primary", on=self.export_requested.emit,
            tip="Write every file in this plan, plus the printed run plan, "
                "into a folder you choose.")
        self.export_btn.setEnabled(False)
        fv.addWidget(self.export_btn)
        # The caveat is a footnote, and a footnote does not need fifty pixels
        # of the rail forever — at 720 px of window height that paragraph was
        # pushing the cut-out step off the bottom of the plan.
        caveat = ("Excludes tool changes, spin-up and pauses. It runs low on "
                  "trace jobs — the machine slows for every corner, and a "
                  "trace pass is nothing but corners.")
        for w in (self.total_label, self.total_value):
            w.setToolTip(caveat)
        outer.addWidget(foot)

    # -- content -----------------------------------------------------------
    def set_job(self, name, facts):
        self.job_name.setText(name or "No job")
        self.job_facts.setText(facts)

    def set_plan(self, plan):
        while self.list.count():
            item = self.list.takeAt(0)
            w = item.widget()
            if w is not None:
                # setParent(None) as well as deleteLater(): taking a widget out
                # of a layout does NOT unparent it, so it stays visible at its
                # last geometry until the deferred delete is processed — and a
                # stale row from the previous plan still draws its old selection
                # highlight over the new rail.
                w.setParent(None)
                w.deleteLater()
        self._rows = {}
        last_kind = None
        for step in plan:
            if step.kind == "run" and last_kind != "run" and last_kind is not None:
                self._add_eyebrow("Run order" if last_kind == "tool" else "")
            if step.kind == "tool" and last_kind in ("run", "handoff"):
                self._add_eyebrow("When you need it")
            row = StepRow(step)
            row.clicked.connect(self._on_click)
            row.set_done(step.key in self._done)
            row.set_exported(step.key in self._exported)
            self.list.addWidget(row)
            self._rows[step.key] = row
            last_kind = step.kind
        self.list.addStretch(1)
        if self._current in self._rows:
            self._rows[self._current].set_selected(True)
        elif self._rows:
            self.select(next(iter(self._rows)))
        self._update_total(plan)

    def _add_eyebrow(self, text):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(theme.GAP_M + 2, theme.GAP_M, theme.GAP_M + 2, 5)
        v.setSpacing(theme.GAP_XS)
        if text:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(theme.GAP_S)
            h.addWidget(widgets.eyebrow(text))
            h.addWidget(widgets.rule(), 1)
            v.addWidget(row)
        else:
            v.addWidget(widgets.rule())
        self.list.addWidget(w)

    def _update_total(self, plan):
        total = plan.total_seconds
        self.total_value.setText("~" + format_duration(total) if total else "—")

    def _on_click(self, key):
        self.select(key)
        self.step_selected.emit(key)

    def select(self, key):
        if key not in self._rows:
            return
        for k, row in self._rows.items():
            row.set_selected(k == key)
        self._current = key

    def current(self):
        return self._current

    def refresh_step(self, key, plan):
        """Re-read one row after its estimate arrived.

        Estimates are filled in as you walk the plan — the toolpath for a step
        is generated when you select it, so the time it will take is known then
        and not before. Rebuilding the whole rail for one number would lose the
        scroll position, so the row updates itself.
        """
        row = self._rows.get(key)
        if row is None:
            return
        row._measure()
        row.update()
        self._update_total(plan)

    def set_done(self, key, on=True):
        (self._done.add if on else self._done.discard)(key)
        if key in self._rows:
            self._rows[key].set_done(on)

    def is_done(self, key):
        return key in self._done

    def clear_done(self):
        self._done.clear()
        for row in self._rows.values():
            row.set_done(False)

    def set_exported(self, keys):
        self._exported = set(keys)
        for k, row in self._rows.items():
            row.set_exported(k in self._exported)

    def set_export_enabled(self, on, reason=""):
        self.export_btn.setEnabled(on)
        if reason:
            self.export_btn.setToolTip(reason)

    def show_finding(self, *a, **kw):
        self.banner.show_finding(*a, **kw)
        self._bwrap.show()

    def clear_finding(self):
        self.banner.hide()
        self._bwrap.hide()
