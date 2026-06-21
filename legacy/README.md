# legacy/

Migrated verbatim from the team repo (`hardware/roland-cnc/`) on branch
`add-mosfet-test-board`. Kept as a historical reference and parity input, **not**
as a working tool.

- `gcode_to_rml.py` — the original minimal G-code→RML converter. Known bugs are
  documented in [`../docs/design.md`](../docs/design.md) §6; the corrected
  emitter lives in `gerber2rml/backends/srm20.py`.
- `test_square.nc` — synthetic 20 mm square G-code used to verify the RML scale
  (20 mm → 800 RML units, confirming 40 units/mm).
- `test_square.rml` — output the legacy script produced from `test_square.nc`.
  Reflects the legacy bugs (e.g. `!MC0` in the header → spindle disabled), so it
  is **not** a golden file. Real golden fixtures will be generated during
  implementation, including a parity diff against mods on a real board.
