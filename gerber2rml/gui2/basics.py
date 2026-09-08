"""The machine, in five minutes: what the guided tour used to teach.

The original interface's tour walked a first-timer through the steps and,
in its levelling branch, explained the machine itself: which coordinate
system the exported files live in, why only Z is ever zeroed, how far Z
can travel, and where the probe clips go. This interface put the step
explanations into the steps, which left the machine lessons with no home.
This is that home: one sheet under Help, readable in the time it takes the
spindle to spin up, with the same numbers the run sheet relies on.
"""
from gerber2rml.gui2 import dialogs, widgets

LESSONS = [
    ("Three coordinate systems, one that matters",
     "VPanel lists several. MACHINE is the mill's own: its origin is fixed "
     "and cannot be moved, and the Z travel limit below is measured in it. "
     "USER is what Roland's own RML software uses; this app rarely does. "
     "G54 is the work coordinate system that NC code uses, and NC code is "
     "what this app exports. So the origin is set in G54, with the Command "
     "Set switched to NC Code in VPanel's Setup dialog."),
    ("Set Z. Leave X and Y alone.",
     "X and Y are already at the machine's origin, which is what the "
     "exported files assume. Jog the bit down until it just touches the "
     "copper and press Z under Set Origin Point. That is the only origin "
     "you set, and it is set again after every bit change and after a flip. "
     "Re-zeroing X or Y is how a second pass lands beside the first."),
    ("Z has about 60 mm of travel",
     "The stroke is 60.5 mm in MACHINE coordinates. If the surface sits too "
     "low the head tops out and cuts air, or too shallow. Keep the MACHINE "
     "Z above −50 mm when the bit touches the copper; if it is lower, raise "
     "the work surface with more spoilboard rather than pushing on."),
    ("The probe is a circuit",
     "Bed levelling senses height by contact: clip the red lead to the "
     "copper and the black lead to the bit. When they touch, the circuit "
     "closes and the point is recorded. Paper or tape under the board keeps "
     "it isolated from the bed, and the Arduino's serial monitor must be "
     "closed, because only one program can hold the port."),
    ("STOP and Pause are different things",
     "STOP drops the move in flight and stops the spindle; the bit stays "
     "where it is, so raise it before jogging, and the job does not resume. "
     "Pause holds the machine with the spindle turning, and Resume carries "
     "on from the same place. Escape is STOP from anywhere in the app."),
    ("Where the files go",
     "Export writes one program per step and the run sheet that says the "
     "order. In VPanel: Cut, Add, pick the file, Output. The dry run comes "
     "first: spindle off, bit held up, tracing where the board is about to "
     "be machined. It is twenty seconds and the cheapest way to find the "
     "stock in the wrong place."),
]


def machine_basics(parent):
    """Help → The machine, in five minutes."""
    d = dialogs.Sheet(parent, "The machine, in five minutes", width=640)
    d.say("What a first-timer needs to know about the SRM-20 before the "
          "first file is sent. The step-by-step guide on the web (F1) has "
          "the photos; this is the part that is true at every step.")
    for head, body in LESSONS:
        sec = widgets.Section(head)
        sec.add(widgets.body(body))
        d.add(sec)
    d.setObjectName("basicsSheet")
    d.act("Close", kind="primary", on=d.accept, default=True)
    return d
