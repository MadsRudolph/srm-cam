# Multi-region Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator mark many rework rectangles at once — each a coloured box with its own depth and height-map-follow toggle — and export them all as one G-code file.

**Architecture:** A new pure engine primitive `clip_toolpaths_to_regions` concatenates per-box clips. The canvas becomes a multi-region renderer + drag source (fires `on_region_added`); the app owns the region list, a table to edit/delete them, and rewires export, run-progress and the rework simulation to the whole region set.

**Tech Stack:** Python 3, PySide6 (GUI), matplotlib (preview), pytest. No new dependencies.

## Global Constraints

- No new third-party dependencies.
- `Move` is frozen (`gerber2rml/toolpath.py`): build new `Move`, never mutate.
- Rework regions clip the **currently-shown op/side** at export (unchanged from today; drill is not reworkable).
- The **Rework depth** spin and **Follow height map** checkbox are the *defaults for the next drawn region*; per-region values live in the table.
- One region == the old single-box behaviour; there is no separate single mode.
- Commits: plain developer messages, **no AI/Claude mention** (team rule).
- Tests run with `python -m pytest`; match existing style in `tests/test_select.py`, `tests/test_canvas.py`, `tests/test_window.py`. GUI tests run offscreen (`QT_QPA_PLATFORM=offscreen`, already set in those files).

---

### Task 1: Engine — `clip_toolpaths_to_regions`

**Files:**
- Modify: `gerber2rml/engine/select.py` (append a new function; leave `clip_toolpaths_to_bbox` untouched)
- Test: `tests/test_select.py` (append)

**Interfaces:**
- Consumes: existing `clip_toolpaths_to_bbox(toolpaths, bbox, cut_z=None)`.
- Produces: `clip_toolpaths_to_regions(toolpaths, regions) -> list[list[Move]]`
  where `regions` is `list[(bbox, cut_z)]`; clips `toolpaths` to each region at
  its `cut_z` and concatenates the results in region order.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_select.py
from gerber2rml.engine.select import clip_toolpaths_to_regions


