#!/usr/bin/env bash
# Build SRM-CAM into a macOS app bundle, dist/SRM-CAM.app.
#
# Mirrors packaging/build.sh (Linux) and build.ps1 (Windows):
#   1. icon        -> build/macos/srm-cam.icns    (sips + iconutil, both ship with macOS)
#   2. PyInstaller -> dist/SRM-CAM.app            (the spec's BUNDLE step, darwin only)
#   3. signature   -> ad-hoc by default; Developer ID + hardened runtime with --release
#   4. disk image  -> dist_installer/SRM-CAM-<version>.dmg   (--dmg or --release)
#   5. notarise    -> notarytool + stapler                  (--release)
#
# Run from anywhere; paths are resolved relative to this script.
#
# Usage: packaging/build-macos.sh [--recreate] [--dmg] [--release]
#   --recreate   delete and rebuild the build venv from scratch (use after
#                changing deps)
#   --dmg        also wrap the app in a drag-to-Applications disk image
#   --release    sign with a "Developer ID Application" certificate, make the
#                disk image, notarise it with Apple and staple the ticket, so
#                it opens on any Mac without a Gatekeeper warning
#
# --release needs, once per Mac (docs/macos.md, "Signed releases"):
#   * a Developer ID Application certificate in the login keychain
#     (Xcode > Settings > Accounts > Manage Certificates > +)
#   * notary credentials stored under a profile name:
#       xcrun notarytool store-credentials srm-cam --apple-id <id> --team-id <team>
# Overrides: SRM_CAM_SIGN_ID (certificate name or hash),
#            SRM_CAM_NOTARY_PROFILE (default: srm-cam).
#
# There is no macOS lock file yet, so the build venv installs the loose set
# (requirements-build.txt). Python 3.12 is preferred: PySide6 has wheels for it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VENV="$ROOT/.build-venv"
PY="$VENV/bin/python"
ENTITLEMENTS="$ROOT/packaging/macos-entitlements.plist"

RECREATE=0
DMG=0
RELEASE=0
for arg in "$@"; do
  case "$arg" in
    --recreate) RECREATE=1 ;;
    --dmg) DMG=1 ;;
    --release) RELEASE=1; DMG=1 ;;
    *) echo "unknown option: $arg" >&2; exit 64 ;;
  esac
done

echo "== SRM-CAM macOS build =="
echo "repo root : $ROOT"

