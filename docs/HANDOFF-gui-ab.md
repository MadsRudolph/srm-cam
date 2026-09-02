# HANDOFF — deciding between the two interfaces

> ## DECIDED, 2026-09-02: the setup sheet.
>
> **SRM-CAM is `gui2` now.** An installed copy — AppImage, Windows installer —
> opens the setup sheet with no arguments. The original interface is still
> built and still shipped, behind `--original` and its own desktop entry and
> Start-menu shortcut, because a migration is not a deletion and people are
> mid-job in it.
>
> Everything below this box was written while the question was open. It is
> kept because the *reasoning* is still the record of why — what each
> interface does better, what the alternative had not proven, and §2.5 / §2.7
> on the machine link, which any future work on that link still has to answer.
> Read it as history, not as an open question. Where it says "nothing has been
> decided", something has.

**For:** a Claude Code session on the CNC PC, at the machine.
**Branch:** `feat/setup-sheet-gui`. **Written:** 2026-08-23.

There are now two complete interfaces over the same engine, and the job is to
decide which one the lab keeps. Both are on this branch, both launch from the
same install, both drive the same `ProjectState` and write the same files.

```bash
# from the repo root
python -m gerber2rml.gui2     # the setup sheet — what SRM-CAM now opens
python -m gerber2rml          # the original interface
```

Nothing has been decided. The alternative is not a replacement until someone
runs a real board through both and says so.

---

## 0 · Two things that will waste your afternoon

**Use the right interpreter.** On the CNC PC the `python` on PATH may be the
Windows Store build (3.11), which has no PySide6 and no gerbonara — the failure
is a `ModuleNotFoundError` that looks like a broken checkout. The project runs
on miniconda:

```bash
C:\Users\Mads2\miniconda3\python.exe -m gerber2rml.gui2
```

Check with `python -c "import PySide6"` before believing anything is wrong.
`python -m gerber2rml.doctor` installs the interface dependencies into whichever
interpreter runs it.

**`pythonw` has no console.** A startup traceback vanishes. The alternative
interface redirects `stdout`/`stderr` to `Documents/SRM-CAM/gui2.log` before it
imports anything, so read that file first when a launch does nothing.

Also: verifying "did the window open?" by enumerating Windows API top-level
windows gives a **false negative** from some shells. Check in-process with
`w.isVisible()` / `w.winId()` instead.

---

## 1 · What is on this branch

| | |
|---|---|
| `gerber2rml/gui/` | the original interface, untouched in design, with two bug fixes merged in from `main` |
| `gerber2rml/gui2/` | the alternative, 20 modules |
| `docs/AB-setup-sheet.md` | the full write-up: what changed, why, and screenshots of both at 1400×900 and 1280×720 |
| `docs/BRIEF-alternative-gui.md` | the brief the alternative was built against — read §3, the non-negotiables |

`main` carries only the two bug fixes (commit `734e001`); the alternative
interface exists on this branch alone. Tests: **878 pass, 2 skip.**

### The two fixes that are on `main` as well

Both were found while building the alternative and belong to the product, not
to either interface:

* **The travel layer had never drawn anything.** Every toolpath generator emits
  one path per contour, each beginning with a rapid to its own start point, so
  the only rapid *runs* inside a path are the plunge and the retract — both at
  a single XY. `toolpath_segments` therefore returned rapid polylines that were
  one point, or two identical points. 50 empty polylines on the demo board.
  `app.preview.traverse_segments` synthesises the real hops; both interfaces
  now draw them.
* **Centre on bed.** One button that puts the whole job in the middle of the
  machine's travel with the spare room shared equally, counting the dowel pins
  on a double-sided board. Both interfaces have it.

---

## 2 · What actually needs a machine, and has never been tested on one

Everything below was written against the hardware's documented behaviour and
exercised offscreen. **None of it has been run against the mill.** This is the
most valuable thing this session can do.

Work through it with the lid closed and **no tool in the collet** unless a step
says otherwise.

