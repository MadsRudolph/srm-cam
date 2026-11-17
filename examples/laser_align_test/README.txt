Laser alignment test board - 40 x 30 mm, F.Cu only, no drilling

Purpose: check that what the xTool etches lands where the photo shows it.

  Crosshairs   at (5,5) (35,5) (5,25) (35,25) and the centre (20,15):
               0.4 mm lines 6 mm long, a 1.2 mm dot in the middle
  L mark       top-left, 0.6 mm: reads as an upright L when the board is
               the right way round (a mirrored or turned board shows here)
  Line ladder  bottom middle, 0.15 / 0.2 / 0.3 / 0.4 / 0.5 mm wide, 5 mm tall

Test:
  1. Laser page: Open Gerber folder... -> this folder (Traces, F.Cu).
  2. Photo, drag onto the blank, Calibrate the camera.
  3. Etch the traces (Photo when done ticked).
  4. Outlines view: the passes should sit evenly round every crosshair.
  5. For a number: Alignment -> Automatic alignment references -> source
     "Artwork shapes", then Align. The move it reports (X, Y in mm) is how
     far the etch is off the drawing; aligned means close to 0. Align moves
     the drawing onto the etch: do not etch again after it.
