"""Platform differences have one home, and these tests keep them there.

Every assertion injects a platform string rather than reading the host's, so
the Linux behaviour is tested on Windows and vice versa. A test that only
passes on the machine it was written on proves nothing about the other one.
"""
import pytest
from pathlib import Path

from gerber2rml import platform as plat


def test_machine_link_is_windows_only():
    assert plat.capabilities("win32").machine_link is True
    assert plat.capabilities("linux").machine_link is False
    assert plat.capabilities("darwin").machine_link is False


def test_default_serial_port_is_com5_on_windows():
    assert plat.default_serial_port("win32") == "COM5"


def test_default_serial_port_refuses_to_guess_off_windows():
    """A guess at /dev/ttyACM0 may be some other board entirely, and produces
    a confusing timeout. spi_probe.best_port returns None for the same reason."""
    assert plat.default_serial_port("linux") is None
    assert plat.default_serial_port("darwin") is None


def test_reveal_selects_the_file_on_windows():
    cmd = plat.reveal_command(Path(r"C:\work\board_traces.nc"), "win32")
    assert cmd[0] == "explorer"
    assert "board_traces.nc" in cmd[-1]


def test_reveal_has_no_command_off_windows():
    """xdg-open cannot select a file, only open a folder - so there is nothing
    better here than the caller's existing QDesktopServices fallback, and
    returning None says so rather than pretending."""
    assert plat.reveal_command(Path("/home/mads/board.nc"), "linux") is None


@pytest.mark.host_capabilities
def test_capabilities_defaults_to_the_running_host():
    import sys
    assert plat.capabilities().machine_link == sys.platform.startswith("win")


def test_permission_hint_names_the_group_the_device_actually_has():
    """Fedora and Ubuntu use dialout; Arch uses uucp. Advice naming the wrong
    group is advice that silently does not work, which is worse than none - so
    the group is read off the device rather than assumed."""
    hint = plat.serial_permission_hint(
        "/dev/ttyACM0", "linux",
        stat_fn=lambda p: type("st", (), {"st_gid": 986})(),
        group_fn=lambda gid: "uucp")
    assert "uucp" in hint
    assert "dialout" not in hint
    assert "sudo usermod -aG uucp" in hint
    assert "log out" in hint.lower()


def test_permission_hint_says_dialout_when_that_is_the_group():
    hint = plat.serial_permission_hint(
        "/dev/ttyACM0", "linux",
        stat_fn=lambda p: type("st", (), {"st_gid": 20})(),
        group_fn=lambda gid: "dialout")
    assert "sudo usermod -aG dialout $USER" in hint


def test_permission_hint_is_silent_on_windows():
    """Windows has no group to join; a hint here would be noise."""
    assert plat.serial_permission_hint("COM5", "win32") is None


def test_permission_hint_survives_a_device_that_is_not_there():
    """The device may have been unplugged between the failure and the hint."""
    def boom(_p):
        raise FileNotFoundError
    hint = plat.serial_permission_hint("/dev/ttyACM0", "linux", stat_fn=boom,
                                        group_fn=lambda gid: "dialout")
    assert hint is None


def test_no_com5_literals_left_in_the_first_interface():
    """Eight of these was the reason platform.py exists. The literal belongs in
    one place now, and this fails if one grows back."""
    import re
    app = (Path(__file__).parent.parent / "gerber2rml" / "gui" / "app.py")
    offenders = [f"{i}: {line.strip()[:70]}"
                 for i, line in enumerate(
                     app.read_text(encoding="utf-8").split("\n"), 1)
                 if re.search(r'"COM\d+"', line)]
    assert not offenders, (
        "hardcoded COM port(s) - use platform.default_serial_port():\n  "
        + "\n  ".join(offenders))


def test_documents_dir_reads_the_xdg_user_dirs_file(tmp_path):
    """A Danish desktop calls it Dokumenter. Qt knows that because it reads
    user-dirs.dirs; _log_path cannot ask Qt, so it reads the same file."""
    cfg = tmp_path / ".config"
    cfg.mkdir()
    (cfg / "user-dirs.dirs").write_text(
        '# generated\nXDG_DESKTOP_DIR="$HOME/Skrivebord"\n'
        'XDG_DOCUMENTS_DIR="$HOME/Dokumenter"\n', encoding="utf-8")
    (tmp_path / "Dokumenter").mkdir()
    assert plat.documents_dir(home=tmp_path, platform="linux") == \
        tmp_path / "Dokumenter"


