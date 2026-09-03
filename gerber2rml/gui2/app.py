"""Entry point.

Two things happen here that are easy to leave out and expensive to debug
without:

**A log file, opened before anything else is imported.** The installed
launcher is a ``pythonw`` GUI script with no console attached, so a traceback
raised while importing PySide6 or matplotlib goes to a stream nobody is
reading and the application simply fails to appear. Redirecting first means
every startup failure lands in ``Documents/SRM-CAM/gui2.log`` where it can be
read.

**A last-resort message box.** If the window cannot be built at all, the user
gets a dialog naming the log rather than nothing at all happening when they
double-click the shortcut.
"""
import os
import sys
import traceback
from pathlib import Path


def _log_path():
    env = os.environ.get("SRM_CAM_HOME")
    if env:
        root = Path(env)
    else:
        from gerber2rml import platform as plat
        root = plat.documents_dir() / "SRM-CAM"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return root / "gui2.log"


def _redirect_output():
    """Send stdout/stderr to the log when there is no console to write to."""
    try:
        interactive = sys.stdout is not None and sys.stdout.isatty()
    except (ValueError, OSError):
        interactive = False        # a closed stdout: the launcher case
    if interactive:
        return None
    path = _log_path()
    if path is None:
        return None
    try:
        f = open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return None
    sys.stdout = sys.stderr = f
    return path


def main(argv=None):
    log = _redirect_output()
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont
        from PySide6.QtCore import Qt

        from gerber2rml import glconfig
        from gerber2rml.gui2 import theme, style
        from gerber2rml.gui2.window import MainWindow
    except Exception:
        traceback.print_exc()
        _panic("SRM-CAM could not start because a dependency failed to "
               "import.", log)
        return 1

    # Before the QApplication, not after: Qt reads these while it starts up.
    # Without it the 3D simulator opens blank on Windows and raises on Linux.
    if QApplication.instance() is None:
        glconfig.configure()

    app = QApplication.instance() or QApplication(list(argv or sys.argv))
    app.setApplicationName("SRM-CAM")
    app.setApplicationDisplayName("SRM-CAM")
    app.setOrganizationName("SRM-CAM")
    # The base font is the prose face; every other role is set through
    # theme.font() at the point of use, so the scale is applied rather than
    # inherited from whatever Qt picked.
    base = QFont(theme.BODY_FAMILY[0])
    base.setFamilies(theme.BODY_FAMILY)
    base.setPointSizeF(theme.SIZE_BODY * 0.75)
    app.setFont(base)
    app.setStyleSheet(style.STYLESHEET)

    try:
        w = MainWindow()
        w.show()
    except Exception:
        traceback.print_exc()
        _panic("SRM-CAM could not build its window.", log)
        return 1
    return app.exec()


def _panic(headline, log):
    """Say something, even when the application itself did not come up."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        box = QMessageBox(QMessageBox.Critical, "SRM-CAM", headline)
        box.setInformativeText(
            f"The details were written to:\n{log}" if log else
            "No log file could be opened either — run it from a terminal with "
            "`python -m gerber2rml.gui2` to see the error.")
        box.exec()
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
