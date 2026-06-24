"""Move dataclass + Toolpath alias: the engine<->backend contract."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Move:
    x: float
    y: float
    z: float
    rapid: bool = False


Toolpath = list  # list[Move]


def offset(paths, dx, dy):
    """Translate every move in a list of toolpaths by (dx, dy) mm. Used to place
    the whole job somewhere on the bed; Z is untouched. Returns the same list
    object when there is no shift, so callers pay nothing for the common case."""
    if not dx and not dy:
        return paths
    return [[Move(m.x + dx, m.y + dy, m.z, m.rapid) for m in tp] for tp in paths]
