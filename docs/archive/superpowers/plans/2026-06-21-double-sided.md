# gerber2rml: Double-sided dowel-pin registration (Plan E)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Mill double-sided boards using two dowel-pin alignment holes: drill the holes, mill the bottom, flip the board over the horizontal pin line, mill the top (correctly transformed), cut out.

**Architecture:** A GUI-free `doublesided` module computes the layout (placed B.Cu/F.Cu, alignment holes, flip transform) and builds the labelled RML job sequence by reusing the existing engines + SRM-20 backend. The loader gains F.Cu. The calibration coupon gains a top side for physical validation. A GUI "Double-sided" mode triggers the job set.

**Registration math (the invariant):** the two 3.0 mm alignment holes sit on a horizontal axis through the board's vertical centre; they are invariant under a flip about that axis. The **top side's transform = the bottom side's transform reflected about that axis** (`reflect_y`). A test asserts the alignment holes + a sample through-hole coincide between sides; the double-sided coupon validates it physically.

**Tech Stack:** Python 3.10+, shapely (affinity reflect), gerbonara, PySide6, pytest. Defaults: pin diameter 3.0 mm, waste margin 6.0 mm, horizontal flip axis.

---

## File Structure

| File | Responsibility |
|---|---|
| `gerber2rml/loader.py` (modify) | read F.Cu into `Board.copper_top` (optional) |
| `gerber2rml/doublesided.py` (create) | layout (place+mirror+reflect, align holes) + `build_double_sided` |
| `gerber2rml/examples/calibration.py` (modify) | optional F.Cu top side for the coupon |
| `gerber2rml/gui/app.py` (modify) | "Double-sided" checkbox → export the job set; warn if no F.Cu |
| `tests/*` | loader F.Cu, the flip invariant, the job builder, GUI |

---

## Task 1: Loader reads F.Cu

**Files:** Modify `gerber2rml/loader.py`; Test `tests/test_loader.py` (append)

Add top copper to `Board` (default empty when absent). Use gerbonara key `('top','copper')`. Mirror it with the rest when `mirror=True` (so it stays in the same raw→placed pipeline as B.Cu).

- [ ] **Step 1: Append failing test**
```python
def test_loads_top_copper_field():
    board = load_board(FIXT, mirror=False)
    assert hasattr(board, "copper_top")     # present (may be empty if no F.Cu)
```

- [ ] **Step 2: Run — expect FAIL** `AttributeError: ... 'copper_top'`.

- [ ] **Step 3: Implement** — add `copper_top` to the `Board` dataclass (a shapely geometry; default via `field(default_factory=Polygon)` or set in `load_board`). In `load_board`, build it with the same `_copper_to_shapely` helper from the `('top','copper')` layer **if present** (use `stack.graphic_layers.get(('top','copper'))`; if None, empty `Polygon()`). Apply the same mirror as copper/outline when `mirror=True`. Do NOT change existing fields/behaviour.

- [ ] **Step 4: Run** `tests/test_loader.py` + full suite → green.

- [ ] **Step 5: Commit**
```bash
git add gerber2rml/loader.py tests/test_loader.py
git commit -m "Loader: read F.Cu into Board.copper_top"
```

---

## Task 2: Double-sided layout + flip invariant

**Files:** Create `gerber2rml/doublesided.py`; Test `tests/test_doublesided.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_doublesided.py
from pathlib import Path
from gerber2rml.doublesided import layout_double_sided, reflect_y

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"

def test_reflect_y_fixes_axis():
    # a point on the axis is unchanged; off-axis reflects
    assert reflect_y([(5.0, 10.0, 0.8)], y_axis=10.0)[0][1] == 10.0
    assert reflect_y([(5.0, 12.0, 0.8)], y_axis=10.0)[0][1] == 8.0

def test_layout_has_two_align_holes_on_axis():
    lay = layout_double_sided(FIXT, pin_diameter=3.0, margin=6.0)
    assert len(lay.align_holes) == 2
    # both on the flip axis
    assert abs(lay.align_holes[0][1] - lay.y_axis) < 1e-6
    assert abs(lay.align_holes[1][1] - lay.y_axis) < 1e-6
    # one left of the board, one right
    bx0, _by0, bx1, _by1 = lay.outline.bounds
    assert lay.align_holes[0][0] < bx0 and lay.align_holes[1][0] > bx1
    # pins span at least the 104 mm jig box (placed beyond it)
    assert lay.align_holes[1][0] - lay.align_holes[0][0] >= 104.0
    # everything is in the positive quadrant
    assert lay.align_holes[0][0] > 0
    # all align holes are the pin diameter
    assert all(abs(d - 3.0) < 1e-6 for (_x, _y, d) in lay.align_holes)

def test_through_hole_registers_after_flip():
    lay = layout_double_sided(FIXT, pin_diameter=3.0, margin=6.0)
    # a bottom hole reflected about the axis is where the top side expects it
    (hx, hy, hd) = lay.holes[0]
    assert any(abs(rx - hx) < 1e-6 and abs(ry - (2 * lay.y_axis - hy)) < 1e-6
               for (rx, ry, rd) in reflect_y(lay.holes, lay.y_axis))
```

