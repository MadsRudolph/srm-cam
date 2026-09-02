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


@pytest.fixture(autouse=True)
def _machine_link_present(request, monkeypatch):
    """Run the suite as if the host had the machine link.

    Same argument as ``_professional_mode`` above: the link is the default on
    the platform this program was written for, and hundreds of these tests
    call a machine-control handler directly and assert on what it did. Off
    Windows those handlers now stop at ``_no_link()``, which puts up a modal
    QMessageBox - and a modal with nobody to click it does not fail, it hangs.
    A whole afternoon of the suite timing out on Linux, one test at a time,
    is what this fixture is for.

    Pinning it here rather than skipping keeps every one of those tests
    meaning exactly what it says on any host, which is the same reason
    platform.py takes an injected platform instead of branching on
    sys.platform. An EXPLICIT platform still resolves honestly, so the tests
    that pass "linux" or "win32" are unaffected, and the ones that gate the UI
    monkeypatch capabilities themselves - after this fixture, so they win.
    """
    if "host_capabilities" in request.keywords:
        yield                      # this test is ABOUT the honest default
        return
    from gerber2rml import platform as plat
    real = plat.capabilities
    monkeypatch.setattr(
        plat, "capabilities",
        lambda platform=None: real(plat.WINDOWS if platform is None else platform))
    yield
