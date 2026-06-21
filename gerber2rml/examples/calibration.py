"""Calibration coupon generator.

Emits three self-consistent Gerber/Excellon files describing a 40×30 mm PCB
calibration coupon:

- ``calib-B_Cu.gbr``         — bottom copper (trace-pair rectangles, round pads)
- ``calib-Edge_Cuts.gbr``    — board outline rectangle
- ``calib-F_Cu.gbr``         — empty top copper (required for gerbonara layer detection)
- ``calib-F_Mask.gbr``       — empty top soldermask (required for gerbonara)
- ``calib-B_Mask.gbr``       — empty bottom soldermask (required for gerbonara)
- ``calib-F_Silkscreen.gbr`` — empty top silk (required for gerbonara)
- ``calib.drl``              — Excellon drill file (8 holes, T1=0.8 mm, T2=1.0 mm)

Entry point: :func:`write_coupon`.
"""

from __future__ import annotations

import math
from pathlib import Path


# ---------------------------------------------------------------------------
# Gerber format helpers
# ---------------------------------------------------------------------------

def _fmt(mm: float) -> str:
    """Convert millimetres to 4.6 Gerber integer string (6 decimal places)."""
    return str(round(mm * 1_000_000))


def _circle_pts(cx: float, cy: float, r: float, n: int) -> list[tuple[float, float]]:
    """Return *n* equally-spaced points on a circle of radius *r* centred at (cx, cy)."""
    pts = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return pts


def _region(points: list[tuple[float, float]]) -> str:
    """Return a Gerber G36/G37 filled region for the given polygon vertices.

    The polygon is automatically closed (first vertex repeated at end).
    Requires an aperture already selected (e.g. ``D10*``).
    """
    lines = ["G36*"]
    x0, y0 = points[0]
    lines.append(f"X{_fmt(x0)}Y{_fmt(y0)}D02*")
    for x, y in points[1:]:
        lines.append(f"X{_fmt(x)}Y{_fmt(y)}D01*")
    # Close the polygon back to the first point
    lines.append(f"X{_fmt(x0)}Y{_fmt(y0)}D01*")
    lines.append("G37*")
    return "\n".join(lines)


def _rect_region(x0: float, y0: float, x1: float, y1: float) -> str:
    """Filled rectangle region from (x0,y0) to (x1,y1) as a G36/G37 block."""
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return _region(pts)


# ---------------------------------------------------------------------------
# Gerber file builders
# ---------------------------------------------------------------------------

def _gbr_header(file_func: str, pol: str = "Positive") -> str:
    return (
        f"%TF.FileFunction,{file_func}*%\n"
        f"%TF.FilePolarity,{pol}*%\n"
        "%FSLAX46Y46*%\n"
        "G04 Gerber Fmt 4.6, Leading zero omitted, Abs format (unit mm)*\n"
        "%MOMM*%\n"
        "%LPD*%\n"
        "G01*\n"
    )


def _aperture_block() -> str:
    """Define and select a single 0.1 mm circle aperture (D10)."""
    return "%ADD10C,0.100*%\nD10*\n"


def _empty_gbr(file_func: str) -> str:
    """Minimal valid Gerber — header only, no objects."""
    return _gbr_header(file_func) + _aperture_block() + "M02*\n"


def _build_edge_cuts() -> str:
    """Edge.Cuts Gerber: rectangle (0,0)–(40,30) as 4 line segments."""
    lines = [
        _gbr_header("Profile,NP"),
        _aperture_block(),
        # Draw four sides
        f"X{_fmt(0)}Y{_fmt(0)}D02*",
        f"X{_fmt(40)}Y{_fmt(0)}D01*",
        f"X{_fmt(40)}Y{_fmt(30)}D01*",
        f"X{_fmt(0)}Y{_fmt(30)}D01*",
        f"X{_fmt(0)}Y{_fmt(0)}D01*",
        "M02*",
    ]
    return "\n".join(lines) + "\n"


