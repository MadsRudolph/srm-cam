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
``purge()``; :class:`SpoolPrinter` is the real one and the simulator
(:mod:`gerber2rml.engine.simmachine`) supplies a fake.

On macOS the same API runs over CUPS instead (:class:`CupsPrinter`, at the
end of this module): the mill is a raw queue named ``SRM-20`` on its
``usb://Roland%20DG/...`` URI, made once with :func:`setup_mill_queue`
(``python -m gerber2rml.doctor --setup-mill``). See docs/macos.md.
"""
import ctypes
import os
import re
import subprocess
from ctypes import wintypes

from gerber2rml.platform import _is_macos, _is_windows

WINDOWS = _is_windows()
MACOS = _is_macos()

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
    """Names of the printers this user can see, or [] off Windows/macOS."""
    if MACOS:
        return cups_list_printers()
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


# --- macOS: the mill as a raw CUPS queue ----------------------------------
#
# The CUPS command-line tools rather than a library: they ship with macOS,
# need no new dependency, and are what a person would type to check by hand.
# Their messages are localised (macOS ignores LANG for them), so nothing here
# parses prose - only queue names and job ids, which are never translated.

CUPS_QUEUE = "SRM-20"
CUPS_SETUP_HINT = (
    "On a Mac the mill is a CUPS printer queue named SRM-20. With the mill "
    "on and its USB plugged in, run  python -m gerber2rml.doctor --setup-mill"
    "  once (it asks for an admin password). See docs/macos.md.")


def _cups(argv, run=None, input=None, timeout=15):
    """Run one CUPS tool. Returns stdout; raises SpoolError with stderr."""
    run = subprocess.run if run is None else run
    try:
        r = run(argv, input=input, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        raise SpoolError(f"{argv[0]} failed: {e}") from e
    out = r.stdout.decode("utf-8", "replace") if isinstance(
        r.stdout, bytes) else (r.stdout or "")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace") if isinstance(
            r.stderr, bytes) else (r.stderr or "")
        raise SpoolError(f"{' '.join(argv[:2])} failed: "
                         f"{(err or out).strip() or 'exit %d' % r.returncode}")
    return out


def cups_list_printers(run=None):
    """CUPS queue names (``lpstat -e``), or [] when CUPS cannot answer."""
    try:
        out = _cups(["lpstat", "-e"], run=run)
    except SpoolError:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


class CupsPrinter:
    """The mill as macOS sees it: a raw CUPS queue."""

    def __init__(self, name, run=None):
        self.name = name
        self._run = run

    def send(self, data, name="SRM-CAM job"):
        """Queue ``data`` (bytes or str) raw. Returns the CUPS job id."""
        if isinstance(data, str):
            data = data.encode("ascii")
        out = _cups(["lp", "-d", self.name, "-o", "raw", "-t", name],
                    run=self._run, input=data, timeout=60)
        # "request id is SRM-20-123 (1 file(s))", in whatever language.
        m = re.search(re.escape(self.name) + r"-(\d+)\b", out)
        if not m:
            raise SpoolError(f"lp gave no job id for {self.name!r}: "
                             f"{out.strip()!r}")
        return int(m.group(1))

    def _jobs(self):
        out = _cups(["lpstat", "-o", self.name], run=self._run)
        head = self.name + "-"
        return [ln.split()[0] for ln in out.splitlines()
                if ln.startswith(head)]

    def pending(self):
        """How many jobs CUPS still holds for the mill."""
        return len(self._jobs())

    def state(self):
        """``{"exists", "stopped", "accepting"}`` for the queue.

        Read from ``lpoptions``, whose ``printer-state`` and
        ``printer-is-accepting-jobs`` are attribute values rather than
        localised prose. CUPS stops a queue by itself after a failed job, and
        a stopped queue holds every later job without a word.
        """
        if self.name not in cups_list_printers(run=self._run):
            return {"exists": False, "stopped": False, "accepting": False}
        try:
            out = _cups(["lpoptions", "-p", self.name], run=self._run)
        except SpoolError:
            out = ""
        attrs = dict(kv.split("=", 1) for kv in out.split() if "=" in kv)
        return {"exists": True,
                "stopped": attrs.get("printer-state") == "5",
                "accepting": attrs.get("printer-is-accepting-jobs",
                                       "true") == "true"}

    def purge(self):
        """Throw away every queued job (``cancel -a``). Cancelling stops the
        USB backend, but bytes already in the mill's own buffer are beyond
        CUPS - that is the Arduino abort's job, as on Windows."""
        try:
            _cups(["cancel", "-a", self.name], run=self._run)
        except SpoolError:
            pass                    # someone else's job; checked below
        return self.pending() == 0


