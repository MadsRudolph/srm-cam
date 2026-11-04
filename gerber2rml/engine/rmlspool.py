"""Send a job straight to the SRM-20, the way VPanel does it - without VPanel.

VPanel is a front end. Its ``SRM20ControlAPI.dll`` imports the Windows
spooler (``OpenPrinterA``/``StartDocPrinterA``/``WritePrinter``) and the
driver installs the mill as an ordinary printer, "Roland SRM-20" on
``USB001``. A job is RML bytes written RAW to that printer. Everything here
is ctypes over ``winspool.drv``: no new dependency, nothing to install.

What this does NOT do is know the origin. RML moves are relative to the
machine's work origin; the autonomous run sets that over the Arduino link
(firmware ``O``/``W``) before it sends anything. See
docs/archive/2026-08-21-spi-command-audit.md and the experiments in
scripts/autorun_lab.py for what is proven on the machine and what is not.

A printer is anything with ``send(data, name)``, ``pending()`` and
``purge()``; :class:`SpoolPrinter` is the real one on Windows and the simulator
(:mod:`gerber2rml.engine.simmachine`) supplies a fake.

Off Windows there is no Roland driver, but the driver was never what talks to
the mill: ``USB001`` is the Windows port monitor for the USB printer class, so
the spooler is handing those RAW bytes to a class-compliant USB printer. Linux
has its own driver for that class, ``usblp``, which makes the same port
``/dev/usb/lp0`` (:class:`UsbLpPrinter`); macOS has none, but CUPS will drive any
USB printer through a raw queue (:class:`CupsPrinter`), and so will Linux when
``usblp`` has been kept off the device. :func:`find_printer` picks by what
:func:`gerber2rml.platform.capabilities` says this host has.

That argument is an inference from the Windows side: no published account of
it was found, and it has not been tried on a real SRM-20 yet. docs/usage.md has
the bench checklist, whose first step shows the mill's USB class on the bus.
"""
import ctypes
import errno
import os
import re
import select
import subprocess
import threading
from collections import deque
from ctypes import wintypes
from pathlib import Path

from gerber2rml import platform as plat
from gerber2rml.platform import _is_windows

WINDOWS = _is_windows()

PRINTER_ENUM_LOCAL = 0x2
PRINTER_ENUM_CONNECTIONS = 0x4
JOB_CONTROL_DELETE = 5
PRINTER_CONTROL_PURGE = 3


class SpoolError(RuntimeError):
    pass


if WINDOWS:
    _ws = ctypes.WinDLL("winspool.drv", use_last_error=True)

    class DOC_INFO_1W(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR),
                    ("pOutputFile", wintypes.LPWSTR),
                    ("pDatatype", wintypes.LPWSTR)]

    class PRINTER_INFO_4W(ctypes.Structure):
        _fields_ = [("pPrinterName", wintypes.LPWSTR),
                    ("pServerName", wintypes.LPWSTR),
                    ("Attributes", wintypes.DWORD)]

    class SYSTEMTIME(ctypes.Structure):
        _fields_ = [(n, wintypes.WORD) for n in
                    ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour",
                     "wMinute", "wSecond", "wMilliseconds")]

    class JOB_INFO_1W(ctypes.Structure):
        _fields_ = [("JobId", wintypes.DWORD),
                    ("pPrinterName", wintypes.LPWSTR),
                    ("pMachineName", wintypes.LPWSTR),
                    ("pUserName", wintypes.LPWSTR),
                    ("pDocument", wintypes.LPWSTR),
                    ("pDatatype", wintypes.LPWSTR),
                    ("pStatus", wintypes.LPWSTR),
                    ("Status", wintypes.DWORD),
                    ("Priority", wintypes.DWORD),
                    ("Position", wintypes.DWORD),
                    ("TotalPages", wintypes.DWORD),
                    ("PagesPrinted", wintypes.DWORD),
                    ("Submitted", SYSTEMTIME)]


def _err(what):
    code = ctypes.get_last_error() if WINDOWS else 0
    return SpoolError(f"{what} failed (Windows error {code})")


def list_printers():
    """Names of the printers this user can see, or [] off Windows."""
    if not WINDOWS:
        return []
    flags = PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    need, got = wintypes.DWORD(0), wintypes.DWORD(0)
    _ws.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(need),
                      ctypes.byref(got))
    if not need.value:
        return []
    buf = ctypes.create_string_buffer(need.value)
    if not _ws.EnumPrintersW(flags, None, 4, buf, need, ctypes.byref(need),
                             ctypes.byref(got)):
        return []
    arr = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_4W))
    return [arr[i].pPrinterName for i in range(got.value)]


