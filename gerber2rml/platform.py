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
from pathlib import Path, PurePosixPath

WINDOWS = "win32"
LINUX = "linux"
MACOS = "darwin"


def _plat(platform=None):
    return sys.platform if platform is None else platform


def _is_windows(platform=None):
    return _plat(platform).startswith("win")


# How a job reaches the mill, in the order to try them. See engine/rmlspool.py.
JOB_SPOOLER = "spooler"      # Windows: the driver's RAW printer on USB001
JOB_USBLP = "usblp"          # Linux: the kernel's printer node, /dev/usb/lpN
JOB_CUPS = "cups"            # a raw CUPS queue: macOS, and Linux without usblp


@dataclass(frozen=True)
class Capabilities:
    """What the host OS supports.

    It is a dataclass rather than a bare bool so that adding a capability does
    not change every call site. Everything past ``machine_link`` has the value
    the CNC PC has as its default, so a caller that only cares about the link
    keeps meaning what it says.

    ``job_routes`` is how a job gets to the mill here; ``vpanel`` is whether
    Roland's VPanel exists on this OS at all, which decides what the app can
    tell someone to do by hand; ``link_proven`` is whether the link has been
    run against a real SRM-20 on this OS. That last one is a fact about what
    has been tested, not about what the code can do: flip it for a platform
    when someone has worked through docs/usage.md's checklist on the machine.
    """
    machine_link: bool
    job_routes: tuple = (JOB_SPOOLER,)
    vpanel: bool = True
    link_proven: bool = True


def _is_linux(platform=None):
    return _plat(platform).startswith(LINUX)


def capabilities(platform=None):
    """What this OS supports.

    ``machine_link`` is the Arduino serial link - connect, DRO, jog, bed
    probing, firmware flashing. It is pyserial on a USB-serial chip everywhere,
    so it runs wherever pyserial does; anything else falls back to the
    simulator rather than a guess.

    The serial side is the same on every OS. What differs is the job: Windows
    has Roland's driver and its spooler, Linux and macOS have neither. On both,
    the mill's USB port is reached as the plain USB printer that driver sits on
    (see engine/rmlspool.py). VPanel does not exist there at all, so the spindle
    speed and the command set can only be changed from a Windows PC: the
    SRM-20's manual says of the first, in as many words, "cannot be specified
    from any application other than VPanel".
    """
    if _is_windows(platform):
        return Capabilities(machine_link=True)
    if _is_linux(platform):
        return Capabilities(machine_link=True,
                            job_routes=(JOB_USBLP, JOB_CUPS),
                            vpanel=False, link_proven=False)
    if _plat(platform) == MACOS:
        return Capabilities(machine_link=True, job_routes=(JOB_CUPS,),
                            vpanel=False, link_proven=False)
    return Capabilities(machine_link=False, job_routes=(), vpanel=False,
                        link_proven=False)


# What to put on screen where the machine controls would have been.
#
# One string, in this module, because BOTH interfaces have to say it and two
# copies of a safety explanation drift apart - one gets a correction the other
# never sees, and the student who reads the wrong one is standing at a mill.
# It names the platform, says which control is missing, and points at the path
# that still works, because "probe once on the CNC PC and carry the CSV" is the
# whole levelling workflow on a system with no link, and nobody would guess it.
NO_MACHINE_LINK_NOTE = (
    "The machine link runs on Windows, Linux and macOS, not on this system, "
    "so there is no Connect here. Prepare the job, export, and send the files "
    "from VPanel on the CNC PC — or load a height map measured there to "
    "export levelled toolpaths.")

# Said once per connection until a platform's ``link_proven`` is true. Not a
# dialog: it is true every time and a modal would be clicked through by the
# second day. It goes in the log and the toast, where the rest of the link's
# sentences go.
UNPROVEN_LINK_NOTE = (
    "This link has not yet been run on a real SRM-20 on this operating "
    "system. Run Machine test with the bit clear of the work first, and keep "
    "your hand near the machine's own power switch.")


def how_to_send_files(platform=None):
    """The end of "export the files and ...", for what this host has."""
    if capabilities(platform).vpanel:
        return "send them from VPanel"
    return "run each step with Machine ▸ Run this step on the mill"


def mill_refused_job_note(platform=None):
    """What a job the mill refuses means here: its command set is wrong."""
    if capabilities(platform).vpanel:
        return ("the mill refused the job. In VPanel, Setup ▸ Command Set "
                "must be NC Code; press Cancel there to clear it")
    return ("the mill refused the job, which is what it does when its command "
            "set is not NC Code. That setting is only in VPanel: set Setup ▸ "
            "Command Set to NC Code once on a Windows PC")


