"""Gerber/Excellon loading.

Reads a folder of KiCad-exported Gerbers + the Excellon drill file with
``gerbonara``, converts copper / outline / holes into ``shapely`` geometry,
mirrors for bottom-up single-sided milling, and detects/validates units.

Stub — see ``docs/design.md`` §3-4.
"""
