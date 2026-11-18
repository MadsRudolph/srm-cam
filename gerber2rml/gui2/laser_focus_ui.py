"""The laser page's focus map: measure the height over the job, then run it
in bands, each with the head refocused for it (engine/laser_focus.py).

Kept out of stencil_laser.py, which is long enough: the page calls
:func:`measure` from its "Measure focus" button and :func:`run_zoned` from its
run, and reads ``page._focus_map``.
"""
from gerber2rml.engine import laser_focus as lf
from gerber2rml.engine import xtool


def job_bounds(page):
    """The job's outline on the bed, (x0, y0, x1, y1) mm, or None."""
    art = getattr(page, "art", None)
    if art is None or getattr(page, "_empty", False):
        return None
    _w, h = art.size
    rings = []
    for poly in getattr(art.outline, "geoms", [art.outline]):
        rings.append(xtool.to_bed(list(poly.exterior.coords), page.origin(), h))
    xs = [x for r in rings for x, _y in r]
    ys = [y for r in rings for _x, y in r]
    return min(xs), min(ys), max(xs), max(ys)


def shape_centres(page, indices):
    """The middle of each of ``art.apertures[i]`` on the bed."""
    art = page.art
    _w, h = art.size
    out = []
    for i in indices:
        c = art.apertures[i].centroid
        out.append(xtool.to_bed([(c.x, c.y)], page.origin(), h)[0])
    return out


def measure(page):
    """Measure the focus over the job with the blue dot, on the page's
    worker; the map lands in ``page._focus_map`` and is drawn."""
    bounds = job_bounds(page)
    if bounds is None:
        return page._say("Nothing loaded to measure over.", warn=True)
    points = lf.grid_points(bounds)

    def work(progress):
        return lf.measure_map(page.laser, page._calibration(), points,
                              progress=lambda i, n: progress(i))

    def done(fmap):
        page._focus_map = fmap
        _draw(page)
        zones = lf.plan_zones([[c] for c in shape_centres(
            page, range(len(page.art.apertures)))], fmap)
        return "Focus map: " + lf.describe(fmap, zones)
    page._start(work, f"Measuring the focus at {len(points)} points…", done)


def clear(page):
    page._focus_map = None
    _draw(page)


def _draw(page):
    """The measured points on the bed, labelled with how far each is off
    focus, if the page can draw marks."""
    fmap = getattr(page, "_focus_map", None)
    draw = getattr(page, "show_focus_points", None)
    if draw is not None:
        draw([] if fmap is None else list(fmap.points))


def zones_for(page, indices):
    """``[(dz, [index])]`` for running ``indices`` of ``page.art.apertures``
    with the page's focus map; one zone at 0 without a map."""
    fmap = getattr(page, "_focus_map", None)
    indices = list(indices)
    if fmap is None or not fmap.points:
        return [(0.0, indices)]
    groups = lf.zone_indices(shape_centres(page, indices), fmap)
    return [(dz, [indices[k] for k in idx]) for dz, idx in groups]


def run_zoned(laser, fmap, zones, build_job, *, progress=None, timeout_for):
    """Run each zone with the head at its focus: ``build_job(indices)``
    gives the job for a zone. Puts the head back where the map was measured.
    Returns the Z of the last zone."""
    base = fmap.z if fmap is not None else laser.z()
    elapsed = 0.0
    last = base
    try:
        for dz, idx in zones:
            if not idx:
                continue
            job = build_job(set(idx))
            if fmap is not None:
                laser._json("POST", "/device/modeSwitch",
                            {"state": "P_AUTOFOCUS"})
                try:
                    last = laser._goto_z(base + dz)
                finally:
                    laser._json("POST", "/device/modeSwitch",
                                {"state": "P_IDLE"})
            laser.run(job.text)
            off = elapsed
            laser.wait(timeout_for(job),
                       progress=(lambda t: progress(off + t)) if progress
                       else None)
            elapsed += job.seconds
    finally:
        if fmap is not None and len(zones) > 1:
            try:
                laser._json("POST", "/device/modeSwitch",
                            {"state": "P_AUTOFOCUS"})
                laser._goto_z(base)
            finally:
                laser._json("POST", "/device/modeSwitch", {"state": "P_IDLE"})
    return last