SIGN_ID="${SRM_CAM_SIGN_ID:-}"
PROFILE="${SRM_CAM_NOTARY_PROFILE:-srm-cam}"
if [ "$RELEASE" = 1 ]; then
  if [ -z "$SIGN_ID" ]; then
    SIGN_ID="$(security find-identity -v -p codesigning \
      | sed -n 's/.*"\(Developer ID Application: [^"]*\)".*/\1/p' | head -1)"
  fi
  if [ -z "$SIGN_ID" ]; then
    echo "--release needs a 'Developer ID Application' certificate, and the" >&2
    echo "keychain has none. Create one in Xcode > Settings > Accounts >" >&2
    echo "Manage Certificates > + > Developer ID Application, then re-run." >&2
    exit 2
  fi
  if ! xcrun notarytool history --keychain-profile "$PROFILE" >/dev/null 2>&1; then
    echo "--release needs notary credentials stored as profile '$PROFILE':" >&2
    echo "  xcrun notarytool store-credentials $PROFILE --apple-id <id> --team-id <team>" >&2
    exit 2
  fi
  echo "signing   : $SIGN_ID"
  echo "notary    : profile $PROFILE"
fi

if [ "$RECREATE" = 1 ] && [ -d "$VENV" ]; then
  echo "Removing existing build venv..."
  rm -rf "$VENV"
fi
if [ ! -x "$PY" ]; then
  BASEPY="$(command -v python3.12 || command -v python3)"
  echo "Creating build venv at $VENV with $BASEPY ..."
  "$BASEPY" -m venv "$VENV"
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r packaging/requirements-build.txt
fi
echo "python    : $PY"
VERSION="$("$PY" -c "import tomllib,pathlib;print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")"

# --- stage 1: icon ----------------------------------------------------------
echo
echo "[1/5] Icon..."
ICONSET="$ROOT/build/macos/srm-cam.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
SRC="$ROOT/packaging/srm-cam-256.png"
for s in 16 32 64 128 256; do
  sips -z "$s" "$s" "$SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
done
for s in 16 32 64 128; do
  cp "$ICONSET/icon_$((s * 2))x$((s * 2)).png" "$ICONSET/icon_${s}x${s}@2x.png"
done
rm "$ICONSET/icon_64x64.png"
iconutil -c icns "$ICONSET" -o "$ROOT/build/macos/srm-cam.icns"
echo "  -> build/macos/srm-cam.icns"

# --- stage 2: PyInstaller ---------------------------------------------------
echo
echo "[2/5] PyInstaller..."
"$PY" -m PyInstaller --noconfirm packaging/srm-cam.spec
APP="$ROOT/dist/SRM-CAM.app"
[ -x "$APP/Contents/MacOS/SRM-CAM" ] || { echo "Expected app missing: $APP" >&2; exit 1; }

# --- stage 3: signature -----------------------------------------------------
# Inside out, as Apple requires: every Mach-O file, then every framework
# bundle, deepest first, then the app. --deep is not used for a release; it
# signs in the wrong order for nested frameworks.
# codesign, quiet unless it fails ("replacing existing signature" is noise).
cs() {
  local out
  if ! out="$(codesign "$@" 2>&1)"; then echo "$out" >&2; return 1; fi
}

sign_release() {
  local id="$1"
  local args=(--force --timestamp --options runtime --entitlements "$ENTITLEMENTS" -s "$id")
  [ "$id" = "-" ] && args=(--force --options runtime --entitlements "$ENTITLEMENTS" -s -)
  find "$APP/Contents" -type f -print0 | while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q "Mach-O"; then
      cs "${args[@]}" "$f"
    fi
  done
  find "$APP/Contents" -type d -name "*.framework" \
    | awk '{print length($0) " " $0}' | sort -rn | cut -d' ' -f2- \
    | while IFS= read -r fw; do
        cs "${args[@]}" "$fw"
      done
  cs "${args[@]}" "$APP"
}

echo
if [ "$RELEASE" = 1 ]; then
  echo "[3/5] Signing (Developer ID, hardened runtime)..."
  sign_release "$SIGN_ID"
elif [ -n "$SIGN_ID" ]; then
  echo "[3/5] Signing with $SIGN_ID (hardened runtime, not notarised)..."
  sign_release "$SIGN_ID"
else
  echo "[3/5] Ad-hoc codesign..."
  codesign --force --deep -s - "$APP"
fi
codesign --verify --deep --strict "$APP"
echo "  signature verified"

# --- stage 4: disk image ----------------------------------------------------
DMG_PATH="$ROOT/dist_installer/SRM-CAM-$VERSION.dmg"
if [ "$DMG" = 1 ]; then
  echo
  echo "[4/5] Disk image..."
  STAGE="$ROOT/build/macos/dmg"
  rm -rf "$STAGE"
  mkdir -p "$STAGE" "$ROOT/dist_installer"
  ditto "$APP" "$STAGE/SRM-CAM.app"
  ln -s /Applications "$STAGE/Applications"
  rm -f "$DMG_PATH"
  hdiutil create -volname "SRM-CAM $VERSION" -srcfolder "$STAGE" \
    -fs HFS+ -format UDZO -ov "$DMG_PATH" >/dev/null
  if [ "$RELEASE" = 1 ]; then
    codesign --force --timestamp -s "$SIGN_ID" "$DMG_PATH"
  fi
  echo "  -> ${DMG_PATH#$ROOT/}"
else
  echo
  echo "[4/5] Disk image skipped (--dmg or --release makes one)"
fi

# --- stage 5: notarise ------------------------------------------------------
echo
if [ "$RELEASE" = 1 ]; then
  echo "[5/5] Notarising with Apple (a few minutes)..."
  xcrun notarytool submit "$DMG_PATH" --keychain-profile "$PROFILE" --wait
  xcrun stapler staple "$DMG_PATH"
  xcrun stapler staple "$APP" || true
  spctl --assess --type open --context context:primary-signature -v "$DMG_PATH"
  echo "  notarised and stapled"
else
  echo "[5/5] Not notarised (--release does it)"
fi

echo
echo "Done -> dist/SRM-CAM.app"
[ "$DMG" = 1 ] && echo "      + ${DMG_PATH#$ROOT/}"
if [ "$RELEASE" != 1 ]; then
  echo "Not notarised: on another Mac the first launch needs right-click -> Open."
fi
