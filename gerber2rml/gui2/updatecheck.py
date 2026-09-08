"""Is there a newer SRM-CAM? Two ways in, one answer.

The engine (:mod:`gerber2rml.engine.updates`) asks GitHub and compares
versions; this is what the setup sheet does with the answer.

* **Help → Check for updates…** asks now, with the cursor busy, and says
  what it found either way — up to date, an update, or that it could not
  find out.
* **At launch**, a probe runs in a thread so a lab PC behind a captive
  portal never holds the window, and speaks only if there is genuinely a
  newer release the person has not already been told about. Once per
  version, then it stays quiet.

This is not a self-updater. A frozen app cannot safely overwrite itself
while it is running, and the install on a lab PC is often not the student's
to replace. It finds out and points at the download; the install is their
click.
"""
from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from gerber2rml import __version__
from gerber2rml.engine import updates
from gerber2rml.gui2 import dialogs, tier

DISMISSED_KEY = "updates/dismissed_version"


class Probe(QThread):
    """The launch-time check, off the GUI thread. Emits the engine's Result."""

    checked = Signal(object)

    def __init__(self, version=__version__, parent=None, fetch=None):
        super().__init__(parent)
        self._version = version
        self._fetch = fetch

    def run(self):
        try:
            self.checked.emit(updates.check(self._version, fetch=self._fetch))
        except Exception:                       # noqa: BLE001 - best effort
            pass


def result_sheet(parent, result):
    """The dialog for an answer. Returned unshown so a test can read it."""
    if result.status == updates.UPDATE:
        d = dialogs.Sheet(parent, f"SRM-CAM {result.latest} is available",
                          width=560)
        d.say(f"You are running {__version__}. The download is a file on "
              "GitHub; install it the same way as the first time.")
        notes = (result.notes or "").strip()
        if notes:
            if len(notes) > 700:
                notes = notes[:700].rstrip() + "…"
            d.say("What's new", small=True)
            d.say(notes, small=True, mono=True)
        d.act("Not now", on=d.reject)
        d.act("Open the download page", kind="primary",
              on=lambda: (QDesktopServices.openUrl(QUrl(result.url)),
                          d.accept()),
              default=True)
    elif result.status == updates.CURRENT:
        d = dialogs.Sheet(parent, "Up to date", width=480)
        d.say(result.message)
        d.act("Close", kind="primary", on=d.accept, default=True)
    else:
        d = dialogs.Sheet(parent, "Could not check for updates", level="warn",
                          width=520)
        d.say("This needs a connection to github.com. The releases page "
              "shows the newest version if you can reach it another way.")
        d.say(result.message, small=True, mono=True)
        d.act("Close", on=d.reject, default=True)
        d.act("Open the releases page", kind="primary",
              on=lambda: (QDesktopServices.openUrl(QUrl(result.url)),
                          d.accept()))
    d.setObjectName("updateSheet")
    return d


def check_now(parent, fetch=None):
    """Help → Check for updates…: ask, then say what was found."""
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        result = updates.check(__version__, fetch=fetch)
    finally:
        QApplication.restoreOverrideCursor()
    result_sheet(parent, result).exec()
    return result


def dismissed_version(settings=None):
    return (settings or tier._settings()).value(DISMISSED_KEY) or None


def announce(parent, result, settings=None):
    """The launch probe's answer. True if it was shown.

    Shown once per new version: "Not now" is remembered, and the menu is
    always there for a second look.
    """
    settings = settings or tier._settings()
    if not updates.should_announce(result, dismissed_version(settings)):
        return False
    settings.setValue(DISMISSED_KEY, result.latest)
    result_sheet(parent, result).exec()
    return True


def start_probe(parent, on_result, fetch=None):
    """Kick off the launch check; ``on_result`` gets the engine's Result on
    the GUI thread. The thread is parented so it dies with the window."""
    probe = Probe(parent=parent, fetch=fetch)
    probe.checked.connect(on_result)
    probe.start()
    return probe
