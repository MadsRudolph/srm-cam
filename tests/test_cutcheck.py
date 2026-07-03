"""Photo-based uncut-copper detection on synthetic board photos."""
import numpy as np
import pytest
from shapely.geometry import box

from gerber2rml.engine.cutcheck import CutCheckError, detect_uncut

COPPER = (184, 115, 51)        # coppery orange
SUBSTRATE = (200, 190, 140)    # bare FR-4 tan... deliberately not too far
DARK = (40, 60, 35)            # cut channel showing substrate/fibreglass


def _board_photo(px_per_mm=10, w_mm=40, h_mm=30, bridge=None):
    """Synthetic machine-frame photo: copper everywhere on two pads separated
    by a vertical channel at x=20 (1 mm wide, dark). ``bridge``=(y0,y1) leaves
    that stretch of the channel copper-colored (uncut)."""
    W, H = w_mm * px_per_mm, h_mm * px_per_mm
    img = np.zeros((H, W, 4), np.uint8)
    img[..., :3] = COPPER
    img[..., 3] = 255
    # channel: x 19.5..20.5 dark (cut through)
    c0, c1 = int(19.5 * px_per_mm), int(20.5 * px_per_mm)
    img[:, c0:c1, :3] = DARK
    if bridge is not None:
        r0, r1 = int(bridge[0] * px_per_mm), int(bridge[1] * px_per_mm)
        img[r0:r1, c0:c1, :3] = COPPER          # this stretch never got cut
    return img, (0.0, float(w_mm), 0.0, float(h_mm))


def _geom_and_channel():
    copper = box(2, 2, 19.5, 28).union(box(20.5, 2, 38, 28))
    channel = [[(20.0, 2.0), (20.0, 28.0)]]     # centerline of the cut
    return copper, channel


def test_clean_channel_reports_full_coverage():
    img, extent = _board_photo()
    copper, channel = _geom_and_channel()
    r = detect_uncut(img, extent, channel, copper)
    assert r["boxes"] == []
    assert r["coverage"] > 0.97


def test_bridge_is_found_and_boxed():
    img, extent = _board_photo(bridge=(12.0, 16.0))
    copper, channel = _geom_and_channel()
    r = detect_uncut(img, extent, channel, copper)
    assert len(r["boxes"]) == 1
    x0, y0, x1, y1 = r["boxes"][0]
    # the box covers the bridged stretch (with bit padding) and sits on x=20
    assert x0 < 20.0 < x1
    assert y0 < 12.5 and y1 > 15.5
    assert r["coverage"] < 0.95


def test_single_speck_is_ignored():
    img, extent = _board_photo()
    px = 10
    img[int(7.0 * px):int(7.2 * px), int(19.6 * px):int(20.4 * px), :3] = COPPER
    copper, channel = _geom_and_channel()
    r = detect_uncut(img, extent, channel, copper)
    assert r["boxes"] == []                     # < min_run samples -> dust


def test_indistinguishable_colors_raise():
    img, extent = _board_photo()
    img[..., :3] = COPPER                       # channel same color as copper
    copper, channel = _geom_and_channel()
    with pytest.raises(CutCheckError):
        detect_uncut(img, extent, channel, copper)


def test_no_overlap_raises():
    img, extent = _board_photo()
    copper, channel = _geom_and_channel()
    with pytest.raises(CutCheckError):
        detect_uncut(img, (100.0, 140.0, 100.0, 130.0), channel, copper)


def test_bridge_found_without_copper_geometry():
    img, extent = _board_photo(bridge=(12.0, 16.0))
    _copper, channel = _geom_and_channel()
    r = detect_uncut(img, extent, channel, copper_geom=None)
    assert len(r["boxes"]) == 1
    x0, _y0, x1, _y1 = r["boxes"][0]
    assert x0 < 20.0 < x1
