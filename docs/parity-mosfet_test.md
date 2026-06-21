# Parity check — gerber2rml vs mods (board: mosfet_test / buck fixture)

**Purpose:** before trusting gerber2rml on real copper, confirm its RML drives the
SRM-20 equivalently to the trusted mods `mill 2D PCB` output for the same board.
Exact move *ordering* will differ (different path planners) — what must match is
**geometry extent** and **that copper is fully isolated**, plus the machine
preamble (spindle on, feeds, units).

## How to regenerate our side

```bash
.venv/Scripts/python.exe -m gerber2rml.cli tests/fixtures/mosfet_test -o out -n mosfet_test
```
Produces `out/mosfet_test_{traces,drill,cutout}.rml` + `mosfet_test_runplan.txt`.

## How to generate the mods side

1. Export the board's **B.Cu** as PNG (≥1000 dpi) or SVG, mirrored, white=copper.
2. Open mods → `programs → open program → machines → Roland → SRM-20 mill → mill 2D PCB`.
3. Tool **1/64" (0.4 mm)**, **2 offsets**, cut depth ~0.1 mm, speed **4 mm/s**.
4. Calculate, save the `.rml`.

## Comparison table — fill the mods column on the machine PC

| Property | gerber2rml (ours) | mods | Match? |
|---|---|---|---|
| Spindle enabled in header | **yes — `^IN;!MC1;`** | `!MC1;` present? | |
| Spindle disabled in footer | **yes — `!MC0;^IN;`** | | |
| Units (RML per mm) | **40 (0.025 mm)** | 40 | |
| XY feed command | **`VS4.0;`** | `VS...;` | |
| Plunge feed command | **`!VZ1.0;`** | `!VZ...;` | |
| Traces move count | **11,399** | (informational; will differ) | n/a |
| Traces bounding box (RML units) | record from our file | record from mods | should match ±rounding |
| All copper isolated (visual) | inspect preview | inspect mods preview | **must match** |

## Acceptance

- ✅ **Header/footer/feeds/units match** (the correctness-critical preamble).
- ✅ **Bounding box of cut moves matches** within rounding (confirms scale + mirror).
- ✅ **Visual: every trace is fully ringed** in both (no missed isolation).
- ⚠️ Move count / ordering will differ — that is expected and not a failure.

## Result (record date + outcome here)

- Date:
- Operator:
- Verdict: PASS / FAIL —
- Notes:

> Until this PASSes for at least one board, treat gerber2rml output as **unverified
> on hardware** — do a dry run (pen/air cut, or cut into scrap) before a real board.
