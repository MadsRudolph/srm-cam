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
"""
import ctypes
import sys
from ctypes import wintypes

PRINTER_ENUM_LOCAL = 0x2
PRINTER_ENUM_CONNECTIONS = 0x4
JOB_CONTROL_DELETE = 5
PRINTER_CONTROL_PURGE = 3


class SpoolError(RuntimeError):
    pass


if sys.platform == "win32":
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
    code = ctypes.get_last_error() if sys.platform == "win32" else 0
    return SpoolError(f"{what} failed (Windows error {code})")


def list_printers():
    """Names of the printers this user can see, or [] off Windows."""
    if sys.platform != "win32":
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
