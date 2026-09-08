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


def _resolve(url, timeout):
    """Where ``.../releases/latest`` redirects to: ``.../releases/tag/v0.5.0``.

    A HEAD request, so no page body comes back — only the final address.
    Unlike the API this has no per-address quota, which matters in a lab
    where thirty laptops share one public IP and the API allows sixty
    anonymous calls an hour between them.
    """
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "SRM-CAM"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.url


def check(current, fetch=None, timeout=6.0, resolve=None):
    """Compare *current* against the newest GitHub release.

    The version comes from the releases page's redirect (``resolve``); the
    API (``fetch``) is only asked for the release notes, and only as a bonus,
    because it is rate-limited per address. If the redirect cannot be read
    the API is the fallback. Injecting either replaces the network entirely.

    Never raises: an offline PC, a rate limit or a proxy returning HTML all
    come back as ERROR with something a person can read. This is a
    convenience, and a convenience that throws is worse than none.
    """
    if fetch is None and resolve is None:
        fetch, resolve = _fetch, _resolve

    tag, url, notes, why = None, RELEASES_PAGE, "", ""
    if resolve is not None:
        try:
            final = resolve(RELEASES_PAGE, timeout)
            tag = final.rstrip("/").rsplit("/", 1)[-1]
            url = final
        except Exception as exc:                               # noqa: BLE001
            tag, why = None, str(exc)

    if tag is None or (parse_version(tag) is None and fetch is not None
                       and resolve is None):
        # No redirect to read (or a test that only injected the API): ask it.
        if fetch is None:
            return Result(ERROR, None, RELEASES_PAGE, "",
                          f"Could not check for updates: {why}")
        try:
            raw = fetch(RELEASES_API, timeout)
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            tag = data.get("tag_name", "")
            url = data.get("html_url") or RELEASES_PAGE
            notes = (data.get("body") or "").strip()
        except Exception as exc:                               # noqa: BLE001
            return Result(ERROR, None, RELEASES_PAGE, "",
                          f"Could not check for updates: {why or exc}")
    elif fetch is not None:
        # Notes are a bonus. A 403 from the quota, or anything else, is not
        # worth a word; the download page has them.
        try:
            raw = fetch(RELEASES_API, timeout)
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            if parse_version(data.get("tag_name", "")) == parse_version(tag):
                notes = (data.get("body") or "").strip()
        except Exception:                                      # noqa: BLE001
            pass

    version = parse_version(tag)
    if version is None:
        return Result(ERROR, None, RELEASES_PAGE, "",
                      f"Could not read the latest version (latest tag: {tag!r}).")

    latest = ".".join(str(p) for p in version)
    if is_newer(latest, current):
        return Result(UPDATE, latest, url, notes,
                      f"SRM-CAM {latest} is available. You are running {current}.")
    return Result(CURRENT, latest, url, notes,
                  f"SRM-CAM {current} is up to date.")


def should_announce(result, dismissed=None):
    """Is this worth interrupting someone with, unprompted, at launch?

    Only a real update they have not already been told about. A failed check
    stays silent: startup is the worst moment to tell someone their wifi is
    off, and they did not ask.
    """
    if result.status != UPDATE:
        return False
    return result.latest != dismissed
