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
