"""Small, separately fired coupons for SRM CAM's native vector path writer.

No XCS fill recipe, automatic exposure sweep, outline engraving, or automatic
repeat. Stages 2 and 3 require measurements from the preceding experiments.
"""
from dataclasses import dataclass
import math

from shapely.affinity import scale, translate
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from gerber2rml.engine import xtool

SIZE = 40.0
STAGES = ("Single lines", "Spacing", "Corners and pads")


@dataclass
class Coupon:
    stage: str
    cells: list  # each is a list of open/closed paths in local bed mm (Y down)
    labels: list
    width: float = 0.0
    pitch: float = 0.0
    rings: int = 6

    def artwork(self):
        # Cell envelopes support selection; the GUI draws the exact vectors.
        envelopes = []
        for paths in self.cells:
            points = [p for path in paths for p in path]
            xs, ys = zip(*points)
            envelopes.append(box(min(xs)-0.2, SIZE-max(ys)-0.2,
                                 max(xs)+0.2, SIZE-min(ys)+0.2))
        return xtool.LaserArt(kind="calibration", apertures=envelopes,
                              outline=box(0, 0, SIZE, SIZE),
                              note="40 × 40 mm · vectors only · one cell, one pass")


def make_coupon(stage="Single lines", *, width=0.0, pitch=0.0, rings=6):
    if stage not in STAGES:
        raise ValueError("Unknown copper calibration stage.")
    if not 1 <= rings <= 12:
        raise ValueError("Use 1–12 isolation rings for this coupon.")
    if stage != "Single lines" and (not math.isfinite(width) or not 0.002 <= width <= 0.2):
        raise ValueError("Enter the measured cleared line width (0.002–0.200 mm) first.")
    cells, labels = [], []
    for i in range(5):
        y = 5.0 + i * 7.0
        if stage == "Single lines":
            paths = [[(3.0, y), (15.0, y)]]
            label = f"Line {i+1} · 12 mm"
        elif stage == "Spacing":
            # Width is removal width at the chosen exposure, not optical spot size.
            step = max(0.001, round(width * (0.4 + i * 0.15), 3))
            count = math.ceil(0.25 / step) + 1
            paths = [[(3.0, y + j * step), (15.0, y + j * step)]
                     for j in range(count)]
            label = f"{step:.3f} mm pitch · {count} lines"
        else:
            if not math.isfinite(pitch) or not 0.001 <= pitch <= width:
                raise ValueError("Enter the tested pitch (at most the cleared line width) first.")
            line = LineString([(4, y), (14, y)]).buffer(0.15)
            shapes = [line,
                      LineString([(4, y-.8), (9, y-.8), (9, y+.8), (14, y+.8)]).buffer(.15),
                      unary_union([line, box(8, y-.65, 9.3, y+.65)]),
                      unary_union([LineString([(4, y-.3), (14, y-.3)]).buffer(.15),
                                   LineString([(4, y+.3), (14, y+.3)]).buffer(.15)]),
                      unary_union([line, Point(9, y).buffer(.65)])]
            copper = translate(scale(shapes[i], yfact=-1, origin=(0, 0)), yoff=SIZE)
            art = xtool.LaserArt(kind="traces", apertures=[], outline=box(0, 0, SIZE, SIZE),
                                 copper=copper)
            recipe = xtool.TracesRecipe(kerf=width, lines_per_cm=10/pitch,
                                       offsets=rings, spot_drills=False, passes=1)
            groups, _ = xtool.traces_rings(art, (0, 0), recipe)
            paths = [path for group in groups for path in group]
            label = ("Straight track", "Corners", "Square pad", "0.30 mm gap", "Round pad")[i]
        cells.append(paths)
        labels.append(label)
    return Coupon(stage, cells, labels, width, pitch, rings)


def vector_job(paths, *, power, speed, frequency):
    """Exactly one native vector pass over the supplied cell, no outline."""
    if not (math.isfinite(power) and 0 < power <= 100 and
            math.isfinite(speed) and 10 <= speed <= 5000 and
            math.isfinite(frequency) and 1 <= frequency <= 60):
        raise ValueError("Exposure is outside the laser controls' supported range.")
    if not paths or not any(len(p) > 1 for p in paths):
        raise ValueError("The selected calibration cell has no vectors.")
    xtool.check_on_bed(paths)
    body = xtool._passes(paths, power, speed, 1)
    if not body:
        raise ValueError("The selected cell collapses at laser output precision.")
    seconds = sum(xtool._length(p) for p in paths) / speed
    text = "\r\n".join(xtool._head("fiber", frequency, power/100) + body + xtool._TAIL)
    return xtool.Job(text, [len(paths)], seconds, 1, [paths],
                     [(0.0, seconds, 0, 0)])
