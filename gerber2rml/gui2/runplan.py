"""The run plan, as a data structure the interface is built out of.

The first interface described the machining order in three places that could
disagree, and fixing that took a commit of its own. This interface does not
have three places: there is one list of :class:`Step`, and the left rail, the
stage, the inspector, the export dialog and the printed run sheet are all
renderings of it. If the order is wrong it is wrong everywhere at once, which
is the only kind of wrong that gets noticed.

The order itself is not invented here. It mirrors, step for step, the order in
which ``cli.build_jobs`` and ``doublesided.build_double_sided`` write their
files — and ``tests/test_gui2_runplan.py`` exports the demo board both ways and
asserts that the file names in this plan are exactly the toolpath files the
engine wrote, in exactly that sequence. A step added to the engine and not to
this module fails the test; so does a step reordered in either place.

Three kinds of entry, because the operator's day has three kinds of thing in
it:

``run``       something you send to the machine. Has a file and a bit.
``handoff``   something you do with your hands and no file: change the bit,
              re-zero Z, flip the board. These are between the run steps in the
              printed plan and they are between them here, because they are
              where boards get scrapped.
``tool``      something you open rather than run: set up, check, level, rework.
"""
from dataclasses import dataclass, field

from gerber2rml.backends import BACKENDS


@dataclass
class Step:
    """One line of the plan."""
    key: str                       # stable id — the interface selects by this
    kind: str                      # "run" | "handoff" | "tool"
    title: str
    ordinal: int = None            # the number the operator says out loud
    detail: str = ""               # the one-line spec: bit, depth, passes
    op: str = None                 # toolpath op the stage should draw
    side: str = "bottom"           # which face this cuts
    file: str = None               # exported file name (no directory)
    bit: float = None              # mm the spindle must be holding (display)
    tool: tuple = None             # the TOOL identity this step needs, or that
                                   # a hands-on step puts in the spindle. Two
                                   # operations share a tool only if this
                                   # matches, which is what decides whether a
                                   # bit-change step exists between them.
    seconds: float = None          # estimated run time, filled in after export
    caution: str = ""              # a consequence worth reading before running
    irreversible: bool = False     # cannot be undone by re-running it
    note: str = ""                 # longer explanation for the inspector

    @property
    def numbered(self):
        return self.ordinal is not None


@dataclass
class Plan:
    steps: list = field(default_factory=list)
    double_sided: bool = False
    registration: str = "dowel"
    ext: str = ".nc"

    def __iter__(self):
        return iter(self.steps)

    def __len__(self):
        return len(self.steps)

    def by_key(self, key):
        for s in self.steps:
            if s.key == key:
                return s
        return None

    @property
    def run_steps(self):
        return [s for s in self.steps if s.kind == "run"]

    @property
    def files(self):
        """Toolpath file names, in the order the engine writes them."""
        return [s.file for s in self.steps if s.file]

    @property
    def total_seconds(self):
        known = [s.seconds for s in self.run_steps if s.seconds is not None]
        return sum(known) if known else None

    @property
    def tools(self):
        """The distinct tools this job needs, in the order they go in."""
        out = []
        for s in self.steps:
            if s.tool is not None and s.tool not in out:
                out.append(s.tool)
        return out

    @property
    def single_tool(self):
        """True when one bit does the whole job.

        This is the normal case in the lab this was built for: one 0.8 mm flat
        endmill isolates, drills and cuts out, and it never leaves the collet.
        When it holds, there is no bit-change step anywhere in the plan and Z
        is zeroed exactly once — so the interface should say that once, rather
        than repeating an instruction nobody is going to follow.
        """
        return len(self.tools) == 1

    @property
    def tool_label(self):
        t = self.tools
        return tool_label(t[0]) if len(t) == 1 else None

    def apply_estimates(self, per_file):
        """Attach ``{filename: seconds}`` (from the exported files) to the steps."""
        for s in self.steps:
            if s.file and s.file in per_file:
                s.seconds = per_file[s.file]


# ---------------------------------------------------------------------------
# Building the plan
# ---------------------------------------------------------------------------

def tool_id(job, *, trace=False):
    """What is physically in the collet for this operation.

    Compared by identity rather than by diameter alone, because a 30° V-bit and
    a 0.8 mm flat endmill are two different tools even when the numbers in the
    job happen to line up. Two operations share a tool only if this matches,
    and that is the only thing that decides whether a bit-change step exists
    between them.
    """
    if trace and getattr(job, "tool_type", "flat") == "vbit":
        return ("vbit", round(job.included_angle, 2), round(job.tip_diameter, 3))
    return ("flat", round(job.bit_diameter, 3))


