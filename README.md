# gerber2rml

Standalone desktop CAM tool that turns KiCad-exported **Gerber + Excellon** files
into ready-to-run toolpaths for the **Roland SRM-20** desktop mill (RML-1 output).

It replaces the team's reliance on the mods website and FlatCAM with a single
program we own and control: load a board's Gerbers, pick the machine, adjust the
milling variables (bit diameter, cut depth, feeds, offsets, tabs), preview, and
export the `.rml` jobs.

## Status

Early scaffold. The architecture and plan live in
[`docs/design.md`](docs/design.md). The package modules are stubs; the legacy
G-code→RML converter migrated from the team repo is in [`legacy/`](legacy/) as the
starting reference for the SRM-20 backend (it has known bugs, documented in the
design §6).

## What it does (v1)

Single-sided boards, three operations each exported as its own RML job:

1. **Trace isolation** (B.Cu, mirrored for bottom-up milling) — multi-pass.
2. **Drilling** (Excellon holes).
3. **Board cutout** (Edge.Cuts) with holding tabs.

SRM-20 is the only machine today, but output sits behind a pluggable
`MachineBackend` interface so adding another CNC is one new backend.

## Architecture

```
Gerber/Excellon ─► loader (gerbonara→shapely) ─► engine (traces/drill/cutout)
                ─► backend (SRM-20 RML) ─► <board>_{traces,drill,cutout}.rml
```

| Package | Responsibility |
|---|---|
| `gerber2rml/loader.py` | Read Gerber + Excellon → shapely geometry; mirror; unit detect |
| `gerber2rml/engine/traces.py` | Copper → multi-pass isolation toolpaths |
| `gerber2rml/engine/drill.py` | Excellon → grouped peck-drill sequence |
| `gerber2rml/engine/cutout.py` | Edge.Cuts → outline cut + tabs |
| `gerber2rml/backends/base.py` | Abstract `MachineBackend` interface |
| `gerber2rml/backends/srm20.py` | Toolpaths → RML-1 |
| `gerber2rml/config.py` | `Job` / `Tool` dataclasses + SRM-20 defaults |
| `gerber2rml/gui/` | PySide6 window, fields, matplotlib preview, export |

## Install (development)

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Run

```bash
python -m gerber2rml          # launches the GUI (once implemented)
```

## Tests

```bash
pytest
```
