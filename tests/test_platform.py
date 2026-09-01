"""Platform differences have one home, and these tests keep them there.

Every assertion injects a platform string rather than reading the host's, so
the Linux behaviour is tested on Windows and vice versa. A test that only
passes on the machine it was written on proves nothing about the other one.
"""
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
