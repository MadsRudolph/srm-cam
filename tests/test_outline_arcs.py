"""Regression: a board outline with filleted/rounded corners (arcs) must build
into a proper closed polygon, not a degenerate sliver.

Guards the bug where ``_outline_to_shapely`` collected only ``Line`` objects and
silently dropped ``Arc`` objects, so a filleted outline failed to polygonize and
fell back to buffering the longest segment into a ~0.1 mm-tall strip -- which
made the cutout toolpath run in one flat line along X.
"""
from pathlib import Path

from gerbonara import GerberFile

from gerber2rml.loader import _outline_to_shapely

FIXTURE = Path(__file__).parent / "fixtures" / "rounded_rect-Edge_Cuts.gm1"


def test_filleted_outline_builds_closed_polygon():
    layer = GerberFile.open(str(FIXTURE))
    # the fixture really does contain arcs (rounded corners)
    assert any(type(o).__name__ == "Arc" for o in layer.objects)

    poly = _outline_to_shapely(layer)

    assert poly.geom_type == "Polygon"
    assert poly.is_valid and not poly.is_empty

    minx, miny, maxx, maxy = poly.bounds
    width, height = maxx - minx, maxy - miny
    # the dropped-arc bug collapsed one dimension to ~0.1 mm; a real board is big
    assert width > 50, f"outline width collapsed to {width:.2f} mm"
    assert height > 50, f"outline height collapsed to {height:.2f} mm"
    assert poly.area > 1000, f"outline area collapsed to {poly.area:.1f} mm^2"

    # rounded corners => the exterior is many short segments, not a 4-corner box
    assert len(poly.exterior.coords) > 12, "arcs were not linearised into the outline"
