"""The Linux job route: the SRM-20 as the kernel's usblp printer node.

A FIFO stands in for /dev/usb/lp0: it takes writes, non-blocking, and the
reader at the other end sees exactly the bytes a mill would.
"""
import os
import sys
import threading
import time

import pytest

from gerber2rml.engine import rmlspool

posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX nodes")


def _sysfs(tmp_path, name, vendor, ieee):
    usb = tmp_path / "devices" / "3-1"
    intf = usb / "3-1:1.0"
    intf.mkdir(parents=True)
    (usb / "idVendor").write_text(vendor + "\n")
    (usb / "manufacturer").write_text("Roland DG\n")
    (usb / "product").write_text("SRM-20\n")
    (intf / "ieee1284_id").write_text(ieee + "\n")
    cls = tmp_path / "usbmisc"
    cls.mkdir(exist_ok=True)
    (cls / name).mkdir()
    (cls / name / "device").symlink_to(intf)
    return cls


@posix
def test_usblp_nodes_finds_the_roland_by_vendor(tmp_path):
    cls = _sysfs(tmp_path, "lp0", "0b75",
                 "MFG:Roland;CMD:RML-1;MDL:SRM-20;DES:Roland SRM-20;")
    nodes = rmlspool.usblp_nodes(sys_root=cls, dev_dir="/dev/usb")
    assert [n for n, _ in nodes] == ["/dev/usb/lp0"]
    assert "SRM-20" in nodes[0][1]


@posix
def test_usblp_nodes_never_takes_somebody_elses_printer(tmp_path):
    usb = tmp_path / "devices" / "1-1"
    intf = usb / "1-1:1.0"
    intf.mkdir(parents=True)
    (usb / "idVendor").write_text("03f0\n")
    (intf / "ieee1284_id").write_text("MFG:HP;MDL:LaserJet;\n")
    cls = tmp_path / "usbmisc"
    cls.mkdir()
    (cls / "lp0").mkdir()
    (cls / "lp0" / "device").symlink_to(intf)
    assert rmlspool.usblp_nodes(sys_root=cls) == []


def _drain(path, out, stop):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        while not stop.is_set():
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                chunk = b""
            if chunk:
                out.extend(chunk)
            else:
                time.sleep(0.005)
    finally:
        os.close(fd)


@posix
def test_a_job_arrives_whole_and_pending_counts_down(tmp_path):
    node = tmp_path / "lp0"
    os.mkfifo(node)
    got, stop = bytearray(), threading.Event()
    reader = threading.Thread(target=_drain, args=(node, got, stop))
    reader.start()
    time.sleep(0.05)
    try:
        p = rmlspool.UsbLpPrinter(str(node))
        assert p.problem() is None
        job = "%\nG21\n" + "G1 X1 Y1\n" * 5000 + "M30\n%\n"
        assert p.send(job, "test") == 1
        deadline = time.monotonic() + 10
        while p.pending() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert p.pending() == 0
        time.sleep(0.05)
        assert bytes(got) == job.encode()
    finally:
        stop.set()
        reader.join()


@posix
def test_purge_stops_feeding(tmp_path):
    node = tmp_path / "lp0"
    os.mkfifo(node)
    hold = os.open(node, os.O_RDONLY | os.O_NONBLOCK)   # a reader that never reads
    try:
        p = rmlspool.UsbLpPrinter(str(node))
        p.send(b"x" * 2_000_000, "big")
        p.send(b"y" * 10, "next")
        time.sleep(0.1)
        assert p.pending() == 2
        assert p.purge() is True
        deadline = time.monotonic() + 2
        while p.pending() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert p.pending() == 0
    finally:
        os.close(hold)


@posix
def test_a_refused_node_says_how_to_fix_it(tmp_path):
    node = tmp_path / "lp0"
    node.write_bytes(b"")
    node.chmod(0)
    if os.geteuid() == 0:
        pytest.skip("root opens anything")
    why = rmlspool.UsbLpPrinter(str(node)).problem()
    assert "permission denied" in why and "Set up USB access" in why
