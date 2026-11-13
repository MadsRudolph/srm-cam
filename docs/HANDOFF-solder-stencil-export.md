# HANDOFF: solder paste stencil export (DXF, and ideally an xTool `.xcs` job)

**For:** the next Claude Code session working on SRM-CAM.
**Status:** **not started in SRM-CAM.** This is a feature request plus everything learned while
dialling it in by hand. Nothing in this repo has changed except this note.
**Written:** 2026-11-13.
**Reference implementation (outside this repo):** `MadsRudolph/solder-stencil-tests`, commit
`b3320b8`. It contains PowerShell scripts, the measured results, and a real XCS project file.

---

## 0 · The request

SRM-CAM already makes the **solder mask** and **silkscreen** laser DXFs from the loaded Gerbers
(`engine/soldermask.py`, `engine/silkscreen.py`, *Also make the laser file (DXF)* on the first
page of the job). The owner wants the same for a **solder paste stencil**:

1. **Stencil DXF** from the board's paste layer, cut on the xTool F1 Ultra fiber laser in
   **0.1 mm 304 stainless** (100 × 100 mm sheets).
2. **Even better: a ready-to-run `.xcs` job** (xTool Creative Space project) with the
   apertures placed and the cutting parameters already set, so the operator only opens it,
   lines it up and presses Start.

---

## 1 · What to reuse

`engine/soldermask.py` already solves most of it. Its docstring lists four rules, and all of
them apply to a stencil:

| Mask today | Stencil |
|---|---|
| Reads `*.Mask` with real flash shapes (`_layer_to_shapely`, `_primitive_to_shapely`) | Read `F.Paste` / `B.Paste` the same way. **Real shapes matter**: a bounding box makes rounded or obround apertures too big. |
| Shrinks each opening `DEFAULT_SHRINK` = 0.1 mm per side, for registration | Shrink by **kerf / 2 per side**. The measured kerf is **0.08 mm**, so **0.04 mm per side** by default. Keep it as a setting. |
| Mirrored like the copper (`x -> -x`) when the milled face is B.Cu | The stencil is laid on the **same face** that gets paste, and is designed seen from above that face. That's the **same mirror rule as the mask** for that face. Verified on a real board: see §4. |
| One DXF: openings plus `OUTLINE` on its own layer | Same. Add a third layer for **registration holes** (see below). Keep the outline as a **mark-only** layer: it is not cut. |
| `shapes_dxf_text` writer (closed LWPOLYLINE, AC1018) | Reuse as is. |

**Registration holes (recommended):** pick two drill holes far apart, e.g. a header pin on one
side and a button on the other. Copy their exact position and drill diameter into the stencil as
round apertures. Pins (drill-bit shanks) through PCB + stencil then align the two perfectly. The
board is drilled on the SRM-20 anyway. Let the user pick or override the two holes.

**Sheet placement:** centre the board on the 100 × 100 sheet. Keep everything inside the middle
80 × 80 mm: the outer 10 mm is for tape.

---

## 2 · The cutting recipe (measured 2026-11-13, F1 Ultra, 0.1 mm 304)

| Setting | Value | Notes |
|---|---|---|
| Laser | fiber, power **100 %**, **550 mm/s**, **30 kHz** | Swept 400–1000 mm/s and 30–60 kHz. 550 mm/s / 30 kHz needed the least energy per mm to cut through. Higher frequency is worse. |
| Processing | **vector cutting** (outline), not Fill | |
| XCS material thickness | **4.1 mm** | The F1 Ultra autofocus value with that carrier. The physical stack (1.6 FR4 + 0.1) **cut far worse** at 1.7. Make it a setting; don't hard-code it. |
| Total passes | **~30** | Through at 21–30 passes; the spread between identical squares is about ±3 runs. |
| Passes per run | **scale with aperture count**: 10 per run for ~15 apertures; **5 per run × 6 runs** for an ESP32-WROOM (49 apertures) | **One job of 30 passes bows the sheet.** The operator re-runs the job with **20–30 s rests**. Put that in the file name, e.g. `<board>_stencil_5x_run6times.xcs`. |
| Kerf compensation | **80 µm** total (0.04 per side) drawn into the geometry | Leave XCS's own kerf setting **off**, or the apertures get compensated twice. |
| Finishing | lap both sides with 1000–1500 grit wet on glass, push out slugs, IPA | |

**Limits:** apertures under ~0.3 mm (e.g. 0.5 mm-pitch QFN) cut, but leave slug fragments behind.
Warn below ~0.3 mm, like the mask's `NARROW_MM`. The owner doesn't do fine-pitch boards; the
real target is parts like the ESP32-WROOM (1.27 mm pitch, 0.9 × 1.5 mm pads), which come out well.

