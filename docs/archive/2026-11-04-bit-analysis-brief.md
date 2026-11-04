# Bit analysis brief: torture_60x30, 4 Nov 2026

For the mill-PC session that sets the final bit profiles and writes the docs.

**Evidence tags:** `[photo]` measured from photo · `[meter]` meter (Mads) · `[Mads]` Mads's report · `[inferred]` inferred. Meter results are in §9, kept separate from the photo results. Where a photo-only claim is now settled by the meter, it's marked **→ meter: ...**.

**Method** `[photo]`
- **Scale:** the ruler sits above the copper and reads about 3–4 % too large. I calibrated each close-up on the board itself instead: 3.2 mm row pitch, trace centre spacing, SOIC 1.27 pitch, 0.5 pitch and the 0603 centre spacing (1.60 mm). These agree within about 1 %.
- **Edges:** found at half-max brightness, sub-pixel, averaged over 10–65 columns per feature.
- **Resolution:** close-ups are 0.015–0.019 mm/px, overviews 0.035 mm/px. The camera output is compressed. Uncertainty is about ±0.03 mm in close-ups and ±0.05 mm in overviews.
- **What the widths mean:** "copper" widths are the flat, bright copper top. Sloped copper walls image dark, so the copper base is wider than these figures. "Channel top" is copper-edge to copper-edge at the surface. "Laminate floor" is the width of exposed laminate, which approximates the cut width at the bottom of the copper.
- **Orientation:** every photo matches the mirrored layout: gaps on the right, widths in the middle, footprints on the left, front (row 1, 1.00 mm and 0.80 gap) at the bottom of the image. The ruler is upside down in several shots, but the board isn't. No photo shows a different board or bit.

---

## 1. Verdict

**Ball mill, 0.8 mm (told 0.30, 0.08 deep, narrow gaps on)**
- Isolates cleanly everywhere visible, including the 0.20 gap row `[photo]`. **Meter: all 8 gap rows open, all 8 width rows (down to 0.15) connected, all footprint pads isolated from each other and from ground** `[meter]`.
- Real cut is about 0.44 mm at the copper top and about 0.29 mm at the copper base `[photo]`. Every feature loses about 0.07 mm per side, because the app was told 0.30 `[photo]`.
- SOIC, SOT-23, 0603 and 0402 are usable. TSSOP 0.65 is marginal. 0.5 pitch is unusable `[photo]`.
- **Choose this by default.** It's buyable and repeatable, and was as good as or better than the pointed bit on every footprint here.

**Pointed bit (snapped 0.8 flat, told 0.20, 3 passes to 0.11)**
- Isolates cleanly everywhere visible `[photo]`. **Meter: all 8 gap rows open, all 8 width rows connected (including the 0.15 and 0.20 rows that show no flat copper), all footprint pads isolated from each other and from ground** `[meter]`.
- **No width advantage at 0.11 deep.** Channel top is about 0.45 mm, the same as the ball mill. The laminate floor is narrower, about 0.19 mm, which fits a V-ish tip `[photo]`.
- It leaves less flat copper than the ball mill on every footprint, because it was told 0.20 so its paths run 0.05 mm closer to the copper `[photo]`.
- Its only plausible advantage is a **shallower** cut: a V gets narrower with less depth `[inferred]`. That's untested.
- Until a shallow test shows narrower channels, **don't choose it over the ball mill**. It's one broken bit and can't be replaced.

---

## 2. Real cut width per bit

**Ball mill**, single-pass outline channels:

| Where | Channel top (mm) | Laminate floor (mm) | Photo |
|---|---|---|---|
| Gap rows 8–4, 14 channels | mean 0.44, range 0.41–0.47 | mean 0.29, range 0.21–0.34 | 0007 |
| Width rows 8–4, 9 channels | mean 0.48, range 0.45–0.51 | mean 0.30, range 0.22–0.36 | 0005 |
| Width rows 3–2 | 0.44–0.47 | not measured | 0006 |
| Whole board, coarse | 0.43–0.50 | not measured | 0008 |

