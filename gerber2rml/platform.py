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
import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

WINDOWS = "win32"
LINUX = "linux"
MACOS = "darwin"


def _plat(platform=None):
    return sys.platform if platform is None else platform


def _is_windows(platform=None):
    return _plat(platform).startswith("win")


def _is_macos(platform=None):
    return _plat(platform) == MACOS


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
    probing, firmware flashing - and sending jobs to the mill. All three
    systems. Windows because the CNC PC is Windows and the link was built
    there. macOS because a lab runs its SRM-20 from a Mac, through a raw CUPS
    queue. Linux since 2026-11-19, proven on the lab mill: pyserial is the same
    code everywhere, and the mill's USB is a plain printer-class device, which
    the kernel's ``usblp`` driver makes ``/dev/usb/lp0`` - the same port the
    Windows spooler writes to as ``USB001`` (``engine/rmlspool.py``).
    """
    return Capabilities(machine_link=True)


def _is_linux(platform=None):
    return _plat(platform).startswith("linux")


# --- Linux: who may open the mill's USB and the Arduino -------------------
#
# Both are root-owned nodes with group access (lp and uucp on Arch, lp and
# dialout on Debian). A udev rule tagging them ``uaccess`` hands them to
# whoever is logged in at the screen, at the next plug-in, with no group to
# join and no logging out. It has to sort before systemd's 73-seat-late.rules,
# hence the 60.
ROLAND_USB_VID = "0b75"
SRM20_USB_PID = "039f"
UDEV_RULES_PATH = "/etc/udev/rules.d/60-srm-cam.rules"
# Arduino (2341, 2a03), CH340 (the lab's Uno), FTDI, CP210x - spi_probe's
# BOARD_VIDS, as udev spells them.
_SERIAL_MATCHES = (("2341", None), ("2a03", None), ("1a86", "7523"),
                   ("0403", "6001"), ("10c4", "ea60"))
# ID_MM_DEVICE_IGNORE keeps ModemManager off the Arduino: it probes new serial
# ports with AT commands, and on this link every letter is a command to a
# board that can move a spindle.
UDEV_RULES = (
    "# SRM-CAM: the Arduino on the SRM-20's SPI header, and the mill's own USB\n"
    "# (the printer node jobs go to, and the settings channel).\n"
    "# Written by Machine > Set up USB access, or by\n"
    "#   python -m gerber2rml.doctor --setup-mill\n"
    + "".join(
        'SUBSYSTEM=="tty", ATTRS{idVendor}=="%s", %sTAG+="uaccess", '
        'ENV{ID_MM_DEVICE_IGNORE}="1", ENV{ID_MM_PORT_IGNORE}="1"\n'
        % (vid, 'ATTRS{idProduct}=="%s", ' % pid if pid else "")
        for vid, pid in _SERIAL_MATCHES)
    + 'SUBSYSTEM=="usbmisc", KERNEL=="lp[0-9]*", ATTRS{idVendor}=="%s", '
      'TAG+="uaccess"\n' % ROLAND_USB_VID
    + 'SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="%s", '
      'ATTR{idProduct}=="%s", TAG+="uaccess"\n'
      % (ROLAND_USB_VID, SRM20_USB_PID))


def udev_rules(platform=None):
    """The udev rules this app wants, or None where there is no udev."""
    return UDEV_RULES if _is_linux(platform) else None


def udev_install_script(rules_file):
    """Shell that installs ``rules_file`` and applies it to what is plugged in.

    One string, for ``pkexec sh -c``, so the password is asked once. The
    trigger re-runs the rules on the devices already there, so nothing has to
    be unplugged.
    """
    import shlex
    return ("install -m 0644 %s %s && udevadm control --reload && "
            "udevadm trigger --action=change --subsystem-match=tty "
            "--subsystem-match=usbmisc --subsystem-match=usb && "
            "udevadm settle"
            % (shlex.quote(str(rules_file)), UDEV_RULES_PATH))


def udev_rules_installed(path=UDEV_RULES_PATH):
    """Whether the rule file is there with this version's contents."""
    try:
        return Path(path).read_text(encoding="utf-8") == UDEV_RULES
    except OSError:
        return False


def phantom_serial_port(device, hwid, platform=None):
    """Whether a listed serial port is one that is never really there.

    Linux lists every 8250 UART slot the kernel reserved - ``/dev/ttyS0`` to
    ``ttyS31`` - with an hwid of ``n/a``, whether or not a chip sits behind
    it. Thirty-two dead entries above the one Arduino is how a beginner picks
    the wrong port. A real onboard UART has an hwid other than ``n/a``.
    """
    return (_is_linux(platform) and (hwid or "n/a") == "n/a"
            and os.path.basename(device).startswith("ttyS"))


