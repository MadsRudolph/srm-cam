#!/usr/bin/env bash
# Build SRM-CAM into a macOS .dmg with a drag-to-install .app.
#
# Two stages, mirroring packaging/build.sh and build.ps1 so the three are
# comparable when one of them breaks:
#   1. PyInstaller -> dist/SRM-CAM.app                        (the app bundle)
#   2. hdiutil     -> dist_installer/SRM-CAM-*-macos-*.dmg    (the download)
#
# Native architecture only: it builds for whichever Mac it runs on. There is no
# universal2 build because there are no universal2 wheels of numpy, shapely or
# matplotlib to build one from, so CI runs this once per architecture.
#
# hdiutil and codesign ship with macOS, so this installs nothing beyond the
# pinned Python packages. The app comes out ad-hoc signed, not Developer ID
# signed: packaging/README.md says what that means for a student downloading it,
# and what proper signing would need.
#
# Run from anywhere; paths are resolved relative to this script.
#
# Usage: packaging/build_macos.sh [--recreate] [--loose] [--skip-installer]
#   --recreate         delete and rebuild the build venv from scratch (use
#                       after changing deps)
#   --loose             install the UNPINNED dependency set
#                       (requirements-build.txt) instead of the pinned lock.
#   --skip-installer    build only the .app; skip the .dmg
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This builds on macOS only (it needs hdiutil and a Mac's own Python)." >&2
  echo "From another system, run the 'dmg' job in .github/workflows/build.yml." >&2
  exit 64
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VENV="$ROOT/.build-venv"
PY="$VENV/bin/python"

RECREATE=0
LOOSE=0
SKIP=0
for arg in "$@"; do
  case "$arg" in
    --recreate) RECREATE=1 ;;
    --loose) LOOSE=1 ;;
    --skip-installer) SKIP=1 ;;
    *) echo "unknown option: $arg" >&2; exit 64 ;;
  esac
done

echo "== SRM-CAM macOS build =="
echo "repo root : $ROOT"

# --- isolated build venv (only the app's runtime deps + pyinstaller) -------
if [ "$RECREATE" = 1 ] && [ -d "$VENV" ]; then
  echo "Removing existing build venv..."
  rm -rf "$VENV"
fi
if [ ! -x "$PY" ]; then
  echo "Creating build venv at $VENV ..."
  python3 -m venv "$VENV"
  "$PY" -m pip install --upgrade pip
  REQS="packaging/requirements-lock-macos.txt"
  [ "$LOOSE" = 1 ] && REQS="packaging/requirements-build.txt"
  echo "deps      : $REQS"
  "$PY" -m pip install -r "$REQS"
fi
echo "python    : $PY"

ARCH="$("$PY" -c "import platform; print(platform.machine())")"
echo "arch      : $ARCH"

# --- stage 1: PyInstaller ---------------------------------------------------
echo
echo "[1/2] PyInstaller..."
"$PY" -m PyInstaller --noconfirm packaging/srm-cam.spec
APP="$ROOT/dist/SRM-CAM.app"
[ -x "$APP/Contents/MacOS/SRM-CAM" ] || { echo "Expected app missing: $APP" >&2; exit 1; }
echo "  -> $APP"

# An Apple Silicon Mac refuses to run unsigned code at all, so the ad-hoc
# signature PyInstaller applies is not optional. Check it, rather than let a
# student find out it was missing.
if ! codesign --verify --deep --strict "$APP" 2>/dev/null; then
  echo "  bundle signature did not verify; re-signing ad hoc..."
  codesign --force --deep --sign - "$APP"
  codesign --verify --deep --strict "$APP"
fi

if [ "$SKIP" = 1 ]; then
  echo
  echo "Done (app only)."
  exit 0
fi

# --- stage 2: the disk image ------------------------------------------------
echo
echo "[2/2] Disk image..."
VERSION="$("$PY" -c "import tomllib,pathlib;print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")"
STAGE="$ROOT/dist/dmg-stage"
rm -rf "$STAGE"
mkdir -p "$STAGE" "$ROOT/dist_installer"
# ditto, not cp: it keeps the framework symlinks and extended attributes that
# the bundle's signature covers.
ditto "$APP" "$STAGE/SRM-CAM.app"
# The drag target that makes it drag-to-install.
ln -s /Applications "$STAGE/Applications"

OUT="$ROOT/dist_installer/SRM-CAM-$VERSION-macos-$ARCH.dmg"
rm -f "$OUT"
# Retried because a CI runner's disk arbitration can leave it "Resource busy" for
# a moment, and that says nothing about the build.
made=0
for attempt in 1 2 3; do
  if hdiutil create -volname "SRM-CAM" -srcfolder "$STAGE" -ov -format UDZO "$OUT"; then
    made=1
    break
  fi
  echo "  hdiutil failed (attempt $attempt); trying again..."
  sleep 10
done
[ "$made" = 1 ] || { echo "hdiutil could not create the disk image" >&2; exit 1; }
hdiutil verify "$OUT"

# Also drop a version-less copy, for releases/latest/download/<name>: the same
# arrangement build.sh makes for the AppImage and build.ps1 for SRM-CAM-Setup.exe.
cp "$OUT" "$ROOT/dist_installer/SRM-CAM-macos-$ARCH.dmg"

echo
echo "Done -> $OUT"
echo "      + dist_installer/SRM-CAM-macos-$ARCH.dmg  (version-less; upload it too)"
