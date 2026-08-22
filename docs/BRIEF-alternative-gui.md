# BRIEF — build a second, independent GUI for SRM-CAM

**For:** a fresh Claude Code session. **Written:** 2026-08-22, against `main` @ `f8c3bb6` (v0.4.0).
**Deliverable:** a complete alternative interface, running side by side with the existing one, so a human can A/B them and pick.

This is **not** a reskin, a theme swap, or a tidy-up of `gerber2rml/gui/`. That interface stays exactly where it is and keeps working. You are building a second one, from scratch, that answers the same problem differently — different information architecture, different interaction model, different visual language.

The goal behind it: **this program is going to be shown to a university with a view to them adopting it.** It has to read as a piece of professional instrument software, not as something assembled over a weekend. Getting that right is the whole job.

---

## 1. What the program actually is

SRM-CAM turns KiCad Gerber files into machine files for a **Roland SRM-20 desktop mill**, and — with an Arduino on the machine's SPI header — drives the mill directly. A student loads their PCB export, checks it, and gets `.nc` files plus a run plan telling them what order to send them in and which cutting tool each one needs.

Three things make it more than a file converter, and any interface has to carry all three:

1. **It drives a machine.** Spindle on/off, jog, pause, stop, probing, live position. Motion happens because of what someone clicked.
2. **Mistakes are physical.** A wrong depth is a hole in the spoilboard. A wrong order frees the board from its own registration and scraps it. A short between two nets is a board that cannot work.
3. **The users are split.** Most are students who have never used CAM and will use it twice. A few are doing double-sided boards with probed height maps and need every control. The current app handles this with a Novice/Professional mode flag.

Read [`docs/usage.md`](usage.md) end to end before you design anything. Then load the app and use it — `python -m gerber2rml` from the repo root. You cannot redesign a workflow you have not performed.

---

## 2. The seam: what you build on, and what you replace

The codebase is already split the right way. This is the single most important structural fact in this brief.

| | Lines | Status |
|---|---|---|
| `gerber2rml/engine/`, `backends/`, `app/`, `cli.py`, `doublesided.py`, `config.py` | ~4,965 | **Do not touch.** This is the product. |
| `gerber2rml/gui/` | ~10,928 (`app.py` alone is 6,496) | What you are writing an alternative to. **Leave it working.** |

The dependency is one-way — nothing in `engine/` imports from `gui/`, with a single leak worth knowing about: `engine/toolwear.py:32` reaches into `gui.workspace` for a directory path. Do not add more of those.

**Your API is `gerber2rml/app/state.py`.** `ProjectState` holds the whole job — the three operation configs (`trace`, `drill`, `cutout`), the loaded board, placement, rotation — and exposes `load(folder)`, `set_placement`, `set_rotation`, `toolpaths(op)` and `export(out_dir, level=)`. Read it first; it is 86 lines and it is the contract.

Everything else you need is a plain function call:

- `gerber2rml.cli.build_jobs(...)` — single-sided export, writes the files and the run plan
- `gerber2rml.doublesided.build_double_sided(...)` — the double-sided path
- `gerber2rml.engine.diagnostics.preflight(...)` — the pre-flight checks, returns `Check(level, title, detail)`
- `gerber2rml.engine.drc.isolation_bridges(...)` — nets the cutter cannot separate
- `gerber2rml.engine.spi_probe` / `spi_stream` — the machine link
- `gerber2rml.engine.estimate` — run-time estimates

### Where to put it

Create **`gerber2rml/gui2/`** as a sibling package with its own `main()`, and add a second entry point in `pyproject.toml` under `[project.gui-scripts]` (the existing one is `gerber2rml = "gerber2rml.gui.app:main"`). Both interfaces must be launchable from the same install, against the same engine, at the same time. That is what makes the A/B honest.

Do not rename, move, or "clean up" anything in `gerber2rml/gui/` — the moment you do, the comparison stops being between two finished things.

---

## 3. Non-negotiables

These are not style preferences. Every one of them is either a safety property or a fact about the machine, most of them learned the hard way and several fixed in the last week. **A redesign that loses one of these is a regression, however good it looks.**

### Machine safety