# What to put on screen where the machine controls would have been.
#
# One string, in this module, because BOTH interfaces have to say it and two
# copies of a safety explanation drift apart - one gets a correction the other
# never sees, and the student who reads the wrong one is standing at a mill.
# It names the platform, says which control is missing, and points at the path
# that still works, because "probe once on the CNC PC and carry the CSV" is the
# whole Linux levelling workflow and nobody would guess it.
NO_MACHINE_LINK_NOTE = (
    "The machine link is not available here, so there is no "
    "Connect. Prepare the job, export, and send the files "
    "from VPanel on a Windows PC — or load a height map "
    "measured there to export levelled toolpaths.")


def qt_style(platform=None):
    """The Qt widget style to build the stylesheet on, or None for Qt's own.

    "Fusion" on macOS: the native macOS style places check-box indicators
    where its own drawing expects them, so the stylesheet's 15 px box comes
    out clipped at the bottom. Fusion honours the stylesheet's geometry, as
    the Windows style does. Elsewhere the default is left alone.
    """
    return "Fusion" if _is_macos(platform) else None


def handoff_address(platform=None, uid=None, tmp=None):
    """Where a running SRM-CAM listens for "open this board".

    The KiCad plugin and a second launch both send a path here, so a board
    opens in the window that is already up instead of a second copy. A named
    pipe on Windows; elsewhere a socket file in the per-user temp folder,
    named by user id so two accounts on one PC never reach each other.
    """
    if _is_windows(platform):
        import getpass
        try:
            user = getpass.getuser()
        except Exception:                       # noqa: BLE001 - no name
            user = "user"
        return f"SRM-CAM-{user}"
    import tempfile
    uid = os.getuid() if uid is None else uid
    tmp = tempfile.gettempdir() if tmp is None else tmp
    return str(PurePosixPath(tmp) / f"srm-cam-{uid}.sock")


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
    if _is_windows(platform) or _is_macos(platform):
        # macOS: /dev/cu.* nodes are world read-write and there is no
        # usermod; a refused port there means another program holds it.
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
            f"Use Machine ▸ Set up USB access… (once, asks for your password), "
            f"or run  sudo usermod -aG {group} $USER  and log out and back in.")


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


_IDE_TAIL = ("resources", "app", "lib", "backend", "resources")


def arduino_cli_candidates(platform=None, env=None, home=None):
    """Where a bundled ``arduino-cli`` might live, most likely first.

    The Arduino IDE ships one inside its own resources; using it means no
    separate toolchain install and the same core versions the IDE would have
    used. Callers fall back to ``shutil.which`` when none of these exist.

    The Linux and macOS branches build with ``PurePosixPath`` rather than the
    bare ``Path`` this module uses everywhere else. ``Path`` always resolves
    to the class of the REAL host, so injecting ``"linux"`` while actually
    running on the Windows dev machine would silently render backslashes
    instead of the forward slashes a Linux path needs - a test simulating a
    different OS is not asking for a usable path, only a correctly-shaped
    one. Only when the requested platform actually matches ``sys.platform``
    - a real lookup, not a simulated one - is the result upgraded to a real
    ``Path`` so ``.is_file()`` works.
    """
    import os
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    if _is_windows(platform):
        local = env.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
        return [base.joinpath("Programs", "Arduino IDE", *_IDE_TAIL,
                               "arduino-cli.exe")]
    if _plat(platform) == MACOS:
        found = [PurePosixPath("/Applications/Arduino IDE.app/Contents",
                                *_IDE_TAIL, "arduino-cli")]
    else:
        found = [
            PurePosixPath("/opt/arduino-ide", *_IDE_TAIL, "arduino-cli"),
            PurePosixPath("/usr/lib/arduino-ide", *_IDE_TAIL, "arduino-cli"),
            PurePosixPath(home.as_posix(), ".local", "share", "arduino-ide",
                           *_IDE_TAIL, "arduino-cli"),
        ]
    live = _plat(platform) == sys.platform
    return [Path(p) for p in found] if live else found


def arduino_library_dir(platform=None, home=None):
    """Where the Arduino IDE looks for user libraries.

    ``Documents/Arduino/libraries`` on Windows; plain ``~/Arduino/libraries``
    on Linux, where the IDE does not put its sketchbook under Documents.
    """
    home = Path.home() if home is None else Path(home)
    if _is_windows(platform):
        return home / "Documents" / "Arduino" / "libraries"
    return home / "Arduino" / "libraries"
