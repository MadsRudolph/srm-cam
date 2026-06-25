"""Bed-leveling test coupon: an 80 x 60 mm board with copper spread edge-to-edge.

A big-ish board whose copper reaches all four corners, the centre, and points in
between — so if the bed isn't flat, the isolation pass cuts to different depths
across it and the leveling compensation has something visible to correct.

- ``level-B_Cu.gbr``        — perimeter frame + centre cross + 6 pads on the holes
- ``level-Edge_Cuts.gbr``   — 80 x 60 outline
- ``level-F_Cu.gbr`` / masks / silk — empty stubs (single-sided)
- ``level.drl``             — 6 holes (3 x 2 grid), 0.8 mm

Entry point: :func:`write_coupon`.
"""

from __future__ import annotations

from pathlib import Path

from gerber2rml.examples.calibration import (
    _gbr_header, _aperture_block, _empty_gbr, _region, _rect_region, _circle_pts, _fmt,
)

BOARD_W = 80.0
BOARD_H = 60.0

# 6 holes on a 3 x 2 grid, well spread; each gets a round pad.
HOLES: list[tuple[float, float, float]] = [
    (x, y, 0.8) for y in (15.0, 45.0) for x in (20.0, 40.0, 60.0)
]
PAD_R = 2.0   # ⌀4 mm pads


def _build_edge_cuts() -> str:
    lines = [
        _gbr_header("Profile,NP"), _aperture_block(),
        f"X{_fmt(0)}Y{_fmt(0)}D02*",
        f"X{_fmt(BOARD_W)}Y{_fmt(0)}D01*",
        f"X{_fmt(BOARD_W)}Y{_fmt(BOARD_H)}D01*",
        f"X{_fmt(0)}Y{_fmt(BOARD_H)}D01*",
        f"X{_fmt(0)}Y{_fmt(0)}D01*",
        "M02*",
    ]
    return "\n".join(lines) + "\n"


def _build_bcu() -> str:
    regions = [
        # perimeter frame (4 bars, ~2 mm wide, inset 3 mm) — copper at every edge
        _rect_region(3.0, 3.0, 77.0, 5.0),     # bottom
        _rect_region(3.0, 55.0, 77.0, 57.0),   # top
        _rect_region(3.0, 3.0, 5.0, 57.0),     # left
        _rect_region(75.0, 3.0, 77.0, 57.0),   # right
        # centre cross — copper through the middle
        _rect_region(10.0, 29.0, 70.0, 31.0),  # horizontal
        _rect_region(39.0, 10.0, 41.0, 50.0),  # vertical
    ]
    regions += [_region(_circle_pts(hx, hy, PAD_R, 16)) for hx, hy, _d in HOLES]
    return _gbr_header("Copper,L2,Bot") + _aperture_block() + "\n".join(regions) + "\nM02*\n"


def _build_drill(holes) -> str:
    lines = ["M48", "METRIC", "T1C0.800", "%", "T1"]
    for x, y, _d in holes:
        lines.append(f"X{x}Y{y}")
    lines.append("M30")
    return "\n".join(lines) + "\n"


def write_coupon(out_dir: Path | str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "level-B_Cu.gbr").write_text(_build_bcu())
    (out_dir / "level-Edge_Cuts.gbr").write_text(_build_edge_cuts())
    (out_dir / "level.drl").write_text(_build_drill(HOLES))
    (out_dir / "level-F_Cu.gbr").write_text(_empty_gbr("Copper,L1,Top"))
    (out_dir / "level-F_Mask.gbr").write_text(_empty_gbr("Soldermask,Top"))
    (out_dir / "level-B_Mask.gbr").write_text(_empty_gbr("Soldermask,Bot"))
    (out_dir / "level-F_Silkscreen.gbr").write_text(_empty_gbr("Legend,Top"))
    return out_dir


if __name__ == "__main__":
    import sys
    dest = sys.argv[1] if len(sys.argv) > 1 else "examples/level_test"
    print("wrote coupon to", write_coupon(dest))
