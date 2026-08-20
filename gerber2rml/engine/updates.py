"""Is there a newer SRM-CAM than the one running?

A frozen app cannot safely replace itself while it is running, so this does
not try to: it finds out whether a newer release exists and points at the
download. The install is the user's click, in their browser.

Deliberately stdlib-only and injectable: the lab PC may have no internet, and
none of this is worth a dependency or a test that touches GitHub.
"""
import json
import re
import urllib.request
from collections import namedtuple

REPO = "MadsRudolph/srm-cam"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"

CURRENT, UPDATE, ERROR = "current", "update", "error"

Result = namedtuple("Result", "status latest url notes message")

_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")


def parse_version(text):
    """'v0.3.0' -> (0, 3, 0). None if it is not a plain version number.

    Anything else — a pre-release, a nightly, a name — is deliberately not
    guessed at: offering it as "the update" would be worse than saying nothing.
    """
    m = _VERSION_RE.match((text or "").strip())
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def is_newer(candidate, current):
    """Is *candidate* a later version than *current*? Numerically — 0.10 > 0.9."""
    a, b = parse_version(candidate), parse_version(current)
    if a is None or b is None:
        return False
    return a > b


def _fetch(url, timeout):
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": "SRM-CAM"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def check(current, fetch=None, timeout=6.0):
    """Compare *current* against the newest GitHub release.

    Never raises: an offline PC, a rate limit or a proxy returning HTML all
    come back as ERROR with something a person can read. This is a
    convenience, and a convenience that throws is worse than none.
    """
    fetch = fetch or _fetch
    try:
        raw = fetch(RELEASES_API, timeout)
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        tag = data.get("tag_name", "")
    except Exception as exc:                                   # noqa: BLE001
        return Result(ERROR, None, RELEASES_PAGE, "",
                      f"Could not check for updates: {exc}")

    version = parse_version(tag)
    if version is None:
        return Result(ERROR, None, RELEASES_PAGE, "",
                      f"Could not read the latest version (latest tag: {tag!r}).")

    latest = ".".join(str(p) for p in version)
    url = data.get("html_url") or RELEASES_PAGE
    notes = (data.get("body") or "").strip()

    if is_newer(latest, current):
        return Result(UPDATE, latest, url, notes,
                      f"SRM-CAM {latest} is available. You are running {current}.")
    return Result(CURRENT, latest, url, notes,
                  f"SRM-CAM {current} is up to date.")