- [ ] **Step 2: Run — expect FAIL** `ModuleNotFoundError`.

- [ ] **Step 3: Implement**
```python
# gerber2rml/doublesided.py
"""Double-sided dowel-pin registration: layout + job builder.

The two alignment holes sit on a horizontal axis through the board's vertical
centre (invariant under the flip). Top transform = bottom transform reflected
about that axis, so the sides register after the physical flip.
"""
from dataclasses import dataclass
from pathlib import Path
from shapely.affinity import scale, translate
from gerber2rml.loader import load_board

def reflect_y(holes, y_axis):
    """Reflect (x, y, d) hole tuples about the horizontal line y = y_axis."""
    return [(x, 2 * y_axis - y, d) for (x, y, d) in holes]

def _reflect_geom(geom, y_axis):
    return scale(geom, xfact=1, yfact=-1, origin=(0, y_axis))

@dataclass
class DoubleSidedLayout:
    bottom_copper: object
    top_copper: object
    outline: object
    holes: list           # placed through-holes (bottom frame)
    align_holes: list     # 2 alignment holes on the flip axis
    y_axis: float

def layout_double_sided(folder, pin_diameter: float = 3.0, margin: float = 6.0,
                        box_size: float = 104.0):
    """Place the board + two alignment holes in the positive quadrant. The pins
    sit beyond `box_size` (the 104x104 laser-jig box) — or beyond the board if it
    is wider — so they never encroach on the board area."""
    folder = Path(folder)
    b = load_board(folder, mirror=True)   # raw, mirrored
    geoms = [g for g in (b.copper, b.outline) if not g.is_empty]
    gx0 = min(g.bounds[0] for g in geoms); gy0 = min(g.bounds[1] for g in geoms)
    gx1 = max(g.bounds[2] for g in geoms); gy1 = max(g.bounds[3] for g in geoms)
    cx = (gx0 + gx1) / 2.0
    y_axis_raw = (gy0 + gy1) / 2.0
    # pins beyond the larger of the board half-width and the jig-box half-width
    half = max((gx1 - gx0) / 2.0, box_size / 2.0) + pin_diameter
    align_raw = [(cx - half, y_axis_raw, pin_diameter),
                 (cx + half, y_axis_raw, pin_diameter)]
    # shift everything (incl. the left pin's radius) into the positive quadrant
    allminx = min(gx0, cx - half - pin_diameter / 2.0)
    allminy = min(gy0, y_axis_raw - pin_diameter / 2.0)
    dx, dy = margin - allminx, margin - allminy
    bottom_copper = translate(b.copper, xoff=dx, yoff=dy)
    top_src = translate(b.copper_top, xoff=dx, yoff=dy)
    outline = translate(b.outline, xoff=dx, yoff=dy)
    holes = [(x + dx, y + dy, d) for (x, y, d) in b.holes]
    align_holes = [(x + dx, y + dy, d) for (x, y, d) in align_raw]
    y_axis = y_axis_raw + dy
    top_copper = _reflect_geom(top_src, y_axis)
    return DoubleSidedLayout(bottom_copper, top_copper, outline, holes,
                             align_holes, y_axis)
```

- [ ] **Step 4: Run** `tests/test_doublesided.py` → 3 pass. Full suite green.

- [ ] **Step 5: Commit**
```bash
git add gerber2rml/doublesided.py tests/test_doublesided.py
git commit -m "Double-sided layout: align holes on flip axis, reflected top copper"
```

