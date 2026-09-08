# gerber2rml: Drill robustness + Isolation preflight + Report + Copper clearing (Plan D)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Four user-requested features: (1) robust drill-file handling, (2) an isolation preflight that flags un-millable copper gaps, (3) report export (preview image + board summary), (4) true copper clearing for `offsets = -1`.

**Architecture:** Mostly pure GUI-free logic (loader, a new `analysis` module, a `report` module, an engine change), each unit-tested, then thin GUI wiring. The isolate engine gains an optional `outline` arg threaded through `ProjectState`/`cli`.

**Tech Stack:** Python 3.10+, shapely (morphology/clipping), gerbonara, PySide6, pytest.

---

## File Structure

| File | Responsibility |
|---|---|
| `gerber2rml/loader.py` (modify) | drill-file selection (prefer split), dedupe, outline filter |
| `gerber2rml/analysis.py` (create) | `find_narrow_gaps(copper, outline, bit_diameter)` |
| `gerber2rml/report.py` (create) | `board_summary(board, name)` text |
| `gerber2rml/engine/traces.py` (modify) | `isolate(copper, job, outline=None)` clipped clear-all |
| `gerber2rml/app/state.py` (modify) | pass outline to isolate; expose narrow gaps + summary |
| `gerber2rml/cli.py` (modify) | pass outline to isolate |
| `gerber2rml/gui/canvas.py` (modify) | overlay narrow-gap polygons (red) |
| `gerber2rml/gui/app.py` (modify) | preflight warning on export; "Export image+summary" button |
| `tests/*` | one module per feature |

---

## Task 1: Drill-file robustness (loader)

**Files:** Modify `gerber2rml/loader.py`; Test `tests/test_drill_files.py`

The loader must (a) prefer KiCad split `-PTH`/`-NPTH` drill files over a redundant combined `<name>.drl`, (b) dedupe identical hits, (c) drop holes outside the board outline (+1 mm margin). This fixes the boost_v2 case (stale combined `.drl` at a different origin producing phantom holes).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drill_files.py
from gerber2rml.loader import select_drill_holes
from shapely.geometry import box

def _excellon(path, holes):
    lines = ["M48", "METRIC", "T1C0.800", "%", "T1"]
    for (x, y) in holes:
        lines.append(f"X{x:.3f}Y{y:.3f}")
    lines.append("M30")
    path.write_text("\n".join(lines) + "\n")

def test_prefers_split_over_combined(tmp_path):
    # combined file has a stray far-away hole; split has the real one
    _excellon(tmp_path / "b.drl", [(5, 5), (200, 200)])
    _excellon(tmp_path / "b-PTH.drl", [(5, 5)])
    _excellon(tmp_path / "b-NPTH.drl", [])
    holes = select_drill_holes(tmp_path, outline=box(0, 0, 40, 40))
    assert len(holes) == 1
    assert abs(holes[0][0] - 5) < 1e-6

def test_filters_outside_outline_and_dedupes(tmp_path):
    _excellon(tmp_path / "only.drl", [(5, 5), (5, 5), (100, 100)])
    holes = select_drill_holes(tmp_path, outline=box(0, 0, 40, 40))
    assert len(holes) == 1            # dup removed, (100,100) outside dropped
```

- [ ] **Step 2: Run — expect FAIL** `ImportError: cannot import name 'select_drill_holes'`.
Run: `.venv\Scripts\python.exe -m pytest tests/test_drill_files.py -v`

- [ ] **Step 3: Implement** in `loader.py` (use the gerbonara Excellon reader already used; `ExcellonFile.open(str(path))`, hits are `Flash` with `.x/.y/.aperture.diameter`):

```python
from gerbonara.excellon import ExcellonFile  # add near other imports

