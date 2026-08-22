"""Pre-flight diagnostics — catch the things that make a cut go wrong BEFORE you
run it, especially on a full-bed job where every value has to line up.

The big one is the SRM-20's **Z reach**: the Z stroke is only 60.5 mm (Z0 at the
top, hard floor at machine -60.5). If the work surface sits too low in that
travel, a deep cut (a dowel hole, a through-cut) blows past the floor and the
machine lifts to the top + cuts shallow — the classic "didn't go through" bug.
Knowing the probed surface Z, we can compute exactly whether the deepest cut
fits, and how much to raise the work if not.
"""
from dataclasses import dataclass

# SRM-20: Z0 at the top of a 60.5 mm stroke, so the hard floor is at machine
# -60.5 mm. A cut at depth d below the surface reaches machine (surface_z - d);
# that must stay above the floor. See the srm20-z-travel-cuttable-range note.
SRM20_Z_FLOOR = -60.5
REACH_MARGIN = 0.5          # mm of slack to keep off the hard floor


@dataclass
class Check:
    level: str              # 'ok' | 'warn' | 'fail'
    title: str
    detail: str


def cut_depths(trace, drill, cutout, dowel_depth=None):
    """Commanded cut depth (mm below Z0) per operation. Traces engrave at a
    single shallow ``cut_depth``; drill/cut-out peck to ``total_depth``; dowels
    (double-sided) go ``dowel_depth`` (stock + bed bite)."""
    d = {"traces": trace.effective_cut_depth(), "drill": drill.total_depth,
         "cutout": cutout.total_depth}
    if dowel_depth is not None:
        d["dowels"] = dowel_depth
    return d


