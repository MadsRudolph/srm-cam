"""Two tiers of interface, over one code path.

The problem is real and unchanged from the first interface: most people who sit
down at this mill have never used CAM and will use it twice, and a few are
running double-sided boards over a probed height map and need everything.

What is different here is *where the line falls*. The first interface splits by
CONTROL — Novice hides the job-parameter forms, the machine dock, double-sided,
rework. That is a defensible split, and it had one bad consequence its own
commit log records: hiding the machine dock hid the STOP button, so guided bed
levelling — which steps a spinning-capable machine down onto the copper — had
to be pulled out of Novice entirely to stop it being the more dangerous mode.

This interface splits by TASK instead. ``ESSENTIAL`` carries the whole
single-sided job including levelling, because levelling is the thing the
Arduino actually buys a beginner. It can do that safely because the stop
control is not in a hideable panel: the machine bar is a structural part of the
window and every control that moves the machine lives in it. See
``machine.py``.

``FULL`` adds the work that assumes you already know the machine — double-sided
registration, rework regions, per-operation parameter editing, the output
format, the experimental stream path, and the machine test.

Two properties are preserved from the first interface's ``mode.py``, because
they were right:

* **Hidden, not disabled.** A greyed-out control still invites a click and
  still has to be explained. A hidden one costs a beginner nothing.
* **A strict subset, not a second program.** Same widgets, same handlers, same
  ``ProjectState``, same ``build_jobs`` call. There is no ESSENTIAL code path
  that can drift, and ``tests/test_gui2_tier.py`` asserts the exported bytes
  are identical in both tiers.

``ESSENTIAL`` is the default on a fresh install, because the person who has
never opened the app is exactly who a default is for.

``SRM_CAM_MODE`` pins the tier machine-wide — the same variable the first
interface reads, and the same spellings, so a lab that has already pinned its
seats does not have to do it twice.
"""
import os

from PySide6.QtCore import QSettings

ESSENTIAL = "essential"
FULL = "full"

_VALID = (ESSENTIAL, FULL)
_KEY = "ui/tier"

# The environment variable is shared with the first interface, so its
# vocabulary has to be accepted as well as ours.
_ALIASES = {"novice": ESSENTIAL, "essential": ESSENTIAL,
            "pro": FULL, "professional": FULL, "full": FULL}


def _settings():
    return QSettings("SRM-CAM", "SRM-CAM-2")


def pinned_tier():
    """The tier fixed by ``SRM_CAM_MODE``, or None if the user may choose."""
    return _ALIASES.get(os.environ.get("SRM_CAM_MODE", "").strip().lower())


def current_tier():
    """Active tier: the environment pin, else the stored choice, else ESSENTIAL."""
    pin = pinned_tier()
    if pin:
        return pin
    stored = str(_settings().value(_KEY, ESSENTIAL) or ESSENTIAL).lower()
    return stored if stored in _VALID else ESSENTIAL


def set_tier(tier):
    """Store the chosen tier. Ignored while ``SRM_CAM_MODE`` pins it."""
    if tier not in _VALID:
        raise ValueError(f"unknown tier {tier!r}; expected one of {_VALID}")
    if pinned_tier():
        return False
    _settings().setValue(_KEY, tier)
    return True


def is_full():
    return current_tier() == FULL


# What FULL adds, in the words a person would use rather than the words the
# code uses. The Interface menu shows this verbatim, so that nobody has to
# guess whether the thing they remember is gone or merely put away.
ADDED_BY_FULL = [
    "Per-operation cutting parameters — feeds, depths, offsets, stepover, "
    "V-bit geometry. In Essential the tool profile sets these.",
    "Double-sided boards — dowel or fiducial registration, the flip, "
    "top-side traces.",
    "Rework — boxing spots on a finished board to re-cut deeper.",
    "Output format and mirroring. The defaults are the ones this lab runs.",
    "Streaming a job over the link instead of through VPanel "
    "(experimental — see the warning it carries).",
    "The machine test panel, and saving your own tool profiles.",
]

# What ESSENTIAL keeps that a control-based split would have taken away, and
# why. Shown beside the list above so the split reads as a decision rather than
# an arbitrary line.
KEPT_IN_ESSENTIAL = [
    ("Bed levelling", "Probing is the thing the Arduino buys a beginner: it "
                      "makes cut depth follow the real surface, and that is "
                      "what decides whether isolation actually separates two "
                      "tracks. The stop control is part of the window, so this "
                      "is safe to keep."),
    ("The dry run", "The cheapest board-saving check in the product, and the "
                    "one a beginner needs most."),
    ("Pre-flight checks", "A beginner needs the checks more than an expert "
                          "does, not less."),
    ("Hold-down screws", "A student who screws the copper down without the "
                         "raised travel height drives the spindle into a screw "
                         "head. The checkbox is what prevents that."),
    ("Placing the job on the bed", "Without it the only way to say where the "
                                   "copper is, is to type machine coordinates "
                                   "nobody can know."),
]