- **Cross-check from merged gap channels** `[photo]`: the 0.40 gap gives 0.53 and the 0.50 gap gives 0.65. Paths are (gap − 0.30) apart, so this implies w = 0.43–0.45, which agrees.
- **Cross-check from trace loss** `[photo]`: 1.00 → 0.87, 0.80 → 0.70 and 0.60 → 0.50 give w = 0.40–0.43.
- **Variation** `[photo]`: in 0005, the width-row channels widen from 0.45 at row 8 to 0.51 at row 4. The 0007 gap rows show no trend. Not sure whether this is real. It could be sheet flatness, since levelling read 0.19 mm from flat.

**Does it explain 0.30–0.35 vs 0.48?** Yes, mostly. The two figures measure different things.
- **0.48 (geometry)** is the width at the copper **top** for a true 0.8 ball at 0.08 deep. The measured top is 0.44, which is what the same ball cuts at about 0.065 deep `[inferred]`. Effective depth was probably about 0.015 mm shallower than set, from Z-zero or levelling error. Not sure.
- **0.30–0.35 (from surviving traces)** matches the measured laminate floor of about 0.29, which is the width at the copper **base**. That base width decides whether copper is electrically cut or kept, so the breaker-card meter results track it `[inferred]`.
- Ball geometry at about 0.065 deep with 35 µm foil predicts about 0.30 mm at the copper base. That fits, but the foil thickness is unmeasured `[inferred]`.
- No sign that runout widens the cut: the channel is narrower than the geometry predicts `[inferred]`.

**Pointed bit**, single-pass outline channels:

| Where | Channel top (mm) | Laminate floor (mm) | Photo |
|---|---|---|---|
| Gap rows 8–6, outer outlines | mean 0.46, range 0.42–0.50 | mean 0.18, range 0.13–0.23 | 0002 |
| Gap rows 8–7 | 0.41–0.45 | 0.20–0.22 | 0006 |
| Gap rows 2–1 | 0.39–0.50 | 0.15–0.21 | 0007 |

- **Gap-side channels** `[photo]`: rows 8 / 7 / 6 measure 0.54 / 0.55 / 0.64 in 0002 and 0.50 / 0.52 in 0006. These are wider than the outlines, which fits paths that partly overlap.
- **Implied width from trace loss** `[photo]`: told 0.20, gap-row traces 0.50 → 0.18–0.29, which implies w = 0.41–0.52.
- **Cross-section** `[photo]`: dark copper walls about 0.06–0.10 mm each side, then a narrow, centre-peaked teal floor, which fits a V-ish tip. The geometry doesn't fit a clean V: at 0.11 deep those walls imply a very blunt angle. Not sure of the tip shape.
- The earlier estimate of 0.20–0.25 mm wide at 0.15 deep is **not reproduced**. At the copper top this board is about 0.45 `[photo]`. Possibly the tip has changed, or that estimate measured the floor. Not sure.

---

## 3. Results tables

### 3a. Ball mill: gap rows (designed traces 0.50)

| Row | Gap | Looks open? | Gap channel (mm) | Remaining traces (mm) | Notes | Photo |
|---|---|---|---|---|---|---|
| 8 | 0.20 | yes | 0.47 (middle cut) | 0.28 / 0.29 | laminate visible full length | 0007 |
| 7 | 0.25 | yes | 0.45 (middle cut) | 0.29 / 0.37 | | 0007 |
| 6 | 0.30 | yes | 0.45 | 0.40 / 0.33 | | 0007 |
| 5 | 0.40 | yes | 0.53 | 0.38 / 0.38 | | 0007 |
| 4 | 0.50 | yes | 0.65 | 0.38 / 0.34 | | 0007 |
| 3 | 0.60 | yes | 0.72 (coarse) | 0.38 / 0.35 (coarse) | | 0008 |
| 2 | 0.70 | yes | 0.83 (coarse) | 0.38 / 0.35 (coarse) | | 0008 |
| 1 | 0.80 | yes | two cuts | about 0.35 (coarse) | thin copper sliver, about 0.03–0.05, floating between the cuts | 0008, 0003 |

All entries `[photo]`. **→ meter: all 8 rows open, including row 1 with its sliver** `[meter]`.
- The pair traces differ by up to 0.08 mm in rows 6–7 `[photo]`. Not sure whether that's cut offset or lighting.
- With narrow gaps on, the middle cut leaves 0.28–0.37 of each 0.50 trace `[photo]`.
- Light dashes along the channel centres in rows 1–5 and in the wide width rows are green, not copper-coloured. They're most likely glass weave in the laminate `[inferred]`. Meter to be sure.

