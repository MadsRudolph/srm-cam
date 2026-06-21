"""Abstract machine-backend interface (the pluggable seam)."""
from typing import Protocol


class MachineBackend(Protocol):
    def render(self, toolpaths: list, xy_feed: float, plunge_feed: float) -> str:
        """Return machine program text for the given toolpaths."""
        ...