---

## Task 3: Double-sided job builder (RML sequence)

**Files:** Modify `gerber2rml/doublesided.py`; Test `tests/test_doublesided.py` (append)

Produce the labelled RML job set: align-drill, bottom-drill, bottom-traces, top-traces, cutout, + a runplan.

- [ ] **Step 1: Append failing test**
```python
def test_build_double_sided_writes_jobs(tmp_path):
    from gerber2rml.doublesided import build_double_sided
    from gerber2rml.config import TraceJob, DrillJob, CutoutJob
    written = build_double_sided(FIXT, tmp_path, name="ds",
                                 trace=TraceJob(), drill=DrillJob(), cutout=CutoutJob())
    names = {p.name for p in written}
    for n in ("ds_align.rml", "ds_bottom_drill.rml", "ds_bottom_traces.rml",
              "ds_top_traces.rml", "ds_cutout.rml"):
        assert n in names
    for p in written:
        if p.suffix == ".rml":
            t = p.read_text()
            assert t.startswith("^IN;!MC1;") and t.rstrip().endswith("!MC0;^IN;")
```

- [ ] **Step 2: Run — expect FAIL** `ImportError: cannot import name 'build_double_sided'`.

- [ ] **Step 3: Implement** in `doublesided.py`:
```python
from gerber2rml.engine.traces import isolate
from gerber2rml.engine.drill import drill_holes
from gerber2rml.engine.cutout import cut_outline
from gerber2rml.backends import srm20
from gerber2rml.config import TraceJob, DrillJob, CutoutJob

def build_double_sided(folder, out_dir, name, trace=None, drill=None, cutout=None,
                       pin_diameter: float = 3.0, margin: float = 6.0):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    trace, drill, cutout = trace or TraceJob(), drill or DrillJob(), cutout or CutoutJob()
    lay = layout_double_sided(folder, pin_diameter=pin_diameter, margin=margin)
    top_outline = _reflect_geom(lay.outline, lay.y_axis)
    jobs = [
        (f"{name}_align.rml", drill_holes(lay.align_holes, drill), drill),
        (f"{name}_bottom_drill.rml", drill_holes(lay.holes + lay.align_holes, drill), drill),
        (f"{name}_bottom_traces.rml", isolate(lay.bottom_copper, trace, outline=lay.outline), trace),
        (f"{name}_top_traces.rml", isolate(lay.top_copper, trace, outline=top_outline), trace),
        (f"{name}_cutout.rml", cut_outline(lay.outline, cutout), cutout),
    ]
    written = []
    for fname, paths, job in jobs:
        (out_dir / fname).write_text(
            srm20.render(paths, xy_feed=job.xy_feed, plunge_feed=job.plunge_feed))
        written.append(out_dir / fname)
    runplan = out_dir / f"{name}_runplan.txt"
    runplan.write_text(
        f"DOUBLE-SIDED run plan: {name}\n"
        f"1. {name}_align: drill the two {pin_diameter} mm holes through board AND bed; seat dowel pins.\n"
        f"2. {name}_bottom_drill, then {name}_bottom_traces (B.Cu).\n"
        f"3. FLIP the board top-over-bottom about the horizontal pin line; drop onto the pins.\n"
        f"4. {name}_top_traces (F.Cu).\n"
        f"5. {name}_cutout last. Keep XY origin at the left pin throughout.\n",
        encoding="utf-8")
    written.append(runplan)
    return written
```

- [ ] **Step 4: Run** `tests/test_doublesided.py` + full suite → green.

- [ ] **Step 5: Commit**
```bash
git add gerber2rml/doublesided.py tests/test_doublesided.py
git commit -m "Double-sided job builder: align/bottom/top/cutout RML + runplan"
```

---

## Task 4: Double-sided calibration coupon (F.Cu)

**Files:** Modify `gerber2rml/examples/calibration.py`; Test `tests/test_calibration.py` (append)

Add a front-copper layer to the coupon so the flip can be physically validated: top pads on the same through-holes as the bottom, plus one clearly asymmetric top-only marker so misregistration is visible.

