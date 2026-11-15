"""The mill's own settings, read and set the way VPanel does it - without VPanel.

A job travels to the SRM-20 as bytes on its printer interface
(:mod:`gerber2rml.engine.rmlspool`). Its settings do not. VPanel reads the
position and changes Setup ▸ Command Set over USB *vendor control transfers*
on endpoint 0, a second channel on the same cable that neither the Windows
spooler nor a CUPS queue carries. Six USBPcap captures of VPanel 1.10
(2026-11-15, the lab mill, docs/vpanel-settings.md) show no bulk packet at
all outside a job. So this module talks to the device directly.

The protocol is a register file. Every exchange is one of four transfers::

    OUT 41 01 <reg lo> <reg hi> 00 00 <len>   data: 01 <reg hi> <reg lo> 00 [value]
    IN  c1 01 01 00 00 00 08 00               -> 82 <busy> <spindle> 01 <working> 00 00 <n>
    IN  c1 01 03 00 00 00 <n>                 -> the n bytes the last request asked for
    IN  c1 01 00 01 00 00 38 00               -> that header plus the 48-byte live block

A request with no value asks for a register; one with a value sets it. The
8-byte header says how many bytes are waiting (its last byte), and VPanel
never reads data without asking the header first. Numbers are little-endian
32-bit, lengths in microns.

The header's fifth byte is the one thing the captures could not teach. It is
``20`` or ``40`` while the mill is still working on the last request, with a
length of zero, and ``00`` once the answer is there - a few milliseconds
later. VPanel was captured through a USB-over-network link that put 70 ms
between any two transfers, so it never once saw the mill unready. Straight
down a cable from a Mac, four requests in five did (the lab mill,
2026-11-15: 128 of 160). Hence :func:`_ready`, which every read and every
write goes through.

What is here is only what the captures prove, each named for the capture it
came from. Reading is harmless and VPanel does it five times a second.
Writing is not: Command Set is shared by everyone who uses the mill, and a
job in the wrong language is refused (engine/runner.py). So nothing in this
module writes unless it is called to, :func:`set_command_set` refuses while
the head moves or the spindle turns, and it reads the setting back before it
says it worked.

Deliberately absent: the registers that move the head (``0262``) and start
the spindle (``3004``). They were seen and are written down in the document,
but motion belongs to the Arduino link and the runner, which have a STOP.

The device is anything with pyusb's ``ctrl_transfer(bmRequestType, bRequest,
wValue, wIndex, data_or_wLength)``, so the tests replay the captures against
a fake and :func:`open_mill` hands back the real one. pyusb and libusb are
imported there and nowhere else: this module loads on a machine with neither.
"""
import struct
import sys
import time
from pathlib import Path

ROLAND_VID = 0x0B75
SRM20_PID = 0x039F

_OUT = 0x41              # host-to-device | vendor | interface
_IN = 0xC1               # device-to-host | vendor | interface
_REQUEST = 0x01
_HEADER = 0x0001         # wValue: the 8-byte status header
_DATA = 0x0003           # wValue: the bytes the last request asked for
_LIVE = 0x0100           # wValue: header + live block, what VPanel polls
_HELLO = 0x0002          # wValue: 01 00 34 12 from an SRM-20

REG_COMMAND_SET = 0x3100         # read: 00 RML-1, 01 NC Code
REG_SET_COMMAND_SET = 0x3101     # write: the same byte
REG_SETUP_REST = 0x3200          # read: the rest of the Setup dialog, 3 bytes
REG_SET_SETUP_REST = 0x3201      # write: VPanel sends it back unchanged
REG_G54 = 0x3203                 # read: G54 X, Y, Z (+ three unused words)
REG_TRAVEL = 0x025B              # read: low corner, high corner of the travel
REG_SPINDLE_RANGE = 0x3003       # read: lowest and highest spindle speed
REG_SET_SPINDLE_PERCENT = 0x3006 # write: VPanel's Spindle slider, percent

# The slider's ends as VPanel sent them: 16 with it pulled all the way down
# (spindel lav.pcapng), 100 at the top. Nothing outside was ever sent, so
# nothing outside is sent from here.
SPINDLE_PERCENT_MIN = 16
SPINDLE_PERCENT_MAX = 100

