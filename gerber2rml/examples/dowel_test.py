"""Minimal double-sided dowel-registration test coupon.

The smallest board that still exercises the whole double-sided flow:

- ``dowel-B_Cu.gbr``         — bottom copper: **2 traces** + round pads on holes
- ``dowel-F_Cu.gbr``         — top copper: round pads on holes + an asymmetric
                               witness mark (so a flip/registration error shows)
- ``dowel-Edge_Cuts.gbr``    — board outline rectangle
- ``dowel-F_Mask.gbr``       — empty top soldermask (gerbonara needs the layer)
- ``dowel-B_Mask.gbr``       — empty bottom soldermask
- ``dowel-F_Silkscreen.gbr`` — empty top silk
- ``dowel.drl``              — Excellon drill: **4 holes**, T1 = 0.8 mm

Why these features: the 4 holes are drilled bottom-up, the board flips on the
two dowel pins, then the top pads should ring the SAME four holes and the
asymmetric mark should land where the preview says. If the dowels register, the
rings line up under a light; if not, the error is obvious. The 2 traces just
prove the isolation pass on both sides registers to the holes too.

This is a *board* (a gerber folder), not raw gcode, so it loads in the GUI: you
can drag it onto the bed to dial in the X/Y placement, then export the
double-sided jobs (which adds the dowel/align holes in the waste).

Entry point: :func:`write_coupon`. Reuses the Gerber/Excellon emitters from
:mod:`gerber2rml.examples.calibration` so the format stays identical.
"""

from __future__ import annotations

from pathlib import Path

from gerber2rml.examples.calibration import (
    _gbr_header,
    _aperture_block,
    _empty_gbr,
    _region,
    _rect_region,
    _circle_pts,
    _fmt,
)

# Board: 24 x 18 mm. Small, but leaves room for the 4-hole witness grid and
# keeps the whole job (board + dowel waste) well inside the SRM-20 bed.
BOARD_W = 24.0
BOARD_H = 18.0

# Four through-holes on a 12 x 8 mm centred rectangle. All 0.8 mm so a single
# drill bit does the lot. Placed symmetric in X (so they survive the flip onto
# the same pins) but the COPPER around them is keyed asymmetric (below).
HOLES: list[tuple[float, float, float]] = [
    (6.0, 5.0, 0.8),
    (18.0, 5.0, 0.8),
    (6.0, 13.0, 0.8),
    (18.0, 13.0, 0.8),
]

PAD_R = 1.6 / 2          # 0.8 mm radius ring on every hole, both sides
TRACE_W = 1.0            # mm — the two isolation-routed traces


def _build_edge_cuts() -> str:
    """Edge.Cuts: the board rectangle (0,0)-(BOARD_W,BOARD_H)."""
    lines = [
        _gbr_header("Profile,NP"),
        _aperture_block(),
        f"X{_fmt(0)}Y{_fmt(0)}D02*",
        f"X{_fmt(BOARD_W)}Y{_fmt(0)}D01*",
        f"X{_fmt(BOARD_W)}Y{_fmt(BOARD_H)}D01*",
        f"X{_fmt(0)}Y{_fmt(BOARD_H)}D01*",
        f"X{_fmt(0)}Y{_fmt(0)}D01*",
        "M02*",
    ]
    return "\n".join(lines) + "\n"


def _pads(holes: list[tuple[float, float, float]]) -> list[str]:
    """A ⌀1.6 mm round pad (12-gon) on every drill hole."""
    return [_region(_circle_pts(hx, hy, PAD_R, 12)) for hx, hy, _d in holes]


def _build_bcu() -> str:
    """B.Cu: 2 horizontal traces joining the hole rows + pads on all 4 holes."""
    regions: list[str] = []
    # Trace 1: bottom row, y = 5, x = 6..18 (joins the two lower holes).
    regions.append(_rect_region(6.0, 5.0 - TRACE_W / 2, 18.0, 5.0 + TRACE_W / 2))
    # Trace 2: top row, y = 13, x = 6..18 (joins the two upper holes).
    regions.append(_rect_region(6.0, 13.0 - TRACE_W / 2, 18.0, 13.0 + TRACE_W / 2))
    regions += _pads(HOLES)
    body = "\n".join(regions)
    return _gbr_header("Copper,L2,Bot") + _aperture_block() + body + "\nM02*\n"


def _build_fcu() -> str:
    """F.Cu: pads on all 4 holes + an asymmetric witness mark.

    The 3 x 1.5 mm mark sits near the top-left corner, off every board axis, so
    any flip or registration error displaces it visibly relative to the holes.
    """
    regions = _pads(HOLES)
    regions.append(_rect_region(3.0, 14.5, 6.0, 16.0))   # asymmetric flip witness
    body = "\n".join(regions)
    return _gbr_header("Copper,L1,Top") + _aperture_block() + body + "\nM02*\n"


def _build_drill(holes: list[tuple[float, float, float]]) -> str:
    """Excellon drill: all 4 holes on a single T1 = 0.8 mm tool."""
    lines = ["M48", "METRIC", "T1C0.800", "%", "T1"]
    for x, y, _d in holes:
        lines.append(f"X{x}Y{y}")
    lines.append("M30")
    return "\n".join(lines) + "\n"


def write_coupon(out_dir: Path | str) -> Path:
    """Write the dowel-test coupon (gerber folder) to *out_dir*.

    Returns the resolved output directory.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "dowel-B_Cu.gbr").write_text(_build_bcu())
    (out_dir / "dowel-F_Cu.gbr").write_text(_build_fcu())
    (out_dir / "dowel-Edge_Cuts.gbr").write_text(_build_edge_cuts())
    (out_dir / "dowel.drl").write_text(_build_drill(HOLES))

    (out_dir / "dowel-F_Mask.gbr").write_text(_empty_gbr("Soldermask,Top"))
    (out_dir / "dowel-B_Mask.gbr").write_text(_empty_gbr("Soldermask,Bot"))
    (out_dir / "dowel-F_Silkscreen.gbr").write_text(_empty_gbr("Legend,Top"))

    return out_dir


if __name__ == "__main__":
    import sys

    dest = sys.argv[1] if len(sys.argv) > 1 else "examples/dowel_test"
    print("wrote coupon to", write_coupon(dest))
