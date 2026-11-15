"""The mill's print queue on a Mac, from inside the app.

On Windows the Roland driver installs the mill as a printer. On a Mac there
is no driver: the mill is a raw CUPS queue named SRM-20
(:mod:`gerber2rml.engine.rmlspool`). This is what the setup sheet says and
does about that queue, so nobody has to open a terminal:

* **Machine ▸ Set up the mill on this Mac…** makes the queue (macOS asks for
  an admin password in its own dialog).
* **Before a run** (:func:`preflight`): a missing queue is offered for setup,
  a queue CUPS stopped after a failed job is offered for resuming, and jobs
  left over from an earlier run - which would cut before this one - are
  offered for clearing. The run does not start until each is settled.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gerber2rml.engine import rmlspool
from gerber2rml.gui2 import dialogs


def _busy(fn):
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        return fn()
    finally:
        QApplication.restoreOverrideCursor()


def setup_sheet(parent, run=None):
    """Explain, then make the SRM-20 queue. Returns the queue name or None."""
    d = dialogs.Sheet(parent, "Set up the mill on this Mac", width=560)
    d.say("SRM-CAM sends jobs to the SRM-20 through a printer queue named "
          "SRM-20. It is made once per Mac.")
    d.say("Switch the mill on and plug its USB cable into this Mac first. "
          "macOS will then ask for an administrator password.", small=True)
    d.setObjectName("millSetupSheet")
    d.act("Not now", on=d.reject)
    d.act("Set it up", kind="primary", on=d.accept, default=True)
    if not d.exec():
        return None
    try:
        queue = _busy(lambda: rmlspool.setup_mill_queue(
            run=run, say=lambda _m: None, admin="gui"))
    except rmlspool.SpoolError as e:
        dialogs.report_error(
            parent, "The mill could not be set up", e,
            "Check that the mill is switched on and its USB cable is in, "
            "then try again. docs/macos.md has the commands to do it by "
            "hand.")
        return None
    done = dialogs.Sheet(parent, "The mill is ready", width=520)
    done.say(f"Jobs now go to the {queue} queue on this Mac.")
    done.act("Close", kind="primary", on=done.accept, default=True)
    done.exec()
    return queue


def _ask(parent, headline, text, go, level="warn"):
    d = dialogs.Sheet(parent, headline, level=level, width=540)
    d.say(text)
    d.act("Cancel the run", on=d.reject)
    d.act(go, kind="primary", on=d.accept, default=True)
    return bool(d.exec())


def find_or_setup(parent, run=None):
    """The mill's queue name, offering setup when there is none."""
    name = rmlspool.find_mill()
    if name is None and setup_sheet(parent, run=run):
        name = rmlspool.find_mill()
    return name


def preflight(parent, printer, run=None):
    """Settle the queue before a run sends anything. True to go ahead."""
    try:
        st = printer.state()
        if st["exists"] and (st["stopped"] or not st["accepting"]):
            if not _ask(parent, "The SRM-20 queue is paused",
                        "macOS stops a printer queue after a job fails - "
                        "usually because the mill was off or unplugged. "
                        "Jobs sent now would wait there and never cut. "
                        "Resume it (asks for an administrator password)?",
                        "Resume the queue"):
                return False
            _busy(lambda: rmlspool.resume_queue(printer.name, run=run,
                                                admin="gui"))
        left = printer.pending()
        if left:
            if not _ask(parent, "Old jobs are waiting for the mill",
                        f"{left} job(s) from an earlier run are still in the "
                        f"SRM-20 queue. They would cut before this run. "
                        f"Clear them?", "Clear them"):
                return False
            if not printer.purge():
                dialogs.report_error(
                    parent, "The old jobs could not be cleared",
                    rmlspool.SpoolError("jobs still queued"),
                    "Someone else's jobs need an administrator to remove: "
                    "open System Settings ▸ Printers & Scanners ▸ SRM-20 ▸ "
                    "Open Print Queue and delete them.")
                return False
    except rmlspool.SpoolError as e:
        dialogs.report_error(parent, "The SRM-20 queue could not be read", e,
                             "Check the queue in System Settings ▸ Printers "
                             "& Scanners.")
        return False
    return True
