"""ProjectState: GUI-free controller holding board + jobs, producing toolpaths/exports."""
from dataclasses import dataclass, field
from pathlib import Path
from gerber2rml.config import TraceJob, DrillJob, CutoutJob
from gerber2rml.loader import load_board, place_in_positive_quadrant
from gerber2rml.engine.traces import isolate
from gerber2rml.engine.drill import drill_holes
from gerber2rml.engine.cutout import cut_outline
from gerber2rml.cli import build_jobs

@dataclass
class ProjectState:
    trace: TraceJob = field(default_factory=TraceJob)
    drill: DrillJob = field(default_factory=DrillJob)
    cutout: CutoutJob = field(default_factory=CutoutJob)
    mirror: bool = True
    machine: str = "Roland SRM-20 (G-code)"
    name: str = "board"
    gerber_dir: Path = None
    board: object = None
    place_x: float = 0.0   # job placement on the bed (mm), origin = front-left home
    place_y: float = 0.0
    _base_board: object = field(default=None, repr=False)

    def load(self, folder):
        self.gerber_dir = Path(folder)
        self._base_board = place_in_positive_quadrant(
            load_board(self.gerber_dir, mirror=self.mirror))
        self.board = self._placed(self._base_board)
        return self.board

    def _placed(self, b):
        """Board translated to the current bed placement (place_x, place_y)."""
        dx, dy = self.place_x, self.place_y
        if not dx and not dy:
            return b
        from shapely.affinity import translate
        from gerber2rml.loader import Board
        ct = b.copper_top
        return Board(
            copper=translate(b.copper, xoff=dx, yoff=dy),
            outline=translate(b.outline, xoff=dx, yoff=dy),
            holes=[(x + dx, y + dy, d) for (x, y, d) in b.holes],
            copper_top=translate(ct, xoff=dx, yoff=dy) if ct is not None else ct,
        )

    def set_placement(self, x, y):
        """Move the whole job to (x, y) mm on the bed; updates ``board`` in place
        without re-reading the Gerbers."""
        self.place_x, self.place_y = x, y
        if self._base_board is not None:
            self.board = self._placed(self._base_board)

    def toolpaths(self, op):
        if self.board is None:
            raise RuntimeError("load a Gerber folder first")
        if op == "traces":
            return isolate(self.board.copper, self.trace, outline=self.board.outline)
        if op == "drill":
            return drill_holes(self.board.holes, self.drill)
        if op == "cutout":
            return cut_outline(self.board.outline, self.cutout)
        raise ValueError(f"unknown operation: {op}")

    def export(self, out_dir, level=None):
        if self.gerber_dir is None:
            raise RuntimeError("load a Gerber folder first")
        return build_jobs(self.gerber_dir, out_dir, self.name,
                          trace=self.trace, drill=self.drill, cutout=self.cutout,
                          mirror=self.mirror, machine=self.machine,
                          offset=(self.place_x, self.place_y), level=level)
