"""Tests for board_summary() report generation."""
from pathlib import Path
from gerber2rml.report import board_summary
from gerber2rml.loader import load_board

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


def test_summary_has_size_and_holes():
    """board_summary() includes board name, dimensions, and hole count."""
    board = load_board(FIXT, mirror=False)
    text = board_summary(board, name="demo")
    assert "demo" in text
    assert "mm" in text
    assert "Holes" in text
