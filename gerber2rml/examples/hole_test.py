"""Dowel-pin fit-test coupon: a drill gerber with two rows of swept diameters.

Load this folder in the GUI, place it on the bed, and export the drill job
(single-bit / interpolate mode, ~6 mm deep). Try the metal pins in each milled
hole; whichever grips snugly tells you the exact ``pin_clearance`` to use. The
holes carry their COMMANDED diameters in the Excellon file, milled by the same
single-bit interpolation as the real dowel holes, so the kerf behaviour matches.

Layout (looking at the bed, +Y away from you):

    TOP row    (larger Y)  -> SMALL pin (1.9 mm)
    BOTTOM row (smaller Y) -> BIG   pin (3.1 mm)

Within each row, hole 1 is leftmost (smallest) and hole N rightmost (largest).
Both rows sweep the SAME ``pin_clearance`` values, so the snug hole's clearance
applies to both pins (and confirms the kerf is the same at both diameters).

A hole's COMMANDED diameter = pin + clearance; on this SRM-20 the milled hole
comes out ~0.4 mm under that (see memory: srm20-interpolated-hole-undersize),
so e.g. clearance 0.4 on the 1.9 mm pin -> 2.3 mm commanded -> ~1.9 mm measured.

Files written (a standard gerber folder so gerbonara loads it):

- ``hole_test-Edge_Cuts.gbr``   — outline enclosing both rows
- ``hole_test-B_Cu.gbr``        — a ring pad on every hole (so it previews)
- ``hole_test-F_Cu.gbr``        — empty top copper
- ``hole_test-F_Mask.gbr`` / ``-B_Mask.gbr`` / ``-F_Silkscreen.gbr`` — empty
- ``hole_test.drl``             — the 18 holes at their swept diameters
- ``hole_test_legend.txt``      — which hole is which clearance

Entry point: :func:`write_hole_test`.
"""

from __future__ import annotations

from pathlib import Path

from gerber2rml.examples.calibration import (
    _gbr_header, _aperture_block, _empty_gbr, _region, _circle_pts, _fmt,
)
from gerber2rml.doublesided import PIN_LARGE, PIN_SMALL

# Clearance sweep (mm added to the pin diameter). 0.40 is the current default, so
# it sits mid-row and you can see whether the snug fit lands left (tighter) or
# right (looser) of it.
CLEAR_START = 0.20
CLEAR_STEP = 0.05
CLEAR_N = 9                      # 0.20 .. 0.60

UNDERSIZE = 0.4                  # measured kerf: commanded - measured
PITCH = 7.0                     # mm between hole centres (clears the 3.7 mm holes)
MARGIN = 8.0                    # mm from the board edge to the first hole centre
ROW_GAP = 16.0                  # mm between the two rows


def _clearances() -> list[float]:
    return [round(CLEAR_START + i * CLEAR_STEP, 3) for i in range(CLEAR_N)]


def _rows():
    """Yield (label, pin, y) for the bottom (big) then top (small) rows."""
    yield "BIG", PIN_LARGE, MARGIN                 # bottom row, smaller Y
    yield "SMALL", PIN_SMALL, MARGIN + ROW_GAP     # top row, larger Y


def _holes_and_legend():
    holes: list[tuple[float, float, float]] = []
    legend = []
    for row_name, pin, y in _rows():
        for i, clr in enumerate(_clearances()):
            x = MARGIN + i * PITCH
            commanded = round(pin + clr, 3)
            holes.append((x, y, commanded))
            legend.append((row_name, pin, i + 1, x, y, clr, commanded,
                           round(commanded - UNDERSIZE, 3)))
    return holes, legend


# Board outline: enclose both rows with MARGIN clearance all round.
BOARD_W = MARGIN + (CLEAR_N - 1) * PITCH + MARGIN
BOARD_H = MARGIN + ROW_GAP + MARGIN


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


