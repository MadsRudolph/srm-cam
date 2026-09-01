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


def serial_permission_hint(device, platform=None, stat_fn=None, group_fn=None):
    """What to tell someone whose serial port refused to open, or None.

    On a fresh Fedora or Ubuntu account, opening ``/dev/ttyACM0`` fails with
    PermissionError because the node is root-owned with group access and the
    user is not in that group. It is invisible on Windows, and it is the most
    likely "the Linux version doesn't work" report this project will get.

    The group is read off the DEVICE rather than hardcoded. Fedora and Ubuntu
    both use ``dialout`` today, but Arch uses ``uucp``, and telling someone to
    join a group that is not the one guarding the node is advice that fails
    silently.

    ``stat_fn`` and ``group_fn`` are injectable so the test does not need a
    real device with a real group.

    ``grp`` is POSIX-only stdlib - importing it at module scope would break the
    Windows build, so it is imported inside the branch.
    """
    if _is_windows(platform):
        return None
    import os
    stat_fn = os.stat if stat_fn is None else stat_fn
    if group_fn is None:
        try:
            import grp
            def group_fn(gid):
                return grp.getgrgid(gid).gr_name
        except ModuleNotFoundError:
            # grp is POSIX-only; on Windows this can't happen in production
            # but tests run on both platforms with injected platform strings
            return None
    try:
        group = group_fn(stat_fn(device).st_gid)
    except Exception:
        # Unplugged between the failure and the hint, or a group with no name.
        # No hint is better than a wrong one.
        return None
    return (f"{device} is owned by the '{group}' group and you are not in it. "
            f"Run  sudo usermod -aG {group} $USER  then log out and back in "
            f"for the change to take effect.")


def documents_dir(home=None, platform=None):
    """The user's documents folder, without asking Qt.

    ``gui2/app.py`` needs this before PySide6 is imported - catching a
    traceback from that very import is why it opens a log first - so it cannot
    use ``QStandardPaths``. But ``workspace_root()`` DOES use QStandardPaths,
    which on Linux reads ``XDG_DOCUMENTS_DIR`` from
    ``~/.config/user-dirs.dirs``. On a Danish desktop that is ``~/Dokumenter``,
    and the two would otherwise disagree: the workspace under Dokumenter and
    the startup log under ~/SRM-CAM. The log is exactly what someone goes
    looking for when the app will not start, so it has to be where they expect.

    Reads the same file Qt reads. Falls back to ``~/Documents``, then to the
    home directory itself, which is the behaviour this replaces.
    """
    home = Path.home() if home is None else Path(home)
    if not _is_windows(platform):
        cfg = home / ".config" / "user-dirs.dirs"
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line.startswith("XDG_DOCUMENTS_DIR"):
                    continue
                _, _, value = line.partition("=")
                value = value.strip().strip('"')
                if value.startswith("$HOME/"):
                    found = home / value[len("$HOME/"):]
                elif value.startswith("/"):
                    found = Path(value)
                else:
                    continue
                if found.is_dir():
                    return found
        except OSError:
            pass
    docs = home / "Documents"
    return docs if docs.is_dir() else home
