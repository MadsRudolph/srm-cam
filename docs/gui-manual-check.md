# GUI manual smoke check

Automated tests drive the window **offscreen** (construction, load, preview,
export, mirror-toggle reload all pass). What they can't confirm is that the window
actually *looks* and *feels* right on a real display. A human runs this once.

## Run it

```bash
cd <gerber2rml repo>
pip install -e ".[gui]"        # if not already
python -m gerber2rml           # or the `gerber2rml` launcher after install
```

## Checklist

- [ ] Window opens; top bar shows **Load Gerber folder…**, a Name field, a Machine
      dropdown (**Roland SRM-20**), and a **Mirror (bottom-up)** checkbox (checked).
- [ ] Left side has three tabs — **Traces / Drill / Cutout** — each with editable
      numeric fields (bit diameter, depths, feeds, offsets, tabs…).
- [ ] Click **Load Gerber folder…**, pick `tests/fixtures/mosfet_test`. The preview
      auto-draws the trace toolpaths (blue cut lines, faint grey rapids).
- [ ] Switch to the **Cutout** tab, click **Generate Preview** — the outline + tabs
      cut path appears (rides just outside the board edge).
- [ ] Change a value (e.g. Traces bit diameter 0.4 → 0.8), **Generate Preview** —
      the isolation rings visibly change.
- [ ] Toggle **Mirror** off and on — the preview redraws each time (board flips).
- [ ] Click **Export .rml…**, pick a temp folder. A dialog lists the written files;
      confirm `*_traces.rml`, `*_drill.rml`, `*_cutout.rml`, `*_runplan.txt` exist.
- [ ] Open a `.rml` in a text editor: starts `^IN;!MC1;`, ends `!MC0;^IN;`,
      coordinates are **positive** (e.g. `Z94,4222,-4;`).
- [ ] Error path: click **Export** before loading anything → a warning dialog
      ("Load a Gerber folder first"), not a crash.

## Result

- Date:
- OS / display:
- Outcome: PASS / FAIL —
- Visual issues / notes:

> Reminder: passing this is NOT hardware verification. `docs/parity-mosfet_test.md`
> (compare against mods on a real board) is still the gate before cutting copper.
