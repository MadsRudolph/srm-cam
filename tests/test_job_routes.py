"""How a job reaches the mill off Windows: engine/rmlspool.py's other printers.

UsbLpPrinter runs against a real FIFO, which has what matters of a USB printer
node: it accepts bytes at the speed of whatever is on the far end, it can fill
up, and its far end can go away. CupsPrinter runs against a fake ``lp``.
Discovery runs against a fake sysfs tree: nothing here opens a real device.
"""
import os
import subprocess
import threading
import time

import pytest

from gerber2rml import platform as plat
from gerber2rml.engine import rmlspool

posix = pytest.mark.skipif(os.name == "nt", reason="POSIX nodes")


class Reader(threading.Thread):
    """The mill's end of the wire."""

    def __init__(self, path, delay=0.0):
        super().__init__(daemon=True)
        self.got = bytearray()
        self.delay = delay
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.stop_reading = threading.Event()
        self.running = threading.Event()
        self.running.set()

    def run(self):
        while not self.stop_reading.is_set():
            if not self.running.is_set():
                time.sleep(0.002)
                continue
            try:
                chunk = os.read(self.fd, 8192)
            except BlockingIOError:
                time.sleep(0.001)
                continue
            if chunk:
                self.got += chunk
            if self.delay:
                time.sleep(self.delay)

    def finish(self):
        self.stop_reading.set()
        self.join(1)
        os.close(self.fd)


@pytest.fixture
def node(tmp_path):
    path = tmp_path / "lp0"
    os.mkfifo(path)
    return str(path)


def _settle(cond, secs=5.0):
    t0 = time.monotonic()
    while not cond() and time.monotonic() - t0 < secs:
        time.sleep(0.002)
    return cond()


@posix
def test_a_job_arrives_byte_for_byte_and_in_order(node):
    r = Reader(node)
    r.start()
    p = rmlspool.UsbLpPrinter(node)
    first = bytes(range(256)) * 2000          # bigger than any buffer on the way
    second = b"%\nO0001\nG0 X1 Y2\nM30\n%\n"
    assert p.send(first, "one") != p.send(second, "two")
    assert _settle(lambda: p.pending() == 0)
    assert _settle(lambda: len(r.got) == len(first) + len(second))
    r.finish()
    assert bytes(r.got) == first + second


@posix
def test_text_goes_as_ascii_like_the_spooler(node):
    r = Reader(node)
    r.start()
    p = rmlspool.UsbLpPrinter(node)
    p.send("G0 X1\n")
    assert _settle(lambda: bytes(r.got) == b"G0 X1\n")
    r.finish()


@posix
def test_pending_counts_a_job_until_the_mill_has_taken_it_all(node):
    """Same meaning as the spooler's: what the runner's "nothing queued" reads."""
    r = Reader(node)
    r.running.clear()                         # the mill's buffer is full
    r.start()
    p = rmlspool.UsbLpPrinter(node)
    p.send(b"x" * 500_000)
    time.sleep(0.2)
    assert p.pending() == 1
    r.running.set()
    assert _settle(lambda: p.pending() == 0)
    r.finish()


@posix
def test_purge_stops_feeding_at_once(node):
    r = Reader(node)
    r.running.clear()
    r.start()
    p = rmlspool.UsbLpPrinter(node)
    p.send(b"x" * 500_000, "job")
    p.send(b"y" * 500_000, "next")
    time.sleep(0.1)
    t0 = time.monotonic()
    assert p.purge() is True
    assert _settle(lambda: p.pending() == 0, 1.0)
    took = time.monotonic() - t0
    print(f"\npurge: nothing queued after {took * 1000:.1f} ms")
    assert took < 2 * rmlspool.UsbLpPrinter.POLL_MS / 1000 + 0.05
    r.running.set()
    time.sleep(0.2)
    r.finish()
    assert len(r.got) < 500_000 and b"y" not in r.got


@posix
def test_a_purged_printer_takes_the_next_job(node):
    r = Reader(node)
    r.running.clear()
    r.start()
    p = rmlspool.UsbLpPrinter(node)
    p.send(b"x" * 500_000)
    time.sleep(0.05)
    p.purge()
    assert _settle(lambda: p.pending() == 0, 1.0)
    r.running.set()
    p.send(b"after\n")
    assert _settle(lambda: bytes(r.got).endswith(b"after\n"))
    r.finish()


