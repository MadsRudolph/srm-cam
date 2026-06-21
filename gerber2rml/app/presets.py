"""Preset load/merge/apply: built-in + repo examples/presets.json + user JSON."""
import json
from dataclasses import asdict, replace
from pathlib import Path

BUILTIN_PRESETS = {
    # FR-4 (abrasive glass-fibre) on the SRM-20 (max ~7000 RPM): slower feeds,
    # slow plunges, shallow drill/cutout pecks to clear glass dust. Conservative
    # starting points — dial up with the calibration coupon. Set VPanel spindle
    # to max (~7000 RPM); use SOLID CARBIDE bits; dust extraction + mask required.
    "FR-4 (1.6 mm): 1/64 traces + 0.8/1.0 drill + 1/32 cutout": {
        "trace": {"bit_diameter": 0.4, "cut_depth": 0.10, "offsets": 2,
                  "stepover": 0.5, "xy_feed": 1.5, "plunge_feed": 0.5, "travel_z": 2.0},
        "drill": {"cut_depth": 0.4, "total_depth": 1.8, "xy_feed": 1.5,
                  "plunge_feed": 0.6, "travel_z": 2.0},
        "cutout": {"bit_diameter": 0.8, "cut_depth": 0.4, "total_depth": 1.8,
                   "tabs": 4, "tab_width": 1.5, "xy_feed": 1.5,
                   "plunge_feed": 0.5, "travel_z": 2.0},
    },
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
