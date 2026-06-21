"""Abstract machine-backend interface (the pluggable seam)."""
from typing import Protocol
from gerber2rml.toolpath import Move


class MachineBackend(Protocol):
    def render(self, toolpaths: list[list[Move]], xy_feed: float,
               plunge_feed: float, rapid_feed: float = ...) -> str:
        """Return machine program text for the given toolpaths."""
        ...
