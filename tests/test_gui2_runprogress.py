"""The automatic run's progress on the Run it page and the machine bar.

The arithmetic is runclock.py's and is tested there; this is that the page
shows it: a bar, the step in hand, the time left and the time of day, the
same on the machine bar, and a clock that stops while the run waits."""
from pathlib import Path

import pytest

from gerber2rml.engine import bracket as br
from gerber2rml.gui2.runclock import RunClock
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


class T:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def page(qt_app, monkeypatch, tmp_path):
    from gerber2rml import platform as plat
    monkeypatch.setattr(plat, "documents_dir", lambda *a, **k: tmp_path)
    monkeypatch.setattr(plat, "capabilities",
                        lambda p=None: plat.Capabilities(machine_link=True))
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.action_autorun(True)
    w.autorun_page.set_bracket(br.DEFAULT)
    w.load_folder(str(FIXT))
    w.select_step("autorun")
    yield w.autorun_page
    w.autorun_page._clock = None
    w.action_autorun(False)
    w.close()


def _clocked(page):
    t = T()
    page._clock = RunClock([("stock", "Find the stock", 40),
                            ("drill_run", "Drill", 200),
                            ("traces_run", "Isolation traces", 760)], now=t)
    return t


def test_every_step_of_the_plan_gets_an_estimate(page):
    from gerber2rml.gui2.autorun import WindowSource
    est = page._estimates(WindowSource(page.ctl, page._gui))
    assert [k for k, _l, _s in est] == [k for k, _l in page._plan_rows()]
    by = {k: s for k, _l, s in est}
    assert by["stock"] == 45.0
    assert all(s > 0 for k, s in by.items() if k != "flip")
    # A cutting step is timed from its own toolpaths, not a flat guess.
    cuts = [s for k, s in by.items() if k.endswith("_run")]
    assert cuts and len(set(round(s) for s in cuts)) > 1


def test_the_line_says_the_step_the_percent_and_the_time_left(page):
    t = _clocked(page)
    page._clock.step("stock", "running")
    t.t = 40; page._clock.step("stock", "done")
    page._clock.step("drill_run", "running")
    t.t = 140                                        # half of the drill
    page._tick()
    text = page.progress_lbl.text()
    assert "Step 2 of 3 · Drill" in text
    assert "14%" in text
    assert "about 14m 20s left" in text
    assert "done about " in text and "so far" in text
    assert page.progress.value() == 140


def test_the_machine_bar_says_it_too_while_the_run_holds_the_machine(page):
    bar = page.ctl.bar
    bar.set_held_by_run(True)
    t = _clocked(page)
    page._clock.step("stock", "running")
    t.t = 20
    page._tick()
    note = bar.offline_note.text()
    assert "Step 1 of 3 · Find the stock" in note and "left" in note
    assert "STOP or Esc stops it" in note
    bar.set_held_by_run(False)
    assert "Step 1 of 3" not in bar.offline_note.text()


def test_the_bar_is_left_alone_when_no_run_holds_the_machine(page):
    bar = page.ctl.bar
    before = bar.offline_note.text()
    _clocked(page)
    page._tick()
    assert bar.offline_note.text() == before


def test_waiting_at_the_flip_says_so_and_stops_the_clock(page):
    t = _clocked(page)
    page._clock.step("stock", "running")
    t.t = 20
    page._clock_wait(True)
    t.t = 620
    page._tick()
    assert "waiting for you" in page.progress_lbl.text()
    assert page.progress.value() == 20               # where it was
    page._clock_wait(False)
    page._tick()
    assert "waiting" not in page.progress_lbl.text()


def test_a_step_past_its_estimate_says_at_least(page):
    t = _clocked(page)
    page._clock.step("stock", "running")
    t.t = 400
    page._tick()
    assert "at least" in page.progress_lbl.text()
