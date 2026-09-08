# gerber2rml Presets + Calibration Coupon Plan (Plan C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add (1) a self-generated calibration coupon (Gerber + Excellon, bundled) that exercises every milling operation, and (2) a preset system in the GUI so a bit set can be saved once and reused across operations.

**Architecture:** A pure generator emits the coupon's Gerber/Excellon text into `examples/calibration/` (committed, so it doubles as a known-good fixture). A GUI-free `presets` module merges built-in + repo + user presets and applies them to `ProjectState`. The GUI gains a preset row (dropdown + Apply + Save) and `DataclassForm` learns to refresh from a new instance.

**Tech Stack:** Python 3.10+, existing gerbonara/shapely loader for round-trip validation, PySide6 GUI, pytest.

**Bits in scope:** traces 0.4 mm (1/64"), drill 0.8 & 1.0 mm, cutout 0.8 mm (1/32"). Coupon board 40×30 mm.

---

## File Structure

| File | Responsibility |
|---|---|
| `gerber2rml/examples/__init__.py` (create) | package marker |
| `gerber2rml/examples/calibration.py` (create) | emit coupon Gerber+Excellon to a folder |
| `examples/calibration/` (generated, committed) | `calib-B_Cu.gbr`, `calib-Edge_Cuts.gbr`, `calib.drl` |
| `gerber2rml/app/presets.py` (create) | built-in presets + load/merge/save + apply to state |
| `gerber2rml/gui/form.py` (modify) | add `set_instance(instance)` to refresh editors |
| `gerber2rml/gui/app.py` (modify) | preset dropdown + Apply + Save row |
| `tests/test_*.py` | generator round-trip, presets, form refresh, GUI preset wiring |

---

## Task 1: Calibration coupon generator

**Files:**
- Create: `gerber2rml/examples/__init__.py`, `gerber2rml/examples/calibration.py`
- Test: `tests/test_calibration.py`

The generator writes three self-consistent files (same origin, mm units) describing a 40×30 mm coupon:
- **Edge.Cuts** — rectangle (0,0)–(40,30), emitted as 4 line draws.
- **B.Cu** — emitted as G36/G37 filled regions: (a) 3 isolation trace-pairs (rectangles 1.0 mm wide × 12 mm tall, the two members of each pair separated by a 0.8 mm gap) at x≈4/12/20; (b) round-ish pads (12-gon regions, ⌀1.6 mm) centred on every drill hole; (c) one roundness ring approximated as a ⌀6 mm filled 24-gon at (33,22).
- **Drill (Excellon)** — tool T1=0.8 mm, T2=1.0 mm. Hits: a drill-size row (0.8 mm at (10,6), 1.0 mm at (14,6)); a 10 mm registration grid of 0.8 mm holes at (10,10),(20,10),(30,10),(10,20),(20,20),(30,20).

Validation is by round-tripping through our own loader, which is the real acceptance bar.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calibration.py
from gerber2rml.examples.calibration import write_coupon
from gerber2rml.loader import load_board

def test_coupon_round_trips_through_loader(tmp_path):
    folder = write_coupon(tmp_path)
    board = load_board(folder, mirror=False)
    # outline is a ~40x30 rectangle
    minx, miny, maxx, maxy = board.outline.bounds
    assert abs((maxx - minx) - 40.0) < 0.5
    assert abs((maxy - miny) - 30.0) < 0.5
    # copper present (isolation pairs + pads + ring)
    assert not board.copper.is_empty
    # 8 holes: 2 in the size-row + 6 in the grid
    assert len(board.holes) == 8
    dias = sorted({round(d, 1) for (_x, _y, d) in board.holes})
    assert dias == [0.8, 1.0]

