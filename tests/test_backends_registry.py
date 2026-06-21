"""Test the backend registry and callable RenderFn seam."""
from gerber2rml.backends import BACKENDS
from gerber2rml.toolpath import Move


def test_srm20_registered():
    """SRM-20 should be registered in BACKENDS under its display name."""
    assert "Roland SRM-20" in BACKENDS


def test_registry_value_renders():
    """BACKENDS values should be callable render functions."""
    render = BACKENDS["Roland SRM-20"]
    rml = render([[Move(0, 0, 2.0, rapid=True)]], 4.0, 1.0)
    assert rml.startswith("^IN;!MC1;")
