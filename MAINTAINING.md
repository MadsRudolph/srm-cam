# Maintaining SRM-CAM

For whoever owns this next — quite possibly someone who has never met the people
who wrote it. That is the situation this document is written for.

SRM-CAM is the CAM tool the DTU Ballerup lab uses to mill PCBs on the Roland
SRM-20. Students load KiCad Gerbers and get `.nc` files they send from VPanel.
It is MIT-licensed, written in Python, and ships as a self-contained Windows
installer.

**If you read one section, read [When it breaks](#when-it-breaks).**

---

## The honest risk assessment

The code is in good shape and defended by CI. The thing most likely to strand
this project is not a bug — it is **ownership**.

| Risk | Real? | What protects you |
|---|---|---|
| A Windows update breaks the app | **Low.** The installer carries its own Python, Qt and every dependency in `_internal\`. Installing, upgrading or removing Python on the PC cannot affect it. | PyInstaller freeze |
| A dependency upgrade silently changes what gets cut | **Low.** | `tests/test_golden.py` — byte-identical `.nc` for a fixed board |
| A future Python or Qt release breaks the build | **Medium, but you get warning.** | The monthly `canary` CI job |
| You cannot rebuild the installer because the original author's laptop is gone | **Low.** | `build.yml` builds from scratch on a clean GitHub runner |
| **The GitHub account hosting all of this disappears** | **This is the one.** | See below — needs a human decision, not code |

### The account problem, stated plainly

At the time of writing, the repository, the releases, the documentation site and
the CI all live under one **personal** GitHub account. Three things break the
day that account goes away:

1. The download link baked into the DTU-EKB PCB-prototyping guide
   (`releases/latest/download/SRM-CAM-Setup.exe`) 404s.
2. The user guide at `madsrudolph.github.io/srm-cam` goes offline.
3. The canary job's "this will break soon" warnings stop reaching anyone,
   because they were going to that account's inbox.

**None of this is hypothetical — students graduate.** The fix is organisational:

- [ ] **Transfer the repository to the `DTU-EKB` organisation**, which already
      hosts the PCB-prototyping guide. Needs an org owner to accept. GitHub
      redirects the old URLs afterwards, so nothing breaks on the day — but
      update the links in `README.md`, `website/*.html` and
      `packaging/README.md` anyway, because redirects stop working the moment
      anyone registers a repo at the old name.
- [ ] **Keep at least two people with push rights**, at all times, one of whom
      is staff rather than a student.
- [ ] **Point the canary somewhere institutional.** GitHub emails the repo
      owner; under an org, set watchers who are not one graduating student.
- [ ] **Keep a cold copy on lab storage** — the installer, a source archive and
      the wheelhouse (see [Cold start](#cold-start-no-github-at-all)). One
      folder on a lab drive means the lab is never one deleted account away from
      losing its PCB toolchain.

---

## Five-minute orientation

```
gerber2rml/          the Python package (the app; the name predates "SRM-CAM")
  loader.py            Gerber + Excellon -> shapely geometry
  engine/              traces, drill, cutout, leveling, rework, diagnostics
  backends/            toolpaths -> G-code (.nc) or RML
  gui/                 PySide6 window; app.py is the big one
hardware/            Arduino sketches for the optional SPI probe
packaging/           how the .exe is built            -> packaging/README.md
website/             the user guide (plain HTML, auto-published to Pages)
docs/                design notes and dev logs, dated
tests/               492 tests; pytest
```

Run it from source:

```bash
pip install -e ".[gui,dev]"
python -m gerber2rml            # GUI
pytest                          # the suite
```

After a `git pull`, `python -m gerber2rml.doctor` installs anything new.

Build the installer, cut a release: **[`packaging/README.md`](packaging/README.md)**
— that document is complete and current; this one does not duplicate it.

---

## What the CI actually protects

Three workflows, each with a distinct job. Do not delete one because it looks
redundant.

| Workflow | Runs when | If it goes red |
|---|---|---|
| `tests.yml` → **locked** | every push and PR | **Stop.** This is the suite against the exact pinned versions we ship. Red here means the app we ship is broken. |
| `tests.yml` → **canary** | 06:00 UTC on the 1st of each month | **Do not panic, do not ignore.** The world moved: a newer Python or dependency broke us. Nothing is shipping broken *yet* — this is the early warning. Read [When it breaks](#when-it-breaks). |
| `build.yml` | on a `v*` tag, or manually | The installer cannot be built. Blocks releasing, not using. |
| `pages.yml` | on pushes touching `website/` | The user guide is stale. Cosmetic. |

The split between **locked** and **canary** is the whole point: what we ship is
frozen and tested, while a separate job asks "will this still build in a few
years?" and answers *before* the answer matters.

---

## When it breaks

### The canary went red on the 1st of the month

This is the system working as designed. Nobody is blocked; the shipped installer
is unaffected.

1. Open the failed run and read **"Record the versions this ran against"** — it
   prints `pip freeze`, so you can see exactly which package moved.
2. Reproduce locally against the newest everything:
   `pip install -e ".[gui,dev]"` in a scratch venv, then `pytest`.
3. Fix the code, or pin around the offender.
4. When it is fixed, regenerate the lock and rebuild:
   `packaging\build.ps1 -Recreate -Loose`, re-freeze `requirements-lock.txt`,
   run the suite, cut a release.

There is no deadline. The lock file means you can leave it red for a term and
students are unaffected — but do not leave it red for a *year*, because the fix
gets harder the further behind you fall.

### A student says "the installer won't run"

Almost always **SmartScreen**, not a bug. The installer is unsigned, so Windows
shows *"Windows protected your PC"* on first run — indistinguishable from
"broken" to a first-year student.

- Tell them: **More info → Run anyway**.
- If they want to verify the file first, every release ships `SHA256SUMS.txt`;
  `Get-FileHash <file> -Algorithm SHA256` should match.
- The permanent fix is a code-signing certificate. It costs money annually and
  needs an institutional owner — a reasonable thing to ask the lab for, not
  something a student can do.

### The app won't start after an install

`console=False` hides the traceback. Rebuild with it `True`
(`packaging/srm-cam.spec`), `build.ps1 -SkipInstaller`, and run
`dist\SRM-CAM\SRM-CAM.exe` from a terminal to see the error.

### A golden test fails

`tests/test_golden.py` asserts a fixed board still exports byte-identical
`.nc`. **A failure here means the toolpaths changed.** If you did not intend
that, you have found a real regression. If you did intend it, look at the diff
carefully, confirm it on a scrap board before regenerating the fixtures, and say
so in the commit message. This test exists so a dependency bump cannot quietly
alter what gets cut into copper.

---

## Cold start (no GitHub at all)

Rebuilding the installer from nothing but a source archive:

1. A Windows PC, **Python 3.12** (standalone CPython, not conda), and
   **Inno Setup 6** (`winget install --id JRSoftware.InnoSetup -e`).
2. `powershell -ExecutionPolicy Bypass -File packaging\build.ps1`
3. Output: `dist_installer\SRM-CAM-Setup-<version>.exe`.

That is the whole procedure. `build.ps1` creates its own venv from
`requirements-lock.txt`, so nothing depends on the state of the machine.

**The one remaining dependency is PyPI.** To remove it, archive a wheelhouse
next to the source:

```bash
pip download -r packaging/requirements-lock.txt -d wheelhouse
```

Then the offline build is the same command with `--no-index --find-links
wheelhouse`. Refresh it whenever the lock changes. A source archive plus a
wheelhouse plus the two prerequisites above is a genuinely self-contained
recovery kit — keep one on lab storage.

---

## Things not to change without understanding why

- **`AppId` in `packaging/installer.iss`** — a fixed GUID. Change it and
  upgrades install side-by-side instead of replacing.
- **The version-less `SRM-CAM-Setup.exe` release asset** — the DTU-EKB guide
  links to `releases/latest/download/SRM-CAM-Setup.exe`. That URL only resolves
  while every release carries an asset with exactly that name.
- **The three version files** — `pyproject.toml`, `packaging/installer.iss`,
  `gerber2rml/__init__.py` must agree. `scripts/check_version.py` enforces it in
  CI; run it before tagging.
- **The golden fixtures** — see above.
- **`kicad-plugin/VERSION`** — bump it whenever the plugin changes, or installed
  copies are never recognised as stale and students keep running the old one.
  `BED_X, BED_Y` in `kicad-plugin/srm20area/geometry.py` must stay equal to
  `gerber2rml.backends.SRM20_BED`; `tests/test_kicadplugin.py` enforces it,
  because a drift would have KiCad telling a student their board fits while
  SRM-CAM refuses to cut it.
- **Novice mode as a strict subset** — Novice hides controls, it does not take a
  different code path. `tests/test_mode.py` asserts both modes export identical
  bytes. Keep it that way: the moment there are two code paths, a student's board
  and a teacher's board can differ.

---

## The Arduino is optional

The Arduino on the SRM-20's SPI remote header buys *automatic* probing, a live
position readout and click-to-jog. **It is the only thing that needs it.**
Traces, drilling, cut-out, double-sided registration, rework and every export run
on a stock machine through VPanel, and Novice mode hides the machine link
entirely. Bed leveling still works without it, manually — see
[Milling without the Arduino](docs/usage.md#milling-without-the-arduino).

If the board is ever removed, nothing in this repository needs to change.
