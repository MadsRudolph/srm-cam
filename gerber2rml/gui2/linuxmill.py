"""The mill's USB on Linux, from inside the app.

On Windows the Roland driver installs the mill as a printer, and on a Mac it is
a CUPS queue (:mod:`gerber2rml.gui2.macmill`). On Linux the kernel already
makes it a printer node, ``/dev/usb/lp0``, the moment its USB cable is in - but
root-owned, as is the Arduino's ``/dev/ttyUSB0`` and the mill's settings
channel. This is what the app says and does about that, so nobody has to open
a terminal:

* **Machine ▸ Set up USB access…** installs one udev rule
  (``platform.UDEV_RULES``) that hands those nodes to whoever is logged in at
  the screen. The system's own password dialog asks, through ``pkexec``; where
  there is no such dialog the sheet shows the terminal command instead.
* **Before a run** (:func:`find_or_setup`): no mill node is a plain "plug it
  in", and a node SRM-CAM may not open is offered the setup.
"""
import os
import subprocess
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gerber2rml import platform as plat
from gerber2rml.engine import rmlspool
from gerber2rml.gui2 import dialogs


def _busy(fn):
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        return fn()
    finally:
        QApplication.restoreOverrideCursor()


def terminal_commands():
    """The same setup, for pasting into a terminal."""
    rules = plat.UDEV_RULES.replace("'", "'\\''")
    return ("printf '%s' '" + rules + "' | sudo tee "
            + plat.UDEV_RULES_PATH + " >/dev/null && sudo udevadm control "
            "--reload && sudo udevadm trigger --action=change "
            "--subsystem-match=tty --subsystem-match=usbmisc "
            "--subsystem-match=usb")


def install_rules(run=None):
    """Write the udev rule as root through pkexec. Raises SpoolError."""
    run = subprocess.run if run is None else run
    fd, path = tempfile.mkstemp(prefix="srm-cam-", suffix=".rules")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(plat.UDEV_RULES)
        try:
            r = run(["pkexec", "sh", "-c", plat.udev_install_script(path)],
                    capture_output=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as e:
            raise rmlspool.SpoolError(f"pkexec could not run ({e})") from e
        if r.returncode != 0:
            err = (r.stderr or b"").decode("utf-8", "replace").strip()
            if r.returncode == 126:
                raise rmlspool.SpoolError("cancelled - no password was given")
            raise rmlspool.SpoolError(err or f"pkexec exit {r.returncode}")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def setup_sheet(parent, run=None):
    """Explain, then install the rule. True when it is in place."""
    d = dialogs.Sheet(parent, "Set up USB access on this PC", width=600)
    d.say("SRM-CAM talks to the SRM-20 over two USB cables: the Arduino "
          "(position, probing, STOP) and the mill's own cable (the jobs, and "
          "its settings). Linux lets only root open them until one rule is "
          "installed. It is done once per PC.")
    d.say("The system will ask for your password. The rule gives the person "
          "logged in at this screen access to those devices and nothing "
          "else; it is written to " + plat.UDEV_RULES_PATH + ".", small=True)
    d.setObjectName("usbSetupSheet")
    d.act("Not now", on=d.reject)
    d.act("Set it up", kind="primary", on=d.accept, default=True)
    if not d.exec():
        return False
    try:
        _busy(lambda: install_rules(run=run))
    except rmlspool.SpoolError as e:
        fail = dialogs.Sheet(parent, "USB access could not be set up",
                             level="warn", width=640)
        fail.say(str(e))
        fail.say("Run this in a terminal instead (it asks for your password "
                 "there):", small=True)
        fail.say(terminal_commands(), mono=True, small=True)
        fail.act("Close", kind="primary", on=fail.accept, default=True)
        fail.exec()
        return False
    done = dialogs.Sheet(parent, "USB access is set up", width=520)
    done.say("The mill and the Arduino can be used from SRM-CAM now. If a "
             "cable was plugged in while this ran and still refuses, unplug "
             "it and plug it back in.")
    done.act("Close", kind="primary", on=done.accept, default=True)
    done.exec()
    return True


def find_or_setup(parent, run=None):
    """The mill's printer node, offering USB setup when it may not be opened.

    Returns the node, or None after saying why there is none.
    """
    node = rmlspool.find_mill()
    if node is None:
        dialogs.report_error(
            parent, "The SRM-20 is not on USB",
            rmlspool.SpoolError("no /dev/usb/lp node for a Roland device"),
            "The mill has its own USB cable, separate from the Arduino's. "
            "Check that it is plugged into this PC and the mill is switched "
            "on, then try again.")
        return None
    why = rmlspool.UsbLpPrinter(node).problem()
    if why is None:
        return node
    if "permission" in why and setup_sheet(parent, run=run):
        if rmlspool.UsbLpPrinter(node).problem() is None:
            return node
        why = rmlspool.UsbLpPrinter(node).problem() or why
    dialogs.report_error(parent, "The mill's USB could not be opened",
                         rmlspool.SpoolError(why),
                         "Machine ▸ Set up USB access… fixes a refused "
                         "port. Unplug the mill's USB cable and plug it back "
                         "in if it still refuses.")
    return None
