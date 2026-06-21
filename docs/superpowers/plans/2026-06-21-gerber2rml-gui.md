# gerber2rml GUI Implementation Plan (Plan B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A PySide6 desktop app on top of the finished headless core: load a Gerber folder, pick the SRM-20, edit milling variables, preview the toolpaths, and export the three `.rml` jobs.

**Architecture:** A GUI-free controller (`app/state.py`) owns all state and reuses the existing loader/engines/backend; a GUI-free preview helper (`app/preview.py`) turns toolpaths into plottable polylines; the PySide6 layer (`gui/`) is thin glue — a form auto-built from the job dataclasses, a matplotlib canvas, and Generate/Export buttons. The controller and preview are fully unit-tested; the widget layer gets one offscreen smoke test, with final visual checks done by a human.

**Tech Stack:** Python 3.10+, PySide6 (Qt widgets), matplotlib (FigureCanvasQTAgg preview), existing gerbonara/shapely core, pytest. GUI deps live in the `gui` extra.

---

## Preconditions

Plan A is merged; the package has `loader`, `engine/{traces,drill,cutout}`, `backends/srm20`, `config`, `cli`. Install GUI deps once: `.venv\Scripts\python.exe -m pip install -e ".[dev,gui]" -q`. Run all tests with `.venv\Scripts\python.exe -m pytest -q`. Commit each task; do NOT push.

## File Structure

| File | Responsibility |
|---|---|
| `gerber2rml/loader.py` (modify) | add `place_in_positive_quadrant(board, margin)` |
| `gerber2rml/cli.py` (modify) | `build_jobs` places board into positive quadrant before generating |
| `gerber2rml/backends/base.py` (modify) | replace the `self`-Protocol with a `RenderFn` callable type |
| `gerber2rml/backends/__init__.py` (modify) | `BACKENDS` registry: machine name → render fn |
| `gerber2rml/app/__init__.py` (create) | package marker |
| `gerber2rml/app/state.py` (create) | `ProjectState` controller (GUI-free) |
| `gerber2rml/app/preview.py` (create) | toolpaths → cut/rapid polylines (GUI-free) |
| `gerber2rml/gui/form.py` (create) | build a Qt form from a dataclass instance |
| `gerber2rml/gui/app.py` (modify) | `MainWindow` + `main()` |
| `gerber2rml/__main__.py` (create) | `python -m gerber2rml` → GUI |
| `pyproject.toml` / `README.md` (modify) | GUI entry point + run docs |
| `tests/test_*.py` | controller, preview, placement, form, window-smoke |

---

## Task 1: Place board in the positive quadrant (correctness fix)

**Files:**
- Modify: `gerber2rml/loader.py`
- Modify: `gerber2rml/cli.py`
- Test: `tests/test_placement.py`