@posix
def test_a_lead_pulled_mid_job_raises_from_pending(node):
    """A job that will never finish looks exactly like a long one, so this is
    the runner's only way to find out. The failure stays: a dead lead is not
    forgotten by the next job."""
    r = Reader(node)
    r.running.clear()
    r.start()
    p = rmlspool.UsbLpPrinter(node)
    p.send(b"x" * 500_000)
    time.sleep(0.05)
    r.finish()                                # the far end is gone
    assert _settle(lambda: _raises(p), 2.0)
    with pytest.raises(rmlspool.SpoolError, match="USB lead"):
        p.pending()


def _raises(p):
    try:
        p.pending()
    except rmlspool.SpoolError:
        return True
    return False


@posix
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root opens anything")
def test_a_node_this_user_may_not_open_says_how_to_fix_it(tmp_path, monkeypatch):
    f = tmp_path / "lp0"
    f.write_bytes(b"")
    f.chmod(0)
    p = rmlspool.UsbLpPrinter(str(f))
    why = p.problem()
    assert why and str(f) in why
    with pytest.raises(rmlspool.SpoolError):
        p.send(b"x")
    assert p.pending() == 0


@posix
def test_a_missing_node_is_a_problem_and_not_a_traceback(tmp_path):
    p = rmlspool.UsbLpPrinter(str(tmp_path / "nope"))
    assert "would not open" in p.problem()


@posix
def test_a_node_that_opens_has_no_problem_and_problem_writes_nothing(node):
    r = Reader(node)
    r.start()
    assert rmlspool.UsbLpPrinter(node).problem() is None
    time.sleep(0.05)
    r.finish()
    assert r.got == b""


# ----------------------------------------------------------------- discovery
def _lp(root, name, *, vendor="0b75", product="SRM-20", maker="Roland DG",
        ieee="MFG:Roland DG;MDL:SRM-20;"):
    if os.name == "nt":
        pytest.skip("sysfs is Linux, and a symlink may need a privilege here")
    usb = root / "devices" / f"usb-{name}"
    intf = usb / "1-1:1.0"
    intf.mkdir(parents=True)
    (usb / "idVendor").write_text(vendor + "\n")
    (usb / "product").write_text(product + "\n")
    (usb / "manufacturer").write_text(maker + "\n")
    (intf / "ieee1284_id").write_text(ieee + "\n")
    cls = root / "class" / name
    cls.mkdir(parents=True)
    (cls / "device").symlink_to(intf)
    return root / "class"


def test_the_mill_is_found_by_what_it_says_it_is(tmp_path):
    sys_root = _lp(tmp_path, "lp0")
    assert rmlspool.usblp_nodes(sys_root, "/dev/usb")[0][0] == "/dev/usb/lp0"


def test_someones_laser_printer_never_gets_the_nc_code(tmp_path):
    sys_root = _lp(tmp_path, "lp0", vendor="03f0", product="LaserJet 1020",
                   maker="HP", ieee="MFG:Hewlett-Packard;MDL:LaserJet 1020;")
    assert rmlspool.usblp_nodes(sys_root, "/dev/usb") == []


def test_the_mill_is_picked_out_from_behind_another_printer(tmp_path):
    _lp(tmp_path, "lp0", vendor="03f0", product="LaserJet", maker="HP", ieee="")
    sys_root = _lp(tmp_path, "lp1")
    assert [d for d, _t in rmlspool.usblp_nodes(sys_root, "/dev/usb")] == \
        ["/dev/usb/lp1"]


def test_rolands_vendor_id_is_enough_when_the_strings_differ(tmp_path):
    sys_root = _lp(tmp_path, "lp0", product="MODELA", maker="", ieee="")
    assert rmlspool.usblp_nodes(sys_root, "/dev/usb")


def test_no_usbmisc_class_at_all_is_just_nothing_found(tmp_path):
    assert rmlspool.usblp_nodes(tmp_path / "missing") == []


def test_find_printer_follows_the_capabilities(monkeypatch):
    monkeypatch.setattr(rmlspool, "usblp_nodes", lambda: [("/dev/usb/lp3", "x")])
    p = rmlspool.find_printer("linux")
    assert isinstance(p, rmlspool.UsbLpPrinter) and p.device == "/dev/usb/lp3"


