"""Photo -> machine-frame registration for the rework photo overlay.

A milled board is flat, so a photo of it taken from ANY angle maps to the
machine frame by a single homography. Fit it from >= 4 clicked hole
correspondences (photo pixels -> known machine mm), then warp the photo into
an RGBA raster aligned with the preview so rework boxes are drawn directly
on the real copper.

Pure numpy - no OpenCV. Points are (u, v) photo pixels (col, row) and
(x, y) machine mm; the fit absorbs the image's y-down convention.
"""
import numpy as np


def _normalize(pts):
    """Hartley normalization: translate centroid to 0, mean distance sqrt(2)."""
    pts = np.asarray(pts, float)
    c = pts.mean(axis=0)
    d = np.sqrt(((pts - c) ** 2).sum(axis=1)).mean()
    s = np.sqrt(2.0) / d if d > 1e-12 else 1.0
    T = np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1.0]])
    return T


def fit_homography(photo_pts, machine_pts):
    """Least-squares homography H (3x3) with H @ [u, v, 1] ~ [x, y, 1].
    Needs >= 4 correspondences, not all collinear."""
    P = np.asarray(photo_pts, float)
    M = np.asarray(machine_pts, float)
    if P.shape != M.shape or P.ndim != 2 or P.shape[1] != 2:
        raise ValueError("photo_pts and machine_pts must both be Nx2")
    n = len(P)
    if n < 4:
        raise ValueError(f"need >= 4 point pairs to fit a homography (got {n})")
    Tp, Tm = _normalize(P), _normalize(M)
    Ph = (Tp @ np.c_[P, np.ones(n)].T).T
    Mh = (Tm @ np.c_[M, np.ones(n)].T).T
    A = []
    for (u, v, _), (x, y, _) in zip(Ph, Mh):
        A.append([u, v, 1, 0, 0, 0, -x * u, -x * v, -x])
        A.append([0, 0, 0, u, v, 1, -y * u, -y * v, -y])
    A = np.asarray(A)
    _, s, vt = np.linalg.svd(A)
    if s[-2] < 1e-10:
        raise ValueError("degenerate point configuration (collinear anchors?)")
    Hn = vt[-1].reshape(3, 3)
    H = np.linalg.inv(Tm) @ Hn @ Tp
    return H / H[2, 2]


def apply_homography(H, pts):
    """Map Nx2 points through H. Returns Nx2 array."""
    P = np.asarray(pts, float)
    ph = np.c_[P, np.ones(len(P))] @ np.asarray(H).T
    return ph[:, :2] / ph[:, 2:3]


def residuals(H, photo_pts, machine_pts):
    """Per-point |H(photo) - machine| in mm."""
    d = apply_homography(H, photo_pts) - np.asarray(machine_pts, float)
    return np.sqrt((d ** 2).sum(axis=1))


def warp_photo(img, H, bounds, px_per_mm=8.0):
    """Warp ``img`` (HxWx3|4 uint8, row 0 = top of photo) into the machine
    frame. ``bounds`` = (x0, y0, x1, y1) mm of the output raster. Returns
    (rgba, extent): rgba row 0 = LOWEST y (ready for imshow(origin='lower')),
    alpha = 0 wherever the photo doesn't cover. Bilinear sampling."""
    img = np.asarray(img)
    if img.ndim != 3 or img.shape[2] not in (3, 4):
        raise ValueError("img must be HxWx3 or HxWx4")
    x0, y0, x1, y1 = bounds
    w = max(2, int(round((x1 - x0) * px_per_mm)))
    h = max(2, int(round((y1 - y0) * px_per_mm)))
    xs = x0 + (np.arange(w) + 0.5) / px_per_mm
    ys = y0 + (np.arange(h) + 0.5) / px_per_mm
    X, Y = np.meshgrid(xs, ys)                      # row j -> ys[j] (y-up)
    Hinv = np.linalg.inv(np.asarray(H, float))
    ph = np.stack([X, Y, np.ones_like(X)], axis=-1) @ Hinv.T
    U = ph[..., 0] / ph[..., 2]
    V = ph[..., 1] / ph[..., 2]

    ih, iw = img.shape[:2]
    inside = (U >= 0) & (U <= iw - 1) & (V >= 0) & (V <= ih - 1)
    Uc = np.clip(U, 0, iw - 1)
    Vc = np.clip(V, 0, ih - 1)
    u0 = np.floor(Uc).astype(int); v0 = np.floor(Vc).astype(int)
    u1 = np.minimum(u0 + 1, iw - 1); v1 = np.minimum(v0 + 1, ih - 1)
    fu = (Uc - u0)[..., None]; fv = (Vc - v0)[..., None]
    rgb = img[..., :3].astype(np.float32)
    samp = ((rgb[v0, u0] * (1 - fu) + rgb[v0, u1] * fu) * (1 - fv)
            + (rgb[v1, u0] * (1 - fu) + rgb[v1, u1] * fu) * fv)
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = np.clip(samp, 0, 255).astype(np.uint8)
    out[..., 3] = np.where(inside, 255, 0)
    return out, (x0, x1, y0, y1)
