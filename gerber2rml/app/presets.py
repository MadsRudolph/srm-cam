"""Preset load/merge/apply: built-in + site-wide JSON + per-user JSON.

Three layers, lowest to highest precedence:

  1. :data:`BUILTIN_PRESETS` — what we ship in code.
  2. **Site presets** — one file the lab owner controls, read from next to the
     installed ``SRM-CAM.exe``. On a normal install that is under Program
     Files: every student can read it, only an admin can change it. This is how
     a teacher hands the same approved toolpath profile to every seat instead
     of talking thirty people through the numbers. Set ``"_hide_builtins":
     true`` in that file to show ONLY the site profiles.
  3. **User presets** — whatever the person saved themselves.

Set ``SRM_CAM_PRESETS`` to point the site layer somewhere else (tests, or a
shared network folder).
"""
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path

BUILTIN_PRESETS = {
    # The single profile we use: SRM-20 with one 0.8 mm flat endmill for
    # everything — traces, drilling and cut-out — on a ~1.6 mm board. Drill and
    # cut-out depth is 1.7 mm = 0.1 mm through into the spoilboard (not more, so
    # we don't gouge the bed). Set the VPanel spindle to max (~7000 RPM); use a
    # SOLID CARBIDE bit; run dust extraction + a mask for FR-4.
    "SRM-20 0.8 mm flat (no 1/64\" bit): coarse traces + 0.8/1.0 drill + cutout": {
        "trace":  {"bit_diameter": 0.8, "cut_depth": 0.15, "offsets": 1,
                   "stepover": 0.5, "xy_feed": 4.0, "plunge_feed": 1.0, "travel_z": 2.0},
        "drill":  {"bit_diameter": 0.8, "cut_depth": 0.6, "total_depth": 1.7,
                   "xy_feed": 4.0, "plunge_feed": 1.0, "travel_z": 2.0},
        "cutout": {"bit_diameter": 0.8, "cut_depth": 0.6, "total_depth": 1.7,
                   "tabs": 4, "tab_width": 1.5, "xy_feed": 4.0,
                   "plunge_feed": 1.0, "travel_z": 2.0},
    },
    # V-bit (engraving) profile for tight SMD traces. Width-first: the 0.2 mm
    # target width back-solves to a ~0.18 mm plunge on a 30 deg / 0.1 mm-tip bit,
    # so it is HYPER-sensitive to surface flatness — always run it over a dense
    # auto-bed-leveling mesh (see docs/2026-06-30-vbit-engraving-support.md).
    # Drill/cut-out still use the 0.8 mm flat bit (bit change between ops).
    "SRM-20 V-bit 30deg / 0.1 mm tip: 0.2 mm SMD traces (LEVEL FIRST)": {
        "trace":  {"tool_type": "vbit", "tip_diameter": 0.1, "included_angle": 30.0,
                   "target_width": 0.2, "offsets": 1, "stepover": 0.5,
                   "xy_feed": 3.0, "plunge_feed": 0.5, "travel_z": 2.0},
        "drill":  {"bit_diameter": 0.8, "cut_depth": 0.6, "total_depth": 1.7,
                   "xy_feed": 4.0, "plunge_feed": 1.0, "travel_z": 2.0},
        "cutout": {"bit_diameter": 0.8, "cut_depth": 0.6, "total_depth": 1.7,
                   "tabs": 4, "tab_width": 1.5, "xy_feed": 4.0,
                   "plunge_feed": 1.0, "travel_z": 2.0},
    },
}


def _user_path():
    return Path.home() / ".gerber2rml" / "presets.json"


def _site_path():
    """The machine-wide presets file.

    Frozen install: beside the executable, i.e. ``presets.json`` in the
    install folder under Program Files. Resolving it from ``__file__``
    instead — as this used to — lands inside the bundled ``_internal``
    folder, where nothing is shipped and nobody can sensibly drop a file,
    so site presets never reached an installed app at all.

    Source checkout: ``examples/presets.json``.
    """
    env = os.environ.get("SRM_CAM_PRESETS")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "presets.json"
    return Path(__file__).resolve().parents[2] / "examples" / "presets.json"


_repo_path = _site_path          # pre-0.2.8 name, kept for any external caller


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _profiles(raw):
    """Drop the settings keys. JSON has no comments, so a leading underscore
    is how this format carries anything that is not a toolpath profile —
    ``_hide_builtins``, and any ``_comment`` someone left for the next person."""
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def load_presets():
    site = _read_json(_site_path())
    # A lab that wants students to see exactly one approved profile sets this.
    hide_builtins = bool(site.get("_hide_builtins", False))
    merged = {} if hide_builtins else dict(BUILTIN_PRESETS)
    merged.update(_profiles(site))
    merged.update(_profiles(_read_json(_user_path())))   # user overrides by name
    if not merged:                            # never hand back an empty list
        merged = dict(BUILTIN_PRESETS)
    return merged


def apply_preset(state, preset):
    """A profile is the whole set of numbers, not a delta on the last one.

    Merging onto the current jobs kept whatever the profile did not name -
    the V-bit profile's ``tool_type`` above all - so applying the flat profile
    after it produced a job isolated for a 0.2 mm V-bit and cut with a 0.8 mm
    endmill. Every job starts from its defaults: a profile that names a field
    sets it, one that does not gets the default, and a field this version
    does not know is dropped rather than refused.
    """
    from dataclasses import fields
    from gerber2rml.config import TraceJob, DrillJob, CutoutJob

    def build(cls, block):
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (block or {}).items() if k in known})

    state.trace = build(TraceJob, preset.get("trace"))
    state.drill = build(DrillJob, preset.get("drill"))
    state.cutout = build(CutoutJob, preset.get("cutout"))


def save_user_preset(name, state):
    path = _user_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_json(path)
    data[name] = {"trace": asdict(state.trace), "drill": asdict(state.drill),
                  "cutout": asdict(state.cutout)}
    path.write_text(json.dumps(data, indent=2))
