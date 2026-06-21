"""Tests for select_drill_holes — Task D1: robust drill-file loading."""
from gerber2rml.loader import select_drill_holes
from shapely.geometry import box


def _excellon(path, holes):
    lines = ["M48", "METRIC", "T1C0.800", "%", "T1"]
    for (x, y) in holes:
        lines.append(f"X{x:.3f}Y{y:.3f}")
    lines.append("M30")
    path.write_text("\n".join(lines) + "\n")


def test_prefers_split_over_combined(tmp_path):
    _excellon(tmp_path / "b.drl", [(5, 5), (200, 200)])
    _excellon(tmp_path / "b-PTH.drl", [(5, 5)])
    _excellon(tmp_path / "b-NPTH.drl", [])
    holes = select_drill_holes(tmp_path, outline=box(0, 0, 40, 40))
    assert len(holes) == 1
    assert abs(holes[0][0] - 5) < 1e-6


def test_filters_outside_outline_and_dedupes(tmp_path):
    _excellon(tmp_path / "only.drl", [(5, 5), (5, 5), (100, 100)])
    holes = select_drill_holes(tmp_path, outline=box(0, 0, 40, 40))
    assert len(holes) == 1
