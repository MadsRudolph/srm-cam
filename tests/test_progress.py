"""Live run-progress tracking from a (simulated) DRO position."""
from gerber2rml.toolpath import Move
from gerber2rml.engine.progress import RunProgress
from gerber2rml.engine.estimate import estimate_toolpaths_seconds


def _line(pts, z=-0.15):
    return [Move(pts[0][0], pts[0][1], 2.0, rapid=True)] + \
           [Move(x, y, z) for (x, y) in pts]


def test_total_matches_the_planner_estimate():
    tp = _line([(0, 0), (10, 0), (10, 10)])
    rp = RunProgress([tp], xy_feed=4.0, plunge_feed=1.0)
    est = estimate_toolpaths_seconds([tp], 4.0, 1.0)
    # progress omits the (0,0,0)->start phantom move; otherwise identical timing
    assert rp.total > 0 and abs(rp.total - est) < 0.5


def test_progress_advances_along_the_path():
    tp = _line([(0, 0), (10, 0), (20, 0)])      # 20 mm cut at 4 mm/s
    rp = RunProgress([tp], xy_feed=4.0, plunge_feed=1.0)
    f0, e0, r0 = rp.update(0.0, 0.0, -0.15)     # at the start
    f_mid, _, r_mid = rp.update(10.0, 0.0, -0.15)
    f1, _, r1 = rp.update(20.0, 0.0, -0.15)     # at the end
    assert f0 < f_mid < f1
    assert abs(f1 - 1.0) < 1e-6 and r1 < 1e-6   # finished
    assert r0 > r_mid > r1                       # remaining counts down


def test_progress_is_forward_only():
    tp = _line([(0, 0), (10, 0), (20, 0)])
    rp = RunProgress([tp], xy_feed=4.0, plunge_feed=1.0)
    rp.update(20.0, 0.0, -0.15)                  # jump to the end
    f_back, _, _ = rp.update(5.0, 0.0, -0.15)    # a rapid back over cut copper
    assert abs(f_back - 1.0) < 1e-6              # bar stays at 100%, not rewound


def test_latches_on_when_armed_mid_run():
    tp = _line([(x, 0) for x in range(0, 41)])   # many vertices, 40 mm long
    rp = RunProgress([tp], xy_feed=4.0, plunge_feed=1.0)
    f, _, _ = rp.update(30.0, 0.0, -0.15)        # first read is already 3/4 in
    assert 0.6 < f < 0.9                          # found its place, not stuck at 0


def test_empty_job_is_safe():
    rp = RunProgress([], xy_feed=4.0, plunge_feed=1.0)
    assert rp.total == 0.0
    assert rp.update(1.0, 2.0, 3.0) == (1.0, 0.0, 0.0)
