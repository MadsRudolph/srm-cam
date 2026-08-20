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