def select_drill_holes(folder, outline=None, margin: float = 1.0):
    """Read drill hits, preferring KiCad split (-PTH/-NPTH) over a redundant
    combined <name>.drl, deduping, and dropping holes outside the outline."""
    folder = Path(folder)
    drl = sorted(folder.glob("*.drl"))
    split = [p for p in drl if p.stem.upper().endswith(("-PTH", "-NPTH", "_PTH", "_NPTH"))]
    sources = split if split else drl
    holes = []
    for p in sources:
        ex = ExcellonFile.open(str(p))
        for o in ex.objects:
            if type(o).__name__ == "Flash":
                holes.append((o.x, o.y, getattr(o.aperture, "diameter", 0) or 0))
    seen, uniq = set(), []
    for h in holes:
        k = (round(h[0], 3), round(h[1], 3), round(h[2], 3))
        if k not in seen:
            seen.add(k); uniq.append(h)
    if outline is not None and not outline.is_empty:
        x0, y0, x1, y1 = outline.bounds
        uniq = [(x, y, d) for (x, y, d) in uniq
                if x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin]
    return uniq
```

- [ ] **Step 4: Wire into `load_board`** — replace the existing drill-reading block (the `list(stack.drill_layers)` loop) so holes come from `select_drill_holes(folder, outline=<raw outline before mirror>)`. The outline must be the RAW (pre-mirror) outline so the filter matches raw hit coordinates; mirror the returned holes afterward exactly as before. Keep the existing `warnings.warn` if no holes found.

- [ ] **Step 5: Run** `tests/test_drill_files.py` + `tests/test_loader.py` + full suite → all green. The loader tests still pass (fixture has one `.drl`).

- [ ] **Step 6: Commit**
```bash
git add gerber2rml/loader.py tests/test_drill_files.py
git commit -m "Robust drill loading: prefer split files, dedupe, filter to outline"
```

---

## Task 2: Isolation preflight (find_narrow_gaps)

**Files:** Create `gerber2rml/analysis.py`; Test `tests/test_analysis.py`

A copper-free channel narrower than the bit diameter can't be milled → potential short. Detect via morphological opening: `region = outline − copper`; channels narrower than the bit are `region − opening(region, r)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analysis.py
from shapely.geometry import box
from gerber2rml.analysis import find_narrow_gaps

def test_flags_gap_narrower_than_bit():
    outline = box(0, 0, 20, 20)
    copper = box(2, 2, 9.7, 18).union(box(10.3, 2, 18, 18))  # 0.6 mm gap
    gaps = find_narrow_gaps(copper, outline, bit_diameter=0.8)
    assert not gaps.is_empty            # 0.6 mm < 0.8 mm bit -> flagged

def test_no_flag_when_gap_wide_enough():
    outline = box(0, 0, 20, 20)
    copper = box(2, 2, 8, 18).union(box(12, 2, 18, 18))      # 4 mm gap
    gaps = find_narrow_gaps(copper, outline, bit_diameter=0.8)
    assert gaps.is_empty
```

- [ ] **Step 2: Run — expect FAIL** `ModuleNotFoundError: gerber2rml.analysis`.

- [ ] **Step 3: Implement**

```python
# gerber2rml/analysis.py
"""Isolation preflight: copper-free channels narrower than the bit can't be milled."""

def find_narrow_gaps(copper, outline, bit_diameter, min_area: float = 0.01):
    """Return a shapely geometry of copper-free channels narrower than the bit
    (an opening by the bit radius removes wider channels; the remainder is the
    un-millable slivers). Empty geometry if none."""
    r = bit_diameter / 2.0
    region = outline.difference(copper)
    if region.is_empty:
        return region
    opened = region.buffer(-r).buffer(r)
    narrow = region.difference(opened)
    if narrow.is_empty:
        return narrow
    # drop numerical specks
    from shapely.geometry import MultiPolygon, Polygon
    polys = narrow.geoms if isinstance(narrow, MultiPolygon) else [narrow]
    keep = [p for p in polys if isinstance(p, Polygon) and p.area >= min_area]
    return MultiPolygon(keep) if keep else Polygon()
```

- [ ] **Step 4: Run** `tests/test_analysis.py` → 2 pass. Full suite green.

- [ ] **Step 5: Commit**
```bash
git add gerber2rml/analysis.py tests/test_analysis.py
git commit -m "Add isolation preflight: find copper gaps narrower than the bit"
```

---

## Task 3: Report — board summary

**Files:** Create `gerber2rml/report.py`; Test `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report.py
from pathlib import Path
from gerber2rml.report import board_summary
from gerber2rml.loader import load_board

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"

