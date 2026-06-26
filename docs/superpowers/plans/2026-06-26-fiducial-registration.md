# Fiducial Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in fiducial-registration workflow for double-sided boards (drill 2–4 stock-only corner holes, measure them after the flip, fit a rigid+optional-scale transform, and warp the top traces to match) while keeping the proven dowel workflow as the default.

**Architecture:** A new pure engine module `engine/fiducial.py` does the math (fit transform from nominal→measured points, apply to toolpaths, report RMS). `doublesided.py` gains a `FiducialSpec` and a `registration="dowel"|"fiducial"` switch that reuses the existing mirror/reflect layout — fiducials simply replace the two dowel holes as the registration holes. The build path drills fiducials stock-only and the top-traces re-export applies the fitted transform. The GUI exposes the mode, the fiducial parameters, and a measure/capture/fit panel.

**Tech Stack:** Python 3, shapely (already used), PySide6 (GUI), pytest. No new dependencies.

## Global Constraints

- No new third-party dependencies (stdlib `math` only for the engine).
- `Move` is frozen (`gerber2rml/toolpath.py`): build new `Move(...)`, never mutate.
- Registration transform changes **X/Y only**; Z is owned by depth/leveling.
- Dowel workflow stays the default: `registration="dowel"` unless explicitly set.
- Commits: plain developer messages, **no AI/Claude mention** (team rule).
- Tests live in `tests/`, run with `python -m pytest`. Match existing style
  (`tests/test_doublesided.py`, `tests/test_estimate.py`).
- Fiducial holes are **through-holes, stock only**: depth = board_thickness +
  small breakthrough; never the dowel bed bite.

---

### Task 1: Engine — `engine/fiducial.py` (pure math)

**Files:**
- Create: `gerber2rml/engine/fiducial.py`
- Test: `tests/test_fiducial.py`

**Interfaces:**
- Consumes: `gerber2rml.toolpath.Move`.
- Produces:
  - `Transform` dataclass: fields `theta` (rad), `scale` (float), `tx`, `ty`
    (mm); method `apply(x, y) -> (x, y)`.
  - `fit_transform(nominal, measured, allow_scale=False) -> Transform`
    where `nominal`/`measured` are `list[(x, y)]` (length 2–4, equal length).
  - `residuals(t, nominal, measured) -> list[float]` (per-point distance).
  - `rms(t, nominal, measured) -> float`.
  - `apply_to_toolpaths(toolpaths, t) -> list[list[Move]]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fiducial.py
import math
import pytest
from gerber2rml.toolpath import Move
from gerber2rml.engine.fiducial import (
    Transform, fit_transform, residuals, rms, apply_to_toolpaths,
)

P = [(0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0)]   # nominal corners


def _apply(pts, t):
    return [t.apply(x, y) for (x, y) in pts]


def test_pure_translation():
    meas = [(x + 2.0, y - 3.0) for (x, y) in P]
    t = fit_transform(P, meas)
    assert abs(t.tx - 2.0) < 1e-9 and abs(t.ty + 3.0) < 1e-9
    assert abs(t.theta) < 1e-9 and abs(t.scale - 1.0) < 1e-9
    assert rms(t, P, meas) < 1e-9


def test_rotation_plus_translation():
    a = math.radians(1.5)                       # small flip skew
    c, s = math.cos(a), math.sin(a)
    meas = [(c * x - s * y + 4.0, s * x + c * y + 1.0) for (x, y) in P]
    t = fit_transform(P, meas)
    assert abs(t.theta - a) < 1e-6
    assert abs(t.scale - 1.0) < 1e-6
    assert rms(t, P, meas) < 1e-6


def test_uniform_scale_only_when_allowed():
    meas = [(1.01 * x, 1.01 * y) for (x, y) in P]
    rigid = fit_transform(P, meas, allow_scale=False)
    assert abs(rigid.scale - 1.0) < 1e-12        # locked
    scaled = fit_transform(P, meas, allow_scale=True)
    assert abs(scaled.scale - 1.01) < 1e-6


def test_two_points_exact_similarity():
    meas = [(5.0, 5.0), (5.0, 15.0)]             # nominal->measured, 90deg + move
    nom = [(0.0, 0.0), (10.0, 0.0)]
    t = fit_transform(nom, meas, allow_scale=True)
    assert rms(t, nom, meas) < 1e-9


def test_residuals_flag_a_bad_point():
    meas = [(x + 1.0, y + 1.0) for (x, y) in P]
    meas[2] = (meas[2][0] + 0.3, meas[2][1])     # one hole mis-measured
    t = fit_transform(P, meas)
    res = residuals(t, P, meas)
    assert max(res) > 0.1 and rms(t, P, meas) > 0.0


def test_apply_to_toolpaths_moves_xy_not_z():
    t = Transform(theta=0.0, scale=1.0, tx=2.0, ty=-3.0)
    tp = [[Move(1.0, 1.0, -0.15), Move(2.0, 1.0, -0.15, rapid=True)]]
    out = apply_to_toolpaths(tp, t)
    assert out[0][0].x == 3.0 and out[0][0].y == -2.0 and out[0][0].z == -0.15
    assert out[0][1].rapid is True


def test_too_few_points_raises():
    with pytest.raises(ValueError):
        fit_transform([(0.0, 0.0)], [(1.0, 1.0)])


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        fit_transform(P, P[:3])


def test_degenerate_nominal_raises():
    with pytest.raises(ValueError):
        fit_transform([(1.0, 1.0), (1.0, 1.0)], [(0.0, 0.0), (2.0, 2.0)])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_fiducial.py -q`
