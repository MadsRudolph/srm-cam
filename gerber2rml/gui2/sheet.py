"""The run sheet: the best thing this program produces, given a screen.

The engine writes ``<name>_runplan.txt`` — the order, the bit for each step,
where to re-zero Z, what the dry run proves. It is the single most useful
artifact in the product and in the first interface it is a text file lying in a
folder beside four ``.nc`` files, which is to say most people never read it.

So the success state of an export is not a message box saying "wrote 6 files".
It is this: the plan, typeset, on the stage, where the board was a second ago.
It can be copied, it can be printed, and the folder it describes is one click
away.

It is styled as a document rather than as an interface — paper values from the
palette, a measure that stops around 70 characters, rules instead of boxes —
because that is what it is. Nothing on it is a control except the three buttons
at the top.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QScrollArea, QFrame, QSizePolicy)

from gerber2rml.gui2 import theme, widgets
from gerber2rml.engine.estimate import format_duration


class RunSheet(QWidget):
    """The exported plan, as a document."""

    open_folder = Signal()
    copy_text = Signal()
    back = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Scoped by object name, always. A stylesheet set on a container
        # WITHOUT a selector is applied to every descendant as well, and it
        # beats the application stylesheet — which silently stripped the fill
        # off the primary button in this bar and left an outline with
        # near-invisible text inside it.
        self.setObjectName("sheetRoot")
        self.setStyleSheet(f"QWidget#sheetRoot {{ background: {theme.INK}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("sheetBar")
        bar.setStyleSheet(f"QWidget#sheetBar {{ background: {theme.BASE}; }}")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(theme.GAP_L, theme.GAP_M, theme.GAP_L, theme.GAP_M)
        bh.setSpacing(theme.GAP_S)
        self.head = QLabel("Job exported")
        self.head.setFont(theme.font("head"))
        bh.addWidget(self.head)
        bh.addStretch(1)
        bh.addWidget(widgets.button("Open the folder", on=self.open_folder.emit))
        bh.addWidget(widgets.button("Copy the plan", on=self.copy_text.emit,
                                    tip="Copies this sheet as plain text — "
                                        "paste it into a lab logbook, or send "
                                        "it to whoever is running the machine."))
        bh.addWidget(widgets.button("Back to the board", kind="primary",
                                    on=self.back.emit))
        outer.addWidget(bar)
        outer.addWidget(widgets.rule())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setObjectName("sheetScroll")
        self.scroll.setStyleSheet(
            f"QScrollArea#sheetScroll {{ background: {theme.INK};"
            f" border: none; }}")
        outer.addWidget(self.scroll, 1)
        self._page = None
        self._text = ""

    def text(self):
        return self._text

    def show_plan(self, plan, *, name, out_dir, machine, leveled=False,
                  double_sided=False, panel=None):
        """``panel``: ``[(name, x, y, rotate)]`` for a sheet carrying several
        boards - each one's front-left corner in machine mm, printed so the
        operator can check the boards sit where the files expect them."""
        page = QWidget()
        page.setObjectName("sheetPage")
        page.setStyleSheet(f"QWidget#sheetPage {{ background: {theme.INK}; }}")
        wrap = QHBoxLayout(page)
        wrap.setContentsMargins(0, theme.GAP_XL, 0, theme.GAP_XL)
        wrap.addStretch(1)

        doc = QWidget()
        doc.setObjectName("sheetDoc")
        doc.setStyleSheet(f"QWidget#sheetDoc {{ background: {theme.SHEET}; }}")
        doc.setFixedWidth(700)
        v = QVBoxLayout(doc)
        v.setContentsMargins(52, 44, 52, 52)
        v.setSpacing(theme.GAP_M)

        lines = []

        def add_line(text):
            lines.append(text)

        # -- masthead ----------------------------------------------------
        eb = QLabel("SRM-20 run plan")
        eb.setFont(theme.font("label"))
        eb.setStyleSheet(f"color: {theme.SHEET_INK_2}; background: transparent;")
        v.addWidget(eb)
        t = QLabel(name)
        t.setFont(theme.font("hero"))
        t.setStyleSheet(f"color: {theme.SHEET_INK}; background: transparent;")
        v.addWidget(t)
        tools = ("one " + plan.tool_label if plan.single_tool
                 else f"{len(plan.tools)} tools")
        sub = QLabel(f"{machine} · "
                     f"{'double-sided' if double_sided else 'single-sided'} · "
                     f"{tools}"
                     + (" · cut warped to the probed surface" if leveled else ""))
        sub.setFont(theme.font("body"))
        sub.setStyleSheet(f"color: {theme.SHEET_INK_2}; background: transparent;")
        v.addWidget(sub)
        add_line(f"SRM-20 run plan — {name}")
        add_line(f"{machine} · "
                 f"{'double-sided' if double_sided else 'single-sided'}"
                 + (" · levelled" if leveled else ""))
        add_line(f"files in: {out_dir}")
        add_line("")
        v.addSpacing(theme.GAP_S)
        v.addWidget(self._rule())
        v.addSpacing(theme.GAP_S)

        folder = QLabel(str(out_dir))
        folder.setFont(theme.font("small", mono=True))
        folder.setStyleSheet(f"color: {theme.SHEET_INK_2}; background: transparent;")
        folder.setWordWrap(True)
        v.addWidget(folder)
        if panel:
            v.addSpacing(theme.GAP_S)
            head = QLabel(f"{len(panel)} boards on the sheet")
            head.setFont(theme.font("label"))
            head.setStyleSheet(f"color: {theme.SHEET_INK_2}; background: transparent;")
            v.addWidget(head)
            add_line(f"{len(panel)} boards on the sheet (front-left corner, "
                     f"machine mm):")
            for bname, x, y, rot in panel:
                where = f"X{x:.2f} Y{y:.2f}" + (f", turned {rot % 360}°"
                                                if rot % 360 else "")
                row = QLabel(f"{bname} — {where}")
                row.setFont(theme.font("small", mono=True))
                row.setStyleSheet(f"color: {theme.SHEET_INK}; background: transparent;")
                v.addWidget(row)
                add_line(f"   {bname}: {where}")
            add_line("")
        v.addSpacing(theme.GAP_M)

        # -- the standing rule -------------------------------------------
        # What to say about Z depends on whether the job changes bits at all.
        # On a one-bit job "re-zero Z after every bit change" is an instruction
        # with no occasions, and printing it anyway is how the half of the
        # sentence that matters — never re-zero XY — stops being read.
        one_bit = plan.single_tool
        rulebox = QLabel(
            "Set the work origin in VPanel before the first file, then send "
            "each program with Cut → Add → Output.\n"
            + (f"One {plan.tool_label} does every step below, so Z is zeroed "
               f"once and never again. "
               if one_bit else
               "Re-zero Z after every bit change. ")
            + "Never re-zero XY — the passes only line up with each other "
              "because they share one origin.")
        rulebox.setFont(theme.font("body"))
        rulebox.setWordWrap(True)
        rulebox.setStyleSheet(
            f"color: {theme.SHEET_INK}; background: transparent;"
            f" border-left: 2px solid {theme.CAUTION}; padding-left: 14px;")
        v.addWidget(rulebox)
        add_line("Set the work origin in VPanel, then send each program with "
                 "Cut -> Add -> Output.")
        add_line("One " + plan.tool_label + " for every step: Z is zeroed once."
                 if one_bit else
                 "Re-zero Z after every bit change.")
        add_line("NEVER re-zero XY.")
        add_line("")
        v.addSpacing(theme.GAP_M)

        # -- the steps ---------------------------------------------------
        for step in plan:
            if step.kind == "tool":
                continue
            v.addWidget(self._step_row(step, lines))

        v.addSpacing(theme.GAP_S)
        v.addWidget(self._rule())
        v.addSpacing(theme.GAP_S)

        total = plan.total_seconds
        if total:
            trow = QWidget()
            th = QHBoxLayout(trow)
            th.setContentsMargins(0, 0, 0, 0)
            lab = QLabel("Total cutting time")
            lab.setFont(theme.font("label"))
            lab.setStyleSheet(f"color: {theme.SHEET_INK_2}; background: transparent;")
            th.addWidget(lab)
            th.addStretch(1)
            val = QLabel("~" + format_duration(total))
            val.setFont(theme.font("head", mono=True))
            val.setStyleSheet(f"color: {theme.SHEET_INK}; background: transparent;")
            th.addWidget(val)
            v.addWidget(trow)
            add_line(f"TOTAL cutting time: ~{format_duration(total)}")
            foot = QLabel(
                "Excludes tool changes, spin-up and pauses. It runs low on "
                "trace jobs — the machine slows for every corner and a trace "
                "pass is nothing but corners.")
            foot.setFont(theme.font("micro"))
            foot.setWordWrap(True)
            foot.setStyleSheet(f"color: {theme.SHEET_INK_2}; background: transparent;")
            v.addWidget(foot)

        wrap.addWidget(doc)
        wrap.addStretch(1)
        self.scroll.setWidget(page)
        self._page = page
        self._text = "\n".join(lines)
        self.head.setText(f"{name} — exported")

    # -- pieces ------------------------------------------------------------
    def _rule(self):
        f = QFrame()
        f.setFixedHeight(1)
        f.setStyleSheet(f"background: {theme.SHEET_RULE}; border: none;")
        return f

    def _step_row(self, step, lines):
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 6, 0, 10)
        h.setSpacing(theme.GAP_M)

        num = QLabel(str(step.ordinal) if step.numbered else "·")
        num.setFont(theme.font("title"))
        num.setFixedWidth(38)
        num.setAlignment(Qt.AlignRight | Qt.AlignTop)
        num.setStyleSheet(
            f"color: {theme.SHEET_INK if step.numbered else theme.SHEET_INK_2};"
            f" background: transparent;")
        h.addWidget(num)

        col = QWidget()
        col.setStyleSheet("background: transparent;")
        cv = QVBoxLayout(col)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(3)

        top = QWidget()
        top.setStyleSheet("background: transparent;")
        th = QHBoxLayout(top)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(theme.GAP_S)
        t = QLabel(step.title)
        t.setFont(theme.font("sub" if step.kind == "run" else "body"))
        t.setStyleSheet(
            f"color: {theme.SHEET_INK if step.kind == 'run' else theme.SHEET_INK_2};"
            f" background: transparent;")
        th.addWidget(t)
        if step.caution:
            c = QLabel(step.caution)
            c.setFont(theme.font("micro"))
            colour = theme.DANGER if step.irreversible else theme.CAUTION
            c.setStyleSheet(f"color: {colour}; background: transparent;")
            th.addWidget(c)
        th.addStretch(1)
        if step.seconds is not None:
            e = QLabel("~" + format_duration(step.seconds))
            e.setFont(theme.font("small", mono=True))
            e.setStyleSheet(f"color: {theme.SHEET_INK_2}; background: transparent;")
            th.addWidget(e)
        cv.addWidget(top)

        if step.file:
            f = QLabel(step.file)
            f.setFont(theme.font("small", mono=True))
            f.setStyleSheet(f"color: {theme.SHEET_INK}; background: transparent;")
            cv.addWidget(f)
        if step.detail:
            d = QLabel(step.detail)
            d.setFont(theme.font("small"))
            d.setWordWrap(True)
            d.setStyleSheet(f"color: {theme.SHEET_INK_2}; background: transparent;")
            cv.addWidget(d)
        h.addWidget(col, 1)

        prefix = f"{step.ordinal}." if step.numbered else "  ·"
        est = f"  (~{format_duration(step.seconds)})" if step.seconds else ""
        lines.append(f"{prefix} {step.title}{est}")
        if step.file:
            lines.append(f"      {step.file}")
        if step.detail:
            lines.append(f"      {step.detail}")
        if step.caution:
            lines.append(f"      !! {step.caution}")
        return row