def preflight(*, depths, bed=None, design_bounds=None, surface_z=None,
              holes=None, bit_diameter=None, trace=None, leveled=False,
              z_floor=SRM20_Z_FLOOR, shorts=None, thickness=None,
              bed_bite=0.2):
    """Run the checks and return a list of :class:`Check`.

    ``depths``: {op: mm} from :func:`cut_depths`. ``design_bounds``: placed
    (x0,y0,x1,y1) incl. dowels. ``surface_z``: probed surface in MACHINE mm
    (negative); without it the Z-reach check can only advise. ``trace`` (the
    :class:`TraceJob`) + ``leveled`` (is a bed height-map being applied?) drive
    the V-bit flatness check. ``shorts`` is the output of
    :func:`gerber2rml.engine.drc.isolation_bridges` - places the cutter
    physically cannot separate two nets."""
    checks = []

    # --- fits the bed -------------------------------------------------------
    if design_bounds is not None and bed is not None:
        x0, y0, x1, y1 = design_bounds
        bx, by = bed
        if x0 >= -1e-6 and y0 >= -1e-6 and x1 <= bx + 1e-6 and y1 <= by + 1e-6:
            checks.append(Check("ok", "Fits the bed",
                                f"{x1 - x0:.1f} x {y1 - y0:.1f} mm, inside the "
                                f"{bx:.0f} x {by:.0f} mm work area."))
        else:
            checks.append(Check("fail", "Off the bed",
                                f"job spans ({x0:.1f},{y0:.1f})-({x1:.1f},{y1:.1f}) "
                                f"mm but the bed is {bx:.0f} x {by:.0f}. Move/rotate "
                                f"it fully onto the bed."))

    # --- Z reach (the 'didn't go through' bug) -----------------------------
    deepest = max(depths.values())
    deepest_op = max(depths, key=depths.get)
    if surface_z is not None:
        available = surface_z - z_floor          # mm of travel below the surface
        if deepest <= available - REACH_MARGIN:
            checks.append(Check("ok", "Z reach OK",
                                f"deepest cut {deepest:.2f} mm ({deepest_op}); "
                                f"{available:.1f} mm of travel below the surface "
                                f"(machine {surface_z:.1f})."))
        else:
            raise_by = deepest - available + REACH_MARGIN
            checks.append(Check("fail", "Deepest cut is out of Z range",
                                f"{deepest:.2f} mm ({deepest_op}) would reach machine "
                                f"{surface_z - deepest:.1f}, past the {z_floor:.1f} "
                                f"floor. The surface at {surface_z:.1f} leaves only "
                                f"{available:.1f} mm. RAISE the work ~{raise_by:.1f} mm "
                                f"(spoilboard/stickout) and re-zero Z."))
    else:
        # no probe yet: tell them how high the surface must sit
        min_surface = z_floor + deepest + REACH_MARGIN
        checks.append(Check("warn", "Z reach unknown (probe Z to confirm)",
                            f"deepest cut {deepest:.2f} mm ({deepest_op}). It only "
                            f"fits if the probed surface sits ABOVE machine "
                            f"{min_surface:.1f} (the Z stroke is {-z_floor:.1f} mm). "
                            f"Probe Z, then re-run this."))

    # --- holes vs bit -------------------------------------------------------
    if holes and bit_diameter:
        diam = [d for _x, _y, d in holes if d > 0]
        if diam:
            dmin = min(diam)
            if dmin < bit_diameter - 1e-3:
                checks.append(Check("warn", "Holes smaller than the bit",
                                    f"smallest hole {dmin:.2f} mm < {bit_diameter:.2f} "
                                    f"mm bit - those come out oversized (plunged)."))
            else:
                checks.append(Check("ok", "Holes fit the bit",
                                    f"smallest hole {dmin:.2f} mm >= {bit_diameter:.2f} "
                                    f"mm bit."))

    # --- depth against the actual stock -------------------------------------
    # Nothing compared these before, so a fat-fingered 17 mm on 1.6 mm stock
    # exported happily: the XY was right, the preview was right, and the only
    # complaint was about Z reach. Through-cuts are supposed to overshoot into
    # the spoilboard a little - that is the bed bite - but not by millimetres.
    if thickness:
        for op in ("drill", "cutout"):
            d = depths.get(op)
            if d is None:
                continue
            if d > thickness + max(bed_bite, 0.0) + 1.0:
                checks.append(Check(
                    "fail", f"{op.capitalize()} depth far below the stock",
                    f"{d:.2f} mm into {thickness:.2f} mm stock - {d - thickness:.2f} "
                    f"mm past the bottom of the board. That is a cut into the "
                    f"spoilboard, and on a screwed-down job it can reach the "
                    f"threaded plate. Check the stock thickness and the total "
                    f"depth for {op}."))
            elif d < thickness:
                checks.append(Check(
                    "warn", f"{op.capitalize()} will not go through",
                    f"{d:.2f} mm into {thickness:.2f} mm stock leaves "
                    f"{thickness - d:.2f} mm uncut."))

    # --- guaranteed shorts --------------------------------------------------
    # This is the only check here that fails on the DESIGN rather than the
    # setup, and it is the most expensive to discover late: a board milled
    # perfectly to a layout the bit cannot separate is scrap either way.
    if shorts is not None:
        if shorts:
            worst = min(s["gap"] for s in shorts)
            checks.append(Check(
                "fail", "Nets closer than the bit",
                f"{len(shorts)} spot(s) where two SEPARATE nets sit closer than "
                f"the cutter can go (worst {worst:.2f} mm, marked X on the "
                f"Traces preview). The copper between them cannot be removed, so "
                f"those nets WILL be shorted on the finished board. Use a "
                f"narrower bit (a V-bit cuts narrower at a shallower depth), or "
                f"move the tracks apart in KiCad."))
        else:
            checks.append(Check(
                "ok", "Net clearance", "no two nets sit closer than the bit."))

    # --- V-bit: cut width is depth-sensitive, so the bed MUST be levelled ----
    if trace is not None and getattr(trace, "tool_type", "flat") == "vbit":
        sens = trace.width_sensitivity()
        depth = trace.effective_cut_depth()
        width = trace.effective_diameter()
        if not leveled:
            checks.append(Check(
                "warn", "V-bit without bed leveling",
                f"cut width {width:.3f} mm at {depth:.3f} mm depth, but a "
                f"{sens:.2f}x depth->width sensitivity means a 0.05 mm surface "
                f"error becomes a {sens * 0.05:.3f} mm width error. Probe a height "
                f"map and enable leveling before running a V-bit."))
        else:
            checks.append(Check(
                "ok", "V-bit leveling on",
                f"cut width {width:.3f} mm held by the height map (depth "
                f"{depth:.3f} mm, {sens:.2f}x sensitivity). Use a dense mesh so "
                f"between-point interpolation stays inside your width budget."))

    return checks


def worst(checks):
    """Overall level across the checks ('fail' > 'warn' > 'ok')."""
    if any(c.level == "fail" for c in checks):
        return "fail"
    if any(c.level == "warn" for c in checks):
        return "warn"
    return "ok"


def format_report(checks):
    """Plain-text, ASCII-only report (Windows-console safe)."""
    tag = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]"}
    lines = [f"{tag[c.level]}  {c.title}\n        {c.detail}" for c in checks]
    return "\n".join(lines)
