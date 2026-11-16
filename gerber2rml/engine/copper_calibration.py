"""Small coupons for SRM CAM's native vector path writer.

Stage 1, "Find the exposure", is a grid of small real traces: in every cell
two parallel 0.4 mm tracks with a 0.3 mm gap, each ending in a pad, isolated
with the production concentric rings exactly as a board would be. The columns
are at different speeds and the rows at different pass counts, all at one
power, fired in one job. A single vector line only cuts a hairline, too thin
to judge whether copper is cleared; a ring band around real tracks is what the
board will get. The passes go round-robin, one pass on every line that still
needs one, then the next, so each line cools while the others are drawn (the
trick that keeps a stencil flat). Look for the cell that clears the copper with
the fewest passes and no charring.

Stages 2-4 then use that exposure: a single line to measure the cleared width,
spacing, then corners and pads. They require measurements from the stage
before. No XCS fill recipe and no outline engraving.
"""
from dataclasses import dataclass
import math

from shapely.affinity import scale, translate
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from gerber2rml.engine import xtool

SIZE = 40.0
EXPOSURE = "Find the exposure"
STAGES = (EXPOSURE, "Single lines", "Spacing", "Corners and pads")
GRID_SPEEDS = (300.0, 600.0, 1000.0, 2000.0)     # mm/s, the columns
GRID_PASSES = (5, 10, 20, 40)                     # the rows
GRID_LINE = 6.0                                   # mm, a cell's width


@dataclass
class Coupon:
    stage: str
    cells: list  # each is a list of open/closed paths in local bed mm (Y down)
    labels: list
    width: float = 0.0
    pitch: float = 0.0
    rings: int = 6
    # The exposure grid only: (speed mm/s, passes) per cell, and the grid's axes.
    exposures: list = None
    speeds: tuple = ()
    pass_counts: tuple = ()

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


def grid_layout(n_cols, n_rows):
    """(x of each column's line start, y of each row) in coupon mm, Y down."""
    left, top = 6.0, 7.0
    dx = (SIZE - left - 2.0 - GRID_LINE) / max(n_cols - 1, 1)
    dy = (SIZE - top - 3.0) / max(n_rows - 1, 1)
    return ([left + c * dx for c in range(n_cols)],
            [top + r * dy for r in range(n_rows)])


TRACE_W = 0.4          # mm, the test tracks
TRACE_GAP = 0.3        # mm between them: the hardest place to clear
PAD = 1.2              # mm square pads at the track ends


def trace_copper(x0, y):
    """Two parallel tracks with a pad at alternate ends, in coupon mm (Y down),
    starting at ``x0`` with the gap centred on ``y``."""
    half = (TRACE_W + TRACE_GAP) / 2
    a = LineString([(x0 + PAD, y - half), (x0 + GRID_LINE - 0.2, y - half)]).buffer(
        TRACE_W / 2, cap_style="flat")
    b = LineString([(x0 + 0.2, y + half), (x0 + GRID_LINE - PAD, y + half)]).buffer(
        TRACE_W / 2, cap_style="flat")
    pa = box(x0, y - half - PAD / 2, x0 + PAD, y - half + PAD / 2)
    pb = box(x0 + GRID_LINE - PAD, y + half - PAD / 2, x0 + GRID_LINE, y + half + PAD / 2)
    return unary_union([a, pa]), unary_union([b, pb])


def trace_cell(x0, y, *, rings=xtool.DEFAULT_TRACE_OFFSETS):
    """The isolation paths for one grid cell, from the production ring
    generator, in coupon mm (Y down)."""
    copper = unary_union(trace_copper(x0, y))
    copper = translate(scale(copper, yfact=-1, origin=(0, 0)), yoff=SIZE)
    art = xtool.LaserArt(kind="traces", apertures=[], outline=box(0, 0, SIZE, SIZE),
                         copper=copper)
    recipe = xtool.TracesRecipe(offsets=rings, spot_drills=False, passes=1)
    groups, _ = xtool.traces_rings(art, (0, 0), recipe)
    return [path for group in groups for path in group]


