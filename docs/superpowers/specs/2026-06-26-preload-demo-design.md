# Preload a demo board on launch — design

**Date:** 2026-06-26
**Status:** approved, ready for implementation

## Problem

The GUI opens empty, which looks bare. It should open with a board already
loaded and previewed. There's also a stale preload block in `main()` pointing at
a hardcoded teammate path (`C:\Users\s246132\...`) that never exists here and
silently does nothing — replace it.

## Design

- Commit the demo Gerber set `examples/preload_example/` (boost_v2, a full KiCad
  export) so it ships with the app.
- Add a module-level helper `_preload_demo(win)` in `gerber2rml/gui/app.py`:
  - Resolve the demo folder relative to the repo root:
    `Path(__file__).resolve().parents[2] / "examples" / "preload_example"`
    (stored as `_DEMO_DIR`).
  - If it's a directory: `win.load_folder(...)`, `win.generate_preview()`, and
    `win.preview.set_demo(True)` — a **persistent** "DEMO BOARD" badge in the
    preview's top-right corner (a transient status-bar hint was rejected because
    it auto-clears). The badge clears in `_on_load_clicked` when the operator
    loads their own Gerbers; internal reloads (mirror toggle) leave it on.
  - Best-effort: wrapped in try/except; if the folder is missing (e.g. an
    installed copy without `examples/`) or load fails, the app starts empty —
    never crashes.
- `main()` calls `_preload_demo(win)` after building the window and before
  `win.show()` — replacing the stale hardcoded block.
- Loaded single-sided (no forced double-sided); the user's own Load replaces it.

**Why in `main()`, not `MainWindow.__init__`:** keeps programmatic/test
construction empty, so the existing "no board" behaviours (estimate `—`, rework
"no regions"/"no board" guards, etc.) and their tests stay valid. The preload is
purely a launch nicety.

## Testing

`tests/test_window.py`:
- `_preload_demo(win)` loads the demo: `win.state.board` goes from `None` to set,
  with a non-empty outline.
- with `_DEMO_DIR` monkeypatched to a missing path, `_preload_demo` does nothing
  and doesn't raise; the board stays `None`.

## Out of scope (YAGNI)

- Remembering/reloading the user's last session.
- A setting to disable the demo (just Load your own folder to replace it).
- Forcing double-sided or any specific op on the demo.
