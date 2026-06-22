"""CLI: gerber folder -> three SRM-20 RML jobs."""
import argparse
from pathlib import Path
from gerber2rml.loader import load_board, place_in_positive_quadrant
from gerber2rml.config import TraceJob, DrillJob, CutoutJob
from gerber2rml.engine.traces import isolate
from gerber2rml.engine.drill import drill_jobs
from gerber2rml.engine.cutout import cut_outline
from gerber2rml.backends import srm20


def build_jobs(gerber_dir, out_dir, name, trace=None, drill=None, cutout=None, mirror=True):
    gerber_dir, out_dir = Path(gerber_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace = trace or TraceJob()
    drill = drill or DrillJob()
    cutout = cutout or CutoutJob()
    board = place_in_positive_quadrant(load_board(gerber_dir, mirror=mirror))

    written = []

    def _write(fname, paths, job):
        p = out_dir / fname
        p.write_text(srm20.render(paths, xy_feed=job.xy_feed, plunge_feed=job.plunge_feed))
        written.append(p)

    _write(f"{name}_traces.rml", isolate(board.copper, trace, outline=board.outline), trace)
    drill_files = drill_jobs(board.holes, drill, f"{name}_drill")
    for fname, paths in drill_files:
        _write(fname, paths, drill)
    _write(f"{name}_cutout.rml", cut_outline(board.outline, cutout), cutout)

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
        f"SRM-20 run plan: {name}\n"
        f"Order: 1) traces  2) drill  3) cutout. "
        f"Re-set Z-zero after each bit change; keep XY origin.\n"
        f"1. traces  — bit {trace.bit_diameter} mm, {trace.offsets} offsets, "
        f"cut {trace.cut_depth} mm/pass, feed {trace.xy_feed} mm/s\n"
        f"{drill_step}"
        f"3. cutout  — bit {cutout.bit_diameter} mm, {cutout.tabs} tabs x "
        f"{cutout.tab_width} mm, total {cutout.total_depth} mm\n"
        f"Board mirrored for bottom-up milling: {mirror}.\n"
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
    args = ap.parse_args(argv)
    for p in build_jobs(args.gerber_dir, args.out, args.name, mirror=not args.no_mirror):
        print("wrote", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
