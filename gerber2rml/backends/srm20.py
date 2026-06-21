"""Roland SRM-20 backend (RML-1). Renders Move lists to RML.

Fixes the legacy bugs (docs/design.md §6): spindle ON via !MC1, XY feed via VS
and plunge via !VZ, clean Z-up header, 40 RML units/mm (SRM-20 = 0.025 mm/unit).
"""

SCALE = 40            # RML-1 units per mm
DEFAULT_RAPID = 15.0  # mm/s travel


def _u(mm: float) -> int:
    return int(round(mm * SCALE))


def render(toolpaths: list, xy_feed: float, plunge_feed: float,
           rapid_feed: float = DEFAULT_RAPID) -> str:
    out = ["^IN;!MC1;"]          # init + spindle ON
    mode = None                  # "cut" | "rapid"
    for tp in toolpaths:
        for m in tp:
            want = "rapid" if m.rapid else "cut"
            if want != mode:
                if m.rapid:
                    out.append(f"VS{rapid_feed};!VZ{rapid_feed};")
                else:
                    out.append(f"VS{xy_feed};!VZ{plunge_feed};")
                mode = want
            out.append(f"Z{_u(m.x)},{_u(m.y)},{_u(m.z)};")
    out.append("!MC0;^IN;")      # spindle OFF + reset
    return "\n".join(out) + "\n"
