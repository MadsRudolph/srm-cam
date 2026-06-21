# gerber2rml Core Pipeline Implementation Plan (Plan A — headless)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A command-line tool that converts a folder of KiCad Gerber/Excellon files into three correct Roland SRM-20 `.rml` jobs (trace isolation, drilling, board cutout) for single-sided boards.

**Architecture:** Pure-logic pipeline with no GUI dependency. `loader` parses Gerber/Excellon into `shapely` geometry; the `engine` modules turn geometry into 3D toolpaths (`Move` lists); the SRM-20 `backend` renders toolpaths to RML-1. A thin `cli` wires them together. Everything is unit-tested; a final parity test diffs our RML move-set against the mods website on a real board.

**Tech Stack:** Python 3.10+, gerbonara (Gerber/Excellon parsing), shapely 2.x (geometry/offsetting), pytest. No GUI in this plan.

---

## File Structure

| File | Responsibility |
|---|---|
| `gerber2rml/toolpath.py` | `Move` dataclass + `Toolpath` alias — the geometry↔machine contract |
| `gerber2rml/config.py` | `TraceJob`/`DrillJob`/`CutoutJob`/`BoardConfig` dataclasses with SRM-20 defaults |
| `gerber2rml/backends/base.py` | `MachineBackend` protocol |
| `gerber2rml/backends/srm20.py` | `Toolpath` list → RML-1 string (bug-fixed emitter) |
| `gerber2rml/loader.py` | Gerber/Excellon folder → `Board` (shapely copper, outline, holes) |
| `gerber2rml/engine/traces.py` | copper → isolation `Toolpath`s |
| `gerber2rml/engine/drill.py` | holes → peck-drill `Toolpath`s |
| `gerber2rml/engine/cutout.py` | outline → cutout `Toolpath`s with tabs |
| `gerber2rml/cli.py` | `python -m gerber2rml.cli <gerber-dir> -o <out>` driver |
| `tests/fixtures/mosfet_test/` | real Gerbers copied from the team repo |
| `tests/test_*.py` | one test module per unit |

Internal contract between engine and backend (defined in Task 1, used everywhere after):

```python
# gerber2rml/toolpath.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Move:
    x: float          # mm, absolute
    y: float          # mm, absolute
    z: float          # mm, absolute (negative = into the board)
    rapid: bool = False   # True = travel move (no cutting), False = feed move

Toolpath = list      # list[Move]
```

---

## Task 0: Dev environment + library API spike

**Files:**
- Create: `tests/fixtures/mosfet_test/` (copied Gerbers)
- Create: `scripts/spike_gerbonara.py` (throwaway, committed for reference)

- [ ] **Step 1: Create and activate a venv, install deps**