def find_mill(names=None):
    """The SRM-20's printer name, or None when the driver is not installed."""
    for n in (names if names is not None else list_printers()):
        if "srm-20" in n.lower() or "srm20" in n.lower():
            return n
    return None


class SpoolPrinter:
    """The mill as Windows sees it: a RAW printer."""

    def __init__(self, name):
        self.name = name

    def _open(self):
        h = wintypes.HANDLE()
        if not _ws.OpenPrinterW(self.name, ctypes.byref(h), None):
            raise _err(f"opening printer {self.name!r}")
        return h

    def send(self, data, name="SRM-CAM job"):
        """Queue ``data`` (bytes or str) RAW. Returns the spooler job id."""
        if isinstance(data, str):
            data = data.encode("ascii")
        h = self._open()
        try:
            doc = DOC_INFO_1W(name, None, "RAW")
            job = _ws.StartDocPrinterW(h, 1, ctypes.byref(doc))
            if not job:
                raise _err("StartDocPrinter")
            try:
                if not _ws.StartPagePrinter(h):
                    raise _err("StartPagePrinter")
                written = wintypes.DWORD(0)
                ok = _ws.WritePrinter(h, data, len(data), ctypes.byref(written))
                _ws.EndPagePrinter(h)
                if not ok or written.value != len(data):
                    raise _err("WritePrinter (%d of %d bytes)"
                               % (written.value, len(data)))
            finally:
                _ws.EndDocPrinter(h)
            return int(job)
        finally:
            _ws.ClosePrinter(h)

    def _jobs(self, h):
        need, got = wintypes.DWORD(0), wintypes.DWORD(0)
        _ws.EnumJobsW(h, 0, 255, 1, None, 0, ctypes.byref(need),
                      ctypes.byref(got))
        if not need.value:
            return []
        buf = ctypes.create_string_buffer(need.value)
        if not _ws.EnumJobsW(h, 0, 255, 1, buf, need, ctypes.byref(need),
                             ctypes.byref(got)):
            raise _err("EnumJobs")
        arr = ctypes.cast(buf, ctypes.POINTER(JOB_INFO_1W))
        return [(arr[i].JobId, arr[i].pDocument, arr[i].Status)
                for i in range(got.value)]

    def pending(self):
        """How many jobs the spooler still holds for the mill."""
        h = self._open()
        try:
            return len(self._jobs(h))
        finally:
            _ws.ClosePrinter(h)

    def purge(self):
        """Throw away every queued job. Deleting each job works for its
        owner without admin rights; the printer-wide purge is tried after,
        for jobs someone else queued, and may be refused."""
        h = self._open()
        try:
            for job_id, _doc, _st in self._jobs(h):
                _ws.SetJobW(h, job_id, 0, None, JOB_CONTROL_DELETE)
            _ws.SetPrinterW(h, 0, None, PRINTER_CONTROL_PURGE)
            return len(self._jobs(h)) == 0
        finally:
            _ws.ClosePrinter(h)


# ---------------------------------------------------------------------------
USBMISC_ROOT = "/sys/class/usbmisc"
USB_DEV_DIR = "/dev/usb"


def _sys_read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def usblp_nodes(sys_root=USBMISC_ROOT, dev_dir=USB_DEV_DIR):
    """``[(device, description)]`` for every SRM-20 the kernel has a printer
    node for, read from sysfs. Nothing is opened.

    Matched like :func:`find_mill` matches a printer's name, or by Roland's
    USB vendor id. Never by being the only printer there: ``lp0`` may well be
    somebody's laser printer, and this is NC code.
    """
    found = []
    try:
        names = sorted(d.name for d in Path(sys_root).iterdir()
                       if d.name.startswith("lp"))
    except OSError:
        return found
    for name in names:
        intf = (Path(sys_root) / name / "device").resolve()
        usb = intf.parent
        text = " ".join(_sys_read(f) for f in (
            intf / "ieee1284_id", usb / "manufacturer", usb / "product"))
        vendor = _sys_read(usb / "idVendor").lower()
        if find_mill([text]) or vendor == plat.ROLAND_USB_VID:
            found.append((f"{dev_dir}/{name}", text.strip()))
    return found


