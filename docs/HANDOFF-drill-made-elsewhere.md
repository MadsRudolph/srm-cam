# HANDOFF — drilling a board made elsewhere (laser-etched traces)

**For:** a Claude Code session on the CNC PC, at the machine.
**Branch:** `main`, commit `fb68373` (`feat(drill): drill a board made elsewhere`).
**Written:** 2026-09-27.

The feature is built and every automated test passes (1234 tests; 12 new ones in
`tests/test_boardfit.py` and `tests/test_gui2_boardfit.py`). **It has never run
on the real mill.** The session that wrote it was on the Linux laptop, which has
no machine link. Your job is to prove it on a real board and fix whatever the
metal disagrees with.

---

## 0 · Before anything else

- `git pull` on the CNC PC first. The feature is not in any installed release
  (the last one is 0.6.0), so run it **from source**.
- **Use the right interpreter.** The `python` on PATH may be the Windows Store
  build, which has no PySide6. The project runs on miniconda:
  ```bash
  C:\Users\Mads2\miniconda3\python.exe -m gerber2rml.gui2
  ```
  If imports fail, run `python -m gerber2rml.doctor` with that interpreter.
- `pythonw` has no console. If the window never opens, read
  `Documents/SRM-CAM/gui2.log`.
- Tests: `python -m pytest tests/test_boardfit.py tests/test_gui2_boardfit.py -q`.

---

## 1 · What the feature does

The user etched a PCB's traces on the xTool F1 Ultra laser and wants the
SRM-20 to drill it. Nothing on that board was cut from the mill's origin, so the
normal drill file can't simply be run.

The workflow: measure where three of the board's pads really are on the machine,
fit a rigid transform (rotate + shift, optional uniform scale) from the design's
hole positions to the measured ones, and write a drill file with every hole
moved onto the real board.

Initial idea: align a phone photo to the Gerber. That was rejected as the primary
method: a photo has no machine reference, and a phone photo is only good to
about 0.3–0.5 mm, against about 0.4 mm of margin for a 0.8 mm drill in a
1.6–2 mm pad. Measuring pads with the machine itself is the reference. The photo
overlay can still be used afterwards as a visual check.

**In the app:** load the Gerber folder (single-sided), then pick **Drill a board
made elsewhere** at the bottom of the left rail.

1. Make the on-screen copper match the board as it lies (toggle **Mirror** in
   *Set up the job*), and drag the picture to roughly where the board is.
2. **Suggest three**, or tick **Pick on the board** and click holes.
3. Per pad: **Go to it**, centre the bit by eye, **Capture**. Or type numbers,
   or **Find it for me**. After two pads, **Go to it** aims by the fit.
4. At three measured pads, the fit is applied. The stage redraws the board
   where it really is. **Worst pad**: good < 0.10 mm, confirm-before-writing
   ≥ 0.25 mm.
5. **Write the drill file** writes `<name>_drill_fitted.nc`. Zero Z with the
   drill bit and run it. Don't move the board or reset XY after measuring.

### Files

| | |
|---|---|
| `gerber2rml/engine/boardfit.py` | pad suggestion, mirror/collinear check, `warp_holes`, `write_fitted_drill` |
| `gerber2rml/gui2/boardfit.py` | `BoardFitPage`, the inspector page |
| `gerber2rml/engine/fiducial.py` | the rigid fit it reuses (`fit_transform`, `residuals`, `rms`) — unchanged |
| `gerber2rml/gui2/fiducial.py` | `FidFindRun`, the electrical hole finder reused by **Find it for me** — unchanged |
| `gerber2rml/gui2/window.py` | `_board_fit`, `set_board_fit`, `_warp_geom`, the `fitdrill` step in `_toolpaths_for` / `_draw_board`, clearing on load |
| `gerber2rml/gui2/stage.py` | new stage mode `"pad"` → `pad_picked` signal |
| `gerber2rml/gui2/runplan.py` | the `fitdrill` tool step (single-sided plans only) |
| `docs/usage.md` | user-facing section, *Drilling a board made elsewhere* |

---

