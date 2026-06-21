"""CLI: gerber folder -> three SRM-20 RML jobs."""
import argparse
from pathlib import Path
from gerber2rml.loader import load_board
from gerber2rml.config import TraceJob, DrillJob, CutoutJob
from gerber2rml.engine.traces import isolate
from gerber2rml.engine.drill import drill_holes
from gerber2rml.engine.cutout import cut_outline
from gerber2rml.backends import srm20


def build_jobs(gerber_dir, out_dir, name, trace=None, drill=None, cutout=None):
    gerber_dir, out_dir = Path(gerber_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace = trace or TraceJob()
    drill = drill or DrillJob()
    cutout = cutout or CutoutJob()
    board = load_board(gerber_dir, mirror=trace.mirror)

    written = []
    jobs = [
        (f"{name}_traces.rml", isolate(board.copper, trace), trace),
        (f"{name}_drill.rml", drill_holes(board.holes, drill), drill),
        (f"{name}_cutout.rml", cut_outline(board.outline, cutout), cutout),
    ]
    for fname, paths, job in jobs:
        rml = srm20.render(paths, xy_feed=job.xy_feed, plunge_feed=job.plunge_feed)
        p = out_dir / fname
        p.write_text(rml)
        written.append(p)

    # Write operator run plan
    runplan = (
        f"SRM-20 run plan: {name}\n"
        f"Order: 1) traces  2) drill  3) cutout. "
        f"Re-set Z-zero after each bit change; keep XY origin.\n"
        f"1. traces  — bit {trace.bit_diameter} mm, {trace.offsets} offsets, "
        f"cut {trace.cut_depth} mm/pass, feed {trace.xy_feed} mm/s\n"
        f"2. drill   — total {drill.total_depth} mm in {drill.cut_depth} mm pecks, "
        f"feed {drill.xy_feed} mm/s\n"
        f"3. cutout  — bit {cutout.bit_diameter} mm, {cutout.tabs} tabs x "
        f"{cutout.tab_width} mm, total {cutout.total_depth} mm\n"
        f"Board mirrored for bottom-up milling: {trace.mirror}.\n"
    )
    rp = out_dir / f"{name}_runplan.txt"
    rp.write_text(runplan)
    written.append(rp)

    return written


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gerber2rml")
    ap.add_argument("gerber_dir")
    ap.add_argument("-o", "--out", default="out")
    ap.add_argument("-n", "--name", default="board")
    args = ap.parse_args(argv)
    for p in build_jobs(args.gerber_dir, args.out, args.name):
        print("wrote", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