### 3b. Ball mill: width rows

| Row | Designed | Remaining flat copper (mm) | Range | Photo |
|---|---|---|---|---|
| 8 | 0.15 | 0.08 | 0.05–0.10, continuous across the measured span | 0005 |
| 7 | 0.20 | 0.15 | 0.12–0.17 | 0005 |
| 6 | 0.30 | 0.20 | 0.16–0.23 | 0005 |
| 5 | 0.40 | 0.27 | 0.24–0.29 | 0005 |
| 4 | 0.50 | 0.32 | 0.11–0.38 (one local dip) | 0005 |
| 3 | 0.60 | 0.50 | 0.49–0.51 | 0006 |
| 2 | 0.80 | 0.70 | 0.68–0.71 | 0006 |
| 1 | 1.00 | 0.87 (coarse) | 0.85–0.88 | 0008 |

All entries `[photo]`. **→ meter: all 8 rows connected, including 0.15** `[meter]`. Loss is 0.05–0.18. The copper base is wider than these figures by about 0.05 per side `[inferred]`.

### 3c. Ball mill: footprints

| Part | Designed pad W (gap) | Remaining pad (mm) | Look | Rating | Evidence |
|---|---|---|---|---|---|
| SOIC 1.27 | 0.60 x 1.50 (0.67) | W 0.50–0.61, L 1.20 | intact; bright edge highlights inflate W, not sure | **usable** | `[photo]` 0005 |
| TSSOP 0.65 | 0.30 x 1.20 (0.35) | W 0.20–0.27, mean 0.22 | intact and straight, narrower than a TSSOP lead | **marginal**: about 70 % of designed width; needs a real part test | `[photo]` 0005 |
| Fine 0.5 | 0.25 x 1.20 (0.25) | W 0.10–0.17, mean 0.13, local minimum about 0.05 | necked (hourglass) pads | **unusable**: about half width and necked | `[photo]` 0005 |
| SOT-23 | 0.80 x 0.90 (1.10) | W 0.73–0.77 | intact; floating copper island about 0.36 between the bottom pads | **usable** | `[photo]` 0006 |
| 0603 | 0.90 x 0.90 (0.70) | 0.80 x 0.70 | intact | **usable** | `[photo]` 0006 |
| 0402 | 0.55 x 0.60 (0.45) | 0.42–0.44 x 0.42 | intact | **usable** | `[photo]` 0006 |

### 3d. Pointed bit: gap rows (designed traces 0.50)

| Row | Gap | Looks open? | Gap channel (mm) | Remaining traces (mm) | Notes | Photo |
|---|---|---|---|---|---|---|
| 8 | 0.20 | yes | 0.50–0.54 | 0.19–0.25 | | 0002, 0006 |
| 7 | 0.25 | yes | 0.52–0.55 | 0.21–0.29 | | 0002, 0006 |
| 6 | 0.30 | yes | 0.64 | 0.18–0.23 | | 0002 |
| 5 | 0.40 | looks open (coarse) | about 0.6 (coarse) | not sure | overview only | 0001 |
| 4 | 0.50 | looks open (coarse) | about 0.7 (coarse) | not sure | overview only | 0001 |
| 3 | 0.60 | looks open (coarse) | about 0.7 (coarse) | not sure | overview only | 0001 |
| 2 | 0.70 | yes | 0.79 | 0.24 / 0.25 | intermittent thin sliver in the gap | 0007 |
| 1 | 0.80 | yes | two cuts, 0.36 + 0.39 | 0.25 / 0.25 | **floating copper sliver about 0.11** between the cuts | 0007 |

- All entries `[photo]` unless noted. **→ meter: all 8 rows open, including rows 5–3 seen only in the overview** `[meter]`.
- **Front row after its extra passes (0.07, 0.09):** no visible difference from row 2. Outline widths are within the same range `[photo]`. "Read open at 0.09" `[Mads]`.

### 3e. Pointed bit: width rows

