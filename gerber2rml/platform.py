"""Everything this program needs to know about the OS it is running on.

One module, for the same reason ``gui2/theme.py`` is one module: a difference
spelled out at each call site is invisible until it has a name, and one nobody
can find is one nobody can fix. The evidence was already in the tree - "COM5"
appeared eight times in ``gui/app.py``, six as a fallback and twice as a
combo-box seed. Eight places, and eight chances for the next one to be missed.

Every function takes an optional ``platform`` argument defaulting to
``sys.platform``, mirroring :func:`gerber2rml.engine.kicadplugin.config_roots`.
Tests inject ``"win32"`` or ``"linux"`` and so run identically on any host.

stdlib only, and no Qt. This module is imported by ``gui2/app.py`` before
PySide6 is imported - that import is precisely what it exists to survive.
"""
import sys
from dataclasses import dataclass
from pathlib import Path

WINDOWS = "win32"
LINUX = "linux"
MACOS = "darwin"


def _plat(platform=None):
    return sys.platform if platform is None else platform


def _is_windows(platform=None):
    return _plat(platform).startswith("win")


@dataclass(frozen=True)
class Capabilities:
    """What the host OS supports.

    One field for now. It is a dataclass rather than a bare bool so that
    adding a second capability does not change every call site.
    """
    machine_link: bool


def capabilities(platform=None):
    """What this OS supports.

    ``machine_link`` is the Arduino serial link - connect, DRO, jog, bed
    probing, firmware flashing. Windows only, deliberately: the CNC PC is
    Windows, the link has only ever been run there, and shipping an unverified
    motion path to someone standing next to a spinning tool is not a trade
    worth making. Losing it costs less than it looks, because a height map is
    a file: measure the bed once on the CNC PC and carry the CSV.
    """
    return Capabilities(machine_link=_is_windows(platform))


def default_serial_port(platform=None):
    """The port to fall back to when nothing is selected, or None.

    ``None`` off Windows rather than a guess at ``/dev/ttyACM0``: that node may
    be some other board entirely, and probing the wrong port produces a
    timeout that tells the user nothing. ``spi_probe.best_port`` returns None
    for exactly this reason and its docstring explains it. ``COM5`` on Windows
    is a documented lab convention, not a guess.
    """
    return "COM5" if _is_windows(platform) else None


def reveal_command(path, platform=None):
    """Argv that shows ``path`` selected in the file manager, or None.

    None off Windows on purpose. ``xdg-open`` opens a folder but cannot select
    a file inside it, which is exactly what the caller's existing
    ``QDesktopServices`` fallback already does - so there is nothing better to
    return here, and None says so instead of pretending.
    """
    if _is_windows(platform):
        return ["explorer", "/select,", str(Path(path))]
    return None