Expected: FAIL (`ModuleNotFoundError: gerber2rml.engine.fiducial`).

- [ ] **Step 3: Write the implementation**

```python
# gerber2rml/engine/fiducial.py
"""Fiducial registration: fit a 2D transform from measured reference holes.

Double-sided alternative to dowel pins. The mill drills 2-4 corner fiducial
holes registered to the bottom copper. After the flip the operator measures
where those holes actually landed; we fit the best-fit similarity transform
(rotation + translation, optionally uniform scale) from the NOMINAL hole
positions (where a perfect flip would put them) to the MEASURED positions, and
warp the top-trace toolpaths by it.

Rigid by default (scale locked to 1) to match a physically rigid board; uniform
scale is offered to absorb genuine thermal/measurement scale. Shear is never
modelled -- it would silently absorb real misregistration. The RMS of the fit
residuals is the numeric "how good was this flip?" readout.

Math: closed-form 2D similarity least squares (Umeyama). Centre both point sets,
then theta = atan2(sum cross, sum dot), scale = |.|/sum|p|^2 (or 1 if locked),
translation = q_bar - scale*R(theta)*p_bar.
"""
from dataclasses import dataclass
from math import atan2, cos, sin, sqrt

from gerber2rml.toolpath import Move


@dataclass(frozen=True)
class Transform:
    """2D similarity: scale * R(theta) * (x, y) + (tx, ty)."""
    theta: float
    scale: float
    tx: float
    ty: float

    def apply(self, x, y):
        c, s = cos(self.theta), sin(self.theta)
        return (self.scale * (c * x - s * y) + self.tx,
                self.scale * (s * x + c * y) + self.ty)


def _check(nominal, measured):
    if len(nominal) != len(measured):
        raise ValueError("nominal and measured must have equal length")
    if len(nominal) < 2:
        raise ValueError("need at least 2 fiducial points to fit a transform")


def fit_transform(nominal, measured, allow_scale=False):
    """Best-fit similarity mapping ``nominal`` -> ``measured`` (each list[(x, y)],
    length 2-4). Rigid (scale=1) unless ``allow_scale``. Raises ValueError on
    too-few/mismatched points or a degenerate (zero-spread) nominal set."""
    _check(nominal, measured)
    n = len(nominal)
    pxb = sum(p[0] for p in nominal) / n
    pyb = sum(p[1] for p in nominal) / n
    qxb = sum(q[0] for q in measured) / n
    qyb = sum(q[1] for q in measured) / n
    dot = cross = denom = 0.0
    for (px, py), (qx, qy) in zip(nominal, measured):
        ax, ay = px - pxb, py - pyb
        bx, by = qx - qxb, qy - qyb
        dot += ax * bx + ay * by
        cross += ax * by - ay * bx
        denom += ax * ax + ay * ay
    if denom < 1e-12:
        raise ValueError("degenerate nominal points (no spread to fit)")
    theta = atan2(cross, dot)
    scale = sqrt(dot * dot + cross * cross) / denom if allow_scale else 1.0
    c, s = cos(theta), sin(theta)
    tx = qxb - scale * (c * pxb - s * pyb)
    ty = qyb - scale * (s * pxb + c * pyb)
    return Transform(theta, scale, tx, ty)


def residuals(t, nominal, measured):
    """Per-point Euclidean distance (mm) between ``t(nominal)`` and ``measured``."""
    _check(nominal, measured)
    out = []
    for (px, py), (qx, qy) in zip(nominal, measured):
        mx, my = t.apply(px, py)
        out.append(sqrt((mx - qx) ** 2 + (my - qy) ** 2))
    return out


def rms(t, nominal, measured):
    """Root-mean-square of :func:`residuals` -- the flip-quality number (mm)."""
    res = residuals(t, nominal, measured)
    return sqrt(sum(r * r for r in res) / len(res))


def apply_to_toolpaths(toolpaths, t):
    """Warp X/Y of every ``Move`` by ``t``; Z and rapid are untouched."""
    out = []
    for path in toolpaths:
        new = []
        for m in path:
            nx, ny = t.apply(m.x, m.y)
            new.append(Move(nx, ny, m.z, m.rapid))
        out.append(new)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_fiducial.py -q`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/engine/fiducial.py tests/test_fiducial.py