| Row | Designed | Remaining flat copper (mm) | Photo |
|---|---|---|---|
| 8 | 0.15 | **no flat copper visible.** A 0.87-wide dark band with a thin brown ridge in the middle, probably a copper ridge with no flat top. Not sure it's connected. | 0002, 0006 |
| 7 | 0.20 | **no flat copper visible**, same as row 8 | 0002, 0006 |
| 6 | 0.30 | partly visible; about 0.15 (coarse) | 0002 (frame edge), 0001 |
| 5 | 0.40 | about 0.25 (coarse) | 0001 |
| 4 | 0.50 | about 0.36 (coarse) | 0001 |
| 3 | 0.60 | about 0.48 (coarse) | 0001 |
| 2 | 0.80 | 0.51 (0.47–0.54) | 0007 |
| 1 | 1.00 | 0.67 (0.63–0.75) | 0007 |

All entries `[photo]`. **→ meter: all 8 rows connected** `[meter]`, so the ridge on rows 8–7 does carry current. How much current it can take is unknown.

### 3f. Pointed bit: footprints

| Part | Designed pad W | Remaining pad (mm) | Look | Rating | Evidence |
|---|---|---|---|---|---|
| SOIC 1.27 | 0.60 x 1.50 | W 0.39–0.45, L 1.21 | intact, clean | **usable** | `[photo]` 0003 |
| TSSOP 0.65 | 0.30 x 1.20 | W 0.14–0.18 | intact and straight | **marginal**: about half width; needs a real part test | `[photo]` 0003 |
| Fine 0.5 | 0.25 x 1.20 | W 0.08–0.15, mean 0.12 | continuous strips, more uniform than the ball mill's | **marginal to unusable**: about half width. Not sure; needs a real part test | `[photo]` 0004 |
| SOT-23 | 0.80 x 0.90 | W 0.64–0.66 | intact | **usable** | `[photo]` 0005 |
| 0603 | 0.90 x 0.90 | 0.67 x 0.65 | intact; island about 0.12 between pads | **usable** | `[photo]` 0005 |
| 0402 | 0.55 x 0.60 | 0.22–0.25 x 0.24–0.29 | intact | **marginal**: about half size | `[photo]` 0005 |

### 3g. Quality, wobble and tip

| Item | Ball mill | Pointed bit |
|---|---|---|
| Clear to laminate | yes, continuous floor in all close-ups `[photo]` | yes, continuous narrow floor `[photo]` |
| Edges | smooth, slight waviness; bright edge glints on footprints may be small burrs, not sure `[photo]` | dark sloped walls, smooth `[photo]` |
| Lifted copper | none seen `[photo]` | none seen `[photo]` |
| Slivers | row 1 gap, about 0.03–0.05; SOT-23 island `[photo]` | row 1 gap about 0.11, row 2 intermittent, 0603 island `[photo]` |
| Wobble or runout | none evident: channel narrower than geometry; outline spread 0.41–0.47 `[photo]` | none evident; outline spread 0.39–0.50 `[photo]` |
| Tip chipping or change along the cut | n/a | no back-to-front trend in width `[photo]`. The 3 passes overwrite each other, so a mid-run change can't be seen. Not sure. |
| Surface | normal | fine scratches across the copper in 0002, 0006 and 0007, as if brushed or sanded; not from the cut `[photo]` |

---

## 4. Recommended final profiles

**Ball mill 0.8, 3 mm cutting length**

| Setting | Value | Evidence | Needs test? |
|---|---|---|---|
| Told width | **0.44** (was 0.30) | real top width 0.44, range 0.41–0.47 `[photo]`; telling 0.30 shaves about 0.07 per side off everything `[photo]` | **yes**: confirm a told-0.44 board keeps designed widths |
| Depth | **0.08** | isolates everywhere `[photo]` | no; shallower is untested |
| Feed / plunge | **3 / 0.5 mm/s** | clean edges, no lifting `[photo]` | no |
| Narrow gaps | **on** | 0.20 and 0.25 rows open with the middle cut `[photo]`; at told 0.44, gaps under 0.44 take the middle cut instead `[inferred]` | covered by the same test |