def make_coupon(stage=EXPOSURE, *, width=0.0, pitch=0.0, rings=6,
                speeds=GRID_SPEEDS, pass_counts=GRID_PASSES):
    if stage not in STAGES:
        raise ValueError("Unknown copper calibration stage.")
    if stage == EXPOSURE:
        speeds = tuple(float(v) for v in speeds)
        pass_counts = tuple(int(v) for v in pass_counts)
        if not 1 <= len(speeds) <= 6 or not 1 <= len(pass_counts) <= 6:
            raise ValueError("Use 1–6 speeds and 1–6 pass counts.")
        if any(not 10 <= v <= 5000 for v in speeds):
            raise ValueError("Speeds must be 10–5000 mm/s.")
        if any(not 1 <= n <= 200 for n in pass_counts):
            raise ValueError("Pass counts must be 1–200.")
        xs, ys = grid_layout(len(speeds), len(pass_counts))
        cells, labels, exposures = [], [], []
        for r, n in enumerate(pass_counts):
            for c, v in enumerate(speeds):
                cells.append(trace_cell(xs[c], ys[r], rings=rings))
                labels.append(f"{v:g} mm/s · {n} passes")
                exposures.append((v, n))
        return Coupon(stage, cells, labels, exposures=exposures,
                      speeds=speeds, pass_counts=pass_counts)
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


def vector_job(paths, *, power, speed, frequency, passes=1):
    """``passes`` native vector passes over the supplied cell, no outline."""
    if not (math.isfinite(power) and 0 < power <= 100 and
            math.isfinite(speed) and 10 <= speed <= 5000 and
            math.isfinite(frequency) and 1 <= frequency <= 60):
        raise ValueError("Exposure is outside the laser controls' supported range.")
    if not paths or not any(len(p) > 1 for p in paths):
        raise ValueError("The selected calibration cell has no vectors.")
    xtool.check_on_bed(paths)
    if not 1 <= int(passes) <= 200:
        raise ValueError("Use 1–200 passes.")
    body = xtool._passes(paths, power, speed, int(passes))
    if not body:
        raise ValueError("The selected cell collapses at laser output precision.")
    seconds = int(passes) * sum(xtool._length(p) for p in paths) / speed
    text = "\r\n".join(xtool._head("fiber", frequency, power/100) + body + xtool._TAIL)
    return xtool.Job(text, [len(paths)], seconds, int(passes), [paths],
                     [(0.0, seconds, 0, 0)])


def exposure_job(cells, exposures, *, power, frequency, rest_s=0.5):
    """The whole exposure grid in one file. ``cells`` are each cell's paths on
    the bed, ``exposures`` its (speed, passes). Round k draws every line that
    still needs a k-th pass, so no line gets its passes back to back, then the
    laser rests ``rest_s`` (off, S0): on a real board a track waits a whole
    board-pass between visits, and the late rounds here have few lines left."""
    if not (math.isfinite(power) and 0 < power <= 100 and
            math.isfinite(frequency) and 1 <= frequency <= 60):
        raise ValueError("Exposure is outside the laser controls' supported range.")
    if len(cells) != len(exposures) or not cells:
        raise ValueError("The grid has no cells.")
    xtool.check_on_bed([p for c in cells for p in c])
    body, secs, timeline = [], 0.0, []
    for k in range(max(n for _v, n in exposures)):
        t0 = secs
        for paths, (speed, n) in zip(cells, exposures):
            if k < n:
                body += xtool._passes(paths, power, speed, 1)
                secs += sum(xtool._length(p) for p in paths) / speed
        timeline.append((t0, secs, 0, k))
        if rest_s > 0 and k < max(n for _v, n in exposures) - 1:
            body += xtool._rest(cells[0][0][0], rest_s)
            secs += rest_s
    text = "\r\n".join(xtool._head("fiber", frequency, power/100) + body + xtool._TAIL)
    return xtool.Job(text, [len(cells)], secs, max(n for _v, n in exposures),
                     [[p for c in cells for p in c]], timeline)