RML = "rml"
NC = "nc"
_SETS = {0: RML, 1: NC}
SET_NAMES = {RML: "RML-1", NC: "NC Code"}


class SetupError(RuntimeError):
    """The mill could not be reached, or did not do what it was told."""


def _transfer(dev, direction, value, payload):
    try:
        return dev.ctrl_transfer(direction, _REQUEST, value, 0, payload)
    except SetupError:
        raise
    except Exception as e:                      # noqa: BLE001 - usb.core.USBError
        raise SetupError(f"the mill did not answer over USB ({e})") from e


def _header(dev):
    """The 8-byte status header: ``82 busy spindle 01 working 00 00 n``."""
    h = bytes(_transfer(dev, _IN, _HEADER, 8))
    if len(h) != 8 or h[0] != 0x82:
        raise SetupError("the mill answered with something that is not an "
                         f"SRM-20 status header: {h.hex(' ') or 'nothing'}")
    return h


def _ready(dev, wait_s=2.0, sleep=time.sleep, clock=time.monotonic):
    """The header once the mill has finished with the last request.

    Asked again every few milliseconds until its fifth byte is ``00``; the
    longest wait measured was 7 ms for a read and 150 ms for a write. A mill
    that never gets there is reported and left alone - not asked for data it
    has not announced, and not sent anything more.
    """
    deadline = clock() + wait_s
    while True:
        h = _header(dev)
        if h[4] == 0:
            return h
        if clock() >= deadline:
            raise SetupError("the mill took the request but stayed busy; "
                             "nothing more was sent")
        sleep(0.005)


def _request(dev, reg, value=b""):
    # The register goes out twice: little-endian in wValue, big-endian in the
    # data. That is not a guess at redundancy - every one of the 60-odd
    # requests in the captures has both, and they always agree.
    data = bytes([0x01, reg >> 8, reg & 0xFF, 0x00]) + bytes(value)
    _transfer(dev, _OUT, reg, data)


def read_register(dev, reg, **timing):
    """Ask for register ``reg`` and return its bytes.

    Three transfers, in VPanel's order: the request, the header (which says
    how long the answer is, once the mill is ready), the answer. VPanel asks
    for at least three bytes even when one is waiting and the mill sends the
    one; so does this.
    """
    _request(dev, reg)
    n = _ready(dev, **timing)[7]
    if n == 0:
        return b""
    return bytes(_transfer(dev, _IN, _DATA, max(n, 3)))[:n]


def write_register(dev, reg, value, **timing):
    """Set register ``reg`` and wait until the mill has taken it.

    After a write the header's fifth byte reads ``20`` for a moment and then
    ``00`` (command-set-nc-rml-nc.pcapng: 150 ms). VPanel does not send the
    next request until it has cleared, so neither does this; a mill that
    never clears it is reported, not written to again.
    """
    _request(dev, reg, value)
    _ready(dev, **timing)


def is_srm20(dev):
    """True when the device answers the way an SRM-20 does (opstart.pcapng:
    VPanel asks this first, before the device id string)."""
    try:
        return bytes(_transfer(dev, _IN, _HELLO, 4)) == b"\x01\x00\x34\x12"
    except SetupError:
        return False


def _words(data, count):
    if len(data) < 4 * count:
        raise SetupError(f"the mill sent {len(data)} bytes where "
                         f"{4 * count} were expected")
    return struct.unpack_from(f"<{count}i", data)


