"""Where this interface keeps user files, and where its dialogs open.

Deliberately a copy of the first interface's contract rather than an import of
it: ``gui2`` does not depend on ``gui``, so that either one can be deleted
without breaking the other. It resolves to the SAME folder — the workspace
belongs to the user and the machine, not to whichever front end wrote it, and a
student who exports from one and looks for the files from the other should find
them.

``SRM_CAM_HOME`` relocates the whole thing (the test suite points it at a temp
directory so a run never touches real Documents).
"""
import os
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

SUBDIRS = ("sessions", "exports", "photos")


def workspace_root():
    """``Documents/SRM-CAM``, with the subfolders created."""
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
    # Its own organisation-scoped key space. The two interfaces remember their
    # own window geometry and their own last-used folders; sharing those would
    # make an A/B of "where does it open?" meaningless.
    return QSettings("SRM-CAM", "SRM-CAM-2")


def remembered_dir(key, fallback_sub=""):
    """Last directory used for ``key``, else the workspace subfolder."""
    d = _settings().value(f"dirs/{key}", "")
    if d and Path(str(d)).is_dir():
        return str(d)
    root = workspace_root()
    return str(root / fallback_sub) if fallback_sub else str(root)


def remember_dir(key, path):
    """Store the directory of ``path`` as last-used for ``key``."""
    if not path:
        return
    p = Path(path)
    _settings().setValue(f"dirs/{key}", str(p if p.is_dir() else p.parent))


def setting(key, default=None):
    return _settings().value(key, default)


def set_setting(key, value):
    _settings().setValue(key, value)