git commit -m "feat(fiducial): transform fit + apply engine for registration"
```

---

### Task 2: Layout — `FiducialSpec` + corner placement + registration switch

**Files:**
- Modify: `gerber2rml/doublesided.py` (add `FiducialSpec`, `_place_fiducials`,
  extend `layout_double_sided` and `preview_layout_double_sided`)
- Test: `tests/test_doublesided.py` (append fiducial cases)

**Interfaces:**
- Consumes: existing `_load_rotated`, `_mirror_all`, `_frame`, `_reflect_geom`,
  `reflect_holes`, `DoubleSidedLayout`, `PreviewLayout`, `_offset_layout`.
- Produces:
  - `FiducialSpec` dataclass: `count:int=4`, `placement:str="onboard"`
    (`"onboard"|"waste"`), `edge_offset:float=4.0`, `hole_diameter:float=0.8`,
    `breakthrough:float=0.3`, `allow_scale:bool=False`, `margin:float=6.0`.
  - `layout_double_sided(folder, dowels=None, offset=(0,0), rotate=0,
    registration="dowel", fiducials=None)` — when `registration=="fiducial"`,
    `lay.align_holes` holds the 2–4 corner fiducial holes (still the registration
    holes), and `lay.axis`/`lay.flip_pos` keep the vertical-axis default so the
    top is reflected exactly as today.
  - same new kwargs on `preview_layout_double_sided`.
  - `nominal_top_fiducials(lay) -> list[(x, y)]` — `lay.align_holes` reflected
    into the top-cut frame (where a perfect flip lands them); the points the
    operator probes and that `fit_transform` takes as `nominal`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_doublesided.py
from gerber2rml.doublesided import FiducialSpec, nominal_top_fiducials


def test_fiducial_count_and_onboard_inside_outline():
    lay = layout_double_sided(FIXT, registration="fiducial",
                              fiducials=FiducialSpec(count=4, placement="onboard",
                                                     edge_offset=3.0))
    assert len(lay.align_holes) == 4
    ox0, oy0, ox1, oy1 = lay.outline.bounds
    for (x, y, d) in lay.align_holes:
        assert ox0 - 1e-6 <= x <= ox1 + 1e-6        # inside the board
        assert oy0 - 1e-6 <= y <= oy1 + 1e-6
        assert abs(d - 0.8) < 1e-6


def test_fiducial_waste_outside_outline():
    lay = layout_double_sided(FIXT, registration="fiducial",
                              fiducials=FiducialSpec(count=4, placement="waste",
                                                     edge_offset=5.0))
    ox0, oy0, ox1, oy1 = lay.outline.bounds
    xs = [h[0] for h in lay.align_holes]
    ys = [h[1] for h in lay.align_holes]
    assert min(xs) < ox0 and max(xs) > ox1          # corners straddle the board
    assert min(ys) < oy0 and max(ys) > oy1


def test_fiducial_count_two_is_diagonal():
    lay = layout_double_sided(FIXT, registration="fiducial",
                              fiducials=FiducialSpec(count=2, placement="onboard"))
    assert len(lay.align_holes) == 2
    (ax, ay, _), (bx, by, _) = lay.align_holes
    assert ax != bx and ay != by                    # opposite corners, not an edge


def test_nominal_top_fiducials_are_reflected():
    lay = layout_double_sided(FIXT, registration="fiducial",
                              fiducials=FiducialSpec(count=4))
    nom = nominal_top_fiducials(lay)
    for (hx, hy, _), (nx, ny) in zip(lay.align_holes, nom):
        assert abs(nx - (2 * lay.flip_pos - hx)) < 1e-6 and abs(ny - hy) < 1e-6


def test_dowel_still_default():
    lay = layout_double_sided(FIXT)                  # no registration kwarg
    assert len(lay.align_holes) == 2                 # unchanged dowel behaviour
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_doublesided.py -q`
Expected: FAIL (`ImportError: FiducialSpec` / `nominal_top_fiducials`).

