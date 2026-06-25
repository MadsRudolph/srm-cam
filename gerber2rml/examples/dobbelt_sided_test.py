"""Real double-sided PCB test board: 4 intricate traces, 12 holes (3 per trace).

A proper double-sided registration test — bigger and busier than the minimal
dowel coupon — so the flip really gets exercised:

- ``dstest-B_Cu.gbr``        — bottom copper: 2 serpentine traces + pads on ALL holes
- ``dstest-F_Cu.gbr``        — top copper: 2 serpentine traces + pads on ALL holes
                               + an asymmetric witness mark
- ``dstest-Edge_Cuts.gbr``   — board outline rectangle (50 x 40 mm)
- ``dstest-F_Mask.gbr`` / ``dstest-B_Mask.gbr`` / ``dstest-F_Silkscreen.gbr``
                               — empty layers gerbonara needs to identify the board
- ``dstest.drl``             — Excellon drill: 12 holes, T1 = 0.8 mm

Design intent
-------------
- **4 traces, 3 holes each (12 holes total).** Each trace is a serpentine
  (zig-zag) polyline threading its three holes, so the isolation pass is
  non-trivial on both sides — "intricate" by request.
- **Two traces on each side.** Traces A & C are on the bottom (B.Cu), B & D on
  the top (F.Cu). That forces a real isolation run on both layers.
- **Every hole is ringed on BOTH sides.** After the flip, the top ring should
  sit concentric with the bottom ring around the SAME drilled hole — hold it to
  a light and a registration error shows immediately at all 12 holes.
- **Asymmetric witness mark** near the top-left so any flip/mirror mistake
  displaces it visibly relative to the holes.

It's a *board* (a Gerber folder), so it loads in the GUI: place it on the bed,
turn on Double-sided, and export the registered job set (which adds the dowel
holes in the waste).

Entry point: :func:`write_coupon`. Reuses the Gerber/Excellon emitters from
:mod:`gerber2rml.examples.calibration` so the format stays identical.
"""

from __future__ import annotations

from pathlib import Path

from gerber2rml.examples.calibration import (
    _gbr_header,
    _region,
    _rect_region,
    _circle_pts,
    _empty_gbr,
    _fmt,
)

# Board: 50 x 40 mm — room for four serpentine lanes, still well inside the
# SRM-20 bed once the double-sided dowel waste is added around it.
BOARD_W = 50.0
BOARD_H = 40.0

TRACE_W = 1.0           # mm — stroked trace width
PAD_R = 1.6 / 2         # 0.8 mm radius ring on every hole, both sides
HOLE_D = 0.8            # mm — single drill bit does all 12

# Four lanes (one per trace) at these Y centres; three holes per lane at these
# X positions. side = which copper layer the lane's trace lives on.
_LANE_Y = (6.0, 15.0, 25.0, 34.0)
_HOLE_X = (8.0, 25.0, 42.0)
_LANE_SIDE = ("bottom", "top", "bottom", "top")   # A, B, C, D

# Serpentine shape between holes (within a lane band): amplitude and how many
# zig-zag points to drop between each pair of holes.
_AMP = 3.0
_BENDS = 4


def _holes() -> list[tuple[float, float, float]]:
    """All 12 drill holes, lane by lane (3 per lane)."""
    return [(x, cy, HOLE_D) for cy in _LANE_Y for x in _HOLE_X]


def _serpentine(cy: float) -> list[tuple[float, float]]:
    """A zig-zag polyline through the lane's three holes at y = ``cy``.

    Passes through each hole centre and bends ``_BENDS`` times between
    consecutive holes, alternating above/below the lane centre by ``_AMP``."""
    pts: list[tuple[float, float]] = [(_HOLE_X[0], cy)]
    for x0, x1 in zip(_HOLE_X, _HOLE_X[1:]):
        for k in range(1, _BENDS + 1):
            xk = x0 + (x1 - x0) * k / (_BENDS + 1)
            yk = cy + (_AMP if k % 2 else -_AMP)
            pts.append((xk, yk))
        pts.append((x1, cy))
    return pts