## 2 · What to verify at the machine, in order

Use a scrap laser-etched board, or any copper board with a few visible features
at known Gerber positions.

1. **Frame check (most likely to be wrong).** With no fit yet, drag the picture
   roughly onto the board and press **Go to it** on one pad. Does the bit go
   to the right *area*? If it goes somewhere mirrored or rotated, the
   design↔machine frame (the **Mirror** setting, `state.mirror`, default `True`)
   doesn't match how the laser board is lying. Work out which setting is right
   for a laser board etched from F.Cu vs B.Cu, and write it into the page's
   text and `docs/usage.md`.
2. **Capture accuracy.** Centre by eye with the drill bit lowered to just above
   the pad, and Capture. Repeat on the same pad a few times. How much do the
   captures scatter? That scatter is the real floor for **Worst pad**. Adjust
   `GOOD` / `USABLE` in `gui2/boardfit.py` if 0.10 / 0.25 mm are wrong for eye
   centring.
3. **The fit.** After three pads, is **Worst pad** small, and does the redrawn
   board sit where the real one is? Click-to-jog on a non-measured hole: the
   bit should land on that pad's centre.
4. **Mirror detection.** Deliberately flip **Mirror** to the wrong setting and
   measure the same three pads by *which pin they are*. **Worst pad** should
   come out in millimetres and the verdict should say too far out.
5. **Drill it.** Write the file, open it in the 3D sim or dry-run it spindle-off
   in VPanel first, then drill. Check every hole lands inside its pad ring.
6. **Find it for me** (optional, least certain). This only makes sense if the
   laser job left the drill mark in each pad as bare laminate (KiCad plot
   option "drill marks"). The probe clip has to be on *that pad's net*, since
   the pads on a laser board are isolated from each other; ground pads are
   easiest. Unverified assumptions:
   - that bare FR-4 at the shallow touch depth reads the same as a real hole;
   - that `FidFindRun`'s surface reference (it looks for copper 2.5 mm
     west/east/north/south of the bit) finds copper on the *clipped* net. On an
     isolated pad it may hit another net and fail;
   - the clearance passed in is `max(0.1, (hole_dia − drill_bit)/2)`, so with a
     0.8 mm bit and a 1.0 mm mark the bit barely fits. A V-bit or a smaller bit
     in the spindle probably behaves better.
   - The failure messages come from the fiducial finder and talk about "the
     hole". Reword them if this path turns out to be useful.

---

## 3 · Known gaps (not done on purpose, pick up if needed)

- **Not saved with the setup.** Pads and measurements are lost on restart or on
  loading another board. The flip-fit page persists its measurements via
  `action_save_setup` / `action_load_setup` in `window.py`. Copy that pattern
  if the user wants it: save hole indices plus measured XY.
- **Pads are stored as indices into `state.board.holes`.** The fit is
  recomputed from them on every read, so dragging or re-mirroring can't leave a
  stale fit. It does assume hole order is stable, which holds for the same
  Gerber folder.
- **Multi-bit drilling** (`drill.single_bit = False`) writes one
  `<name>_drill_fitted_<dia>mm.nc` per diameter. It's covered by
  `drill_jobs` but untested in the GUI.
- **No dry-run file** is written for this job. The normal job's `_airpass`
  traces the unfitted outline, so it's useless here. If wanted, write an air
  pass over the *fitted* holes.
- **Levelling:** the file is levelled with the bottom-face height map if one is
  active. For drilling that barely matters, and a stale map from another board
  would be wrong. Consider dropping it or asking first.
- The photo overlay (`engine/photofit.py`) isn't wired into this page. It could
  be used after the fit as a visual "every hole on its pad" check.

---

## 4 · Commit conventions

Conventional-ish subjects, as in `git log` (`feat(...)`, `fix(...)`). Commit
messages end with the `Co-Authored-By` trailer. Run the two test files above
before committing, and the full suite (`pytest`, about 8 minutes) before
pushing. Don't touch `tests/test_golden.py` fixtures: this feature doesn't
change any normal-job output, and a golden failure means something else broke.