- **Bed leveling drives the machine.** It steps Z down onto the copper repeatedly. Any mode or view that can start it **must** have a visible, always-enabled stop control. The current app removed guided leveling from Novice for exactly this reason — Novice hides the machine dock, and the STOP button was in it.
- **A dry run comes first.** Every single-sided export writes `<name>_airpass.nc` — spindle off, bit held 5 mm up, tracing the outline. It is step 0 of the run plan and the cheapest board-saving check in the product. Do not bury it.
- **The cut-out runs last**, and on a double-sided job it runs *after* the flip and the top traces. Cutting the outline early frees the board from the dowels it is registered on.
- **Irreversible actions must look different from safe ones.** Wet run, Clear Z, Clear all.

### Machine truths that constrain the UI

- **The spindle speed is NOT settable over the link.** `turnSpindle`'s RPM argument is ignored by this machine — 500, 1000, 2000 and 3000 all settle on whatever VPanel's slider says. The link gives you `M3`/`M5`, nothing more. Never build UI implying otherwise. ([`docs/2026-08-21-spi-command-audit.md`](2026-08-21-spi-command-audit.md))
- **Streaming a job over SPI is EXPERIMENTAL** and gated on uncalibrated speed units. The normal path is export → VPanel. Do not promote streaming to the happy path.
- **Only one status bit is proven** (`0x20000`, cover/lid). The bit Roland labels "paused" demonstrably does not mean paused here. Do not display an unproven bit as a machine state.
- **XY work origin stays at the machine origin; only Z is zeroed.** The screw-fixture file is emitted in machine coordinates and depends on this.

### Workflow truths

- **One order, stated once.** The app used to describe the machining order in three places that disagreed. Whatever navigation you invent must agree with the run plan the engine writes (`cli.py` for single-sided, `doublesided.py` for double-sided) — or better, be generated from it.
- **The run plan is the best artifact the program produces.** Order, bit per step, when to re-zero Z, what the dry run is for. It must reach the user, not sit in a `.txt` beside four `.nc` files.
- **A board that will short must say so before export**, not in a status line that expires.
- **Novice output is byte-identical to Professional output.** Whatever two-tier scheme you invent, keep that property — there must be no second code path that can drift.

---

## 4. What "state-of-the-art, not AI-generated" means here

The current interface is competent and unremarkable. The reason it reads as unremarkable is worth understanding, because it is what you have to beat.

**The tells to avoid:**

- **A type scale of one.** The current app's entire UI lives between 11 px and 14 px — no headings, hierarchy attempted with four font weights inside a 4 px range. Real applications have a range.
- **Generic layout.** Left nav, centre form, right preview, three stacked bars at the bottom. Correct, and it could be any Qt app ever written.
- **Decoration standing in for hierarchy.** Rounded corners and a cyan accent applied evenly to everything, so nothing is emphasised.
- **Undesigned states.** The empty state, the error state, the "connecting" state, the "nothing selected" state. These are where amateur software gives itself away — it designs the happy path and lets the rest happen.
- **Vocabulary from the codebase.** Labels like `xy feed`, `travel z`, `clr L`, `drift chk 6`, `Probe over SPI`. Users do not have your variable names.
- **Emoji as iconography.** Instant tell.
- **Everything visible at once**, because deciding what is secondary is harder than showing it all.

**What credible instrument software does instead** — look at Bantam Tools, Fusion 360's CAM workspace, Prusa/Bambu slicers, Carbide Create, KiCad 8+, LinearMotion/Onshape:

- One dominant object on screen (the work), everything else subordinate to it
- A real typographic scale, and restraint about weight
- Colour that means something, used sparingly, so that when something goes red you look
- Progressive disclosure — the depth is *reachable*, not *present*
- States that are designed: empty, loading, error, success, disconnected
- Domain vocabulary, consistently, with the jargon explained where it first appears
- Density that suits the task — a machine-control panel and a settings form want different densities
- Motion used to explain a change of state, never as decoration

**The user will supply one or more `skills.md` files carrying a specific design system or method. Load and follow them — they take precedence over the generic advice in this section.** Ask for them if they have not arrived before you start visual design.

---

## 5. What the current GUI gets wrong (do not inherit these)

From an independent design critique run on 2026-08-22. Scores were: hierarchy 4/10, layout 4/10, typography 3/10, colour 3/10, copy 6/10, states 4/10, consistency 4/10, craft 5/10.