def _stroke(points: list[tuple[float, float]]) -> str:
    """Gerber stroke (D02 move, D01 draws) of an open polyline. Requires the
    trace aperture (D11) to be selected first — gerbonara reads these as Line
    objects, so the loader buffers them to ``TRACE_W`` wide copper."""
    x0, y0 = points[0]
    lines = [f"X{_fmt(x0)}Y{_fmt(y0)}D02*"]
    for x, y in points[1:]:
        lines.append(f"X{_fmt(x)}Y{_fmt(y)}D01*")
    return "\n".join(lines)


def _apertures() -> str:
    """D10 = 0.1 mm circle (region fills), D11 = trace-width circle (strokes)."""
    return (f"%ADD10C,0.100*%\n%ADD11C,{TRACE_W:.3f}*%\nD10*\n")


def _pads(holes: list[tuple[float, float, float]]) -> list[str]:
    """A round pad (12-gon, diameter 1.6 mm) on every hole."""
    return [_region(_circle_pts(hx, hy, PAD_R, 12)) for hx, hy, _d in holes]


def _build_copper(side: str, file_func: str, holes, witness: bool) -> str:
    """One copper layer: pads on all holes + the serpentine traces routed on
    this ``side`` + (optionally) the asymmetric witness mark."""
    body = list(_pads(holes))                      # rings on ALL 12 holes
    if witness:
        body.append(_rect_region(4.0, 35.5, 8.0, 38.0))   # asymmetric flip witness
    strokes = [_serpentine(cy)
               for cy, s in zip(_LANE_Y, _LANE_SIDE) if s == side]
    trace_block = ""
    if strokes:
        trace_block = "\nD11*\n" + "\n".join(_stroke(p) for p in strokes)
    return (_gbr_header(file_func) + _apertures()
            + "\n".join(body) + trace_block + "\nM02*\n")


def _build_edge_cuts() -> str:
    """Edge.Cuts: the board rectangle (0,0)-(BOARD_W, BOARD_H)."""
    lines = [
        _gbr_header("Profile,NP"),
        _apertures(),
        f"X{_fmt(0)}Y{_fmt(0)}D02*",
        f"X{_fmt(BOARD_W)}Y{_fmt(0)}D01*",
        f"X{_fmt(BOARD_W)}Y{_fmt(BOARD_H)}D01*",
        f"X{_fmt(0)}Y{_fmt(BOARD_H)}D01*",
        f"X{_fmt(0)}Y{_fmt(0)}D01*",
        "M02*",
    ]
    return "\n".join(lines) + "\n"


def _build_drill(holes: list[tuple[float, float, float]]) -> str:
    """Excellon drill: all 12 holes on a single T1 = 0.8 mm tool."""
    lines = ["M48", "METRIC", "T1C0.800", "%", "T1"]
    for x, y, _d in holes:
        lines.append(f"X{x}Y{y}")
    lines.append("M30")
    return "\n".join(lines) + "\n"


def write_coupon(out_dir: Path | str) -> Path:
    """Write the double-sided test board (Gerber folder) to *out_dir*."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    holes = _holes()

    (out_dir / "dstest-B_Cu.gbr").write_text(
        _build_copper("bottom", "Copper,L2,Bot", holes, witness=False))
    (out_dir / "dstest-F_Cu.gbr").write_text(
        _build_copper("top", "Copper,L1,Top", holes, witness=True))
    (out_dir / "dstest-Edge_Cuts.gbr").write_text(_build_edge_cuts())
    (out_dir / "dstest.drl").write_text(_build_drill(holes))

    (out_dir / "dstest-F_Mask.gbr").write_text(_empty_gbr("Soldermask,Top"))
    (out_dir / "dstest-B_Mask.gbr").write_text(_empty_gbr("Soldermask,Bot"))
    (out_dir / "dstest-F_Silkscreen.gbr").write_text(_empty_gbr("Legend,Top"))

    return out_dir


if __name__ == "__main__":
    import sys

    dest = sys.argv[1] if len(sys.argv) > 1 else "examples/Dobbelt_sided_TEST"
    print("wrote double-sided test board to", write_coupon(dest))
