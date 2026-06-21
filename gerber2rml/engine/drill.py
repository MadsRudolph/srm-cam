"""Drilling: Excellon holes -> peck-drill toolpaths."""
from gerber2rml.toolpath import Move


def drill_holes(holes, job):
    """Generate peck-drill toolpaths for a list of holes.

    Args:
        holes: List of (x, y, diameter) tuples in mm.
        job: DrillJob with cut_depth, total_depth, travel_z.

    Returns:
        List[Toolpath] — one toolpath per hole.
    """
    paths = []
    for (x, y, _dia) in holes:
        tp = [Move(x, y, job.travel_z, rapid=True)]
        depth = 0.0
        while depth < job.total_depth:
            depth = min(depth + job.cut_depth, job.total_depth)
            tp.append(Move(x, y, -depth))                 # peck down
            tp.append(Move(x, y, job.travel_z, rapid=True))  # retract
        paths.append(tp)
    return paths