- **Four places select the operation**, two of them nested tab bars with identical labels, which can disagree with each other.
- **The settings panel resizes itself** from 513 px to 1032 px as you walk the run plan, and overwrites any splitter position the user set.
- **Two equal-weight primary buttons** side by side offering the first and last step of the workflow.
- **26 error dialogs whose entire body is `str(e)`** — "Load failed: list index out of range".
- **The 3D viewer, photo overlay, rework boxes and machine test** are all separate windows/dialogs with no shared visual language.
- **No File menu until 0.4.0**; two keyboard shortcuts in the whole application.
- **Steps 3 and 7 of the run plan are the same screen.**

Full critique context lives in this brief's companion sections; the fixes already applied are in the git log from `38626a1` onward.

## 6. What it gets right (do not throw these away)

Being specific, because these represent real thinking and a rewrite tends to lose them:

- **The run-plan spine.** Naming sidebar steps in machining order and routing each to the page/operation/side it needs, while keeping every step clickable — *"it's a map, not a gate"*. Better information architecture than the tab soup most CAM tools ship.
- **`mode.py`'s reasoning.** Hidden-not-disabled, Novice as a strict subset so the modes cannot drift, Novice as the default *because* it is for the person who has never opened the app. Read this file even if you keep none of its code.
- **The tooltips.** ~98 of them, and they are explanations rather than label restatements — several pre-empt the exact misconception the control could cause.
- **The safety copy.** The stream dialog tells you the move count, what a dry run guarantees mechanically, what a wet run needs from you first, and that the speed units are uncalibrated. Nobody who reads it can be surprised.
- **The machine-test panel** — a Risk column, separate arming for motion and spindle, PASS/FAIL/UNKNOWN backed by the *word* and not just a colour, and a Copy report button.
- **The code comments.** Most non-obvious decisions carry the reason and often the incident that caused them.

---

## 7. How the A/B actually gets run

The comparison is worthless if one side is a mockup. Build to the same standard:

1. **Both launch from the same install.** `gerber2rml` (current) and a second entry point (yours).
2. **Both do the whole single-sided job end to end** — load, place, inspect, diagnose, export — against `tests/fixtures/mosfet_test`. That is the minimum for a fair comparison.
3. **Both handle the states**, not just the happy path: no board loaded, a board with 13 guaranteed shorts (the bundled demo has 39), no machine connected, an export that fails.
4. **Write `docs/AB-<yourname>.md`** — what you changed and why, with screenshots of both at 1400×900 and at 1280×720, so the difference can be judged rather than argued about.
5. **Tests.** The engine has 755 passing tests; keep them passing. Add offscreen tests for your GUI in the style of `tests/test_window.py` (`QT_QPA_PLATFORM=offscreen`, `SRM_CAM_HOME` to a temp dir — see `tests/conftest.py`).

### Environment

```bash
# from the repo root
python -m gerber2rml.doctor    # installs GUI deps into the venv
python -m pytest -q            # 755 pass, 2 skip
python -m gerber2rml           # the current GUI
```

Stack is **PySide6 + matplotlib + pyqtgraph**. You are not required to keep matplotlib for the preview — a custom `QGraphicsView`/`QPainter` canvas or a QML front end are both legitimate answers, and would help make this *visibly* a different program. If you change the stack, add the dependency to `pyproject.toml`'s `gui` extra and say so in your A/B write-up.

There is a desktop shortcut on this machine, **SRM-CAM (dev)**, running `pythonw -m gerber2rml` from the working tree.

### Two local gotchas that will waste your afternoon

- Verifying "did the window open?" via Windows API enumeration gives a **false negative** — check in-process with `w.isVisible()` / `w.winId()` instead.
- `pythonw` has no console, so a startup traceback vanishes. Redirect `sys.stdout`/`sys.stderr` to a file before importing anything.

---

## 8. Definition of done

- A second GUI, launchable alongside the first, doing the full single-sided workflow against the real engine.
- Every non-negotiable in §3 demonstrably intact.
- Empty / error / disconnected / success states designed, not incidental.
- No raw colour literals — the existing GUI routes everything through `gerber2rml/gui/theme.py` and `tests/test_theme.py` enforces it. Do the same for yours.
- `docs/AB-<yourname>.md` with side-by-side screenshots.
- The existing GUI untouched and still passing its tests.

**Start by using the current app for twenty minutes on the bundled demo board.** Everything above will make more sense, and you will find things this brief missed.
