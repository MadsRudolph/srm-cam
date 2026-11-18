"""Is there a newer SRM-CAM? Two ways in, one answer.

The engine (:mod:`gerber2rml.engine.updates`) asks GitHub and compares
versions; this is what the setup sheet does with the answer.

* **Help → Check for updates…** asks now, on a worker thread with the
  cursor busy, and says what it found either way — up to date, an update,
  or that it could not find out. Asked on the GUI thread, a slow network
  froze the window for as long as the request took.
* **At launch**, a probe runs in a thread so a lab PC behind a captive
  portal never holds the window, and speaks only if there is genuinely a
  newer release the person has not already been told about. Once per
  version, then it stays quiet.

This is not a self-updater. A frozen app cannot safely overwrite itself
while it is running, and the install on a lab PC is often not the student's
to replace. It finds out and points at the download; the install is their
click.
"""
import threading

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal, Slot
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


def mac_checkout(frozen=None, meipass=None, here=None):
    """The source checkout this Mac copy was built from, or None.

    The releases on GitHub are Windows and Linux files; a Mac copy is built
    from a checkout (packaging/build-macos.sh), so updating it means
    rebuilding there. A frozen build carries the path in build_info.json;
    a source run is the checkout itself.
    """
    import json
    import sys
    from pathlib import Path
    from gerber2rml import platform as plat
    if not plat._is_macos():
        return None
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen:
        base = Path(meipass or getattr(sys, "_MEIPASS", ""))
        try:
            repo = Path(json.loads((base / "build_info.json").read_text(
                encoding="utf-8"))["repo"])
        except (OSError, ValueError, KeyError):
            return None
    else:
        repo = Path(here or __file__).resolve().parents[2]
    script = repo / "packaging" / "update-macos.sh"
    return repo if script.is_file() and (repo / ".git").exists() else None


def run_mac_update(repo):
    """Open Terminal on packaging/update-macos.sh --install for ``repo``."""
    import os
    import shlex
    import tempfile
    fd, path = tempfile.mkstemp(prefix="srm-cam-update-", suffix=".command")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\n"
                f"cd {shlex.quote(str(repo))} && "
                "packaging/update-macos.sh --install\n")
    os.chmod(path, 0o755)
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def result_sheet(parent, result, checkout=None):
    """The dialog for an answer. Returned unshown so a test can read it.

    ``checkout`` is :func:`mac_checkout`'s answer: given, an update is
    offered as a rebuild there instead of a download."""
    repo = checkout if result.status == updates.UPDATE else None
    if repo is not None:
        d = dialogs.Sheet(parent, f"SRM-CAM {result.latest} is available",
                          width=560)
        d.say(f"You are running {__version__}. This Mac copy is built from "
              f"the source in {repo}, so updating means rebuilding it there.")
        d.say("Update now opens Terminal: it fetches the new version, runs "
              "the tests, builds the app and installs it in Applications. "
              "Quit SRM-CAM when it asks.", small=True)
        d.act("Not now", on=d.reject)
        d.act("Update now", kind="primary",
              on=lambda: (run_mac_update(repo), d.accept()), default=True)
        d.setObjectName("updateSheet")
        return d
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


class _Ask(QObject):
    """One Help → Check for updates…: the request on a worker thread, the
    answer shown on the GUI thread (this object lives there).

    A plain daemon thread rather than a QThread: quitting while GitHub is
    slow to answer must neither wait for it nor destroy a running QThread.
    """

    answered = Signal(object)        # emitted from the worker
    done = Signal(object)            # the Result, once its sheet has closed

    def __init__(self, parent, fetch=None):
        super().__init__(parent)
        self._fetch = fetch
        self.result = None
        self.answered.connect(self._show)
        self.thread = threading.Thread(target=self._ask, daemon=True,
                                       name="srm-cam update check")

    def start(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.thread.start()
        return self

    def busy(self):
        return self.thread.is_alive() or self.result is None

    def _ask(self):                  # worker thread: no widgets here
        result = updates.check(__version__, fetch=self._fetch)   # never raises
        try:
            self.answered.emit(result)
        except RuntimeError:         # the window has gone: nobody to tell
            pass

    @Slot(object)
    def _show(self, result):
        QApplication.restoreOverrideCursor()
        self.result = result
        try:
            result_sheet(self.parent(), result, mac_checkout()).exec()
        finally:
            self.done.emit(result)


def check_now(parent, fetch=None):
    """Help → Check for updates…: ask on a worker thread, then say what was
    found. Returns at once with the :class:`_Ask` doing it; its ``done``
    signal carries the engine's Result. A second click while one is out
    gets the one already asking."""
    asking = getattr(parent, "_update_ask", None)
    if asking is not None:
        if asking.busy():
            return asking
        try:
            asking.deleteLater()
        except RuntimeError:
            pass
    ask = _Ask(parent, fetch)
    parent._update_ask = ask
    return ask.start()


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
    result_sheet(parent, result, mac_checkout()).exec()
    return True


def start_probe(parent, on_result, fetch=None):
    """Kick off the launch check; ``on_result`` gets the engine's Result on
    the GUI thread. The thread is parented so it dies with the window."""
    probe = Probe(parent=parent, fetch=fetch)
    probe.checked.connect(on_result)
    probe.start()
    return probe
