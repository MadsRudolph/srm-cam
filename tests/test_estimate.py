"""Tests for the run-time estimator."""
from gerber2rml.toolpath import Move
from gerber2rml.engine.estimate import (
    estimate_toolpaths_seconds, estimate_nc_seconds, estimate_file_seconds,
    format_duration,
)


def test_toolpaths_feed_and_rapid():
    # 10 mm cut at 4 mm/s = 2.5 s; then 6 mm rapid at 15 mm/s = 0.4 s
    tp = [[Move(10.0, 0.0, 0.0, rapid=False), Move(16.0, 0.0, 0.0, rapid=True)]]
    s = estimate_toolpaths_seconds(tp, xy_feed=4.0, plunge_feed=1.0, rapid_feed=15.0)
    assert abs(s - (2.5 + 0.4)) < 1e-6


def test_toolpaths_plunge_uses_plunge_feed():
    # straight down 2 mm at plunge feed 1 mm/s = 2 s (not the xy feed)
    tp = [[Move(0.0, 0.0, -2.0, rapid=False)]]
    s = estimate_toolpaths_seconds(tp, xy_feed=4.0, plunge_feed=1.0)
    assert abs(s - 2.0) < 1e-6


def test_nc_uses_modal_feed_in_mm_per_min():
    # 100 mm at F240 (= 4 mm/s) = 25 s; + 60 mm rapid at 15 mm/s = 4 s
    nc = "G90\nG1 X100 F240\nG0 X160\n"
    assert abs(estimate_nc_seconds(nc) - 29.0) < 1e-6


def test_nc_skips_homing():
    nc = "G90\nG28 Z0.\nG1 X100 F240\n"     # homing must not count as a cut move
    assert abs(estimate_nc_seconds(nc) - 25.0) < 1e-6


def test_file_estimate_only_for_nc(tmp_path):
    p = tmp_path / "j.nc"
    p.write_text("G90\nG1 X100 F240\n")
    assert abs(estimate_file_seconds(p) - 25.0) < 1e-6
    txt = tmp_path / "runplan.txt"
    txt.write_text("not gcode")
    assert estimate_file_seconds(txt) is None      # non-.nc -> None


def test_format_duration():
    assert format_duration(5) == "5s"
    assert format_duration(85) == "1m 25s"
    assert format_duration(3920) == "1h 05m"
