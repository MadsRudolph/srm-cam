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
    """Load the board in ``gerber_dir`` and write its files: see :func:`write_jobs`.

    ``mirror`` flips the design for bottom-up milling. ``rotate`` (degrees,
    0/90/180/270) reorients the whole board before toolpaths are generated, so
    the exported cut comes out rotated."""
    board = place_in_positive_quadrant(load_board(Path(gerber_dir), mirror=mirror))
    if rotate % 360:
        from gerber2rml.loader import rotate_board
        board = place_in_positive_quadrant(rotate_board(board, rotate))
    return write_jobs(board, out_dir, name, trace=trace, drill=drill,
                      cutout=cutout, mirror=mirror, machine=machine,
                      offset=offset, level=level, rotate=rotate, lead_in=lead_in)


def write_jobs(board, out_dir, name, *, trace=None, drill=None, cutout=None,
               mirror=True, machine=DEFAULT_MACHINE, offset=(0.0, 0.0), level=None,
               rotate=0, lead_in=True, panel=None):
    """Write every job file for ``board`` into ``out_dir``, and the run plan
    beside them. Returns the paths written, in the order they are meant to be
    run.

    ``offset`` places the whole job on the bed, in mm, after the toolpaths are
    generated.

    ``level`` (optional) is a callable ``hmap(x, y) -> dz`` from
    :mod:`gerber2rml.engine.leveling`; when given, every job's Z is warped to
    follow the measured surface (applied AFTER placement, in machine coords).

    ``lead_in`` (default on) ramps the entry plunge of the cutting passes (traces,
    cut-out) into the copper instead of plunging straight down, to avoid a torque
    spike at engagement. Drill plunges are left vertical.

    ``panel`` describes a sheet carrying several boards, as ``[(name, x, y,
    rotate)]`` with each board's front-left corner in machine mm. It is printed
    in the run plan and changes nothing else: the boards have already been
    composed into ``board``. ``mirror`` and ``rotate`` are likewise only
    reported."""
    from gerber2rml.engine.leadin import apply_lead_in
    _leadin = apply_lead_in if lead_in else (lambda p: p)
    from gerber2rml.toolpath import offset as offset_paths
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace = trace or TraceJob()
    drill = drill or DrillJob()
    cutout = cutout or CutoutJob()
    backend = BACKENDS[machine]          # (render fn, file extension)
    ext = backend.ext

    from gerber2rml.engine.estimate import estimate_toolpaths_seconds, format_duration
    written = []
    est = {}                                     # fname -> estimated seconds

    def _write(fname, paths, job, header=None):
        p = out_dir / fname
        placed = offset_paths(paths, *offset)
        if level is not None:
            from gerber2rml.engine.leveling import apply_leveling
            placed = apply_leveling(placed, level)
        p.write_text(backend.render(placed,
                                    xy_feed=job.xy_feed, plunge_feed=job.plunge_feed,
                                    header=header))
        est[fname] = estimate_toolpaths_seconds(placed, job.xy_feed, job.plunge_feed)
        written.append(p)

    # Dry-run outline, written first because it is meant to be run first. It
    # traces where the board will be with the spindle off and the bit held
    # clear, so a misplaced piece of copper costs twenty seconds of watching
    # instead of a board. Deliberately NOT levelled: it is in the air, and it
    # is the one file that must stay identical whatever the surface does.
    from gerber2rml.engine.airpass import air_path, DEFAULT_FEED
    air = offset_paths(air_path(board.outline), *offset)
    if air:
        ap_name = f"{name}_airpass{ext}"
        (out_dir / ap_name).write_text(backend.render(
            air, xy_feed=DEFAULT_FEED, plunge_feed=DEFAULT_FEED, spindle=False,
            header=[f"{name} - step 0 of 4: DRY RUN",
                    "spindle OFF, bit held 5 mm up - this file cannot cut",
                    "watch it trace the outline, then run the traces file"]))
        est[ap_name] = estimate_toolpaths_seconds(air, DEFAULT_FEED, DEFAULT_FEED)
        written.append(out_dir / ap_name)

    _write(f"{name}_traces{ext}",
           _leadin(isolate(board.copper, trace, outline=board.outline)), trace,
           header=[f"{name} - step 1 of 4: ISOLATION TRACES",
                   f"bit {trace.bit_diameter} mm, {trace.offsets} offset(s), "
                   f"{trace.cut_depth} mm per pass, feed {trace.xy_feed} mm/s",
                   "re-zero Z after any bit change; do NOT move the XY origin"])
    drill_files = drill_jobs(board.holes, drill, f"{name}_drill", ext=ext)
    for fname, paths in drill_files:
        _write(fname, paths, drill,               # drills stay vertical (no lead-in)
               header=[f"{name} - step 2 of 4: DRILL",
                       f"bit {drill.bit_diameter} mm, through {drill.total_depth} mm",
                       "re-zero Z after the bit change; do NOT move the XY origin"])
    _write(f"{name}_cutout{ext}", _leadin(cut_outline(board.outline, cutout)), cutout,
           header=[f"{name} - step 3 of 4: CUT-OUT - RUN THIS LAST",
                   f"bit {cutout.bit_diameter} mm, through {cutout.total_depth} mm, "
                   f"{cutout.tabs} tabs x {cutout.tab_width} mm",
                   "frees the board from the waste - everything else must be done"])

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
        f"Order: 0) airpass  1) traces  2) drill  3) cutout. "
        f"Re-set Z-zero after each bit change; keep XY origin.\n"
        f"0. airpass — {name}_airpass{ext}: DRY RUN, spindle stays off and the "
        f"bit is held 5 mm up. Watch it trace where the board will be cut. If "
        f"it leaves the copper, stop and re-place the stock — nothing has been "
        f"cut yet. Run this before every job.\n"
        f"1. traces  — bit {trace.bit_diameter} mm, {trace.offsets} offsets, "
        f"cut {trace.cut_depth} mm/pass, feed {trace.xy_feed} mm/s\n"
        f"{drill_step}"
        f"3. cutout  — bit {cutout.bit_diameter} mm, {cutout.tabs} tabs x "
        f"{cutout.tab_width} mm, total {cutout.total_depth} mm\n"
        f"Board mirrored for bottom-up milling: {mirror}.\n"
        + (f"Whole job rotated {rotate % 360}°.\n" if rotate % 360 else "")
        + (("Boards on the sheet (front-left corner, machine mm):\n"
            + "".join(f"   {n}: X{x:.2f} Y{y:.2f}"
                      + (f", turned {r % 360}°\n" if r % 360 else "\n")
                      for n, x, y, r in panel))
           if panel else "")
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