def test_write_coupon_creates_three_files(tmp_path):
    folder = write_coupon(tmp_path)
    names = sorted(p.name for p in folder.iterdir())
    assert any(n.endswith("B_Cu.gbr") for n in names)
    assert any("Edge_Cuts" in n for n in names)
    assert any(n.endswith(".drl") for n in names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_calibration.py -v`
Expected: FAIL with `ModuleNotFoundError: gerber2rml.examples.calibration`.

- [ ] **Step 3: Implement the generator**

Create `gerber2rml/examples/__init__.py` with a one-line docstring. Then implement `write_coupon(out_dir) -> Path` in `gerber2rml/examples/calibration.py`. It must emit **RS-274X** Gerber (format `%FSLAX46Y46*%`, `%MOMM*%`, coordinates = round(mm*1e6)) and **Excellon** (metric, absolute). Copper shapes as `G36`/`G37` regions (after selecting any aperture, e.g. `%ADD10C,0.10*%` + `D10*`). Build the hole list once and reuse it for both the drill file and the pad regions so they always coincide. Helper to emit a polygon region from a list of (x,y) points: move to first with `D02`, draw the rest with `D01`, close, wrapped in `G36*`/`G37*`. Approximate circles with `_circle_pts(cx, cy, r, n)`. Edge.Cuts emitted as 4 `D01` line draws with a thin circle aperture. Excellon header: `M48`, `METRIC`, `T1C0.800`, `T2C1.000`, `%`, then `T1` + hits, `T2` + hits, `M30`. Return the output folder `Path`.

> **Execution note:** the acceptance test loads the output with our own loader, so iterate on the emitted text until `load_board` reports the rectangle outline, non-empty copper, and exactly 8 holes (2×0.8/1.0 in the row + 6×0.8 grid — wait: the row has one 0.8 and one 1.0; the grid is six 0.8; total holes = 8, diameters {0.8, 1.0}). Keep the hole set exactly as specified so the test's counts hold.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_calibration.py -v`
Expected: PASS (2). Full suite green.

- [ ] **Step 5: Generate the committed example files**

Run: `.venv\Scripts\python.exe -c "from pathlib import Path; from gerber2rml.examples.calibration import write_coupon; write_coupon(Path('examples/calibration'))"`
Confirm `examples/calibration/` now has the three files. Ensure `.gitignore` does not exclude them (the `*.rml` ignore won't; gerbers are fine).

- [ ] **Step 6: Commit**

```bash
git add gerber2rml/examples tests/test_calibration.py examples/calibration
git commit -m "Add calibration coupon generator and bundled example gerbers"
```

---

## Task 2: Presets module (built-in + repo + user, GUI-free)

**Files:**
- Create: `gerber2rml/app/presets.py`, `examples/presets.json` (repo defaults)
- Test: `tests/test_presets.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_presets.py
from gerber2rml.app.presets import load_presets, apply_preset, save_user_preset, BUILTIN_PRESETS
from gerber2rml.app.state import ProjectState

def test_builtin_present():
    presets = load_presets()
    assert any("1/64" in name for name in presets)

def test_apply_preset_sets_jobs():
    st = ProjectState()
    name = next(iter(BUILTIN_PRESETS))
    apply_preset(st, BUILTIN_PRESETS[name])
    assert st.trace.bit_diameter == 0.4
    assert st.cutout.tabs == 4

def test_save_and_load_user_preset(tmp_path, monkeypatch):
    monkeypatch.setattr("gerber2rml.app.presets._user_path",
                        lambda: tmp_path / "presets.json")
    st = ProjectState()
    st.trace.bit_diameter = 0.6
    save_user_preset("mine", st)
    presets = load_presets()
    assert "mine" in presets
    assert presets["mine"]["trace"]["bit_diameter"] == 0.6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_presets.py -v`
Expected: FAIL with `ModuleNotFoundError: gerber2rml.app.presets`.

- [ ] **Step 3: Implement**

`gerber2rml/app/presets.py`:
```python
"""Preset load/merge/apply: built-in + repo examples/presets.json + user JSON."""
import json
from dataclasses import asdict, replace
from pathlib import Path

BUILTIN_PRESETS = {
    "FR-1: 1/64 traces + 0.8/1.0 drill + 1/32 cutout": {
        "trace": {"bit_diameter": 0.4, "cut_depth": 0.10, "offsets": 2,
                  "stepover": 0.5, "xy_feed": 4.0, "plunge_feed": 1.0, "travel_z": 2.0},
        "drill": {"cut_depth": 0.6, "total_depth": 1.8, "xy_feed": 4.0,
                  "plunge_feed": 1.0, "travel_z": 2.0},
        "cutout": {"bit_diameter": 0.8, "cut_depth": 0.6, "total_depth": 1.8,
                   "tabs": 4, "tab_width": 1.5, "xy_feed": 4.0,
                   "plunge_feed": 1.0, "travel_z": 2.0},
    },
}

def _user_path():
    return Path.home() / ".gerber2rml" / "presets.json"

def _repo_path():
    return Path(__file__).resolve().parents[2] / "examples" / "presets.json"

def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError):
        return {}

def load_presets():
    merged = dict(BUILTIN_PRESETS)
    merged.update(_read_json(_repo_path()))
    merged.update(_read_json(_user_path()))   # user overrides by name
    return merged

def apply_preset(state, preset):
    state.trace = replace(state.trace, **preset.get("trace", {}))
    state.drill = replace(state.drill, **preset.get("drill", {}))
    state.cutout = replace(state.cutout, **preset.get("cutout", {}))

def save_user_preset(name, state):
    path = _user_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_json(path)
    data[name] = {"trace": asdict(state.trace), "drill": asdict(state.drill),
                  "cutout": asdict(state.cutout)}
    path.write_text(json.dumps(data, indent=2))
```

Also create `examples/presets.json` with `{}` (placeholder for team-shared presets).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_presets.py -v`
Expected: PASS (3). Full suite green.

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/app/presets.py examples/presets.json tests/test_presets.py
git commit -m "Add presets module (built-in + repo + user, apply/save)"
```

---

## Task 3: DataclassForm.set_instance (refresh editors)

**Files:**
- Modify: `gerber2rml/gui/form.py`
- Test: `tests/test_form.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_form.py`)

```python
def test_form_set_instance_refreshes_editors():
    from gerber2rml.config import TraceJob
    form = DataclassForm(TraceJob())
    form.set_instance(TraceJob(bit_diameter=0.8, offsets=4))
    assert form.value().bit_diameter == 0.8
    assert form.value().offsets == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_form.py::test_form_set_instance_refreshes_editors -v`
Expected: FAIL with `AttributeError: 'DataclassForm' object has no attribute 'set_instance'`.

- [ ] **Step 3: Implement** — add to `DataclassForm`:

```python
    def set_instance(self, instance):
        """Replace the backing instance and push its values into the editors."""
        self._instance = instance
        for name in self._editors:
            self.set_field(name, getattr(instance, name))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_form.py -v`
Expected: PASS. Full suite green.

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/gui/form.py tests/test_form.py
git commit -m "Add DataclassForm.set_instance to refresh from a new instance"
```

---

## Task 4: GUI preset row (dropdown + Apply + Save)

**Files:**
- Modify: `gerber2rml/gui/app.py`
- Test: `tests/test_window.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_window.py`)

```python
def test_apply_preset_updates_forms():
    from gerber2rml.app.presets import BUILTIN_PRESETS
    w = MainWindow()
    name = next(iter(BUILTIN_PRESETS))
    w.preset_combo.setCurrentText(name)
    w.apply_selected_preset()
    assert w.forms["traces"].value().bit_diameter == 0.4
    assert w.forms["cutout"].value().tabs == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_window.py::test_apply_preset_updates_forms -v`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute 'preset_combo'`.

- [ ] **Step 3: Implement** — in `MainWindow.__init__`, after building the machine row, add a preset row; add the methods. Concretely:

In `__init__` (after `self.mirror_chk` is added to `top`), insert before `top.addStretch(1)`:
```python
        from gerber2rml.app.presets import load_presets
        self._presets = load_presets()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(self._presets.keys()))
        self.apply_preset_btn = QPushButton("Apply preset")
        self.apply_preset_btn.clicked.connect(self.apply_selected_preset)
        self.save_preset_btn = QPushButton("Save preset…")
        self.save_preset_btn.clicked.connect(self._on_save_preset)
        for w in (QLabel("Preset:"), self.preset_combo,
                  self.apply_preset_btn, self.save_preset_btn):
            top.addWidget(w)
```

Add methods (near `generate_preview`):
```python
    def apply_selected_preset(self):
        from gerber2rml.app.presets import apply_preset
        name = self.preset_combo.currentText()
        if name not in self._presets:
            return
        apply_preset(self.state, self._presets[name])
        self.forms["traces"].set_instance(self.state.trace)
        self.forms["drill"].set_instance(self.state.drill)
        self.forms["cutout"].set_instance(self.state.cutout)
        if self.state.board is not None:
            self.generate_preview()

    def _on_save_preset(self):
        from PySide6.QtWidgets import QInputDialog
        from gerber2rml.app.presets import save_user_preset, load_presets
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if ok and name:
            self._sync_state()
            save_user_preset(name, self.state)
            self._presets = load_presets()
            self.preset_combo.clear()
            self.preset_combo.addItems(list(self._presets.keys()))
            self.preset_combo.setCurrentText(name)
```

Ensure `QComboBox`, `QLabel`, `QPushButton` are already imported in app.py (they are).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_window.py -v`
Expected: PASS. Full suite green.

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/gui/app.py tests/test_window.py
git commit -m "Add preset row (apply/save) to the GUI"
```

---

## Task 5: Docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document presets + the calibration coupon**

Add a short "Calibration & presets" section to `README.md`: how to load `examples/calibration/` (no KiCad needed), what each coupon feature tests (isolation at 0.8 mm clearance, 0.8/1.0 mm drill row, 10 mm registration grid, roundness ring, cutout+tabs), and how presets work (built-in + `~/.gerber2rml/presets.json` + repo `examples/presets.json`).

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Document calibration coupon and presets"
```

---

## Self-Review

- **Spec coverage:** calibration coupon with isolation/drill-row/registration-grid/roundness/cutout (Task 1 ✓), bits 0.4/0.8/1.0 (coupon + preset ✓), presets built-in+repo+user with apply/save (Task 2 ✓), GUI preset row (Task 4 ✓), form refresh so applying a preset updates the UI (Task 3 ✓), docs (Task 5 ✓).
- **Type consistency:** `write_coupon(out_dir) -> Path` (Task 1) consumed in Task 2/loader tests; `load_presets()/apply_preset(state,preset)/save_user_preset(name,state)/BUILTIN_PRESETS` (Task 2) used in Task 4; `DataclassForm.set_instance(instance)` (Task 3) used in Task 4; `ProjectState.trace/drill/cutout` reused throughout.
- **Placeholder scan:** none — concrete code in every step; Task 1 leaves the exact Gerber/Excellon byte emission to the implementer but pins acceptance via a loader round-trip with exact hole counts/diameters.

## Deferred
- Loader hardening against redundant/mixed-origin drill files (the boost_v2 stale-`.drl` issue) — separate fix; the coupon avoids it. Note it as a known limitation: keep one consistent drill set per folder.
