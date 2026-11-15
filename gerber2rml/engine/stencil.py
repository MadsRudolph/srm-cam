"""The solder paste stencil for a board, cut from steel foil on the xTool F1 Ultra.

The paste layer (B.Paste or F.Paste) says where paste goes. The stencil is a sheet
of 0.1 mm stainless with a hole over each of those places, cut by the fiber
laser. This module makes the holes from the same Gerber folder the mill's files
came from. It is the solder mask file's sibling (``engine/soldermask.py``) and
shares its reader, its mirroring rule and its DXF writer. Three things are its
own:

Kerf, not registration. A mask opening is shrunk so a registration error leaves
ink on the pad. A stencil hole is shrunk because the beam is not a line: it
removes about :data:`DEFAULT_KERF` mm of steel around the path it follows, so a
hole drawn at pad size comes out a kerf too big. Each hole is drawn half a kerf
smaller per side. 80 um was measured on the F1 Ultra in 0.1 mm 304 stainless.

Mirrored like the copper. A single-sided board's paste goes on the milled face,
B.Cu, which lies face up when the stencil goes on, exactly as the mask's does.
So B.Paste is mirrored once and F.Paste is not, and the file name says which.

Holes that print. Paste only leaves a hole cleanly when the hole's area is big
next to its wall: the area ratio, area / (perimeter x foil thickness), should
be at least :data:`MIN_AREA_RATIO`. Smaller holes are kept but reported, and so
is a hole the kerf shrink made vanish.

The outline goes into the file as well, on its own layer: the laser marks it so
the stencil can be lined up with the board, and it places the job on the bed.
"""
from dataclasses import dataclass, field
from pathlib import Path

from gerbonara import GerberFile
from shapely.affinity import scale, translate
from shapely.geometry import Polygon

from gerber2rml.engine import soldermask
from gerber2rml.engine.soldermask import (
    LAYER_OUTLINE, _SLIVER_MM2, _layer_to_shapely, _polygons, _read_outline,
    _size, shapes_dxf_text)
from gerber2rml.loader import _find_layer

DEFAULT_KERF = 0.08        # mm, total: each hole is drawn kerf/2 smaller per side
MAX_KERF = 0.4
DEFAULT_FOIL = 0.1         # mm, the stencil steel
MIN_AREA_RATIO = 0.66      # IPC-7525: below this paste tends to stay in the hole

LAYER_APERTURES = "STENCIL_APERTURES"
soldermask._COLOUR.setdefault(LAYER_APERTURES, 5)     # blue, like the mask's

_PASTE_PATTERNS = {"bottom": ("*-B_Paste.*", "*.gbp"),
                   "top": ("*-F_Paste.*", "*.gtp")}
_LAYER_NAME = {"bottom": "B.Paste", "top": "F.Paste"}

__all__ = ["DEFAULT_KERF", "DEFAULT_FOIL", "LAYER_APERTURES", "LAYER_OUTLINE",
           "StencilError", "StencilArtwork", "paste_layer_path", "build_stencil",
           "stencil_filename", "write_stencil_dxf", "area_ratio"]


class StencilError(ValueError):
    """Why this folder cannot give a stencil, in words for the operator."""


def area_ratio(poly, foil=DEFAULT_FOIL):
    """Hole area over wall area, for a hole cut through ``foil`` mm of steel."""
    return poly.area / (poly.exterior.length * foil) if poly.exterior.length else 0.0


@dataclass
class StencilArtwork:
    """One face's stencil holes and the board outline, in the laser's frame.

    Same frame as the mask file: mm, Y up, the outline's lower-left corner at
    (0, 0)."""
    side: str
    source: Path
    mirrored: bool
    kerf: float
    foil: float
    apertures: list                                 # shapely Polygons
    outline: Polygon
    vanished: list = field(default_factory=list)    # (x, y, w, h)
    poor_release: list = field(default_factory=list)   # (x, y, ratio)

    @property
    def size(self):
        x0, y0, x1, y1 = self.outline.bounds
        return x1 - x0, y1 - y0

    def warnings(self):
        out = []
        if self.vanished:
            x, y, w, h = self.vanished[0]
            n = len(self.vanished)
            out.append(f"{n} paste hole{'' if n == 1 else 's'} vanished: a "
                       f"{w:.2f} x {h:.2f} mm pad at X{x:.2f} Y{y:.2f} is smaller "
                       f"than the {self.kerf:.2f} mm kerf. It gets no paste.")
        if self.poor_release:
            x, y, r = min(self.poor_release, key=lambda t: t[2])
            n = len(self.poor_release)
            out.append(f"{n} hole{'' if n == 1 else 's'} may not release paste "
                       f"cleanly (area ratio under {MIN_AREA_RATIO} in "
                       f"{self.foil:g} mm foil); the worst, {r:.2f}, at "
                       f"X{x:.2f} Y{y:.2f}. Check those pads after printing.")
        return out


