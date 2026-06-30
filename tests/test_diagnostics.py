"""Tests for the pre-flight diagnostics."""
from gerber2rml.config import TraceJob, DrillJob, CutoutJob
from gerber2rml.engine.diagnostics import (
    cut_depths, preflight, worst, format_report, SRM20_Z_FLOOR,
)


def test_cut_depths_collects_all_ops():
    d = cut_depths(TraceJob(), DrillJob(), CutoutJob(), dowel_depth=6.6)
    assert d["traces"] == TraceJob().cut_depth
    assert d["drill"] == DrillJob().total_depth
    assert d["dowels"] == 6.6


def _depths(dowel=6.6):
    return cut_depths(TraceJob(), DrillJob(), CutoutJob(), dowel_depth=dowel)


def test_z_reach_fails_when_surface_too_low():
    # surface at -58 leaves 2.5 mm before the -60.5 floor; a 6.6 mm cut overruns
    checks = preflight(depths=_depths(), surface_z=-58.0)
    reach = [c for c in checks if "Z range" in c.title or "reach" in c.title.lower()][0]
    assert reach.level == "fail"
    assert "RAISE" in reach.detail and "4.6 mm" in reach.detail   # 6.6 - 2.5 + 0.5
    assert worst(checks) == "fail"


def test_z_reach_ok_when_surface_high():
    checks = preflight(depths=_depths(), surface_z=-50.0)
    assert worst(checks) == "ok"


def test_z_reach_unknown_without_probe_gives_required_surface():
    checks = preflight(depths=_depths(), surface_z=None)
    reach = [c for c in checks if c.level == "warn"][0]
    # surface must sit above floor + deepest + margin = -60.5 + 6.6 + 0.5 = -53.4
    assert "-53.4" in reach.detail


def test_bed_fit_fail_when_off_bed():
    checks = preflight(depths=_depths(), bed=(203.2, 152.4),
                       design_bounds=(0, 0, 210, 140), surface_z=-50.0)
    assert any(c.level == "fail" and "bed" in c.title.lower() for c in checks)


def test_holes_smaller_than_bit_warns():
    checks = preflight(depths=_depths(dowel=None), surface_z=-50.0,
                       holes=[(0, 0, 0.5)], bit_diameter=0.8)
    assert any(c.level == "warn" and "bit" in c.title.lower() for c in checks)


def test_format_report_is_ascii():
    report = format_report(preflight(depths=_depths(), surface_z=-58.0))
    assert report.isascii() and "[FAIL]" in report


# -- V-bit checks ----------------------------------------------------------

def test_cut_depths_uses_vbit_derived_depth():
    vbit = TraceJob(tool_type="vbit", tip_diameter=0.1, included_angle=30.0,
                    target_width=0.2)
    d = cut_depths(vbit, DrillJob(), CutoutJob())
    assert abs(d["traces"] - vbit.effective_cut_depth()) < 1e-9
    assert d["traces"] != vbit.cut_depth


def test_vbit_without_leveling_warns():
    vbit = TraceJob(tool_type="vbit")
    checks = preflight(depths=_depths(dowel=None), surface_z=-50.0,
                       trace=vbit, leveled=False)
    assert any(c.level == "warn" and "level" in c.title.lower() for c in checks)


def test_vbit_with_leveling_is_ok():
    vbit = TraceJob(tool_type="vbit")
    checks = preflight(depths=_depths(dowel=None), surface_z=-50.0,
                       trace=vbit, leveled=True)
    vbit_checks = [c for c in checks if "v-bit" in c.title.lower()]
    assert vbit_checks and all(c.level == "ok" for c in vbit_checks)


def test_flat_tool_adds_no_vbit_check():
    checks = preflight(depths=_depths(dowel=None), surface_z=-50.0,
                       trace=TraceJob(), leveled=False)
    assert not any("v-bit" in c.title.lower() for c in checks)
