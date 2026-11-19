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


# The machine's own error (engine/laser_focus.py), measured once on a flat
# sheet and kept with the page's other settings.
REFERENCE_KEY = "focus_reference"
REFERENCE_SPACING_MM = 20.0


def _settings():
    from PySide6.QtCore import QSettings
    from gerber2rml.gui2.stencil_laser import _SETTINGS
    return QSettings(*_SETTINGS)


def load_reference():
    import json
    try:
        data = json.loads(_settings().value(REFERENCE_KEY, "") or "null")
    except (TypeError, ValueError):
        return None
    return lf.FocusMap.from_dict(data) if data else None


def save_reference(ref):
    import json
    cfg = _settings()
    if ref is None:
        cfg.remove(REFERENCE_KEY)
    else:
        cfg.setValue(REFERENCE_KEY, json.dumps(ref.to_dict()))


def reference_status():
    ref = load_reference()
    if ref is None:
        return ("Not measured. Away from the middle of the bed the blue dot "
                "reads a slope that is not there, so the focus map is not "
                "trusted until this is measured.")
    xs = [p[0] for p in ref.points]
    ys = [p[1] for p in ref.points]
    return (f"Measured at {len(ref.points)} points, X {min(xs):g}-{max(xs):g}, "
            f"Y {min(ys):g}-{max(ys):g} mm; up to {ref.spread:.2f} mm taken "
            f"off the map's readings.")


def bias_at(at):
    """What the dot reads at ``at`` on a flat sheet in focus: 0 without a
    reference, or where the reference does not reach."""
    ref = load_reference()
    if ref is None or not lf.reference_covers(ref, (*at, *at)):
        return 0.0
    return ref.at(*at)


def calibrate(page):
    """Measure the machine's error over the job's area on a sheet known to be
    flat (fresh copper-clad lying on the bed), the head focused on it."""
    bounds = job_bounds(page)
    if bounds is None:
        return page._say("Load a job as big as the flat sheet first: the "
                         "correction is measured over its area.", warn=True)
    points = lf.grid_points(bounds, spacing=REFERENCE_SPACING_MM)
    centre = lf.REFERENCE_CENTRE
    if not (bounds[0] <= centre[0] <= bounds[2] and bounds[1] <= centre[1] <= bounds[3]):
        return page._say(f"The job must cover the middle of the bed (X {centre[0]:g} "
                         f"Y {centre[1]:g}), where the dot is trusted.", warn=True)
    points.append(centre)

    def work(progress):
        return lf.measure_map(page.laser, page._calibration(), points,
                              progress=lambda i, n: progress(i))

    def done(fmap):
        ref = lf.reference_from(fmap)
        save_reference(ref)
        page._focus_map = None
        _draw(page)
        note = getattr(page, "focus_ref_note", None)
        if note is not None:
            note.setText(reference_status())
        return (f"Focus map correction saved: {len(ref.points)} points, the dot "
                f"read {ref.spread:.2f} mm of slope on the flat sheet.")
    page._start(work, f"Measuring the machine's focus error at {len(points)} "
                      f"points…", done)


def forget_reference(page):
    save_reference(None)
    note = getattr(page, "focus_ref_note", None)
    if note is not None:
        note.setText(reference_status())
    page._say("Focus map correction forgotten.")


def measure(page):
    """Measure the focus over the job with the blue dot, on the page's
    worker; the map lands in ``page._focus_map`` and is drawn."""
    bounds = job_bounds(page)
    if bounds is None:
        return page._say("Nothing loaded to measure over.", warn=True)
    points = lf.grid_points(bounds)
    ref = load_reference()

    def work(progress):
        return lf.measure_map(page.laser, page._calibration(), points,
                              progress=lambda i, n: progress(i))

    def done(fmap):
        fmap = lf.corrected(fmap, ref)
        page._focus_map = fmap
        _draw(page)
        if getattr(page, "kind", None) == "traces":
            zones = lf.band_boxes(fmap, bounds)
        else:
            zones = lf.plan_zones([[c] for c in shape_centres(
                page, range(len(page.art.apertures)))], fmap)
        words = "Focus map: " + lf.describe(fmap, zones)
        if ref is None:
            return words + (" Not corrected for the machine's own error: "
                            "measure the correction on a flat sheet first.")
        if not lf.reference_covers(ref, bounds):
            return words + (" The correction was measured over a smaller "
                            "area; its edge values are used beyond it.")
        return words + " Corrected for the machine's own error."
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
