"""Novice / Professional UI modes.

The mill is shared by a course: most of the people who sit down at it this
term have never used CAM before and need to do one thing — turn their Gerbers
into three files they can send from VPanel. A smaller number are doing
double-sided boards, bed leveling, fiducial fits and rework, and need every
control the app has.

Rather than build a second UI for the first group, one mode flag hides the
professional controls. Two consequences of that choice, both deliberate:

* **Hidden, not disabled.** A greyed-out control still invites clicking, and
  still has to be explained. A hidden one costs a beginner nothing.
* **The novice UI is a strict subset.** There is no separate novice code path
  that can drift out of step with the real one — same widgets, same handlers,
  same exports. What a student produces in Novice is byte-identical to what
  the same settings produce in Professional.

Novice is the default on a fresh install, because the person who has never
opened the app before is exactly the person the default is for.

Switching is a menu item, not a password: this manages complexity, it is not
a security boundary. A lab that does want it fixed can set the ``SRM_CAM_MODE``
environment variable (machine-wide, or in the shortcut that launches the app);
that overrides the stored preference and the menu greys out.
"""
import os

from PySide6.QtCore import QSettings

NOVICE = "novice"
PRO = "pro"

_KEY = "ui/mode"
_VALID = (NOVICE, PRO)


def _settings():
    return QSettings("SRM-CAM", "SRM-CAM")


def forced_mode():
    """The mode pinned by ``SRM_CAM_MODE``, or None if the user is free to pick.

    Accepts "novice"/"pro" in any case, plus "professional" as the spelling
    people actually type.
    """
    raw = os.environ.get("SRM_CAM_MODE", "").strip().lower()
    if raw == "professional":
        raw = PRO
    return raw if raw in _VALID else None


def current_mode():
    """The active mode: the env override if set, else the stored preference,
    else Novice (fresh install)."""
    forced = forced_mode()
    if forced:
        return forced
    stored = str(_settings().value(_KEY, NOVICE) or NOVICE).lower()
    return stored if stored in _VALID else NOVICE


def set_mode(mode):
    """Store the chosen mode. Ignored while ``SRM_CAM_MODE`` pins it."""
    if mode not in _VALID:
        raise ValueError(f"unknown mode {mode!r}; expected one of {_VALID}")
    if forced_mode():
        return False
    _settings().setValue(_KEY, mode)
    return True


def is_pro():
    return current_mode() == PRO


# What Novice puts away, in the words a person would use. Shown by the Mode
# menu's "What's hidden in Novice?" item, so nobody has to guess whether the
# feature they remember is gone or just tucked away.
HIDDEN_IN_NOVICE = [
    "Job parameters — feeds, depths, offsets, stepover, V-bit geometry "
    "(the preset sets these)",
    "Double-sided milling — registration, flip + align, top traces",
    "Bed leveling — probing the surface and the height map",
    "Rework — boxing spots to re-cut",
    "Machine control — connect, DRO, jog, probe, streaming (use VPanel)",
    "Output format, mirroring and preview frame (the defaults are correct)",
    "The feed test card and saving your own presets",
]
