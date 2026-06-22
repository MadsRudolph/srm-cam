"""G-code (RS-274 / NC) backend for the SRM-20 in NC-code command mode.

VPanel streams the resulting ``.nc`` via *Cut -> Output* exactly like an RML
job (the machine must be set to the **NC code** command set). The output
follows the conventions of the Fusion 360 post that already runs on the lab's
SRM-20:

  * millimetres, absolute (``G21 G90``), feed-per-minute (``G94``)
  * a **G54 work origin** -- the XY/Z zero you set in VPanel, NOT machine zero
  * safe-Z retract via ``G28`` between moves and at end of program
  * spindle on/off with ``M3`` / ``M5``, program end ``M30``

gerber2rml's engine emits already-linearised :class:`Move` lists, so we only
need ``G0`` (rapid) and ``G1`` (feed) -- no arcs (``G2/G3``) or canned drill
cycles (``G81``). Rapids lift Z first, then traverse, so the tool never drags
through copper.

Feeds arrive in mm/s (gerber2rml convention) and are converted to mm/min for
``G94``.
"""
from gerber2rml.toolpath import Move

DEFAULT_RAPID = 15.0   # mm/s (informational; G0 uses the machine rapid rate)
DEFAULT_RPM = 7000     # SRM-20 spindle tops out ~7000 rpm
PLUNGE_CLEARANCE = 0.5 # mm above the work surface (Z0) to rapid down to before a
                       # plunge, so we don't creep through air at the plunge feed
EPS = 1e-6


def _f(v: float) -> str:
    """Format a coordinate/feed: trim trailing zeros but always keep a decimal
    point (``4.0 -> '4.'``, ``11.246 -> '11.246'``, ``-1.76 -> '-1.76'``).
    A trailing point matters: some NC interpreters read bare integers as
    machine units."""
    s = f"{v:.3f}".rstrip("0")
    return s if s.endswith(".") else s


def render(toolpaths: list[list[Move]], xy_feed: float, plunge_feed: float,
           rapid_feed: float = DEFAULT_RAPID, rpm: int = DEFAULT_RPM,
           travel_z: float = 2.0) -> str:
    xy_fpm = xy_feed * 60.0          # mm/s -> mm/min for G94
    plunge_fpm = plunge_feed * 60.0

    out = [
        "%",
        "O0001",
        "( gerber2rml - SRM-20 NC )",
        "G90 G94 G17",               # absolute, feed/min, XY plane
        "G21",                       # millimetres
        "G91",                       # incremental for the homing line...
        "G28 Z0.",                   # ...retract Z to machine home (safe)
        "G90",                       # back to absolute
        "G49",                       # cancel any tool-length offset (G43) left
                                     #   active by a prior Fusion/NC job, so Z is
                                     #   purely G54-relative (the VPanel zero)
        "G54",                       # work coordinate origin (set in VPanel)
        f"S{int(round(rpm))} M3",    # spindle on, clockwise
    ]

    cx = cy = cz = None              # current machine position (work coords)
    feed = None                      # current modal feedrate

    def changed(a, b):
        return a is None or abs(a - b) > EPS

    for tp in toolpaths:
        for m in tp:
            if m.rapid:
                # Lift Z first, then traverse XY -- never plunge during a rapid.
                if changed(cz, m.z):
                    out.append(f"G0 Z{_f(m.z)}")
                    cz = m.z
                if changed(cx, m.x) or changed(cy, m.y):
                    out.append(f"G0 X{_f(m.x)} Y{_f(m.y)}")
                    cx, cy = m.x, m.y
            else:
                # A pure downward move at constant XY is a plunge (slower feed).
                is_plunge = (not changed(cx, m.x) and not changed(cy, m.y)
                             and cz is not None and m.z < cz - EPS)
                if is_plunge and cz > PLUNGE_CLEARANCE + EPS and m.z < PLUNGE_CLEARANCE:
                    # rapid down to just above the surface, then feed only the cut —
                    # otherwise the whole descent from travel height is at plunge feed
                    out.append(f"G0 Z{_f(PLUNGE_CLEARANCE)}")
                    cz = PLUNGE_CLEARANCE
                want = plunge_fpm if is_plunge else xy_fpm
                line = f"G1 X{_f(m.x)} Y{_f(m.y)} Z{_f(m.z)}"
                if changed(feed, want):
                    line += f" F{_f(want)}"
                    feed = want
                out.append(line)
                cx, cy, cz = m.x, m.y, m.z

    # End of program: lift clear, park, spindle off.
    out += [
        f"G0 Z{_f(travel_z)}",
        "G91",
        "G28 Z0.",                   # Z to machine home
        "G90",
        "M5",                        # spindle off
        "G91",
        "G28 X0. Y0.",               # park XY at machine home
        "G90",
        "M30",                       # program end
        "%",
    ]
    return "\n".join(out) + "\n"
