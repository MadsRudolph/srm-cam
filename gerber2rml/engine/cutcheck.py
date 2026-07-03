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


def detect_uncut(photo_rgba, extent, channels, copper_geom=None, bit_d=0.8,
                 step=0.3, score_thresh=0.18, min_run=3, cluster_gap=2.0):
    """Find channel stretches that still look like copper.

    ``photo_rgba``: HxWx4 uint8, machine-frame warped, row 0 at the LOWEST y
    (exactly what ``photofit.warp_photo`` produces). ``extent``: (x0, x1, y0,
    y1) mm. ``channels``: iterable of polylines [(x, y), ...] — the isolation
    toolpath centerlines. ``copper_geom``: optional shapely geometry of the
    copper for the copper-color reference; without it the reference is sampled
    just beside the channels (their flanks are copper by construction).

    Returns ``{"boxes", "coverage", "n_samples", "n_suspect", "copper_color",
    "channel_color"}`` where boxes are (x0, y0, x1, y1) mm, padded by the bit
    diameter. Raises :class:`CutCheckError` when the photo can't answer the
    question (no overlap, or copper and channels are the same color).
    """
    img = np.asarray(photo_rgba)
    if img.ndim != 3 or img.shape[2] != 4:
        raise CutCheckError("photo must be an RGBA array")
    if copper_geom is not None:
        cu = _copper_color(img, extent, copper_geom)
    else:
        cu = _neighbor_copper_color(img, extent, channels,
                                    offset=max(bit_d, 0.8), step=step)

    samples = []                    # (x, y, rgb)
    for poly in channels:
        if len(poly) < 2:
            continue
        for (x, y) in _walk(list(poly), step):
            s = _sample(img, *_to_px(extent, img.shape, x, y))
            if s is not None:
                samples.append((x, y, s))
    if len(samples) < 20:
        raise CutCheckError("photo covers too little of the toolpaths — check "
                            "the overlay alignment")
    ch = np.median(np.array([s for _x, _y, s in samples]), axis=0)
    sep = float(np.linalg.norm(cu - ch))
    if sep < 25:
        raise CutCheckError(
            f"copper and channel colors are too similar in this photo "
            f"(separation {sep:.0f}) — more light / less glare needed")

    suspects = []
    for (x, y, s) in samples:
        d_cu = float(np.linalg.norm(s - cu))
        d_ch = float(np.linalg.norm(s - ch))
        score = (d_ch - d_cu) / max(d_ch + d_cu, 1e-9)
        if score > score_thresh:                 # clearly closer to copper
            suspects.append((x, y))

    # Cluster suspect samples; a real bridge is a RUN of them, a single sample
    # is dust/glare.
    boxes = _merge_boxes([(x, y, x, y) for (x, y) in suspects], cluster_gap)
    counts = []
    for b in boxes:
        n = sum(1 for (x, y) in suspects
                if b[0] - 1e-9 <= x <= b[2] + 1e-9
                and b[1] - 1e-9 <= y <= b[3] + 1e-9)
        counts.append(n)
    pad = bit_d
    keep = [(round(b[0] - pad, 2), round(b[1] - pad, 2),
             round(b[2] + pad, 2), round(b[3] + pad, 2))
            for b, n in zip(boxes, counts) if n >= min_run]
    return {
        "boxes": keep,
        "coverage": 1.0 - len(suspects) / len(samples),
        "n_samples": len(samples),
        "n_suspect": len(suspects),
        "copper_color": tuple(float(v) for v in cu),
        "channel_color": tuple(float(v) for v in ch),
    }
