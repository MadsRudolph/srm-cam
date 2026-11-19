"""A project: many boards, each made start to finish, ticked off as they go.

The analog synth (2026-11-19) is a dozen boards, some milled, some etched on
the laser and drilled and cut out on the mill. A project keeps the list, and
for each board its own saved setup (how it is made, where it sits, its
depths, its rework) and which of its steps are done - so the only thing left
to do at the machine is put the copper down, pick the next board, and run.

A ``.srmproj`` file is JSON beside a folder of the boards' setups
(``<name>.boards/<board>.srmcam``, written by the window). Paths to Gerber
folders and setups are stored relative to the project file where they can
be, so a project moved with its boards still opens.

Stdlib only; the window does the loading and the ticking
(``gui2/projectpage.py``).
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

SUFFIX = ".srmproj"
VERSION = 1

# The Gerber files that make a folder a board's.
_COPPER = (".gtl", ".gbl")
_OUTLINE = (".gm1", ".gko")


@dataclass
class Board:
    name: str
    gerber_dir: str                     # absolute in memory
    setup: str = ""                     # its .srmcam, absolute; "" = not yet
    # [(key, title, machine)] - the board's plan, as last opened. Empty until
    # the board has been opened once.
    steps: list = field(default_factory=list)
    done: set = field(default_factory=set)

    def progress(self):
        """(done, of) over the steps known."""
        keys = [k for k, _t, _m in self.steps]
        return sum(1 for k in keys if k in self.done), len(keys)

    def finished(self):
        d, n = self.progress()
        return n > 0 and d == n


@dataclass
class Project:
    name: str
    path: str = ""                      # the .srmproj, absolute; "" = unsaved
    boards: list = field(default_factory=list)

    # -- boards ----------------------------------------------------------
    def find(self, gerber_dir):
        """The board for ``gerber_dir``, or None."""
        want = _norm(gerber_dir)
        return next((b for b in self.boards if _norm(b.gerber_dir) == want),
                    None)

    def add(self, gerber_dir, name=None):
        """Add a board (once). Returns it."""
        have = self.find(gerber_dir)
        if have is not None:
            return have
        b = Board(name=name or board_name(gerber_dir),
                  gerber_dir=str(Path(gerber_dir).resolve()))
        names = {x.name for x in self.boards}
        base, n = b.name, 2
        while b.name in names:
            b.name = f"{base} ({n})"
            n += 1
        self.boards.append(b)
        return b

    def remove(self, board):
        self.boards = [b for b in self.boards if b is not board]

    def next_unfinished(self, after=None):
        """The first board not finished, after ``after`` in the list if
        given, wrapping round. None when all are done."""
        order = list(self.boards)
        if after in order:
            i = order.index(after)
            order = order[i + 1:] + order[:i + 1]
        return next((b for b in order if not b.finished()), None)

    def progress(self):
        d = n = 0
        for b in self.boards:
            bd, bn = b.progress()
            d, n = d + bd, n + bn
        return d, n

    def setups_dir(self):
        """Where the boards' setups go: beside the project file."""
        p = Path(self.path)
        return p.with_name(p.stem + ".boards")

    def setup_path_for(self, board):
        safe = "".join(c if c.isalnum() or c in "-_ ." else "_"
                       for c in board.name).strip() or "board"
        return self.setups_dir() / f"{safe}.srmcam"

    # -- file ------------------------------------------------------------
    def to_dict(self):
        base = Path(self.path).parent if self.path else None
        return {"version": VERSION, "name": self.name,
                "boards": [{"name": b.name,
                            "gerber_dir": _rel(b.gerber_dir, base),
                            "setup": _rel(b.setup, base) if b.setup else "",
                            "steps": [list(s) for s in b.steps],
                            "done": sorted(b.done)}
                           for b in self.boards]}

    def save(self, path=None):
        if path:
            self.path = str(Path(path).resolve())
        if not self.path:
            raise ValueError("the project has no file yet")
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, p)


def load(path):
    p = Path(path).resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "boards" not in data:
        raise ValueError(f"{p.name} is not an SRM-CAM project")
    base = p.parent
    proj = Project(name=data.get("name") or p.stem, path=str(p))
    for d in data["boards"]:
        proj.boards.append(Board(
            name=d.get("name") or board_name(d["gerber_dir"]),
            gerber_dir=_abs(d["gerber_dir"], base),
            setup=_abs(d["setup"], base) if d.get("setup") else "",
            steps=[tuple(s) for s in d.get("steps", [])],
            done=set(d.get("done", []))))
    return proj


# -- finding boards ----------------------------------------------------------

def is_gerber_dir(folder):
    """A folder with copper and an outline in it."""
    try:
        names = [n.lower() for n in os.listdir(folder)]
    except OSError:
        return False
    copper = any(n.endswith(_COPPER) or ("cu" in n and n.endswith(".gbr"))
                 for n in names)
    outline = any(n.endswith(_OUTLINE) or ("edge_cuts" in n and n.endswith(".gbr"))
                  for n in names)
    return copper and outline


def discover(folder, limit=200):
    """Every board folder under ``folder``, sorted - the synth's
    ``hardware/*/production/gerbers`` in one go."""
    found = []
    for root, dirs, _files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".")
                         and d not in ("node_modules", "__pycache__"))
        if is_gerber_dir(root):
            found.append(root)
            dirs[:] = []                    # a board's folder holds one board
        if len(found) >= limit:
            break
    return sorted(found)


def board_name(gerber_dir):
    """A board's name from its folder: ``hardware/vcf/production/gerbers``
    is "vcf", not "gerbers"."""
    p = Path(gerber_dir)
    skip = {"gerbers", "gerber", "production", "fab", "plot", "plots",
            "cam", "srm-cam"}                # srm-cam: the KiCad plugin's send
    for part in [p.name] + [q.name for q in p.parents]:
        if part and part.lower() not in skip:
            return part
    return p.name or "board"


def _norm(p):
    return os.path.normcase(str(Path(p).resolve()))


def _rel(p, base):
    if not p or base is None:
        return str(p)
    try:
        return os.path.relpath(p, base)
    except ValueError:                      # another drive on Windows
        return str(p)


def _abs(p, base):
    q = Path(p)
    return str(q if q.is_absolute() else (base / q).resolve())
