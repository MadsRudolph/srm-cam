"""Detect uncut copper from a registered board photo.

The rework loop closes here: the photo overlay already puts a real photo of
the board in machine coordinates (engine.photofit). This module walks every
isolation channel the job was supposed to cut, samples the photo along it,
and asks a simple question per sample: does this pixel look like copper or
like a cut channel? Runs of copper-looking samples are clustered into
proposed rework boxes — the operator reviews boxes instead of hunting for
bridges with a loupe.

Colors are learned from the board itself (no calibration): the copper
reference is the median color inside the copper polygons, the channel
reference is the median color along all channels — on any real board the
vast majority of channels ARE cut, so their median is the substrate color.
"""
import math

import numpy as np


class CutCheckError(RuntimeError):
    pass


def _to_px(extent, shape, x, y):
    """Machine mm -> (row, col) in a warped RGBA array (row 0 = LOWEST y)."""
    x0, x1, y0, y1 = extent
    h, w = shape[0], shape[1]
    c = (x - x0) / max(x1 - x0, 1e-9) * (w - 1)
    r = (y - y0) / max(y1 - y0, 1e-9) * (h - 1)
    return int(round(r)), int(round(c))


def _sample(img, r, c, k=1):
    """Median RGB of the (2k+1)^2 patch at (r, c); None if outside/transparent."""
    h, w = img.shape[:2]
    if not (0 <= r < h and 0 <= c < w):
        return None
    r0, r1 = max(r - k, 0), min(r + k + 1, h)
    c0, c1 = max(c - k, 0), min(c + k + 1, w)
    patch = img[r0:r1, c0:c1]
    a = patch[..., 3]
    if not (a > 0).any():
        return None
    rgb = patch[..., :3][a > 0]
    return np.median(rgb.reshape(-1, 3), axis=0)


def _walk(polyline, step):
    """Points every ``step`` mm along a polyline (includes both endpoints)."""
    out = []
    for (ax, ay), (bx, by) in zip(polyline, polyline[1:]):
        d = math.hypot(bx - ax, by - ay)
        n = max(1, int(math.ceil(d / step)))
        for i in range(n):
            t = i / n
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    if polyline:
        out.append(tuple(polyline[-1]))
    return out


def _walk_with_normal(polyline, step):
    """Like :func:`_walk` but yields (x, y, nx, ny) with the segment's unit
    normal, for sampling the channel's flanks."""
    out = []
    for (ax, ay), (bx, by) in zip(polyline, polyline[1:]):
        d = math.hypot(bx - ax, by - ay)
        if d < 1e-9:
            continue
        nx, ny = -(by - ay) / d, (bx - ax) / d
        n = max(1, int(math.ceil(d / step)))
        for i in range(n + 1):
            t = i / n
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t, nx, ny))
    return out


def _copper_color(img, extent, copper_geom, max_samples=400):
    """Median photo color inside the copper polygons (machine frame)."""
    from shapely.geometry import Point
    from shapely.prepared import prep
    minx, miny, maxx, maxy = copper_geom.bounds
    prepped = prep(copper_geom)
    n = int(math.ceil(math.sqrt(max_samples)))
    cols = []
    for j in range(n):
        for i in range(n):
            x = minx + (maxx - minx) * (i + 0.5) / n
            y = miny + (maxy - miny) * (j + 0.5) / n
            if not prepped.contains(Point(x, y)):
                continue
            s = _sample(img, *_to_px(extent, img.shape, x, y))
            if s is not None:
                cols.append(s)
    if len(cols) < 10:
        raise CutCheckError("photo barely overlaps the copper — check the "
                            "overlay alignment")
    return np.median(np.array(cols), axis=0)


