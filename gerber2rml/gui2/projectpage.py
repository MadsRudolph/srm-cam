"""The Project page: many boards, each ticked off step by step.

A third page beside CNC and Laser (Ctrl+3). It lists the boards of a project
(``gerber2rml/project.py``) with their steps as tick boxes - the mill's runs
and the laser's jobs, from each board's own plan - and what is left. Open a
board and the window switches to it as it was left: its setup (saved into
the project when another board is opened) and its ticks. A step ticks itself
when its run finishes (the rail's done marks); a tick can be set or cleared
by hand, here or on the rail.

The window keeps one :class:`ProjectController` (``win.project_ctl``); this
module owns everything about projects so the window only calls it at the
few points where a board is loaded or a step is done.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from gerber2rml import project as pj
from gerber2rml.gui2 import theme, widgets

_KEY_ROLE = Qt.UserRole


TOP_TRACES = "laser_traces_top"


def checklist_steps(plan, board=None):
    """``[(key, title, machine)]``: the steps of a board's plan worth ticking
    off - the mill's runs and the laser's jobs, not hand-offs. A board with
    copper on both faces has its traces etched twice on the laser, one face
    at a time (the laser page's copper face): a tick for each."""
    if plan is None:
        return []
    two = board is not None and getattr(board, "copper_top", None) is not None \
        and not board.copper_top.is_empty
    out = []
    for s in plan.steps:
        if s.kind not in ("run", "laser"):
            continue
        machine = s.machine or ("laser" if s.kind == "laser" else "mill")
        if s.key == "laser_traces" and two:
            out.append((s.key, s.title + " · B.Cu (bottom)", machine))
            out.append((TOP_TRACES, s.title + " · F.Cu (top)", machine))
        else:
            out.append((s.key, s.title, machine))
    return out


class ProjectController:
    """The window's project: which board is open, saving, ticking."""

    def __init__(self, win):
        self.win = win
        self.project = None
        self.current = None             # the project's board now loaded
        self.page = ProjectPage(self)
        self._loading = False

    # -- files -------------------------------------------------------------
    def new(self, path, name=None):
        self.project = pj.Project(name=name or Path(path).stem)
        self.project.save(path)
        self.current = None
        self._remember(path)
        self.page.refresh()

    def open(self, path):
        self.project = pj.load(path)
        self.current = None
        self._remember(path)
        self.page.refresh()

    def restore_last(self):
        """Reopen the project that was open when the app was last closed -
        the list, not a board: the board is opened from it."""
        from gerber2rml.gui2 import workspace
        last = workspace.setting("project/last", "")
        if last and Path(last).is_file():
            try:
                self.open(last)
            except (OSError, ValueError):
                pass

    def _remember(self, path):
        from gerber2rml.gui2 import workspace
        workspace.set_setting("project/last", str(path))

    def save(self):
        if self.project is not None and self.project.path:
            try:
                self.project.save()
            except OSError as e:
                self.win.say("warn", f"The project could not be saved: {e}")

    # -- boards ------------------------------------------------------------
    def add_folders(self, folders):
        if self.project is None:
            return []
        added = [self.project.add(f) for f in folders]
        self.save()
        self.page.refresh()
        return added

    def remove(self, board):
        if self.project is None:
            return
        if board is self.current:
            self.current = None
        self.project.remove(board)
        self.save()
        self.page.refresh()

    def leave_current(self):
        """Keep the open board's setup and ticks in the project."""
        b = self.current
        if b is None or self.project is None or self.win.state.board is None:
            return
        try:
            path = self.project.setup_path_for(b)
            self.win.write_setup(path)
            b.setup = str(path)
        except OSError as e:
            self.win.say("warn", f"{b.name}'s setup could not be kept: {e}")
        self._take_steps(b)
        self.save()

    def open_board(self, board):
        """Switch the window to ``board``, as it was left."""
        if self.project is None or board is None:
            return False
        if board is self.current:
            return True
        self.leave_current()
        self._loading = True
        try:
            if board.setup and Path(board.setup).is_file():
                self.win.load_setup(board.setup)
            else:
                # The first time: as File > Open does it - sides, method
                # (KiCad's choice, else guessed), the board's own choices.
                self.win.load_folder(board.gerber_dir)
                if self.win.state.board is not None:
                    self.win._detect_sides()
                    self.win._detect_method()
                    self.win.autorun_page.board_opened()
        finally:
            self._loading = False
        if self.win.state.board is None:
            return False
        self.current = board
        trav = self.win.traveller
        trav.clear_done()
        plan_keys = {k for k, _t, _m in checklist_steps(self.win.plan, self.win.state.board)}
        for key in board.done:
            if key in plan_keys:
                trav.set_done(key, True)
        self._take_steps(board)
        self.save()
        self.page.refresh()
        self.win.say("ok", f"{board.name} is open"
                     + (f": {board.progress()[0]} of {board.progress()[1]} "
                        f"steps done." if board.steps else "."))
        return True

    def open_next(self):
        if self.project is None:
            return False
        b = self.project.next_unfinished(after=self.current)
        if b is None:
            self.win.say("ok", "Every board in the project is done.")
            return False
        return self.open_board(b)

    def _take_steps(self, board):
        steps = checklist_steps(self.win.plan, self.win.state.board)
        if steps:
            board.steps = steps
            keys = {k for k, _t, _m in steps}
            board.done = {k for k in board.done if k in keys} | {
                k for k in keys if self.win.traveller.is_done(k)}

    # -- ticks -------------------------------------------------------------
    def on_done(self, key, on):
        """The rail marked ``key`` done or not: the open board's tick."""
        b = self.current
        if b is None or self._loading:
            return
        if not any(k == key for k, _t, _m in b.steps):
            self._take_steps(b)
        (b.done.add if on else b.done.discard)(key)
        self.save()
        self.page.refresh_soon()

    def set_tick(self, board, key, on):
        """A tick changed on the Project page."""
        (board.done.add if on else board.done.discard)(key)
        if board is self.current:
            self.win.traveller.set_done(key, on)      # the rail follows
        self.save()
        # Not now: this runs inside the tick's own itemChanged, and a refresh
        # deletes that item under Qt (an access violation on Windows CI).
        self.page.refresh_soon()

    def board_loaded_elsewhere(self):
        """The window loaded a board by other means (File > Open...): if it
        is not the project's open board, the project lets go of it."""
        if self._loading or self.current is None:
            return
        gd = getattr(self.win.state, "gerber_dir", None)
        if gd is None or self.project.find(gd) is not self.current:
            # Another board is up now; the one the project had was replaced
            # without being kept, so its last ticks stay as they were saved.
            self.current = None
            self.page.refresh()


class ProjectPage(QWidget):
    """The list of boards and their steps."""

    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.setObjectName("projectPage")
        self.setStyleSheet(f"QWidget#projectPage {{ background: {theme.INK}; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(theme.GAP_L, theme.GAP_L, theme.GAP_L, theme.GAP_L)
        v.setSpacing(theme.GAP_M)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(widgets.eyebrow("Project"))
        self.title = QLabel("No project open")
        self.title.setFont(theme.font("sub"))
        col.addWidget(self.title)
        self.summary = widgets.hint("")
        col.addWidget(self.summary)
        head.addLayout(col, 1)
        self.new_btn = widgets.button("New project…", on=self.action_new)
        self.open_btn = widgets.button("Open project…", on=self.action_open)
        for b in (self.new_btn, self.open_btn):
            head.addWidget(b)
        v.addLayout(head)

        bar = QHBoxLayout()
        self.add_btn = widgets.button(
            "Add boards…", on=self.action_add,
            tip="Pick a folder: every board's Gerber folder under it is added "
                "(the synth's hardware folder adds all its boards).")
        self.remove_btn = widgets.button("Remove", kind="ghost",
                                         on=self.action_remove)
        self.open_board_btn = widgets.button(
            "Open board", kind="primary", on=self.action_open_board,
            tip="Switch to the chosen board, as it was left")
        self.next_btn = widgets.button(
            "Open next unfinished", on=lambda: self.ctl.open_next())
        for b in (self.add_btn, self.remove_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        for b in (self.next_btn, self.open_board_btn):
            bar.addWidget(b)
        v.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Board / step", "Machine", "Done"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setRootIsDecorated(True)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.tree.itemSelectionChanged.connect(self._sync_buttons)
        self.tree.itemSelectionChanged.connect(self._sync_preview)
        # The chosen board as it looks, beside the list: which is which on
        # the bench (2026-11-23).
        from gerber2rml.gui2.board_preview import BoardPreview
        self.preview = BoardPreview()
        body = QHBoxLayout()
        body.setSpacing(theme.GAP_L)
        body.addWidget(self.tree, 3)
        body.addWidget(self.preview, 2)
        v.addLayout(body, 1)
        self.note = widgets.hint(
            "Open a board to start it: it comes back as it was left, and its "
            "steps tick themselves as they finish on the mill or the laser.")
        v.addWidget(self.note)
        self._filling = False
        self.refresh()

    # -- what is shown ---------------------------------------------------
    def refresh_soon(self):
        """Refresh once the event in hand is done with the tree's items."""
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self, self.refresh)

    def refresh(self):
        proj = self.ctl.project
        self._filling = True
        try:
            expanded = {self.tree.topLevelItem(i).data(0, _KEY_ROLE)
                        for i in range(self.tree.topLevelItemCount())
                        if self.tree.topLevelItem(i).isExpanded()}
            sel = self._selected_board()
            self.tree.clear()
            if proj is None:
                self.title.setText("No project open")
                self.summary.setText("New project… to start one, or Open "
                                     "project… for one you have.")
            else:
                self.title.setText(proj.name)
                d, n = proj.progress()
                done_boards = sum(1 for b in proj.boards if b.finished())
                self.summary.setText(
                    f"{len(proj.boards)} boards, {done_boards} finished · "
                    f"{d} of {n} steps done")
                for b in proj.boards:
                    self._add_board(b, b.name in expanded or b is self.ctl.current,
                                    b is sel)
        finally:
            self._filling = False
        self._sync_buttons()

    def _add_board(self, b, expand, select):
        d, n = b.progress()
        state = ("done" if b.finished() else
                 f"{d}/{n}" if n else "not opened yet")
        it = QTreeWidgetItem([b.name + ("   ◀ open" if b is self.ctl.current
                                        else ""), "", state])
        it.setData(0, _KEY_ROLE, b.name)
        it.setToolTip(0, b.gerber_dir)
        f = it.font(0)
        f.setBold(b is self.ctl.current)
        it.setFont(0, f)
        self.tree.addTopLevelItem(it)
        for key, title, machine in b.steps:
            s = QTreeWidgetItem([title, machine, ""])
            s.setData(0, _KEY_ROLE, key)
            s.setFlags(s.flags() | Qt.ItemIsUserCheckable)
            s.setCheckState(2, Qt.Checked if key in b.done else Qt.Unchecked)
            it.addChild(s)
        it.setExpanded(expand)
        if select:
            self.tree.setCurrentItem(it)

    def _board_of(self, item):
        proj = self.ctl.project
        if proj is None or item is None:
            return None
        top = item if item.parent() is None else item.parent()
        name = top.data(0, _KEY_ROLE)
        return next((b for b in proj.boards if b.name == name), None)

    def _selected_board(self):
        return self._board_of(self.tree.currentItem())

    def _sync_preview(self):
        b = self._selected_board()
        if b is None:
            return self.preview.show_board("", None)
        if getattr(self, "_previewed", None) == (b.name, b.gerber_dir):
            return                              # a step of the same board
        self._previewed = (b.name, b.gerber_dir)
        self.preview.show_board(b.name, b.gerber_dir)

    def _sync_buttons(self):
        has = self.ctl.project is not None
        sel = self._selected_board() is not None
        self.add_btn.setEnabled(has)
        self.next_btn.setEnabled(has and bool(self.ctl.project.boards))
        self.remove_btn.setEnabled(sel)
        self.open_board_btn.setEnabled(sel)

    # -- what is done ----------------------------------------------------
    def _item_changed(self, item, column):
        if self._filling or column != 2 or item.parent() is None:
            return
        b = self._board_of(item)
        if b is not None:
            self.ctl.set_tick(b, item.data(0, _KEY_ROLE),
                              item.checkState(2) == Qt.Checked)

    def _double_clicked(self, item, _col):
        if item.parent() is None:
            self.ctl.open_board(self._board_of(item))

    def action_open_board(self):
        self.ctl.open_board(self._selected_board())

    def action_remove(self):
        b = self._selected_board()
        if b is not None:
            self.ctl.remove(b)

    def action_new(self):
        from gerber2rml.gui2 import workspace
        path, _ = QFileDialog.getSaveFileName(
            self, "New project", workspace.remembered_dir("project", "projects")
            + "/project" + pj.SUFFIX, f"SRM-CAM project (*{pj.SUFFIX})")
        if not path:
            return
        if not path.endswith(pj.SUFFIX):
            path += pj.SUFFIX
        workspace.remember_dir("project", path)
        self.ctl.leave_current()
        self.ctl.new(path)

    def action_open(self):
        from gerber2rml.gui2 import workspace
        path, _ = QFileDialog.getOpenFileName(
            self, "Open a project",
            workspace.remembered_dir("project", "projects"),
            f"SRM-CAM project (*{pj.SUFFIX});;All files (*)")
        if not path:
            return
        workspace.remember_dir("project", path)
        self.ctl.leave_current()
        try:
            self.ctl.open(path)
        except (OSError, ValueError) as e:
            self.ctl.win.report_error("That project could not be opened", e,
                                      "Projects end in .srmproj.")

    def action_add(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Add the boards in a folder")
        if not folder:
            return
        found = pj.discover(folder)
        if not found:
            self.ctl.win.say("warn", "No Gerber folders were found there: a "
                                     "board's folder holds its copper and its "
                                     "outline.")
            return
        before = len(self.ctl.project.boards)
        self.ctl.add_folders(found)
        added = len(self.ctl.project.boards) - before
        self.ctl.win.say("ok", f"{added} board{'s' if added != 1 else ''} added"
                         + (f" ({len(found) - added} already in the project)."
                            if added < len(found) else "."))
