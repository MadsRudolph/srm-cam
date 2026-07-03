"""Feed-card photo scoring on synthetic card photos."""
import numpy as np
import pytest

from gerber2rml.engine.cutcheck import CutCheckError
from gerber2rml.engine.feedscore import score_feed_card
from gerber2rml.engine.testcard import feed_ladder_layout

COPPER = (184, 115, 51)
DARK = (40, 60, 35)


def _card_photo(blocks, px=8, w_mm=80, h_mm=60, bad_feeds=(), torn_feeds=()):
    """Copper card; channels dark along every block's serpentine + land pair.
    Blocks in ``bad_feeds`` keep 40% of their serpentine copper (uncut);
    blocks in ``torn_feeds`` get their land painted dark (torn away)."""
    img = np.zeros((h_mm * px, w_mm * px, 4), np.uint8)
    img[..., :3] = COPPER
    img[..., 3] = 255

    def paint(p0, p1, half_w, color):
        n = int(max(abs(p1[0] - p0[0]), abs(p1[1] - p0[1])) * px * 2) + 1
        for i in range(n):
            t = i / max(n - 1, 1)
            x = p0[0] + (p1[0] - p0[0]) * t
            y = p0[1] + (p1[1] - p0[1]) * t
            r0 = int((y - half_w) * px); r1 = int((y + half_w) * px) + 1
            c0 = int((x - half_w) * px); c1 = int((x + half_w) * px) + 1
            img[max(r0, 0):r1, max(c0, 0):c1, :3] = color

    for b in blocks:
        serp = b["serpentine"]
        segs = list(zip(serp, serp[1:]))
        for k, (a, c) in enumerate(segs):
            if b["feed"] in bad_feeds and k >= int(len(segs) * 0.6):
                continue                     # leave the tail uncut (copper)
            paint(a, c, 0.4, DARK)
        # the tight pair around the land (channels at +-0.5 from the midline;
        # keep them narrow so the copper land strip survives 3x3 sampling)
        (lx0, ly), (lx1, _y) = b["land"]
        paint((lx0 - 0.5, ly - 0.5), (lx1 + 0.5, ly - 0.5), 0.22, DARK)
        paint((lx0 - 0.5, ly + 0.5), (lx1 + 0.5, ly + 0.5), 0.22, DARK)
        if b["feed"] in torn_feeds:
            paint((lx0, ly), (lx1, ly), 0.3, DARK)    # land destroyed
    return img, (0.0, float(w_mm), 0.0, float(h_mm))


def test_recommends_fastest_clean_feed():
    blocks, _anchors = feed_ladder_layout()
    img, extent = _card_photo(blocks, bad_feeds=(15.0,))
    r = score_feed_card(img, extent, blocks)
    by_feed = {b["feed"]: b for b in r["blocks"]}
    assert by_feed[15.0]["cut"] < 0.75          # the too-fast block reads dirty
    assert by_feed[12.0]["cut"] > 0.9
    assert r["recommended"] == 12.0


def test_torn_land_disqualifies_a_feed():
    blocks, _anchors = feed_ladder_layout()
    img, extent = _card_photo(blocks, torn_feeds=(12.0, 15.0))
    r = score_feed_card(img, extent, blocks)
    assert r["recommended"] == 10.0


def test_all_clean_recommends_fastest():
    blocks, _anchors = feed_ladder_layout()
    img, extent = _card_photo(blocks)
    r = score_feed_card(img, extent, blocks)
    assert r["recommended"] == 15.0


def test_anchor_corners_are_the_extreme_rings():
    blocks, anchors = feed_ladder_layout()
    labels = [a for a, _p in anchors]
    assert labels == ["bottom-left big ring", "bottom-right big ring",
                      "top-right big ring", "top-left big ring"]
    xs = [p[0] for _l, p in anchors]
    ys = [p[1] for _l, p in anchors]
    assert xs[0] == min(xs) and xs[1] == max(xs)
    assert ys[2] == max(ys) and ys[0] == min(ys)


def test_glare_photo_refuses():
    blocks, _anchors = feed_ladder_layout()
    img, extent = _card_photo(blocks)
    img[..., :3] = COPPER                       # everything one color
    with pytest.raises(CutCheckError):
        score_feed_card(img, extent, blocks)
