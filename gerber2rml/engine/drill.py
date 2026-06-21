"""Drilling: Excellon holes -> peck-drill toolpaths."""
import math
from gerber2rml.toolpath import Move


def drill_holes(holes, job):
    """Generate peck-drill toolpaths (one per hole).

    holes: list of (x, y, diameter) tuples in mm. diameter is unused in v1
    (the operator loads one bit). Each hole: rapid over the hole, then peck
    cycles (plunge cut_depth, retract to travel_z) until total_depth, ending
    lifted.
    """
    pecks = max(1, math.ceil(job.total_depth / job.cut_depth))
    paths = []
    for (x, y, _dia) in holes:
        tp = [Move(x, y, job.travel_z, rapid=True)]
        for k in range(1, pecks + 1):
            depth = job.total_depth if k == pecks else k * job.cut_depth
            tp.append(Move(x, y, -depth))                    # peck down
            tp.append(Move(x, y, job.travel_z, rapid=True))  # retract
        paths.append(tp)
    return paths