- [ ] **Step 3: Write the implementation**

Add near `DowelSpec` in `gerber2rml/doublesided.py`:

```python
@dataclass
class FiducialSpec:
    """2-4 corner reference holes for measured (non-dowel) registration.

    ``placement='onboard'`` insets the holes ``edge_offset`` mm inside the board
    corners (permanent holes, no oversized stock — works for full-bed boards);
    ``'waste'`` outsets them ``edge_offset`` mm beyond the corners (clean board,
    needs larger stock). Holes are through-holes drilled stock-only (board
    thickness + ``breakthrough``); they never take the dowel bed bite.
    """
    count: int = 4                     # 2..4
    placement: str = "onboard"         # "onboard" | "waste"
    edge_offset: float = 4.0           # inset (onboard) / outset (waste), mm
    hole_diameter: float = 0.8         # mm (drilled with the single bit)
    breakthrough: float = 0.3          # mm past the board, for a clean through-hole
    allow_scale: bool = False          # fit uniform scale too?
    margin: float = 6.0                # positive-quadrant clearance (mm)


# corner order: FL, FR, BR, BL. count=2 -> FL,BR (diagonal); 3 -> FL,FR,BL.
_CORNER_PICK = {2: (0, 2), 3: (0, 1, 3), 4: (0, 1, 2, 3)}


def _place_fiducials(gx0, gy0, gx1, gy1, spec):
    """Return (align_holes, flip_pos, dx, dy) for fiducial registration.

    Corners are insets (onboard) or outsets (waste) of the framed board box; the
    whole job is then shifted into the positive quadrant with ``margin``. The
    flip axis stays the board's vertical centre line so the top reflects exactly
    as in the dowel layout."""
    off = spec.edge_offset
    s = -1.0 if spec.placement == "onboard" else 1.0   # onboard insets inward
    corners = [(gx0 - s * off, gy0 - s * off),         # FL
               (gx1 + s * off, gy0 - s * off),         # FR
               (gx1 + s * off, gy1 + s * off),         # BR
               (gx0 - s * off, gy1 + s * off)]         # BL
    n = max(2, min(4, spec.count))
    picked = [corners[i] for i in _CORNER_PICK[n]]
    cx = (gx0 + gx1) / 2.0
    allminx = min(gx0, min(x for x, _ in picked))
    allminy = min(gy0, min(y for _, y in picked))
    dx, dy = spec.margin - allminx, spec.margin - allminy
    align = [(x + dx, y + dy, spec.hole_diameter) for (x, y) in picked]
    return align, cx + dx, dx, dy


def nominal_top_fiducials(lay):
    """The registration holes reflected into the top-cut frame — where a perfect
    flip puts them, and the ``nominal`` points for :func:`fit_transform`."""
    return [(x, y) for (x, y, _d) in
            reflect_holes(lay.align_holes, lay.axis, lay.flip_pos)]
```

Then thread `registration`/`fiducials` through the two layout builders. In
`layout_double_sided`, replace the placement call:

