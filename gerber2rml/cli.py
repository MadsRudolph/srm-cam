"""CLI: gerber folder -> three SRM-20 jobs (RML or G-code)."""
import argparse
from pathlib import Path
from gerber2rml.loader import load_board, place_in_positive_quadrant
from gerber2rml.config import TraceJob, DrillJob, CutoutJob
from gerber2rml.engine.traces import isolate
from gerber2rml.engine.drill import drill_jobs
from gerber2rml.engine.cutout import cut_outline
from gerber2rml.backends import BACKENDS, DEFAULT_MACHINE


def build_jobs(gerber_dir, out_dir, name, trace=None, drill=None, cutout=None,
               mirror=True, machine=DEFAULT_MACHINE, offset=(0.0, 0.0), level=None,
               rotate=0, lead_in=True):
    """``level`` (optional) is a callable ``hmap(x, y) -> dz`` from
    :mod:`gerber2rml.engine.leveling`; when given, every job's Z is warped to
    follow the measured surface (applied AFTER placement, in machine coords).

    ``rotate`` (degrees, 0/90/180/270) reorients the whole board before
    toolpaths are generated, so the exported cut comes out rotated.

    ``lead_in`` (default on) ramps the entry plunge of the cutting passes (traces,
    cut-out) into the copper instead of plunging straight down, to avoid a torque
    spike at engagement. Drill plunges are left vertical."""
    from gerber2rml.engine.leadin import apply_lead_in
    _leadin = apply_lead_in if lead_in else (lambda p: p)
    from gerber2rml.toolpath import offset as offset_paths
    gerber_dir, out_dir = Path(gerber_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace = trace or TraceJob()
    drill = drill or DrillJob()
    cutout = cutout or CutoutJob()
    backend = BACKENDS[machine]          # (render fn, file extension)
    ext = backend.ext
    board = place_in_positive_quadrant(load_board(gerber_dir, mirror=mirror))
    if rotate % 360:
        from gerber2rml.loader import rotate_board
        board = place_in_positive_quadrant(rotate_board(board, rotate))

    from gerber2rml.engine.estimate import estimate_toolpaths_seconds, format_duration
    written = []
    est = {}                                     # fname -> estimated seconds

    def _write(fname, paths, job):
        p = out_dir / fname
        placed = offset_paths(paths, *offset)
        if level is not None:
            from gerber2rml.engine.leveling import apply_leveling
            placed = apply_leveling(placed, level)
        p.write_text(backend.render(placed,
                                    xy_feed=job.xy_feed, plunge_feed=job.plunge_feed))
        est[fname] = estimate_toolpaths_seconds(placed, job.xy_feed, job.plunge_feed)
        written.append(p)

    _write(f"{name}_traces{ext}",
           _leadin(isolate(board.copper, trace, outline=board.outline)), trace)
    drill_files = drill_jobs(board.holes, drill, f"{name}_drill", ext=ext)
    for fname, paths in drill_files:
        _write(fname, paths, drill)               # drills stay vertical (no lead-in)
    _write(f"{name}_cutout{ext}", _leadin(cut_outline(board.outline, cutout)), cutout)

    # Drill run-plan line depends on the mode
    if drill.single_bit:
        drill_step = (f"2. drill  — {drill_files[0][0]}: one {drill.bit_diameter} mm "
                      f"bit, plunge holes that fit + interpolate larger ones, "
                      f"total {drill.total_depth} mm\n")
    else:
        files = ", ".join(f for (f, _p) in drill_files)
        drill_step = (f"2. drill  — one file per diameter (change bit between): "
                      f"{files}\n")

    runplan = (
        f"SRM-20 run plan: {name}  [{machine}]\n"
        f"Send each file via VPanel: Cut -> Add -> Output (set the work XY/Z "
        f"origin first; G-code references that as G54).\n"
        f"Order: 1) traces  2) drill  3) cutout. "
        f"Re-set Z-zero after each bit change; keep XY origin.\n"
        f"1. traces  — bit {trace.bit_diameter} mm, {trace.offsets} offsets, "
        f"cut {trace.cut_depth} mm/pass, feed {trace.xy_feed} mm/s\n"
        f"{drill_step}"
        f"3. cutout  — bit {cutout.bit_diameter} mm, {cutout.tabs} tabs x "
        f"{cutout.tab_width} mm, total {cutout.total_depth} mm\n"
        f"Board mirrored for bottom-up milling: {mirror}.\n"
        + (f"Whole job rotated {rotate % 360}°.\n" if rotate % 360 else "")
        + "Estimated run time (excludes tool changes, spin-up and pauses):\n"
        + "".join(f"   {Path(p).name}: ~{format_duration(est[Path(p).name])}\n"
                  for p in written if Path(p).name in est)
        + f"   TOTAL: ~{format_duration(sum(est.values()))}\n"
    )
    rp = out_dir / f"{name}_runplan.txt"
    rp.write_text(runplan, encoding="utf-8")
    written.append(rp)

    return written


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gerber2rml")
    ap.add_argument("gerber_dir")
    ap.add_argument("-o", "--out", default="out")
    ap.add_argument("-n", "--name", default="board")
    ap.add_argument("--no-mirror", action="store_true",
                    help="do not mirror (e.g. top-side or already-mirrored gerbers)")
    ap.add_argument("-m", "--machine", default=DEFAULT_MACHINE, choices=list(BACKENDS),
                    help="output target: 'Roland SRM-20' (RML) or "
                         "'Roland SRM-20 (G-code)' (.nc for VPanel NC mode)")
    ap.add_argument("--gcode", action="store_const", dest="machine",
                    const="Roland SRM-20 (G-code)",
                    help="shorthand for --machine 'Roland SRM-20 (G-code)'")
    ap.add_argument("--multi-bit", action="store_true",
                    help="one drill file per hole diameter (change bits between "
                         "files). Default is single-bit: one file, plunge + "
                         "interpolate with the bit in the spindle.")
    ap.set_defaults(machine=DEFAULT_MACHINE)
    args = ap.parse_args(argv)
    drill = DrillJob(single_bit=not args.multi_bit)
    for p in build_jobs(args.gerber_dir, args.out, args.name, drill=drill,
                        mirror=not args.no_mirror, machine=args.machine):
        print("wrote", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
