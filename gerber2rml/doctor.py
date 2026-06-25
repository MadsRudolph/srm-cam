"""Environment doctor: check for the packages the GUI needs and install any
that are missing, so a fresh ``git pull`` always ends up runnable.

Run it after pulling::

    python -m gerber2rml.doctor          # check, then install anything missing
    python -m gerber2rml.doctor --check  # only report, don't install
    python -m gerber2rml.doctor --dev    # also include the test (dev) extras

This module imports ONLY the standard library, so it works on a fresh checkout
where none of the third-party packages are installed yet. The required packages
are read from ``pyproject.toml`` (the single source of truth), so adding a
dependency there is automatically picked up here.
"""
import argparse
import importlib.metadata as md
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # repo root (holds pyproject.toml)

# Distribution name -> import name, only where they differ. Used so the report
# can show a friendly "import as ..." hint; presence is checked by dist name.
_IMPORT_HINT = {
    "PySide6": "PySide6", "PyOpenGL": "OpenGL", "pyserial": "serial",
    "pyqtgraph": "pyqtgraph", "matplotlib": "matplotlib", "shapely": "shapely",
    "gerbonara": "gerbonara", "pytest": "pytest",
}

# Fallback requirements if pyproject.toml can't be read/parsed (kept in sync
# with pyproject.toml). Names only; version pins are enforced by pip on install.
_FALLBACK = {
    "core": ["gerbonara", "shapely"],
    "gui": ["PySide6", "matplotlib", "pyqtgraph", "PyOpenGL", "pyserial"],
    "dev": ["pytest"],
}


def _dist_name(req):
    """'shapely>=2.0' -> 'shapely' (strip version/marker/extras)."""
    return re.split(r"[<>=!~;\s\[]", req.strip(), 1)[0]


def _requirements():
    """{'core': [...], 'gui': [...], 'dev': [...]} read from pyproject.toml,
    falling back to the baked-in list if the file is missing or tomllib isn't
    available (Python 3.10)."""
    pyproject = ROOT / "pyproject.toml"
    try:
        import tomllib                          # Python 3.11+
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        proj = data["project"]
        opt = proj.get("optional-dependencies", {})
        return {
            "core": [_dist_name(r) for r in proj.get("dependencies", [])],
            "gui": [_dist_name(r) for r in opt.get("gui", [])],
            "dev": [_dist_name(r) for r in opt.get("dev", [])],
        }
    except Exception:
        return dict(_FALLBACK)


def _installed_version(dist):
    """Installed version string, or None if the package isn't installed."""
    try:
        return md.version(dist)
    except md.PackageNotFoundError:
        return None


def _report(groups, include_dev):
    """Print an OK/MISSING table; return the list of missing dist names."""
    wanted = list(groups["core"]) + list(groups["gui"])
    if include_dev:
        wanted += groups["dev"]
    seen, ordered = set(), []
    for d in wanted:                             # de-dup, keep order
        if d not in seen:
            seen.add(d); ordered.append(d)

    missing = []
    width = max((len(d) for d in ordered), default=10)
    print("Checking packages the gerber2rml GUI needs:\n")
    for dist in ordered:
        ver = _installed_version(dist)
        if ver is None:
            missing.append(dist)
            print(f"  [MISSING]  {dist:<{width}}")
        else:
            hint = _IMPORT_HINT.get(dist, dist)
            extra = "" if hint == dist else f"  (import as {hint})"
            print(f"  [ok]       {dist:<{width}}  {ver}{extra}")
    print()
    return missing


def _pip_install(include_dev):
    """Install the project + extras with the current interpreter's pip."""
    extras = "gui,dev" if include_dev else "gui"
    target = f"{ROOT}[{extras}]"                  # pip accepts "<path>[extras]"
    cmd = [sys.executable, "-m", "pip", "install", "-e", target]
    print(f"Installing: {' '.join(cmd)}\n")
    return subprocess.run(cmd).returncode


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m gerber2rml.doctor",
        description="Check for and install the packages the gerber2rml GUI needs.")
    ap.add_argument("--check", action="store_true",
                    help="only report what's missing; don't install anything")
    ap.add_argument("--dev", action="store_true",
                    help="also include the dev (pytest) extras")
    args = ap.parse_args(argv)

    if sys.version_info < (3, 10):
        print(f"WARNING: Python {sys.version_info.major}.{sys.version_info.minor} "
              "is below the required 3.10.\n")

    groups = _requirements()
    missing = _report(groups, args.dev)

    if not missing:
        print("All set - the GUI should run:  python -m gerber2rml.gui.app")
        return 0

    print(f"Missing {len(missing)} package(s): {', '.join(missing)}")
    if args.check:
        print("Run 'python -m gerber2rml.doctor' (without --check) to install them.")
        return 1

    rc = _pip_install(args.dev)
    if rc != 0:
        print("\npip install failed - see the output above.")
        return rc

    still = _report(groups, args.dev)            # re-check after installing
    if still:
        print(f"Still missing after install: {', '.join(still)}")
        return 1
    print("All set - the GUI should run:  python -m gerber2rml.gui.app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
