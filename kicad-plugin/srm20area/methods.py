"""Design rules per fabrication method, chosen before the first track. Pure.

No pcbnew and no wx, so it imports and tests anywhere; ``rules.py`` reads and
writes the board, ``rules_dialog.py`` is the window. Written for the Python
KiCad ships (3.9 on some builds), so no newer syntax.

A board's rules follow from how its copper is made, and that is decided before
layout: a gap the tool cannot enter is a short, and a gap far wider than the
tool needs is copper the laser burns for nothing. Each method below carries the
numbers that have been cut or etched in the lab:

* **0.8 mm flat endmill** - the default mill bit. Clearance 0.85 mm (the bit's
  0.8 mm plus runout), tracks 1.0 mm. Through-hole parts.
* **0.8 mm ball mill** - 0.44 mm channel at 0.08 mm deep. Clearance and tracks
  0.50 mm. Fine pitch and SMD.
* **Fiber laser copper** (xTool F1 Ultra from SRM-CAM's laser page; holes and
  outline on the mill). The laser clears about 0.22 mm out from every copper
  edge (6 isolation rings), so a pour 0.25 mm from the copper gives a trench
  that is about the gap itself. Tracks 0.30 mm, as on the curtain-drive board.

``floor`` is the narrowest gap the method can make at all. The board's own
minimum clearance is set to it, so a documented exception (a custom rule for a
fine-pitch footprint) can go below the net-class clearance but never below what
the tool can cut.

Holes are drilled on the mill whatever makes the copper, so every method asks
for the drill SRM-CAM has (``drill_mm``) as the smallest hole, with 0.5 mm of
copper round a via's hole to solder its wire to.
"""
import json
import os
import re

OUT_DIRNAME = "srm-cam"
METHOD_FILE = "method.json"
VIA_RING_MM = 0.5
DEFAULT_DRILL_MM = 0.8

# The numbers a method asks for, in mm. Keys are the fields of the window.
FIELDS = (
    ("track", "Track width"),
    ("clearance", "Clearance (net classes)"),
    ("floor", "Board minimum clearance"),
    ("pour_gap", "Pour to other copper"),
    ("thermal_gap", "Thermal relief gap"),
    ("pour_min", "Pour minimum width"),
    ("edge", "Copper to board edge"),
    ("drill", "Smallest hole (drill)"),
)

METHODS = (
    {"id": "mill_flat",
     "name": "Mill: 0.8 mm flat endmill",
     "about": "Isolation-milled on the SRM-20 with the 0.8 mm flat endmill. "
              "Through-hole parts. No gap may be narrower than the bit.",
     "values": {"track": 1.0, "clearance": 0.85, "floor": 0.8,
                "pour_gap": 0.85, "thermal_gap": 0.85, "pour_min": 0.5,
                "edge": 0.5}},
    {"id": "mill_ball",
     "name": "Mill: 0.8 mm ball mill (0.44 mm channel)",
     "about": "Isolation-milled on the SRM-20 with the 0.8 mm ball mill, "
              "0.08 mm deep. For fine pitch and SMD.",
     "values": {"track": 0.5, "clearance": 0.5, "floor": 0.44,
                "pour_gap": 0.5, "thermal_gap": 0.5, "pour_min": 0.5,
                "edge": 0.5}},
    {"id": "laser",
     "name": "Fiber laser copper (holes and outline on the mill)",
     "about": "Copper etched on the xTool F1 Ultra from SRM-CAM's laser page; "
              "drilling and the cut-out stay on the SRM-20. The laser clears "
              "about 0.22 mm round every copper edge, so the pour stands "
              "0.25 mm off: a trench no wider than the gap.",
     "values": {"track": 0.3, "clearance": 0.25, "floor": 0.2,
                "pour_gap": 0.25, "thermal_gap": 0.25, "pour_min": 0.25,
                "edge": 0.5}},
)


def method(method_id):
    for m in METHODS:
        if m["id"] == method_id:
            return m
    raise KeyError(method_id)


def defaults(method_id, drill_mm=None):
    """The numbers ``method_id`` asks for, with the drill SRM-CAM has."""
    values = dict(method(method_id)["values"])
    values["drill"] = round(float(drill_mm or DEFAULT_DRILL_MM), 3)
    return values