def test_linux_falls_back_to_a_cups_queue_without_usblp(monkeypatch):
    monkeypatch.setattr(rmlspool, "usblp_nodes", lambda: [])
    monkeypatch.setattr(rmlspool, "cups_queues", lambda: ["HP", "SRM-20"])
    p = rmlspool.find_printer("linux")
    assert isinstance(p, rmlspool.CupsPrinter) and p.name == "SRM-20"


def test_macos_only_looks_at_cups(monkeypatch):
    def no(*a):
        raise AssertionError("macOS has no usblp")
    monkeypatch.setattr(rmlspool, "usblp_nodes", no)
    monkeypatch.setattr(rmlspool, "cups_queues", lambda: ["SRM-20"])
    assert isinstance(rmlspool.find_printer("darwin"), rmlspool.CupsPrinter)


def test_windows_still_finds_the_spooler_printer(monkeypatch):
    monkeypatch.setattr(rmlspool, "list_printers",
                        lambda: ["Adobe PDF", "Roland SRM-20"])
    p = rmlspool.find_printer("win32")
    assert isinstance(p, rmlspool.SpoolPrinter) and p.name == "Roland SRM-20"


def test_nothing_found_returns_none(monkeypatch):
    monkeypatch.setattr(rmlspool, "usblp_nodes", lambda: [])
    monkeypatch.setattr(rmlspool, "cups_queues", lambda: [])
    assert rmlspool.find_printer("linux") is None
    assert rmlspool.find_printer("freebsd14") is None


def test_each_system_says_its_own_reason_for_no_printer(tmp_path):
    empty = tmp_path / "usb"
    empty.mkdir()
    assert "not installed on this PC" in rmlspool.no_printer_reason("win32")
    assert "own USB lead" in rmlspool.no_printer_reason("linux", empty)
    assert "lpadmin" in rmlspool.no_printer_reason("darwin", empty)


def test_a_mill_with_no_node_gets_told_about_usblp(tmp_path):
    d = tmp_path / "usb" / "1-1"
    d.mkdir(parents=True)
    (d / "idVendor").write_text("0b75\n")
    why = rmlspool.no_printer_reason("linux", tmp_path / "usb")
    assert "modprobe usblp" in why and "lpadmin" in why


# ----------------------------------------------------------------------- CUPS
class _Done:
    def __init__(self, out=b"", err=b"", code=0):
        self.stdout, self.stderr, self.returncode = out, err, code


class _Lp:
    def __init__(self, **kw):
        self.calls = []
        self.reply = _Done(**kw)

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return self.reply


def test_cups_sends_raw_so_no_filter_reads_the_nc_code():
    lp = _Lp(out=b"request id is SRM-20-42 (1 file(s))\n")
    p = rmlspool.CupsPrinter("SRM-20", run=lp)
    assert p.send("G0 X1\n", "traces") == 42
    argv, kw = lp.calls[0]
    assert argv[:3] == ["lp", "-d", "SRM-20"]
    assert argv[argv.index("-o") + 1] == "raw"
    assert kw["input"] == b"G0 X1\n"


def test_cups_refusing_a_job_raises_with_its_reason():
    p = rmlspool.CupsPrinter("SRM-20", run=_Lp(err=b"no such queue", code=1))
    with pytest.raises(rmlspool.SpoolError, match="no such queue"):
        p.send(b"x", "traces")


def test_cups_counts_the_queue():
    lp = _Lp(out=b"SRM-20-1 mads 100 now\nSRM-20-2 mads 100 now\n")
    assert rmlspool.CupsPrinter("SRM-20", run=lp).pending() == 2
    assert lp.calls[0][0] == ["lpstat", "-o", "SRM-20"]


def test_cups_going_away_mid_job_raises_rather_than_reading_as_empty():
    """An empty answer would read as the job having finished."""
    p = rmlspool.CupsPrinter("SRM-20", run=_Lp(err=b"not running", code=1))
    with pytest.raises(rmlspool.SpoolError):
        p.pending()