def _build_bcu(holes) -> str:
    """A ring pad (hole radius + 0.5 mm) on every hole, so the coupon previews
    and the holes are visible where they'll be drilled."""
    regions = [_region(_circle_pts(hx, hy, d / 2 + 0.5, 16)) for hx, hy, d in holes]
    return _gbr_header("Copper,L2,Bot") + _aperture_block() + "\n".join(regions) + "\nM02*\n"


def _build_drill(holes) -> str:
    """Excellon drill: one tool per distinct diameter, hits grouped under it."""
    dias = sorted({round(d, 3) for _x, _y, d in holes})
    lines = ["M48", "METRIC"]
    tool_of = {}
    for i, d in enumerate(dias, start=1):
        tool_of[d] = f"T{i}"
        lines.append(f"T{i}C{d:.3f}")
    lines.append("%")
    for d in dias:
        lines.append(tool_of[d])
        for x, y, hd in holes:
            if round(hd, 3) == d:
                lines.append(f"X{x}Y{y}")
    lines.append("M30")
    return "\n".join(lines) + "\n"


def write_hole_test(out_dir: Path | str, name: str = "hole_test") -> Path:
    """Write the fit-test drill gerber folder + legend. Returns the folder."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    holes, legend = _holes_and_legend()

    (out_dir / f"{name}-Edge_Cuts.gbr").write_text(_build_edge_cuts())
    (out_dir / f"{name}-B_Cu.gbr").write_text(_build_bcu(holes))
    (out_dir / f"{name}-F_Cu.gbr").write_text(_empty_gbr("Copper,L1,Top"))
    (out_dir / f"{name}-F_Mask.gbr").write_text(_empty_gbr("Soldermask,Top"))
    (out_dir / f"{name}-B_Mask.gbr").write_text(_empty_gbr("Soldermask,Bot"))
    (out_dir / f"{name}-F_Silkscreen.gbr").write_text(_empty_gbr("Legend,Top"))
    (out_dir / f"{name}.drl").write_text(_build_drill(holes))
    (out_dir / f"{name}_legend.txt").write_text(
        _legend_text(name, legend), encoding="utf-8")
    return out_dir


def _legend_text(name, rows) -> str:
    head = (
        f"DOWEL-PIN FIT TEST: {name}  (drill gerber)\n\n"
        f"Load the folder in the GUI, place it, export the DRILL job in single-bit\n"
        f"(interpolate) mode ~6 mm deep. Try each pin in its row; the hole that\n"
        f"grips snugly gives the pin_clearance to set.\n\n"
        f"  TOP row    (larger Y, {rows[CLEAR_N][4]:.0f} mm) -> SMALL pin {PIN_SMALL:.1f} mm\n"
        f"  BOTTOM row (smaller Y, {rows[0][4]:.0f} mm) -> BIG   pin {PIN_LARGE:.1f} mm\n"
        f"  Hole 1 = leftmost (smallest), hole {CLEAR_N} = rightmost (largest).\n"
        f"  'measured' is the expected milled size (~{UNDERSIZE:.1f} mm under commanded).\n\n"
        f"{'row':<6} {'pin':>5} {'#':>3} {'X':>6} {'Y':>5} {'clearance':>10} "
        f"{'commanded':>10} {'~measured':>10}\n")
    lines = [head]
    for (row, pin, idx, x, y, clr, cmd, meas) in rows:
        lines.append(f"{row:<6} {pin:>5.1f} {idx:>3} {x:>6.1f} {y:>5.1f} "
                     f"{clr:>10.2f} {cmd:>10.2f} {meas:>10.2f}")
    lines.append("\nTell me the snug hole per row (e.g. 'BIG #5, SMALL #5') and I'll\n"
                 "set pin_clearance to match.\n")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    dest = sys.argv[1] if len(sys.argv) > 1 else "examples/hole_test"
    print("wrote drill gerber to", write_hole_test(dest))
