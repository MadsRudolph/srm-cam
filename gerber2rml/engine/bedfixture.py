"""A datum the machine drills for itself.

Without the machine link, the only way anyone tells the SRM-20 where the
copper is, is by jogging the spindle to the corner of the stock and calling
that zero. That corner is a sheared edge, the eye is good to a millimetre or
two on a good day, and every student does it differently. Worse, if the origin
moves between passes, traces / drill / cut-out stop registering *with each
other* — each pass is fine on its own and the board is scrap.

The fix is to stop telling the machine where the stock is. Anything the
machine cuts is already in machine coordinates, so it drills three holes for
itself; you drop pins in and push the copper against them. The stock's corner
then lands on the work origin every time, without anyone measuring anything.

Three pins, not four: **3-2-1 locating**. Two along the bottom edge fix
rotation and Y, one on the left edge fixes X. A fourth pin has nothing left to
constrain and can only fight the other three. They sit *outside* the stock
outline — a pin under the copper holds it up, a pin beside it locates it.

Pins rather than a milled L-corner because an inside corner packs with chips,
and a chip behind the stock is exactly the error this exists to remove.
"""
from gerber2rml.backends import SRM20_BED
from gerber2rml.doublesided import CLEAR_LARGE
from gerber2rml.toolpath import Move

DEFAULT_PIN_DIAMETER = 3.0     # Ø3 mm dowel — stiff enough to take side load
DEFAULT_BED_DEPTH = 5.0        # mm into the sacrificial bed; the same depth the
                               # dowel work found a pin actually needs to hold
EDGE_FRACTION = 0.15           # bottom pins sit this far in from each corner,
                               # so they are spread wide (a small seating error
                               # over a long baseline is a small angle) while
                               # staying clear of the corner itself


def pin_holes(stock_w, stock_h, pin_diameter=DEFAULT_PIN_DIAMETER):
    """Pin-hole centres for a *stock_w* x *stock_h* piece, as (x, y, diameter).

    Coordinates are relative to the work origin, which is where the stock's
    front-left corner ends up. The holes therefore sit at small negative X or
    Y — set the work origin far enough inside the machine's travel to reach
    them (the run plan says so).
    """
    if stock_w > SRM20_BED[0] or stock_h > SRM20_BED[1]:
        raise ValueError(
            f"Stock {stock_w} x {stock_h} mm is larger than the SRM-20's "
            f"{SRM20_BED[0]} x {SRM20_BED[1]} mm travel — it does not fit.")

    r = pin_diameter / 2.0
    # Milled holes on this machine come out ~0.2 mm under nominal, measured on
    # real coupons during the double-sided work. Cut them oversize by the same
    # amount rather than re-learning it.
    d = pin_diameter + CLEAR_LARGE

    return [
        (stock_w * EDGE_FRACTION, -r, d),           # bottom edge, left of centre
        (stock_w * (1 - EDGE_FRACTION), -r, d),     # bottom edge, right of centre
        (-r, stock_h / 2.0, d),                     # left edge, mid height
    ]


def fixture_toolpaths(stock_w, stock_h, pin_diameter=DEFAULT_PIN_DIAMETER,
                      bed_depth=DEFAULT_BED_DEPTH, bit_diameter=0.8,
                      travel_z=2.0, step=0.6):
    """Toolpaths that cut the pin holes, using the normal drill engine.

    The holes are wider than the end mill, so they are interpolated (the tool
    circles out to size) — the same path the double-sided dowel holes take,
    whose clearances were dialled in on real coupons.
    """
    from gerber2rml.config import DrillJob
    from gerber2rml.engine.drill import drill_single_bit

    holes = pin_holes(stock_w, stock_h, pin_diameter)
    job = DrillJob(bit_diameter=bit_diameter, single_bit=True,
                   cut_depth=step, total_depth=bed_depth,
                   travel_z=travel_z)
    return drill_single_bit(holes, job)


def procedure(stock_w, stock_h, pin_diameter=DEFAULT_PIN_DIAMETER):
    """The operator's instructions. Written out with the job, because the
    fixture is worthless if the next person does not know what it is for."""
    holes = pin_holes(stock_w, stock_h, pin_diameter)
    listed = "\n".join(
        f"     pin {i}:  X {x:+8.2f}   Y {y:+8.2f}   hole Ø{d:.2f} mm"
        for i, (x, y, d) in enumerate(holes, start=1))
    return (
        f"SRM-20 bed fixture — for {stock_w:g} x {stock_h:g} mm stock\n"
        f"\n"
        f"Cut this ONCE per sacrificial bed. After that every job starts the\n"
        f"same way and nobody sets XY zero by eye again.\n"
        f"\n"
        f"1. Put the sacrificial bed on the machine and clamp it down.\n"
        f"2. In VPanel, set the XY work origin (G54) at least 10 mm in from\n"
        f"   the front-left of the machine's travel — the pin holes sit just\n"
        f"   outside the stock, at slightly negative X and Y.\n"
        f"3. Set Z zero on the surface of the sacrificial bed.\n"
        f"4. Run this file. It drills three holes, {bed_depth_note()}:\n"
        f"{listed}\n"
        f"5. Press Ø{pin_diameter:g} mm dowel pins into the holes.\n"
        f"6. Push the copper against all three pins and tape it down. Its\n"
        f"   front-left corner is now exactly on the work origin.\n"
        f"\n"
        f"From then on: DO NOT move the XY origin. Re-zero Z after every bit\n"
        f"change, never XY. If the XY origin moves between passes, the traces,\n"
        f"drill and cut-out stop lining up with each other and the board is\n"
        f"scrap even though each pass looked fine.\n"
        f"\n"
        f"Run the _airpass file before each job to confirm the stock is where\n"
        f"the toolpath expects it.\n")


def bed_depth_note(bed_depth=DEFAULT_BED_DEPTH):
    return f"{bed_depth:g} mm deep into the bed"
