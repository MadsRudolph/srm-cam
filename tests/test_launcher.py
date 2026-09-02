"""Which interface the frozen app opens, and that it can still reach the other.

packaging/launcher.py is what PyInstaller bundles. It used to import
gerber2rml.gui.app unconditionally, so an installed copy could not open the
second interface at all - which is most of the people the A/B in
docs/HANDOFF-gui-ab.md was meant to be asked of.

That A/B is decided now: SRM-CAM IS the setup sheet, and these tests are what
stops the default quietly reverting. The first interface is still built and
still reachable behind --original, because a migration is not a deletion.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "srm_cam_launcher",
    Path(__file__).resolve().parents[1] / "packaging" / "launcher.py")
launcher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(launcher)


@pytest.fixture
def _stub_interfaces(monkeypatch):
    """Record which interface was started, without starting a Qt app."""
    called = {}
    import gerber2rml.gui.app as gui1
    import gerber2rml.gui2.app as gui2

    def _gui1():
        called["who"] = "gui1"
        return 0

    def _gui2(argv=None):
        called["who"] = "gui2"
        called["argv"] = argv
        return 0

    monkeypatch.setattr(gui1, "main", _gui1)
    monkeypatch.setattr(gui2, "main", _gui2)
    return called


def test_no_flag_starts_the_setup_sheet(_stub_interfaces):
    """The decision, asserted. SRM-CAM with no arguments is the second interface."""
    assert launcher.main(["SRM-CAM"]) == 0
    assert _stub_interfaces["who"] == "gui2"


def test_the_original_flag_starts_the_first_interface(_stub_interfaces):
    assert launcher.main(["SRM-CAM", launcher.ORIGINAL_FLAG]) == 0
    assert _stub_interfaces["who"] == "gui1"


def test_the_old_setup_sheet_flag_still_opens_the_setup_sheet(_stub_interfaces):
    """It is spelled into shortcuts and shell history on machines already out
    there. Silently opening the other interface would be worse than a dead
    option, so it stays, doing what it always did."""
    assert launcher.main(["SRM-CAM", launcher.SETUP_SHEET_FLAG]) == 0
    assert _stub_interfaces["who"] == "gui2"


def test_our_flags_are_consumed_not_passed_to_qt(_stub_interfaces):
    """Qt parses argv itself and warns about options it does not know."""
    launcher.main(["SRM-CAM", launcher.SETUP_SHEET_FLAG, "--", "board"])
    assert launcher.SETUP_SHEET_FLAG not in _stub_interfaces["argv"]
    assert _stub_interfaces["argv"][0] == "SRM-CAM"   # argv[0] survives
    assert "board" in _stub_interfaces["argv"]        # everything else does too


def test_a_program_named_like_the_flag_is_not_the_flag(_stub_interfaces):
    """Only argv[1:] is searched, so argv[0] cannot select an interface."""
    launcher.main([launcher.ORIGINAL_FLAG])
    assert _stub_interfaces["who"] == "gui2"          # the default, not gui1


def test_the_desktop_entries_name_a_launchable_command():
    """Each .desktop Exec must be something launcher.main() actually answers.

    The AppImage installs these; an Exec line the launcher ignores gives a
    silent second copy of the default interface rather than an error.
    """
    pkg = Path(__file__).resolve().parents[1] / "packaging"
    execs = {}
    for entry in pkg.glob("*.desktop"):
        for line in entry.read_text(encoding="utf-8").splitlines():
            if line.startswith("Exec="):
                execs[entry.name] = line[len("Exec="):].split()
    assert execs, "no desktop entries found"
    for name, argv in execs.items():
        assert argv[0] == "SRM-CAM", f"{name}: unexpected command {argv[0]}"
        for opt in argv[1:]:
            assert opt in launcher._FLAGS, f"{name}: unknown option {opt}"
    assert any(a == ["SRM-CAM"] for a in execs.values()), \
        "no desktop entry opens the default interface"
    assert any(launcher.ORIGINAL_FLAG in a for a in execs.values()), \
        "no desktop entry opens the original interface"