def g54_moved_note(platform=None):
    """Where to put G54 back: the job's XY rests on it being machine 0, 0."""
    if capabilities(platform).vpanel:
        return ("in VPanel, set G54 X/Y back to machine 0, 0 (only Z is ever "
                "zeroed)")
    return ("only VPanel can set that: set G54 X/Y back to machine 0, 0 once "
            "on a Windows PC (only Z is ever zeroed)")


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

    None on Linux on purpose. ``xdg-open`` opens a folder but cannot select a
    file inside it, which is exactly what the caller's existing
    ``QDesktopServices`` fallback already does - so there is nothing better to
    return here, and None says so instead of pretending.
    """
    if _is_windows(platform):
        return ["explorer", "/select,", str(Path(path))]
    if _plat(platform) == MACOS:
        return ["open", "-R", str(path)]
    return None


def serial_open_options(platform=None):
    """Extra arguments for ``serial.Serial``.

    Windows gives a COM port to one program at a time; POSIX does not, and two
    programs on one port would each read half of the other's replies while
    both drive the mill. So off Windows the port asks for the exclusivity
    Windows gives it for nothing. This is what makes a second copy of the app,
    or a stray terminal, fail at Connect instead of mid-move.
    """
    return {} if _is_windows(platform) else {"exclusive": True}


def serial_port_can_be_a_board(device, platform=None):
    """Whether a port pyserial lists could be the Arduino at all.

    Off Windows the list is full of ports that cannot be. On Linux every
    motherboard UART is there, ``/dev/ttyS0`` to ``ttyS31`` whether or not
    anything is behind it: pyserial 3.5 hides them by their sysfs subsystem being
    ``platform``, and on a current kernel it reads ``serial-base`` instead. Seen
    on an Arch machine with nothing plugged in: 32 of them, and Connect lit. A
    Mac lists its Bluetooth and debug ports. An Arduino is on USB, so none of
    these is one.

    Windows keeps its whole list: rank_ports puts the likely board first there,
    and this is about ports that exist only on paper.
    """
    name = str(device)
    if _is_linux(platform):
        return not name.startswith("/dev/ttyS")
    if _plat(platform) == MACOS:
        return not ("Bluetooth" in name or "debug-console" in name)
    return True


def serial_flush_can_hang(platform=None):
    """Whether pyserial's ``flush()`` can block for good.

    On POSIX it is ``tcdrain``, which has no timeout: on a wedged USB-serial
    port it waits for ever, and STOP calls it from the GUI thread. On Windows
    ``flush()`` is a polling loop on the driver's queue.
    """
    return not _is_windows(platform)


def serial_permission_hint(device, platform=None, stat_fn=None, group_fn=None):
    """What to tell someone whose serial port refused to open, or None.

    On a fresh Fedora or Ubuntu account, opening ``/dev/ttyACM0`` fails with
    PermissionError because the node is root-owned with group access and the
    user is not in that group. It is invisible on Windows, and it is the most
    likely "the Linux version doesn't work" report this project will get.

    The group is read off the DEVICE rather than hardcoded. Fedora and Ubuntu
    both use ``dialout`` today, but Arch uses ``uucp``, and telling someone to
    join a group that is not the one guarding the node is advice that fails
    silently. The same goes for the mill's own node, ``/dev/usb/lp0``, whose
    group is ``lp``.

    macOS has no ``usermod`` and its serial nodes are open to everyone, so
    there is no advice to give there.

    ``stat_fn`` and ``group_fn`` are injectable so the test does not need a
    real device with a real group.

    ``grp`` is POSIX-only stdlib - importing it at module scope would break the
    Windows build, so it is imported inside the branch.
    """
    if _is_windows(platform) or _plat(platform) == MACOS:
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
            f"Use Machine ▸ Set up USB access, or run  sudo usermod -aG "
            f"{group} $USER  then log out and back in for the change to take "
            f"effect.")


# Roland DG's USB vendor id (usb.ids), and the USB-serial chips of
# spi_probe.BOARD_VIDS, as udev spells them.
ROLAND_USB_VID = "0b75"
UDEV_RULES_PATH = "/etc/udev/rules.d/60-srm-cam.rules"
# ``uaccess`` hands the node to whoever is logged in at the screen, so it works
# at the next plug-in with no group to join and no logging out. It has to run
# before systemd's 73-seat-late.rules, which is why the file is numbered 60.
#
# ID_MM_DEVICE_IGNORE keeps ModemManager off the Arduino. It probes new serial
# ports by sending them AT commands, and on this link every letter is a command
# to a board that can move a spindle.
_SERIAL_MATCHES = (("2341", None), ("2a03", None), ("1a86", "7523"),
                   ("0403", "6001"), ("10c4", "ea60"))
UDEV_RULES = (
    "# SRM-CAM: the Arduino on the SRM-20's SPI header, and the mill's own USB\n"
    "# port. Written by Machine > Set up USB access, or by:\n"
    "#   SRM-CAM --udev-rule | sudo tee " + UDEV_RULES_PATH + "\n"
    + "".join(
        'SUBSYSTEM=="tty", ATTRS{idVendor}=="%s", %sTAG+="uaccess", '
        'ENV{ID_MM_DEVICE_IGNORE}="1", ENV{ID_MM_PORT_IGNORE}="1"\n'
        % (vid, 'ATTRS{idProduct}=="%s", ' % pid if pid else "")
        for vid, pid in _SERIAL_MATCHES)
    + 'SUBSYSTEM=="usbmisc", KERNEL=="lp[0-9]*", ATTRS{idVendor}=="'
    + ROLAND_USB_VID + '", TAG+="uaccess"\n')


def udev_rules(platform=None):
    """The udev rules this app wants, or None where udev does not exist."""
    return UDEV_RULES if _is_linux(platform) else None


def udev_install_script(rules_file):
    """Shell that installs ``rules_file`` and applies it to what is plugged in.

    One string, for ``pkexec sh -c``: the password is asked once, for the
    whole of it. A shell quote around the path, because a temp dir can have
    anything in it.
    """
    import shlex
    return ("install -m 0644 %s %s && udevadm control --reload && udevadm "
            "trigger --subsystem-match=tty --subsystem-match=usbmisc"
            % (shlex.quote(str(rules_file)), UDEV_RULES_PATH))


def udev_terminal_commands(program="SRM-CAM"):
    """The same, for pasting into a terminal."""
    return ("%s --udev-rule | sudo tee %s >/dev/null && sudo udevadm control "
            "--reload && sudo udevadm trigger --subsystem-match=tty "
            "--subsystem-match=usbmisc" % (program, UDEV_RULES_PATH))


def _usb_ids(sys_root):
    """``{vendor id}`` of everything on the USB bus, from sysfs. No device is
    opened; an unreadable tree is an empty set."""
    found = set()
    try:
        for d in Path(sys_root).iterdir():
            try:
                found.add((d / "idVendor").read_text(
                    encoding="ascii").strip().lower())
            except OSError:
                continue
    except OSError:
        pass
    return found


USB_SYS_ROOT = "/sys/bus/usb/devices"


def no_serial_ports_hint(platform=None, sys_root=USB_SYS_ROOT):
    """Why a USB-serial chip that is plugged in has no port, or "".

    A CH340 with no ``/dev/ttyUSB`` node is nearly always brltty: on Ubuntu the
    braille daemon claims that chip's id for a display that shares it, and the
    port appears and vanishes in the same second. The lab's Uno is a CH340.
    """
    if not _is_linux(platform):
        return ""
    if "1a86" not in _usb_ids(sys_root):
        return ""
    return (" A CH340 is plugged in but has no port: on Ubuntu that is usually "
            "brltty taking it. Run  sudo apt remove brltty  and plug it in "
            "again.")


def mill_on_usb(platform=None, sys_root=USB_SYS_ROOT):
    """Whether Roland hardware is on the USB bus, read from sysfs (Linux)."""
    return _is_linux(platform) and ROLAND_USB_VID in _usb_ids(sys_root)


def host_env(env=None):
    """The environment for running one of the SYSTEM's own programs.

    A frozen app starts with ``LD_LIBRARY_PATH`` pointing into its own bundle,
    so a system tool started from it loads the bundle's libraries instead of
    its own and dies on a symbol mismatch. PyInstaller keeps the original under
    ``*_ORIG``; running from source there is nothing to undo.
    """
    import os
    env = dict(os.environ if env is None else env)
    if getattr(sys, "frozen", False):
        for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            orig = env.pop(var + "_ORIG", None)
            if orig is None:
                env.pop(var, None)
            else:
                env[var] = orig
    env["LC_ALL"] = "C"          # lp and lpstat are parsed; keep them English
    return env


def process_list_command(platform=None):
    """Argv that lists the running programs, one per line."""
    return (["tasklist"] if _is_windows(platform)
            else ["ps", "-A", "-o", "comm="])


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

    ``Documents/Arduino/libraries`` on Windows and macOS; plain
    ``~/Arduino/libraries`` on Linux, where the IDE does not put its sketchbook
    under Documents.
    """
    home = Path.home() if home is None else Path(home)
    if _is_windows(platform) or _plat(platform) == MACOS:
        return home / "Documents" / "Arduino" / "libraries"
    return home / "Arduino" / "libraries"
