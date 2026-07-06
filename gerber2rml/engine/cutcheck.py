"""Detect failed isolation channels from a registered board photo.

Trained against ground truth (the MegaPCB top side: the operator's actual
rework boxes vs the channels that cut clean, evaluated on the real photo):
the discriminating signature is the channel CROSS-PROFILE, not its color.

- A properly cut channel reads BRIGHT across its profile: exposed substrate
  floor plus burred edges catching the light.
- A failed channel (cut too shallow, or never cut) reads FLAT or as a dark
  smooth groove — no bright floor, no edge highlights.

Per channel sample a 13-tap brightness profile is taken across the channel
(+-1.2 mm); ``bright`` = how much the inner profile rises above the copper
flanks. Samples are classified cut / suspect / undecided, and 8 mm tiles are
scored by their suspect fraction among DECIDED samples — that aggregation is
what turns a noisy per-sample signal (photos of shiny boards are noisy) into
a usable region detector (tile-level AUC 0.78 on the MegaPCB ground truth).

Needs the FULL-RESOLUTION photo warped at >= 12 px/mm: the profile signature
does not survive heavy downscaling (found the hard way).

Honest limits, enforced with refusals rather than guesses: soft-focus or
glare regions where nothing reads clearly are excluded; if too little of the
board is decidable, or suspects smear over most of it (misalignment), a
:class:`CutCheckError` explains instead of proposing garbage boxes.
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
    normal, for sampling across the channel."""
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


def _drop_outline_channels(channels, outline, margin):
    """Remove channel polylines that FOLLOW the board edge (the pour-edge /
    outline ring): they are cut by the cutout job, not the traces job, so
    'failed' there is expected and would drown the real findings. A polyline
    is dropped when >80% of its (decimated) vertices lie within ``margin`` mm
    of the outline."""
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


def channel_profiles(photo_rgba, extent, channels, step=0.3, half_width=1.2,
                     taps=13):
    """Cross-profile brightness stats per channel sample (vectorized).

    Returns ``(xy, bright)``: sample positions (N, 2) and how much the inner
    profile rises above the copper flanks (N,). ``bright`` is the feature the
    classifier thresholds: big = bright cut floor/edges, ~0 = flat copper or
    a dark smooth groove.
    """
    img = np.asarray(photo_rgba)
    L = img[..., :3].astype(np.float32).mean(axis=-1)
    A = img[..., 3]
    h, w = L.shape
    x0, x1, y0, y1 = extent
    offs = np.linspace(-half_width, half_width, taps)
    all_xy, all_bright = [], []
    for poly in channels:
        if len(poly) < 2:
            continue
        walked = _walk_with_normal(list(poly), step)
        if not walked:
            continue
        P = np.array(walked)
        prof = np.empty((len(P), taps), np.float32)
        for t_i, off in enumerate(offs):
            gx = P[:, 0] + P[:, 2] * off
            gy = P[:, 1] + P[:, 3] * off
            cc = np.clip(((gx - x0) / max(x1 - x0, 1e-9)
                          * (w - 1)).round().astype(int), 0, w - 1)
            rr = np.clip(((gy - y0) / max(y1 - y0, 1e-9)
                          * (h - 1)).round().astype(int), 0, h - 1)
            v = L[rr, cc].copy()
            v[A[rr, cc] == 0] = np.nan
            prof[:, t_i] = v
        ok = ~np.isnan(prof).any(axis=1)
        if not ok.any():
            continue
        P, prof = P[ok], prof[ok]
        outer = prof[:, [0, 1, taps - 2, taps - 1]].mean(axis=1)
        inner_max = prof[:, 2:taps - 2].max(axis=1)
        all_xy.append(P[:, :2])
        all_bright.append(inner_max - outer)
    if not all_xy:
        return np.empty((0, 2)), np.empty(0)
    return np.vstack(all_xy), np.concatenate(all_bright)