```python
def layout_double_sided(folder, dowels: DowelSpec = None, offset=(0.0, 0.0),
                        rotate=0, registration="dowel", fiducials: FiducialSpec = None):
    dowels = dowels or DowelSpec()
    folder = Path(folder)
    axis = "vertical" if registration == "fiducial" else _axis_of(dowels)
    b = _load_rotated(folder, rotate)
    copper, copper_top, outline_g, holes_raw = _mirror_all(b, axis)
    geoms = [g for g in (copper, outline_g) if not g.is_empty]
    gx0, gy0, gx1, gy1 = _frame(geoms)
    if registration == "fiducial":
        align_holes, flip_pos, dx, dy = _place_fiducials(
            gx0, gy0, gx1, gy1, fiducials or FiducialSpec())
    else:
        align_holes, flip_pos, dx, dy = _place(gx0, gy0, gx1, gy1, dowels)
    bottom_copper = translate(copper, xoff=dx, yoff=dy)
    top_src = translate(copper_top, xoff=dx, yoff=dy)
    outline = translate(outline_g, xoff=dx, yoff=dy)
    holes = [(x + dx, y + dy, d) for (x, y, d) in holes_raw]
    top_copper = _reflect_geom(top_src, axis, flip_pos)
    top_outline = _reflect_geom(outline, axis, flip_pos)
    return _offset_layout(
        DoubleSidedLayout(bottom_copper, top_copper, outline, top_outline,
                          holes, align_holes, axis, flip_pos), offset)
```

Apply the same `registration`/`fiducials` kwargs + branch to
`preview_layout_double_sided` (it frames `b.copper`/`b.outline` un-mirrored; call
`_place_fiducials` the same way).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_doublesided.py -q`
Expected: PASS (existing dowel tests + 5 new fiducial tests).

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/doublesided.py tests/test_doublesided.py
git commit -m "feat(fiducial): corner-hole layout + registration switch"
```

---

### Task 3: Build path — fiducial drill, run plan, transformed top traces

**Files:**
- Modify: `gerber2rml/doublesided.py` (`build_double_sided`, `build_top_traces`,
  run-plan text; add a fiducial align-depth helper + fiducial run-plan block)
- Test: `tests/test_doublesided.py` (append build cases)

**Interfaces:**
- Consumes: Task 1 `fit_transform`/`apply_to_toolpaths`, Task 2
  `FiducialSpec`/`nominal_top_fiducials`, existing `drill_single_bit`,
  `isolate`, `backend.render`.
- Produces:
  - `build_double_sided(..., registration="dowel", fiducials=None)` — fiducial
    mode drills the corner holes `board_thickness + fiducials.breakthrough` deep
    (no bed bite) and writes a fiducial run plan listing nominal top-frame coords.
  - `build_top_traces(..., measured_fiducials=None, allow_scale=False,
    registration="dowel", fiducials=None)` — when `measured_fiducials` is given,
    fit `T` from `nominal_top_fiducials(lay)` → `measured_fiducials` and apply to
    the top toolpaths before (optional) leveling and render. Returns the Path.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_doublesided.py
import math as _math
from gerber2rml.doublesided import build_double_sided, build_top_traces


def test_fiducial_build_writes_files_and_runplan(tmp_path):
    files = build_double_sided(FIXT, tmp_path, "fid", registration="fiducial",
                               fiducials=FiducialSpec(count=4))
    names = {p.name for p in files}
    assert "fid_align.rml" in names and "fid_runplan.txt" in names
    plan = (tmp_path / "fid_runplan.txt").read_text(encoding="utf-8")
    assert "fiducial" in plan.lower()
    assert "X" in plan and "Y" in plan          # nominal probe coords listed


def test_fiducial_top_traces_apply_measured_transform(tmp_path):
    lay = layout_double_sided(FIXT, registration="fiducial",
                              fiducials=FiducialSpec(count=4))
    nom = nominal_top_fiducials(lay)
    measured = [(x + 1.0, y + 0.5) for (x, y) in nom]   # pure 1.0/0.5 shift
    out = build_top_traces(FIXT, tmp_path, "fid", registration="fiducial",
                           fiducials=FiducialSpec(count=4),
                           measured_fiducials=measured)
    shifted = out.read_text()
    # baseline (no measured transform) for comparison
    base = build_top_traces(FIXT, tmp_path, "base", registration="fiducial",
                            fiducials=FiducialSpec(count=4))
    assert shifted != base.read_text()          # transform changed the output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_doublesided.py -k fiducial_build -q`
Expected: FAIL (`build_double_sided` has no `registration` kwarg / TypeError).

- [ ] **Step 3: Write the implementation**

Add a fiducial align-depth helper and branch in `build_double_sided`. Replace the
`lay = layout_double_sided(...)` and align-drill section with a registration-aware
version:

```python
def _fiducial_align_drill(drill, fiducials, board_thickness):
    """Drill spec for fiducial holes: through the stock + a small breakthrough,
    single bit. NO bed bite (that is the dowel-only behaviour)."""
    depth = board_thickness + fiducials.breakthrough
    return replace(drill, total_depth=depth, single_bit=True), depth
```

In `build_double_sided`, accept `registration="dowel"`, `fiducials=None`, build
the layout with them, and choose the align drill:

```python
    lay = layout_double_sided(folder, dowels=dowels, offset=offset, rotate=rotate,
                              registration=registration, fiducials=fiducials)
    if registration == "fiducial":
        fiducials = fiducials or FiducialSpec()
        align_drill, align_depth = _fiducial_align_drill(drill, fiducials,
                                                         board_thickness)
    else:
        align_drill, align_depth = _align_drill(drill, dowels, align_depth,
                                                 board_thickness, bed_depth)
```

Keep the rest of `build_double_sided` identical (the align/drill/traces/cutout
`_write` calls and the estimate block are unchanged). For the run plan, branch:

```python
    if registration == "fiducial":
        rp = _fiducial_runplan_text(name, machine, lay, fiducials or FiducialSpec(),
                                    drill_step, align_depth, board_thickness)
    else:
        rp = _runplan_text(name, machine, lay, dowels, drill_step, align_depth,
                           board_thickness)
    runplan.write_text(rp + est_block, encoding="utf-8")
```

Add the fiducial run-plan text:

```python
def _fiducial_runplan_text(name, machine, lay, fiducials, drill_step,
                           align_depth, thickness):
    from gerber2rml.doublesided import nominal_top_fiducials
    nom = nominal_top_fiducials(lay)
    rows = "".join(f"    fiducial {i + 1}: X{x:.3f} Y{y:.3f}\n"
                   for i, (x, y) in enumerate(nom))
    where = ("inside the board corners" if fiducials.placement == "onboard"
             else "in the waste beyond the board corners")
    scale = "rotation + translation + uniform scale" if fiducials.allow_scale \
        else "rotation + translation"
    return (
        f"DOUBLE-SIDED run plan: {name}  [{machine}]  registration: FIDUCIAL\n\n"
        f"FIDUCIAL mode: {len(nom)} reference holes {where}, drilled "
        f"{align_depth:.2f} mm (through the {thickness:.1f} mm stock only — NOT "
        f"into the bed). Onboard holes stay in the finished board; pick corners "
        f"clear of copper.\n\n"
        f"0. Set XY zero ONCE and do NOT re-zero XY for the bottom side.\n"
        f"1. {name}_align: drills the {len(nom)} fiducial holes. Bottom side: "
        f"{drill_step}. Then {name}_bottom_traces.\n"
        f"2. FLIP the board left-to-right and re-place it (no pins needed).\n"
        f"   Re-zero Z on the new surface.\n"
        f"3. Probe each fiducial and record its measured X/Y. Nominal (perfect-\n"
        f"   flip) positions to probe near:\n{rows}"
        f"4. In the app, enter/capture the measured X/Y and 'Fit & export top\n"
        f"   traces' (fit: {scale}). Check the RMS — a high value means a bad\n"
        f"   re-placement; re-seat and re-probe before cutting.\n"
        f"5. {name}_top_traces (now warped to the fit): cut it.\n"
        f"6. {name}_cutout LAST.\n")
```

Extend `build_top_traces` to optionally fit+apply the transform:

```python
def build_top_traces(folder, out_dir, name, trace=None, dowels: DowelSpec = None,
                     machine=DEFAULT_MACHINE, offset=(0.0, 0.0), rotate=0, level=None,
                     registration="dowel", fiducials: FiducialSpec = None,
                     measured_fiducials=None, allow_scale=False):
    dowels = dowels or DowelSpec()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace = trace or TraceJob()
    backend = BACKENDS[machine]
    lay = layout_double_sided(folder, dowels=dowels, offset=offset, rotate=rotate,
                              registration=registration, fiducials=fiducials)
    paths = isolate(lay.top_copper, trace, outline=lay.top_outline)
    if measured_fiducials:
        from gerber2rml.engine.fiducial import fit_transform, apply_to_toolpaths
        nom = nominal_top_fiducials(lay)
        t = fit_transform(nom, measured_fiducials, allow_scale=allow_scale)
        paths = apply_to_toolpaths(paths, t)
    if level is not None:
        from gerber2rml.engine.leveling import apply_leveling
        paths = apply_leveling(paths, level)
    out = out_dir / f"{name}_top_traces{backend.ext}"
    out.write_text(backend.render(paths, xy_feed=trace.xy_feed,
                                  plunge_feed=trace.plunge_feed))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_doublesided.py -q`
