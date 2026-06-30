"""Job/Tool parameter dataclasses and SRM-20 defaults (see docs/design.md §4)."""
import math
from dataclasses import dataclass


@dataclass
class TraceJob:
    bit_diameter: float = 0.4    # mm (1/64") — flat endmill cut width
    cut_depth: float = 0.15      # mm, single pass (validated on the SRM-20 with a
                                 # sharp flat endmill; 0.10 left thin copper bridges)
    offsets: int = 2             # isolation passes; -1 = clear all copper
    stepover: float = 0.5        # fraction of bit diameter
    xy_feed: float = 4.0         # mm/s
    plunge_feed: float = 1.0     # mm/s
    travel_z: float = 2.0        # mm
    # --- V-bit (engraving bit) support -------------------------------------
    # A V-bit's cut width grows with depth, so for tight SMD traces we drive it
    # "width-first": the operator sets target_width and the depth is back-solved.
    # tool_type == "flat" keeps the original flat-endmill behaviour untouched.
    tool_type: str = "flat"      # "flat" | "vbit"
    tip_diameter: float = 0.1    # mm — flat at the very tip of the V (T)
    included_angle: float = 30.0  # deg — full included angle of the V (theta)
    target_width: float = 0.2    # mm — desired effective cut width for a V-bit (W)

    # -- V-bit geometry: W = T + 2*D*tan(theta/2), and its inverse ----------
    def width_at_depth(self, depth):
        """Effective cut width of the V-bit at cut depth ``depth`` (mm)."""
        half = math.radians(self.included_angle) / 2.0
        return self.tip_diameter + 2.0 * depth * math.tan(half)

    def depth_for_width(self, width):
        """Cut depth (mm) needed to reach effective width ``width``. Clamped at
        0: a width at or below the tip diameter is the tip alone (no plunge)."""
        half = math.radians(self.included_angle) / 2.0
        t = math.tan(half)
        if t <= 0:
            return 0.0
        return max(0.0, (width - self.tip_diameter) / (2.0 * t))

    def effective_cut_depth(self):
        """Depth the cut should plunge to. Flat: the configured ``cut_depth``.
        V-bit: the depth that yields ``target_width`` (width-first)."""
        if self.tool_type == "vbit":
            return self.depth_for_width(self.target_width)
        return self.cut_depth

    def effective_diameter(self):
        """Cut width the toolpath engine should isolate by. Flat: the bit
        diameter. V-bit: the width at the (derived) cut depth — i.e. the
        achievable ``target_width`` once depth is clamped to >= 0."""
        if self.tool_type == "vbit":
            return self.width_at_depth(self.effective_cut_depth())
        return self.bit_diameter

    def width_sensitivity(self):
        """How fast the cut width changes with depth: dW/dD = 2*tan(theta/2).
        For a flat endmill this is 0 (width is depth-independent). This is the
        amplification factor from a surface-height error to a trace-width error,
        which is why a V-bit must run over a dense bed-leveling mesh."""
        if self.tool_type != "vbit":
            return 0.0
        return 2.0 * math.tan(math.radians(self.included_angle) / 2.0)


@dataclass
class DrillJob:
    bit_diameter: float = 0.8    # mm — the drill bit / end mill in the spindle
    single_bit: bool = True      # DEFAULT: one bit for everything -> one file,
                                 #          plunge holes that fit, interpolate (circle
                                 #          out) larger ones. We almost always run a
                                 #          single bit. Set False to opt into one file
                                 #          per hole diameter, each plunged with a
                                 #          matching bit (multi-bit / bit-change run).
    cut_depth: float = 0.6       # mm per peck
    total_depth: float = 1.8     # mm (through 1.6 mm board)
    peck_retract: float = 0.5    # mm above the surface to lift BETWEEN pecks of one
                                 # hole (chip clearing). The full travel_z retract
                                 # only happens when leaving the hole for the next.
    xy_feed: float = 4.0
    plunge_feed: float = 1.0
    travel_z: float = 2.0


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


@dataclass
class BoardConfig:
    thickness: float = 1.6       # mm
