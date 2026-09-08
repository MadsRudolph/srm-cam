"""The setup sheet installs the KiCad build-area plugin: KiCad → Set up the
build-area plugin…, and the launch offer. Nothing here touches the real
KiCad folders."""
import pytest
from PySide6.QtWidgets import QPushButton

from gerber2rml.engine import kicadplugin
from gerber2rml.gui2 import dialogs, kicadsetup
from gerber2rml.gui2.window import MainWindow


class _Settings:
    def __init__(self):
        self.d = {}

    def value(self, k, default=None):
        return self.d.get(k, default)

    def setValue(self, k, v):
        self.d[k] = v

    def remove(self, k):
        self.d.pop(k, None)


@pytest.fixture
def win(qt_app):
    w = MainWindow()
    yield w
    w.close()


@pytest.fixture
def shown(monkeypatch):
    """Sheets are built but never block; we read them instead."""
    seen = []
    monkeypatch.setattr(dialogs.Sheet, "exec", lambda self: seen.append(self) or 0)
    return seen


def _root_with(tmp_path, monkeypatch, versions):
    root = tmp_path / "kicad"
    for ver in versions:
        (root / ver / "scripting" / "plugins").mkdir(parents=True)
    monkeypatch.setattr(kicadplugin, "config_roots", lambda *a, **k: [root])
    return root


def test_the_kicad_menu_offers_the_setup(win):
    assert win.kicad_act.text() == "Set up the build-area plugin…"


def test_setup_installs_into_every_kicad_version_found(win, shown, tmp_path, monkeypatch):
    """A PC upgraded from KiCad 9 to 10 keeps both trees, and the student
    opens whichever shortcut is on the desktop. Install into both."""
    root = _root_with(tmp_path, monkeypatch, ("9.0", "10.0"))
    s = _Settings(); s.setValue(kicadsetup.DECLINED_KEY, "1.0.0")

    done = kicadsetup.setup(win, s)

    assert len(done) == 2
    for ver in ("9.0", "10.0"):
        landed = root / ver / "scripting" / "plugins" / kicadplugin.PLUGIN_DIRNAME
        assert (landed / "action_srm20_area.py").is_file()
        assert (landed / "srm20area" / "geometry.py").is_file()
        assert kicadplugin.status(landed.parent, kicadplugin.bundled_version()) == "current"
    assert shown and "installed" in shown[0].windowTitle()
    assert s.value(kicadsetup.DECLINED_KEY) is None        # they have it now


def test_setup_creates_the_plugins_folder_a_fresh_kicad_lacks(win, shown, tmp_path, monkeypatch):
    root = tmp_path / "kicad"
    (root / "10.0" / "scripting").mkdir(parents=True)
    monkeypatch.setattr(kicadplugin, "config_roots", lambda *a, **k: [root])

    done = kicadsetup.setup(win, _Settings())

    assert done == [root / "10.0" / "scripting" / "plugins" / kicadplugin.PLUGIN_DIRNAME]


def test_setup_explains_itself_when_kicad_is_absent(win, shown, tmp_path, monkeypatch):
    """Not an error: plenty of people run SRM-CAM on a PC without KiCad."""
    monkeypatch.setattr(kicadplugin, "config_roots", lambda *a, **k: [tmp_path / "nope"])

    assert kicadsetup.setup(win, _Settings()) == []
    assert shown and "not found" in shown[0].windowTitle()


def test_the_launch_offer_asks_once_per_version(win, shown, tmp_path, monkeypatch):
    _root_with(tmp_path, monkeypatch, ("10.0",))
    s = _Settings()

    assert kicadsetup.maybe_offer(win, s) is True       # shown; exec stub = "Not now"
    assert s.value(kicadsetup.DECLINED_KEY) == kicadplugin.bundled_version()
    assert kicadsetup.maybe_offer(win, s) is False      # remembered
    assert len(shown) == 1
    btns = {b.text() for b in shown[0].findChildren(QPushButton)}
    assert {"Add it", "Not now"} <= btns


def test_the_launch_offer_stays_quiet_without_kicad_or_when_current(win, shown, tmp_path, monkeypatch):
    monkeypatch.setattr(kicadplugin, "config_roots", lambda *a, **k: [tmp_path / "nope"])
    assert kicadsetup.maybe_offer(win, _Settings()) is False

    root = _root_with(tmp_path, monkeypatch, ("10.0",))
    kicadplugin.install(kicadplugin.bundled_source(), root / "10.0" / "scripting" / "plugins")
    assert kicadsetup.maybe_offer(win, _Settings()) is False
    assert shown == []