def test_documents_dir_falls_back_when_there_is_no_xdg_config(tmp_path):
    (tmp_path / "Documents").mkdir()
    assert plat.documents_dir(home=tmp_path, platform="linux") == \
        tmp_path / "Documents"


def test_documents_dir_falls_back_to_home_when_nothing_exists(tmp_path):
    assert plat.documents_dir(home=tmp_path, platform="linux") == tmp_path


def test_documents_dir_does_not_read_xdg_on_windows(tmp_path):
    """Windows has no user-dirs.dirs; Documents is Documents."""
    (tmp_path / "Documents").mkdir()
    assert plat.documents_dir(home=tmp_path, platform="win32") == \
        tmp_path / "Documents"


def test_arduino_cli_candidates_point_into_the_ide_on_windows(tmp_path):
    got = plat.arduino_cli_candidates(
        "win32", env={"LOCALAPPDATA": r"C:\Users\x\AppData\Local"},
        home=tmp_path)
    assert any("arduino-cli.exe" in str(p) for p in got)


def test_arduino_cli_candidates_cover_the_linux_ide_layouts(tmp_path):
    got = [str(p) for p in plat.arduino_cli_candidates("linux", env={},
                                                       home=tmp_path)]
    assert any(p.startswith("/opt/") for p in got)
    # .as_posix(), not str(): the home-relative candidate is normalised to
    # forward slashes like the other two, so it never contains tmp_path's own
    # native (backslash, on Windows) string form.
    assert any(tmp_path.as_posix() in p for p in got)
    assert not any(p.endswith(".exe") for p in got)


def test_arduino_cli_candidates_use_forward_slashes_even_for_the_home_entry(tmp_path):
    """The home-relative candidate is built from ``home`` - already coerced to
    the real host's Path flavour at the top of the function - so it is the one
    entry that can smuggle backslashes back in if it does not also get
    PurePosixPath treatment. The other two entries are bare literals and can't
    fail this way, which is exactly how this slipped past them once already."""
    got = [str(p) for p in plat.arduino_cli_candidates("linux", env={},
                                                       home=tmp_path)]
    assert got, "no candidates returned"
    for p in got:
        assert "\\" not in p, p
        assert "/" in p, p


def test_arduino_library_dir_differs_by_platform(tmp_path):
    assert plat.arduino_library_dir("win32", home=tmp_path) == \
        tmp_path / "Documents" / "Arduino" / "libraries"
    assert plat.arduino_library_dir("linux", home=tmp_path) == \
        tmp_path / "Arduino" / "libraries"


PKG = Path(__file__).parent.parent / "gerber2rml"

# kicadplugin.config_roots predates platform.py, already takes an injectable
# platform argument, and already has the Linux branch. It is the pattern this
# module copied rather than a violation of it.
_ALLOWED = {"platform.py", "kicadplugin.py"}


def test_no_bare_platform_checks_outside_the_platform_module():
    """Same discipline as test_gui2_theme's no-hex-literals rule, for the same
    reason: a difference spelled out at the call site is one nobody can find."""
    offenders = []
    for f in sorted(PKG.rglob("*.py")):
        if f.name in _ALLOWED:
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            if "sys.platform" in line or "platform.system()" in line:
                offenders.append(f"{f.relative_to(PKG)}:{i}  {line.strip()[:70]}")
    assert not offenders, (
        "platform checks outside gerber2rml/platform.py - add a named "
        "function there instead:\n  " + "\n  ".join(offenders))


def test_platform_module_imports_no_qt_and_no_third_party():
    """gui2/app.py imports this before PySide6, because surviving that import
    is what it is for. A Qt import here would defeat the whole arrangement.

    Checked against import lines only, not the whole file: platform.py's own
    docstrings explain, in prose, exactly why PySide6 must stay out - a bare
    substring scan would fail on that explanation as if it were the offence."""
    lines = (PKG / "platform.py").read_text(encoding="utf-8").split("\n")
    imports = [line.strip() for line in lines
               if line.strip().startswith(("import ", "from "))]
    for banned in ("PySide6", "serial", "shapely", "gerbonara", "numpy"):
        assert not any(banned in line for line in imports), banned
