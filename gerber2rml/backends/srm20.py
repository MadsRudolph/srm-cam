"""Roland SRM-20 backend (RML-1).

Emits RML-1 directly from internal toolpaths. Reimplements the legacy
``legacy/gcode_to_rml.py`` logic with its known bugs fixed (see
``docs/design.md`` §6):

* spindle ON via ``!MC1`` (legacy wrongly used ``!MC0`` everywhere);
* XY feed via ``VS`` and plunge via ``!VZ`` (legacy ``V`` = Z speed only);
* clean Z-up header (no bogus rapid), lift before ``!MC0``;
* 40 RML units per mm (SRM-20 = 0.025 mm/unit).

Stub.
"""