def tool_label(tool):
    """The tool, in the words someone standing at the machine would use."""
    if tool is None:
        return "no tool"
    if tool[0] == "vbit":
        _kind, angle, tip = tool
        return f"{angle:g}° V-bit ({tip:g} mm tip)"
    return f"{tool[1]:.2f} mm flat endmill"


class _Sequence:
    """Builds the run order, inserting a hands-on step only where one is real.

    The rule: a bit-change step exists between two operations **exactly when
    the tool changes**. On a one-bit job — one 0.8 mm endmill isolating,
    drilling and cutting out, which is how this lab runs — that means none at
    all, and the plan says so by not containing them.

    This used to emit "fit the trace bit / fit the drill bit / fit the cut-out
    bit" unconditionally, which on a one-bit job put three rows in the plan
    telling the operator to do something they never do. Instructions that are
    routinely ignorable are how a plan stops being read.
    """

    def __init__(self):
        self.steps = []
        self.spindle = None            # the tool currently in the collet

    def hand(self, key, title, detail, *, tool=None, **kw):
        self.steps.append(Step(key, "handoff", title, detail=detail, tool=tool,
                               **kw))
        if tool is not None:
            self.spindle = tool
        return self.steps[-1]

    def run(self, key, title, *, tool=None, **kw):
        if tool is not None and tool != self.spindle:
            self.hand(f"{key}__bit",
                      f"Change to the {tool_label(tool)}",
                      "Then re-zero Z on the new tool. Never re-zero XY.",
                      tool=tool)
        self.steps.append(Step(key, "run", title, tool=tool, **kw))
        return self.steps[-1]

    def add(self, step):
        self.steps.append(step)
        return step


ORIGIN_NOTE = (
    "This is the one time XY is set, and after it XY is never touched again — "
    "the traces, the holes and the outline only land on top of each other "
    "because every pass was cut from the same origin.\n\n"
    "Zero Z on the copper with the bit you are about to cut with. The dry run "
    "that follows holds the bit 5 mm above THIS zero, so it only means "
    "anything once the zero is set.")

ONE_BIT_NOTE = (
    "One bit does this whole job — traces, holes and outline — so it never "
    "leaves the collet and Z stays where you zeroed it. There is no bit change "
    "anywhere in this plan, and nothing to re-zero between the steps.")


def _drill_files(holes, drill, prefix, ext):
    """The drill file names, by the same rule ``engine.drill.drill_jobs`` uses.

    Names only — generating the toolpaths here would double the cost of every
    keystroke that rebuilds the plan.
    """
    if drill.single_bit:
        return [(f"{prefix}{ext}", drill.bit_diameter)]
    from gerber2rml.engine.drill import group_holes_by_diameter, format_diameter
    return [(f"{prefix}_{format_diameter(d)}mm{ext}", d)
            for d, _hs in group_holes_by_diameter(holes or [])]


def _trace_detail(trace):
    if getattr(trace, "tool_type", "flat") == "vbit":
        return (f"V-bit {trace.included_angle:.0f}° · cutting "
                f"{trace.effective_diameter():.2f} mm wide at "
                f"{trace.effective_cut_depth():.2f} mm deep")
    passes = ("clears all background copper" if trace.offsets == -1
              else f"{trace.offsets} pass" + ("" if trace.offsets == 1 else "es"))
    return (f"{trace.bit_diameter:.2f} mm flat · {passes} · "
            f"{trace.cut_depth:.2f} mm deep")


def _cutout_detail(cutout):
    return (f"{cutout.bit_diameter:.2f} mm · through {cutout.total_depth:.2f} mm · "
            f"{cutout.tabs} tabs of {cutout.tab_width:.1f} mm")


def _drill_detail(drill, files):
    if drill.single_bit:
        return (f"{drill.bit_diameter:.2f} mm · through "
                f"{drill.total_depth:.2f} mm · one bit for every hole")
    return (f"{len(files)} files, one per hole size — change the bit and "
            f"re-zero Z between each")


AIRPASS_NOTE = (
    "The spindle never starts and the bit is held 5 mm above the copper, so "
    "this file physically cannot cut. It traces where the board is about to "
    "be machined, slowly enough to watch.\n\n"
    "If the bit wanders off the copper, stop it and re-place the stock. You "
    "will have spent twenty seconds instead of a board. Worth running before "
    "every job, whether or not the stock is in a fixture.")

