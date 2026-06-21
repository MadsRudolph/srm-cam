"""Board summary text for documentation / the report."""
from collections import Counter


def board_summary(board, name: str = "board") -> str:
    """Generate a text summary of the board dimensions and holes.

    Args:
        board: Board dataclass with .outline (shapely geometry),
               .copper (shapely geometry with .area),
               .holes (list of (x, y, diameter) tuples)
        name: Board name for the title

    Returns:
        Formatted text summary with board size, copper area, and hole breakdown.
    """
    x0, y0, x1, y1 = board.outline.bounds
    lines = [
        f"# {name} - board summary",
        "",
        f"- Size: {x1 - x0:.1f} x {y1 - y0:.1f} mm",
        f"- Copper area: {board.copper.area:.1f} mm^2",
        f"- Holes: {len(board.holes)}"
    ]

    by_dia = Counter(round(d, 2) for (_x, _y, d) in board.holes)
    for dia, n in sorted(by_dia.items()):
        lines.append(f"  - {dia} mm x {n}")

    return "\n".join(lines) + "\n"