def status(dev):
    """What VPanel shows, from one poll (tomgang.pcapng, jog.pcapng).

    ``x_mm``/``y_mm``/``z_mm`` are machine coordinates. ``busy`` is the
    header's second byte: 09 during every jog, 01 for the four seconds a
    spindle took to run up and again while it ran down, 00 at rest. Its bits
    are not mapped, so it is reported as true or false. ``spindle_on`` is the
    third byte, 01 from the start command to the stop.

    ``spindle_reading`` is the mill's own measurement and is NOT rpm as
    VPanel words it: it settled near 4300 with the slider at 16 % and was
    past 6400 and still climbing at 100 %, where upstream's SPI audit read
    8600 on a spindle rated 7000 (docs/archive/2026-08-21-spi-command-audit.md).
    Good for "is it turning, and faster or slower than before".
    """
    b = bytes(_transfer(dev, _IN, _LIVE, 56))
    if len(b) != 56 or b[0] != 0x82:
        raise SetupError("the mill's status could not be read")
    x, y, z = _words(b[8:20], 3)
    return {"x_mm": x / 1000.0, "y_mm": y / 1000.0, "z_mm": z / 1000.0,
            "busy": b[1] != 0, "spindle_on": b[2] != 0,
            "spindle_reading": struct.unpack_from("<I", b, 32)[0],
            "speed_percent": b[38], "spindle_percent": b[40]}


def command_set(dev):
    """``"nc"`` or ``"rml"``: the language the mill reads a job in.

    The byte VPanel shows in Setup ▸ Command Set. It read 01 with NC Code
    selected, 00 after RML-1 was chosen, 01 again after NC Code
    (command-set-nc-rml-nc.pcapng).
    """
    b = read_register(dev, REG_COMMAND_SET)
    if len(b) != 1 or b[0] not in _SETS:
        raise SetupError("the mill's command set could not be read "
                         f"(it sent {b.hex(' ') or 'nothing'})")
    return _SETS[b[0]]


def set_command_set(dev, nc=True, **timing):
    """Set Setup ▸ Command Set, as VPanel's OK button does. Returns the
    setting read back.

    The mill must be standing still with the spindle off: VPanel stops the
    spindle itself before it opens the dialog, and changing the language
    under a running job is not something to find out about at the machine.

    VPanel follows the command-set write with register ``3201`` carrying the
    three bytes it read from ``3200`` when the dialog opened - the dialog's
    other settings, saved together by its one OK button. What those bytes
    mean is not known. They are sent back exactly as read, because that is
    the only sequence proven to work, and it changes nothing.
    """
    st = status(dev)
    if st["busy"] or st["spindle_on"]:
        raise SetupError("the mill is moving or its spindle is on - wait "
                         "until it stands still before changing the command "
                         "set")
    want = NC if nc else RML
    if command_set(dev) == want:
        return want
    rest = read_register(dev, REG_SETUP_REST, **timing)
    write_register(dev, REG_SET_COMMAND_SET, [1 if nc else 0], **timing)
    if rest:
        write_register(dev, REG_SET_SETUP_REST, rest, **timing)
    got = command_set(dev)
    if got != want:
        raise SetupError(f"the mill still reads {SET_NAMES[got]} after being "
                         f"set to {SET_NAMES[want]}")
    return got


def g54_origin(dev):
    """The G54 work origin, ``(x_mm, y_mm, z_mm)`` in machine coordinates.

    VPanel asks for this three times a second while its display is set to
    G54 and never otherwise (machine to g54 to machine.pcapng), and it read
    0, 0, -55.64 on a mill whose automatic runs pass the G54 check. It is
    read-only here: the automatic run needs to know where G54 is, not to
    move it (engine/autorun.py, ``_check_frame``).
    """
    x, y, z = _words(read_register(dev, REG_G54), 3)
    return (x / 1000.0, y / 1000.0, z / 1000.0)


def travel(dev):
    """The machine's travel, ``((x0, y0, z0), (x1, y1, z1))`` in mm. On the
    SRM-20: (0, 0, -60.5) to (203.2, 152.4, 0) (opstart.pcapng)."""
    w = _words(read_register(dev, REG_TRAVEL), 9)
    return (tuple(v / 1000.0 for v in w[0:3]),
            tuple(v / 1000.0 for v in w[6:9]))


def spindle_range(dev):
    """``(lowest, highest)`` spindle speed the mill reports: 2000 and 7000
    (opstart.pcapng). VPanel does not use it to set a speed: both spindle
    starts in the captures carried 7000, one with the slider at the top and
    one with it at the bottom."""
    lo, hi = _words(read_register(dev, REG_SPINDLE_RANGE), 2)
    return (lo, hi)