def via_diameter(drill):
    return round(drill + 2 * VIA_RING_MM, 3)


# ------------------------------------------------------------------ the plan
def _same(a, b):
    return a is not None and b is not None and abs(a - b) < 0.0005


def plan(current, wanted):
    """What to change, from the board as it is (``current``) to ``wanted``.

    ``current`` is what ``rules.read_current`` returns: ``board`` (dict of
    ``floor``, ``edge``, ``drill``), ``classes`` (name -> ``clearance``,
    ``track``, ``via_drill``, ``via_dia``; None where the class does not set
    it), ``zones`` (list of ``name``, ``clearance``, ``thermal_gap``,
    ``pour_min``) and ``zone_defaults`` (the same three, for new zones).

    Returns ``(target, key, old, new)`` operations; target is ``"board"``,
    ``("class", name)``, ``("zone", index)`` or ``"zone_defaults"``.
    Clearances and pour settings are set to what is asked, up or down: the
    method decides them. Track width is set on the Default class; another
    class (a wider power class, say) is only raised to it. Holes are only
    ever raised to the drill.
    """
    ops = []

    def want(target, key, old, new, only_up=False):
        if _same(old, new):
            return
        if only_up and old is not None and old > new:
            return
        ops.append((target, key, old, new))

    b = current.get("board", {})
    want("board", "floor", b.get("floor"), wanted["floor"])
    want("board", "edge", b.get("edge"), wanted["edge"])
    want("board", "drill", b.get("drill"), wanted["drill"], only_up=True)
    for name, c in current.get("classes", {}).items():
        t = ("class", name)
        want(t, "clearance", c.get("clearance"), wanted["clearance"])
        want(t, "track", c.get("track"), wanted["track"],
             only_up=(name != "Default"))
        want(t, "via_drill", c.get("via_drill"), wanted["drill"], only_up=True)
        want(t, "via_dia", c.get("via_dia"), via_diameter(wanted["drill"]),
             only_up=True)
    pour = (("clearance", "pour_gap"), ("thermal_gap", "thermal_gap"),
            ("pour_min", "pour_min"))
    for i, z in enumerate(current.get("zones", [])):
        for key, field in pour:
            want(("zone", i), key, z.get(key), wanted[field])
    zd = current.get("zone_defaults")
    if zd:
        for key, field in pour:
            want("zone_defaults", key, zd.get(key), wanted[field])
    return ops


_LABEL = {"floor": "minimum clearance", "edge": "copper to edge",
          "drill": "smallest hole", "clearance": "clearance",
          "track": "track width", "via_drill": "via hole",
          "via_dia": "via size", "thermal_gap": "thermal gap",
          "pour_min": "minimum width"}


def describe(op, zone_names=()):
    """One line for an operation from :func:`plan`."""
    target, key, old, new = op
    if target == "board":
        where = "Board"
    elif target == "zone_defaults":
        where = "New zones"
    elif target[0] == "class":
        where = "Net class %s" % target[1]
    else:
        names = list(zone_names)
        where = "Zone %s" % (names[target[1]] if target[1] < len(names)
                             else target[1] + 1)
    label = _LABEL[key]
    if target != "board" and key == "clearance" and target[0] == "zone":
        label = "clearance to other copper"
    old_s = "unset" if old is None else "%.2f" % old
    return "%s %s %s -> %.2f mm" % (where, label, old_s, new)


def too_tight(current, wanted):
    """What a board asks for that its method cannot make, as lines. Empty when
    every gap is at least the method's floor and no hole is under the drill.
    The check *Send to SRM-CAM* runs on a board whose method is known."""
    floor, drill = wanted["floor"], wanted["drill"]
    out = []
    b = current.get("board", {})
    if b.get("floor") is not None and b["floor"] < floor - 0.0005:
        out.append("Board minimum clearance: %.2f mm" % b["floor"])
    for name, c in current.get("classes", {}).items():
        if c.get("clearance") is not None and c["clearance"] < floor - 0.0005:
            out.append("Net class %s clearance: %.2f mm" % (name, c["clearance"]))
        if c.get("via_drill") is not None and c["via_drill"] < drill - 0.0005:
            out.append("Net class %s via hole: %.2f mm" % (name, c["via_drill"]))
    for z in current.get("zones", []):
        for key, label in (("clearance", "clearance"),
                           ("thermal_gap", "thermal gap")):
            if z.get(key) is not None and z[key] < floor - 0.0005:
                out.append("Zone %s %s: %.2f mm" % (z.get("name"), label, z[key]))
    return out


