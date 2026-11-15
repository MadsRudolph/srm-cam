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


def split_narrow_gaps(gaps, copper, touch_mm: float = 0.01):
    """Sort :func:`find_narrow_gaps`'s patches into ``(between, corners)``.

    ``between`` lie between two SEPARATE pieces of copper: a gap that was
    meant to be cleared and will not be. ``corners`` touch one piece only -
    the inside of an acute bend, where a track joins another at 45 degrees:
    a round cutter cannot reach into the point, so that copper stays, and it
    stays part of the very track it is the corner of. Nothing is joined that
    was apart, so it is not a finding; it is what a milled corner looks like.

    Both are shapely geometries, empty when there are none.
    """
    from shapely.strtree import STRtree

    def pack(polys):
        return MultiPolygon(polys) if polys else Polygon()

    if gaps is None or gaps.is_empty:
        return Polygon(), Polygon()
    pieces = list(getattr(copper, "geoms", [copper]))
    patches = list(getattr(gaps, "geoms", [gaps]))
    if len(pieces) < 2:
        return Polygon(), pack(patches)
    tree = STRtree(pieces)
    between, corners = [], []
    for patch in patches:
        near = sum(1 for i in tree.query(patch.buffer(touch_mm))
                   if pieces[int(i)].distance(patch) <= touch_mm)
        (between if near >= 2 else corners).append(patch)
    return pack(between), pack(corners)
