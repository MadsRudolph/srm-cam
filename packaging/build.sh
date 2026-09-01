#!/usr/bin/env bash
# Build SRM-CAM into a Linux AppImage.
#
# Two stages, mirroring packaging/build.ps1 so the two are comparable when one
# of them breaks:
#   1. PyInstaller -> dist/SRM-CAM/                    (the runnable app folder)
#   2. linuxdeploy -> dist_installer/*.AppImage        (the downloadable file)
#
# Run from anywhere; paths are resolved relative to this script.
#
# Usage: packaging/build.sh [--recreate] [--loose] [--skip-installer]
#   --recreate         delete and rebuild the build venv from scratch (use
#                       after changing deps)
#   --loose             install the UNPINNED dependency set
#                       (requirements-build.txt) instead of the pinned lock.
#                       Only for deliberately upgrading a dependency: build
#                       with it, re-freeze the lock, run the tests, then
#                       commit the new pins.
#   --skip-installer    build only the PyInstaller app folder; skip linuxdeploy
set -euo pipefail

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

echo "== SRM-CAM build =="
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
  # Pinned by default: a release build must be reproducible. --loose is the
  # opt-in path for deliberately upgrading a dependency (then re-freeze).
  REQS="packaging/requirements-lock-linux.txt"
  [ "$LOOSE" = 1 ] && REQS="packaging/requirements-build.txt"
  echo "deps      : $REQS"
  "$PY" -m pip install -r "$REQS"
fi
echo "python    : $PY"

# --- stage 1: PyInstaller ---------------------------------------------------
echo
echo "[1/2] PyInstaller..."
"$PY" -m PyInstaller --noconfirm packaging/srm-cam.spec
APP="$ROOT/dist/SRM-CAM/SRM-CAM"
[ -x "$APP" ] || { echo "Expected app missing: $APP" >&2; exit 1; }
echo "  -> $APP"

if [ "$SKIP" = 1 ]; then
  echo
  echo "Done (app folder only)."
  exit 0
fi

# --- stage 2: linuxdeploy ----------------------------------------------------
echo
echo "[2/2] AppImage..."
if ! command -v linuxdeploy-x86_64.AppImage >/dev/null 2>&1; then
  echo "linuxdeploy not found. Get it with:" >&2
  echo "  wget https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage" >&2
  echo "  chmod +x linuxdeploy-x86_64.AppImage" >&2
  echo "  sudo mv linuxdeploy-x86_64.AppImage /usr/local/bin/" >&2
  echo "then re-run this script to produce the AppImage." >&2
  exit 2
fi

VERSION="$("$PY" -c "import tomllib,pathlib;print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")"
APPDIR="$ROOT/dist/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r "$ROOT/dist/SRM-CAM/." "$APPDIR/usr/bin/"

mkdir -p "$ROOT/dist_installer"
# linuxdeploy names a deployed icon after --icon-file's basename
# (srm-cam-256), but srm-cam.desktop declares Icon=srm-cam - without
# --icon-filename to rename it on deploy, nothing matches that key and
# appimagetool aborts. Don't rename srm-cam-256.png itself: srm-cam.spec
# also bundles it, as the window/taskbar icon.
#
# APPIMAGE_EXTRACT_AND_RUN covers linuxdeploy-x86_64.AppImage itself and the
# linuxdeploy-plugin-appimage that --output appimage invokes underneath it -
# both are AppImages that would otherwise need FUSE2 to mount. Set here
# unconditionally rather than left to whatever's on the developer's machine:
# there's no downside to self-extracting, and FUSE2 isn't a safe assumption
# on every distro (ubuntu-latest in CI ships FUSE3 only - see build.yml).
OUTPUT="SRM-CAM-$VERSION-x86_64.AppImage" \
VERSION="$VERSION" \
APPIMAGE_EXTRACT_AND_RUN=1 \
linuxdeploy-x86_64.AppImage \
  --appdir "$APPDIR" \
  --executable "$APPDIR/usr/bin/SRM-CAM" \
  --desktop-file "$ROOT/packaging/srm-cam.desktop" \
  --icon-file "$ROOT/packaging/srm-cam-256.png" \
  --icon-filename srm-cam \
  --output appimage
mv "$ROOT/SRM-CAM-$VERSION-x86_64.AppImage" "$ROOT/dist_installer/"

# Also drop a version-less copy. The DTU-PCB-prototyping guide links to
# releases/latest/download/<name>, which only resolves if every release ships
# an asset with this exact un-versioned name - same arrangement build.ps1
# makes for SRM-CAM-Setup.exe. Upload both when publishing a release.
cp "$ROOT/dist_installer/SRM-CAM-$VERSION-x86_64.AppImage" \
   "$ROOT/dist_installer/SRM-CAM-x86_64.AppImage"

echo
echo "Done -> dist_installer/SRM-CAM-$VERSION-x86_64.AppImage"
echo "      + dist_installer/SRM-CAM-x86_64.AppImage  (version-less; upload it too)"