Expected: PASS (all dowel + fiducial cases).

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/doublesided.py tests/test_doublesided.py
git commit -m "feat(fiducial): stock-only drill, run plan, transformed top traces"
```

---

### Task 4: GUI — registration selector + measure/capture/fit panel

**Files:**
- Modify: `gerber2rml/gui/app.py` (registration mode selector in the double-sided
  page; a fiducial-align panel; wire `build_double_sided`/`build_top_traces`
  calls; capture-from-DRO using the existing `_on_position` live feed)
- Test: `tests/test_window.py` (append a fiducial smoke test)

**Interfaces:**
- Consumes: Task 1–3 engine/build API; existing `_dowel_spec_from_ui`
  (`app.py:853`), `_on_double_sided_toggled` (`app.py:939`),
  `_update_double_sided_controls` (`app.py:928`), the `build_double_sided` call
  site (`app.py:1138`), and the live DRO position handler `_on_position`
  (last live `(x, y, z)` is already tracked for the tool marker).
- Produces: a `registration` choice ("dowel"/"fiducial"), a `_fiducial_spec_from_ui()`
  returning `FiducialSpec`, a fiducial panel with one measured-X/Y row per hole,
  a per-row "Capture from DRO" button, and a "Fit & export top traces" button
  that shows RMS/rotation/scale and writes the corrected top-traces file.

- [ ] **Step 1: Write the failing smoke test**

```python
# append to tests/test_window.py  (follow the existing QApplication fixture)
def test_fiducial_mode_builds(qtbot, tmp_path, monkeypatch):
    from gerber2rml.gui.app import MainWindow      # match existing imports
    w = MainWindow()
    qtbot.addWidget(w)
    # select a board fixture + enable double-sided + fiducial registration
    w._select_registration("fiducial")             # helper added in this task
    spec = w._fiducial_spec_from_ui()
    assert spec.count in (2, 3, 4)
    assert spec.placement in ("onboard", "waste")
```

(If `test_window.py` uses a different harness than `qtbot`, mirror that file's
existing fixture instead — match the file, do not introduce pytest-qt if it is
not already used.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_window.py -k fiducial -q`
Expected: FAIL (`_select_registration` / `_fiducial_spec_from_ui` missing).

- [ ] **Step 3: Implement the GUI wiring**

In the double-sided page (around `app.py:674` / `_make_page`), add a
**Registration** combo: `Dowel pins` / `Fiducial holes`. Default `Dowel pins`.
Reveal the existing dowel controls for "dowel" and a new fiducial group for
"fiducial" (reuse the `_update_double_sided_controls` show/hide pattern).

Fiducial group widgets:
- `count` spinbox (2–4, default 4)
- `placement` combo (`On board` -> "onboard", `In waste` -> "waste")
- `edge_offset` double-spin (mm, default 4.0)
- `allow_scale` checkbox ("Also fit scale", default off)
- A table/grid: one row per fiducial showing nominal X/Y (from
  `nominal_top_fiducials` after a build), two editable fields for measured X/Y,
  and a "Capture from DRO" button that fills them from the last live position.
- "Fit & export top traces" button.

Add helpers:

```python
def _select_registration(self, mode):
    """Set the registration combo programmatically ('dowel'|'fiducial')."""
    self._registration = mode
    idx = 1 if mode == "fiducial" else 0
    self.registration_combo.setCurrentIndex(idx)
    self._update_double_sided_controls()

def _fiducial_spec_from_ui(self):
    from gerber2rml.doublesided import FiducialSpec
    return FiducialSpec(
        count=self.fid_count.value(),
        placement=("waste" if self.fid_placement.currentIndex() == 1 else "onboard"),
        edge_offset=self.fid_offset.value(),
        allow_scale=self.fid_scale.isChecked())

def _capture_fiducial_from_dro(self, row):
    """Fill row's measured X/Y from the last live tool position."""
    if self._last_pos is None:                 # set in _on_position
        return
    x, y, _z = self._last_pos
    self.fid_rows[row].x.setText(f"{x:.3f}")
    self.fid_rows[row].y.setText(f"{y:.3f}")
```

