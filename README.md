# SRM-CAM

[![tests](https://github.com/MadsRudolph/srm-cam/actions/workflows/tests.yml/badge.svg)](https://github.com/MadsRudolph/srm-cam/actions/workflows/tests.yml)
[![build installer](https://github.com/MadsRudolph/srm-cam/actions/workflows/build.yml/badge.svg)](https://github.com/MadsRudolph/srm-cam/actions/workflows/build.yml)

Desktop CAM for the **Roland SRM-20** mill: load KiCad **Gerber + Excellon**,
preview the toolpaths, and export **G-code** (`.nc`) or RML. One tool we own,
replacing the mods site and FlatCAM.

> Python package name: `gerber2rml`.

**📖 User guide: [madsrudolph.github.io/srm-cam](https://madsrudolph.github.io/srm-cam/)**

![SRM-CAM main window](docs/Readme_photos/srmcam_GUI_MainPage.png)

## Install

**Just run it (Windows):** download the latest installer from
[Releases](https://github.com/MadsRudolph/srm-cam/releases) and run
`SRM-CAM-Setup-*.exe`. No Python needed.

**From source:**

```bash
pip install -e ".[gui]"
python -m gerber2rml                                          # GUI
python -m gerber2rml.cli <gerber-folder> -o out -n <board>   # headless CLI
```

After a `git pull`, `python -m gerber2rml.doctor` installs any new dependencies.

## What it does

- **Traces / drill / cut-out** from Gerber + Excellon, exported per operation.
- **G-code default** (`.nc`, G54 origin) for VPanel NC mode; RML available.
- **Double-sided** registration — dowel pins or measured fiducials.
- **Bed leveling** — probe a height map so depth follows an uneven surface.
- **Rework** — mark several spots, re-cut them in one pass at per-region depth.
- **3D views** — toolpath simulation + bed height-map.
- **Guided tour** — launches on first run; replay via the **Guide** button (and
  per-section buttons). A demo board loads so new users can follow along.

## Two modes

**Novice** (the default on a fresh install) is the shortest path from Gerbers to
three files you can send from VPanel — load, drill, traces, cut out, export. Job
parameters, double-sided, bed leveling, rework and the machine link are put
away; Diagnostics and the Guide stay, because a beginner needs those most.

**Professional** is every control.

Novice is a strict subset, not a second program — the same settings export
byte-identical files in either mode. Switch from the **Mode** menu; set
`SRM_CAM_MODE=novice|pro` to pin a machine to one.

A course hands the same approved feeds and depths to every seat with a **site
preset**: `presets.json` next to the installed `SRM-CAM.exe`, which lives in
Program Files so only an admin can change it. See
[`docs/usage.md`](docs/usage.md#presets).

## Showcase

<table>
<tr>
<td width="50%"><img src="docs/Readme_photos/srmcam_3dview_traces.png" alt="3D toolpath simulation"><br><sub><b>3D toolpath simulation</b> — orbit and play back the whole job before cutting.</sub></td>
<td width="50%"><img src="docs/Readme_photos/srmcam_BedLeveling_3DView.png" alt="3D bed height-map"><br><sub><b>Bed height-map</b> — probe the surface so the cut depth follows the board.</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/Readme_photos/srmcam_doublesided.png" alt="Double-sided registration"><br><sub><b>Double-sided</b> — dowel-pin or measured-fiducial registration for the flip.</sub></td>
<td width="50%"><img src="docs/Readme_photos/rework_example.png" alt="Multi-region rework"><br><sub><b>Rework</b> — box every spot to re-cut, each with its own depth, in one pass.</sub></td>
</tr>
</table>

You can also do **perfect double-sided PCBs** with srm-cam — both layers registered off dowel pins or fiducials. A finished board, held to the light:

<table>
<tr>
<td width="50%"><img src="docs/Readme_photos/doublesided_bcu.jpg" alt="Bottom copper (B.Cu)"><br><sub><b>Bottom — B.Cu</b></sub></td>
<td width="50%"><img src="docs/Readme_photos/doublesided_fcu.jpg" alt="Top copper (F.Cu)"><br><sub><b>Top — F.Cu</b></sub></td>
</tr>
</table>

## More

- **Step-by-step guide (KiCad → milled board), with photos:** [DTU Ballerup PCB prototyping — Roland CNC router](https://github.com/DTU-EKB/DTU-PCB-prototyping#making-pcbs-with-the-roland-cnc-router)
- Full usage & feature reference: [`docs/usage.md`](docs/usage.md)
- Build the installer / cut a release: [`packaging/README.md`](packaging/README.md)
- Bed-leveling probe firmware (Arduino UNO): [`hardware/srm20_spi_probe/`](hardware/srm20_spi_probe) — flash it before using auto bed leveling (wiring in [`docs/usage.md`](docs/usage.md#bed-leveling)).
- Run the tests: `pytest`

## Keeping it running

The installed app does **not** use the machine's Python — PyInstaller freezes
its own interpreter, Qt and every dependency into `_internal\`. Installing,
upgrading or removing Python on the PC cannot affect it.

What is maintained deliberately:

| | |
|---|---|
| **Reproducible builds** | `packaging/requirements-lock.txt` pins every version, including transitives, to the set the shipped installer was built from. |
| **Builds on any machine** | Pushing a `v*` tag builds the installer from scratch on a clean GitHub Windows runner and drafts a release. No one person's laptop is in the loop. |
| **Nothing silently changes** | `tests/test_golden.py` asserts a fixed board still produces byte-identical `.nc` output, so a dependency upgrade cannot quietly alter what gets cut. |
| **Early warning** | A monthly `canary` CI job runs the suite against the newest Python and newest dependencies. When the world moves, it goes red before anyone is mid-course. |

Handover notes: [`HANDOFF.md`](HANDOFF.md).
