"""Trace isolation.

Union the B.Cu copper and, for each pass i, take the boundary of
``copper.buffer(r + i * stepover)`` (r = bit radius) as an isolation toolpath.
``offsets = -1`` clears all copper. Stub — see ``docs/design.md`` §4.
"""
