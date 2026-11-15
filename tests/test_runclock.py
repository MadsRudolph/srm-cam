"""The automatic run's progress and time left (gui2/runclock.py)."""
import pytest

from gerber2rml.gui2.runclock import ALMOST, RunClock


class T:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _clock():
    t = T()
    c = RunClock([("stock", "Find the stock", 40),
                  ("drill", "Drill", 200),
                  ("traces", "Isolation traces", 760)], now=t)
    return c, t


def test_before_anything_runs_it_is_all_still_to_do():
    c, t = _clock()
    s = c.snapshot()
    assert s["fraction"] == 0.0 and s["left_s"] == 1000.0
    assert s["index"] == 0 and s["count"] == 3


def test_a_step_in_hand_counts_by_how_long_it_has_been_going():
    c, t = _clock()
    c.step("stock", "running")
    t.t += 20
    s = c.snapshot()
    assert s["fraction"] == pytest.approx(0.02)
    assert s["left_s"] == pytest.approx(980.0)
    assert (s["label"], s["index"]) == ("Find the stock", 1)


def test_a_finished_step_counts_whole_whatever_it_took():
    c, t = _clock()
    c.step("stock", "running"); t.t += 40; c.step("stock", "done")
    s = c.snapshot()
    assert s["fraction"] == pytest.approx(0.04)
    assert s["left_s"] == pytest.approx(960.0)


def test_it_learns_how_fast_the_mill_really_is():
    """The drill took twice its estimate: what is left is doubled too."""
    c, t = _clock()
    c.step("stock", "running"); t.t += 40; c.step("stock", "done")
    c.step("drill", "running"); t.t += 400; c.step("drill", "done")
    s = c.snapshot()
    assert s["fraction"] == pytest.approx(0.24)
    # stock (40 in 40) and drill (200 in 400): 440 taken for 240 estimated.
    assert s["left_s"] == pytest.approx(760 * 440 / 240)


def test_one_wild_step_cannot_run_away_with_the_estimate():
    c, t = _clock()
    c.step("drill", "running"); t.t += 5000; c.step("drill", "done")
    assert c.snapshot()["left_s"] == pytest.approx(800 * 3.0)


def test_a_step_past_its_estimate_holds_just_short_of_done():
    c, t = _clock()
    c.step("stock", "running")
    t.t += 500
    s = c.snapshot()
    assert s["over"] is True
    assert s["fraction"] == pytest.approx(40 * ALMOST / 1000)
    assert s["left_s"] > 960.0


def test_waiting_for_a_person_stops_the_clock():
    c, t = _clock()
    c.step("stock", "running"); t.t += 40; c.step("stock", "done")
    c.step("drill", "running"); t.t += 50
    before = c.snapshot()
    c.wait(True)
    t.t += 600                                  # ten minutes at the flip
    held = c.snapshot()
    assert held["waiting"] is True
    assert held["fraction"] == pytest.approx(before["fraction"])
    assert held["left_s"] == pytest.approx(before["left_s"])
    assert held["elapsed_s"] == pytest.approx(before["elapsed_s"])
    c.wait(False)
    t.t += 150; c.step("drill", "done")
    # 200 s of drilling, not 800: the wait is not the drill's.
    assert c.snapshot()["left_s"] == pytest.approx(760.0)


def test_skipped_steps_are_done_with():
    c, t = _clock()
    c.step("stock", "skipped"); c.step("drill", "skipped")
    assert c.snapshot()["fraction"] == pytest.approx(0.24)


def test_when_every_step_is_done_it_is_done():
    c, t = _clock()
    for k in ("stock", "drill", "traces"):
        c.step(k, "running"); t.t += 10; c.step(k, "done")
    s = c.snapshot()
    assert s["fraction"] == 1.0 and s["left_s"] == 0.0


def test_a_step_the_plan_did_not_list_changes_nothing():
    c, t = _clock()
    c.step("holes_again", "running")
    assert c.snapshot()["fraction"] == 0.0
