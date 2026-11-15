"""The Mac's print-queue checks before a run (gui2/macmill.py).

A paused queue would swallow the job; old jobs would cut before this one.
The run must not start until both are settled. No real CUPS, no dialogs."""
import pytest

from gerber2rml.engine import rmlspool
from gerber2rml.gui2 import macmill


class Printer:
    name = "SRM-20"

    def __init__(self, stopped=False, jobs=0, purge_ok=True):
        self.stopped, self.jobs, self.purge_ok = stopped, jobs, purge_ok
        self.purged = False

    def state(self):
        return {"exists": True, "stopped": self.stopped, "accepting": True}

    def pending(self):
        return self.jobs

    def purge(self):
        self.purged = True
        if self.purge_ok:
            self.jobs = 0
        return self.purge_ok


@pytest.fixture
def answers(monkeypatch, qt_app):
    said = {"asked": [], "errors": [], "resumed": [], "yes": True}
    monkeypatch.setattr(macmill, "_ask", lambda parent, head, text, go:
                        said["asked"].append(head) or said["yes"])
    monkeypatch.setattr(macmill.dialogs, "report_error",
                        lambda *a, **k: said["errors"].append(a[1]))
    monkeypatch.setattr(rmlspool, "resume_queue",
                        lambda name, run=None, admin="sudo":
                        said["resumed"].append((name, admin)))
    return said


def test_a_clean_queue_goes_ahead_without_a_word(answers):
    assert macmill.preflight(None, Printer()) is True
    assert answers["asked"] == []


def test_a_paused_queue_is_resumed_through_the_password_dialog(answers):
    assert macmill.preflight(None, Printer(stopped=True)) is True
    assert answers["resumed"] == [("SRM-20", "gui")]


def test_a_paused_queue_left_paused_stops_the_run(answers):
    answers["yes"] = False
    assert macmill.preflight(None, Printer(stopped=True)) is False
    assert answers["resumed"] == []


def test_old_jobs_are_cleared_before_the_run(answers):
    p = Printer(jobs=2)
    assert macmill.preflight(None, p) is True
    assert p.purged and p.jobs == 0


def test_old_jobs_kept_stop_the_run(answers):
    answers["yes"] = False
    p = Printer(jobs=2)
    assert macmill.preflight(None, p) is False
    assert not p.purged


def test_old_jobs_that_will_not_clear_stop_the_run(answers):
    assert macmill.preflight(None, Printer(jobs=1, purge_ok=False)) is False
    assert answers["errors"]