def set_spindle_percent(dev, percent, **timing):
    """Set the spindle speed the way VPanel's Spindle slider does. Returns
    the percentage the mill then reports.

    This is the setting the Arduino link cannot reach: over SPI the spindle
    only turns on and off, at "whatever VPanel's slider was last set to"
    (the SPI audit, section 6d). The slider is this register. Dragging it
    sent 95, 83 and 60 and the poll echoed each one (speed1.pcapng); with it
    at 16 the running spindle read about 4300 where 100 read over 6400
    (spindel lav.pcapng, Spindle on, speed high + 100%.pcapng).

    It is a percentage, not rpm, and what speed each step gives has not been
    measured with a tachometer. It may be changed while the spindle turns -
    that is what a slider is for - and it takes effect on the mill at once.
    """
    p = int(percent)
    if not SPINDLE_PERCENT_MIN <= p <= SPINDLE_PERCENT_MAX:
        raise SetupError(f"spindle speed must be {SPINDLE_PERCENT_MIN} to "
                         f"{SPINDLE_PERCENT_MAX} percent, not {percent}")
    write_register(dev, REG_SET_SPINDLE_PERCENT, [p], **timing)
    # The first poll after the write still carried the old value in the
    # capture, the second the new one (200 ms apart). So it is asked a few
    # times before the mill is said not to have taken it.
    sleep = timing.get("sleep", time.sleep)
    for _ in range(8):
        got = status(dev)["spindle_percent"]
        if got == p:
            return got
        sleep(0.15)
    raise SetupError(f"the mill reports {got} % after being set to {p} %")


# --- the real device --------------------------------------------------------

USB_HINT = (
    "Reading the mill's settings needs direct USB access: the pyusb package "
    "and libusb. From source, `pip install pyusb` and `brew install libusb`; "
    "the packaged app carries both. See docs/vpanel-settings.md.")


def _libusb_backend():
    """pyusb's libusb backend, looking where a packaged app keeps the library.

    pyusb finds libusb through ``ctypes.util.find_library``, which searches
    neither a PyInstaller bundle nor Homebrew's prefix on Apple silicon. So
    the places it can be are tried by name first, and pyusb's own search is
    the fallback.
    """
    import usb.backend.libusb1 as libusb1
    names = ("libusb-1.0.0.dylib", "libusb-1.0.dylib", "libusb-1.0.so.0",
             "libusb-1.0.dll")
    roots = [Path(getattr(sys, "_MEIPASS", "")), Path("/opt/homebrew/lib"),
             Path("/usr/local/lib")]
    for root in roots:
        for name in names:
            lib = root / name
            if str(root) and lib.is_file():
                be = libusb1.get_backend(find_library=lambda _n, p=str(lib): p)
                if be is not None:
                    return be
    return libusb1.get_backend()


def open_mill():
    """The SRM-20 as a pyusb device, ready for the functions above.

    The device is not configured, claimed or detached from the system's
    printer driver: control transfers on endpoint 0 need none of that, and
    taking the printer interface away would break the queue the jobs go
    through. That VPanel's own polling and a print job coexist on Windows is
    the same arrangement.

    Windows is not served: the Roland driver owns the device there and
    libusb cannot open it. VPanel runs on Windows, so nothing is lost.
    """
    try:
        import usb.core
    except ImportError as e:
        raise SetupError("pyusb is not installed. " + USB_HINT) from e
    backend = _libusb_backend()
    if backend is None:
        raise SetupError("libusb was not found. " + USB_HINT)
    try:
        dev = usb.core.find(idVendor=ROLAND_VID, idProduct=SRM20_PID,
                            backend=backend)
    except Exception as e:                      # noqa: BLE001 - USBError
        raise SetupError(f"USB could not be searched ({e})") from e
    if dev is None:
        raise SetupError("no SRM-20 on USB - is the mill switched on and its "
                         "cable plugged into this computer?")
    if not is_srm20(dev):
        raise SetupError("the mill is on USB but does not answer its "
                         "settings channel. Another program may hold it, or "
                         "this system does not let SRM-CAM talk to it.")
    return dev
