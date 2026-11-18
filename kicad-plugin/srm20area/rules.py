"""The design rules an SRM-20 board needs, set in one go.

The mill separates two nets by driving its cutter between them, so nothing
on the board may sit closer to another net than the cutter is wide. KiCad's
defaults (0.2 mm) are a fab's, not a 0.8 mm endmill's, and the clearance
lives in three places - the board's minimum, every net class, and every
zone - of which people find one. This sets all three, refills the zones, and
leaves the routing alone: DRC then shows what has to move.

The clearance asked for is the cutter's own width: SRM-CAM cuts a gap that
is exactly that wide with one pass down its middle. Nothing is ever lowered,
and a board already routed at the cutter's width is left without new DRC
errors.

Holes are the same argument with the drill: it cannot make a hole smaller
than itself, so a 0.3 mm via comes out 0.8 mm whatever the board says, and
the copper round it has to have been sized for that. Via holes - the
board's minimum, the net classes', and the vias already placed - are raised
to the drill, and a via left with too little copper round the bigger hole
is made bigger. Footprint pads are left as their footprints have them.
"""
import os

import pcbnew

DEFAULT_CUTTER_MM = 0.8   # the lab's flat endmill, when SRM-CAM has not said
DEFAULT_DRILL_MM = 0.8    # ...and the same bit drills

# Copper left around a via's hole. A milled board has no plating: a via is a
# hole with a wire soldered through it, so the ring is what there is to
# solder to. New vias get RING_MM; one already on the board is only made
# bigger when it has less than RING_MIN_MM, because growing copper is what
# makes new clearance errors.
RING_MM = 0.5
RING_MIN_MM = 0.3


def wanted_clearance(cutter_mm):
    return round(cutter_mm, 3)


def _netclasses(board):
    ns = board.GetDesignSettings().m_NetSettings
    out = [("Default", ns.GetDefaultNetclass())]
    try:
        for name, nc in ns.GetNetclasses().items():
            out.append((str(name), nc))
    except Exception:                           # noqa: BLE001 - older API
        pass
    return out


def _zone_clearance(zone):
    c = zone.GetLocalClearance()
    try:
        return None if c is None else int(c)
    except (TypeError, ValueError):
        return None


def _vias(board):
    return [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]


def _via_width(via):
    try:
        return via.GetWidth(pcbnew.B_Cu)        # KiCad 9+: per layer
    except TypeError:
        return via.GetWidth()


def _set_via_width(via, width):
    try:
        via.SetWidth(pcbnew.F_Cu, width)        # the padstack's one size
    except TypeError:
        via.SetWidth(width)


def holes_too_small(board, drill_mm):
    """What asks for a hole the drill cannot make, as lines to show."""
    drill = pcbnew.FromMM(drill_mm)
    mm = pcbnew.ToMM
    found = []
    ds = board.GetDesignSettings()
    if ds.m_MinThroughDrill < drill:
        found.append("Board minimum drill: %.2f mm" % mm(ds.m_MinThroughDrill))
    for name, nc in _netclasses(board):
        if nc.HasViaDrill() and nc.GetViaDrill() < drill:
            found.append("Net class %s via hole: %.2f mm"
                         % (name, mm(nc.GetViaDrill())))
    small = [v for v in _vias(board) if v.GetDrill() < drill]
    if small:
        found.append("%d via(s) with a hole under the drill (smallest "
                     "%.2f mm)" % (len(small),
                                   mm(min(v.GetDrill() for v in small))))
    return found


def too_tight(board, cutter_mm=DEFAULT_CUTTER_MM, drill_mm=None):
    """What is set tighter than the cutter allows, or asks for a hole the
    drill cannot make (``drill_mm``; left out, holes are not looked at), as
    lines to show. Empty when the rules already suit the mill."""
    want = pcbnew.FromMM(wanted_clearance(cutter_mm))
    least = want
    mm = pcbnew.ToMM
    found = [] if drill_mm is None else holes_too_small(board, drill_mm)
    ds = board.GetDesignSettings()
    if ds.m_MinClearance < least:
        found.append("Board minimum clearance: %.2f mm" % mm(ds.m_MinClearance))
    for name, nc in _netclasses(board):
        if nc.HasClearance() and nc.GetClearance() < least:
            found.append("Net class %s clearance: %.2f mm"
                         % (name, mm(nc.GetClearance())))
    for zone in board.Zones():
        c = _zone_clearance(zone)
        if c is not None and c < least:
            found.append("Zone %s clearance: %.2f mm"
                         % (zone.GetNetname() or zone.GetZoneName(), mm(c)))
    return found, mm(want)


