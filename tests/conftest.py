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
