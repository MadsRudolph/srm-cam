"""Dialogs, and one rule about them.

**An error dialog whose body is ``str(e)`` is not an error dialog.** The first
interface has twenty-six of them, and they produce messages like "Load failed:
list index out of range" — which tells a student nothing they can act on, and
tells a maintainer nothing they could not get from a traceback.

Every failure in this interface goes through :func:`report_error`, which forces
three separate things to exist:

1. **What failed**, in the user's terms. A sentence, in the title.
2. **What to do about it.** The most useful thing on the dialog, and the only
   part that changes what happens next.
3. **What the system said**, verbatim, in monospace, folded away under
   "Technical detail". It is still there — a maintainer needs it and a student
   can paste it into an email — but it is not the message.

If a caller cannot write (2), that is a signal the failure is not understood
well enough to be handled, not a reason to show the exception instead.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QWidget,
                               QCheckBox, QScrollArea, QFrame)

from gerber2rml.gui2 import theme, widgets


class Sheet(QDialog):
    """The shared shape: a headline, a body, and an action row."""

    def __init__(self, parent, headline, *, level="info", width=520):
        super().__init__(parent)
        self.setWindowTitle(headline)
        self.setMinimumWidth(width)
        self.setModal(True)
        v = QVBoxLayout(self)
        v.setContentsMargins(theme.GAP_L + 4, theme.GAP_L, theme.GAP_L + 4,
                             theme.GAP_L)
        v.setSpacing(theme.GAP_M)
        top = QWidget()
        h = QHBoxLayout(top)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.GAP_S + 2)
        if level in ("warn", "fail"):
            h.addWidget(widgets.Dot(level, 10), 0, Qt.AlignTop)
        self.head = QLabel(headline)
        self.head.setFont(theme.font("title"))
        self.head.setWordWrap(True)
        colour = {"fail": theme.DANGER, "warn": theme.CAUTION}.get(level,
                                                                   theme.TEXT)
        self.head.setStyleSheet(f"color: {colour};")
        h.addWidget(self.head, 1)
        v.addWidget(top)
        self.body = QVBoxLayout()
        self.body.setSpacing(theme.GAP_M)
        v.addLayout(self.body)
        v.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(theme.GAP_S)
        self.actions.addStretch(1)
        v.addLayout(self.actions)

    def say(self, text, *, small=False, mono=False, colour=None):
        lb = QLabel(text)
        lb.setFont(theme.font("small" if small else "body", mono=mono))
        lb.setWordWrap(True)
        lb.setStyleSheet(f"color: {colour or (theme.TEXT_3 if small else theme.TEXT_2)};")
        self.body.addWidget(lb)
        return lb

    def add(self, w):
        self.body.addWidget(w)
        return w

    def act(self, text, *, kind="", on=None, default=False):
        b = widgets.button(text, kind=kind, on=on)
        b.setDefault(default)
        self.actions.addWidget(b)
        return b


def report_error(parent, headline, exc=None, guidance=""):
    """The only way this interface reports a failure.

    ``headline`` says what failed in the user's terms; ``guidance`` says what to
    do next; ``exc`` is folded away where it does not have to be the message.
    """
    d = Sheet(parent, headline, level="fail")
    if guidance:
        d.say(guidance)
    else:
        d.say("This is not something the app knows how to explain yet. The "
              "technical detail below is the most useful thing to send on.")
    if exc is not None:
        detail = widgets.Disclosure("Technical detail")
        text = (f"{exc.__class__.__name__}: {exc}"
                if isinstance(exc, BaseException) else str(exc))
        lb = QLabel(text)
        lb.setFont(theme.font("small", mono=True))
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lb.setStyleSheet(
            f"color: {theme.TEXT_3}; background: {theme.SUNK};"
            f" border: 1px solid {theme.RULE}; padding: 9px;")
        detail.add(lb)
        d.add(detail)
    d.act("Close", kind="primary", on=d.accept, default=True)
    d.exec()


def confirm_shorts(parent, shorts, cut_width):
    """Ask before writing files for a board that cannot work.

    A modal, and deliberately not another line in a status bar — the status bar
    is where this finding used to go to die. It is also phrased as a question
    about the LAYOUT rather than about the export, because milling it more
    carefully will not help.
    """
    worst = min(s["gap"] for s in shorts)
    d = Sheet(parent, "This board will have shorted nets", level="fail",
              width=560)
    d.say(f"{len(shorts)} spot{'s' if len(shorts) != 1 else ''} on this layout "
          f"have two separate nets sitting closer together than the "
          f"{cut_width:.2f} mm the cutter removes. The worst is "
          f"{worst:.2f} mm apart.")
    d.say("The copper between them physically cannot be taken out, so those "
          "nets will be joined on the finished board. No depth, feed or bed "
          "levelling changes that — the bit is simply wider than the gap.")
    d.say("Two things fix it: a narrower bit (a V-bit cuts narrower at a "
          "shallower depth), or moving the tracks apart in KiCad.")
    d.say("They are marked with a cross on the stage.", small=True)
    out = {"go": False}

    def go():
        out["go"] = True
        d.accept()

    d.act("Go back and fix it", kind="primary", on=d.reject, default=True)
    d.act("Export anyway", kind="danger", on=go)
    d.exec()
    return out["go"]


def confirm_irreversible(parent, headline, body, confirm_label):
    """For the handful of actions that cannot be undone by trying again.

    They look different from safe ones — a red action, a neutral default, and a
    tick that has to be set before the red button will work — because the
    interface's only chance to distinguish them is before the click.
    """
    d = Sheet(parent, headline, level="warn", width=540)
    d.say(body)
    chk = QCheckBox("I understand this cannot be undone by re-running it")
    d.add(chk)
    out = {"go": False}

    def go():
        out["go"] = True
        d.accept()

    d.act("Cancel", on=d.reject, default=True)
    btn = d.act(confirm_label, kind="danger", on=go)
    btn.setEnabled(False)
    chk.toggled.connect(btn.setEnabled)
    d.exec()
    return out["go"]


STREAM_WARNING = """\
Streaming sends the job to the machine move by move over the Arduino link, \
instead of writing a file for VPanel. It is EXPERIMENTAL and it is not the way \
this lab runs jobs.

