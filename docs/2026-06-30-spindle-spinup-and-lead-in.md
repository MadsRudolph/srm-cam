# Dev log — spindle spin-up settle + ramped lead-in

**Date:** 2026-06-30
**Scope:** soften the moment the bit first engages copper, to avoid the torque
spike at the start of a cut. Two independent mechanisms, both confirmed against
the SRM-20 manual (R4) and shipped on by default.

---

## The request vs. the hardware

The ask was a *"spindle speed ramp"* at the start of the G-code. The SRM-20 can't
do that: it has **no programmable spindle speed**. In NC mode the spindle is
`M3`/`M5` only — there is no `S` word (the machine's word list is `% O ( ) G0 G1
G02 G03 G04 G10 G17–19 G20 G21 G28 G39 G40–42 G53 G54–59 G80–89 G90 G91 G92 G98
G99 M02 M03 M05 M30 F X Y Z I J K N O R`, manual R4 p.115–116). RPM is a **VPanel
cut-setting** (the Spindle Speed Low–High slider, p.119), not a program word. In
RML mode it's `!MC1`/`!MC0`, on/off only. So an S-word ramp would be ignored.

What the manual *does* give us, and what actually serves the goal:

1. **`G04` Dwell IS supported** (Preparation Feature table, p.115). Since the
   machine has **no `P` word** (Other Words table, p.116), the dwell time is the
   `X<seconds>` form: `G04 X2.` = wait 2 s.
2. **`M03` does not wait for spin-up** — the table (p.116) marks it "Function
   Start: same time as the operation in the block," i.e. motion can begin while
   the spindle is still accelerating. So an explicit dwell after `M3` is genuinely
   needed, not belt-and-braces.

## 1. Spindle spin-up settle (`backends/gcode.py`)

After `M3`, the NC header now emits a `G04 X<spinup_s>` dwell (default
`DEFAULT_SPINUP_S = 2.0` s) so the spindle reaches full RPM **before any motion**,
and therefore before the first plunge engages copper. `render(..., spinup_s=…)`
makes it tunable; `spinup_s=0` omits it. Every export gets it automatically (all
`render` call-sites use kwargs/defaults).

`engine/gcode_parse.py` now skips `G04` lines so the simulator/round-trip parser
doesn't mistake the dwell's `X<sec>` argument for an X coordinate.

RML backend: left as-is (no dwell). NC is our production path; RML is the
fallback.

## 2. Ramped lead-in (`engine/leadin.py`)

`apply_lead_in(paths, ramp_len=1.0, clearance=0.2)` replaces a cut path's vertical
entry plunge with a shallow **ramp**: rapid down to 0.2 mm above the surface, then
descend to full depth over the first `ramp_len` mm of the cut path (resampled by
arc length, so even a single long first edge enters gradually). Closed paths
(isolation rings, the cut-out outline) are **re-cut over the ramped stretch at
full depth** at the end, so the gentle entry doesn't leave that bit shallow.

It is a pure transform on `Move` lists (like `apply_leveling`), applied AFTER
toolpath generation but BEFORE placement/leveling, so the ramp Z (nominal,
surface = 0) later warps with the height map. It only touches paths that have a
lateral cut to ramp along:

  * trace isolation rings + cut-out outline → ramped
  * drill plunges / pecks (no lateral cut)  → returned unchanged (still vertical —
    you can't ramp a drilled hole)

Wired into both export paths, on by default, behind a `lead_in` flag:
`cli.build_jobs(..., lead_in=True)` (covers the CLI and the single-sided GUI via
`ProjectState.export`) and `doublesided.build_double_sided(..., lead_in=True)` /
`build_top_traces(..., lead_in=True)`. Drill files are passed through untouched.

Example entry (8 mm ring, 0.15 mm depth, 1 mm ramp):

```
M3
( spindle spin-up settle 2. s before first cut )
G04 X2.
G0 Z2.
G0 X0. Y0.
G0 Z0.2                       <- clearance hop
G1 X0.25 Y0. Z0.113 F240.     <- ramp in...
G1 X0.5  Y0. Z0.025
G1 X0.75 Y0. Z-0.062
G1 X1.   Y0. Z-0.15           <- full depth reached 1 mm along
G1 X8.   Y0. Z-0.15           <- ...ring at depth...
...
G1 X1.   Y0. Z-0.15           <- re-cut the lead-in stretch at depth
G0 Z2.
```

## Interaction notes

- Order is **lead-in → offset → leveling**, so the ramp rides the probed surface.
- The lead-in adds a small amount of extra path (the re-cut + clearance hops); the
  run-time estimate already runs on the final toolpaths, so it stays consistent.
  The `G04` dwell is not motion, so it's excluded from the estimate (the runplan
  already notes the estimate "excludes … spin-up …").
- The ramp descends at the XY feed (standard ramp-entry). For these shallow PCB
  depths the vertical component stays gentle; a dedicated slower ramp feed would
  be a possible future refinement.

## Tests

- `test_gcode_backend.py` — dwell after `M3`, before first motion; `X<sec>` form;
  configurable; `spinup_s=0` omits it.
- `test_gcode_parse.py::test_parse_skips_dwell_line` — `G04 X2.` not read as a move.
- `test_leadin.py` — drills/pecks untouched; entry no longer a vertical plunge;
  gradual monotonic descent to full depth; ring still fully cut at depth; rings
  shorter than the ramp still valid.
- `test_cli.py::test_lead_in_on_by_default_ramps_traces` — wiring on by default.
- Two double-sided leveling tests pass `lead_in=False` to isolate the leveling
  assertion (the ramp's Z steps are covered in `test_leadin.py`).

Full suite: **334 passing** headless.

## Files

```
gerber2rml/backends/gcode.py     (edit) G04 spin-up dwell after M3
gerber2rml/engine/gcode_parse.py (edit) skip G04 when parsing
gerber2rml/engine/leadin.py      (new)  apply_lead_in transform
gerber2rml/cli.py                (edit) lead_in wiring (traces + cut-out)
gerber2rml/doublesided.py        (edit) lead_in wiring (bottom/top traces, cut-out)
tests/test_gcode_backend.py      (new)
tests/test_leadin.py             (new)
tests/test_gcode_parse.py, tests/test_cli.py, tests/test_doublesided.py (edit)
```
