"""The mill's own settings, from inside the app.

Two settings on the SRM-20 itself decide whether a job runs and how fast the
spindle turns, and until now both lived only in Roland's VPanel, which is
Windows-only: Setup ▸ Command Set, and the Spindle slider. A lab that runs
its mill from a Mac had to borrow a Windows PC to look at either.
:mod:`gerber2rml.engine.millsetup` reads and sets them over USB the way
VPanel does; this is the sheet in front of it.

**Machine ▸ The mill's settings…** reads the mill and says what it found:
the command set, where G54 is, the spindle slider. It changes nothing by
being opened. The two things it can change each have their own button.

**Before an automatic run** (:func:`preflight`) the same reading is taken
without anyone asking, so that Start is the only thing to press. What can be
put right is put right: a mill in RML-1 would refuse every job, so it is set
to NC Code there and then, and the run says in its log that it did - never
silently, because the setting is shared by everyone who uses the mill. What
cannot be put right from here stops for a person: a G54 that is not at
machine 0, 0 would end the run at its frame check, so the run says so before
it has probed anything. A mill that cannot be read is said too, and the run
may go on - it has its own checks, and they are the ones that were proven at
the machine.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QSpinBox, QWidget

from gerber2rml.engine import millsetup
from gerber2rml.gui2 import dialogs, theme, widgets

HOW_TO_REACH = (
    "Switch the mill on and plug its USB cable into this computer. If it is "
    "on and plugged in, see docs/vpanel-settings.md for what SRM-CAM needs "
    "to reach it.")


def _busy(fn):
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        return fn()
    finally:
        QApplication.restoreOverrideCursor()


def read_all(dev):
    """Everything the sheet shows, in one go: ``{"set", "g54", "status"}``."""
    return {"set": millsetup.command_set(dev),
            "g54": millsetup.g54_origin(dev),
            "status": millsetup.status(dev)}


def g54_note(g54):
    """What to say about G54, and whether it is a problem.

    The automatic run moves to its first point through G54 and stops if the
    head is not where it expected (engine/autorun.py, ``_check_frame``), so
    X and Y have to be machine 0, 0. Z is whatever the last touch-off left.
    """
    x, y, z = g54
    where = f"G54 origin: X {x:.2f}  Y {y:.2f}  Z {z:.2f} mm (machine)"
    ok = abs(x) < 0.005 and abs(y) < 0.005
    if ok:
        return where, True
    return (where + ". The automatic run needs X and Y at 0, 0 and will stop "
            "at its frame check until they are - that has to be put back in "
            "VPanel."), False


def _ask(parent, headline, text, go, level="warn"):
    d = dialogs.Sheet(parent, headline, level=level, width=560)
    d.say(text)
    d.act("Cancel the run", on=d.reject, default=True)
    d.act(go, kind="primary", on=d.accept)
    return bool(d.exec())


def preflight(parent, open_mill=None, say=None):
    """Check the mill's own settings before a run sends anything, and put
    right what can be. True to go ahead.

    The command set is set to NC Code without a question: the run cannot
    work any other way, and a question whose only useful answer is yes is
    one more thing to get wrong at the machine. It is not done quietly:
    ``say(level, text)`` gets a line for the run's log, which is where the
    next person finds out why VPanel shows something else than they left.
    Cancel is the default button on the questions that remain, so Return
    never starts a run that had something to say.
    """
    say = (lambda _level, _text: None) if say is None else say
    open_mill = millsetup.open_mill if open_mill is None else open_mill
    try:
        dev = _busy(open_mill)
        now = _busy(lambda: read_all(dev))
    except millsetup.SetupError as e:
        return _ask(parent, "The mill's settings could not be checked",
                    f"SRM-CAM could not read the mill over USB ({e}). The "
                    "run can still start: it stops by itself if the mill "
                    "refuses the job or G54 is not where it should be. "
                    "Start without the check?", "Start anyway")
    if now["set"] != millsetup.NC:
        try:
            _busy(lambda: millsetup.set_command_set(dev, nc=True))
        except millsetup.SetupError as e:
            dialogs.report_error(
                parent, "The mill is set to RML-1 and could not be changed",
                e,
                "SRM-CAM's automatic run sends NC Code, which the mill "
                "would refuse. The run has not started and nothing else was "
                "sent. Machine ▸ The mill's settings… shows what it reads "
                "now.")
            return False
        say("warn", "The mill's command set was RML-1. SRM-CAM set it to NC "
                    "Code, which the automatic run needs; it stays that way "
                    "for the next user.")
    text, ok = g54_note(now["g54"])
    if not ok:
        return _ask(parent, "G54 is not at machine 0, 0",
                    text + " Starting now will probe the stock and then "
                    "stop before it cuts.", "Start anyway")
    return True


def settings_sheet(parent, open_mill=None):
    """Show the mill's settings and offer the two changes. Returns the last
    reading (:func:`read_all`), or None when the mill could not be reached."""
    open_mill = millsetup.open_mill if open_mill is None else open_mill
    try:
        dev = _busy(open_mill)
        now = _busy(lambda: read_all(dev))
    except millsetup.SetupError as e:
        dialogs.report_error(parent, "The mill's settings could not be read",
                             e, HOW_TO_REACH)
        return None

    nc = now["set"] == millsetup.NC
    d = dialogs.Sheet(parent, "The mill's settings",
                      level="info" if nc else "warn", width=580)
    d.setObjectName("millSettingsSheet")
    set_line = d.say("")
    g54_text, g54_ok = g54_note(now["g54"])
    d.say(g54_text, colour=None if g54_ok else theme.CAUTION)

    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(theme.GAP_S)
    spin = QSpinBox()
    spin.setObjectName("spindlePercent")
    spin.setRange(millsetup.SPINDLE_PERCENT_MIN, millsetup.SPINDLE_PERCENT_MAX)
    spin.setSuffix(" %")
    spin.setValue(max(millsetup.SPINDLE_PERCENT_MIN,
                      min(millsetup.SPINDLE_PERCENT_MAX,
                          now["status"]["spindle_percent"])))
    h.addWidget(widgets.button("Set the spindle speed",
                               on=lambda: set_spindle()))
    h.addWidget(spin)
    h.addStretch(1)
    d.add(row)
    d.say("The spindle speed is VPanel's Spindle slider, in percent of the "
          "mill's top speed. It is what a job runs at: the program can only "
          "turn the spindle on and off.", small=True)
    d.say("These settings belong to the mill and stay as they are for the "
          "next person. Nothing here changes until a button is pressed.",
          small=True)

    def show_set():
        name = millsetup.SET_NAMES[now["set"]]
        if now["set"] == millsetup.NC:
            set_line.setText(f"Command set: {name}. This is what SRM-CAM's "
                             f"automatic run sends.")
        else:
            set_line.setText(f"Command set: {name}. SRM-CAM's automatic run "
                             f"sends NC Code, and the mill will refuse it "
                             f"until this is changed.")
        to_nc.setVisible(now["set"] != millsetup.NC)

    def change(headline, fn):
        try:
            return _busy(fn)
        except millsetup.SetupError as e:
            dialogs.report_error(d, headline, e,
                                 "Nothing else was sent to the mill. Read "
                                 "the settings again before trying once "
                                 "more.")
            return None

    def set_nc():
        got = change("The command set could not be changed",
                     lambda: millsetup.set_command_set(dev, nc=True))
        if got is not None:
            now["set"] = got
            show_set()

    def set_spindle():
        got = change("The spindle speed could not be set",
                     lambda: millsetup.set_spindle_percent(dev, spin.value()))
        if got is not None:
            now["status"]["spindle_percent"] = got
            spin.setValue(got)

    d.act("Close", on=d.accept)
    to_nc = d.act("Set the command set to NC Code", kind="primary", on=set_nc)
    show_set()
    d.exec()
    return now
