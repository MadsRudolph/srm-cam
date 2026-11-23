"""The Discord invite: once at launch per round, and always under Help."""
import pytest

from PySide6.QtWidgets import QPushButton

from gerber2rml.gui2 import community, dialogs
from gerber2rml.gui2.window import MainWindow


class _Settings:
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


def test_help_has_the_discord(win):
    assert win.discord_act.text() == "Join the Discord…"


def test_invite_shows_once_and_join_opens_the_link(win, monkeypatch):
    seen, opened = [], []

    def fake_exec(sheet):
        seen.append(sheet)
        [b for b in sheet.findChildren(QPushButton)
         if b.text() == "Join the Discord"][0].click()
        return 1

    monkeypatch.setattr(dialogs.Sheet, "exec", fake_exec)
    s = _Settings()
    assert community.maybe_invite(win, s, opener=opened.append) is True
    assert opened == [win] and len(seen) == 1
    assert community.maybe_invite(win, s, opener=opened.append) is False


def test_not_now_is_remembered_until_the_next_round(win, monkeypatch):
    monkeypatch.setattr(dialogs.Sheet, "exec", lambda self: 0)
    s, opened = _Settings(), []
    assert community.maybe_invite(win, s, opener=opened.append) is True
    assert opened == []
    assert not community.should_invite(s)
    monkeypatch.setattr(community, "INVITE_ROUND", community.INVITE_ROUND + 1)
    assert community.should_invite(s)