def paste_layer_path(folder, side="bottom"):
    """The paste Gerber for ``side`` in ``folder``, or None."""
    return _find_layer(folder, *_PASTE_PATTERNS[side])


def build_stencil(folder, *, side="bottom", kerf=DEFAULT_KERF, mirror=None,
                  foil=DEFAULT_FOIL):
    """Read one face's paste layer and the outline from a Gerber folder.

    ``mirror`` defaults to the face: the bottom is mirrored like the copper,
    the top is not."""
    folder = Path(folder)
    if not 0 <= kerf <= MAX_KERF:
        raise StencilError(f"The kerf must be between 0 and {MAX_KERF} mm.")
    if mirror is None:
        mirror = side == "bottom"
    path = paste_layer_path(folder, side)
    if path is None:
        other = "top" if side == "bottom" else "bottom"
        there = paste_layer_path(folder, other)
        raise StencilError(
            f"No {_LAYER_NAME[side]} Gerber in {folder}, so there is nothing to "
            f"make the stencil from."
            + (f" There is an {_LAYER_NAME[other]} ({there.name}): the paste is on "
               f"the other face." if there else "")
            + f" In KiCad's Plot dialog, tick {_LAYER_NAME[side]} as well and plot "
              f"into this same folder.")
    edge = _find_layer(folder, "*-Edge_Cuts.*", "*.gm1")
    if edge is None:
        raise StencilError(f"No board outline (Edge.Cuts) Gerber in {folder}. The "
                           f"stencil needs it to line up with the board.")
    outline = _read_outline(edge)
    if outline.is_empty:
        raise StencilError(f"{edge.name} has no outline in it.")
    pads = _polygons(_layer_to_shapely(GerberFile.open(str(path))))
    if not pads:
        raise StencilError(f"{path.name} is empty: no pad on {_LAYER_NAME[side]} "
                           f"asks for paste.")

    if mirror:
        outline = scale(outline, xfact=-1, yfact=1, origin=(0, 0))
        pads = [scale(p, xfact=-1, yfact=1, origin=(0, 0)) for p in pads]
    x0, y0, _, _ = outline.bounds
    outline = translate(outline, -x0, -y0)
    pads = [translate(p, -x0, -y0) for p in pads]

    apertures, vanished, poor = [], [], []
    half = kerf / 2
    for pad in pads:
        small = pad.buffer(-half, join_style="mitre") if half else pad
        parts = [p for p in _polygons(small) if p.area >= _SLIVER_MM2]
        cx, cy = pad.representative_point().coords[0]
        if not parts:
            vanished.append((cx, cy, *_size(pad)))
            continue
        # The ratio is of the hole as cut, which is the pad itself.
        r = area_ratio(pad, foil)
        if r < MIN_AREA_RATIO:
            poor.append((cx, cy, r))
        apertures.extend(parts)
    return StencilArtwork(side=side, source=path, mirrored=mirror, kerf=kerf,
                          foil=foil, apertures=apertures, outline=outline,
                          vanished=vanished, poor_release=poor)


def stencil_filename(name, art):
    state = "mirrored" if art.mirrored else "not_mirrored"
    return f"{name}_stencil_{art.side}_{state}.dxf"


def write_stencil_dxf(art, out_dir, name):
    """Write the stencil DXF into ``out_dir``. Returns its path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / stencil_filename(name, art)
    path.write_text(shapes_dxf_text(art.apertures, art.outline, LAYER_APERTURES),
                    encoding="ascii")
    return path
