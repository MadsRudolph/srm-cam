"""Per-user workspace folders and remembered file-dialog locations.

The app keeps its user data in Documents/SRM-CAM/ with one subfolder per
kind of file (sessions, exports, photos). Every file dialog starts in the
folder it was last used with (remembered across restarts via QSettings),
falling back to the matching workspace subfolder the first time.

Set the SRM_CAM_HOME environment variable to relocate the workspace
(tests use this to stay out of the real Documents folder).
"""
import os
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

SUBDIRS = ("sessions", "exports", "photos")


def workspace_root():
    """The Documents/SRM-CAM folder, with all subfolders created."""
    env = os.environ.get("SRM_CAM_HOME")
    if env:
        root = Path(env)
    else:
        docs = QStandardPaths.writableLocation(
            QStandardPaths.DocumentsLocation) or str(Path.home())
        root = Path(docs) / "SRM-CAM"
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _settings():
    return QSettings("SRM-CAM", "SRM-CAM")


def remembered_dir(key, fallback_sub=""):
    """Last directory used for ``key`` (e.g. "session", "out", "photo"), or
    the workspace subfolder ``fallback_sub`` if none is remembered yet."""
    d = _settings().value(f"dirs/{key}", "")
    if d and Path(str(d)).is_dir():
        return str(d)
    root = workspace_root()
    return str(root / fallback_sub) if fallback_sub else str(root)


def remember_dir(key, path):
    """Store the directory of ``path`` (a file or dir) as last-used for ``key``."""
    if not path:
        return
    p = Path(path)
    d = p if p.is_dir() else p.parent
    _settings().setValue(f"dirs/{key}", str(d))