def test_summary_has_size_and_holes():
    board = load_board(FIXT, mirror=False)
    text = board_summary(board, name="demo")
    assert "demo" in text
    assert "mm" in text
    assert "Holes" in text
```

- [ ] **Step 2: Run — expect FAIL** `ModuleNotFoundError: gerber2rml.report`.

- [ ] **Step 3: Implement**

```python
# gerber2rml/report.py
"""Board summary text for documentation / the report."""
from collections import Counter

def board_summary(board, name: str = "board") -> str:
    x0, y0, x1, y1 = board.outline.bounds
    lines = [f"# {name} - board summary", "",
             f"- Size: {x1 - x0:.1f} x {y1 - y0:.1f} mm",
             f"- Copper area: {board.copper.area:.1f} mm^2",
             f"- Holes: {len(board.holes)}"]
    by_dia = Counter(round(d, 2) for (_x, _y, d) in board.holes)
    for dia, n in sorted(by_dia.items()):
        lines.append(f"  - {dia} mm x {n}")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run** → pass. Full suite green.

- [ ] **Step 5: Commit**
```bash
git add gerber2rml/report.py tests/test_report.py
git commit -m "Add board summary report text"
```

---

## Task 4: True copper clearing (isolate offsets=-1, clipped to outline)

**Files:** Modify `gerber2rml/engine/traces.py`, `gerber2rml/app/state.py`, `gerber2rml/cli.py`; Test `tests/test_traces.py`

`offsets = -1` should concentrically pocket the copper-free background, **clipped to the outline**, terminating when no copper-free area remains — instead of spiralling to a cap (today's bug).

- [ ] **Step 1: Write the failing test** (append to `tests/test_traces.py`)

```python
def test_clear_all_terminates_and_stays_in_outline():
    from shapely.geometry import box, Point
    outline = box(0, 0, 20, 20)
    copper = Point(10, 10).buffer(2.0)        # one pad in the middle
    job = TraceJob(bit_diameter=0.8, offsets=-1, stepover=0.5)
    paths = isolate(copper, job, outline=outline)
    assert 0 < len(paths) < 200               # terminates, not the 1000+ cap
    xs = [m.x for tp in paths for m in tp if not m.rapid]
    assert min(xs) >= -1 and max(xs) <= 21     # clipped to the board, no huge rings
```

- [ ] **Step 2: Run — expect FAIL** (signature/behaviour: `isolate()` takes no `outline`, or assertion fails).

- [ ] **Step 3: Implement** — change `isolate` to accept `outline=None` and branch clear-all:

```python
def isolate(copper, job, outline=None):
    r = job.bit_diameter / 2.0
    step = job.stepover * job.bit_diameter
    cut_z, travel_z = -job.cut_depth, job.travel_z
    paths = []
    if job.offsets == -1:
        clip = outline if (outline is not None and not outline.is_empty) else copper.envelope
        i = 0
        while True:
            grown = copper.buffer(r + i * step)
            clipped = grown.intersection(clip)
            for coords in _rings(clipped):
                paths.append(_ring_to_toolpath(coords, cut_z, travel_z))
            remaining = clip.difference(grown)
            if remaining.is_empty or remaining.area < 1e-3:
                break
            if i > 5000:                       # hard backstop
                break
            i += 1
        return paths
    # finite offsets (unchanged)
    for i in range(job.offsets):
        grown = copper.buffer(r + i * step)
        if grown.is_empty:
            break
        for coords in _rings(grown):
            paths.append(_ring_to_toolpath(coords, cut_z, travel_z))
    return paths
```
Keep `_rings` and `_ring_to_toolpath` as-is. Remove the old `while True` clear-all block if present, replacing with the above. Existing finite-offset tests call `isolate(copper, job)` (outline defaults None) and must still pass.

- [ ] **Step 4: Thread the outline through** — in `gerber2rml/app/state.py` `toolpaths("traces")` call `isolate(self.board.copper, self.trace, outline=self.board.outline)`; in `gerber2rml/cli.py` `build_jobs`, change the traces line to `isolate(board.copper, trace, outline=board.outline)`.

- [ ] **Step 5: Run** `tests/test_traces.py` + `tests/test_cli.py` + `tests/test_state.py` + full suite → green.

- [ ] **Step 6: Commit**
```bash
git add gerber2rml/engine/traces.py gerber2rml/app/state.py gerber2rml/cli.py tests/test_traces.py
git commit -m "True copper clearing for offsets=-1: clip to outline and terminate"
```

---

## Task 5: GUI wiring (gap overlay + preflight warning + report export)

**Files:** Modify `gerber2rml/gui/canvas.py`, `gerber2rml/gui/app.py`; Test `tests/test_window.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_window.py`)

