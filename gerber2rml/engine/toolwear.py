"""Cumulative tool-wear ledger: how many metres has each bit cut?

A dull 0.8 mm endmill tears copper instead of shearing it — the burrs look
exactly like the leveling failures this app now guards against, so knowing a
bit is tired is diagnostic gold. Every traces/rework export adds its cut
distance to a per-tool ledger in the workspace (Documents/SRM-CAM/
tool_wear.json); past the warn threshold the export status says so.

The ledger key is the tool, not the job: "flat 0.80mm", "vbit 0.20mm", ...
Reset a line by deleting it from the JSON (or the whole file) after changing
to a fresh bit.
"""
import json
import math

WARN_AT_M = 25.0          # flat micro endmills in FR-4 are visibly duller ~25 m


def cut_distance_mm(toolpaths):
    """Total non-rapid XY distance over a list of toolpaths (Move lists)."""
    total = 0.0
    for tp in toolpaths:
        prev = None
        for m in tp:
            if prev is not None and not m.rapid:
                total += math.hypot(m.x - prev.x, m.y - prev.y)
            prev = m
    return total


def _store_path():
    from gerber2rml.gui.workspace import workspace_root
    return workspace_root() / "tool_wear.json"


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record(tool_key, dist_mm, path=None):
    """Add ``dist_mm`` to the tool's ledger; returns its new total (mm)."""
    path = path or _store_path()
    data = _load(path)
    total = float(data.get(tool_key, 0.0)) + float(dist_mm)
    data[tool_key] = round(total, 1)
    try:
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except Exception:
        pass                          # a read-only disk never blocks an export
    return total


def total_m(tool_key, path=None):
    """The tool's recorded total, in metres."""
    path = path or _store_path()
    return float(_load(path).get(tool_key, 0.0)) / 1000.0


def wear_note(tool_key, path=None, warn_at_m=WARN_AT_M):
    """Status-bar suffix for the tool: always its mileage, plus a warning when
    it's past the threshold. Empty string if the tool has no history."""
    m = total_m(tool_key, path)
    if m <= 0:
        return ""
    note = f" · {tool_key} has cut {m:.1f} m"
    if m >= warn_at_m:
        note += " — WORN, consider a fresh bit"
    return note