What is not calibrated: the speed units. The feed you set in millimetres per \
second is sent as a number this machine's remote-move command interprets in \
units nobody here has measured, so the job may run faster or slower than the \
file would. Nothing about the geometry changes — only how fast the head gets \
there.

What is enforced: the run aborts if the lid opens, STOP drops the move in \
flight, and Pause holds mid-move. The spindle is started and stopped by the \
run itself.

What is still yours: the spindle SPEED, which this link cannot set. Set it on \
VPanel's slider before you start.

Do the dry run first. Every time, on every new job."""


def stream_dialog(parent, *, move_count, dry_run_default=True):
    """The safety copy for the experimental path, in full.

    Nobody who reads this dialog can be surprised by what happens next. That is
    the entire specification for it.
    """
    d = Sheet(parent, "Stream this job over the link", level="warn", width=580)
    d.say(f"{move_count:,} moves.", colour=theme.TEXT)
    lb = QLabel(STREAM_WARNING)
    lb.setFont(theme.font("small"))
    lb.setWordWrap(True)
    lb.setStyleSheet(f"color: {theme.TEXT_2};")
    d.add(lb)
    dry = QCheckBox("Dry run — spindle off, bit held clear of the copper")
    dry.setChecked(dry_run_default)
    dry.setToolTip(
        "A dry run cannot cut: the spindle never starts and every Z is lifted "
        "clear of the surface. It is a mechanical guarantee, not a setting the "
        "job could override.")
    d.add(dry)
    out = {"go": False, "dry": dry_run_default}

    def go():
        out["go"] = True
        out["dry"] = dry.isChecked()
        d.accept()

    d.act("Cancel", on=d.reject, default=True)
    d.act("Start", kind="danger", on=go)
    d.exec()
    return out


def about_tier(parent):
    """What the full tier adds, and what the essential one deliberately keeps.

    Shown from the Interface menu so nobody has to guess whether the control
    they remember is gone or merely put away.
    """
    from gerber2rml.gui2 import tier
    d = Sheet(parent, "What the two tiers differ by", width=600)
    d.say("Essential is the whole single-sided job, including bed levelling. "
          "It is a strict subset of Full — the same controls, the same "
          "handlers, and files that come out byte for byte identical.")
    s1 = widgets.Section("Full adds")
    for line in tier.ADDED_BY_FULL:
        s1.add(widgets.hint("· " + line))
    s2 = widgets.Section("Essential keeps, on purpose")
    for name, why in tier.KEPT_IN_ESSENTIAL:
        card = widgets.Card(quiet=True, pad=theme.GAP_S + 2, gap=2)
        t = QLabel(name)
        t.setFont(theme.font("small"))
        t.setStyleSheet(f"color: {theme.TEXT};")
        card.box.addWidget(t)
        card.box.addWidget(widgets.hint(why))
        s2.add(card)
    # Eleven paragraphs and five cards: on a 768 px laptop the Close button
    # was below the screen edge. The two sections scroll inside the sheet.
    inner = QWidget()
    iv = QVBoxLayout(inner)
    iv.setContentsMargins(0, 0, 0, 0)
    iv.setSpacing(theme.GAP_L)
    iv.addWidget(s1)
    iv.addWidget(s2)
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setWidget(inner)
    sa.setMaximumHeight(440)
    d.add(sa)
    d.act("Close", kind="primary", on=d.accept, default=True)
    d.exec()