def test_cups_purge_does_not_wait_because_the_stop_commands_come_after_it():
    started = []

    class Popen:
        def __init__(self, argv, **kw):
            started.append(argv)

        def wait(self):
            raise AssertionError("purge must not wait")
    assert rmlspool.CupsPrinter("SRM-20", popen=Popen).purge() is True
    assert started == [["cancel", "-a", "SRM-20"]]


def test_a_system_with_no_lp_is_an_error_and_not_a_crash():
    def missing(*a, **k):
        raise FileNotFoundError("lp")
    p = rmlspool.CupsPrinter("SRM-20", run=missing, popen=missing)
    with pytest.raises(rmlspool.SpoolError):
        p.send(b"x")
    assert p.purge() is False


def test_cups_queues_reads_lpstat():
    lp = _Lp(out=b"HP accepting requests since x\nSRM-20 accepting requests\n")
    assert rmlspool.cups_queues(run=lp) == ["HP", "SRM-20"]
    assert rmlspool.cups_queues(run=_Lp(code=1)) == []

    def missing(*a, **k):
        raise FileNotFoundError("lpstat")
    assert rmlspool.cups_queues(run=missing) == []
    assert rmlspool.cups_queues(
        run=lambda *a, **k: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("lpstat", 1))) == []


def test_the_tools_never_inherit_the_bundles_libraries(monkeypatch):
    """Frozen, LD_LIBRARY_PATH points into the app, and a system tool started
    with that loads the wrong libc friends and dies."""
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    env = plat.host_env({"LD_LIBRARY_PATH": "/tmp/_MEIxxx", "HOME": "/h"})
    assert "LD_LIBRARY_PATH" not in env and env["HOME"] == "/h"
    env = plat.host_env({"LD_LIBRARY_PATH": "/tmp/_MEIxxx",
                         "LD_LIBRARY_PATH_ORIG": "/usr/local/lib"})
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env


def test_from_source_the_library_path_is_left_alone(monkeypatch):
    import sys
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert plat.host_env({"LD_LIBRARY_PATH": "/x"})["LD_LIBRARY_PATH"] == "/x"


def test_lp_output_is_kept_english_for_the_parser():
    assert plat.host_env({"LANG": "da_DK.UTF-8"})["LC_ALL"] == "C"


@posix
def test_the_module_imports_with_no_winspool_off_windows():
    assert rmlspool.WINDOWS is False
    assert rmlspool.list_printers() == []


# ------------------------------------------------- with the runner on top of it
class _Board:
    """The Arduino, answering by the last command it was sent."""
    def __init__(self):
        self.last = b""
        self.writes = []

    def write(self, data):
        self.last = data
        self.writes.append(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        pass

    def readline(self):
        c, self.last = self.last[:1], b""
        return {b"Q": b"Q 0 0 0 0\n", b"X": b"X 130 4 0\n",
                b"K": b"K ok\n"}.get(c, b"")


@posix
def test_the_runner_sees_a_job_through_this_printer_to_the_end(node):
    from gerber2rml.engine.runner import JobRunner
    r = Reader(node)
    r.start()
    job = b"G0 X1\n" * 20000
    runner = JobRunner(_Board(), rmlspool.UsbLpPrinter(node), lambda: False,
                       still_s=0.05, poll_s=0.01)
    assert runner.run(job.decode(), "traces", end_mm=None) is True
    assert _settle(lambda: len(r.got) == len(job))
    r.finish()
    assert bytes(r.got) == job


@posix
def test_stop_cuts_this_printer_off_and_the_board_hears_every_command(node):
    from gerber2rml.engine.runner import JobRunner, RunStopped
    r = Reader(node)
    r.running.clear()                         # the mill is busy with its buffer
    r.start()
    board = _Board()
    printer = rmlspool.UsbLpPrinter(node)
    stop = threading.Event()
    threading.Timer(0.1, stop.set).start()
    runner = JobRunner(board, printer, stop.is_set, poll_s=0.01)
    with pytest.raises(RunStopped):
        runner.run("G0 X1\n" * 200000, "traces", end_mm=None)
    assert _settle(lambda: printer.pending() == 0, 1.0)
    r.running.set()
    time.sleep(0.1)
    r.finish()
    assert len(r.got) < 1_200_000
    for command in (b"%\n", b"K\n", b"S 0\n", b"!\n"):
        assert command in board.writes
