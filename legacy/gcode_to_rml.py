#!/usr/bin/env python3
"""
Minimal G-code to RML-1 converter for Roland SRM-20.
Handles G00/G01 moves and tool up/down (Z).
Usage: python3 gcode_to_rml.py input.nc output.rml

NOTE: migrated verbatim from the team repo (hardware/roland-cnc/). Kept for
reference only. It has known bugs documented in docs/design.md §6 (notably the
header uses !MC0 which DISABLES the spindle, and only handles non-modal G-code).
The SRM-20 backend in gerber2rml/backends/srm20.py reimplements this correctly.
"""
import sys, re

SCALE = 40  # RML-1 units per mm (SRM-20 = 40 units/mm)
Z_UP   =  2.0   # mm — travel height
Z_DOWN = -0.1   # mm — cut depth (override per operation if needed)

def mm_to_rml(val):
    return int(round(float(val) * SCALE))

def convert(infile, outfile):
    lines = open(infile).readlines()
    out = []
    out.append("^IN;!MC0;V15;Z1168,1168,1168;")  # SRM-20 init, spindle on

    x = y = z = 0.0
    for line in lines:
        line = line.strip().upper()
        mx = re.search(r'X([-\d.]+)', line)
        my = re.search(r'Y([-\d.]+)', line)
        mz = re.search(r'Z([-\d.]+)', line)
        if mx: x = float(mx.group(1))
        if my: y = float(my.group(1))
        if mz: z = float(mz.group(1))

        if line.startswith('G00') or line.startswith('G01'):
            rx, ry, rz = mm_to_rml(x), mm_to_rml(y), mm_to_rml(z)
            out.append(f"Z{rx},{ry},{rz};")

    out.append("!MC0;^IN;")  # spindle off, reset
    open(outfile, 'w').write('\n'.join(out) + '\n')
    print(f"Written {len(out)-2} moves to {outfile}")

if __name__ == '__main__':
    convert(sys.argv[1], sys.argv[2])