The mirror (about x=0) leaves geometry in negative X, so RML coordinates are negative — wrong for the machine (operator zeroes at the board's lower-left). Translate the whole board so its lower-left sits at `(margin, margin)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_placement.py
from pathlib import Path
from gerber2rml.loader import load_board, place_in_positive_quadrant

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"

def test_places_board_lower_left_at_margin():
    board = place_in_positive_quadrant(load_board(FIXT, mirror=True), margin=2.0)
    minx, miny, _, _ = board.copper.bounds
    assert abs(minx - 2.0) < 1e-6
    assert abs(miny - 2.0) < 1e-6

def test_places_holes_too():
    raw = load_board(FIXT, mirror=True)
    placed = place_in_positive_quadrant(raw, margin=2.0)
    assert len(placed.holes) == len(raw.holes)
    assert all(x > 0 and y > 0 for (x, y, _d) in placed.holes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_placement.py -v`
Expected: FAIL with `ImportError: cannot import name 'place_in_positive_quadrant'`.

- [ ] **Step 3: Implement in loader.py** (add near the bottom; `Board`, `translate` from shapely.affinity)

```python
from shapely.affinity import translate as _translate  # add to imports if absent

def place_in_positive_quadrant(board, margin: float = 2.0):
    """Translate copper, outline and holes so the board's lower-left corner
    sits at (margin, margin) — machine coordinates the operator zeroes at the
    board corner expect positive X/Y."""
    geoms = [g for g in (board.copper, board.outline) if not g.is_empty]
    minx = min(g.bounds[0] for g in geoms)
    miny = min(g.bounds[1] for g in geoms)
    dx, dy = margin - minx, margin - miny
    return Board(
        copper=_translate(board.copper, xoff=dx, yoff=dy),
        outline=_translate(board.outline, xoff=dx, yoff=dy),
        holes=[(x + dx, y + dy, d) for (x, y, d) in board.holes],
    )
```

- [ ] **Step 4: Wire into cli.build_jobs** — after `board = load_board(...)`, place it:

In `gerber2rml/cli.py`, change the load line in `build_jobs` from
`board = load_board(gerber_dir, mirror=mirror)` to:
```python
    board = place_in_positive_quadrant(load_board(gerber_dir, mirror=mirror))
```
and add `place_in_positive_quadrant` to the `from gerber2rml.loader import ...` line.

- [ ] **Step 5: Run tests to verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_placement.py tests/test_cli.py -v`
Expected: PASS (placement 2 + cli 2). Then full suite green.

- [ ] **Step 6: Commit**

```bash
git add gerber2rml/loader.py gerber2rml/cli.py tests/test_placement.py
git commit -m "Place board in positive quadrant so machine coords are non-negative"
```

---

## Task 2: Backend registry + callable seam

**Files:**
- Modify: `gerber2rml/backends/base.py`
- Modify: `gerber2rml/backends/__init__.py`
- Test: `tests/test_backends_registry.py`

Replace the mismatched `self`-Protocol with a callable type, and add a name→render registry the GUI's machine dropdown uses.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backends_registry.py
from gerber2rml.backends import BACKENDS
from gerber2rml.toolpath import Move

def test_srm20_registered():
    assert "Roland SRM-20" in BACKENDS

def test_registry_value_renders():
    render = BACKENDS["Roland SRM-20"]
    rml = render([[Move(0, 0, 2.0, rapid=True)]], 4.0, 1.0)
    assert rml.startswith("^IN;!MC1;")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backends_registry.py -v`
Expected: FAIL with `ImportError: cannot import name 'BACKENDS'`.

- [ ] **Step 3: Implement**

`gerber2rml/backends/base.py` (replace contents):
```python
"""Machine-backend seam: a render function maps toolpaths -> machine program text."""
from typing import Callable
from gerber2rml.toolpath import Move

# (toolpaths, xy_feed, plunge_feed[, rapid_feed]) -> program text
RenderFn = Callable[..., str]
```

`gerber2rml/backends/__init__.py` (replace contents):
```python
"""Machine backends: name -> render function (the pluggable seam)."""
from gerber2rml.backends import srm20

BACKENDS = {"Roland SRM-20": srm20.render}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backends_registry.py -v`
Expected: PASS (2). Full suite green (the cli imports `srm20` directly, unaffected).

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/backends/base.py gerber2rml/backends/__init__.py tests/test_backends_registry.py
git commit -m "Add backend registry and callable RenderFn seam"
```

---

## Task 3: ProjectState controller (GUI-free)

**Files:**
- Create: `gerber2rml/app/__init__.py`, `gerber2rml/app/state.py`
- Test: `tests/test_state.py`

Holds the loaded board + job configs + machine choice; computes per-operation toolpaths for preview and delegates export to `build_jobs`. No Qt.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state.py
from pathlib import Path
from gerber2rml.app.state import ProjectState

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"

def test_load_then_toolpaths_per_op():
    st = ProjectState()
    st.load(FIXT)
    assert st.board is not None
    assert len(st.toolpaths("traces")) > 0
    assert len(st.toolpaths("drill")) > 0
    assert len(st.toolpaths("cutout")) > 0

def test_toolpaths_requires_load():
    import pytest
    st = ProjectState()
    with pytest.raises(RuntimeError):
        st.toolpaths("traces")

def test_export_writes_files(tmp_path):
    st = ProjectState(name="demo")
    st.load(FIXT)
    written = st.export(tmp_path)
    assert any(p.name == "demo_traces.rml" for p in written)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: gerber2rml.app`.

- [ ] **Step 3: Implement**

`gerber2rml/app/__init__.py`:
```python
"""GUI-free application layer: controller + preview helpers."""
```

`gerber2rml/app/state.py`:
```python
"""ProjectState: GUI-free controller holding board + jobs, producing toolpaths/exports."""
from dataclasses import dataclass, field
from pathlib import Path
from gerber2rml.config import TraceJob, DrillJob, CutoutJob
from gerber2rml.loader import load_board, place_in_positive_quadrant
from gerber2rml.engine.traces import isolate
from gerber2rml.engine.drill import drill_holes
from gerber2rml.engine.cutout import cut_outline
from gerber2rml.cli import build_jobs

@dataclass
class ProjectState:
    trace: TraceJob = field(default_factory=TraceJob)
    drill: DrillJob = field(default_factory=DrillJob)
    cutout: CutoutJob = field(default_factory=CutoutJob)
    mirror: bool = True
    machine: str = "Roland SRM-20"
    name: str = "board"
    gerber_dir: Path = None
    board: object = None

    def load(self, folder):
        self.gerber_dir = Path(folder)
        self.board = place_in_positive_quadrant(
            load_board(self.gerber_dir, mirror=self.mirror))
        return self.board

    def toolpaths(self, op):
        if self.board is None:
            raise RuntimeError("load a Gerber folder first")
        if op == "traces":
            return isolate(self.board.copper, self.trace)
        if op == "drill":
            return drill_holes(self.board.holes, self.drill)
        if op == "cutout":
            return cut_outline(self.board.outline, self.cutout)
        raise ValueError(f"unknown operation: {op}")

    def export(self, out_dir):
        if self.gerber_dir is None:
            raise RuntimeError("load a Gerber folder first")
        return build_jobs(self.gerber_dir, out_dir, self.name,
                          trace=self.trace, drill=self.drill, cutout=self.cutout,
                          mirror=self.mirror)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_state.py -v`
Expected: PASS (3). Full suite green.

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/app/__init__.py gerber2rml/app/state.py tests/test_state.py
git commit -m "Add GUI-free ProjectState controller"
```

---

## Task 4: Preview polyline helper (GUI-free)

**Files:**
- Create: `gerber2rml/app/preview.py`
- Test: `tests/test_preview.py`

Split toolpaths into cut polylines and rapid polylines so the canvas can draw cuts solid and rapids dashed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_preview.py
from gerber2rml.toolpath import Move
from gerber2rml.app.preview import toolpath_segments

def test_splits_cut_and_rapid():
    # rapid approach, plunge+cut, rapid lift
    tp = [Move(0, 0, 2, rapid=True), Move(0, 0, -0.1), Move(1, 0, -0.1),
          Move(1, 0, 2, rapid=True)]
    cuts, rapids = toolpath_segments([tp])
    assert len(cuts) >= 1
    assert len(rapids) >= 1
    # the cut polyline contains the (0,0)->(1,0) move
    assert any((1.0, 0.0) in poly for poly in cuts)

def test_empty_input():
    assert toolpath_segments([]) == ([], [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_preview.py -v`
Expected: FAIL with `ModuleNotFoundError: gerber2rml.app.preview`.

- [ ] **Step 3: Implement**

```python
# gerber2rml/app/preview.py
"""Turn toolpaths into cut/rapid polylines (lists of (x,y)) for plotting."""

def toolpath_segments(toolpaths):
    """Return (cuts, rapids): each a list of polylines [[(x,y), ...], ...].
    Consecutive moves of the same kind (cut vs rapid) form one polyline; the
    boundary point is shared so the drawn path stays continuous."""
    cuts, rapids = [], []
    for tp in toolpaths:
        if not tp:
            continue
        cur = [(tp[0].x, tp[0].y)]
        cur_rapid = tp[0].rapid
        for m in tp[1:]:
            if m.rapid == cur_rapid:
                cur.append((m.x, m.y))
            else:
                (rapids if cur_rapid else cuts).append(cur)
                cur = [cur[-1], (m.x, m.y)]   # share boundary point
                cur_rapid = m.rapid
        (rapids if cur_rapid else cuts).append(cur)
    return cuts, rapids
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_preview.py -v`
Expected: PASS (2). Full suite green.

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/app/preview.py tests/test_preview.py
git commit -m "Add cut/rapid preview polyline helper"
```

---

## Task 5: Dataclass→Qt form builder

**Files:**
- Create: `gerber2rml/gui/form.py`
- Test: `tests/test_form.py`

Build a `QFormLayout` of editors (QDoubleSpinBox/QSpinBox/QCheckBox) from a dataclass instance, writing edits back into a copy. This keeps `MainWindow` thin and is testable offscreen.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_form.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from gerber2rml.config import TraceJob
from gerber2rml.gui.form import DataclassForm

_app = QApplication.instance() or QApplication([])

def test_form_reads_dataclass_values():
    form = DataclassForm(TraceJob())
    assert form.value().bit_diameter == 0.4
    assert form.value().offsets == 2

def test_form_edit_reflects_in_value():
    form = DataclassForm(TraceJob())
    form.set_field("bit_diameter", 0.8)
    assert form.value().bit_diameter == 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_form.py -v`
Expected: FAIL with `ModuleNotFoundError: gerber2rml.gui.form`.

- [ ] **Step 3: Implement**

```python
# gerber2rml/gui/form.py
"""Build a Qt form from a dataclass instance; read edits back as a new instance."""
from dataclasses import fields, replace
from PySide6.QtWidgets import QWidget, QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox

class DataclassForm(QWidget):
    def __init__(self, instance, parent=None):
        super().__init__(parent)
        self._instance = instance
        self._editors = {}
        layout = QFormLayout(self)
        for f in fields(instance):
            val = getattr(instance, f.name)
            if isinstance(val, bool):
                w = QCheckBox(); w.setChecked(val)
            elif isinstance(val, int):
                w = QSpinBox(); w.setRange(-1, 100000); w.setValue(val)
            else:  # float
                w = QDoubleSpinBox(); w.setDecimals(3); w.setRange(-1000.0, 100000.0)
                w.setSingleStep(0.1); w.setValue(float(val))
            self._editors[f.name] = w
            layout.addRow(f.name.replace("_", " "), w)

    def _read(self, name):
        w = self._editors[name]
        if isinstance(w, QCheckBox):
            return w.isChecked()
        return w.value()

    def set_field(self, name, value):
        w = self._editors[name]
        if isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        else:
            w.setValue(value)

    def value(self):
        return replace(self._instance, **{n: self._read(n) for n in self._editors})
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_form.py -v`
Expected: PASS (2). Full suite green.

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/gui/form.py tests/test_form.py
git commit -m "Add dataclass-to-Qt form builder"
```

---

## Task 6: Matplotlib preview canvas

**Files:**
- Create: `gerber2rml/gui/canvas.py`
- Test: `tests/test_canvas.py`

A `QWidget` wrapping a matplotlib `FigureCanvasQTAgg` that draws cut polylines (solid) and rapid polylines (thin, light) from `toolpath_segments`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_canvas.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import matplotlib
matplotlib.use("Agg")
from PySide6.QtWidgets import QApplication
from gerber2rml.gui.canvas import PreviewCanvas

_app = QApplication.instance() or QApplication([])

def test_canvas_draws_without_error():
    canvas = PreviewCanvas()
    cuts = [[(0, 0), (1, 0), (1, 1)]]
    rapids = [[(1, 1), (0, 0)]]
    canvas.show_segments(cuts, rapids)        # must not raise
    assert len(canvas.ax.collections) >= 1

def test_canvas_clear():
    canvas = PreviewCanvas()
    canvas.show_segments([[(0, 0), (1, 1)]], [])
    canvas.show_segments([], [])              # redraw empty must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_canvas.py -v`
Expected: FAIL with `ModuleNotFoundError: gerber2rml.gui.canvas`.

- [ ] **Step 3: Implement**

```python
# gerber2rml/gui/canvas.py
"""Matplotlib preview canvas: draws cut (solid) and rapid (light) polylines."""
from PySide6.QtWidgets import QWidget, QVBoxLayout
from matplotlib.figure import Figure
from matplotlib.collections import LineCollection
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

class PreviewCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure(figsize=(5, 5))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_aspect("equal")
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)

    def show_segments(self, cuts, rapids):
        self.ax.clear()
        self.ax.set_aspect("equal")
        if rapids:
            self.ax.add_collection(LineCollection(rapids, colors="0.8", linewidths=0.4))
        if cuts:
            self.ax.add_collection(LineCollection(cuts, colors="tab:blue", linewidths=0.8))
        self.ax.autoscale_view()
        self.ax.relim()
        self.ax.margins(0.05)
        self.canvas.draw_idle()
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_canvas.py -v`
Expected: PASS (2). Full suite green.

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/gui/canvas.py tests/test_canvas.py
git commit -m "Add matplotlib preview canvas"
```

---

## Task 7: MainWindow + entry points

**Files:**
- Modify: `gerber2rml/gui/app.py`
- Create: `gerber2rml/__main__.py`
- Modify: `pyproject.toml`, `README.md`
- Test: `tests/test_window.py`

Assemble the window: top row (Load folder button, board-name field, machine dropdown from `BACKENDS`), left parameter tabs (a `DataclassForm` per op + a mirror checkbox), centre `PreviewCanvas`, bottom buttons (Generate Preview for the selected op, Export all). Wire to `ProjectState`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_window.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import matplotlib
matplotlib.use("Agg")
from pathlib import Path
from PySide6.QtWidgets import QApplication
from gerber2rml.gui.app import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"
_app = QApplication.instance() or QApplication([])

def test_window_builds():
    w = MainWindow()
    assert w.machine_combo.count() >= 1          # SRM-20 present
    assert w.preview is not None

def test_load_and_preview_and_export(tmp_path):
    w = MainWindow()
    w.load_folder(str(FIXT))                      # programmatic load (no dialog)
    w.generate_preview()                          # default op (traces)
    assert len(w.preview.ax.collections) >= 1
    written = w.export_to(tmp_path)
    assert any(p.suffix == ".rml" for p in written)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_window.py -v`
Expected: FAIL with `ImportError: cannot import name 'MainWindow'`.

- [ ] **Step 3: Implement `gerber2rml/gui/app.py`** (replace the stub)

```python
"""gerber2rml desktop app: load Gerbers, edit variables, preview, export RML."""
import os
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLineEdit, QComboBox, QTabWidget, QCheckBox, QLabel, QFileDialog, QMessageBox,
)
from gerber2rml.app.state import ProjectState
from gerber2rml.app.preview import toolpath_segments
from gerber2rml.backends import BACKENDS
from gerber2rml.gui.form import DataclassForm
from gerber2rml.gui.canvas import PreviewCanvas

_OPS = ["traces", "drill", "cutout"]

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("gerber2rml — SRM-20 CAM")
        self.state = ProjectState()

        # top bar
        self.load_btn = QPushButton("Load Gerber folder…")
        self.load_btn.clicked.connect(self._on_load_clicked)
        self.name_edit = QLineEdit(self.state.name)
        self.machine_combo = QComboBox()
        self.machine_combo.addItems(list(BACKENDS.keys()))
        self.mirror_chk = QCheckBox("Mirror (bottom-up)"); self.mirror_chk.setChecked(True)
        top = QHBoxLayout()
        for w in (self.load_btn, QLabel("Name:"), self.name_edit,
                  QLabel("Machine:"), self.machine_combo, self.mirror_chk):
            top.addWidget(w)
        top.addStretch(1)

        # parameter tabs (one form per op)
        self.forms = {"traces": DataclassForm(self.state.trace),
                      "drill": DataclassForm(self.state.drill),
                      "cutout": DataclassForm(self.state.cutout)}
        self.tabs = QTabWidget()
        for op in _OPS:
            self.tabs.addTab(self.forms[op], op.capitalize())

        # preview + buttons
        self.preview = PreviewCanvas()
        self.gen_btn = QPushButton("Generate Preview")
        self.gen_btn.clicked.connect(self.generate_preview)
        self.export_btn = QPushButton("Export .rml…")
        self.export_btn.clicked.connect(self._on_export_clicked)
        btns = QHBoxLayout(); btns.addWidget(self.gen_btn); btns.addWidget(self.export_btn)

        left = QVBoxLayout(); left.addWidget(self.tabs); left.addLayout(btns)
        left_w = QWidget(); left_w.setLayout(left)
        body = QHBoxLayout(); body.addWidget(left_w, 0); body.addWidget(self.preview, 1)

        root = QVBoxLayout(); root.addLayout(top); root.addLayout(body)
        central = QWidget(); central.setLayout(root); self.setCentralWidget(central)

    # --- programmatic API (also used by tests) ---
    def _sync_state(self):
        self.state.name = self.name_edit.text() or "board"
        self.state.machine = self.machine_combo.currentText()
        self.state.mirror = self.mirror_chk.isChecked()
        self.state.trace = self.forms["traces"].value()
        self.state.drill = self.forms["drill"].value()
        self.state.cutout = self.forms["cutout"].value()

    def load_folder(self, folder):
        self._sync_state()
        self.state.load(folder)

    def generate_preview(self):
        if self.state.board is None:
            return
        self._sync_state()
        op = _OPS[self.tabs.currentIndex()]
        cuts, rapids = toolpath_segments(self.state.toolpaths(op))
        self.preview.show_segments(cuts, rapids)

    def export_to(self, out_dir):
        self._sync_state()
        return self.state.export(out_dir)

    # --- dialog wrappers ---
    def _on_load_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Gerber folder")
        if folder:
            try:
                self.load_folder(folder)
                self.generate_preview()
            except Exception as e:  # surface loader errors to the user
                QMessageBox.critical(self, "Load failed", str(e))

    def _on_export_clicked(self):
        if self.state.gerber_dir is None:
            QMessageBox.warning(self, "Nothing to export", "Load a Gerber folder first.")
            return
        out = QFileDialog.getExistingDirectory(self, "Select output folder")
        if out:
            written = self.export_to(out)
            QMessageBox.information(self, "Exported",
                                    "Wrote:\n" + "\n".join(p.name for p in written))

def main():
    app = QApplication.instance() or QApplication([])
    win = MainWindow(); win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add `gerber2rml/__main__.py`**

```python
"""`python -m gerber2rml` launches the GUI."""
from gerber2rml.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Restore the GUI entry point in `pyproject.toml`**

Add below the existing `[project.scripts]` block:
```toml
[project.gui-scripts]
gerber2rml = "gerber2rml.gui.app:main"
```

- [ ] **Step 6: Update `README.md` Run section**

Replace the line `The GUI (\`python -m gerber2rml\`) is a separate later plan (Plan B) and is not implemented yet.` with:
```
GUI:

```bash
pip install -e ".[gui]"
python -m gerber2rml         # or the `gerber2rml` launcher after install
```
```

- [ ] **Step 7: Run tests to verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_window.py -v`
Expected: PASS (2). Then full suite green.

- [ ] **Step 8: Commit**

```bash
git add gerber2rml/gui/app.py gerber2rml/__main__.py pyproject.toml README.md tests/test_window.py
git commit -m "Add MainWindow, GUI entry points, and offscreen window tests"
```

---

## Task 8: Manual visual smoke (human-in-loop)

**Files:**
- Create: `docs/gui-manual-check.md`

Automated tests run offscreen; a human must confirm the window actually looks/behaves right once.

- [ ] **Step 1: Launch the GUI**

Run: `.venv\Scripts\python.exe -m gerber2rml`

- [ ] **Step 2: Exercise it** — Load `tests/fixtures/mosfet_test`, switch tabs, change a bit diameter, Generate Preview (confirm cuts redraw), Export to a temp folder (confirm 3 `.rml` + runplan written).

- [ ] **Step 3: Record the outcome** in `docs/gui-manual-check.md` (date, OS, what worked, any visual issues). Commit it.

```bash
git add docs/gui-manual-check.md
git commit -m "Record manual GUI smoke check"
```

---

## Self-Review

- **Spec coverage (design §5):** file loader + name + machine dropdown (Task 7 ✓), per-op parameter tabs (Tasks 5,7 ✓), matplotlib preview (Tasks 4,6 ✓), export button writing the 3 jobs (Tasks 3,7 ✓), regenerate via explicit button — documented deviation from "regenerate on change" to avoid lag on large boards. Pluggable machine via registry (Task 2 ✓). Error surfacing via QMessageBox (Task 7 ✓). Plus the positive-quadrant correctness fix the Plan-A review flagged (Task 1 ✓).
- **Placeholder scan:** none — every code step has full code.
- **Type consistency:** `ProjectState` fields/methods (`load`, `toolpaths(op)`, `export`, `board`, `trace/drill/cutout`, `name`, `gerber_dir`, `mirror`, `machine`) used identically in Tasks 3 and 7. `toolpath_segments(toolpaths) -> (cuts, rapids)` defined in Task 4, consumed in Tasks 6,7. `DataclassForm(instance)` with `.value()`/`.set_field()` defined in Task 5, used in Task 7. `PreviewCanvas.show_segments(cuts, rapids)` and `.ax` defined in Task 6, used in Task 7. `place_in_positive_quadrant(board, margin=2.0)` defined in Task 1, used in Task 3. `BACKENDS` dict defined in Task 2, used in Task 7.
- **Testability:** controller/preview/placement/form/canvas all unit-tested; window tested offscreen; only final visual polish is human (Task 8).

## Deferred / follow-ups
- Live coordinate readout / DRC overlay, multi-board panelization, saving/loading a project file — not in scope.
- If preview of full-clear (`offsets=-1`) or very large boards is slow, add downsampling later.