Run (Windows PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```
Expected: gerbonara, shapely, PySide6, matplotlib, pytest install without error.

- [ ] **Step 2: Confirm the existing smoke test passes**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS (1 passed).

- [ ] **Step 3: Copy a real board's Gerbers in as a fixture**

Run (PowerShell, from repo root):
```powershell
$src = "C:\Users\Mads2\DTU\4. Semester\Electrical Energy Systems\team\hardware\kicad\production\mosfet_test\gerbers"
New-Item -ItemType Directory -Force tests\fixtures\mosfet_test | Out-Null
Copy-Item "$src\*" tests\fixtures\mosfet_test\
```
Expected: `tests/fixtures/mosfet_test/` contains `*-B_Cu.gbl`, `*-Edge_Cuts.gm1`, `*.drl`, etc.

- [ ] **Step 4: Spike gerbonara's API to confirm attribute/method names**

Create `scripts/spike_gerbonara.py`:
```python
"""Throwaway: print what gerbonara gives us so the loader is written against
the real API of the installed version. Run once, read output, keep for reference."""
from pathlib import Path
from gerbonara import LayerStack

d = Path("tests/fixtures/mosfet_test")
stack = LayerStack.open_dir(str(d))
print("LAYERS:", list(stack.graphic_layers.keys()))
print("HAS DRILL:", stack.drill_pth is not None or stack.drill_npth is not None)

bottom = stack['bottom copper']        # adjust key from the LAYERS print
print("BOTTOM TYPE:", type(bottom))
obj_types = {}
for o in bottom.objects:
    obj_types[type(o).__name__] = obj_types.get(type(o).__name__, 0) + 1
print("OBJECT TYPES ON B.Cu:", obj_types)
print("FIRST OBJECT ATTRS:", vars(next(iter(bottom.objects))))
```

Run: `python scripts/spike_gerbonara.py`
Expected: prints the layer keys (note the exact key for bottom copper, drill access, outline), the graphic-object class names (e.g. `Line`, `Flash`, `Region`, `Arc`), and one object's attributes (so we know how to read width, endpoints, aperture).

- [ ] **Step 5: Record findings as a docstring at the top of the loader file**

Create `gerber2rml/loader.py` header comment capturing the confirmed keys/attrs from Step 4 (exact layer key for B.Cu, how to reach the drill file, object classes present). The loader implementation (Task 4) is written against these.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/mosfet_test scripts/spike_gerbonara.py gerber2rml/loader.py
git commit -m "Add gerbonara API spike, mosfet_test fixture, loader API notes"
```

---

## Task 1: Toolpath data model

**Files:**
- Create: `gerber2rml/toolpath.py`
- Test: `tests/test_toolpath.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_toolpath.py
from gerber2rml.toolpath import Move

def test_move_defaults_to_feed():
    m = Move(1.0, 2.0, -0.1)
    assert (m.x, m.y, m.z) == (1.0, 2.0, -0.1)
    assert m.rapid is False

def test_move_can_be_rapid():
    assert Move(0, 0, 2.0, rapid=True).rapid is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_toolpath.py -v`
Expected: FAIL with `ModuleNotFoundError: gerber2rml.toolpath`.

- [ ] **Step 3: Write minimal implementation**

```python
# gerber2rml/toolpath.py
"""Move dataclass + Toolpath alias: the engine↔backend contract."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Move:
    x: float
    y: float
    z: float
    rapid: bool = False

Toolpath = list  # list[Move]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_toolpath.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/toolpath.py tests/test_toolpath.py
git commit -m "Add Move toolpath data model"
```

---

## Task 2: Job config dataclasses

**Files:**
- Modify: `gerber2rml/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from gerber2rml.config import TraceJob, DrillJob, CutoutJob, BoardConfig

def test_trace_defaults_match_srm20():
    j = TraceJob()
    assert j.bit_diameter == 0.4
    assert j.cut_depth == 0.10
    assert j.offsets == 2
    assert j.xy_feed == 4.0
    assert j.plunge_feed == 1.0
    assert j.mirror is True

def test_cutout_has_tabs():
    c = CutoutJob()
    assert c.bit_diameter == 0.8
    assert c.tabs == 4
    assert c.tab_width == 1.5

def test_board_thickness_default():
    assert BoardConfig().thickness == 1.6

def test_drill_total_depth():
    assert DrillJob().total_depth == 1.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'TraceJob'`.

- [ ] **Step 3: Write minimal implementation** (replaces the stub docstring file)

```python
# gerber2rml/config.py
"""Job/Tool parameter dataclasses and SRM-20 defaults (see docs/design.md §4)."""
from dataclasses import dataclass

@dataclass
class TraceJob:
    bit_diameter: float = 0.4    # mm (1/64")
    cut_depth: float = 0.10      # mm, single pass
    offsets: int = 2             # isolation passes; -1 = clear all copper
    stepover: float = 0.5        # fraction of bit diameter
    xy_feed: float = 4.0         # mm/s
    plunge_feed: float = 1.0     # mm/s
    travel_z: float = 2.0        # mm
    mirror: bool = True

@dataclass
class DrillJob:
    cut_depth: float = 0.6       # mm per peck
    total_depth: float = 1.8     # mm (through 1.6 mm board)
    xy_feed: float = 4.0
    plunge_feed: float = 1.0
    travel_z: float = 2.0
    mirror: bool = True

@dataclass
class CutoutJob:
    bit_diameter: float = 0.8    # mm (1/32")
    cut_depth: float = 0.6       # mm per pass
    total_depth: float = 1.8
    tabs: int = 4
    tab_width: float = 1.5       # mm
    xy_feed: float = 4.0
    plunge_feed: float = 1.0
    travel_z: float = 2.0
    mirror: bool = True

@dataclass
class BoardConfig:
    thickness: float = 1.6       # mm
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/config.py tests/test_config.py
git commit -m "Add job config dataclasses with SRM-20 defaults"
```

---

## Task 3: SRM-20 RML backend (the bug-fixed emitter)

**Files:**
- Modify: `gerber2rml/backends/base.py`, `gerber2rml/backends/srm20.py`
- Test: `tests/test_srm20_backend.py`

This is the highest-value correctness task: it fixes the legacy bugs (spindle `!MC1`, real feeds via `VS`/`!VZ`, clean header, 40 units/mm). The backend is intentionally dumb — it only renders `Move`s; all pass/peck geometry is decided by the engine.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_srm20_backend.py
from gerber2rml.toolpath import Move
from gerber2rml.backends.srm20 import render

def test_scale_is_40_units_per_mm():
    rml = render([[Move(20.0, 0.0, -0.1)]], xy_feed=4.0, plunge_feed=1.0)
    assert "Z800,0,-4;" in rml          # 20 mm * 40 = 800 ; -0.1 mm * 40 = -4

def test_spindle_is_turned_on_then_off():
    rml = render([[Move(0, 0, 2.0, rapid=True)]], xy_feed=4.0, plunge_feed=1.0)
    lines = rml.splitlines()
    assert lines[0].startswith("^IN;!MC1;")     # header MUST enable spindle
    assert "!MC0" not in lines[0]               # the legacy header bug
    assert lines[-1] == "!MC0;^IN;"             # footer disables + resets

def test_feeds_emitted_for_cut_moves():
    rml = render([[Move(1, 1, -0.1)]], xy_feed=4.0, plunge_feed=1.0)
    assert "VS4.0;!VZ1.0;" in rml

def test_rapid_uses_rapid_feed():
    rml = render([[Move(0, 0, 2.0, rapid=True)]], xy_feed=4.0, plunge_feed=1.0,
                 rapid_feed=15.0)
    assert "VS15.0;" in rml
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_srm20_backend.py -v`
Expected: FAIL with `ImportError: cannot import name 'render'`.

- [ ] **Step 3: Write minimal implementation**

```python
# gerber2rml/backends/srm20.py
"""Roland SRM-20 backend (RML-1). Renders Move lists to RML.

Fixes the legacy bugs (docs/design.md §6): spindle ON via !MC1, XY feed via VS
and plunge via !VZ, clean Z-up header, 40 RML units/mm (SRM-20 = 0.025 mm/unit).
"""
from gerber2rml.toolpath import Toolpath

SCALE = 40            # RML-1 units per mm
DEFAULT_RAPID = 15.0  # mm/s travel

def _u(mm: float) -> int:
    return int(round(mm * SCALE))

def render(toolpaths: list, xy_feed: float, plunge_feed: float,
           rapid_feed: float = DEFAULT_RAPID) -> str:
    out = ["^IN;!MC1;"]          # init + spindle ON
    mode = None                  # "cut" | "rapid"
    for tp in toolpaths:
        for m in tp:
            want = "rapid" if m.rapid else "cut"
            if want != mode:
                if m.rapid:
                    out.append(f"VS{rapid_feed};!VZ{rapid_feed};")
                else:
                    out.append(f"VS{xy_feed};!VZ{plunge_feed};")
                mode = want
            out.append(f"Z{_u(m.x)},{_u(m.y)},{_u(m.z)};")
    out.append("!MC0;^IN;")      # spindle OFF + reset
    return "\n".join(out) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_srm20_backend.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Define the backend protocol**

```python
# gerber2rml/backends/base.py
"""Abstract machine-backend interface (the pluggable seam)."""
from typing import Protocol

class MachineBackend(Protocol):
    def render(self, toolpaths: list, xy_feed: float, plunge_feed: float) -> str:
        """Return machine program text for the given toolpaths."""
        ...
```

- [ ] **Step 6: Commit**

```bash
git add gerber2rml/backends/srm20.py gerber2rml/backends/base.py tests/test_srm20_backend.py
git commit -m "Add bug-fixed SRM-20 RML backend"
```

---

## Task 4: Loader (Gerber/Excellon → shapely Board)

**Files:**
- Modify: `gerber2rml/loader.py`
- Test: `tests/test_loader.py`

Uses the API confirmed in Task 0. Builds shapely geometry by unioning each B.Cu graphic object: stroked `Line`s become buffered `LineString`s (buffer = aperture radius), `Flash`es become aperture polygons at their location, `Region`s become `Polygon`s. Outline comes from Edge.Cuts, holes from the Excellon file.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_loader.py
from pathlib import Path
from shapely.geometry.base import BaseGeometry
from gerber2rml.loader import load_board

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"

def test_loads_copper_outline_and_holes():
    board = load_board(FIXT, mirror=False)
    assert isinstance(board.copper, BaseGeometry)
    assert not board.copper.is_empty
    assert board.outline is not None and not board.outline.is_empty
    assert len(board.holes) > 0
    for x, y, dia in board.holes:
        assert dia > 0

def test_mirror_flips_x():
    a = load_board(FIXT, mirror=False)
    b = load_board(FIXT, mirror=True)
    assert b.copper.bounds[0] == -a.copper.bounds[2]  # minx_mirrored == -maxx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_loader.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_board'`.

- [ ] **Step 3: Write the implementation**

```python
# gerber2rml/loader.py  (replace the stub; keep the Task-0 API notes at top)
"""Gerber/Excellon folder -> shapely Board (copper, outline, holes)."""
from dataclasses import dataclass
from pathlib import Path
from shapely.geometry import LineString, Polygon, Point
from shapely.ops import unary_union
from shapely import affinity
from gerbonara import LayerStack

@dataclass
class Board:
    copper: object          # shapely geometry (B.Cu, possibly mirrored)
    outline: object         # shapely geometry (Edge.Cuts)
    holes: list             # list[(x, y, diameter)] in mm

def _objects_to_polygons(layer):
    polys = []
    for o in layer.objects:
        cls = type(o).__name__
        if cls == "Line":
            w = getattr(o, "width", 0) or 0
            ls = LineString([(o.x1, o.y1), (o.x2, o.y2)])
            polys.append(ls.buffer(max(w, 1e-6) / 2.0, cap_style=1))
        elif cls == "Flash":
            r = (getattr(o.aperture, "diameter", 0) or 0) / 2.0
            polys.append(Point(o.x, o.y).buffer(max(r, 1e-6)))
        elif cls == "Region":
            pts = [(p.x, p.y) for p in o.outline] if hasattr(o, "outline") else []
            if len(pts) >= 3:
                polys.append(Polygon(pts))
        # NOTE: Arc support deferred — KiCad B.Cu rarely emits arcs; the spike
        # in Task 0 confirms whether this board contains any.
    return unary_union(polys) if polys else Polygon()

def load_board(folder, mirror: bool = True) -> Board:
    folder = Path(folder)
    stack = LayerStack.open_dir(str(folder))
    copper = _objects_to_polygons(stack['bottom copper'])
    outline = _objects_to_polygons(stack['mechanical outline'])
    holes = []
    drill = stack.drill_pth or stack.drill_npth
    if drill is not None:
        for o in drill.objects:
            if type(o).__name__ == "Flash":
                dia = getattr(o.aperture, "diameter", 0) or 0
                holes.append((o.x, o.y, dia))
    if mirror:
        copper = affinity.scale(copper, xfact=-1, origin=(0, 0))
        outline = affinity.scale(outline, xfact=-1, origin=(0, 0))
        holes = [(-x, y, d) for (x, y, d) in holes]
    return Board(copper=copper, outline=outline, holes=holes)
```

> **Execution note:** the layer keys (`'bottom copper'`, `'mechanical outline'`) and object attribute names (`o.x1`, `o.aperture.diameter`, `o.outline`) MUST match the Task-0 spike output for the installed gerbonara version. Adjust to the printed names before expecting the test to pass.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_loader.py -v`
Expected: PASS (2 passed). If attribute errors appear, reconcile with Task-0 output.

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/loader.py tests/test_loader.py
git commit -m "Add Gerber/Excellon loader producing shapely Board"
```

---

## Task 5: Trace isolation engine

**Files:**
- Modify: `gerber2rml/engine/traces.py`
- Test: `tests/test_traces.py`

Pass *i* path = boundary of `copper.buffer(r + i*stepover_mm)`. Each boundary ring becomes a `Toolpath`: rapid to start at travel Z, plunge to cut depth, follow the ring, lift.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_traces.py
from shapely.geometry import Point
from gerber2rml.config import TraceJob
from gerber2rml.engine.traces import isolate
from gerber2rml.toolpath import Move

def test_one_pad_makes_one_ring_per_offset():
    copper = Point(0, 0).buffer(1.0)        # 1 mm radius pad
    job = TraceJob(bit_diameter=0.4, offsets=2, stepover=0.5)
    paths = isolate(copper, job)
    assert len(paths) == 2                   # two offset passes
    for tp in paths:
        assert all(isinstance(m, Move) for m in tp)
        assert tp[0].rapid is True           # starts with a rapid approach
        assert any(m.z < 0 for m in tp)      # cuts below zero
        assert tp[-1].rapid is True          # ends lifted

def test_ring_radius_grows_by_stepover():
    copper = Point(0, 0).buffer(1.0)
    job = TraceJob(bit_diameter=0.4, offsets=2, stepover=0.5)
    paths = isolate(copper, job)
    r0 = max(abs(m.x) for m in paths[0] if not m.rapid)
    r1 = max(abs(m.x) for m in paths[1] if not m.rapid)
    assert r1 > r0                           # second pass is further out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_traces.py -v`
Expected: FAIL with `ImportError: cannot import name 'isolate'`.

- [ ] **Step 3: Write the implementation**

```python
# gerber2rml/engine/traces.py
"""Trace isolation: copper -> multi-pass isolation toolpaths."""
from shapely.geometry import MultiPolygon, Polygon
from gerber2rml.toolpath import Move

def _rings(geom):
    """Yield each exterior + interior ring coordinate list of a (Multi)Polygon."""
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    for poly in polys:
        if isinstance(poly, Polygon) and not poly.is_empty:
            yield list(poly.exterior.coords)
            for interior in poly.interiors:
                yield list(interior.coords)

def _ring_to_toolpath(coords, cut_z, travel_z):
    sx, sy = coords[0]
    tp = [Move(sx, sy, travel_z, rapid=True), Move(sx, sy, cut_z)]
    for (x, y) in coords[1:]:
        tp.append(Move(x, y, cut_z))
    tp.append(Move(coords[-1][0], coords[-1][1], travel_z, rapid=True))
    return tp

def isolate(copper, job):
    r = job.bit_diameter / 2.0
    step = job.stepover * job.bit_diameter
    n = job.offsets
    cut_z, travel_z = -job.cut_depth, job.travel_z
    paths = []
    i = 0
    while True:
        if n != -1 and i >= n:
            break
        grown = copper.buffer(r + i * step)
        if grown.is_empty:
            break
        rings = list(_rings(grown))
        if not rings:
            break
        for coords in rings:
            paths.append(_ring_to_toolpath(coords, cut_z, travel_z))
        if n == -1 and i > 1000:      # safety cap for clear-all mode
            break
        i += 1
    return paths
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_traces.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/engine/traces.py tests/test_traces.py
git commit -m "Add trace isolation engine"
```

---

## Task 6: Drill engine

**Files:**
- Modify: `gerber2rml/engine/drill.py`
- Test: `tests/test_drill.py`

Each hole becomes a `Toolpath`: rapid over the hole at travel Z, then peck cycles (plunge `cut_depth`, retract to travel Z) until `total_depth` is reached.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drill.py
from gerber2rml.config import DrillJob
from gerber2rml.engine.drill import drill_holes

def test_peck_count_reaches_total_depth():
    job = DrillJob(cut_depth=0.6, total_depth=1.8, travel_z=2.0)
    paths = drill_holes([(5.0, 5.0, 0.8)], job)
    assert len(paths) == 1
    tp = paths[0]
    depths = [m.z for m in tp if not m.rapid]
    assert min(depths) <= -1.8                 # reaches through the board
    assert tp[0].rapid and tp[0].z == 2.0      # starts lifted over the hole
    assert tp[-1].rapid and tp[-1].z == 2.0    # ends lifted

def test_one_path_per_hole():
    job = DrillJob()
    holes = [(1, 1, 0.8), (2, 2, 0.8), (3, 3, 1.0)]
    assert len(drill_holes(holes, job)) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_drill.py -v`
Expected: FAIL with `ImportError: cannot import name 'drill_holes'`.

- [ ] **Step 3: Write the implementation**

```python
# gerber2rml/engine/drill.py
"""Drilling: Excellon holes -> peck-drill toolpaths."""
from gerber2rml.toolpath import Move

def drill_holes(holes, job):
    paths = []
    for (x, y, _dia) in holes:
        tp = [Move(x, y, job.travel_z, rapid=True)]
        depth = 0.0
        while depth < job.total_depth:
            depth = min(depth + job.cut_depth, job.total_depth)
            tp.append(Move(x, y, -depth))                 # peck down
            tp.append(Move(x, y, job.travel_z, rapid=True))  # retract
        paths.append(tp)
    return paths
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_drill.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/engine/drill.py tests/test_drill.py
git commit -m "Add peck-drill engine"
```

---

## Task 7: Cutout engine with tabs

**Files:**
- Modify: `gerber2rml/engine/cutout.py`
- Test: `tests/test_cutout.py`

Outline buffered outward by the bit radius; the resulting ring is cut in multiple passes down to `total_depth`. `tabs` evenly-spaced gaps of `tab_width` are left un-cut on the final geometry by skipping ring segments near the tab positions.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cutout.py
from shapely.geometry import box
from gerber2rml.config import CutoutJob
from gerber2rml.engine.cutout import cut_outline

def test_cutout_passes_reach_total_depth():
    outline = box(0, 0, 20, 20)
    job = CutoutJob(cut_depth=0.6, total_depth=1.8, tabs=0)
    paths = cut_outline(outline, job)
    deepest = min(m.z for tp in paths for m in tp if not m.rapid)
    assert deepest <= -1.8

def test_outline_is_offset_outward():
    outline = box(0, 0, 20, 20)
    job = CutoutJob(bit_diameter=0.8, tabs=0, cut_depth=0.6, total_depth=0.6)
    paths = cut_outline(outline, job)
    xs = [m.x for tp in paths for m in tp if not m.rapid]
    assert min(xs) < 0          # cut path rides outside the board edge

def test_tabs_create_gaps():
    outline = box(0, 0, 20, 20)
    job = CutoutJob(tabs=4, tab_width=1.5, cut_depth=0.6, total_depth=0.6)
    paths_with = cut_outline(outline, job)
    paths_without = cut_outline(outline, CutoutJob(tabs=0, cut_depth=0.6, total_depth=0.6))
    n_with = sum(len(tp) for tp in paths_with)
    n_without = sum(len(tp) for tp in paths_without)
    assert n_with > n_without   # tabs split the ring into more, shorter paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cutout.py -v`
Expected: FAIL with `ImportError: cannot import name 'cut_outline'`.

- [ ] **Step 3: Write the implementation**

```python
# gerber2rml/engine/cutout.py
"""Board cutout: outline -> outward-offset cut with holding tabs."""
from shapely.geometry import MultiPolygon, Polygon, LineString
from gerber2rml.toolpath import Move

def _largest_ring(geom):
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    polys = [p for p in polys if isinstance(p, Polygon) and not p.is_empty]
    biggest = max(polys, key=lambda p: p.area)
    return LineString(biggest.exterior.coords)

def _segments_with_tabs(ring, tabs, tab_width):
    """Split the closed ring into kept segments, leaving `tabs` gaps."""
    L = ring.length
    if tabs <= 0:
        return [list(ring.coords)]
    gap_centers = [L * k / tabs for k in range(tabs)]
    cut_ranges = []  # (start_dist, end_dist) to KEEP
    prev = 0.0
    for c in gap_centers + [L]:
        gap_start = c - tab_width / 2.0
        if gap_start > prev:
            cut_ranges.append((prev, gap_start))
        prev = c + tab_width / 2.0
    segments = []
    for (a, b) in cut_ranges:
        n = max(2, int((b - a) / 0.5))
        pts = [ring.interpolate(a + (b - a) * t / (n - 1)).coords[0] for t in range(n)]
        segments.append(pts)
    return segments

def cut_outline(outline, job):
    r = job.bit_diameter / 2.0
    ring = _largest_ring(outline.buffer(r))
    segments = _segments_with_tabs(ring, job.tabs, job.tab_width)
    paths = []
    depth = 0.0
    while depth < job.total_depth:
        depth = min(depth + job.cut_depth, job.total_depth)
        for seg in segments:
            sx, sy = seg[0]
            tp = [Move(sx, sy, job.travel_z, rapid=True), Move(sx, sy, -depth)]
            for (x, y) in seg[1:]:
                tp.append(Move(x, y, -depth))
            tp.append(Move(seg[-1][0], seg[-1][1], job.travel_z, rapid=True))
            paths.append(tp)
    return paths
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cutout.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/engine/cutout.py tests/test_cutout.py
git commit -m "Add cutout engine with holding tabs"
```

---

## Task 8: CLI driver

**Files:**
- Create: `gerber2rml/cli.py`
- Test: `tests/test_cli.py`

Wires loader → engines → SRM-20 backend, writing three `.rml` files plus an operator run-plan note.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from pathlib import Path
from gerber2rml.cli import build_jobs

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"

def test_build_jobs_writes_three_rml(tmp_path):
    written = build_jobs(FIXT, tmp_path, name="mosfet_test")
    names = {p.name for p in written}
    assert "mosfet_test_traces.rml" in names
    assert "mosfet_test_drill.rml" in names
    assert "mosfet_test_cutout.rml" in names
    for p in written:
        text = p.read_text()
        assert text.startswith("^IN;!MC1;")   # spindle on
        assert text.rstrip().endswith("!MC0;^IN;")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_jobs'`.

- [ ] **Step 3: Write the implementation**

```python
# gerber2rml/cli.py
"""CLI: gerber folder -> three SRM-20 RML jobs."""
import argparse
from pathlib import Path
from gerber2rml.loader import load_board
from gerber2rml.config import TraceJob, DrillJob, CutoutJob
from gerber2rml.engine.traces import isolate
from gerber2rml.engine.drill import drill_holes
from gerber2rml.engine.cutout import cut_outline
from gerber2rml.backends import srm20

def build_jobs(gerber_dir, out_dir, name, trace=None, drill=None, cutout=None):
    gerber_dir, out_dir = Path(gerber_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace, drill, cutout = trace or TraceJob(), drill or DrillJob(), cutout or CutoutJob()
    board = load_board(gerber_dir, mirror=trace.mirror)

    written = []
    jobs = [
        (f"{name}_traces.rml", isolate(board.copper, trace), trace),
        (f"{name}_drill.rml", drill_holes(board.holes, drill), drill),
        (f"{name}_cutout.rml", cut_outline(board.outline, cutout), cutout),
    ]
    for fname, paths, job in jobs:
        rml = srm20.render(paths, xy_feed=job.xy_feed, plunge_feed=job.plunge_feed)
        p = out_dir / fname
        p.write_text(rml)
        written.append(p)
    return written

def main(argv=None):
    ap = argparse.ArgumentParser(prog="gerber2rml")
    ap.add_argument("gerber_dir")
    ap.add_argument("-o", "--out", default="out")
    ap.add_argument("-n", "--name", default="board")
    args = ap.parse_args(argv)
    for p in build_jobs(args.gerber_dir, args.out, args.name):
        print("wrote", p)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the whole suite + try the CLI for real**

Run: `pytest -v`
Expected: all tests PASS.
Run: `python -m gerber2rml.cli tests/fixtures/mosfet_test -o out -n mosfet_test`
Expected: prints three written `.rml` paths; inspect `out/mosfet_test_traces.rml` — header `^IN;!MC1;`, contains `VS4.0;!VZ1.0;`, ends `!MC0;^IN;`.

- [ ] **Step 6: Commit**

```bash
git add gerber2rml/cli.py tests/test_cli.py
git commit -m "Add CLI that writes three SRM-20 RML jobs"
```

---

## Task 9: mods parity check (trust gate before milling)

**Files:**
- Create: `docs/parity-mosfet_test.md`

Manual verification task — confirms our RML drives the machine like the trusted mods output before anyone cuts metal.

- [ ] **Step 1: Generate our RML**

Run: `python -m gerber2rml.cli tests/fixtures/mosfet_test -o out -n mosfet_test`

- [ ] **Step 2: Generate mods RML for the same board**

Export the same B.Cu as PNG/SVG, run it through the mods `mill 2D PCB` SRM-20 program (1/64", 2 offsets, 4 mm/s), download its `.rml`.

- [ ] **Step 3: Compare and record**

In `docs/parity-mosfet_test.md`, record: bounding box of moves (ours vs mods, should match within rounding), total cut length, spindle on/off presence, and any divergence. Note that exact move ordering will differ (different path planners) — what must match is **geometry extent and that copper is fully isolated**.

- [ ] **Step 4: Commit**

```bash
git add docs/parity-mosfet_test.md
git commit -m "Add mods parity verification notes for mosfet_test"
```

---

## Self-Review

- **Spec coverage:** loader (§3-4 ✓ Task 4), traces/drill/cutout engines (§4 ✓ Tasks 5-7), pluggable backend + SRM-20 RML bug-fixes (§3,§6 ✓ Tasks 1,3), error handling (mismatched layers surface as gerbonara key errors at load; full GUI error messaging is Plan B), testing incl. mods parity (§8 ✓ Task 9). Single-sided mirror (§2 ✓ Task 4). GUI (§5) is intentionally deferred to Plan B. Submodule wiring (§9) is deferred to after the tool works (Plan B final task).
- **Type consistency:** `Move(x,y,z,rapid)` and `render(toolpaths, xy_feed, plunge_feed, rapid_feed=)` used identically in Tasks 3,5,6,7,8. `load_board(folder, mirror)` → `Board(copper, outline, holes)` consumed consistently in Task 8. Job dataclass field names match between Task 2 and their use in Tasks 5-8.
- **Known verification points (not placeholders, real external-API checks):** Task 0 spike confirms gerbonara layer keys + object attributes that Task 4 depends on; Task 9 confirms machine-level parity. Both are explicit steps with commands and expected output.

## Deferred to Plan B (GUI)

PySide6 window, parameter tabs, matplotlib toolpath preview, export button (design §5); richer error dialogs; submodule wiring into the team repo at `tools/srm-cam/` (design §9); arc (`G02`/`G03`-equivalent) handling in the loader if a board needs it.
