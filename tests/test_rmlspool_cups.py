"""The macOS spooler: the same printer API as Windows, over the CUPS tools.

Every test injects a fake ``subprocess.run``, so these run on any host and
nothing ever reaches a real queue - let alone a real mill.
"""
import subprocess

import pytest

from gerber2rml.engine import rmlspool
from gerber2rml.engine.rmlspool import CupsPrinter, SpoolError


class FakeRun:
    """Records argv and answers from a table keyed by the argv prefix."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, argv, input=None, capture_output=True, timeout=None):
        self.calls.append((list(argv), input))
        for prefix, (rc, out, err) in self.answers.items():
            if tuple(argv[:len(prefix)]) == prefix:
                return subprocess.CompletedProcess(argv, rc, out.encode(),
                                                   err.encode())
        raise AssertionError(f"unexpected command {argv}")


def test_list_printers_reads_queue_names():
    run = FakeRun({("lpstat", "-e"): (0, "dummy\nSRM-20\n", "")})
    names = rmlspool.cups_list_printers(run=run)
    assert names == ["dummy", "SRM-20"]
    assert rmlspool.find_mill(names) == "SRM-20"


def test_list_printers_is_empty_when_cups_cannot_answer():
    run = FakeRun({("lpstat",): (1, "", "lpstat: scheduler not running")})
    assert rmlspool.cups_list_printers(run=run) == []


def test_send_is_raw_on_stdin_and_returns_the_job_id():
    """The id is read off the queue name, not the sentence around it - macOS
    localises that sentence whatever LANG says."""
    run = FakeRun({("lp",): (0, "anmodnings-id er SRM-20-123 (1 fil(er))\n",
                             "")})
    job = CupsPrinter("SRM-20", run=run).send("^IN;V15;", "board_traces")
    assert job == 123
    argv, data = run.calls[0]
    assert argv == ["lp", "-d", "SRM-20", "-o", "raw", "-t", "board_traces"]
    assert data == b"^IN;V15;"


def test_send_raises_spool_error_with_stderr():
    run = FakeRun({("lp",): (1, "", "lp: The printer or class does not "
                                    "exist.")})
    with pytest.raises(SpoolError, match="does not exist"):
        CupsPrinter("SRM-20", run=run).send(b"x")


def test_send_without_a_job_id_is_an_error():
    run = FakeRun({("lp",): (0, "something else\n", "")})
    with pytest.raises(SpoolError, match="no job id"):
        CupsPrinter("SRM-20", run=run).send(b"x")


def test_a_missing_tool_is_a_spool_error_not_a_crash():
    def run(argv, **kw):
        raise FileNotFoundError(argv[0])
    with pytest.raises(SpoolError):
        CupsPrinter("SRM-20", run=run).pending()


def test_pending_counts_only_this_queues_jobs():
    out = ("SRM-20-12   marius   2048   fre 13 nov 16:01:02 2026\n"
           "SRM-20-13   marius   1024   fre 13 nov 16:01:09 2026\n")
    run = FakeRun({("lpstat", "-o", "SRM-20"): (0, out, "")})
    assert CupsPrinter("SRM-20", run=run).pending() == 2


def test_pending_is_zero_on_an_empty_queue():
    run = FakeRun({("lpstat", "-o", "SRM-20"): (0, "", "")})
    assert CupsPrinter("SRM-20", run=run).pending() == 0


def test_pending_raises_when_the_queue_is_gone():
    """Like OpenPrinter failing on Windows: the run must not read a vanished
    queue as 'nothing left to send'."""
    run = FakeRun({("lpstat", "-o"): (1, "", "lpstat: Invalid destination")})
    with pytest.raises(SpoolError):
        CupsPrinter("SRM-20", run=run).pending()


class Queue:
    """A queue whose jobs ``cancel -a`` really removes."""

    def __init__(self, jobs, cancel_works=True):
        self.jobs = list(jobs)
        self.cancel_works = cancel_works
        self.calls = []

    def __call__(self, argv, input=None, capture_output=True, timeout=None):
        self.calls.append(list(argv))
        if argv[0] == "cancel":
            if self.cancel_works:
                self.jobs = []
                return subprocess.CompletedProcess(argv, 0, b"", b"")
            return subprocess.CompletedProcess(argv, 1, b"",
                                               b"cancel: Forbidden")
        out = "".join(f"SRM-20-{j} marius 10 now\n" for j in self.jobs)
        return subprocess.CompletedProcess(argv, 0, out.encode(), b"")


def test_purge_empties_the_queue():
    """STOP depends on this: purge first, then the Arduino abort."""
    q = Queue([7, 8])
    assert CupsPrinter("SRM-20", run=q).purge() is True
    assert ["cancel", "-a", "SRM-20"] in q.calls
    assert q.jobs == []


def test_purge_reports_jobs_it_could_not_remove():
    q = Queue([7], cancel_works=False)
    assert CupsPrinter("SRM-20", run=q).purge() is False


LPINFO = ("network ipp\n"
          "direct usb://Brother/HL-1110?serial=X\n"
          "direct usb://Roland%20DG/SRM-20?serial=ZHA1234\n"
          "network socket\n")


def test_mill_uri_is_found_in_lpinfo():
    assert rmlspool.cups_mill_uris(LPINFO) == [
        "usb://Roland%20DG/SRM-20?serial=ZHA1234"]
    assert rmlspool.cups_mill_uris("network ipp\n") == []


def test_setup_makes_an_enabled_raw_queue(monkeypatch):
    monkeypatch.setattr(rmlspool.os, "geteuid", lambda: 501, raising=False)
    run = FakeRun({("lpinfo",): (0, LPINFO, ""),
                   ("sudo",): (0, "", "")})
    assert rmlspool.setup_mill_queue(run=run, say=lambda m: None) == "SRM-20"
    argvs = [c[0] for c in run.calls]
    assert argvs[1] == ["sudo", "lpadmin", "-p", "SRM-20", "-E", "-v",
                        "usb://Roland%20DG/SRM-20?serial=ZHA1234", "-m", "raw"]
    assert ["sudo", "cupsenable", "SRM-20"] in argvs
    assert ["sudo", "cupsaccept", "SRM-20"] in argvs


def test_setup_without_a_mill_says_so():
    run = FakeRun({("lpinfo",): (0, "network ipp\n", "")})
    with pytest.raises(SpoolError, match="switched on"):
        rmlspool.setup_mill_queue(run=run, say=lambda m: None)


@pytest.mark.parametrize("cups_up", [True, False])
def test_stop_purges_cups_then_still_aborts_over_the_arduino(monkeypatch,
                                                               cups_up):
    """STOP's order from engine/runner.py holds with CUPS: the queue is
    purged first, and the Arduino steps run even when CUPS is not answering -
    emptying a queue cannot recall bytes already in the mill's buffer."""
    from gerber2rml.engine import runner, spi_probe
    did = []
    for fn in ("stop_moving_now", "cancel_job", "spindle_off", "send_abort"):
        monkeypatch.setattr(spi_probe, fn,
                            lambda ser, fn=fn: did.append(fn))
    if cups_up:
        q = Queue([41])
    else:
        def q(argv, **kw):
            raise FileNotFoundError(argv[0])
    printer = CupsPrinter("SRM-20", run=q)
    runner.JobRunner(object(), printer, lambda: True).stop()
    if cups_up:
        assert q.calls[0] == ["cancel", "-a", "SRM-20"]
        assert q.jobs == []
    assert did == ["stop_moving_now", "cancel_job", "spindle_off",
                   "send_abort"]


