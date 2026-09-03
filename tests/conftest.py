"""Shared test setup: keep tests out of the user's real workspace.

The app keeps user data in Documents/SRM-CAM (dialog start dirs, the
tool-wear ledger, ...). SRM_CAM_HOME relocates all of it; pointing it at a
per-session temp dir means a test run never pollutes real mileage counters
or creates folders in Documents.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path_factory, monkeypatch):
    ws = tmp_path_factory.getbasetemp() / "srm-cam-workspace"
    monkeypatch.setenv("SRM_CAM_HOME", str(ws))
    yield


@pytest.fixture(autouse=True)
def _professional_mode(monkeypatch):
    """Run the suite against the FULL UI.

    Novice is the default mode on a fresh install (gerber2rml/gui/mode.py), and
    it hides most of what these tests assert on — job parameter forms, the
    double-sided controls, the machine dock. Pinning Professional here keeps
    every existing test meaning exactly what it says. The Novice behaviour has
    its own tests in test_mode.py, which opt back out of this fixture by
    setting the variable themselves.

    Using the env override rather than the stored preference is deliberate: it
    also keeps the test run from writing to the developer's real QSettings.
    """
    monkeypatch.setenv("SRM_CAM_MODE", "pro")


@pytest.fixture(scope="session", autouse=True)
def _isolated_qsettings(tmp_path_factory):
    """Keep every QSettings the suite touches out of the developer's registry.

    Both interfaces construct ``QSettings("SRM-CAM", ...)`` for the remembered
    folders, the tier and the mode. In the native format on Windows that is
    HKCU, and every test that loaded a fixture folder wrote it there as the
    last-used Gerber folder - so the next REAL export dialog opened in a pytest
    temp directory full of fixtures. Pointing the default format at INI files
    under the session's temp dir catches every construction in the process,
    with the product code untouched.
    """
    from PySide6.QtCore import QSettings
    d = tmp_path_factory.getbasetemp() / "qsettings"
    d.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(d))
    yield


@pytest.fixture(scope="session")
def qt_app():
    """One offscreen QApplication for the whole session.

    Qt allows exactly one, and it must outlive every widget any test builds, so
    it is session-scoped and never torn down. Added for the gui2 tests; the
    older GUI tests make their own at module import and are unaffected.
    """
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return app