---

## 3 · The `.xcs` format (reverse-engineered from XCS 2.7.22, F1 Ultra)

An `.xcs` file is **one line of JSON**. The reference implementation's `xcs_lib.ps1` writes it,
and `test.xcs` in that repo is a file **saved by XCS itself**: diff against it.

```
{ canvasId, canvas: [ { id, title:"{panel}1", layerData:{ "#fe0002":{name,order,visible}, ... },
                        groupData:{ "g-<uuid>":{...} },
                        displays:[ { id, type:"PATH", x, y, width, height, dPath:"M x y L ... Z",
                                     graphicX, graphicY, offsetX, offsetY, layerTag, groupTag, ... } ] } ],
  extId:"F1Ultra", extName:"F1 Ultra",
  device: { id, power:[20,20],
            data:{ dataType:"Map", value:[ [canvasId, { mode:"LASER_PLANE",
                     data:{ LASER_PLANE:{ thickness, isProcessByLayer, ... } },
                     displays:{ dataType:"Map", value:[ [displayId, {
                        processingType:"VECTOR_CUTTING",
                        data:{ VECTOR_CUTTING:{ materialType:<preset id | "customize">,
                               parameter:{ customize:{ power, speed, frequency, repeat,
                                           processingLightSource:"red" (= fiber), enableKerf:false, ... }}}, ...},
                        processIgnore:false } ], ... ] } } ] ] },
            materialList:[], materialTypeList:[ <preset objects>], customProjectData:{} },
  version:"2.7.22", created, modify, ua, meta:[...], cover:"", minRequiredVersion:"" }
```

- **Position:** a display's `x, y` = `graphicX + minX(dPath)`, `graphicY + minY(dPath)` (mm,
  canvas, Y down). Write `dPath` in sheet coordinates and set `graphicX/Y = offsetX/Y` = the
  sheet's corner on the canvas.
- **`processIgnore: true`** keeps an object in the file but doesn't cut it. Use it for a grey
  **100 × 100 sheet outline**: the operator drags the group until it sits on the sheet in the
  camera image. Projects with custom layer colours (e.g. `#808080`) open fine.
- **One `.xcs` can hold several canvases (tabs),** each with its own `thickness`.
- **Presets:** the user's presets live in XCS's library with stable ids, and the matching
  `materialTypeList` entries are embedded in the project. The XCS settings-manager export
  format = a JSON array of those objects.
- **`repeat` > 10 is allowed** (seen up to 160).

**XCS quirks that cost a day:**
- **XCS ignores layer order** even with `isProcessByLayer: true`. It seems to merge objects with
  identical settings and run **low-power objects first**, and with mixed lasers, fiber before
  diode. So you **cannot** build cooling pauses into a job (tried "rest" objects at 1 %:
  diode, fiber, and speed-ordered). The rests must be the operator re-running the job.
- **XCS has no "pause between passes" setting.**

---

## 4 · Proof it is the right geometry

In the reference repo, `gen_esp32_stencil.ps1` builds the stencil straight from
`esp32-solder-test/esp32solder.kicad_pcb` (U1 `ESP32-WROOM-32_NoVias` on **B.Cu**, rot 180)
plus that board's `production/*_MIRRORED.dxf`. It reads the paste pads, not the Gerbers.
SRM-CAM should read the **Gerbers**. Checks that passed:
- All 10 bottom-row pads and pad 14 land on the copper DXF's own pad corners (4/4 each).
- Pin 14 → J1 hole distance = (−27.250, 14.700) mm in both the stencil job and the
  production files.
- It was cut, came out almost right, and showed the passes-per-run rule above.

A good SRM-CAM test, in the spirit of `tests/test_soldermask.py`: every stencil opening must lie
inside its copper pad (after mirroring), and be exactly kerf/2 smaller per side.

---

## 5 · Suggested shape

- `engine/stencil.py`: `build_stencil(folder, *, side, kerf=0.08, mirror=True, reg_holes=None)`
  → artwork (openings, outline, registration holes, warnings for < 0.3 mm), then
  `write_stencil_dxf(...)` reusing `shapes_dxf_text`.
- Optional `engine/xcs.py`: write the `.xcs` job (one canvas, sheet outline ignored, outline
  marked at ~50 % × 1 pass, apertures + holes at the recipe), with passes per run picked from
  the aperture count and the run count in the file name.
- GUI: **Solder paste stencil › Also make the laser file (DXF / XCS)** next to the mask and
  silkscreen options. Document it in `docs/usage.md` the way the mask is documented.
