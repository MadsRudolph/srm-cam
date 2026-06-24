"""Matplotlib preview canvas: draws cut/rapid polylines, or drill holes as circles."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSlider
from PySide6.QtCore import Qt
from matplotlib.figure import Figure
from matplotlib.collections import LineCollection
from matplotlib.patches import Circle, Rectangle
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
        self._full_top_cuts = []
        self._pins = []
        self._limits = None

        # Orientation badge + optional view-only horizontal flip. The flip shows
        # the un-mirrored "as designed" orientation WITHOUT changing any
        # coordinates (data, selection and export stay in the real frame).
        self._frame_label = None
        self._frame_color = "#ffb000"
        self._flip_x = False

        # Machine bed: when set to (width, height) mm the work area is drawn from
        # the origin (front-left corner) and the design is checked to fit inside.
        self._bed = None
        self._bed_fits = True

        # Rework box-selection state. When selecting, a left-drag draws a
        # rectangle that persists across redraws/scrubbing; the chosen bbox is
        # read back by the app to clip a second-pass program.
        self._selecting = False
        self._selection_bbox = None       # (x0, y0, x1, y1) or None
        self._drag_start = None
        self._rect_artist = None
        self.on_selection_changed = None  # callback(bbox) set by the app

        # Move-on-bed state: left-drag translates the whole design. A dashed
        # ghost shows the target footprint; the committed (dx, dy) is reported
        # to the app, which folds it into the placement offset.
        self._moving = False
        self._move_start = None
        self._move_bbox0 = None
        self._move_ghost = None
        self.on_move_delta = None         # callback(dx, dy) set by the app
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)

    def show_segments(self, cuts, rapids, holes=None, top_cuts=None, pins=None):
        """Store the toolpaths and update the display based on the slider.

        ``top_cuts`` are the reflected front-side isolation polylines (drawn in a
        second colour) and ``pins`` are the (x, y, d) dowel/alignment holes, both
        used for the double-sided preview. Both default empty, so the ordinary
        single-sided callers are unaffected."""
        self._full_cuts = cuts or []
        self._full_rapids = rapids or []
        self._full_holes = holes or []
        self._full_top_cuts = top_cuts or []
        self._pins = pins or []
        self._limits = self._compute_limits()
        self.slider.setValue(1000)
        self._draw_fraction(1.0)

    def set_frame(self, label, color="#ffb000", flip_x=False):
        """Set the persistent orientation badge and whether to flip the view
        horizontally. ``flip_x`` only mirrors the *display* (to show the design
        orientation); coordinates, selection and export are untouched."""
        self._frame_label = label
        self._frame_color = color
        self._flip_x = bool(flip_x)

    def set_bed(self, size):
        """Set the machine work area to ``(width, height)`` mm (origin at the
        front-left corner), or ``None`` to hide it."""
        self._bed = size

    def _design_bounds(self):
        """(minx, miny, maxx, maxy) of all toolpath/hole/pin geometry, or None."""
        xs, ys = [], []
        for seg in self._full_cuts + self._full_rapids + self._full_top_cuts:
            for (x, y) in seg:
                xs.append(x); ys.append(y)
        for (x, y, d) in self._full_holes + self._pins:
            r = max(d, 0.1) / 2.0
            xs += [x - r, x + r]; ys += [y - r, y + r]
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    def _compute_limits(self):
        """Fixed view frame from the FULL geometry, so scrubbing the slider
        animates within a stable view instead of rescaling each frame."""
        xs, ys = [], []
        for seg in self._full_cuts + self._full_rapids + self._full_top_cuts:
            for (x, y) in seg:
                xs.append(x); ys.append(y)
        for (x, y, d) in self._full_holes + self._pins:
            r = max(d, 0.1) / 2.0
            xs += [x - r, x + r]; ys += [y - r, y + r]
        if self._bed:                       # keep the whole bed in view
            xs += [0, self._bed[0]]; ys += [0, self._bed[1]]
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

        self._bed_fits = True
        if self._bed:
            bw, bh = self._bed
            db = self._design_bounds()
            self._bed_fits = db is None or (
                db[0] >= -1e-6 and db[1] >= -1e-6
                and db[2] <= bw + 1e-6 and db[3] <= bh + 1e-6)
            bed_color = "#33cc88" if self._bed_fits else "#ff4444"
            self.ax.add_patch(Rectangle((0, 0), bw, bh, fill=False,
                                        edgecolor=bed_color, linewidth=1.5, zorder=1))
            self.ax.scatter([0], [0], s=40, c=bed_color, marker="s", zorder=2)  # home

        c_end = int(len(self._full_cuts) * fraction)
        r_end = int(len(self._full_rapids) * fraction)
        h_end = int(len(self._full_holes) * fraction)
        t_end = int(len(self._full_top_cuts) * fraction)

        rapids = self._full_rapids[:r_end]
        cuts = self._full_cuts[:c_end]
        holes = self._full_holes[:h_end]
        top_cuts = self._full_top_cuts[:t_end]

        if rapids:
            self.ax.add_collection(
                LineCollection(rapids, colors="#555555", linewidths=0.6))
        if cuts:
            self.ax.add_collection(
                LineCollection(cuts, colors="#00ffff", linewidths=1.2))
        if top_cuts:
            # reflected front-side isolation, second colour so the two registered
            # sides are visually distinct
            self.ax.add_collection(
                LineCollection(top_cuts, colors="#ff55ff", linewidths=1.2))
        if holes:
            for (x, y, d) in holes:
                self.ax.add_patch(Circle((x, y), max(d, 0.1) / 2.0, fill=False,
                                         edgecolor="#ff5555", linewidth=1.2))
            self.ax.scatter([h[0] for h in holes], [h[1] for h in holes],
                            s=15, c="#ff5555", marker="+")
        # dowel/alignment holes: always drawn in full (registration features,
        # never scrubbed away) and clearly distinct from the board's own holes
        for (x, y, d) in self._pins:
            self.ax.add_patch(Circle((x, y), max(d, 0.1) / 2.0, fill=False,
                                     edgecolor="#ffd700", linewidth=2.0, zorder=6))
        if self._pins:
            self.ax.scatter([p[0] for p in self._pins], [p[1] for p in self._pins],
                            s=80, c="#ffd700", marker="+", zorder=6)
        if self._limits:
            x0, x1, y0, y1 = self._limits
            # flip_x reverses the x-axis to show the un-mirrored "as designed"
            # orientation; the data underneath is unchanged.
            self.ax.set_xlim((x1, x0) if self._flip_x else (x0, x1))
            self.ax.set_ylim(y0, y1)
        # ax.clear() above dropped the selection rectangle; re-add it so the
        # picked area stays visible while scrubbing or regenerating the preview.
        self._rect_artist = None
        self._add_selection_patch()
        if self._frame_label:
            self.ax.text(0.02, 0.98, self._frame_label, transform=self.ax.transAxes,
                         va="top", ha="left", fontsize=9, color="#1e1e1e", zorder=20,
                         bbox=dict(boxstyle="round,pad=0.3", facecolor=self._frame_color,
                                   edgecolor="none", alpha=0.95))
        if self._bed and not self._bed_fits:
            self.ax.text(0.98, 0.02, "DESIGN EXCEEDS BED", transform=self.ax.transAxes,
                         va="bottom", ha="right", fontsize=9, color="#1e1e1e", zorder=20,
                         bbox=dict(boxstyle="round,pad=0.3", facecolor="#ff4444",
                                   edgecolor="none", alpha=0.95))
        self.canvas.draw_idle()

    # ---- Rework box-selection -------------------------------------------
    def set_selecting(self, on):
        """Enable/disable box-selection mode. A previous selection is kept so it
        can still be exported after the operator toggles the mode back off."""
        self._selecting = bool(on)
        self.canvas.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    def set_moving(self, on):
        """Enable/disable move-on-bed mode (left-drag translates the design)."""
        self._moving = bool(on)
        self.canvas.setCursor(Qt.SizeAllCursor if on else Qt.ArrowCursor)

    def _draw_move_ghost(self, dx, dy):
        self._clear_move_ghost()
        if self._move_bbox0 is None:
            return
        x0, y0, x1, y1 = self._move_bbox0
        self._move_ghost = Rectangle(
            (x0 + dx, y0 + dy), x1 - x0, y1 - y0, fill=False,
            edgecolor="#ffd700", linestyle="--", linewidth=1.5, zorder=11)
        self.ax.add_patch(self._move_ghost)
        self.canvas.draw_idle()

    def _clear_move_ghost(self):
        if self._move_ghost is not None:
            try:
                self._move_ghost.remove()
            except (ValueError, NotImplementedError):
                pass
            self._move_ghost = None

    def selection_bbox(self):
        """The current (x0, y0, x1, y1) selection in board mm, or None."""
        return self._selection_bbox

    def clear_selection(self):
        self._selection_bbox = None
        self._drag_start = None
        self._draw_fraction(self.slider.value() / 1000.0)
        if self.on_selection_changed:
            self.on_selection_changed(None)

    def _add_selection_patch(self):
        if not self._selection_bbox:
            return
        x0, y0, x1, y1 = self._selection_bbox
        self._rect_artist = Rectangle(
            (min(x0, x1), min(y0, y1)), abs(x1 - x0), abs(y1 - y0),
            fill=False, edgecolor="#00ff00", linestyle="--", linewidth=1.5,
            zorder=10)
        self.ax.add_patch(self._rect_artist)

    def _redraw_selection_only(self):
        """Cheap update of just the rectangle during a live drag."""
        if self._rect_artist is not None:
            try:
                self._rect_artist.remove()
            except (ValueError, NotImplementedError):
                pass
            self._rect_artist = None
        self._add_selection_patch()
        self.canvas.draw_idle()

    def _on_press(self, event):
        if event.button != 1 or event.inaxes != self.ax:
            return
        if self._selecting:
            self._drag_start = (event.xdata, event.ydata)
        elif self._moving:
            self._move_start = (event.xdata, event.ydata)
            self._move_bbox0 = self._design_bounds()

    def _on_motion(self, event):
        if event.xdata is None or event.ydata is None:
            return
        if self._drag_start is not None:
            x0, y0 = self._drag_start
            self._selection_bbox = (x0, y0, event.xdata, event.ydata)
            self._redraw_selection_only()
        elif self._move_start is not None:
            self._draw_move_ghost(event.xdata - self._move_start[0],
                                  event.ydata - self._move_start[1])

    def _on_release(self, event):
        if self._move_start is not None:
            x0, y0 = self._move_start
            x1 = event.xdata if event.xdata is not None else x0
            y1 = event.ydata if event.ydata is not None else y0
            self._move_start = None
            self._clear_move_ghost()
            if self.on_move_delta and (abs(x1 - x0) > 1e-9 or abs(y1 - y0) > 1e-9):
                self.on_move_delta(x1 - x0, y1 - y0)
            return
        if self._drag_start is None:
            return
        x0, y0 = self._drag_start
        x1 = event.xdata if event.xdata is not None else x0
        y1 = event.ydata if event.ydata is not None else y0
        self._drag_start = None
        if abs(x1 - x0) < 1e-6 or abs(y1 - y0) < 1e-6:
            self._selection_bbox = None       # a click, not a box
        else:
            self._selection_bbox = (min(x0, x1), min(y0, y1),
                                    max(x0, x1), max(y0, y1))
        self._redraw_selection_only()
        if self.on_selection_changed:
            self.on_selection_changed(self._selection_bbox)

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
