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
    machine: str = "Roland SRM-20"
    name: str = "board"
    gerber_dir: Path = None
    board: object = None

    def load(self, folder):
        self.gerber_dir = Path(folder)
        self.board = place_in_positive_quadrant(
            load_board(self.gerber_dir, mirror=self.mirror))
        return self.board

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

    def export(self, out_dir):
        if self.gerber_dir is None:
            raise RuntimeError("load a Gerber folder first")
        return build_jobs(self.gerber_dir, out_dir, self.name,
                          trace=self.trace, drill=self.drill, cutout=self.cutout,
                          mirror=self.mirror)