def test_setup_from_the_app_asks_once_through_the_macos_dialog():
    """The app has no terminal: one osascript call, macOS's own password
    dialog, every admin step inside it."""
    run = FakeRun({("lpinfo",): (0, LPINFO, ""), ("osascript",): (0, "", "")})
    rmlspool.setup_mill_queue(run=run, say=lambda m: None, admin="gui")
    argvs = [c[0] for c in run.calls]
    assert argvs[0][:3] == ["lpinfo", "--include-schemes", "usb"]
    assert len(argvs) == 2 and argvs[1][:2] == ["osascript", "-e"]
    script = argvs[1][2]
    assert script.endswith("with administrator privileges")
    for step in ("lpadmin -p SRM-20 -E -v", "-m raw", "cupsenable SRM-20",
                 "cupsaccept SRM-20"):
        assert step in script


def test_a_cancelled_password_dialog_is_not_retried():
    run = FakeRun({("lpinfo",): (0, LPINFO, ""),
                   ("osascript",): (1, "", "execution error: User canceled. "
                                           "(-128)")})
    with pytest.raises(SpoolError, match="cancelled"):
        rmlspool.setup_mill_queue(run=run, say=lambda m: None, admin="gui")
    assert sum(c[0][0] == "osascript" for c in run.calls) == 1


def test_the_applescript_survives_quotes_in_the_uri():
    argv = rmlspool._applescript_admin([["lpadmin", "-v", 'usb://a"b\\c']])
    assert '\\"' in argv[2] and "\\\\" in argv[2]


def test_state_reads_a_stopped_queue():
    run = FakeRun({("lpstat", "-e"): (0, "SRM-20\n", ""),
                   ("lpoptions",): (0, "printer-is-accepting-jobs=true "
                                       "printer-state=5 "
                                       "printer-state-reasons=paused", "")})
    st = CupsPrinter("SRM-20", run=run).state()
    assert st == {"exists": True, "stopped": True, "accepting": True}


def test_state_of_a_missing_queue():
    run = FakeRun({("lpstat", "-e"): (0, "dummy\n", "")})
    assert CupsPrinter("SRM-20", run=run).state()["exists"] is False


def test_resume_enables_and_accepts():
    run = FakeRun({("osascript",): (0, "", "")})
    rmlspool.resume_queue(run=run, admin="gui")
    script = run.calls[0][0][2]
    assert "cupsenable SRM-20" in script and "cupsaccept SRM-20" in script


class _StuckQueue:
    """A queue that never empties: the mill is off."""
    name = "SRM-20"

    def send(self, data, name=""):
        return 1

    def pending(self):
        return 1

    def purge(self):
        return True


def test_a_job_stuck_in_the_queue_is_said_once(monkeypatch):
    from gerber2rml.engine import runner, spi_probe
    monkeypatch.setattr(spi_probe, "machine_status", lambda ser: {})
    monkeypatch.setattr(spi_probe, "query_position",
                        lambda ser: (1.0, 1.0, 5.0))
    for fn in ("stop_moving_now", "cancel_job", "spindle_off", "send_abort"):
        monkeypatch.setattr(spi_probe, fn, lambda ser: None)
    notes, polls = [], []

    def abort():
        polls.append(1)
        return len(polls) > 40
    r = runner.JobRunner(object(), _StuckQueue(), abort, note=notes.append,
                         poll_s=0.001, stall_s=0.01)
    with pytest.raises(runner.RunStopped):
        r.run("PU0,0;", "traces", end_mm=(50.0, 50.0))
    stuck = [n for n in notes if "print queue" in n]
    assert len(stuck) == 1 and "traces" in stuck[0]