def _apply_holes(board, drill_mm):
    """Via holes the drill can make, with copper left round them."""
    drill = pcbnew.FromMM(drill_mm)
    ring, ring_min = pcbnew.FromMM(RING_MM), pcbnew.FromMM(RING_MIN_MM)
    mm = pcbnew.ToMM
    changed = []
    ds = board.GetDesignSettings()
    if ds.m_MinThroughDrill < drill:
        changed.append("Board minimum drill %.2f -> %.2f mm"
                       % (mm(ds.m_MinThroughDrill), mm(drill)))
        ds.m_MinThroughDrill = drill
    for name, nc in _netclasses(board):
        if not nc.HasViaDrill() or nc.GetViaDrill() < drill:
            changed.append("Net class %s via hole %.2f -> %.2f mm"
                           % (name, mm(nc.GetViaDrill()), mm(drill)))
            nc.SetViaDrill(drill)
        if not nc.HasViaDiameter() or nc.GetViaDiameter() < drill + 2 * ring:
            changed.append("Net class %s via size %.2f -> %.2f mm"
                           % (name, mm(nc.GetViaDiameter()),
                              mm(drill + 2 * ring)))
            nc.SetViaDiameter(drill + 2 * ring)
    holes = grown = 0
    for via in _vias(board):
        if via.GetDrill() < drill:
            via.SetDrill(drill)
            holes += 1
        if _via_width(via) < via.GetDrill() + 2 * ring_min:
            _set_via_width(via, via.GetDrill() + 2 * ring)
            grown += 1
    if holes:
        changed.append("%d via hole(s) -> %.2f mm" % (holes, mm(drill)))
    if grown:
        changed.append("%d via(s) made %.2f mm across, to keep a ring of "
                       "copper round the hole" % (grown, mm(drill + 2 * ring)))
    return changed


def apply(board, cutter_mm=DEFAULT_CUTTER_MM, drill_mm=None):
    """Raise every clearance below the wanted one to it, make every via hole
    one the drill can make (``drill_mm``; left out, holes are left alone),
    and refill the zones. Never lowers a clearance or shrinks a hole.
    Returns the lines of what changed."""
    want = pcbnew.FromMM(wanted_clearance(cutter_mm))
    mm = pcbnew.ToMM
    changed = [] if drill_mm is None else _apply_holes(board, drill_mm)
    ds = board.GetDesignSettings()
    if ds.m_MinClearance < want:
        changed.append("Board minimum clearance %.2f -> %.2f mm"
                       % (mm(ds.m_MinClearance), mm(want)))
        ds.m_MinClearance = want
    for name, nc in _netclasses(board):
        if not nc.HasClearance() or nc.GetClearance() < want:
            changed.append("Net class %s clearance %.2f -> %.2f mm"
                           % (name, mm(nc.GetClearance()), mm(want)))
            nc.SetClearance(want)
    zones = list(board.Zones())
    for zone in zones:
        c = _zone_clearance(zone)
        if c is not None and c < want:
            changed.append("Zone %s clearance %.2f -> %.2f mm"
                           % (zone.GetNetname() or zone.GetZoneName(),
                              mm(c), mm(want)))
            zone.SetLocalClearance(want)
    if zones:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    return changed


# ------------------------------------------------- rules per fabrication method
# The window (rules_dialog.py) picks a method and its numbers (methods.py);
# these read the board into the shape methods.plan() takes, and carry the plan
# out. Unlike apply() above, a method sets clearances down as well as up: it is
# chosen before layout, and a laser board wants a narrow pour gap.

def _mm_or_none(has, get):
    try:
        return round(pcbnew.ToMM(get()), 4) if has() else None
    except Exception:                               # noqa: BLE001 - older API
        return None


def fill_zones(board):
    return [z for z in board.Zones() if not z.GetIsRuleArea()]


