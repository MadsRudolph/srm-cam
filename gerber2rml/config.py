"""Job/Tool parameter dataclasses and SRM-20 defaults (see docs/design.md §4)."""
from dataclasses import dataclass


@dataclass
class TraceJob:
    bit_diameter: float = 0.4    # mm (1/64")
    cut_depth: float = 0.10      # mm, single pass
    offsets: int = 2             # isolation passes; -1 = clear all copper
    stepover: float = 0.5        # fraction of bit diameter
    xy_feed: float = 4.0         # mm/s
    plunge_feed: float = 1.0     # mm/s
    travel_z: float = 2.0        # mm
    mirror: bool = True


@dataclass
class DrillJob:
    cut_depth: float = 0.6       # mm per peck
    total_depth: float = 1.8     # mm (through 1.6 mm board)
    xy_feed: float = 4.0
    plunge_feed: float = 1.0
    travel_z: float = 2.0
    mirror: bool = True


@dataclass
class CutoutJob:
    bit_diameter: float = 0.8    # mm (1/32")
    cut_depth: float = 0.6       # mm per pass
    total_depth: float = 1.8
    tabs: int = 4
    tab_width: float = 1.5       # mm
    xy_feed: float = 4.0
    plunge_feed: float = 1.0
    travel_z: float = 2.0
    mirror: bool = True


@dataclass
class BoardConfig:
    thickness: float = 1.6       # mm