In `_on_position`, store `self._last_pos = (x, y, z)` (if not already kept).

Wire the build call: where `build_double_sided` is invoked (`app.py:1138`), pass
`registration=self._registration` and, when fiducial, `fiducials=self._fiducial_spec_from_ui()`.

Fit & export handler:

```python
def _on_fit_and_export_top(self):
    from gerber2rml.doublesided import build_top_traces
    from gerber2rml.engine.fiducial import fit_transform, rms
    import math
    spec = self._fiducial_spec_from_ui()
    lay = self._fiducial_layout()              # layout_double_sided(..., "fiducial", spec)
    from gerber2rml.doublesided import nominal_top_fiducials
    nom = nominal_top_fiducials(lay)
    measured = self._measured_fiducials()      # list[(x, y)] from the rows
    if len(measured) < 2:
        self._status("Need at least 2 measured fiducials.")
        return
    try:
        t = fit_transform(nom[:len(measured)], measured, allow_scale=spec.allow_scale)
    except ValueError as e:
        self._status(f"Fit failed: {e}")
        return
    err = rms(t, nom[:len(measured)], measured)
    build_top_traces(self._folder, self._out_dir, self._job_name,
                     registration="fiducial", fiducials=spec,
                     measured_fiducials=measured, allow_scale=spec.allow_scale,
                     machine=self._machine)
    self._status(f"Top traces exported. RMS {err * 1000:.0f} um, "
                 f"rot {math.degrees(t.theta):.3f} deg, scale {t.scale:.5f}")
```

(Names like `self._status`, `self._folder`, `self._out_dir`, `self._job_name`,
`self._machine`, `self._last_pos` should match the existing app's equivalents —
read the surrounding methods and reuse the real attribute names.)

- [ ] **Step 4: Run the smoke test + full suite**

Run: `python -m pytest tests/test_window.py -k fiducial -q`
Expected: PASS.
Then: `python -m pytest -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/gui/app.py tests/test_window.py
git commit -m "feat(fiducial): GUI mode selector + measure/capture/fit panel"
```

---

### Task 5: Docs — README + dev log

**Files:**
- Modify: `README.md` (double-sided section: mention the two registration modes)
- Create: `docs/2026-06-26-fiducial-registration.md` (dev log, sibling style to
  `docs/2026-06-25-srm20-spi-and-bed-leveling.md`)

**Interfaces:** none (documentation only).

- [ ] **Step 1: Write the dev log**

Document: the two modes, when to pick each, the onboard/waste trade-off, the
through-hole/stock-only depth, the fit model (rigid + optional scale, no shear),
the RMS-as-quality-readout, and the operator flow (build → flip → probe →
capture → fit & export → cut). Note the calibration-free nature vs dowels and
that automated electrical centre-finding is a future firmware add.

- [ ] **Step 2: Update README**

Add a short "Registration: dowel vs fiducial" note to the double-sided section
pointing at the dev log.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/2026-06-26-fiducial-registration.md
git commit -m "docs: fiducial registration mode + dev log"
```

---

## Self-Review

**Spec coverage:**
- Engine `fiducial.py` (Transform/fit/residuals/rms/apply) → Task 1. ✓
- `FiducialSpec` + onboard/waste placement + registration switch + nominal
  top-frame points → Task 2. ✓
- Stock-only fiducial drill, fiducial run plan, transformed top-traces
  re-export → Task 3. ✓
- GUI selector + count/placement/scale + measure/type-in + capture-from-DRO +
  fit&export with RMS → Task 4. ✓
- Error handling (too few/degenerate points raise; <2 measured guarded in GUI)
  → Tasks 1 & 4. ✓
- Tests across engine/layout/build/GUI → each task. ✓
- Docs → Task 5. ✓

**Placeholder scan:** GUI task intentionally says "match the real attribute
names" because `app.py` is 2400 lines and the implementer must read it; all
engine/layout/build code is complete and literal. No TBDs in logic.

**Type consistency:** `fit_transform(nominal, measured, allow_scale)`,
`Transform(theta, scale, tx, ty)`, `apply_to_toolpaths`, `nominal_top_fiducials`,
`FiducialSpec(count, placement, edge_offset, hole_diameter, breakthrough,
allow_scale, margin)`, `build_top_traces(..., measured_fiducials, allow_scale,
registration, fiducials)` — names identical across Tasks 1–4. ✓
