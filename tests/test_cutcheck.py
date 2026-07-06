"""Photo-based failed-channel detection on synthetic board photos.

Convention learned from the real MegaPCB ground truth: a CUT channel reads
BRIGHT across its profile (exposed substrate + burred edges); a failed one
(never cut, or too shallow) reads like the surrounding copper.
"""
import numpy as np
import pytest
from shapely.geometry import box

from gerber2rml.engine.cutcheck import CutCheckError, detect_uncut

COPPER = (184, 115, 51)        # coppery
BRIGHT = (235, 232, 220)       # cut channel: exposed substrate catching light


def _board_photo(px_per_mm=16, w_mm=40, h_mm=30, bridge=None):
    """Synthetic machine-frame photo: copper everywhere, one vertical channel
    at x=20 (1 mm wide, BRIGHT = properly cut). ``bridge``=(y0,y1) leaves that
    stretch copper-colored (failed)."""
    W, H = w_mm * px_per_mm, h_mm * px_per_mm
    img = np.zeros((H, W, 4), np.uint8)
    img[..., :3] = COPPER
    img[..., 3] = 255
    c0, c1 = int(19.5 * px_per_mm), int(20.5 * px_per_mm)
    img[:, c0:c1, :3] = BRIGHT
    if bridge is not None:
        r0, r1 = int(bridge[0] * px_per_mm), int(bridge[1] * px_per_mm)
        img[r0:r1, c0:c1, :3] = COPPER          # this stretch never got cut
    return img, (0.0, float(w_mm), 0.0, float(h_mm))


def _channel():
    return [[(20.0, 2.0), (20.0, 28.0)]]


def test_clean_channel_reports_full_coverage():
    img, extent = _board_photo()
    r = detect_uncut(img, extent, _channel())
    assert r["boxes"] == []
    assert r["coverage"] == 1.0
    assert r["decided_frac"] > 0.9


def test_bridge_is_found_and_boxed():
    img, extent = _board_photo(bridge=(10.0, 16.0))
    r = detect_uncut(img, extent, _channel())
    assert len(r["boxes"]) == 1
    x0, y0, x1, y1 = r["boxes"][0]
    assert x0 < 20.0 < x1
    assert y0 < 11.0 and y1 > 15.0             # covers the failed stretch
    assert r["coverage"] < 0.95


def test_single_speck_is_ignored():
    img, extent = _board_photo()
    px = 16
    img[int(7.0 * px):int(7.3 * px), int(19.6 * px):int(20.4 * px), :3] = COPPER
    r = detect_uncut(img, extent, _channel())
    assert r["boxes"] == []                     # one dusty sample != a region


def test_everything_copper_refuses():
    img, extent = _board_photo()
    img[..., :3] = COPPER                       # no cut signature anywhere
    with pytest.raises(CutCheckError):
        detect_uncut(img, extent, _channel())


def test_no_overlap_raises():
    img, extent = _board_photo()
    with pytest.raises(CutCheckError):
        detect_uncut(img, (100.0, 140.0, 100.0, 130.0), _channel())


def test_copper_geom_param_still_accepted():
    img, extent = _board_photo(bridge=(10.0, 16.0))
    copper = box(2, 2, 19.5, 28).union(box(20.5, 2, 38, 28))
    r = detect_uncut(img, extent, _channel(), copper_geom=copper)
    assert len(r["boxes"]) == 1