class UsbLpPrinter:
    """The mill as Linux sees it: a USB printer node.

    Jobs queue here, and one thread feeds them to the node, because a write
    takes as long as the mill takes to accept the bytes, and the caller is the
    loop that has to keep watching the machine. So ``pending()`` means what it
    means on Windows: jobs not yet entirely handed over.

    The node is opened non-blocking and fed small chunks, for STOP. A blocking
    ``write`` to ``usblp`` cannot be interrupted from another thread; here the
    feeder is never further than one poll from noticing a purge, and closing
    the node then kills the transfer in flight (``usblp_release`` in the kernel's
    ``usblp.c``). The poll after the last chunk is not optional: that close would
    kill it just the same at the end of a job that went well. POLLOUT is the
    kernel's "the last transfer completed", so that poll is what waits for it.
    """
    CHUNK = 4096
    POLL_MS = 50

    @staticmethod
    def _flags():
        # A function, not a class attribute: this module imports on Windows,
        # where O_NONBLOCK does not exist.
        return os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC

    def __init__(self, device):
        self.device = device
        self._lock = threading.Lock()
        self._jobs = deque()
        self._next_id = 1
        self._feeder = None
        self._cancel = threading.Event()
        self._failure = None

    def problem(self):
        """Why jobs cannot be sent, or None. Opened and shut straight away,
        which sends nothing, so a run finds out before it probes for ten
        minutes rather than at its first job."""
        try:
            os.close(self._open())
        except SpoolError as e:
            return str(e)
        return None

    def _open(self):
        try:
            return os.open(self.device, self._flags())
        except PermissionError as e:
            raise SpoolError(plat.serial_permission_hint(self.device)
                             or f"{self.device}: permission denied.") from e
        except OSError as e:
            raise SpoolError(f"{self.device} would not open: "
                             f"{os.strerror(e.errno)}.") from e

    def send(self, data, name="SRM-CAM job"):
        """Queue ``data`` (bytes or str). Returns a job id."""
        if isinstance(data, str):
            data = data.encode("ascii")
        os.close(self._open())           # refused here, not on another thread
        with self._lock:
            if self._failure is not None:
                raise SpoolError(self._failure)
            job = self._next_id
            self._next_id += 1
            self._jobs.append((job, data))
            if self._feeder is None or not self._feeder.is_alive():
                self._cancel.clear()
                self._feeder = threading.Thread(target=self._feed, daemon=True,
                                                name="srm-usblp")
                self._feeder.start()
        return job

    def _feed(self):
        while True:
            with self._lock:
                if not self._jobs:
                    self._feeder = None
                    return
                _job, data = self._jobs[0]
            try:
                self._write_job(data)
            except OSError as e:
                with self._lock:
                    self._failure = (f"the mill's USB lead failed "
                                     f"({self.device}: {os.strerror(e.errno)})")
                    self._jobs.clear()
                    self._feeder = None
                return
            with self._lock:
                self._jobs.popleft()
                self._cancel.clear()

    def _write_job(self, data):
        fd = os.open(self.device, self._flags())
        try:
            ready = select.poll()
            ready.register(fd, select.POLLOUT)
            done = 0
            while done < len(data):
                if self._cancel.is_set():
                    return
                if not ready.poll(self.POLL_MS):
                    continue
                try:
                    done += os.write(fd, data[done:done + self.CHUNK])
                except OSError as e:
                    if e.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                        raise
            # The last chunk is still in flight until the node says it can
            # take another; see the class docstring.
            while not self._cancel.is_set():
                for _fd, event in ready.poll(self.POLL_MS):
                    if event & (select.POLLERR | select.POLLHUP):
                        raise OSError(errno.ENODEV, os.strerror(errno.ENODEV))
                    return
        finally:
            os.close(fd)

    def pending(self):
        """How many jobs are not fully handed over. A lead that failed raises,
        because a job that will now never finish looks exactly like a long
        one from out here."""
        with self._lock:
            if self._failure is not None:
                raise SpoolError(self._failure)
            return len(self._jobs)

    def purge(self):
        """Throw away everything not yet sent, and the transfer in flight."""
        with self._lock:
            while len(self._jobs) > 1:
                self._jobs.pop()
            if self._jobs:
                self._cancel.set()
        return True