CUTOUT_NOTE = (
    "This one runs last, and the order is not a preference.\n\n"
    "The cut-out is what separates the board from the sheet it is registered "
    "in. Run it early and everything after it is being machined on a piece of "
    "copper held only by four 1.5 mm tabs — which is how a finished board "
    "becomes swarf on the last pass.")

ALIGN_NOTE = (
    "This drills through the stock and on into the sacrificial bed, so those "
    "holes stay in the bed after the job. That is the point — the pins seated "
    "in them are what the board registers against before and after the flip — "
    "but it is also why this is the one cut in the app you cannot take back "
    "by re-zeroing and trying again.\n\n"
    "Run the dry run first.")

FLIP_NOTE = (
    "Lift the board off the pins, turn it over about the pin line, and drop it "
    "back on the same two pins. The pins sit ON the flip axis, so they do not "
    "move when the board does.\n\n"
    "Then re-zero Z on the new surface — it is a different face and it is not "
    "at the same height. Do NOT touch the XY origin.")

FIDUCIAL_FLIP_NOTE = (
    "Turn the board over and put it down anywhere sensible — there are no pins "
    "to seat it on. Re-zero Z on the new surface; leave XY alone.\n\n"
    "Then probe the reference holes so the app can measure where the board "
    "actually landed and warp the top traces to match. The fit is only as good "
    "as the spread of the holes you probe.")