def detect_uncut(photo_rgba, extent, channels, copper_geom=None, bit_d=0.8,
                 step=0.3, exclude_outline=None, outline_margin=2.0,
                 tile_mm=8.0, cut_bright=30.0, suspect_bright=15.0,
                 tile_thresh=0.5, min_decided=10):
    """Find channel regions that did not cut properly.

    ``photo_rgba``: machine-frame warped RGBA at >= 12 px/mm — use the FULL
    resolution photo, the profile signature dies in downscaled warps. Row 0
    at the LOWEST y (photofit.warp_photo). ``extent``: (x0, x1, y0, y1) mm.
    ``channels``: iterable of centerline polylines. ``copper_geom`` accepted
    for API compatibility (unused).

    Per sample: ``bright`` > ``cut_bright`` -> cut; < ``suspect_bright`` ->
    suspect (flat copper or dark groove); between -> undecided (soft focus /
    glare abstains). Tiles of ``tile_mm`` with at least ``min_decided``
    decided samples score suspect/(suspect+cut); tiles above ``tile_thresh``
    merge into proposed boxes.

    Returns ``{"boxes", "coverage", "n_samples", "n_suspect", "n_tiles",
    "n_suspect_tiles", "decided_frac"}``. Raises :class:`CutCheckError` when
    the photo can't answer (little overlap, nothing decidable, or suspect
    tiles covering most of the board = misalignment).
    """
    img = np.asarray(photo_rgba)
    if img.ndim != 3 or img.shape[2] != 4:
        raise CutCheckError("photo must be an RGBA array")
    del copper_geom
    if exclude_outline is not None:
        channels = _drop_outline_channels(channels, exclude_outline,
                                          outline_margin)
    xy, bright = channel_profiles(img, extent, channels, step=step)
    if len(xy) < 50:
        raise CutCheckError("photo covers too little of the toolpaths — check "
                            "the overlay alignment")
    suspect = bright < suspect_bright
    cut = bright > cut_bright
    decided = suspect | cut
    decided_frac = float(decided.mean())
    if decided_frac < 0.2:
        raise CutCheckError(
            f"only {decided_frac * 100:.0f}% of the channels read clearly — "
            f"soft focus or glare; reshoot straighter-on with even light")

    keys = (np.floor(xy[:, 0] / tile_mm).astype(np.int64) * 100000
            + np.floor(xy[:, 1] / tile_mm).astype(np.int64))
    sus_tiles, n_tiles = [], 0
    for k in np.unique(keys):
        m = keys == k
        n_dec = int(decided[m].sum())
        if n_dec < min_decided:
            continue
        n_tiles += 1
        frac = suspect[m].sum() / n_dec
        if frac > tile_thresh:
            tx = xy[m][:, 0]; ty = xy[m][:, 1]
            s = suspect[m]
            sus_tiles.append((float(tx[s].min()), float(ty[s].min()),
                              float(tx[s].max()), float(ty[s].max())))
    if n_tiles < 4:
        raise CutCheckError("too few readable regions to judge — check the "
                            "photo/overlay")
    if len(sus_tiles) > 0.6 * n_tiles:
        raise CutCheckError(
            f"{len(sus_tiles)} of {n_tiles} tiles read as failed — that's a "
            f"misaligned overlay or unusable photo, not a board this bad. "
            f"Re-check the anchor clicks.")
    pad = bit_d
    boxes = [(round(b[0] - pad, 2), round(b[1] - pad, 2),
              round(b[2] + pad, 2), round(b[3] + pad, 2))
             for b in _merge_boxes(sus_tiles, gap=1.0)]
    n_sus = int(suspect.sum())
    return {
        "boxes": boxes,
        "coverage": 1.0 - len(sus_tiles) / n_tiles,
        "n_samples": int(len(xy)),
        "n_suspect": n_sus,
        "n_tiles": n_tiles,
        "n_suspect_tiles": len(sus_tiles),
        "decided_frac": decided_frac,
    }
