"""The laser file for marking the silkscreen onto a milled board.

The mill cuts the copper; the fiber laser marks the component side with the
silkscreen: reference designators, outlines, polarity marks. The laser needs a
drawing of that artwork, closed shapes it can fill, and the board outline to
place it by, in mm at 1:1. This module makes that drawing from the same Gerber
folder the mill's files came from, so the two cannot be from different revisions
of the board. Nothing here touches the milling files.

It is the solder mask file's sibling (``engine/soldermask.py``) and shares its
reader and its DXF writer. Three things are its own:

Which face, which way. KiCad plots every layer seen from the top. A single-sided
board is milled on B.Cu and marked on the other face, F.Silkscreen, which lies
face up on the laser exactly as KiCad drew it: not mirrored, whatever the
copper's Mirror setting. That is the ``_silk_top.dxf`` the kicad-cli flow has
always made. A double-sided job also gets B.Silkscreen when the folder has it,
mirrored once like the bottom copper; a board with nothing on its bottom silk is
normal and gets no bottom file.

Strokes become shapes. Silkscreen is drawn with round pens, so every line and
every letter is buffered to its real width and the lot is unioned. Overlapping
strokes become one shape, and the inside of an O stays a loop of its own, which
the laser's compound fill leaves unmarked.

Kept on the board. Artwork that runs over the board edge would be marked into
the spoilboard or the air, so it is clipped to the outline and the clip is
reported. Nothing is shrunk: unlike a mask opening, a misplaced line of silk
costs nothing electrical.
"""
from dataclasses import dataclass
from pathlib import Path

from gerbonara import GerberFile
from shapely.affinity import scale, translate
from shapely.geometry import Polygon

from gerber2rml.engine.soldermask import (
    LAYER_OUTLINE, LAYER_SILKSCREEN, _SLIVER_MM2, _layer_to_shapely, _polygons,
    _read_outline, shapes_dxf_text)
from gerber2rml.loader import _find_layer

LAYER_SILK = LAYER_SILKSCREEN
__all__ = ["LAYER_SILK", "LAYER_OUTLINE", "SilkError", "SilkArtwork",
           "silk_layer_path", "build_silk", "silk_filename", "write_silk_dxf",
           "write_silk_files"]

_SILK_PATTERNS = {"top": ("*-F_Silkscreen.*", "*-F_SilkS.*", "*.gto"),
                  "bottom": ("*-B_Silkscreen.*", "*-B_SilkS.*", "*.gbo")}
_LAYER_NAME = {"top": "F.Silkscreen", "bottom": "B.Silkscreen"}
_CLIP_MM2 = 0.01          # less than this off the board is a rounding, not a clip


class SilkError(ValueError):
    """Why this folder cannot give a silkscreen file, in words for the operator."""


@dataclass
class SilkArtwork:
    """One face's silkscreen and outline, in the laser's frame.

    The outline's lower-left corner is at (0, 0), so the numbers are the same
    whatever origin KiCad plotted from.
    """
    side: str                 # "top" or "bottom"
    source: Path              # the silkscreen Gerber it was read from
    mirrored: bool
    shapes: list              # shapely Polygons, clipped to the board
    outline: Polygon
    clipped_mm2: float = 0.0  # artwork that lay off the board and was cut away

    def warnings(self):
        """What the operator should know about this file, in words."""
        if self.clipped_mm2 >= _CLIP_MM2:
            return [f"{self.clipped_mm2:.1f} mm² of the {_LAYER_NAME[self.side]} "
                    f"artwork ran past the board edge and was cut off at the "
                    f"outline. Check the text near the edge in KiCad."]
        return []


def silk_layer_path(folder, side="top"):
    """The silkscreen Gerber for ``side`` in ``folder``, or None."""
    return _find_layer(folder, *_SILK_PATTERNS[side])


def build_silk(folder, *, side="top", mirror=None):
    """Read one face's silkscreen and the outline from a Gerber folder.

    ``mirror`` defaults to the face's own way: the top as plotted, the bottom
    mirrored. Raises :class:`SilkError` when the folder cannot give a file: the
    layer is missing or empty, or there is no outline to place it by.
    """
    folder = Path(folder)
    if mirror is None:
        mirror = side == "bottom"
    path = silk_layer_path(folder, side)
    if path is None:
        raise SilkError(
            f"No {_LAYER_NAME[side]} Gerber in {folder}, so there is nothing to "
            f"make the silkscreen file from. In KiCad's Plot dialog, tick "
            f"{_LAYER_NAME[side]} as well, plot into this same folder, and try "
            f"again.")
    edge = _find_layer(folder, "*-Edge_Cuts.*", "*.gm1")
    if edge is None:
        raise SilkError(f"No board outline (Edge.Cuts) Gerber in {folder}. The "
                        f"silkscreen file needs it to place the artwork on the "
                        f"laser.")
    outline = _read_outline(edge)
    if outline.is_empty:
        raise SilkError(f"{edge.name} has no outline in it.")
    drawn = _layer_to_shapely(GerberFile.open(str(path)))
    if drawn.is_empty:
        raise SilkError(
            f"{path.name} is empty: {_LAYER_NAME[side]} has nothing drawn on it. "
            f"Re-plot it from KiCad once the board has its silkscreen.")

    # Clipped in KiCad's frame, before anything moves, so the two cannot drift.
    on_board = drawn.intersection(outline)
    clipped = drawn.area - on_board.area

    if mirror:
        outline = scale(outline, xfact=-1, yfact=1, origin=(0, 0))
        on_board = scale(on_board, xfact=-1, yfact=1, origin=(0, 0))
    x0, y0, _, _ = outline.bounds
    outline = translate(outline, -x0, -y0)
    on_board = translate(on_board, -x0, -y0)
    shapes = [p for p in _polygons(on_board) if p.area >= _SLIVER_MM2]
    if not shapes:
        raise SilkError(
            f"Everything on {path.name} lies outside the board outline. The "
            f"silkscreen and Edge.Cuts look like they come from different plots.")
    return SilkArtwork(side=side, source=path, mirrored=mirror, shapes=shapes,
                       outline=outline, clipped_mm2=clipped)


def dxf_text(art):
    """The artwork as the text of a DXF file: mm, 1:1, two named layers."""
    return shapes_dxf_text(art.shapes, art.outline, LAYER_SILK)


def silk_filename(name, art):
    """``<name>_silk_top_not_mirrored.dxf``: the face and the mirroring, the two
    things the operator must not get wrong at the laser."""
    state = "mirrored" if art.mirrored else "not_mirrored"
    return f"{name}_silk_{art.side}_{state}.dxf"


def write_silk_dxf(art, out_dir, name):
    """Write one face's file into ``out_dir``. Returns its path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / silk_filename(name, art)
    path.write_text(dxf_text(art), encoding="ascii")
    return path


def write_silk_files(folder, out_dir, name, *, double_sided=False):
    """Write the job's silkscreen file or files. Returns ``[(path, artwork), ...]``.

    Every job gets the top face, F.Silkscreen, and a missing one raises
    :class:`SilkError`. A double-sided job also gets the bottom face when the
    folder has a B.Silkscreen with something on it; without one it is skipped
    quietly, since most boards have nothing there.
    """
    out = [build_silk(folder, side="top")]
    if double_sided and silk_layer_path(folder, "bottom") is not None:
        try:
            out.append(build_silk(folder, side="bottom"))
        except SilkError:
            pass        # an empty bottom silk: nothing to mark on that face
    return [(write_silk_dxf(a, out_dir, name), a) for a in out]
