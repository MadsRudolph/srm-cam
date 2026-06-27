"""The brain of the tour: step sequencing, gating, page switching, persistence.

:class:`TourController` owns the current step list and index, drives the
:class:`~gerber2rml.gui.tour.overlay.Spotlight` and
:class:`~gerber2rml.gui.tour.overlay.Callout`, wires each gated step's advance
signal, and remembers (via ``QSettings``) that the user has seen the tour so it
auto-runs only once. After the core path it offers the opt-in branches.

Targets and advance signals are resolved from the window by attribute name, so
a missing widget skips its step instead of crashing.
"""
from PySide6.QtCore import QObject, QEvent, QPoint, QRect, QTimer, Qt, QSettings
from PySide6.QtWidgets import QScrollArea, QAbstractButton

from gerber2rml.gui.tour.overlay import Spotlight, Callout, place_callout
from gerber2rml.gui.tour.steps import CORE_STEPS, BRANCHES

_SEEN_KEY = "tour/seen"


class TourController(QObject):
    def __init__(self, window, settings=None):
        super().__init__(window)
        self.window = window
        self.settings = settings or QSettings("srm-cam", "SRM-CAM")
        self._steps = []
        self._i = 0
        self._is_branch = False
        self._overlay = None
        self._callout = None
        self._gate = None            # (signal, slot) currently connected
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._reposition)
        self._active = False

    # ---- lifecycle ---------------------------------------------------------
    @property
    def active(self):
        return self._active

    def has_seen(self):
        return self.settings.value(_SEEN_KEY, False, type=bool)

    def maybe_autostart(self):
        """Start the tour the first time ever; silent on later launches."""
        if not self.has_seen():
            self.start()

    def start(self, steps=None, is_branch=False):
        self._steps = list(steps if steps is not None else CORE_STEPS)
        self._is_branch = is_branch
        self._i = 0
        if not self._active:
            self._build_widgets()
            self._app().installEventFilter(self)      # for Esc
            self._timer.start()
            self._active = True
        self._show_step()

    def _build_widgets(self):
        host = self.window.centralWidget() or self.window
        self._overlay = Spotlight(host)
        self._callout = Callout(host)
        self._callout.on_back = self._back
        self._callout.on_next = self._next
        self._callout.on_skip = self.skip
        self._overlay.setGeometry(host.rect())
        self._overlay.show()
        self._callout.show()

    def _teardown(self):
        self._timer.stop()
        self._disconnect_gate()
        self._app().removeEventFilter(self)
        for w in (self._callout, self._overlay):
            if w is not None:
                w.hide()
                w.deleteLater()
        self._callout = self._overlay = None
        self._active = False

    def skip(self):
        self._mark_seen()
        self._teardown()

    def _finish(self):
        self._mark_seen()
        self._teardown()

    def _mark_seen(self):
        self.settings.setValue(_SEEN_KEY, True)

    # ---- navigation --------------------------------------------------------
    def _next(self, *_):
        self._disconnect_gate()
        if self._i + 1 < len(self._steps):
            self._i += 1
            self._show_step()
        else:
            self._on_sequence_end()

    def _back(self):
        self._disconnect_gate()
        if self._i > 0:
            self._i -= 1
            self._show_step()

    def _on_sequence_end(self):
        # Core path or any branch ends by offering the advanced mini-tours;
        # "Finish" closes the whole tour.
        self._offer_branches()

    def _offer_branches(self):
        self._disconnect_gate()
        self._is_branch = False
        self._overlay.set_spot(None)
        buttons = [(name, lambda n=name: self._start_branch(n)) for name in BRANCHES]
        buttons.append(("Finish", self._finish))
        self._callout.show_menu(
            "That's the core workflow!",
            "Mill, and you're done. Want a quick look at an advanced feature? "
            "Or finish the tour.",
            buttons,
        )
        self._place_centered()

    def start_branch(self, name):
        """Jump straight into one section's mini-tour (per-page Guide buttons), so
        you don't have to walk the whole core flow to reach it."""
        if name in BRANCHES:
            self._start_branch(name)

    def _start_branch(self, name):
        _page, steps = BRANCHES[name]
        self.start(steps=steps, is_branch=True)

    # ---- showing a step ----------------------------------------------------
    def _show_step(self):
        step = self._steps[self._i]
        target = getattr(self.window, step.target, None) if step.target else None
        if step.target and target is None:
            return self._next()                 # widget gone -> skip gracefully

        if hasattr(self.window, "sidebar"):
            self.window.sidebar.setCurrentRow(step.page)
        if step.reveal:
            chk = getattr(self.window, step.reveal, None)
            if chk is not None and hasattr(chk, "isChecked") and not chk.isChecked():
                chk.setChecked(True)
        if target is not None:
            self._ensure_visible(target)

        counter = "" if self._is_branch else f"Step {self._i + 1} of {len(self._steps)}"
        next_enabled = not step.is_gated
        self._callout.show_step(step.title, step.body, counter,
                                next_enabled=next_enabled, can_back=self._i > 0)

        self._connect_gate(step)
        self._reposition()

    def _connect_gate(self, step):
        if not step.is_gated:
            return
        try:
            attr, sig_name = step.advance_signal.split(".")
            signal = getattr(getattr(self.window, attr), sig_name)
        except (AttributeError, ValueError):
            return                              # bad spec -> behave as explain-only
        signal.connect(self._next)
        self._gate = (signal, self._next)

    def _disconnect_gate(self):
        if self._gate is not None:
            signal, slot = self._gate
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
            self._gate = None

    # ---- geometry ----------------------------------------------------------
    def _ensure_visible(self, target):
        p = target.parent()
        while p is not None:
            if isinstance(p, QScrollArea):
                p.ensureWidgetVisible(target)
                break
            p = p.parent()

    def _target_rect(self):
        """Current target's rect in overlay-local coords, or None."""
        if not self._active or self._overlay is None:
            return None
        step = self._steps[self._i]
        target = getattr(self.window, step.target, None) if step.target else None
        if target is None or not target.isVisible():
            return None
        size = target.size()
        if size.width() <= 0 or size.height() <= 0:
            return None
        tl = self._overlay.mapFromGlobal(target.mapToGlobal(QPoint(0, 0)))
        return QRect(tl, size)

    def _reposition(self):
        if not self._active or self._overlay is None:
            return
        host = self.window.centralWidget() or self.window
        self._overlay.setGeometry(host.rect())
        rect = self._target_rect()
        if rect is None:
            self._overlay.set_spot(None)
            self._place_centered()
        else:
            self._overlay.set_spot(rect)
            self._place_near(rect)
        self._overlay.raise_()
        self._callout.raise_()

    def _place_near(self, rect):
        c = self._callout
        c.adjustSize()
        size = (c.width(), c.height())
        ob = self._overlay.rect()
        bounds = (8, 8, ob.width() - 16, ob.height() - 16)
        step = self._steps[self._i]
        x, y = place_callout((rect.x(), rect.y(), rect.width(), rect.height()),
                             size, bounds, preferred=step.placement)
        c.move(int(x), int(y))

    def _place_centered(self):
        if self._callout is None or self._overlay is None:
            return
        c = self._callout
        c.adjustSize()
        ob = self._overlay.rect()
        c.move(max(0, (ob.width() - c.width()) // 2),
               max(0, (ob.height() - c.height()) // 3))

    # ---- misc --------------------------------------------------------------
    def _app(self):
        from PySide6.QtWidgets import QApplication
        return QApplication.instance()

    def eventFilter(self, obj, ev):
        if self._active and ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.skip()
            return True
        return super().eventFilter(obj, ev)