def _build_bcu(holes: list[tuple[float, float, float]]) -> str:
    """B.Cu Gerber: isolation trace-pairs, pad circles on every drill, roundness pad."""
    regions: list[str] = []

    # --- Isolation trace-pairs ---
    # Three pairs, each = two 1.0 mm wide × 12 mm tall rectangles separated by 0.8 mm gap.
    # Pair centres at x≈4, x≈12, x≈20; y span 14..26
    trace_w = 1.0
    gap = 0.8
    y0_trace, y1_trace = 14.0, 26.0
    for cx in (4.0, 12.0, 20.0):
        # Left member: [cx - gap/2 - trace_w, cx - gap/2]
        lx0 = cx - gap / 2 - trace_w
        lx1 = cx - gap / 2
        regions.append(_rect_region(lx0, y0_trace, lx1, y1_trace))
        # Right member: [cx + gap/2, cx + gap/2 + trace_w]
        rx0 = cx + gap / 2
        rx1 = cx + gap / 2 + trace_w
        regions.append(_rect_region(rx0, y0_trace, rx1, y1_trace))

    # --- Round pads on every drill hole (12-gon, ⌀1.6 mm) ---
    pad_r = 1.6 / 2  # 0.8 mm radius
    for hx, hy, _diam in holes:
        pts = _circle_pts(hx, hy, pad_r, 12)
        regions.append(_region(pts))

    # --- Roundness ring at (33, 22): ⌀6 mm filled 24-gon ---
    ring_pts = _circle_pts(33.0, 22.0, 3.0, 24)
    regions.append(_region(ring_pts))

    body = "\n".join(regions)
    return _gbr_header("Copper,L2,Bot") + _aperture_block() + body + "\nM02*\n"


# ---------------------------------------------------------------------------
# Drill file builder
# ---------------------------------------------------------------------------

def _build_drill(holes: list[tuple[float, float, float]]) -> str:
    """Excellon drill file for the given holes.

    Splits hits by diameter into T1 (0.8 mm) and T2 (1.0 mm) sections.
    Uses decimal metric coordinates (KiCad style).
    """
    t1 = [(x, y) for x, y, d in holes if round(d, 1) == 0.8]
    t2 = [(x, y) for x, y, d in holes if round(d, 1) == 1.0]

    lines = [
        "M48",
        "METRIC",
        "T1C0.800",
        "T2C1.000",
        "%",
        "T1",
    ]
    for x, y in t1:
        lines.append(f"X{x}Y{y}")
    lines.append("T2")
    for x, y in t2:
        lines.append(f"X{x}Y{y}")
    lines.append("M30")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_coupon(out_dir: Path | str) -> Path:
    """Write calibration coupon Gerber + Excellon files to *out_dir*.

    Creates:
    - ``calib-B_Cu.gbr``         — bottom copper
    - ``calib-Edge_Cuts.gbr``    — board outline
    - ``calib-F_Cu.gbr``         — empty top copper (needed for layer detection)
    - ``calib-F_Mask.gbr``       — empty top soldermask
    - ``calib-B_Mask.gbr``       — empty bottom soldermask
    - ``calib-F_Silkscreen.gbr`` — empty top silk
    - ``calib.drl``              — Excellon drill file

    Parameters
    ----------
    out_dir:
        Destination directory (created if absent).

    Returns
    -------
    Path
        The resolved output directory.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build the hole list ONCE — reused for both the drill file and pad placement.
    holes: list[tuple[float, float, float]] = [
        # Drill-size test row
        (10.0, 6.0, 0.8),   # T1 test hole
        (14.0, 6.0, 1.0),   # T2 test hole
        # 10 mm registration grid (all T1 = 0.8 mm)
        (10.0, 10.0, 0.8),
        (20.0, 10.0, 0.8),
        (30.0, 10.0, 0.8),
        (10.0, 20.0, 0.8),
        (20.0, 20.0, 0.8),
        (30.0, 20.0, 0.8),
    ]
    # Totals: 7 × T1 (0.8 mm) + 1 × T2 (1.0 mm) = 8 holes

    # Write the three primary files
    (out_dir / "calib-B_Cu.gbr").write_text(_build_bcu(holes))
    (out_dir / "calib-Edge_Cuts.gbr").write_text(_build_edge_cuts())
    (out_dir / "calib.drl").write_text(_build_drill(holes))

    # Write dummy layers so gerbonara LayerStack.open() can identify the board
    # (it requires at least 6 Gerber files in the standard KiCad layer set).
    (out_dir / "calib-F_Cu.gbr").write_text(_empty_gbr("Copper,L1,Top"))
    (out_dir / "calib-F_Mask.gbr").write_text(_empty_gbr("Soldermask,Top"))
    (out_dir / "calib-B_Mask.gbr").write_text(_empty_gbr("Soldermask,Bot"))
    (out_dir / "calib-F_Silkscreen.gbr").write_text(_empty_gbr("Legend,Top"))

    return out_dir