def build(state, *, double_sided=False, registration="dowel", holes=None,
          align_holes=None):
    """The plan for the job currently in ``state``.

    ``holes`` overrides the hole list used to name per-diameter drill files
    (the double-sided path drills the placed layout's holes, not the board's).
    """
    ext = BACKENDS[state.machine].ext
    name = state.name or "board"
    trace, drill, cutout = state.trace, state.drill, state.cutout
    holes = holes if holes is not None else (
        state.board.holes if state.board is not None else [])

    trace_tool = tool_id(trace, trace=True)
    drill_tool = tool_id(drill)
    cutout_tool = tool_id(cutout)

    seq = _Sequence()
    seq.add(Step("setup", "tool", "Set up the job",
                 detail="Board, copper, tool, placement", op="board"))
    seq.add(Step("checks", "tool", "Check before cutting",
                 detail="Fit, depth, reach, shorts", op="board"))

    # -- the origin, which nothing works without ---------------------------
    # The dry run holds the bit 5 mm above the WORK Z ZERO, so it means nothing
    # until that zero exists - and VPanel will not output a file without an
    # origin either. This step was missing entirely: the plan opened with the
    # dry run and told you to fit a bit afterwards.
    first_tool = drill_tool if double_sided else trace_tool
    seq.hand("origin", f"Fit the {tool_label(first_tool)}, set the origin",
             "X, Y and Z, once. From here on only Z is ever re-zeroed.",
             tool=first_tool, note=ORIGIN_NOTE)

    # -- step 0 is the same on both paths, and it is deliberately first -----
    seq.run("airpass", "Dry run", ordinal=0, op="airpass",
            file=f"{name}_airpass{ext}",
            detail="Spindle off, bit held 5 mm up, tracing the outline",
            note=AIRPASS_NOTE)

    if not double_sided:
        seq.run("traces_run", "Isolation traces", ordinal=1, op="traces",
                file=f"{name}_traces{ext}", tool=trace_tool,
                bit=trace.effective_diameter(), detail=_trace_detail(trace),
                note="Cuts a channel around every copper feature so the nets "
                     "stop touching. This is the pass that decides whether the "
                     "board works, and the one bed levelling exists for.")

        dfiles = _drill_files(holes, drill, f"{name}_drill", ext)
        for i, (fn, dia) in enumerate(dfiles):
            seq.run(f"drill_run{i}" if i else "drill_run",
                    "Drill" if len(dfiles) == 1 else f"Drill {dia:.2f} mm holes",
                    ordinal=2 if i == 0 else None, op="drill", file=fn,
                    tool=("flat", round(dia, 3)), bit=dia,
                    detail=_drill_detail(drill, dfiles) if i == 0
                           else f"{dia:.2f} mm bit",
                    note="Holes are drilled after the traces so the copper is "
                         "still one flat sheet while the fine work happens.")

        seq.run("cutout_run", "Cut the board out", ordinal=3, op="cutout",
                file=f"{name}_cutout{ext}", tool=cutout_tool,
                bit=cutout.bit_diameter, detail=_cutout_detail(cutout),
                caution="Runs last - it frees the board", note=CUTOUT_NOTE)
    else:
        fiducial = registration == "fiducial"
        align_word = "reference holes" if fiducial else "dowel holes"
        seq.run("align", "Fiducial holes" if fiducial else "Dowel holes",
                ordinal=1, op="align", file=f"{name}_align{ext}",
                tool=drill_tool, bit=drill.bit_diameter,
                detail=(f"{len(align_holes or [])} {align_word} - "
                        f"{drill.bit_diameter:.2f} mm bit"),
                caution=None if fiducial else "Drills into the sacrificial bed",
                irreversible=not fiducial,
                note=ALIGN_NOTE if not fiducial else
                     "Through-holes in the stock only - these never reach the "
                     "bed. They are what the app measures the flipped board "
                     "against, so the further apart they are, the better the "
                     "fit.")

        dfiles = _drill_files(holes, drill, f"{name}_bottom_drill", ext)
        for i, (fn, dia) in enumerate(dfiles):
            seq.run(f"bdrill{i}",
                    "Drill the board" if len(dfiles) == 1
                    else f"Drill {dia:.2f} mm holes",
                    ordinal=2 if i == 0 else None, op="drill", file=fn,
                    tool=("flat", round(dia, 3)), bit=dia,
                    detail=_drill_detail(drill, dfiles) if i == 0
                           else f"{dia:.2f} mm bit")

        seq.run("bottom_traces", "Bottom traces", ordinal=3, op="traces",
                side="bottom", file=f"{name}_bottom_traces{ext}",
                tool=trace_tool, bit=trace.effective_diameter(),
                detail=_trace_detail(trace),
                note="Milled mirrored, because you are cutting the underside "
                     "of the board from above.")

        # The flip is a Z re-zero whatever the tooling: it is the other face of
        # the board, and it is not at the same height.
        seq.hand("flip",
                 "Flip the board, re-place it, probe" if fiducial
                 else "Flip the board onto the pins",
                 "Then re-zero Z on the new face. Never re-zero XY.",
                 caution="Getting this backwards mirrors every trace",
                 note=FIDUCIAL_FLIP_NOTE if fiducial else FLIP_NOTE)

        if fiducial:
            # Not a file and not a bit change: a measurement. It sits between
            # the flip and the top traces because that is where it happens, and
            # because the top traces the export wrote are only NOMINAL until it
            # has been done.
            seq.hand("fitflip", "Measure where it landed",
                     "Probe the reference holes; the top traces warp to match",
                     caution="The top traces are nominal until you do this",
                     note="The export wrote the top traces for a perfect flip. "
                          "A flip is never perfect, and without pins there is "
                          "nothing making it close. Probing the reference "
                          "holes measures the real position and rewrites that "
                          "one file to suit it.")

        seq.run("top_traces", "Top traces", ordinal=4, op="top_traces",
                side="top", file=f"{name}_top_traces{ext}", tool=trace_tool,
                bit=trace.effective_diameter(), detail=_trace_detail(trace),
                note="Cut as plain F.Cu. Mirroring the bottom and reflecting "
                     "the top about the same axis cancel out, so the top comes "
                     "out the way KiCad drew it and still lands on the "
                     "bottom's holes.")

        seq.run("cutout_run", "Cut the board out", ordinal=5, op="cutout",
                file=f"{name}_cutout{ext}", tool=cutout_tool,
                bit=cutout.bit_diameter, detail=_cutout_detail(cutout),
                caution="Runs last - it frees the board and the dowel waste",
                note=CUTOUT_NOTE)

    seq.add(Step("level", "tool", "Level the bed",
                 detail="Measure the surface so cut depth follows it",
                 op="level"))
    seq.add(Step("rework", "tool", "Rework",
                 detail="Box up spots on a cut board and machine them again",
                 op="rework"))

    plan = Plan(steps=seq.steps, double_sided=double_sided,
                registration=registration, ext=ext)
    if plan.single_tool:
        # Say it once, on the step that puts the bit in, rather than repeating
        # a bit-change instruction that does not apply to this job.
        origin = plan.by_key("origin")
        origin.detail = (f"One {plan.tool_label} for the whole job. "
                         f"X, Y and Z, once.")
        origin.note = ORIGIN_NOTE + "\n\n" + ONE_BIT_NOTE
    return plan


def tool_changes(plan):
    """``[(step_key, tool)]`` for every point the operator changes the bit.

    Empty on a one-bit job, which is the whole point: the plan contains a
    bit-change step exactly when this is non-empty.
    """
    return [(s.key, s.tool) for s in plan.steps
            if s.kind == "handoff" and s.tool is not None
            and s.key != "origin"]
