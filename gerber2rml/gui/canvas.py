"""Matplotlib preview canvas: draws cut/rapid polylines, or drill holes as circles."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSlider
from PySide6.QtCore import Qt
from matplotlib.figure import Figure
from matplotlib.collections import LineCollection
from matplotlib.patches import Circle
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg


class PreviewCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure(figsize=(5, 5))
        self.figure.patch.set_facecolor('#1e1e1e')
        self.canvas = FigureCanvasQTAgg(self.figure)
        
        self.ax = self.figure.add_subplot(111)
        self.ax.set_aspect("equal")
        self.ax.set_facecolor('#1e1e1e')
        self.ax.tick_params(colors='#d4d4d4')
        self.ax.grid(True, color='#333333', linestyle='--')
        for spine in self.ax.spines.values():
            spine.set_color('#333333')

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(1000)
        self.slider.setToolTip("Scrub through the toolpath (Live Preview)")
        self.slider.valueChanged.connect(self._on_slider)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        layout.addWidget(self.slider)

        self._full_cuts = []
        self._full_rapids = []
        self._full_holes = []
        self._limits = None

    def show_segments(self, cuts, rapids, holes=None):
        """Store the toolpaths and update the display based on the slider."""
        self._full_cuts = cuts or []
        self._full_rapids = rapids or []
        self._full_holes = holes or []
        self._limits = self._compute_limits()
        self.slider.setValue(1000)
        self._draw_fraction(1.0)

    def _compute_limits(self):
        """Fixed view frame from the FULL geometry, so scrubbing the slider
        animates within a stable view instead of rescaling each frame."""
        xs, ys = [], []
        for seg in self._full_cuts + self._full_rapids:
            for (x, y) in seg:
                xs.append(x); ys.append(y)
        for (x, y, d) in self._full_holes:
            r = max(d, 0.1) / 2.0
            xs += [x - r, x + r]; ys += [y - r, y + r]
        if not xs:
            return None
        m = 0.05
        dx = (max(xs) - min(xs)) or 1.0
        dy = (max(ys) - min(ys)) or 1.0
        return (min(xs) - dx * m, max(xs) + dx * m,
                min(ys) - dy * m, max(ys) + dy * m)

    def _style_axes(self):
        self.ax.set_aspect("equal")
        self.ax.set_facecolor('#1e1e1e')
        self.ax.tick_params(colors='#d4d4d4')
        self.ax.grid(True, color='#333333', linestyle='--')
        for spine in self.ax.spines.values():
            spine.set_color('#333333')

    def _on_slider(self, val):
        self._draw_fraction(val / 1000.0)

    def _draw_fraction(self, fraction):
        self.ax.clear()
        self._style_axes()

        c_end = int(len(self._full_cuts) * fraction)
        r_end = int(len(self._full_rapids) * fraction)
        h_end = int(len(self._full_holes) * fraction)

        rapids = self._full_rapids[:r_end]
        cuts = self._full_cuts[:c_end]
        holes = self._full_holes[:h_end]

        if rapids:
            self.ax.add_collection(
                LineCollection(rapids, colors="#555555", linewidths=0.6))
        if cuts:
            self.ax.add_collection(
                LineCollection(cuts, colors="#00ffff", linewidths=1.2))
        if holes:
            for (x, y, d) in holes:
                self.ax.add_patch(Circle((x, y), max(d, 0.1) / 2.0, fill=False,
                                         edgecolor="#ff5555", linewidth=1.2))
            self.ax.scatter([h[0] for h in holes], [h[1] for h in holes],
                            s=15, c="#ff5555", marker="+")
        if self._limits:
            x0, x1, y0, y1 = self._limits
            self.ax.set_xlim(x0, x1)
            self.ax.set_ylim(y0, y1)
        self.canvas.draw_idle()

    def show_holes(self, holes):
        """Draw drill holes alone (circles + centre marks), no trace context."""
        self.show_segments([], [], holes=holes)

    def show_gaps(self, gaps):
        """Overlay narrow-gap polygons (isolation preflight) in red."""
        from shapely.geometry import MultiPolygon
        polys = gaps.geoms if isinstance(gaps, MultiPolygon) else [gaps]
        for p in polys:
            if not p.is_empty and p.geom_type == "Polygon":
                xs, ys = p.exterior.xy
                self.ax.fill(list(xs), list(ys), color="#ff0000", alpha=0.5, zorder=5)
        self.canvas.draw_idle()
