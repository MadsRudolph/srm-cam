"""What the laser page did, written down: ``laser.log`` in the workspace.

drums1 (2026-11-19) came off the laser with unfinished edges, and nothing
said afterwards what the focus map had measured, what the correction took
off, which bands ran at which height, or with which recipe. The mill keeps a
run log per run; this is the laser's: every message the page ends a step
with, and the numbers behind the focus map and each etch. Appended, one
block per event, stamped. Writing it never fails a step.
"""
import datetime
import json
import os
from pathlib import Path


def path():
    from gerber2rml import platform as plat
    home = os.environ.get("SRM_CAM_HOME")
    base = Path(home) if home else Path(plat.documents_dir()) / "SRM-CAM"
    return base / "laser.log"


def write(what, **detail):
    """One stamped entry: ``what`` and any numbers, as JSON-ish lines."""
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"{stamp}  {what}"]
        for k, v in detail.items():
            try:
                text = json.dumps(v, default=_plain)
            except (TypeError, ValueError):
                text = repr(v)
            lines.append(f"    {k}: {text}")
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:                       # noqa: BLE001 - a log, never a failure
        pass


def _plain(v):
    if hasattr(v, "__dict__"):
        return {k: x for k, x in vars(v).items() if not k.startswith("_")}
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    return repr(v)


def points(fmap):
    """A focus map's points, rounded, for the log."""
    if fmap is None:
        return None
    return [[round(x, 1), round(y, 1), round(dz, 3)] for x, y, dz in fmap.points]
