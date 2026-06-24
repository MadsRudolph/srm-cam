"""Test the backend registry and Backend(render, ext) seam."""
from gerber2rml.backends import BACKENDS, DEFAULT_MACHINE
from gerber2rml.toolpath import Move


def test_srm20_registered():
    """SRM-20 should be registered in BACKENDS under its display name."""
    assert "Roland SRM-20" in BACKENDS
    assert "Roland SRM-20 (G-code)" in BACKENDS


def test_backends_carry_srm20_bed_size():
    """Each backend knows the SRM-20 XY work area for the fit check."""
    for b in BACKENDS.values():
        assert b.bed == (203.2, 152.4)


def test_default_machine_is_gcode_and_first():
    """We use NC/G-code: it must be the default and the first entry (the GUI
    dropdown opens on the first backend)."""
    assert DEFAULT_MACHINE == "Roland SRM-20 (G-code)"
    assert next(iter(BACKENDS)) == "Roland SRM-20 (G-code)"
    assert BACKENDS[DEFAULT_MACHINE].ext == ".nc"


def test_registry_value_renders():
    """BACKENDS values bundle a callable render fn + file extension."""
    backend = BACKENDS["Roland SRM-20"]
    assert backend.ext == ".rml"
    rml = backend.render([[Move(0, 0, 2.0, rapid=True)]], 4.0, 1.0)
    assert rml.startswith("^IN;!MC1;")


def test_gcode_backend_renders():
    """The G-code backend emits an NC program with mm + G54 work origin."""
    backend = BACKENDS["Roland SRM-20 (G-code)"]
    assert backend.ext == ".nc"
    nc = backend.render(
        [[Move(0, 0, 2.0, rapid=True), Move(0, 0, -0.1), Move(1, 0, -0.1)]],
        4.0, 1.0)
    assert nc.startswith("%")
    assert "G21" in nc and "G54" in nc          # mm, work origin
    assert "M3" in nc and "M5" in nc            # spindle on/off
    assert "M30" in nc and nc.rstrip().endswith("%")
    # plunge at plunge feed (1 mm/s -> 60 mm/min), lateral at xy feed (4 -> 240)
    assert "F60." in nc and "F240." in nc
    assert "G2 " not in nc and "G3 " not in nc  # linearised: no arc moves (G28 is fine)
    assert "G0 Z0.5" in nc                      # rapid to clearance before plunging
