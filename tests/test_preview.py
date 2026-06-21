"""Tests for the preview polyline helper."""
from gerber2rml.toolpath import Move
from gerber2rml.app.preview import toolpath_segments


def test_splits_cut_and_rapid():
    """Rapid approach, plunge+cut, rapid lift."""
    tp = [Move(0, 0, 2, rapid=True), Move(0, 0, -0.1), Move(1, 0, -0.1),
          Move(1, 0, 2, rapid=True)]
    cuts, rapids = toolpath_segments([tp])
    assert len(cuts) >= 1
    assert len(rapids) >= 1
    # the cut polyline contains the (0,0)->(1,0) move
    assert any((1.0, 0.0) in poly for poly in cuts)


def test_empty_input():
    """Empty input returns empty lists."""
    assert toolpath_segments([]) == ([], [])
