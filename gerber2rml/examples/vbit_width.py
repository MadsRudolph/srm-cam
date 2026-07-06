"""V-bit width test card: read the actual cut width with a MULTIMETER.

Sub-0.1 mm line widths can't be measured with calipers. This coupon turns
the measurement electrical: 8 copper tracks with design widths stepping

    0.40  0.35  0.30  0.25  0.20  0.15  0.10  0.05  mm   (top row -> bottom)

each connecting its OWN pair of 3x2 mm probe pads. Isolation milling keeps
a track at exactly its design width only when the real cut width equals the
configured one; an OVERCUT of d mm thins every track by d (d/2 per edge),
and tracks with design width <= d vanish -> their pad pair stops beeping.

Reading (with the traces tool configured for a 0.2 mm cut):

    narrowest track that still beeps    actual cut width
    0.05                                < 0.25
    0.10                                0.25 - 0.30
    0.15                                0.30 - 0.35
    0.20                                0.35 - 0.40   ...and so on.

All beep AND the 0.05 track looks clearly fatter than a hairline under a
loupe -> the cut is UNDERSIZED (Z zero shallow / angle smaller than set).

Entry point: :func:`write_coupon` (same contract as examples.calibration).
"""
from __future__ import annotations

from pathlib import Path

from gerber2rml.examples.calibration import (_aperture_block, _build_drill,
                                             _empty_gbr, _fmt, _gbr_header,
                                             _rect_region)

BOARD_W, BOARD_H = 26.0, 24.0
WIDTHS = (0.40, 0.35, 0.30, 0.25, 0.20, 0.15, 0.10, 0.05)
ROW_PITCH = 2.5
ROW_Y0 = 21.0                 # widest track on the TOP row, stepping down
PAD_W, PAD_H = 3.0, 2.0
PAD_LX, PAD_RX = 1.5, BOARD_W - 1.5 - PAD_W
HOLES = [(8.0, 1.2, 0.8), (18.0, 1.2, 0.8)]   # photo/registration anchors


def _build_bcu(widths=WIDTHS) -> str:
    regions = []
    for i, w in enumerate(widths):
        c = ROW_Y0 - i * ROW_PITCH
        regions.append(_rect_region(PAD_LX, c - PAD_H / 2,
                                    PAD_LX + PAD_W, c + PAD_H / 2))
        regions.append(_rect_region(PAD_RX, c - PAD_H / 2,
                                    PAD_RX + PAD_W, c + PAD_H / 2))
        regions.append(_rect_region(PAD_LX + PAD_W, c - w / 2,
                                    PAD_RX, c + w / 2))
    body = "\n".join(regions)
    return _gbr_header("Copper,L2,Bot") + _aperture_block() + body + "\nM02*\n"


def _build_edge() -> str:
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


def write_coupon(out_dir, widths=WIDTHS, name="vbit_width") -> Path:
    """Write the V-bit width card Gerbers into ``out_dir``/``name``.

    ``widths`` sets the 8 track design widths (top row first) — use a wider
    ladder when the first card wipes out completely (severe runout)."""
    if len(widths) != len(WIDTHS):
        raise ValueError(f"need exactly {len(WIDTHS)} widths")
    folder = Path(out_dir) / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "vbit-B_Cu.gbr").write_text(_build_bcu(widths))
    (folder / "vbit-Edge_Cuts.gbr").write_text(_build_edge())
    (folder / "vbit-F_Cu.gbr").write_text(_empty_gbr("Copper,L1,Top"))
    (folder / "vbit-F_Mask.gbr").write_text(_empty_gbr("Soldermask,Top"))
    (folder / "vbit-B_Mask.gbr").write_text(_empty_gbr("Soldermask,Bot"))
    (folder / "vbit-F_Silkscreen.gbr").write_text(_empty_gbr("Legend,Top"))
    (folder / "vbit.drl").write_text(_build_drill(HOLES))
    (folder / "README.txt").write_text(
        "V-bit width card - read with a multimeter (see vbit_width.py).\n"
        f"Rows top->bottom (mm): {' '.join(f'{w:.2f}' for w in widths)}\n"
        "Narrowest row that still beeps = upper bound on the overcut past\n"
        "the configured bit width. Actual cut width = bit_diameter + the\n"
        "bracket between the widest dead row and the narrowest live row.\n"
        "Everything beeps and the thinnest looks fat -> cut is undersized.\n")
    return folder


# Wide ladder for badly-behaved setups (broken tips, runout): 0.20-1.50 mm.
WIDE_WIDTHS = (1.50, 1.25, 1.00, 0.80, 0.60, 0.45, 0.30, 0.20)
