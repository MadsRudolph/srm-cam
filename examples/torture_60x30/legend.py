"""The torture board's map, to scale: python legend.py writes legend.png."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle

import make_board as mb

CU = "#c9783f"
fig, ax = plt.subplots(figsize=(14, 7.6))
ax.add_patch(Rectangle((0, 0), mb.W, mb.H, fill=False, ec="black", lw=1.4))


def trace(points, width, pads):
    ax.plot(*zip(*points), color=CU, lw=width * 15.5, solid_capstyle="round")
    for x, y in pads:
        ax.add_patch(Circle((x, y), mb.PAD_D / 2, color=CU))
        end = min(points, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
        ax.plot([end[0], x], [end[1], y], color=CU, lw=width * 15.5)


for gap, a, b, y in [(g, a, b, y) for (g, a, b), y in zip(mb.gap_rows(), mb.ROW_YS)]:
    trace(*a)
    trace(*b)
    ax.text(12.2, y, "%.2f" % gap, ha="center", va="center", fontsize=8, fontweight="bold",
            bbox=dict(fc="white", ec="none", pad=0.6))
for (w, net), y in zip(mb.width_rows(), mb.ROW_YS):
    trace(*net)
    ax.text(30.5, y + 0.85, "%.2f" % w, ha="center", va="center", fontsize=8, fontweight="bold")
for name, pads in mb.parts().items():
    for x, y, w, h in pads:
        ax.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, color=CU))
    xs = [p[0] for p in pads]
    ys = [p[1] for p in pads]
    ax.text(sum(xs) / len(xs), max(ys) + 1.3 + max(p[3] for p in pads) / 2 - 0.2, name,
            ha="center", va="center", fontsize=8, fontweight="bold")
for x, y in mb.HOLES:
    ax.add_patch(Circle((x, y), mb.HOLE_D / 2, fill=False, ec="black"))
ax.text(12.5, mb.H + 0.8, "GAPS: gap between 2 traces. Meter: left pad to right pad must be OPEN",
        ha="center", fontsize=9)
ax.text(30.5, mb.H + 0.8, "WIDTHS: pad to pad must CONNECT", ha="center", fontsize=9)
ax.text(49.5, mb.H + 0.8, "PARTS: pads must stay separate", ha="center", fontsize=9)
ax.set_title("Torture board, drawn from the top. On a single-sided board the copper is on the "
             "bottom, so it cuts mirrored, left to right.", fontsize=10, pad=20)
ax.set_xlim(-1, mb.W + 1)
ax.set_ylim(-1, mb.H + 2)
ax.set_aspect("equal")
ax.axis("off")
fig.tight_layout()
fig.savefig(Path(__file__).with_name("legend.png"), dpi=120)
