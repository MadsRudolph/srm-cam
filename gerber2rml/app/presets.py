"""Preset load/merge/apply: built-in + repo examples/presets.json + user JSON."""
import json
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
