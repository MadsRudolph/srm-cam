"""How far the automatic run has got, and when it will be done.

The run is a checklist: find the stock, probe, drill, cut, flip, cut. A
checklist says what is finished and nothing about how long the rest takes -
and "how long" is the first thing anyone standing at a mill for forty
minutes wants to know. This is the arithmetic behind the bar on the Run it
page: each step has an estimate, the clock knows which have finished and how
long the one in hand has been going, and from that it says a fraction and a
time left.

Two things keep it honest:

* **It learns.** Estimates are made from the planned feeds, and a mill is
  never quite that fast. Once a step has finished, the ratio of what it took
  to what was estimated is applied to everything still to come, so the time
  left settles towards the truth as the run goes on rather than staying
  wrong by the same factor to the end.
* **It stops when the machine does.** At the flip, and at the check before
  the cut-out, the run waits for a person. That time is not the run's, and a
  clock that kept counting through it would promise an end that moves away
  for as long as nobody presses Continue.

No Qt, no machine: steps in, events in, a snapshot out.
"""
import time

# A running step is never shown as finished: it is finished when the run
# says so. Short of that, a step that overruns its estimate holds here.
ALMOST = 0.97
# The learnt speed is kept inside these, so that one odd step - a probe that
# had to step aside ten times - cannot make the rest look eight times longer.
SLOWEST, FASTEST = 3.0, 0.5
# Steps too short to learn from: their time is mostly start-up.
LEARN_FROM_S = 20.0


class RunClock:
    """``steps`` is ``[(key, label, estimate_s), ...]`` in run order."""

    def __init__(self, steps, now=time.monotonic):
        self._now = now
        self.steps = [{"key": k, "label": lab, "est": max(0.0, float(est)),
                       "state": "pending", "t0": None, "took": None}
                      for k, lab, est in steps]
        self._start = now()
        self._waiting_since = None
        self._waited = 0.0

    def _find(self, key):
        return next((s for s in self.steps if s["key"] == key), None)

    def step(self, key, state):
        """The run's own event: ``state`` is "running", "done", "failed" or
        "skipped". A key the plan did not list is ignored."""
        s = self._find(key)
        if s is None:
            return
        t = self._now()
        if state == "running":
            s["state"], s["t0"] = "running", t
            return
        if s["state"] == "running" and s["t0"] is not None:
            s["took"] = max(0.0, t - s["t0"] - self._wait_inside(s))
        s["state"] = state

    def _wait_inside(self, s):
        return s.get("waited", 0.0)

    def wait(self, on):
        """The run is waiting for a person (the flip, the check), or no
        longer is. Time spent waiting is nobody's estimate."""
        t = self._now()
        if on and self._waiting_since is None:
            self._waiting_since = t
        elif not on and self._waiting_since is not None:
            d = t - self._waiting_since
            self._waiting_since = None
            self._waited += d
            for s in self.steps:
                if s["state"] == "running":
                    s["waited"] = s.get("waited", 0.0) + d

    def waiting(self):
        return self._waiting_since is not None

    def _ratio(self):
        est = took = 0.0
        for s in self.steps:
            if (s["state"] == "done" and s["took"] is not None
                    and s["est"] >= LEARN_FROM_S):
                est += s["est"]
                took += s["took"]
        if est <= 0.0:
            return 1.0
        return max(FASTEST, min(SLOWEST, took / est))

    def snapshot(self):
        """``{"fraction", "left_s", "elapsed_s", "label", "index", "count",
        "waiting", "over"}``. ``index`` is the 1-based number of the step in
        hand (or the last one finished); ``over`` says the step in hand has
        run past its estimate, so the time left is a floor, not a guess."""
        t = self._now()
        paused = (t - self._waiting_since) if self._waiting_since else 0.0
        ratio = self._ratio()
        total = sum(s["est"] for s in self.steps)
        done = 0.0
        label, index, over = "", 0, False
        for i, s in enumerate(self.steps, 1):
            if s["state"] in ("done", "skipped", "failed"):
                done += s["est"]
                index = max(index, i)
            elif s["state"] == "running":
                going = max(0.0, t - s["t0"] - s.get("waited", 0.0) - paused)
                want = s["est"] * ratio
                part = ALMOST if want <= 0 else min(going / want, ALMOST)
                over = want > 0 and going > want
                done += s["est"] * part
                label, index = s["label"], i
        if not label and index:
            label = self.steps[index - 1]["label"]
        fraction = 1.0 if total <= 0 else max(0.0, min(1.0, done / total))
        return {"fraction": fraction,
                "left_s": max(0.0, (total - done) * ratio),
                "elapsed_s": max(0.0, t - self._start - self._waited - paused),
                "label": label, "index": index, "count": len(self.steps),
                "waiting": self.waiting(), "over": over}