def cups_mill_uris(lpinfo_text):
    """Roland USB device URIs in ``lpinfo -v`` output, most likely first."""
    uris = []
    for ln in lpinfo_text.splitlines():
        parts = ln.split(None, 1)
        if len(parts) == 2 and parts[1].startswith("usb://") \
                and "roland" in parts[1].lower():
            uris.append(parts[1].strip())
    uris.sort(key=lambda u: "srm" not in u.lower())
    return uris


def _applescript_admin(commands):
    """``osascript`` argv that runs ``commands`` (argv lists) as admin.

    macOS's own password dialog asks; nothing here sees the password. The
    commands are joined into one shell line so the dialog comes up once.
    """
    import shlex
    line = " && ".join(" ".join(shlex.quote(a) for a in c) for c in commands)
    quoted = line.replace("\\", "\\\\").replace('"', '\\"')
    return ["osascript", "-e",
            f'do shell script "{quoted}" with administrator privileges']


def _as_admin(commands, run=None, admin="sudo", timeout=300):
    """Run each argv in ``commands`` with admin rights.

    ``admin`` is ``"sudo"`` for a terminal (asks there, unless already root)
    or ``"gui"`` for macOS's password dialog, which is what the app uses.
    """
    if admin == "gui":
        _cups(_applescript_admin(commands), run=run, timeout=timeout)
        return
    sudo = [] if getattr(os, "geteuid", lambda: 0)() == 0 else ["sudo"]
    for c in commands:
        _cups(sudo + c, run=run, timeout=timeout)


def find_mill_uri(run=None):
    """The mill's USB URI as CUPS sees it, or None when it is not plugged in.

    USB only (``--include-schemes``): probing the network backends as well
    takes seconds and can never find a USB mill.
    """
    out = _cups(["lpinfo", "--include-schemes", "usb", "-v"], run=run,
                timeout=90)
    uris = cups_mill_uris(out)
    return uris[0] if uris else None


def setup_mill_queue(queue=CUPS_QUEUE, run=None, say=print, admin="sudo"):
    """Make the raw CUPS queue the mill is sent to. Returns the queue name.

    Needs the mill on and plugged in, and admin rights (see :func:`_as_admin`).
    CUPS may warn that raw queues are deprecated; on macOS they still work,
    and are exactly what the Windows spooler does with the Roland driver's
    "RAW" datatype. Newer CUPS refuses "-m raw"; no model at all is the same
    raw queue, so that is the fallback.
    """
    uri = find_mill_uri(run=run)
    if uri is None:
        raise SpoolError("no Roland USB device found by lpinfo -v - is the "
                         "mill switched on and its USB cable plugged in?")
    say(f"Mill found at {uri}")
    add = ["lpadmin", "-p", queue, "-E", "-v", uri]
    rest = [["cupsenable", queue], ["cupsaccept", queue]]
    try:
        _as_admin([add + ["-m", "raw"]] + rest, run=run, admin=admin)
    except SpoolError as e:
        if "cancel" in str(e).lower() or "-128" in str(e):
            raise SpoolError("cancelled - no password was given") from e
        _as_admin([add] + rest, run=run, admin=admin)
    say(f"Queue {queue} is ready. Check with:  lpstat -p {queue}")
    return queue


def resume_queue(queue=CUPS_QUEUE, run=None, admin="sudo"):
    """Start a queue CUPS stopped after a failed job, and let it take jobs."""
    _as_admin([["cupsenable", queue], ["cupsaccept", queue]], run=run,
              admin=admin)


if MACOS:
    SpoolPrinter = CupsPrinter      # noqa: F811 - the macOS mill