def _merge_boxes(boxes, gap):
    merged = True
    boxes = [list(b) for b in boxes]
    while merged:
        merged = False
        out = []
        for b in boxes:
            for o in out:
                if (b[0] <= o[2] + gap and o[0] <= b[2] + gap
                        and b[1] <= o[3] + gap and o[1] <= b[3] + gap):
                    o[0] = min(o[0], b[0]); o[1] = min(o[1], b[1])
                    o[2] = max(o[2], b[2]); o[3] = max(o[3], b[3])
                    merged = True
                    break
            else:
                out.append(b)
        boxes = out
    return [tuple(b) for b in boxes]


def _neighbor_copper_color(img, extent, channels, offset, step):
    """Copper reference without geometry: sample just BESIDE the channels.
    An isolation channel has copper on both flanks (that's what it isolates),
    so the median over both sides is copper even where one side runs off the
    board."""
    cols = []
    for poly in channels:
        pts = list(poly)
        for a, b in zip(pts, pts[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            if length < 1e-9:
                continue
            nx, ny = -dy / length, dx / length
            for (x, y) in _walk([a, b], step * 2):
                for sgn in (1.0, -1.0):
                    s = _sample(img, *_to_px(extent, img.shape,
                                             x + nx * offset * sgn,
                                             y + ny * offset * sgn))
                    if s is not None:
                        cols.append(s)
    if len(cols) < 10:
        raise CutCheckError("photo barely overlaps the toolpaths — check the "
                            "overlay alignment")
    return np.median(np.array(cols), axis=0)


def _drop_outline_channels(channels, outline, margin):
    """Remove channel polylines that FOLLOW the board edge (the pour-edge /
    outline ring): they are cut by the cutout job, not the traces job, so
    'uncut' there is expected and would chain every real finding into one
    giant cluster. A polyline is dropped when >80% of its (decimated)
    vertices lie within ``margin`` mm of the outline."""
    from shapely.geometry import LineString, Point
    if not outline or len(outline) < 3:
        return list(channels)
    ring = LineString(list(outline) + [outline[0]])
    keep = []
    for poly in channels:
        pts = list(poly)[::5] or list(poly)
        near = sum(1 for (x, y) in pts if ring.distance(Point(x, y)) <= margin)
        if near <= 0.8 * len(pts):
            keep.append(poly)
    return keep


def _split_and_tighten(box, suspects, max_mm, min_run, pad):
    """Split an oversized merged cluster into <= ``max_mm`` tiles, keep tiles
    with at least ``min_run`` suspects, tighten each to its own suspects."""
    x0, y0, x1, y1 = box
    import math as m
    nx = max(1, m.ceil((x1 - x0) / max_mm))
    ny = max(1, m.ceil((y1 - y0) / max_mm))
    out = []
    for j in range(ny):
        for i in range(nx):
            tx0 = x0 + (x1 - x0) * i / nx
            tx1 = x0 + (x1 - x0) * (i + 1) / nx
            ty0 = y0 + (y1 - y0) * j / ny
            ty1 = y0 + (y1 - y0) * (j + 1) / ny
            inside = [(x, y) for (x, y) in suspects
                      if tx0 - 1e-9 <= x <= tx1 + 1e-9
                      and ty0 - 1e-9 <= y <= ty1 + 1e-9]
            if len(inside) < min_run:
                continue
            bx0 = min(x for x, _y in inside); bx1 = max(x for x, _y in inside)
            by0 = min(y for _x, y in inside); by1 = max(y for _x, y in inside)
            out.append((round(bx0 - pad, 2), round(by0 - pad, 2),
                        round(bx1 + pad, 2), round(by1 + pad, 2)))
    return out


def detect_uncut(photo_rgba, extent, channels, copper_geom=None, bit_d=0.8,
                 step=0.3, score_thresh=0.18, min_run=5, cluster_gap=1.5,
                 exclude_outline=None, outline_margin=2.0, max_box_mm=30.0):
    """Find channel stretches that still look like copper.

    ``photo_rgba``: HxWx4 uint8, machine-frame warped, row 0 at the LOWEST y
    (exactly what ``photofit.warp_photo`` produces). ``extent``: (x0, x1, y0,
    y1) mm. ``channels``: iterable of polylines [(x, y), ...] — the isolation
    toolpath centerlines. ``copper_geom`` (same frame as the channels) makes
    the flank sampling copper-verified — strongly recommended.

    Why local: on a bed-filling board photographed at an angle, lighting
    varies more across the photo than copper differs from substrate — global
    color references drown in it (found the hard way on the MegaPCB). Instead
    every channel sample is compared against its OWN flanks one bit-diameter
    to each side, which are copper by construction; the lighting gradient
    cancels. A cut channel differs from its flanks, an uncut bridge matches
    them.

    Returns ``{"boxes", "coverage", "n_samples", "n_suspect", "contrast",
    "copper_color", "channel_color"}`` — boxes are (x0, y0, x1, y1) mm,
    padded by the bit diameter; contrast is the median channel-vs-flank
    color difference (the photo's signal strength). Raises
    :class:`CutCheckError` when the photo can't answer the question: little
    overlap, no contrast (glare/flat light), or suspects everywhere (which
    means misalignment, not a board that's 40% uncut).
    """
    img = np.asarray(photo_rgba)
    if img.ndim != 3 or img.shape[2] != 4:
        raise CutCheckError("photo must be an RGBA array")
    del score_thresh                             # legacy knob (global method)
    if exclude_outline is not None:
        channels = _drop_outline_channels(channels, exclude_outline,
                                          outline_margin)

    # Flank offsets to try, nearest first. With one-pass isolation a
    # NEIGHBOURING channel can run 1-1.5 mm away, so a blind flank sample can
    # land in substrate and make a cut channel read "uncut". When the copper
    # geometry is available, each flank is projected onto VERIFIED copper.
    offsets = [max(bit_d, 0.8), max(bit_d, 0.8) + 0.5, max(bit_d, 0.8) + 1.0]
    walked = []                     # (x, y, nx, ny)
    for poly in channels:
        if len(poly) < 2:
            continue
        walked.extend(_walk_with_normal(list(poly), step))

    flank_ok = None
    if copper_geom is not None and not getattr(copper_geom, "is_empty", True):
        cand_x, cand_y = [], []
        for (x, y, nx, ny) in walked:
            for sgn in (1.0, -1.0):
                for off in offsets:
                    cand_x.append(x + nx * off * sgn)
                    cand_y.append(y + ny * off * sgn)
        try:
            import shapely
            flank_ok = shapely.contains_xy(
                copper_geom, np.array(cand_x), np.array(cand_y))
        except (ImportError, AttributeError):    # shapely < 2: prepared loop
            from shapely.geometry import Point
            from shapely.prepared import prep
            prepped = prep(copper_geom)
            flank_ok = np.array([prepped.contains(Point(cx, cy))
                                 for cx, cy in zip(cand_x, cand_y)])

    n_off = len(offsets)
    samples = []                    # (x, y, diff_to_flanks)
    ch_cols, fl_cols = [], []
    for k, (x, y, nx, ny) in enumerate(walked):
        c = _sample(img, *_to_px(extent, img.shape, x, y))
        if c is None:
            continue
        flanks = []
        for s_i, sgn in enumerate((1.0, -1.0)):
            for o_i, off in enumerate(offsets):
                if flank_ok is not None and not flank_ok[
                        k * 2 * n_off + s_i * n_off + o_i]:
                    continue                     # not verified copper there
                f = _sample(img, *_to_px(extent, img.shape,
                                         x + nx * off * sgn,
                                         y + ny * off * sgn))
                if f is not None:
                    flanks.append(f)
                    break                        # nearest valid flank per side
        if not flanks:
            continue                             # no copper flank: can't judge
        f = np.mean(np.array(flanks), axis=0)
        samples.append((x, y, float(np.linalg.norm(c - f))))
        ch_cols.append(c)
        fl_cols.append(f)
    if len(samples) < 20:
        raise CutCheckError("photo covers too little of the toolpaths — check "
                            "the overlay alignment")

    diffs = np.array([d for _x, _y, d in samples])
    contrast = float(np.median(diffs))
    if contrast < 15.0:
        raise CutCheckError(
            f"no copper/channel contrast in this photo (median {contrast:.0f})"
            f" — glare or flat light; reshoot with side light")

    # LOCAL contrast normalization: a handheld photo has focus/lighting
    # falloff across the board that swamps a global threshold (measured on
    # the MegaPCB: the sharp region flagged MORE than the damaged one). Each
    # sample is judged against the median contrast of its own 8 mm
    # neighbourhood; regions with no local contrast (soft focus) abstain
    # instead of guessing.
    xs = np.array([x for x, _y, _d in samples])
    ys = np.array([y for _x, y, _d in samples])
    keys = (np.floor(xs / 8.0).astype(np.int64) * 100000
            + np.floor(ys / 8.0).astype(np.int64))
    local_med = np.full(len(samples), contrast)
    for k in np.unique(keys):
        m = keys == k
        if m.sum() >= 30:
            local_med[m] = np.median(diffs[m])
    sus_mask = (diffs < 0.30 * local_med) & (local_med > 12.0)
    suspects = [(x, y) for (x, y, _d), s in zip(samples, sus_mask) if s]
    frac = len(suspects) / len(samples)
    if frac > 0.45:
        raise CutCheckError(
            f"{frac * 100:.0f}% of the channels read as copper — that's a "
            f"misaligned overlay or unusable lighting, not a board this "
            f"uncut. Re-check the photo anchors.")

    # Dispersion gate: real damage clusters; NOISE smears evenly. If the
    # suspects touch most of the board, the photo cannot answer the question
    # — refuse rather than tile the whole board in boxes. (Shallow-but-
    # visible cuts are invisible to any color test: judge DEPTH failures
    # with Probe boxes / Mesh check, not photos.)
    if suspects:
        tile = 15.0
        s_tiles = {(int(x // tile), int(y // tile)) for (x, y) in suspects}
        a_tiles = {(int(x // tile), int(y // tile))
                   for (x, y, _d) in samples}
        if len(s_tiles) > 0.5 * len(a_tiles) and len(a_tiles) > 8:
            raise CutCheckError(
                f"suspect readings are spread over {len(s_tiles)} of "
                f"{len(a_tiles)} board tiles — that's photo noise (soft "
                f"focus/glare), not localized damage. This check finds "
                f"channels that were NEVER cut; too-SHALLOW cuts look cut "
                f"in any photo — use Probe boxes / Mesh check for depth.")

    # Cluster suspect samples; a real bridge is a RUN of them, a single sample
    # is dust/glare. Oversized clusters (a badly leveled BAND, or chained
    # neighbours) get tiled into <= max_box_mm boxes — a 200 mm rework box is
    # not a workable instruction.
    boxes = _merge_boxes([(x, y, x, y) for (x, y) in suspects], cluster_gap)
    pad = bit_d
    keep = []
    for b in boxes:
        inside = [(x, y) for (x, y) in suspects
                  if b[0] - 1e-9 <= x <= b[2] + 1e-9
                  and b[1] - 1e-9 <= y <= b[3] + 1e-9]
        if len(inside) < min_run:
            continue
        if (b[2] - b[0]) > max_box_mm or (b[3] - b[1]) > max_box_mm:
            keep.extend(_split_and_tighten(b, inside, max_box_mm, min_run, pad))
        else:
            keep.append((round(b[0] - pad, 2), round(b[1] - pad, 2),
                         round(b[2] + pad, 2), round(b[3] + pad, 2)))
    return {
        "boxes": keep,
        "coverage": 1.0 - frac,
        "n_samples": len(samples),
        "n_suspect": len(suspects),
        "contrast": contrast,
        "copper_color": tuple(float(v)
                              for v in np.median(np.array(fl_cols), axis=0)),
        "channel_color": tuple(float(v)
                               for v in np.median(np.array(ch_cols), axis=0)),
    }