def test_regions_concatenate_each_at_its_depth():
    tp = _ring([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    # box A over the bottom edge at -0.20, box B over the top edge at -0.40
    regions = [((-1, -1, 11, 1), -0.20), ((-1, 9, 11, 11), -0.40)]
    out = clip_toolpaths_to_regions([tp], regions)
    cut_zs = {round(m.z, 3) for path in out for m in path if not m.rapid}
    assert cut_zs == {-0.20, -0.40}                 # both depths present
    pts = _cut_points(out)
    assert (0, 0) in pts and (0, 10) in pts          # geometry from both boxes


def test_regions_skip_empty_boxes():
    tp = _ring([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    regions = [((-1, -1, 11, 1), -0.2), ((50, 50, 60, 60), -0.2)]  # 2nd misses
    out = clip_toolpaths_to_regions([tp], regions)
    # only the bottom edge survives; the empty box contributes nothing
    assert out and all((m.x, m.y) != (10, 10) for path in out for m in path)


def test_regions_empty_list_is_empty():
    tp = _ring([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    assert clip_toolpaths_to_regions([tp], []) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_select.py -k regions -q`
Expected: FAIL (`cannot import name 'clip_toolpaths_to_regions'`).

- [ ] **Step 3: Write the implementation**

```python
# append to gerber2rml/engine/select.py
def clip_toolpaths_to_regions(toolpaths, regions):
    """Clip ``toolpaths`` to several rework rectangles and concatenate.

    ``regions`` is ``[(bbox, cut_z), ...]`` (bbox in board mm, any corner order;
    cut_z in machine mm, negative for below the surface). Each region is clipped
    independently via :func:`clip_toolpaths_to_bbox` and the results are joined
    into one program, regions in the given order. Regions that capture no cut
    geometry contribute nothing. Returns a flat list of ``Move`` toolpaths.
    """
    out = []
    for bbox, cut_z in regions:
        out.extend(clip_toolpaths_to_bbox(toolpaths, bbox, cut_z=cut_z))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_select.py -q`
Expected: PASS (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/engine/select.py tests/test_select.py
git commit -m "feat(rework): clip_toolpaths_to_regions for multi-box passes"
```

---

### Task 2: Canvas — multi-region rendering + `on_region_added`

**Files:**
- Modify: `gerber2rml/gui/canvas.py`
- Test: `tests/test_canvas.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces, on `PreviewCanvas`:
  - `self.on_region_added` — callback `(bbox)` fired when a select-mode drag
    commits a rectangle.
  - `set_rework_regions(regions)` — `regions` is `list[(bbox, color, label)]`
    (bbox `(x0,y0,x1,y1)`, color hex str, label str); stores + redraws.
  - removes the old single-box API: `selection_bbox()`, `clear_selection()`,
    `on_selection_changed`, `_selection_bbox`, `_rect_artist`,
    `_add_selection_patch()`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_canvas.py
def test_canvas_draws_rework_regions():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (10, 0), (10, 10)]], [])
    canvas.set_rework_regions([
        ((0, 0, 4, 4), "#ff5252", "0.20 mm"),
        ((6, 6, 9, 9), "#42a5f5", "0.40 mm"),
    ])
    rects = [p for p in canvas.ax.patches
             if p.__class__.__name__ == "Rectangle"]
    assert len(rects) >= 2                       # one per region


def test_canvas_region_drag_fires_callback():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (10, 0), (10, 10)]], [])
    seen = {}
    canvas.on_region_added = lambda bbox: seen.setdefault("bbox", bbox)
    canvas.set_selecting(True)
    press = type("E", (), {"button": 1, "inaxes": canvas.ax, "xdata": 1.0, "ydata": 1.0})
    move = type("E", (), {"button": 1, "inaxes": canvas.ax, "x": 5, "y": 5, "xdata": 5.0, "ydata": 5.0, "key": None})
    release = type("E", (), {"button": 1, "inaxes": canvas.ax, "xdata": 5.0, "ydata": 5.0})
    canvas._on_press(press()); canvas._on_motion(move()); canvas._on_release(release())
    assert seen["bbox"] == (1.0, 1.0, 5.0, 5.0)


def test_canvas_set_rework_regions_empty_clears():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (10, 0)]], [])
    canvas.set_rework_regions([((0, 0, 4, 4), "#ff5252", "0.20 mm")])
    canvas.set_rework_regions([])                # must not raise
    rects = [p for p in canvas.ax.patches if p.__class__.__name__ == "Rectangle"]
    assert rects == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_canvas.py -k rework_region -q` and
`python -m pytest tests/test_canvas.py -k region_drag -q`
Expected: FAIL (`set_rework_regions` / `on_region_added` missing).

- [ ] **Step 3: Implement the canvas changes**

In `__init__`, replace the single-box selection block (the lines initialising
`self._selecting`, `self._selection_bbox`, `self._drag_start`,
`self._rect_artist`, `self.on_selection_changed`) with:

```python
        # Rework box-selection state. While selecting, a left-drag draws a
        # rubber-band; on release the committed box is reported to the app, which
        # appends it to the region list and pushes the draw list back here.
        self._selecting = False
        self._drag_start = None
        self._drag_bbox = None             # live rubber-band during a drag
        self._rework_regions = []          # list of (bbox, color, label) to draw
        self._rework_artists = []          # matplotlib artists for those regions
        self.on_region_added = None        # callback(bbox) set by the app
```

Replace `selection_bbox()` / `clear_selection()` / `_add_selection_patch()` /
`_redraw_selection_only()` with:

```python
    def set_rework_regions(self, regions):
        """Store the rework regions to draw -- ``[(bbox, color, label), ...]`` --
        and redraw. Pass ``[]`` to clear them."""
        self._rework_regions = list(regions)
        self._draw_fraction(self.slider.value() / 1000.0)

    def _add_rework_patches(self):
        """Draw every stored region in its colour (dashed) with a depth label,
        plus the live rubber-band during a drag."""
        self._rework_artists = []
        for (bbox, color, label) in self._rework_regions:
            x0, y0, x1, y1 = bbox
            rect = Rectangle((min(x0, x1), min(y0, y1)), abs(x1 - x0), abs(y1 - y0),
                             fill=False, edgecolor=color, linestyle="--",
                             linewidth=1.5, zorder=10)
            self.ax.add_patch(rect)
            self._rework_artists.append(rect)
            if label:
                t = self.ax.text(min(x0, x1), max(y0, y1), label, va="bottom",
                                 ha="left", fontsize=8, color=color, zorder=11)
                self._rework_artists.append(t)
        if self._drag_bbox:
            x0, y0, x1, y1 = self._drag_bbox
            live = Rectangle((min(x0, x1), min(y0, y1)), abs(x1 - x0), abs(y1 - y0),
                             fill=False, edgecolor="#ffffff", linestyle=":",
                             linewidth=1.2, zorder=12)
            self.ax.add_patch(live)
            self._rework_artists.append(live)

    def _redraw_rework_only(self):
        """Cheap update of just the rework rectangles during a live drag."""
        for a in self._rework_artists:
            try:
                a.remove()
            except (ValueError, NotImplementedError):
                pass
        self._rework_artists = []
        self._add_rework_patches()
        self.canvas.draw_idle()
```

In the redraw path (`_draw_fraction`/full redraw, where the old code did
`self._rect_artist = None; self._add_selection_patch()` around line 514-515),
replace those two lines with:

```python
        self._rework_artists = []
        self._add_rework_patches()
```

In `_on_motion`, the selecting branch (where it set `self._selection_bbox` and
called `_redraw_selection_only`) becomes:

```python
        if self._drag_start is not None:
            x0, y0 = self._drag_start
            self._drag_bbox = (x0, y0, event.xdata, event.ydata)
            self._redraw_rework_only()
```

In `_on_release`, the selecting branch (the block from `if self._drag_start is
None: return` through the old `on_selection_changed` call) becomes:

```python
        if self._drag_start is None:
            return
        x0, y0 = self._drag_start
        x1 = event.xdata if event.xdata is not None else x0
        y1 = event.ydata if event.ydata is not None else y0
        self._drag_start = None
        self._drag_bbox = None
        if abs(x1 - x0) < 1e-6 or abs(y1 - y0) < 1e-6:
            self._redraw_rework_only()          # a click, not a box
            return
        bbox = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        self._redraw_rework_only()
        if self.on_region_added:
            self.on_region_added(bbox)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_canvas.py -q`
Expected: PASS (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/gui/canvas.py tests/test_canvas.py
git commit -m "feat(rework): canvas draws multiple regions, reports each drag"
```

---

### Task 3: App — region list, table UI, add/delete wiring

**Files:**
- Modify: `gerber2rml/gui/app.py`
- Test: `tests/test_window.py` (append)

**Interfaces:**
- Consumes: Task 2 `set_rework_regions`/`on_region_added`; existing
  `select_chk`, `rework_depth_spin`, `rework_level_chk`, `clear_sel_btn`,
  the Rework `QGroupBox` (built around line 757-763), `_OPS`, `self.tabs`.
- Produces on `MainWindow`:
  - `self._rework_regions` — `list[dict]` with keys `bbox`,`depth`,`follow`,`color`.
  - `_REWORK_COLORS` palette (list of hex strings).
  - `_on_region_added(bbox)`, `_refresh_rework(self)` (rebuild table + canvas
    draw list), `_clear_rework()`, `_delete_rework_region(i)`,
    `_rework_draw_list()` (-> `[(bbox,color,label)]`).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_window.py
def test_rework_add_and_delete_regions():
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()
    w.rework_depth_spin.setValue(0.20)
    w._on_region_added((0.0, 0.0, 4.0, 4.0))
    w.rework_depth_spin.setValue(0.40)
    w._on_region_added((6.0, 6.0, 9.0, 9.0))
    assert len(w._rework_regions) == 2
    assert w.rework_table.rowCount() == 2
    assert abs(w._rework_regions[0]["depth"] - 0.20) < 1e-9
    assert abs(w._rework_regions[1]["depth"] - 0.40) < 1e-9
    w._delete_rework_region(0)
    assert len(w._rework_regions) == 1
    assert abs(w._rework_regions[0]["depth"] - 0.40) < 1e-9


def test_rework_clear_empties_all():
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()
    w._on_region_added((0.0, 0.0, 4.0, 4.0))
    w._clear_rework()
    assert w._rework_regions == [] and w.rework_table.rowCount() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_window.py -k "rework_add or rework_clear" -q`
Expected: FAIL (`_on_region_added` / `rework_table` missing).

- [ ] **Step 3: Implement region state + table**

Near the top of `MainWindow` (class body, before `__init__` or as a class attr),
add the palette:

```python
    _REWORK_COLORS = ["#ff5252", "#42a5f5", "#66bb6a", "#ffa726",
                      "#ab47bc", "#26c6da", "#ec407a", "#d4e157"]
```

In `__init__`, initialise the region list early (near other state inits):

```python
        self._rework_regions = []          # [{bbox, depth, follow, color}]
```

Replace the Rework widget construction (the `select_chk` / `clear_sel_btn` /
`rework_depth_spin` / `rework_level_chk` / `export_sel_btn` block around 579-607)
— keep those widgets but change the two labels' wording and add the table:

```python
        self.select_chk = QCheckBox("Add areas")
        self.select_chk.setToolTip("Drag boxes over each spot to re-cut; each box "
                                   "is added to the list below.")
        self.select_chk.toggled.connect(self._on_select_toggled)
        self.clear_sel_btn = QPushButton("Clear all")
        self.clear_sel_btn.clicked.connect(self._clear_rework)
        self.rework_depth_spin = QDoubleSpinBox()
        self.rework_depth_spin.setRange(0.0, 5.0)
        self.rework_depth_spin.setSingleStep(0.01)
        self.rework_depth_spin.setDecimals(3)
        self.rework_depth_spin.setValue(0.15)
        self.rework_depth_spin.setSuffix(" mm")
        self.rework_depth_spin.setToolTip(
            "Default depth for the NEXT box you draw. Edit any box's depth in the "
            "table. Raise past the trace depth to be sure stubborn copper cuts "
            "through.")
        self.rework_level_chk = QCheckBox("Follow height map")
        self.rework_level_chk.setChecked(True)
        self.rework_level_chk.setToolTip(
            "Default for new boxes: warp the box to the probed surface so its depth "
            "stays uniform over the board's warp. Toggle per box in the table. "
            "Needs a probed/loaded height map (>=3 points).")
        self.rework_table = QTableWidget(0, 5)
        self.rework_table.setHorizontalHeaderLabels(
            ["#", "size (mm)", "depth", "lvl", ""])
        self.rework_table.horizontalHeader().setStretchLastSection(True)
        self.rework_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.export_sel_btn = QPushButton("Export rework NC...")
        self.export_sel_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.export_sel_btn.clicked.connect(self._on_export_selected)
        self.export_sel_btn.setEnabled(False)
```

Update the Rework panel layout (around 757-763) to include the table:

```python
        _rl.addWidget(_row(self.select_chk, self.clear_sel_btn, stretch_first=True))
        _rl.addWidget(_row(QLabel("New-box depth"), self.rework_depth_spin,
                           stretch_first=True))
        _rl.addWidget(self.rework_level_chk)
        _rl.addWidget(self.rework_table)
        _rl.addWidget(self.export_sel_btn)
```

Wire the canvas callback (where `self.preview.on_selection_changed = ...` was set,
around line 776):

```python
        self.preview.on_region_added = self._on_region_added
```

Add the handlers (place them next to the other rework methods, e.g. just before
`_rework_clip`):

```python
    def _on_region_added(self, bbox):
        """A drag committed a box -> add a region at the current defaults."""
        color = self._REWORK_COLORS[len(self._rework_regions) % len(self._REWORK_COLORS)]
        self._rework_regions.append({
            "bbox": bbox, "depth": self.rework_depth_spin.value(),
            "follow": self.rework_level_chk.isChecked(), "color": color})
        self._refresh_rework()

    def _clear_rework(self):
        self._rework_regions = []
        self._refresh_rework()

    def _delete_rework_region(self, i):
        if 0 <= i < len(self._rework_regions):
            del self._rework_regions[i]
            self._refresh_rework()

    def _rework_draw_list(self):
        return [(r["bbox"], r["color"], f'{r["depth"]:.3f} mm')
                for r in self._rework_regions]

    def _refresh_rework(self):
        """Rebuild the region table and push the draw list to the canvas."""
        from PySide6.QtWidgets import QDoubleSpinBox, QCheckBox, QPushButton
        t = self.rework_table
        t.setRowCount(len(self._rework_regions))
        for i, r in enumerate(self._rework_regions):
            x0, y0, x1, y1 = r["bbox"]
            sw = QTableWidgetItem("●"); sw.setForeground(QColor(r["color"]))
            t.setItem(i, 0, sw)
            t.setItem(i, 1, QTableWidgetItem(f"{abs(x1 - x0):.1f}x{abs(y1 - y0):.1f}"))
            ds = QDoubleSpinBox(); ds.setRange(0.0, 5.0); ds.setSingleStep(0.01)
            ds.setDecimals(3); ds.setValue(r["depth"]); ds.setSuffix(" mm")
            ds.valueChanged.connect(lambda v, i=i: self._set_region_depth(i, v))
            t.setCellWidget(i, 2, ds)
            cb = QCheckBox(); cb.setChecked(r["follow"])
            cb.toggled.connect(lambda on, i=i: self._set_region_follow(i, on))
            t.setCellWidget(i, 3, cb)
            dl = QPushButton("X")
            dl.clicked.connect(lambda _=False, i=i: self._delete_rework_region(i))
            t.setCellWidget(i, 4, dl)
        self.preview.set_rework_regions(self._rework_draw_list())
        self.export_sel_btn.setEnabled(self._rework_export_ok())

    def _set_region_depth(self, i, v):
        if 0 <= i < len(self._rework_regions):
            self._rework_regions[i]["depth"] = v
            self.preview.set_rework_regions(self._rework_draw_list())  # relabel box

    def _set_region_follow(self, i, on):
        if 0 <= i < len(self._rework_regions):
            self._rework_regions[i]["follow"] = bool(on)

    def _rework_export_ok(self):
        """True when there is at least one region and the current op/side is
        reworkable (traces/cutout, single side for double-sided)."""
        if not self._rework_regions:
            return False
        op = _OPS[self.tabs.currentIndex()]
        if op == "drill":
            return False
        if self.double_sided_chk.isChecked() and self._ds_side() is None:
            return False
        return True
```

- [ ] **Step 4: Run the new tests + the window suite**

Run: `python -m pytest tests/test_window.py -k "rework_add or rework_clear" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/gui/app.py tests/test_window.py
git commit -m "feat(rework): region list + editable table, add/delete/clear"
```

---

### Task 4: App — export, run-progress and simulation over all regions

**Files:**
- Modify: `gerber2rml/gui/app.py`
- Test: `tests/test_window.py` (append)

**Interfaces:**
- Consumes: Task 1 `clip_toolpaths_to_regions`, Task 3 `self._rework_regions` /
  `_rework_export_ok`; existing `_ds_side`, `_ds_side_toolpaths`,
  `state.toolpaths(op)`, `_level_heightmap_preview`, `BACKENDS`.
- Produces: `_rework_clip_regions(toolpaths) -> (paths, n_leveled)`; replaces the
  single-box `_rework_clip` and the `selection_bbox()` reads in the run-progress
  (around 1477-1484) and the simulation (around 2210-2213) and the old
  `_on_selection_changed` (around 2346) and `_on_export_selected` (around 2382).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_window.py
def test_rework_export_two_regions_one_file(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()      # traces tab, single-sided
    b = w.state.board.outline.bounds
    cx = (b[0] + b[2]) / 2; cy = (b[1] + b[3]) / 2
    w.rework_depth_spin.setValue(0.20)
    w._on_region_added((b[0], b[1], cx, cy))            # lower-left quadrant
    w.rework_depth_spin.setValue(0.40)
    w._on_region_added((cx, cy, b[2], b[3]))            # upper-right quadrant
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(tmp_path)))
    w._on_export_selected()
    files = list(tmp_path.glob("*_rework.nc"))
    assert len(files) == 1                               # ONE file for all regions


def test_rework_export_refused_with_no_regions(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.setdefault("w", a)))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(tmp_path)))
    w = MainWindow()
    w.load_folder(str(FIXT)); w.generate_preview()
    w._on_export_selected()                              # no regions
    assert list(tmp_path.glob("*_rework.nc")) == []     # nothing written
    assert "w" in warned
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_window.py -k "rework_export" -q`
Expected: FAIL (export still single-box; writes 0 or wrong file / AttributeError).

- [ ] **Step 3: Implement the multi-region clip + rewire consumers**

Replace `_rework_clip` (around 2360) with the region version:

```python
    def _rework_clip_regions(self, toolpaths):
        """Clip ``toolpaths`` to every rework region at its own depth, applying
        each region's height-map follow if set. Returns ``(paths, n_leveled)``."""
        from gerber2rml.engine.select import clip_toolpaths_to_regions
        hmap = self._level_heightmap_preview()
        paths, n_leveled = [], 0
        for r in self._rework_regions:
            clip = clip_toolpaths_to_regions(toolpaths, [(r["bbox"], -r["depth"])])
            if clip and r["follow"] and hmap is not None:
                from gerber2rml.engine.leveling import apply_leveling
                clip = apply_leveling(clip, hmap)
                n_leveled += 1
            paths.extend(clip)
        return paths, n_leveled
```

Replace the old `_on_selection_changed` (around 2346) with a refresh shim (the
preview no longer reports selection; the table drives button state). Also remove
the call `self._on_selection_changed(self.preview.selection_bbox())` in
`generate_preview` (around 1050) and replace it with:

```python
        self.export_sel_btn.setEnabled(self._rework_export_ok())
```

Replace `_on_export_selected` (around 2382) with:

```python
    def _on_export_selected(self):
        from pathlib import Path
        if self.state.board is None:
            QMessageBox.warning(self, "Nothing to export", "Load a Gerber folder first.")
            return
        if not self._rework_regions:
            QMessageBox.warning(self, "No regions",
                                "Enable 'Add areas' and drag one or more boxes first.")
            return
        op = _OPS[self.tabs.currentIndex()]
        ds = self.double_sided_chk.isChecked()
        side = self._ds_side()
        if op == "drill":
            QMessageBox.warning(self, "Not available",
                                "Rework works on the traces or cutout preview, not drilling.")
            return
        if ds and side is None:
            QMessageBox.warning(self, "Pick a side",
                                "Double-sided board: set View to Bottom or Top to rework that side.")
            return
        self._sync_state()
        toolpaths = self._ds_side_toolpaths(op, side) if ds else self.state.toolpaths(op)
        clipped, n_leveled = self._rework_clip_regions(toolpaths)
        if not clipped:
            QMessageBox.information(self, "Empty selection",
                                    "No toolpaths fall inside the boxes.")
            return
        out = QFileDialog.getExistingDirectory(self, "Select output folder")
        if not out:
            return
        backend = BACKENDS[self.state.machine]
        job = self.state.trace if op == "traces" else self.state.cutout
        try:
            text = backend.render(clipped, xy_feed=job.xy_feed, plunge_feed=job.plunge_feed)
            side_tag = f"{side.lower()}_" if side else ""
            path = Path(out) / f"{self.state.name}_{side_tag}{op}_rework{backend.ext}"
            path.write_text(text)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self.statusBar().showMessage(
            f"Wrote {path.name}: {len(self._rework_regions)} region(s), "
            f"{len(clipped)} path(s)"
            f"{f', {n_leveled} height-map leveled' if n_leveled else ''}", 10000)
```

Rewire the **run-progress** rework branch (around 1477-1484). Replace the
`bbox = self.preview.selection_bbox()` ... `toolpaths, _lv = self._rework_clip(
toolpaths, bbox)` block with:

```python
            if not self._rework_regions:
                QMessageBox.warning(self, "No regions",
                                    "Tick off 'selection', or add rework boxes first.")
                self.run_track_btn.setChecked(False)
                return
            toolpaths, _lv = self._rework_clip_regions(toolpaths)
```

(Keep the surrounding logic — the message text near the old "drag a rework box"
warning should read "add rework boxes" too.)

Rewire the **simulation** rework branch (around 2210-2213). Replace
`bbox = self.preview.selection_bbox()` ... `clipped, _leveled = self._rework_clip(
toolpaths, bbox)` with:

```python
        if self._rework_regions:
            clipped, _leveled = self._rework_clip_regions(toolpaths)
```

(Adjust the `if bbox ...` guard that wrapped it to `if self._rework_regions:`.)

- [ ] **Step 4: Run the rework tests + full window suite**

Run: `python -m pytest tests/test_window.py -k rework -q`
Expected: PASS.
Then: `python -m pytest tests/test_window.py tests/test_canvas.py tests/test_select.py -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/gui/app.py tests/test_window.py
git commit -m "feat(rework): export/run-progress/simulate over all regions"
```

---

### Task 5: Docs — README + dev log

**Files:**
- Modify: `README.md` (Rework section, if present, else add a short note)
- Create: `docs/2026-06-26-multi-region-rework.md` (dev log, sibling style)

**Interfaces:** none.

- [ ] **Step 1: Write the dev log**

Document: the multi-region model, the table (per-region depth + follow + delete +
colour), that the depth-spin/follow-checkbox are now defaults for new boxes, the
single-file export, and that run-progress + simulation now cover the whole set.

- [ ] **Step 2: Update README**

Add/extend the Rework note: mark all spots as coloured boxes with per-box depth,
export as one file; point at the dev log.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/2026-06-26-multi-region-rework.md
git commit -m "docs: multi-region rework + dev log"
```

---

## Self-Review

**Spec coverage:**
- `clip_toolpaths_to_regions` engine primitive → Task 1. ✓
- Canvas multi-region draw + `on_region_added`, removal of single-box API → Task 2. ✓
- Region dicts + palette + table (size/editable depth/per-region follow/delete) +
  add/clear → Task 3. ✓
- One-file export, run-progress + simulation over all regions, zero-region
  refusals, button-enable by region count → Task 4. ✓
- Defaults from the depth spin + follow checkbox → Task 3 (`_on_region_added`). ✓
- Docs → Task 5. ✓

**Placeholder scan:** No TBD/"handle edge cases"; every code step is literal. The
"around line N" anchors point at real current line numbers (grepped on the clean
main tree); the implementer adjusts if the file drifts.

**Type consistency:** region dict keys `bbox/depth/follow/color` identical across
Tasks 3–4; `clip_toolpaths_to_regions(toolpaths, regions)` with `regions=
[(bbox,cut_z)]` identical in Tasks 1 & 4; `set_rework_regions(list[(bbox,color,
label)])` and `on_region_added(bbox)` identical in Tasks 2–3; `_rework_export_ok`
used in Tasks 3 & 4. ✓
