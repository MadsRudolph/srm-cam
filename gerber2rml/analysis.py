"""Isolation preflight: copper-free channels narrower than the bit can't be milled."""

from shapely.geometry import MultiPolygon, Polygon


def find_narrow_gaps(copper, outline, bit_diameter, min_area: float = 0.1):
    """Return a shapely geometry of copper-free channels narrower than the bit.

    A morphological closing of the copper fills in gaps narrower than the bit.
    The difference between the closed copper and the original copper represents
    the un-millable slivers.

    Args:
        copper: Shapely geometry of copper regions.
        outline: Shapely geometry of the board outline (unused, kept for signature).
        bit_diameter: Diameter of the milling bit in mm.
        min_area: Minimum area in mm² to report (filters noise).

    Returns:
        Shapely geometry of flagged narrow gaps. Empty if none.
    """
    r = bit_diameter / 2.0
    
    # Morphological closing: dilate then erode. 
    # This bridges any gaps narrower than 2r.
    closed_copper = copper.buffer(r).buffer(-r)
    
    # The filled gaps are the difference.
    narrow = closed_copper.difference(copper)

    if narrow.is_empty:
        return narrow

    # Filter by minimum area and return valid polygons only. `.difference()`
    # can yield a GeometryCollection (polygons mixed with degenerate edges), so
    # flatten anything with sub-geometries rather than only MultiPolygon.
    polys = list(narrow.geoms) if hasattr(narrow, "geoms") else [narrow]
    keep = [p for p in polys if isinstance(p, Polygon) and p.area >= min_area]

    return MultiPolygon(keep) if keep else Polygon()