- **Why 0.44 and not 0.30** `[inferred]`: the told width controls path offset. 0.30 has proven isolation but costs 0.07 per side of copper. 0.44 should keep pads at their designed size, since the copper base still clears about 0.29.
- **Not final until** a torture_60x30 cut at told 0.44, 0.08 deep, narrow gaps on, has been metered on all gap and width rows, with pad widths photographed.

**Pointed bit**

| Setting | Value | Evidence | Needs test? |
|---|---|---|---|
| Told width | **0.45 if run at 0.11**. Otherwise measure at the chosen depth | top width about 0.45 at 0.11 `[photo]`; told 0.20 shaved about 0.13 per side `[photo]` | **yes** |
| Depth | **not settled.** 0.11 proven (3 passes); 0.09 proven open on row 1 only | `[photo]`, `[Mads]`; width falls with depth for a V `[inferred]` | **yes**: the main open question |
| Feed / plunge | 3 / 0.5 mm/s | clean `[photo]` | no |
| Narrow gaps | on, once told width is about 0.45 | same reasoning as the ball mill `[inferred]` | yes |
| Bit type in app | flat (current). Use a V model if the app has one, after measuring | `[inferred]` | yes |

- **Not final.** Next test: torture_60x30, single pass, no step-down, at **0.07** and at **0.09**, two boards or two halves.
- Photograph each at about 66 px/mm and meter all rows.
- Keep the pointed bit only if the channel top is clearly below the ball mill's 0.44 **and** every gap still reads open.

---

## 5. Capability table for the docs

| Bit | Settings | Finest proven clearance | Finest proven trace | Finest usable pitch | Marginal pitch | Evidence level |
|---|---|---|---|---|---|---|
| Ball mill 0.8 | told 0.30, 0.08 deep, 1 pass, 3 / 0.5 mm/s, narrow gaps on | 0.20 `[meter]` (smallest on board). Earlier breaker card: 0.10 at told 0.15 `[Mads]` | 0.15 `[meter]` (smallest on board; about 0.08 flat copper `[photo]`). Earlier: 0.10 continuity at told 0.30 `[Mads]` | 1.27 (SOIC); all pads isolated `[meter]`; SOT-23, 0603, 0402 usable `[photo]` | 0.65 (TSSOP) `[photo]` | meter + photo |
| Pointed bit (broken 0.8 flat, one-off) | told 0.20 flat, passes 0.05 / 0.10 / 0.11, 3 / 0.5 mm/s, narrow gaps off | 0.20 `[meter]` (smallest on board) | 0.15 `[meter]` (smallest on board), but 0.15 and 0.20 survive as a ridge with no flat top `[photo]`; 0.30 is the finest with flat copper `[photo]` | 1.27 (SOIC); all pads isolated `[meter]`; SOT-23, 0603 usable `[photo]` | 0.65 TSSOP, 0.5 pitch, 0402 `[photo]` | meter + photo |
| Standard 0.8 flat | – | no data | no data | no data | no data | no data |

---

## 6. Doc notes

- **Told width is a setting, not the bit size.** Measured top widths are about 0.44 for the ball mill and about 0.45 for the pointed bit at 0.11. The base widths, about 0.29 and 0.19, decide electrical isolation `[photo]`.
- Limits depend on the settings: told width, depth and narrow gaps on or off. Quote them only with their settings.
- **Width depends on depth.** For the ball mill, 0.08 set acted like about 0.065 `[inferred]`. An uneven sheet changes width across the board, and levelling here read 0.19 mm from flat. Re-level before fine work.
- Foil is assumed 35 µm, not measured. Base-width figures depend on it.
- Wide gaps of 0.80 or more with a 0.44-wide cut can leave a thin floating copper sliver between the two isolation cuts. It's harmless electrically but can flake off.
- The pointed bit is **one accidentally snapped 0.8 flat bit**. It can't be bought, and nobody else can reproduce it. Don't publish it as a recommended bit, only as a data point.
- 0.5 pitch is not reliably millable with either bit as tested.

---

## 7. Unknowns

