# What each bit can cut

Tested 4 Nov 2026 on `examples/torture_60x30`, SRM-20, 3 mm/s feed, 0.5 mm/s plunge. Full evidence: [the analysis brief](archive/2026-11-04-bit-analysis-brief.md).

**Limits only hold with their settings.** Told width, depth and narrow gaps all change the result.

## Capability

| | Ball mill, **standard** | Ball mill, earlier | Pointed bit (one-off) | 0.8 mm flat |
|---|---|---|---|---|
| Told width | 0.44 mm | 0.30 mm | 0.20 mm | |
| Depth | 0.08 mm, one pass | 0.08 mm, one pass | 0.05, 0.10, 0.11 mm passes | |
| Cut gaps too narrow | On | On | Off | |
| Finest gap, metered | 0.20 mm* | 0.20 mm* | 0.20 mm* | No data |
| Finest trace, metered | 0.15 mm* | 0.15 mm* | 0.15 mm* | No data |
| Usable | Not rated by measurement | SOIC 1.27, SOT-23, 0603, 0402 | SOIC 1.27, SOT-23, 0603 | No data |
| Marginal | Not rated by measurement | TSSOP 0.65 | TSSOP 0.65, 0.5 pitch, 0402 | No data |
| Not usable | 0.5 pitch, by calculation | 0.5 pitch | | No data |
| Holes and cut-out | Ran once, 1.9 mm deep | Untested | Don't: tip is fragile | |

\* The finest on the board, so the real limit may be lower. Isolated pads were metered on the told 0.30 and pointed boards; on told 0.44, Mads reports all rows measure good. Ratings are from photos of the earlier boards. Told 0.44 pads looked about right under the microscope on the solder board, with no numbers recorded. No part rating here comes from soldering.

**Profiles:** the app ships `SRM-20 0.8 mm flat` and `SRM-20 0.8 mm ball mill` (told 0.44 mm traces, 0.8 mm holes and outline at 1.9 mm, 4 tabs, 3 and 0.5 mm/s).

**Earlier ball mill card (0.08 mm, narrow gaps on, Mads's meter):**

| Told width | Gaps | Traces |
|---|---|---|
| 0.15 mm | Open down to 0.10 mm | 0.15 and 0.10 mm cut away |
| 0.30 mm | Not recorded by row | Continuity down to 0.10 mm |

## Measured cut

| Bit | Channel at copper top | Bare laminate floor |
|---|---|---|
| Ball mill, 0.08 mm | 0.44 mm (0.41-0.47) | 0.29 mm (0.21-0.36) |
| Pointed bit, 0.11 mm | 0.45 mm (0.39-0.50) | 0.19 mm (0.13-0.23) |

Measured from microscope photos, about ±0.03 mm.

## Which bit

- **Gaps of 0.8 mm and up: the 0.8 mm flat.** The everyday profile, and faster at 4 mm/s. It hasn't been through this test, so its limit is just the bit's width.
- **Gaps under 0.8 mm: the ball mill.** You can buy another, and it needed less depth and one pass.
- **Pointed bit: a data point, no saved profile.** It's one accidentally snapped 0.8 mm flat bit, nobody can buy it, and at 0.11 mm it's no narrower than the ball mill. It might cut narrower at a shallower depth, which is untested. Its settings: told 0.20 mm, 0.11 mm deep, 3 and 0.5 mm/s, traces only.

## Rules

- **Told width isn't the bit size.** It sets how far the path sits from the copper. Told less than the real cut, every copper edge loses half the difference.
- **Pitch sets the pad limit.** With a cut down a gap between two pads, flat pad width can't exceed pitch minus cut width. At a 0.44 mm cut, that's about 0.21 mm at 0.65 pitch and 0.06 mm at 0.5 pitch, whatever the told width.
- **Tiny traces may have no flat top.** The pointed bit's 0.15 and 0.20 mm traces conduct as a ridge. Current capacity is unknown.
- **Wide gaps can leave a sliver** between the two cuts. It didn't bridge here, but it can flake off.
- **Automatic has no bit change.** With different trace and drill sizes, it drills with the trace bit straight after the traces, without stopping. The ball mill profile relies on this: one bit does the whole job.

## Still unproven

- Ball mill told 0.44 mm: pad widths in numbers, and how long a bit lasts through holes and cut-outs.
- Ball mill depth below 0.08 mm.
- Pointed bit in one pass, at 0.07, 0.09 or 0.11 mm.
- Soldering real TSSOP, 0.5 pitch or 0402 parts.
- Foil thickness (35 µm is assumed).
