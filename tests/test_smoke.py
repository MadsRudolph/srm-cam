"""Smoke test: the package imports and exposes a version."""

import gerber2rml


def test_version():
    assert gerber2rml.__version__
