"""Move dataclass + Toolpath alias: the engine<->backend contract."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Move:
    x: float
    y: float
    z: float
    rapid: bool = False


Toolpath = list  # list[Move]
