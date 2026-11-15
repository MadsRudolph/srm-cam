"""CLI: Gerber folder -> solder paste stencil, and cutting it on the xTool F1 Ultra.

    srm-cam-stencil <gerber-folder> -o out                       # write the stencil DXF
    srm-cam-stencil <gerber-folder> --trace X Y                  # show where it goes (blue)
    srm-cam-stencil <gerber-folder> --cut X Y --thickness 12     # cut it

X Y is where the stencil's top-left corner (its outline's) sits on the bed: import
the DXF into XCS, place it on the camera image, and read X and Y. The thickness
is what XCS's autofocus reports for the foil on its carrier.
"""
import argparse
import sys
import time
from pathlib import Path

from gerber2rml.engine import stencil, xtool


def main(argv=None):
    ap = argparse.ArgumentParser(prog="srm-cam-stencil", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gerber_dir", type=Path)
    ap.add_argument("--side", choices=["bottom", "top"], default="bottom")
    ap.add_argument("--kerf", type=float, default=stencil.DEFAULT_KERF)
    ap.add_argument("-o", "--out", type=Path, help="write the stencil DXF here")
    ap.add_argument("-n", "--name", help="file name stem (default: the folder's)")
    ap.add_argument("--gcode", type=Path, help="also save the laser job file here")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--trace", nargs=2, type=float, metavar=("X", "Y"))
    g.add_argument("--cut", nargs=2, type=float, metavar=("X", "Y"))
    ap.add_argument("--thickness", type=float, help="XCS autofocus thickness (mm)")
    r = xtool.DEFAULT_RECIPE
    ap.add_argument("--passes", type=int, default=r.total_passes)
    ap.add_argument("--burst", type=int, default=r.passes_per_burst)
    ap.add_argument("--rest", type=float, default=r.rest_s)
    ap.add_argument("--zones", type=int, default=r.zones)
    ap.add_argument("--host", default=xtool.HOST)
    a = ap.parse_args(argv)

    try:
        art = stencil.build_stencil(a.gerber_dir, side=a.side, kerf=a.kerf)
    except stencil.StencilError as e:
        sys.exit(str(e))
    w, h = art.size
    print(f"{len(art.apertures)} holes, {w:.2f} x {h:.2f} mm, "
          f"{'mirrored' if art.mirrored else 'not mirrored'}, kerf {art.kerf:g} mm")
    for msg in art.warnings():
        print("  !", msg)
    name = a.name or a.gerber_dir.resolve().name
    if a.out:
        print("wrote", stencil.write_stencil_dxf(art, a.out, name))

    origin = a.trace or a.cut
    if not origin:
        return
    holes, outline = xtool.stencil_paths(art, tuple(origin))
    laser = xtool.F1Ultra(a.host)
    if a.trace:
        laser.run(xtool.trace_job(outline))
        print("tracing the outline in blue ...")
        laser.wait(120)
        return

    if a.thickness is None:
        sys.exit("--cut needs --thickness (what XCS's autofocus reports).")
    recipe = xtool.Recipe(total_passes=a.passes, passes_per_burst=a.burst,
                          rest_s=a.rest, zones=a.zones)
    job = xtool.stencil_job(holes, outline, recipe)
    if a.gcode:
        a.gcode.write_text(job.text, newline="")
    print(f"{len(job.zones)} zones {job.zones}, {recipe.rounds} rounds x "
          f"{recipe.passes_per_burst} passes, about {job.seconds:.0f} s")
    print(f"focus Z {laser.focus(a.thickness):.2f} (thickness {a.thickness:g})")
    try:
        laser.run(job.text)
        laser.wait(job.seconds * 2 + 120,
                   progress=lambda t: print(f"\r  {t:4.0f} / ~{job.seconds:.0f} s",
                                            end="", flush=True))
        print("\ndone")
    except KeyboardInterrupt:
        laser.stop()
        print("\nstopped")


if __name__ == "__main__":
    main()