- [ ] **Step 1: Append failing test**
```python
def test_coupon_has_top_copper(tmp_path):
    folder = write_coupon(tmp_path)
    assert any(n.endswith("F_Cu.gbr") and (folder / n).stat().st_size > 200
               for n in [p.name for p in folder.iterdir()])
```
(The coupon already emits an empty `calib-F_Cu.gbr`; this asserts it now has real content.)

- [ ] **Step 2: Run — expect FAIL** (empty F.Cu file is tiny).

- [ ] **Step 3: Implement** — in `write_coupon`, emit real F.Cu copper: a ⌀1.6 mm pad (region) on every drill hole (same positions as the bottom pads, so through-holes are ringed on both sides) plus one asymmetric top-only feature (e.g. a small rectangle near one corner) so a flip error is visually obvious. Reuse the same region-emit helpers; write to `calib-F_Cu.gbr` instead of the empty stub. Keep all other layers/holes unchanged. Regenerate the committed `examples/calibration/` files (`write_coupon(Path("examples/calibration"))`).

- [ ] **Step 4: Run** `tests/test_calibration.py` + full suite → green.

- [ ] **Step 5: Commit**
```bash
git add gerber2rml/examples/calibration.py tests/test_calibration.py examples/calibration
git commit -m "Calibration coupon: add F.Cu top side for double-sided validation"
```

---

## Task 5: GUI double-sided mode

**Files:** Modify `gerber2rml/gui/app.py`; Test `tests/test_window.py` (append)

- [ ] **Step 1: Append failing test**
```python
def test_double_sided_export(tmp_path):
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.double_sided_chk.setChecked(True)
    written = w.export_to(tmp_path)
    assert any(p.name.endswith("_top_traces.rml") for p in written)
```

- [ ] **Step 2: Run — expect FAIL** `AttributeError: ... 'double_sided_chk'`.

- [ ] **Step 3: Implement** — add a `QCheckBox("Double-sided")` to the Project group (store as `self.double_sided_chk`). In `export_to`, branch:
```python
    def export_to(self, out_dir):
        self._sync_state()
        if self.double_sided_chk.isChecked():
            from gerber2rml.doublesided import build_double_sided
            return build_double_sided(self.state.gerber_dir, out_dir, self.state.name,
                                      trace=self.state.trace, drill=self.state.drill,
                                      cutout=self.state.cutout)
        return self.state.export(out_dir)
```
In `_on_export_clicked`, if double-sided is checked and the loaded board has no F.Cu (`self.state.board.copper_top.is_empty`), show a `QMessageBox.warning` ("No F.Cu found — double-sided needs front copper") and proceed only if the user is okay (or just warn and continue). Keep single-sided behaviour unchanged when the box is off.

- [ ] **Step 4: Run** `tests/test_window.py` + full suite → green.

- [ ] **Step 5: Commit**
```bash
git add gerber2rml/gui/app.py tests/test_window.py
git commit -m "GUI: double-sided export mode"
```

---

## Task 6: Docs

**Files:** Modify `README.md`

- [ ] **Step 1** Add a "Double-sided boards" section: the dowel-pin method, the operator sequence (drill align holes into board+bed → pins → bottom → flip top-over-bottom about the horizontal pin line → top → cutout), the 3.0 mm pin / 6 mm waste defaults, the need for F.Cu, and the **validate-with-the-coupon-first** caution (registration is bounded by SRM-20 repeatability ~0.05–0.1 mm). Commit `"Document double-sided dowel-pin workflow"`.

---

## Self-Review
- **Coverage:** F.Cu load (T1), layout+flip invariant (T2), job builder (T3), validation coupon (T4), GUI mode (T5), docs (T6).
- **Invariant:** `reflect_y`/`_reflect_geom` about `y_axis`; top transform = reflected bottom; align holes on axis (tested coincide). Physical correctness validated by the double-sided coupon before any real board.
- **Type consistency:** `layout_double_sided(folder, pin_diameter, margin) -> DoubleSidedLayout`; `reflect_y(holes, y_axis) -> list`; `build_double_sided(folder, out_dir, name, trace=, drill=, cutout=, pin_diameter=, margin=)`; `Board.copper_top` (T1) used by layout; engines/backend reused unchanged.
- **Backward-compat:** single-sided paths untouched (new checkbox off by default; `load_board` only adds a field).

## Deferred
- Configurable flip axis (vertical), top-side drilling-from-top, copper clearing on both sides, auto stock-size check. Future.
