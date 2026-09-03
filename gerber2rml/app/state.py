"""ProjectState: GUI-free controller holding board + jobs, producing toolpaths/exports."""
from dataclasses import dataclass, field
from pathlib import Path
from gerber2rml.config import TraceJob, DrillJob, CutoutJob
from gerber2rml.engine.traces import isolate
from gerber2rml.engine.drill import drill_holes
from gerber2rml.engine.cutout import cut_outline
from gerber2rml.cli import build_jobs, write_jobs
from gerber2rml.app import panel as panel_mod


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
    rotate: int = 0        # whole-job rotation in degrees (0/90/180/270), CCW
    _base_board: object = field(default=None, repr=False)
    # The boards on the sheet, in the order they were added. One entry is the
    # ordinary job. ``gerber_dir``, ``place_x``, ``place_y``, ``rotate`` and
    # ``_base_board`` above always describe ``boards[current]``, so everything
    # written for one board keeps reading the board being worked on, and
    # ``board`` is all of them composed into one.
    boards: list = field(default_factory=list, repr=False)
    current: int = 0

    # -- the sheet ---------------------------------------------------------
    def load(self, folder):
        """Start a job from one Gerber folder, replacing whatever was loaded."""
        self.boards = [panel_mod.read_board(folder, mirror=self.mirror)]
        self.current = 0
        self._sync()
        return self.board

    def add_board(self, folder, gap=panel_mod.PANEL_GAP_MM):
        """Put another board on the sheet, beside the ones already there, and
        make it the one being worked on. Returns the new member."""
        if not self.boards:
            self.load(folder)
            return self.boards[0]
        m = panel_mod.read_board(folder, mirror=self.mirror,
                                 taken=[b.name for b in self.boards])
        m.place_x, m.place_y = panel_mod.next_slot(self.boards, m, gap)
        self.boards.append(m)
        self.current = len(self.boards) - 1
        self._sync()
        return m

    def remove_board(self, index):
        """Take one board off the sheet. Returns it."""
        m = self.boards.pop(index)
        if index < self.current:
            self.current -= 1
        self.current = max(0, min(self.current, len(self.boards) - 1))
        self._sync()
        return m

    def select_board(self, index):
        """Make ``boards[index]`` the one placement and rotation act on."""
        if not 0 <= index < len(self.boards):
            raise IndexError(index)
        self.current = index
        self._sync_current()

    @property
    def is_panel(self):
        return len(self.boards) > 1

    def move_all(self, dx, dy):
        """Slide every board by the same amount: the panel keeps its shape."""
        for m in self.boards:
            m.place_x += dx
            m.place_y += dy
        self._sync()

    def arrange(self, gap=panel_mod.PANEL_GAP_MM):
        """Lay the boards side by side, left to right, ``gap`` mm apart."""
        panel_mod.arrange_row(self.boards, gap)
        self._sync()

    def reload(self):
        """Re-read every board from its folder - after ``mirror`` changes."""
        for m in self.boards:
            m.base = panel_mod.read_board(m.gerber_dir, mirror=self.mirror).base
        self._sync()

    def panel_summary(self):
        """``[(name, x0, y0, rotate)]``: each board's front-left corner on the
        bed in machine mm, for the run plan."""
        out = []
        for m in self.boards:
            x0, y0, _x1, _y1 = m.bounds()
            out.append((m.name, x0, y0, m.rotate))
        return out

    def rebuild(self):
        """Recompose ``board`` after a member was edited directly."""
        self._sync()

    def _sync_current(self):
        m = self.boards[self.current]
        self.gerber_dir, self._base_board = m.gerber_dir, m.base
        self.place_x, self.place_y, self.rotate = m.place_x, m.place_y, m.rotate

    def _sync(self):
        """Rebuild ``board`` from the members and point the single-board fields
        at the current one."""
        if not self.boards:
            self.board = self._base_board = self.gerber_dir = None
            return
        self._sync_current()
        self.board = panel_mod.compose([m.board() for m in self.boards])

    # -- placement ---------------------------------------------------------
    def set_placement(self, x, y):
        """Move the current board to (x, y) mm on the bed; updates ``board``
        in place without re-reading the Gerbers."""
        self.place_x, self.place_y = x, y
        if self.boards:
            m = self.boards[self.current]
            m.place_x, m.place_y = x, y
            self._sync()

    def set_rotation(self, angle):
        """Turn the current board to ``angle`` degrees (snapped to 0/90/180/
        270); recomputes ``board`` without re-reading the Gerbers."""
        self.rotate = int(round(angle / 90.0)) * 90 % 360
        if self.boards:
            self.boards[self.current].rotate = self.rotate
            self._sync()

    # -- output ------------------------------------------------------------
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
        if self.is_panel:
            # The members are already placed, so the composed geometry goes
            # straight to the writer; nothing is re-read from disk.
            return write_jobs(self.board, out_dir, self.name,
                              trace=self.trace, drill=self.drill,
                              cutout=self.cutout, mirror=self.mirror,
                              machine=self.machine, level=level,
                              panel=self.panel_summary())
        return build_jobs(self.gerber_dir, out_dir, self.name,
                          trace=self.trace, drill=self.drill, cutout=self.cutout,
                          mirror=self.mirror, machine=self.machine,
                          offset=(self.place_x, self.place_y), level=level,
                          rotate=self.rotate)
