"""Machine-backend seam: a render function maps toolpaths -> machine program text."""
from typing import Callable
from gerber2rml.toolpath import Move

# (toolpaths, xy_feed, plunge_feed[, rapid_feed]) -> program text
RenderFn = Callable[..., str]