# ------------------------------------------------------- the custom rules file
_NUM = re.compile(r"\(min\s+([0-9.]+)\s*(mm|mil|in)?\s*\)")


def _blocks(text):
    """The top-level ``(rule ...)`` blocks of a .kicad_dru, in order."""
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    s = "\n".join(lines)
    out, depth, start, in_str = [], 0, None, False
    for i, ch in enumerate(s):
        if ch == '"' and (i == 0 or s[i - 1] != "\\"):
            in_str = not in_str
        if in_str:
            continue
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and start is not None:
                block = s[start:i + 1]
                if re.match(r"\(\s*rule\b", block):
                    out.append(block)
    return out


def clearance_rules(text):
    """``(name, condition or None, min clearance mm)`` for every custom rule
    that sets a copper clearance and is not switched off."""
    found = []
    for block in _blocks(text):
        if re.search(r"\(severity\s+ignore\)", block):
            continue
        m = re.search(r"\(constraint\s+clearance\s+(\([^()]*\))", block)
        if not m:
            continue
        n = _NUM.search(m.group(1))
        if not n:
            continue
        value = float(n.group(1))
        unit = n.group(2) or "mm"
        value *= {"mm": 1.0, "mil": 0.0254, "in": 25.4}[unit]
        name = re.match(r'\(\s*rule\s+("([^"]*)"|(\S+))', block)
        cond = re.search(r'\(condition\s+"((?:[^"\\]|\\.)*)"\)', block)
        found.append((name.group(2) or name.group(3) if name else "?",
                      cond.group(1) if cond else None, round(value, 4)))
    return found


def _touches_zones(cond):
    """Whether a rule's condition can match a pour: none at all, or one that
    names zones without excluding them."""
    if cond is None:
        return True
    return ("'Zone'" in cond and "!= 'Zone'" not in cond)


def rule_file_notes(text, wanted):
    """Custom rules that will override the method, as lines to show.

    A rule asking for less than the method's floor allows a gap the tool
    cannot make. A rule that reaches the pours and asks for more than the
    pour gap keeps the pour further off than the method wants - the last
    such rule wins in KiCad, so only that one is named."""
    notes = []
    rules = clearance_rules(text)
    for name, cond, value in rules:
        if value < wanted["floor"] - 0.0005:
            notes.append('Rule "%s" allows %.2f mm, less than this method '
                         'can make (%.2f mm).' % (name, value, wanted["floor"]))
    last = None
    for name, cond, value in rules:
        if _touches_zones(cond):
            last = (name, value)
    if last and last[1] > wanted["pour_gap"] + 0.0005:
        notes.append('Rule "%s" holds the pour %.2f mm from other copper; '
                     'this method wants %.2f mm.'
                     % (last[0], last[1], wanted["pour_gap"]))
    return notes


# ------------------------------------------------- which method a board uses
def method_file(board_file):
    return os.path.join(os.path.dirname(os.path.abspath(board_file)),
                        OUT_DIRNAME, METHOD_FILE)


def read_method(board_file):
    """``(method id, values)`` last set for this board, or ``(None, None)``.
    Kept beside the board, in the folder *Send to SRM-CAM* plots into."""
    try:
        with open(method_file(board_file), encoding="utf-8") as f:
            data = json.load(f)
        boards = data.get("boards", {})
        entry = boards.get(os.path.basename(board_file))
        if entry and entry.get("method") in [m["id"] for m in METHODS]:
            return entry["method"], dict(entry.get("values") or {})
    except (OSError, ValueError, AttributeError):
        pass
    return None, None


def write_method(board_file, method_id, values):
    path = method_file(board_file)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data.setdefault("boards", {})[os.path.basename(board_file)] = {
        "method": method_id, "values": values}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    return path
