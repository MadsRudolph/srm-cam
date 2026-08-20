"""Checking whether a newer SRM-CAM has been released.

The network call is injected everywhere, so none of this touches GitHub.
"""
import json

import pytest

from gerber2rml.engine import updates


def _release(tag):
    """What the GitHub releases API hands back, trimmed to what we read."""
    return json.dumps({"tag_name": tag, "name": f"SRM-CAM {tag}",
                       "html_url": f"https://example.invalid/{tag}",
                       "body": "notes here"}).encode("utf-8")


def test_version_numbers_compare_numerically_not_alphabetically():
    """0.10.0 is newer than 0.9.0. String comparison gets this backwards, and
    it is the kind of bug that only shows up long after release."""
    assert updates.is_newer("0.10.0", "0.9.0")
    assert not updates.is_newer("0.9.0", "0.10.0")


def test_a_leading_v_on_the_tag_is_not_part_of_the_version():
    """Tags are v0.3.0; the app reports 0.3.0."""
    assert updates.is_newer("v0.3.0", "0.2.7")
    assert not updates.is_newer("v0.2.7", "0.2.7")


def test_reports_an_update_when_the_release_is_newer():
    result = updates.check("0.2.7", fetch=lambda url, timeout: _release("v0.3.0"))

    assert result.status == updates.UPDATE
    assert result.latest == "0.3.0"
    assert result.url == "https://example.invalid/v0.3.0"


def test_reports_up_to_date_when_running_the_latest():
    result = updates.check("0.3.0", fetch=lambda url, timeout: _release("v0.3.0"))

    assert result.status == updates.CURRENT
    assert result.latest == "0.3.0"


def test_a_development_build_ahead_of_the_last_release_is_not_an_update():
    """Running a local build newer than anything released must not be told to
    'update' back down to the release."""
    result = updates.check("0.4.0", fetch=lambda url, timeout: _release("v0.3.0"))

    assert result.status == updates.CURRENT


def test_being_offline_is_reported_plainly_and_never_raises():
    """A lab PC with no internet is normal. This is a convenience, not a
    dependency — it must not throw out of the menu handler."""
    def boom(url, timeout):
        raise OSError("getaddrinfo failed")

    result = updates.check("0.2.7", fetch=boom)

    assert result.status == updates.ERROR
    assert "could not" in result.message.lower()
    assert updates.RELEASES_PAGE in result.url


def test_garbage_from_the_server_is_an_error_not_a_crash():
    result = updates.check("0.2.7", fetch=lambda url, timeout: b"<html>502</html>")

    assert result.status == updates.ERROR


@pytest.mark.parametrize("tag", ["v0.3.0-rc1", "nightly", ""])
def test_a_tag_that_is_not_a_plain_version_is_ignored_rather_than_guessed(tag):
    """Pre-release and oddly-named tags must not be offered as 'the update'."""
    result = updates.check("0.2.7", fetch=lambda url, timeout: _release(tag))

    assert result.status == updates.ERROR


# --- the quiet check at launch --------------------------------------------

def _result(status, latest=None):
    return updates.Result(status, latest, updates.RELEASES_PAGE, "", "msg")


def test_announces_an_update_the_first_time_it_is_seen():
    assert updates.should_announce(_result(updates.UPDATE, "0.3.0"), dismissed=None)


def test_stays_quiet_when_already_up_to_date():
    assert not updates.should_announce(_result(updates.CURRENT, "0.2.7"), dismissed=None)


def test_stays_quiet_when_the_check_failed():
    """Startup is the worst possible moment to tell someone their wifi is off."""
    assert not updates.should_announce(_result(updates.ERROR), dismissed=None)


def test_does_not_mention_the_same_version_twice():
    """Told once, ignored once. Announcing 0.3.0 every launch until they act
    is how a useful notice becomes wallpaper."""
    assert not updates.should_announce(_result(updates.UPDATE, "0.3.0"), dismissed="0.3.0")
    # ...but the next release is a new thing to say.
    assert updates.should_announce(_result(updates.UPDATE, "0.4.0"), dismissed="0.3.0")