def read_current(board):
    """The board's rules, in mm, as methods.plan() takes them."""
    mm = pcbnew.ToMM
    ds = board.GetDesignSettings()
    cur = {"board": {"floor": round(mm(ds.m_MinClearance), 4),
                     "edge": round(mm(ds.m_CopperEdgeClearance), 4),
                     "drill": round(mm(ds.m_MinThroughDrill), 4)},
           "classes": {}, "zones": []}
    for name, nc in _netclasses(board):
        cur["classes"][name] = {
            "clearance": _mm_or_none(nc.HasClearance, nc.GetClearance),
            "track": _mm_or_none(nc.HasTrackWidth, nc.GetTrackWidth),
            "via_drill": _mm_or_none(nc.HasViaDrill, nc.GetViaDrill),
            "via_dia": _mm_or_none(nc.HasViaDiameter, nc.GetViaDiameter)}
    for z in fill_zones(board):
        c = _zone_clearance(z)
        cur["zones"].append({
            "name": z.GetNetname() or z.GetZoneName() or "?",
            "clearance": None if c is None else round(mm(c), 4),
            "thermal_gap": round(mm(z.GetThermalReliefGap()), 4),
            "pour_min": round(mm(z.GetMinThickness()), 4)})
    try:
        zd = ds.GetDefaultZoneSettings()
        cur["zone_defaults"] = {"clearance": round(mm(zd.m_ZoneClearance), 4),
                                "thermal_gap": round(mm(zd.m_ThermalReliefGap), 4),
                                "pour_min": round(mm(zd.m_ZoneMinThickness), 4)}
    except Exception:                               # noqa: BLE001 - older API
        pass
    return cur


def _raise_vias(board, drill_mm):
    """Vias already placed: holes up to the drill, with copper round them."""
    drill = pcbnew.FromMM(drill_mm)
    ring, ring_min = pcbnew.FromMM(RING_MM), pcbnew.FromMM(RING_MIN_MM)
    holes = grown = 0
    for via in _vias(board):
        if via.GetDrill() < drill:
            via.SetDrill(drill)
            holes += 1
        if _via_width(via) < via.GetDrill() + 2 * ring_min:
            _set_via_width(via, via.GetDrill() + 2 * ring)
            grown += 1
    out = []
    if holes:
        out.append("%d via hole(s) -> %.2f mm" % (holes, drill_mm))
    if grown:
        out.append("%d via(s) made bigger, to keep a ring of copper round "
                   "the hole" % grown)
    return out


def apply_plan(board, ops, drill_mm):
    """Carry out methods.plan(): set every rule it lists, raise the vias
    already placed to the drill, and refill the zones. Tracks stay where they
    are. Returns the lines of what changed."""
    from srm20area import methods
    nm = pcbnew.FromMM
    ds = board.GetDesignSettings()
    classes = dict(_netclasses(board))
    zones = fill_zones(board)
    zd = None
    for target, key, _old, new in ops:
        v = nm(new)
        if target == "board":
            if key == "floor":
                ds.m_MinClearance = v
            elif key == "edge":
                ds.m_CopperEdgeClearance = v
            elif key == "drill":
                ds.m_MinThroughDrill = v
        elif target == "zone_defaults":
            if zd is None:
                zd = ds.GetDefaultZoneSettings()
            if key == "clearance":
                zd.m_ZoneClearance = v
            elif key == "thermal_gap":
                zd.m_ThermalReliefGap = v
            elif key == "pour_min":
                zd.m_ZoneMinThickness = v
        elif target[0] == "class":
            nc = classes[target[1]]
            {"clearance": nc.SetClearance, "track": nc.SetTrackWidth,
             "via_drill": nc.SetViaDrill, "via_dia": nc.SetViaDiameter}[key](v)
        else:
            z = zones[target[1]]
            {"clearance": z.SetLocalClearance,
             "thermal_gap": z.SetThermalReliefGap,
             "pour_min": z.SetMinThickness}[key](v)
    if zd is not None:
        ds.SetDefaultZoneSettings(zd)
    names = [z.GetNetname() or z.GetZoneName() or "?" for z in zones]
    changed = [methods.describe(op, names) for op in ops]
    changed += _raise_vias(board, drill_mm)
    if zones:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    return changed


def rules_file(board):
    """The project's custom rules file (.kicad_dru), or None."""
    name = board.GetFileName()
    if not name:
        return None
    path = os.path.splitext(name)[0] + ".kicad_dru"
    return path if os.path.isfile(path) else None
