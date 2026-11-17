Laser proof test board - 40 x 30 mm, single-sided (F.Cu)

Purpose: test "Proof on the drilled holes" on the xTool laser page.

Holes (12):
  1.0 mm  alignment holes at (4,4) (36,4) (4,26) (30,26)
          - lopsided on purpose: the top-right one is pulled in to x=30,
            so the pattern only fits one way round
  0.8 mm  DIP-8 at 2.54 mm pitch, rows y=11.19 / y=18.81
Copper: 0.5 mm traces linking the holes to the DIP, four 1.5 mm SMD pads,
        and a 1 mm fiducial dot (no hole) at (36,26) for "Pick matching points".

Workflow:
  1. SRM-20: drill + cut out only (Run it all), leave it on stock with margin
     so the proof can mark the waste beside the board.
  2. xTool: load this folder as a traces job on F.Cu, drag within ~3 mm,
     press "Proof on the drilled holes".
