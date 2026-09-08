"""The setup sheet's update check: Help → Check for updates…, and the quiet
probe at launch. The network is injected everywhere; nothing here reaches
GitHub."""
import json

import pytest
from PySide6.QtWidgets import QPushButton

from gerber2rml import __version__
from gerber2rml.engine import updates
from gerber2rml.gui2 import dialogs, updatecheck
from gerber2rml.gui2.window import MainWindow


def _release(tag, body="- fixed the thing"):
    return json.dumps({"tag_name": tag, "html_url": f"https://example.invalid/{tag}",
                       "body": body}).encode("utf-8")


def _newer():
    a, b, c = (int(p) for p in __version__.split(".")[:3])
    return f"v{a}.{b}.{c + 1}"


class _Settings:
    """QSettings, as far as the check cares."""
    def __init__(self):
        self.d = {}

    def value(self, k, default=None):
        return self.d.get(k, default)

    def setValue(self, k, v):
        self.d[k] = v


@pytest.fixture
def win(qt_app):
    w = MainWindow()
    yield w
    w.close()


@pytest.fixture
def no_exec(monkeypatch):
    """Dialogs are built but never block."""
    shown = []
    monkeypatch.setattr(dialogs.Sheet, "exec", lambda self: shown.append(self) or 0)
    return shown


def _buttons(sheet):
    return {b.text(): b for b in sheet.findChildren(QPushButton)}


def test_help_menu_offers_the_check(win):
    assert win.update_act.text() == "Check for updates…"


def test_an_update_names_the_version_and_offers_the_download(win):
    result = updates.check(__version__, fetch=lambda u, t: _release(_newer()))
    d = updatecheck.result_sheet(win, result)
    assert result.latest in d.windowTitle()
    btns = _buttons(d)
    assert "Open the download page" in btns
    assert btns["Open the download page"].objectName() == "primary"
    assert "Not now" in btns


def test_up_to_date_says_so_and_only_closes(win):
    result = updates.check(__version__, fetch=lambda u, t: _release("v" + __version__))
    d = updatecheck.result_sheet(win, result)
    assert d.windowTitle() == "Up to date"
    assert list(_buttons(d)) == ["Close"]


def test_a_failed_check_is_information_not_an_error_dump(win):
    def down(u, t):
        raise OSError("no route to host")
    result = updates.check(__version__, fetch=down)
    d = updatecheck.result_sheet(win, result)
    assert "Could not check" in d.windowTitle()
    assert "Open the releases page" in _buttons(d)


def test_check_now_shows_a_sheet_and_restores_the_cursor(win, no_exec, qt_app):
    result = updatecheck.check_now(win, fetch=lambda u, t: _release(_newer()))
    assert result.status == updates.UPDATE
    assert len(no_exec) == 1
    assert qt_app.overrideCursor() is None


def test_the_launch_probe_speaks_once_per_version(win, no_exec):
    s = _Settings()
    result = updates.check(__version__, fetch=lambda u, t: _release(_newer()))
    assert updatecheck.announce(win, result, s) is True
    assert updatecheck.announce(win, result, s) is False       # remembered
    assert len(no_exec) == 1
    assert s.value(updatecheck.DISMISSED_KEY) == result.latest


def test_the_launch_probe_stays_quiet_when_current_or_offline(win, no_exec):
    s = _Settings()
    current = updates.check(__version__, fetch=lambda u, t: _release("v" + __version__))
    assert updatecheck.announce(win, current, s) is False

    def down(u, t):
        raise OSError("offline")
    assert updatecheck.announce(win, updates.check(__version__, fetch=down), s) is False
    assert no_exec == []


def test_the_probe_thread_hands_back_the_engine_result(win, qt_app):
    got = []
    probe = updatecheck.Probe(parent=win, fetch=lambda u, t: _release(_newer()))
    probe.checked.connect(got.append)
    probe.run()                     # synchronously, on this thread
    assert got and got[0].status == updates.UPDATE
