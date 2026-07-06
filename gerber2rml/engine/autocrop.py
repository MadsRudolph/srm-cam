"""Auto-crop a board photo to the copper stock.

Phone photos of the bed include the whole machine — gantry, rails, spoil
board, clips. The copper blank is the one large *pink/red-brown, low
saturation* region: copper hue sits below ~30 deg with a small green-blue
gap, while the wooden spoilboard is yellower (large green-blue gap), the
machine is grey (no red excess), and the orange panel / red clip are far
more saturated. Threshold on that, take the largest connected blob, and
crop to its bounding box plus a margin.

Everything runs on a small copy (<= ~400 px) — the caller applies the
normalized box to the full-resolution image.
"""
from __future__ import annotations

import numpy as np

MIN_AREA_FRAC = 0.06      # blob smaller than this -> not a board, no crop
MARGIN_FRAC = 0.015       # breathing room around the blob's bbox


def _copper_mask(rgb: np.ndarray) -> np.ndarray:
    """Boolean mask of copper-looking pixels (HxWx3 uint8 in, HxW out)."""
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    spread = mx - mn                            # ~saturation * value
    # red-dominant, but pink (small g-b gap) rather than yellow (big gap):
    # copper: r-g moderate, g-b small. wood: g-b comparable to r-g.
    coppery = (r - g >= 8) & ((g - b) <= (r - g) + 12) & ((g - b) < 45)
    muted = (spread >= 10) & (spread <= 110)    # not grey, not neon orange
    lit = (mx >= 60) & (mx <= 245)              # not shadow, not blown out
    return coppery & muted & lit


def _open3(m: np.ndarray) -> np.ndarray:
    """3x3 binary opening (erode+dilate) — kills dust/speckle noise."""
    def erode(a):
        p = np.pad(a, 1, constant_values=False)
        out = p[1:-1, 1:-1].copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                out &= p[1 + dy:p.shape[0] - 1 + dy,
                         1 + dx:p.shape[1] - 1 + dx]
        return out

    def dilate(a):
        p = np.pad(a, 1, constant_values=False)
        out = np.zeros_like(a)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                out |= p[1 + dy:p.shape[0] - 1 + dy,
                         1 + dx:p.shape[1] - 1 + dx]
        return out

    return dilate(erode(m))


def _largest_blob(mask: np.ndarray) -> np.ndarray | None:
    """Largest 4-connected component (scanline flood fill, no scipy)."""
    todo = mask.copy()
    best = None
    best_n = 0
    h, w = mask.shape
    while True:
        seeds = np.argwhere(todo)
        if not len(seeds):
            break
        stack = [tuple(seeds[0])]
        comp = np.zeros_like(mask)
        todo[tuple(seeds[0])] = False
        n = 0
        while stack:
            y, x = stack.pop()
            comp[y, x] = True
            n += 1
            if y > 0 and todo[y - 1, x]:
                todo[y - 1, x] = False; stack.append((y - 1, x))
            if y < h - 1 and todo[y + 1, x]:
                todo[y + 1, x] = False; stack.append((y + 1, x))
            if x > 0 and todo[y, x - 1]:
                todo[y, x - 1] = False; stack.append((y, x - 1))
            if x < w - 1 and todo[y, x + 1]:
                todo[y, x + 1] = False; stack.append((y, x + 1))
        if n > best_n:
            best_n = n
            best = comp
        # everything left is smaller than what we have once half is gone
        if best_n >= todo.sum():
            break
    return best


def copper_bbox(rgb: np.ndarray):
    """Normalized (x0, y0, x1, y1) of the copper stock in an RGB(A) image,
    or None when no convincing board is visible. Coordinates are fractions
    of width/height, so they apply to any resolution of the same photo."""
    if rgb.ndim != 3:
        return None
    rgb = rgb[..., :3]
    h, w = rgb.shape[:2]
    step = max(1, max(h, w) // 400)             # ~400 px working copy
    small = rgb[::step, ::step]
    mask = _open3(_copper_mask(small))
    if mask.mean() < MIN_AREA_FRAC:
        return None
    blob = _largest_blob(mask)
    if blob is None or blob.mean() < MIN_AREA_FRAC:
        return None
    ys, xs = np.nonzero(blob)
    sh, sw = mask.shape
    # per-row/col trim: drop the outer ~1% of blob pixels in each direction
    # so one stray dust streak can't drag the box across the bed
    lo = 0.01, 0.99
    x0, x1 = np.quantile(xs, lo)
    y0, y1 = np.quantile(ys, lo)
    mx, my = MARGIN_FRAC * sw, MARGIN_FRAC * sh
    return (max(0.0, (x0 - mx) / sw), max(0.0, (y0 - my) / sh),
            min(1.0, (x1 + 1 + mx) / sw), min(1.0, (y1 + 1 + my) / sh))


def crop_to_copper(rgb: np.ndarray):
    """Convenience: return the cropped array (or the original if no crop,
    or if the found box is basically the whole frame already)."""
    box = copper_bbox(rgb)
    if box is None:
        return rgb, False
    x0, y0, x1, y1 = box
    if (x1 - x0) * (y1 - y0) > 0.90:            # already tight
        return rgb, False
    h, w = rgb.shape[:2]
    return rgb[int(y0 * h):int(np.ceil(y1 * h)),
               int(x0 * w):int(np.ceil(x1 * w))], True