class CupsPrinter:
    """The mill as a raw CUPS queue: ``lp``, ``lpstat`` and ``cancel``.

    The tools rather than a library because they are on every system with CUPS
    and nothing has to be bundled for them. ``run`` is injectable so the tests
    need no print system. Only ``purge`` does not wait for its tool: it is the
    first thing a STOP does, and the motion commands come after it.
    """

    def __init__(self, name, run=subprocess.run, popen=subprocess.Popen):
        self.name = name
        self._run = run
        self._popen = popen

    def problem(self):
        return None

    def _tool(self, *argv, **kw):
        try:
            return self._run(list(argv), capture_output=True, timeout=20,
                             env=plat.host_env(), **kw)
        except (OSError, subprocess.SubprocessError) as e:
            raise SpoolError(f"{argv[0]} failed: {e}") from e

    def send(self, data, name="SRM-CAM job"):
        if isinstance(data, str):
            data = data.encode("ascii")
        # -o raw: no CUPS filter gets to reinterpret NC code as something to
        # print.
        r = self._tool("lp", "-d", self.name, "-o", "raw", "-t", name,
                       input=data)
        if r.returncode:
            raise SpoolError("lp refused the job: "
                             + r.stderr.decode("utf-8", "replace").strip())
        # "request id is SRM-20-42 (1 file(s))": the queue's name has a dash and
        # a number in it too.
        m = re.search(rb"request id is \S*-(\d+)", r.stdout)
        return int(m.group(1)) if m else 0

    def pending(self):
        r = self._tool("lpstat", "-o", self.name)
        if r.returncode:
            raise SpoolError("lpstat failed: "
                             + r.stderr.decode("utf-8", "replace").strip())
        return sum(1 for ln in r.stdout.splitlines() if ln.strip())

    def purge(self):
        try:
            self._popen(["cancel", "-a", self.name], env=plat.host_env(),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        return True


def cups_queues(run=subprocess.run):
    """Names of the CUPS queues this user can see, or [] with no CUPS."""
    try:
        r = run(["lpstat", "-a"], capture_output=True, timeout=10,
                env=plat.host_env())
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode:
        return []
    return [ln.split()[0] for ln in r.stdout.decode("utf-8", "replace").splitlines()
            if ln.strip()]


def find_printer(platform=None):
    """A printer for the mill on this host, or None when there is no way to
    reach it. See :func:`no_printer_reason` for what to say then."""
    for route in plat.capabilities(platform).job_routes:
        if route == plat.JOB_SPOOLER:
            name = find_mill()
            if name is not None:
                return SpoolPrinter(name)
        elif route == plat.JOB_USBLP:
            nodes = usblp_nodes()
            if nodes:
                return UsbLpPrinter(nodes[0][0])
        elif route == plat.JOB_CUPS:
            name = find_mill(cups_queues())
            if name is not None:
                return CupsPrinter(name)
    return None


# The queue a raw CUPS route needs, set up once. The URI is the mill's own, and
# only lpinfo can say what it is on a given machine.
_ADD_CUPS_QUEUE = ("lpinfo -v | grep -i roland  to find the mill's usb:// "
                   "address, then  sudo lpadmin -p SRM-20 -E -v '<that address>' "
                   "-m raw")


def no_printer_reason(platform=None, sys_root=plat.USB_SYS_ROOT):
    """The sentence for :func:`find_printer` coming back empty."""
    caps = plat.capabilities(platform)
    if plat.JOB_SPOOLER in caps.job_routes:
        return ("The Roland SRM-20 printer is not installed on this PC, so "
                "there is nothing to send jobs to.")
    if plat.JOB_USBLP in caps.job_routes:
        if plat.mill_on_usb(platform, sys_root):
            return ("The mill is on USB but has no printer node, which means "
                    "the kernel's usblp driver is not bound to it. Run  sudo "
                    "modprobe usblp  and plug the mill in again; if your system "
                    "keeps usblp off for CUPS, add it there instead: "
                    + _ADD_CUPS_QUEUE + ".")
        return ("No SRM-20 found on USB. The mill has its own USB lead, "
                "separate from the Arduino's: check that it is plugged in and "
                "the mill is switched on.")
    return ("The mill has not been added as a printer on this computer. Plug "
            "in its USB lead and switch it on, then, once: " + _ADD_CUPS_QUEUE
            + ".")
