"""Assert the version number agrees everywhere, and (in CI) matches the tag.

SRM-CAM's version lives in three places that must not drift:

  * pyproject.toml           [project] version
  * packaging/installer.iss  #define MyAppVersion  -> the installer filename
  * gerber2rml/__init__.py   __version__           -> what the app reports

A mismatch is not cosmetic: the installer would be named for one version while
the app reports another, and the release asset the DTU guide links to would
point at the wrong build. This runs in CI on every push, so the drift is caught
the moment it is introduced instead of at release time.

Usage:
    python scripts/check_version.py            # the three files agree
    python scripts/check_version.py v0.2.8     # ...and match this git tag
"""
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pyproject():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def _installer():
    text = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    m = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', text)
    if not m:
        raise SystemExit("installer.iss: no #define MyAppVersion found")
    return m.group(1)


def _package():
    text = (ROOT / "gerber2rml" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("gerber2rml/__init__.py: no __version__ found")
    return m.group(1)


def main(argv):
    found = {
        "pyproject.toml": _pyproject(),
        "packaging/installer.iss": _installer(),
        "gerber2rml/__init__.py": _package(),
    }
    for where, version in found.items():
        print(f"  {version:<10} {where}")

    if len(set(found.values())) != 1:
        print("\nVersion mismatch — these must all be the same.", file=sys.stderr)
        return 1
    version = next(iter(found.values()))

    if argv:                                  # a git tag was passed (CI release)
        tag = argv[0].lstrip("v")
        if tag != version:
            print(f"\nTag {argv[0]} does not match version {version}. "
                  f"Bump the three files, or re-tag.", file=sys.stderr)
            return 1
        print(f"\nOK — version {version} matches tag {argv[0]}.")
    else:
        print(f"\nOK — version {version} is consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