1. **Connect.** The port list ranks likely Arduinos first but filters nothing.
   On a recent check this PC showed `COM1/COM3/COM4` all as "unknown device",
   which usually means the board is not plugged in — the lab's Uno is a CH340
   and should be labelled as one. Fix the lead before blaming the app.
2. **The DRO.** Position should update ~3×/second and the chip should go blue.
   Watch for the canvas going sluggish — the position poll used to force a full
   re-stroke of the toolpath and that was fixed by caching; if it feels slow on
   a big board, that cache has regressed.
3. **The lid.** Open and close it while connected. The status chip must follow.
   This is the **only** status bit proven on this machine; if it does not
   follow, nothing else in the status word can be trusted either.
4. **STOP, and Escape.** Both must stop the machine from anywhere, including
   with a dialog focused. Escape is bound application-wide.
5. **Bed levelling, and stopping it mid-run.** Build a 3×3 grid, start
   *Probe over the link*, and press STOP part-way. The tool must lift and the
   points already measured must be kept. This is the single most important
   safety behaviour to confirm, because the probe run owns the serial port and
   STOP reaches it through a shared abort flag rather than through the port.
6. **Z jog and Zero Z here.** Jogging down must be refused while the probe says
   the bit is touching copper; jogging up must always work.
7. **Spindle on/off.** There is deliberately no speed control — this machine
   ignores the RPM argument. Confirm the button follows a spindle started from
   VPanel, and that disconnecting does **not** stop a spindle the app did not
   start.

Then a real board, end to end: load → centre on bed → check → export → send the
files from VPanel in the order the run plan gives.

---

## 3 · The question you are answering

Not "which looks nicer". The alternative was built to a brief with specific
claims; the useful session is one that tests them on a real job.

* Can a student who has never used CAM get from Gerbers to files they can send,
  without help, in each one?
* When the board has shorts, does each interface make that unmissable before
  anything is written?
* Standing at the machine with a bit in your hand: which one tells you what to
  run next, with which tool, without opening a text file?
* Is one dominant object on screen better than a settings form, or is the form
  faster once you know it?
* What does the alternative make *harder*? It is not a superset — see §8 of
  `docs/AB-setup-sheet.md` for what it does not do (no guided tour, no 3D
  viewer, no photo overlay, no machine-test panel, no feed card).

Write findings into `docs/AB-setup-sheet.md` under a new "On the machine"
section, with the board and the date. A decision made from one real run is
worth more than any amount of screenshot comparison.

---

## 4 · Ground rules that do not change

From `docs/BRIEF-alternative-gui.md` §3, and they apply to whichever interface
survives:

* the dry run is step 0 and the cut-out runs **last** — on a double-sided job,
  after the flip and the top traces;
* **XY origin is set once and never re-zeroed**; only Z is;
* the spindle speed is not settable over the link, and nothing may imply it is;
* streaming a job over SPI is experimental and gated on uncalibrated speed
  units — the normal path is export → VPanel;
* only the cover/lid status bit is proven; no other bit may be shown as a
  machine state;
* whatever two-tier scheme exists, the simple tier's output must stay
  byte-identical to the full tier's.

`tests/test_gui2_window.py` and `tests/test_gui2_tier.py` assert most of these
for the alternative. Keep them passing.

---

## 5 · If you change code

```bash
C:\Users\Mads2\miniconda3\python.exe -m pytest -q     # 878 pass, 2 skip
```

* The alternative routes every colour through `gerber2rml/gui2/theme.py` and
  `tests/test_gui2_theme.py` enforces it — no hex literals anywhere else.
* Every failure goes through `gui2.dialogs.report_error`, which needs a
  headline, guidance, and only then the exception. A test asserts no bare
  `QMessageBox` exists in the package.
* The run order lives in `gui2/runplan.py` and is checked against the files the
  engine actually writes. Add a file to `cli.build_jobs` and the test fails.
* Commit messages read like a developer wrote them. No AI attribution.
