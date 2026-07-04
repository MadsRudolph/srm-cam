"""Score a cut feed-ladder card from a photo and recommend the feed.

After milling the card on scrap, photograph it and register the photo with
the 4 big pad rings (same click-anchors flow as the board overlay). Each
block is then judged on two things:

- **cut**: fraction of the serpentine channel that actually reads as cut.
  Too-fast feeds deflect the tool and leave copper in the channel.
- **land**: fraction of the thin land between the tight channel pair that
  still reads as copper. Too-fast feeds tear it away.

The recommendation is the FASTEST feed whose two scores are within a small
tolerance of the best block's — i.e. as clean as the slow blocks, minus
measurement noise.
"""
import numpy as np

from gerber2rml.engine.cutcheck import (CutCheckError, _sample, _to_px, _walk)


def score_feed_card(photo_rgba, extent, blocks, step=0.25, tol=0.06):
    """``blocks`` from :func:`testcard.feed_ladder_layout`; photo warped to
    machine frame (row 0 = lowest y) with ``extent`` = (x0, x1, y0, y1) mm.

    Returns ``{"blocks": [{feed, cut, land}], "recommended": feed|None}``.
    """
    img = np.asarray(photo_rgba)
    if img.ndim != 3 or img.shape[2] != 4:
        raise CutCheckError("photo must be an RGBA array")

    # references learned from the card itself: copper = between the serpentine
    # channels (the lands are half a pitch above each pass), channel = the
    # median along ALL serpentines (most of every card cuts fine).
    chan, copper = [], []
    per_block = []
    for b in blocks:
        pts = _walk(list(b["serpentine"]), step)
        vals = []
        for (x, y) in pts:
            s = _sample(img, *_to_px(extent, img.shape, x, y))
            if s is not None:
                vals.append((x, y, s))
                chan.append(s)
                c = _sample(img, *_to_px(extent, img.shape, x, y + 0.8))
                if c is not None:
                    copper.append(c)
        per_block.append(vals)
    if sum(len(v) for v in per_block) < 50:
        raise CutCheckError("photo covers too little of the card — check the "
                            "anchor clicks")
    cu = np.median(np.array(copper), axis=0)
    ch = np.median(np.array(chan), axis=0)
    if float(np.linalg.norm(cu - ch)) < 25:
        raise CutCheckError("copper and channel colors are too similar in this "
                            "photo — more light / less glare needed")

    def looks_cut(s):
        return float(np.linalg.norm(s - ch)) < float(np.linalg.norm(s - cu))

    out = []
    for b, vals in zip(blocks, per_block):
        cut = (sum(1 for (_x, _y, s) in vals if looks_cut(s)) / len(vals)
               if vals else 0.0)
        lvals = []
        for (x, y) in _walk(list(b["land"]), step):
            s = _sample(img, *_to_px(extent, img.shape, x, y))
            if s is not None:
                lvals.append(s)
        land = (sum(1 for s in lvals if not looks_cut(s)) / len(lvals)
                if lvals else 0.0)
        out.append({"feed": b["feed"], "cut": cut, "land": land})

    best_cut = max(o["cut"] for o in out)
    best_land = max(o["land"] for o in out)
    ok = [o for o in out
          if o["cut"] >= best_cut - tol and o["land"] >= best_land - tol]
    rec = max((o["feed"] for o in ok), default=None)
    return {"blocks": out, "recommended": rec}