```python
def test_export_image_writes_png(tmp_path):
    w = MainWindow()
    w.load_folder(str(FIXT))
    w.generate_preview()
    out = w.export_image_to(tmp_path)
    assert out.exists() and out.suffix == ".png"
    assert (tmp_path / (out.stem + "_summary.md")).exists()
```

- [ ] **Step 2: Run — expect FAIL** `AttributeError: ... 'export_image_to'`.

- [ ] **Step 3: Implement**

In `canvas.py`, add an optional gaps overlay to `show_segments`:
```python
    def show_gaps(self, gaps):
        """Overlay narrow-gap polygons (preflight) in red on the current view."""
        from shapely.geometry import MultiPolygon
        polys = gaps.geoms if isinstance(gaps, MultiPolygon) else [gaps]
        for p in polys:
            if not p.is_empty:
                xs, ys = p.exterior.xy
                self.ax.fill(list(xs), list(ys), color="#ff0000", alpha=0.5, zorder=5)
        self.canvas.draw_idle()
```

In `app.py`:
- In `generate_preview`, for the traces op, after drawing, compute and overlay gaps:
  ```python
  from gerber2rml.analysis import find_narrow_gaps
  gaps = find_narrow_gaps(self.state.board.copper, self.state.board.outline,
                          self.state.trace.bit_diameter)
  if not gaps.is_empty:
      self.preview.show_gaps(gaps)
      self.statusBar().showMessage("Warning: copper gaps too narrow to isolate (red)", 8000)
  ```
- Add an `export_image_to(out_dir)` method and an "Export image" button:
  ```python
  def export_image_to(self, out_dir):
      from pathlib import Path
      from gerber2rml.report import board_summary
      out_dir = Path(out_dir)
      png = out_dir / f"{self.state.name}_preview.png"
      self.preview.figure.savefig(str(png), facecolor=self.preview.figure.get_facecolor())
      if self.state.board is not None:
          (out_dir / f"{self.state.name}_preview_summary.md").write_text(
              board_summary(self.state.board, self.state.name), encoding="utf-8")
      return png
  ```
  Wire a `QPushButton("Export image")` in the Project group calling a `_on_export_image` dialog wrapper (mirror `_on_export_clicked`'s folder-pick + guard).

- [ ] **Step 4: Run** `tests/test_window.py` + full suite → green.

- [ ] **Step 5: Commit**
```bash
git add gerber2rml/gui/canvas.py gerber2rml/gui/app.py tests/test_window.py
git commit -m "GUI: narrow-gap preflight overlay + export preview image and summary"
```

---

## Task 6: Docs

**Files:** Modify `README.md`

- [ ] **Step 1** Add a short "Preflight, reports & clearing" section: the isolation preflight (red = un-millable gaps), report export (PNG + summary), and that `offsets = -1` now truly clears copper. Commit `"Document preflight, report export, and copper clearing"`.

---

## Self-Review
- **Coverage:** drill robustness (Task 1), isolation preflight + GUI overlay/warning (Tasks 2,5), report summary + image export (Tasks 3,5), true copper clearing wired through state+cli (Task 4). Docs (Task 6).
- **Type consistency:** `select_drill_holes(folder, outline=, margin=)` (T1); `find_narrow_gaps(copper, outline, bit_diameter)` → shapely geom (T2,T5); `board_summary(board, name)` → str (T3,T5); `isolate(copper, job, outline=None)` (T4, used by state+cli); `PreviewCanvas.show_gaps(gaps)`, `MainWindow.export_image_to(out_dir)` (T5).
- **Backward-compat:** `isolate(copper, job)` still valid (outline defaults None); existing finite-offset/cli/state tests unaffected.

## Deferred
- V-bit isolation, machining-time estimate, GRBL backend, measure tool, save/load project — future plans.
