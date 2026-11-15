#!/usr/bin/env bash
# Bring this macOS checkout up to date with upstream and rebuild the app.
#
# What docs/macos.md describes by hand, in one go:
#   1. fetch upstream and rebase this branch (the macOS patch) onto it
#   2. reinstall the package into .venv and run the doctor
#   3. run the tests - a failure stops here, before anything is rebuilt
#   4. packaging/build-macos.sh
#   5. with --install: replace /Applications/SRM-CAM.app (after SRM-CAM quits)
#
# Usage: packaging/update-macos.sh [--install] [--no-tests]
#
# SRM-CAM's Help > Check for updates runs this with --install in Terminal.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
INSTALL=0
TESTS=1
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    --no-tests) TESTS=0 ;;
    *) echo "unknown option: $arg" >&2; exit 64 ;;
  esac
done

# Tests known to fail on macOS for reasons that are not the patch's, one per
# line, deselected so they do not stop an update; anything else does. Empty
# since the five there were (docs/macos.md, "Known limitations") were fixed.
# Expanded with the ${X[@]+...} form below: macOS ships bash 3.2, where an
# empty array is "unbound" under set -u.
KNOWN_MAC_FAILURES=()

echo "== SRM-CAM macOS update =="
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "This checkout has uncommitted changes. Commit or stash them first:" >&2
  git status --short --untracked-files=no >&2
  exit 1
fi

echo
echo "[1/5] Fetching upstream..."
git fetch upstream
if git merge-base --is-ancestor upstream/main HEAD; then
  echo "  already on top of upstream/main"
else
  if ! git rebase upstream/main; then
    git rebase --abort || true
    echo "The macOS patch no longer applies cleanly to upstream." >&2
    echo "Nothing was changed. Rebase by hand: git rebase upstream/main" >&2
    exit 1
  fi
fi

echo
echo "[2/5] Python environment..."
if [ ! -x .venv/bin/python ]; then
  "$(command -v python3.12 || command -v python3)" -m venv .venv
fi
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -e ".[gui,dev]"
.venv/bin/python -m pip install -q pytest-xdist || true   # only for speed
.venv/bin/python -m gerber2rml.doctor

echo
if [ "$TESTS" = 1 ]; then
  echo "[3/5] Tests (a minute with pytest-xdist, about seven without)..."
  DESELECT=()
  for t in ${KNOWN_MAC_FAILURES[@]+"${KNOWN_MAC_FAILURES[@]}"}; do
    DESELECT+=(--deselect "$t")
  done
  # In parallel when pytest-xdist is there (pip install pytest-xdist): about
  # one minute instead of seven. Work stealing matters - the long simulator
  # runs sit together in two files and would otherwise queue on one worker.
  PARALLEL=()
  if .venv/bin/python -c "import xdist" 2>/dev/null; then
    PARALLEL=(-n auto --dist worksteal)
  fi
  QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider \
    -W ignore ${PARALLEL[@]+"${PARALLEL[@]}"} ${DESELECT[@]+"${DESELECT[@]}"}
else
  echo "[3/5] Tests skipped (--no-tests)"
fi

echo
echo "[4/5] Building the app..."
# The build replaces dist/SRM-CAM.app; a copy running from there would lose
# its own files mid-run.
while pgrep -f "$ROOT/dist/SRM-CAM.app/Contents/MacOS/SRM-CAM" >/dev/null; do
  echo "  waiting for SRM-CAM (running from dist/) to quit - Cmd-Q in SRM-CAM..."
  sleep 3
done
packaging/build-macos.sh

echo
if [ "$INSTALL" = 1 ]; then
  echo "[5/5] Installing to /Applications..."
  while pgrep -f "SRM-CAM.app/Contents/MacOS/SRM-CAM" >/dev/null; do
    echo "  waiting for SRM-CAM to quit (Cmd-Q in SRM-CAM)..."
    sleep 3
  done
  rm -rf /Applications/SRM-CAM.app
  ditto dist/SRM-CAM.app /Applications/SRM-CAM.app
  echo "  -> /Applications/SRM-CAM.app"
  open /Applications/SRM-CAM.app
else
  echo "[5/5] Not installed (no --install). The new app is dist/SRM-CAM.app"
fi
echo
echo "Done."