- Ball mill holes and cut-out: untested.
- Ball mill at told 0.44: untested (this is the proposed final setting).
- Ball mill depth below 0.08: untested.
- Pointed bit single pass straight to 0.11: untested, since every pass recut the same path.
- Pointed bit full board at 0.07 or 0.09: untested. 0.09 is open on row 1 only, after a 0.05 pass `[Mads]`.
- Pointed tip geometry: walls and floor don't fit a clean V. Not sure.
- Whether the tip changed during the run: can't be seen.
- Holes and cut-out with a second bit after a pointed-bit run: Automatic mode has no bit-change step yet.
- Copper foil thickness: unmeasured.
- Clearance below 0.20 and traces below 0.15: not on this board, so not proven with these settings.
- Current capacity of the pointed bit's ridge-only 0.15 and 0.20 traces: unknown.
- Real soldering of TSSOP, 0.5 pitch and 0402: untested.

---

## 8. Photo list

| File | Folder | Shows | Scale (board) | Angle OK? |
|---|---|---|---|---|
| microscope-20261104-152704-0003.png | ball mill (`/home/mads/cnc`) | whole board overview, no ruler | about 28 px/mm | yes (overview only) |
| microscope-20261104-153445-0008.png | ball mill | whole board with ruler at front | 28.2 px/mm | yes (coarse) |
| microscope-20261104-153027-0005.png | ball mill | TSSOP, SOIC, 0.5 pitch; width rows 8–4 | 52.9 px/mm | yes |
| microscope-20261104-153124-0006.png | ball mill | 0402, 0603, SOT-23; width rows 3–2 (left pads) | 66.5 px/mm | yes |
| microscope-20261104-153330-0007.png | ball mill | gap rows 8–4, vertical ruler | 61 px/mm | yes |
| sacred-bit-20261104-153727-0001.png | pointed (`/home/mads/cnc/sacred-bit`) | whole board with ruler at front | 28.2 px/mm | yes (coarse) |
| sacred-bit-20261104-153824-0002.png | pointed | width rows 8–6, gap rows 8–6 | 66 px/mm | yes |
| sacred-bit-20261104-153920-0003.png | pointed | TSSOP and SOIC (both rows) | 66 px/mm | yes |
| sacred-bit-20261104-153956-0004.png | pointed | 0.5 pitch (both rows) | 66 px/mm | yes |
| sacred-bit-20261104-154016-0005.png | pointed | 0402, 0603, SOT-23 | 66 px/mm | yes |
| sacred-bit-20261104-154100-0006.png | pointed | gap rows 8–7, width rows 8–7 (right pads) | 66 px/mm | yes |
| sacred-bit-20261104-154132-0007.png | pointed | gap rows 2–1 (0.80 front row), width rows 2–1 | 66 px/mm | yes |

The pointed folder has no close-up of gap rows 5–3 or width rows 5–3; those come from the overview only.

---

## 9. Meter results (Mads), both boards

Mads: *"they all measure as they should with the multimeter, so beeps at all in the middle row, no beeps in the right row, and all the different pads on the soics are isolated from each other and also isolated from the gnd"*. Mads confirmed: both boards, and **all** footprint pads isolated (SOIC, TSSOP, 0.5 pitch, SOT-23, 0603, 0402).

| Test | Ball mill | Pointed bit | Evidence |
|---|---|---|---|
| Width rows 1–8 (1.00 → 0.15), pad to pad | all beep (connected) | all beep (connected) | `[meter]` |
| Gap rows 1–8 (0.80 → 0.20), left pad to right pad | no beep (open) | no beep (open) | `[meter]` |
| SOIC 1.27 pads, pad to pad | isolated | isolated | `[meter]` |
| SOIC 1.27 pads to ground copper | isolated | isolated | `[meter]` |
| TSSOP, 0.5 pitch, SOT-23, 0603, 0402 pads, pad to pad and to ground | isolated | isolated | `[meter]` |

What this settles:
- Both bits, at the tested settings, prove 0.20 clearance and 0.15 traces: the finest features on the board.
- The ball mill row-1 sliver and the pointed bit's row 1–2 slivers do not bridge.
- The pointed bit's 0.15 and 0.20 traces are connected even though no flat copper is visible.
- This is a pass/fail test. It doesn't change the measured cut widths in §2 or the recommended told widths in §4.
- Every footprint is electrically isolated on both boards, including 0.5 pitch. The usable / marginal / unusable ratings in §3 are about **pad size for soldering**, not isolation, so they stand.
