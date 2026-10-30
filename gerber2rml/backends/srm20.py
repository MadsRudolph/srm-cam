"""Roland SRM-20 backend (RML-1). Renders Move lists to RML.

Fixes the legacy bugs (docs/design.md §6): spindle ON via !MC1, XY feed via VS
and plunge via !VZ, clean Z-up header, 100 RML units/mm.

Coordinate unit: the SRM-20's RML-1 software resolution is 0.01 mm/step, i.e.
100 units/mm (SRM-20 User's Manual R4, Specifications p. 151). This is NOT the
0.025 mm/step (40 units/mm) of the older MODELA/HP-GL RML dialect -- using 40
makes every coordinate come out at 40% of size, shrinking the job toward the
origin. NC code, by contrast, is written in real decimal mm and is unaffected.
"""
from gerber2rml.toolpath import Move

SCALE = 100           # RML-1 units per mm (SRM-20 = 0.01 mm/step, manual p.151)
DEFAULT_RAPID = 15.0  # mm/s travel


def _u(mm: float) -> int:
    return int(round(mm * SCALE))


def render(toolpaths: list[list[Move]], xy_feed: float, plunge_feed: float,
           rapid_feed: float = DEFAULT_RAPID, spindle: bool = True,
           header: list[str] | None = None, rpm: int | None = None) -> str:
    """``spindle=False`` keeps the spindle OFF for the whole program (the
    dry-run outline, which is watched from close up). ``rpm`` sets the speed
    with ``!RC`` before the spindle starts; None leaves the machine's own.

    The program never starts with a diagonal. The first ``Z x,y,z`` used to
    drive all three axes at once from wherever the bit happened to be, so a
    bit left low dragged across the stock on its way. Now it climbs to the
    highest Z the program uses (``!PZ`` sets that as the pen-up height, and
    ``PU`` lifts before it travels), and only then follows the moves.

    ``header`` is accepted and IGNORED. The G-code backend writes the
    per-operation notes there as ``( ... )`` comments; RML-1 has no comment
    syntax, so there is nowhere to put them and anything emitted would be
    parsed as a command. Accepting the argument keeps the two backends
    interchangeable at the call site.
    """
    speed = f"!RC{int(rpm)};" if spindle and rpm else ""
    out = ["^IN;" + speed + ("!MC1;" if spindle else "!MC0;")]   # init + spindle
    moves = [m for tp in toolpaths for m in tp]
    if moves:
        top = max(m.z for m in moves)
        out.append(f"VS{rapid_feed};!VZ{rapid_feed};")
        out.append(f"!PZ0,{_u(top)};PU{_u(moves[0].x)},{_u(moves[0].y)};")
    mode = None                  # "cut" | "rapid"
    for tp in toolpaths:
        for m in tp:
            want = "rapid" if m.rapid else "cut"
            if want != mode:
                if want == "rapid":
                    out.append(f"VS{rapid_feed};!VZ{rapid_feed};")
                else:
                    out.append(f"VS{xy_feed};!VZ{plunge_feed};")
                mode = want
            out.append(f"Z{_u(m.x)},{_u(m.y)},{_u(m.z)};")
    out.append("!MC0;^IN;")      # spindle OFF + reset
    return "\n".join(out) + "\n"
