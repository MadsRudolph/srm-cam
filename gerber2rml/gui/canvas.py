"""Matplotlib preview canvas: draws cut/rapid polylines, or drill holes as circles."""
import math
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSlider,
                               QPushButton)
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
        # Trim the dark border around the plot: tiny top/right margins (no labels
        # there) and just enough left/bottom for the axis tick labels + titles.
        self.figure.subplots_adjust(left=0.085, right=0.99, top=0.99, bottom=0.075)
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

        self.fit_btn = QPushButton("Fit")
        self.fit_btn.setToolTip(
            "Reset the zoom to fit the whole job.\n"
            "Scroll to zoom (finer mm grid + more precise click-to-jog as you zoom "
            "in); right-drag to pan.")
        self.fit_btn.setMaximumWidth(60)
        self.fit_btn.clicked.connect(self.fit_view)

        # Collapse/expand the settings panel for a wider preview. Lives on the
        # viewer's control bar (not a bare icon in the corner) so it's findable.
        self.panel_btn = QPushButton("◀  Hide panel")
        self.panel_btn.setCheckable(True)
        self.panel_btn.setToolTip("Hide the settings panel for a wider preview")
        self.on_toggle_panel = None          # callback(collapsed) set by the app
        self.panel_btn.toggled.connect(self._on_panel_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        _bottom = QHBoxLayout(); _bottom.setContentsMargins(0, 0, 0, 0)
        _bottom.addWidget(self.panel_btn)
        _bottom.addWidget(self.fit_btn)
        _bottom.addWidget(self.slider, 1)
        layout.addLayout(_bottom)

        # Zoom/pan view override: when set, used instead of the auto-fit limits so
        # the zoom survives redraws (slider scrub, regenerate). Cleared by Fit.
        self._view_limits = None
        self._panning = False

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

        # Board outline (the Edge.Cuts boundary) as a list of (x, y) vertices,
        # drawn so the physical board edge is always visible, not just the
        # toolpaths inside it. None = hidden.
        self._outline_xy = None

        # Physical copper stock: (x0, y0, w, h) mm on the bed — the actual piece of
        # copper you measured, drawn so you can line the design (and dowels) up
        # inside it. None = hidden.
        self._stock = None
        self._stock_fits = True

        # Bed-leveling height map overlay: (X, Y, Z) meshes of surface deviation
        # (mm) + the probe points [(x, y, dz)], drawn under the toolpaths so you
        # can eyeball the tilt/warp before cutting. None = hidden.
        self._level_overlay = None

        # Bed-leveling probe grid: the planned (x, y) probe points, drawn as
        # numbered markers so you can see where it will probe before measuring.
        # None = hidden.
        self._probe_grid = None

        # Live tool position (machine mm) for the DRO overlay — a crosshair+ring
        # showing where the spindle is over the bed. None = hidden.
        self._tool_pos = None
        self._tool_touch = False
        self._tool_artists = []

        # Breadcrumb trail of where the tool has actually been (live DRO samples),
        # drawn as a recency-faded amber line so you can follow the bit's tracks
        # during a rework pass. Capped so a long job can't grow it without bound.
        self._tool_trail = []
        self._tool_trail_on = True
        self._tool_trail_artist = None

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

        # Click-to-jog: in this mode a left-click reports the bed (x, y) so the
        # app can drive the machine there. Mutually exclusive with select/move.
        self._jogging = False
        self.on_jog_to = None             # callback(x, y) set by the app

        # Arrow-key carriage jog: while the mouse is over the preview, the arrow
        # keys nudge the machine in X/Y. on_jog_step(dx, dy) reports a signed
        # step in board mm; the app turns it into a relative machine move.
        self.on_jog_step = None
        self._hover = False               # mouse currently over the canvas
        self.canvas.setFocusPolicy(Qt.StrongFocus)

        # Measure (ruler): drag a line that snaps to the board's corners, edges
        # and hole centres, reading out length + dx/dy. Corner-to-corner gives
        # the board size. Mutually exclusive with the other drag modes.
        self._measuring = False
        self._measure_start = None        # snapped (x, y) of the drag start
        self._measure_line = None         # (x0, y0, x1, y1) of the ruler, or None
        self._measure_artists = []
        self._snap_pts = []               # corners + hole centres to snap to
        self._snap_segs = []              # outline edge segments (ax, ay, bx, by)

        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("figure_enter_event", self._on_enter)
        self.canvas.mpl_connect("figure_leave_event", self._on_leave)
        self.canvas.mpl_connect("key_press_event", self._on_key)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)

    def _on_panel_btn(self, collapsed):
        """Viewer's settings-panel collapse toggle: flip the label and report it."""
        self.panel_btn.setText("▶  Show panel" if collapsed else "◀  Hide panel")
        if self.on_toggle_panel:
            self.on_toggle_panel(collapsed)

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

    def set_board_outline(self, outline_xy):
        """Set the board's Edge.Cuts boundary as a list of (x, y) vertices (open
        ring), or ``None`` to hide it. Stored; drawn on the next redraw."""
        self._outline_xy = outline_xy or None

    def set_stock(self, rect):
        """Show the physical copper stock as ``(x0, y0, w, h)`` mm on the bed, or
        ``None`` to hide it. Redraws so the change is immediate."""
        self._stock = rect if (rect and rect[2] > 0 and rect[3] > 0) else None
        self._draw_fraction(self.slider.value() / 1000.0)

    def set_level_overlay(self, X=None, Y=None, Z=None, points=None):
        """Show (or clear, with no args) the height-map heatmap. ``X``/``Y``/``Z``
        are 2D meshes of surface deviation (mm); ``points`` are the probed
        ``(x, y, dz)`` in mm. Redraws immediately."""
        self._level_overlay = (X, Y, Z, points) if X is not None else None
        self._draw_fraction(self.slider.value() / 1000.0)

    def set_probe_grid(self, points):
        """Show (or clear, with ``None``) the planned bed-leveling probe points as
        numbered markers. ``points`` is a list of (x, y) in board mm. Redraws."""
        self._probe_grid = list(points) if points else None
        self._draw_fraction(self.slider.value() / 1000.0)

    # Trail tuning: drop samples closer than this (mm) so jitter doesn't pile up,
    # and cap the point count so a long job stays responsive.
    _TRAIL_MIN_STEP = 0.2
    _TRAIL_MAX = 4000

    def set_tool_position(self, x, y, touch=False):
        """Show (or clear, with ``None``) the live tool marker at machine ``(x, y)``
        mm; ``touch`` turns it red when the bit is contacting the plate. Each new
        position also extends the breadcrumb trail. Lightweight: updates just the
        marker + trail, no full redraw."""
        if x is not None and self._tool_trail_on:
            if (not self._tool_trail
                    or math.hypot(x - self._tool_trail[-1][0],
                                  y - self._tool_trail[-1][1]) >= self._TRAIL_MIN_STEP):
                self._tool_trail.append((x, y))
                if len(self._tool_trail) > self._TRAIL_MAX:
                    del self._tool_trail[:-self._TRAIL_MAX]
        self._tool_pos = (x, y) if x is not None else None
        self._tool_touch = bool(touch)
        self._redraw_tool_only()

    def clear_tool_trail(self):
        """Wipe the breadcrumb trail (e.g. when starting a fresh pass)."""
        self._tool_trail = []
        self._redraw_tool_only()

    def set_tool_trail_visible(self, on):
        """Show/hide the breadcrumb trail. Hiding also stops recording so it
        doesn't silently accumulate while invisible."""
        self._tool_trail_on = bool(on)
        if not on:
            self._tool_trail = []
        self._redraw_tool_only()

    def _add_tool_trail(self):
        """Draw the trail as segments fading from dim (oldest) to bright amber
        (newest), so the freshest tracks read clearly over the cyan toolpaths."""
        if not self._tool_trail_on or len(self._tool_trail) < 2:
            return
        pts = self._tool_trail
        segs = [[pts[i], pts[i + 1]] for i in range(len(pts) - 1)]
        n = len(segs)
        colors = [(1.0, 0.78, 0.12, 0.15 + 0.75 * (i / max(n - 1, 1)))
                  for i in range(n)]                # alpha 0.15 -> 0.90 over the run
        self._tool_trail_artist = LineCollection(
            segs, colors=colors, linewidths=1.7, zorder=14)
        self.ax.add_collection(self._tool_trail_artist)

    def _add_tool_marker(self):
        if not self._tool_pos:
            return
        x, y = self._tool_pos
        c = "#ff3b3b" if self._tool_touch else "#39ff14"   # red on contact, else green
        self._tool_artists = [
            self.ax.axhline(y, color=c, lw=0.5, alpha=0.4, zorder=15),
            self.ax.axvline(x, color=c, lw=0.5, alpha=0.4, zorder=15),
            self.ax.scatter([x], [y], s=70, facecolors="none", edgecolors=c,
                            linewidths=1.5, zorder=16),
            self.ax.scatter([x], [y], s=8, c=c, zorder=16),
        ]

    def _redraw_tool_only(self):
        if self._tool_trail_artist is not None:
            try:
                self._tool_trail_artist.remove()
            except (ValueError, NotImplementedError):
                pass
            self._tool_trail_artist = None
        for a in self._tool_artists:
            try:
                a.remove()
            except (ValueError, NotImplementedError):
                pass
        self._tool_artists = []
        self._add_tool_trail()
        self._add_tool_marker()
        self.canvas.draw_idle()

    def _draw_level_overlay(self):
        X, Y, Z, points = self._level_overlay
        zmax = max(abs(min(min(r) for r in Z)), abs(max(max(r) for r in Z)), 1e-4)
        self.ax.pcolormesh(X, Y, Z, cmap="coolwarm", alpha=0.55, zorder=0,
                           shading="auto", vmin=-zmax, vmax=zmax)
        if points:
            self.ax.scatter([p[0] for p in points], [p[1] for p in points],
                            s=18, facecolors="none", edgecolors="#1e1e1e", zorder=3)
            for (x, y, dz) in points:           # label each point in microns
                self.ax.annotate(f"{dz * 1000:+.0f}", (x, y), color="#1e1e1e",
                                 fontsize=7, ha="center", va="bottom", zorder=3)
            lo = min(p[2] for p in points) * 1000.0
            hi = max(p[2] for p in points) * 1000.0
            self.ax.text(0.98, 0.98, f"surface {lo:+.0f}..{hi:+.0f} um",
                         transform=self.ax.transAxes, va="top", ha="right",
                         fontsize=9, color="#1e1e1e", zorder=20,
                         bbox=dict(boxstyle="round,pad=0.3", facecolor="#88bbff",
                                   edgecolor="none", alpha=0.95))

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
        self.ax.set_axisbelow(True)                 # grid behind the toolpaths
        self.ax.tick_params(colors='#d4d4d4', labelsize=8)
        self.ax.set_xlabel("X (mm)", color="#8a9099", fontsize=8)
        self.ax.set_ylabel("Y (mm)", color="#8a9099", fontsize=8)
        for spine in self.ax.spines.values():
            spine.set_color('#333333')
        # the actual mm grid is set in _apply_ruler_grid (needs the view limits)

    @staticmethod
    def _nice_step(raw):
        """Round ``raw`` up to a 'nice' 1/2/5 x 10^n step (ruler-friendly)."""
        import math
        if raw <= 0:
            return 1.0
        base = 10.0 ** math.floor(math.log10(raw))
        for m in (1, 2, 5):
            if raw <= m * base:
                return m * base
        return 10 * base

    def _apply_ruler_grid(self):
        """A ruler-like mm grid: labeled major lines + a finer minor grid. The
        spacing is chosen from the current view span so it stays readable whether
        you're looking at a 20 mm coupon or the whole bed."""
        from matplotlib.ticker import MultipleLocator
        x0, x1 = sorted(self.ax.get_xlim())
        y0, y1 = sorted(self.ax.get_ylim())
        span = max(x1 - x0, y1 - y0, 1.0)
        major = self._nice_step(span / 8.0)         # ~8 labeled divisions across
        minor = max(major / 10.0, 0.001)            # fine ticks (down to the step size)
        for axis in (self.ax.xaxis, self.ax.yaxis):
            axis.set_major_locator(MultipleLocator(major))
            axis.set_minor_locator(MultipleLocator(minor))
        self.ax.grid(True, which="major", color="#45454a", linewidth=0.7, alpha=0.9)
        self.ax.grid(True, which="minor", color="#2b2b2e", linewidth=0.4, alpha=0.7)
        self.ax.tick_params(which="major", length=5, colors="#d4d4d4", labelsize=8)
        self.ax.tick_params(which="minor", length=2, colors="#666666")

    # ---- zoom / pan -----------------------------------------------------
    _MIN_SPAN_MM = 0.2          # don't zoom in past ~0.2 mm (well under a step)

    def _set_view(self, x0, x1, y0, y1):
        """Apply a zoom/pan view and remember it so redraws keep it."""
        self._view_limits = (x0, x1, y0, y1)
        self.ax.set_xlim(x0, x1)
        self.ax.set_ylim(y0, y1)
        self._apply_ruler_grid()
        self.canvas.draw_idle()

    def fit_view(self):
        """Reset the zoom to fit the whole job (clears any zoom/pan)."""
        self._view_limits = None
        self._draw_fraction(self.slider.value() / 1000.0)

    reset_view = fit_view

    def _on_scroll(self, event):
        """Scroll wheel zooms about the cursor; the mm grid refines as you zoom
        in, and click-to-jog gets finer (clicks resolve in data/mm coordinates)."""
        if event.inaxes != self.ax or event.xdata is None:
            return
        zoom_in = event.button == "up"
        scale = 1 / 1.25 if zoom_in else 1.25
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        cx, cy = event.xdata, event.ydata
        nx0, nx1 = cx + (x0 - cx) * scale, cx + (x1 - cx) * scale
        ny0, ny1 = cy + (y0 - cy) * scale, cy + (y1 - cy) * scale
        if zoom_in and (abs(nx1 - nx0) < self._MIN_SPAN_MM
                        or abs(ny1 - ny0) < self._MIN_SPAN_MM):
            return                                  # already at max zoom
        self._set_view(nx0, nx1, ny0, ny1)

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

        self._stock_fits = True
        if self._stock:
            sx, sy, sw, sh = self._stock
            db = self._design_bounds()
            # design (incl. dowels) must sit inside the copper
            self._stock_fits = db is None or (
                db[0] >= sx - 1e-6 and db[1] >= sy - 1e-6
                and db[2] <= sx + sw + 1e-6 and db[3] <= sy + sh + 1e-6)
            edge = "#d9943f" if self._stock_fits else "#ff4444"
            self.ax.add_patch(Rectangle((sx, sy), sw, sh, facecolor="#b87333",
                                        alpha=0.16, edgecolor=edge, linewidth=1.6,
                                        zorder=0.5))

        if self._outline_xy:
            # the board edge (Edge.Cuts) — a subtle closed boundary so the PCB
            # outline is always visible, not just the cuts inside it
            ox = [p[0] for p in self._outline_xy] + [self._outline_xy[0][0]]
            oy = [p[1] for p in self._outline_xy] + [self._outline_xy[0][1]]
            self.ax.plot(ox, oy, color="#9aa0a6", lw=1.2, alpha=0.9, zorder=1)

        if self._level_overlay is not None:
            self._draw_level_overlay()

        if self._probe_grid:
            gx = [p[0] for p in self._probe_grid]
            gy = [p[1] for p in self._probe_grid]
            self.ax.scatter(gx, gy, s=70, marker="P", facecolors="#ff9a3c",
                            edgecolors="#1e1e1e", linewidths=0.8, zorder=13)
            for i, (px, py) in enumerate(self._probe_grid, 1):
                self.ax.annotate(str(i), (px, py), color="#ff9a3c", fontsize=7,
                                 ha="left", va="bottom", zorder=13,
                                 xytext=(3, 3), textcoords="offset points")

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
        if self._view_limits is not None:    # user zoom/pan overrides the auto-fit
            x0, x1, y0, y1 = self._view_limits
            self.ax.set_xlim(x0, x1)
            self.ax.set_ylim(y0, y1)
        elif self._limits:
            x0, x1, y0, y1 = self._limits
            # flip_x reverses the x-axis to show the un-mirrored "as designed"
            # orientation; the data underneath is unchanged.
            self.ax.set_xlim((x1, x0) if self._flip_x else (x0, x1))
            self.ax.set_ylim(y0, y1)
        self._apply_ruler_grid()             # mm ruler grid, sized to the view
        # ax.clear() above dropped the selection rectangle; re-add it so the
        # picked area stays visible while scrubbing or regenerating the preview.
        self._rect_artist = None
        self._add_selection_patch()
        self._tool_artists = []          # ax.clear() dropped them; re-add live marker
        self._tool_trail_artist = None   # and the breadcrumb trail under it
        self._add_tool_trail()
        self._add_tool_marker()
        self._measure_artists = []       # ax.clear() dropped the ruler; re-add it
        self._add_measure_artist()
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
        if self._stock and not self._stock_fits:
            self.ax.text(0.02, 0.02, "DESIGN EXCEEDS COPPER", transform=self.ax.transAxes,
                         va="bottom", ha="left", fontsize=9, color="#1e1e1e", zorder=20,
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

    def set_jogging(self, on):
        """Enable/disable click-to-jog mode (a left-click reports the bed point)."""
        self._jogging = bool(on)
        self.canvas.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)

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
        if event.inaxes != self.ax:
            return
        if event.button == 3:                    # right-drag = pan
            self._panning = True
            self.ax.start_pan(event.x, event.y, 1)   # button 1 => pan (not zoom)
            return
        if event.button != 1:
            return
        if self._jogging:
            if self.on_jog_to and event.xdata is not None and event.ydata is not None:
                self.on_jog_to(event.xdata, event.ydata)
        elif self._measuring:
            sx, sy, _ = self._snap(event.xdata, event.ydata)
            if sx is not None:
                self._measure_start = (sx, sy)
                self._measure_line = (sx, sy, sx, sy)
        elif self._selecting:
            self._drag_start = (event.xdata, event.ydata)
        elif self._moving:
            self._move_start = (event.xdata, event.ydata)
            self._move_bbox0 = self._design_bounds()

    def _on_motion(self, event):
        if self._panning and event.x is not None:
            self.ax.drag_pan(1, event.key, event.x, event.y)
            self._view_limits = (*self.ax.get_xlim(), *self.ax.get_ylim())
            self._apply_ruler_grid()
            self.canvas.draw_idle()
            return
        if event.xdata is None or event.ydata is None:
            return
        if self._measure_start is not None:
            sx, sy, _ = self._snap(event.xdata, event.ydata)
            x0, y0 = self._measure_start
            self._measure_line = (x0, y0, sx, sy)
            self._redraw_measure_only()
            return
        if self._drag_start is not None:
            x0, y0 = self._drag_start
            self._selection_bbox = (x0, y0, event.xdata, event.ydata)
            self._redraw_selection_only()
        elif self._move_start is not None:
            self._draw_move_ghost(event.xdata - self._move_start[0],
                                  event.ydata - self._move_start[1])

    def _on_release(self, event):
        if self._panning:
            self.ax.end_pan()
            self._panning = False
            return
        if self._measure_start is not None:
            self._measure_start = None       # keep the finished ruler displayed
            return
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

    # ---- Arrow-key carriage jog (active while the mouse is over the canvas) ----
    _JOG_KEYS = {"left": (-1, 0), "right": (1, 0), "up": (0, 1), "down": (0, -1)}

    def _on_enter(self, event):
        """Mouse entered the preview: grab keyboard focus so the arrow keys jog
        the carriage without needing a click first."""
        self._hover = True
        self.canvas.setFocus()

    def _on_leave(self, event):
        """Mouse left the preview: release focus so typing goes back to the
        settings fields, and stop handling arrow-key jogs."""
        self._hover = False
        self.canvas.clearFocus()

    def _on_key(self, event):
        """Arrow keys nudge the carriage in X/Y while the mouse is over the
        canvas. Step = 1 mm, Shift = 10 mm (coarse), Ctrl = 0.1 mm (fine).
        Reports a signed (dx, dy) in board mm; the app makes it a relative move."""
        if not self._hover or not self.on_jog_step or not event.key:
            return
        base = event.key.rsplit("+", 1)[-1]        # strip any modifier prefixes
        if base not in self._JOG_KEYS:
            return
        step = 0.1 if "ctrl" in event.key else (10.0 if "shift" in event.key else 1.0)
        ux, uy = self._JOG_KEYS[base]
        dx = -ux * step if self._flip_x else ux * step   # keep on-screen dir intuitive
        self.on_jog_step(dx, uy * step)

    # ---- Measure (ruler) with snapping --------------------------------------
    def set_measuring(self, on):
        """Enable/disable ruler mode. Leaving the mode clears the drawn line."""
        self._measuring = bool(on)
        self.canvas.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        if not on:
            self._measure_start = None
            self._measure_line = None
            self._redraw_measure_only()

    def set_snap_geometry(self, outline_xy=None, holes=None):
        """Give the ruler the board outline vertices and hole centres to snap to.
        ``outline_xy`` is a list of (x, y) perimeter vertices (open ring); its
        consecutive pairs become the snappable edges."""
        pts, segs = [], []
        if outline_xy:
            n = len(outline_xy)
            for i, (x, y) in enumerate(outline_xy):
                pts.append((x, y))
                nx, ny = outline_xy[(i + 1) % n]
                segs.append((x, y, nx, ny))
        if holes:
            pts += [(h[0], h[1]) for h in holes]
        self._snap_pts, self._snap_segs = pts, segs

    @staticmethod
    def _project(px, py, ax, ay, bx, by):
        """Closest point to (px, py) on the segment (ax,ay)-(bx,by)."""
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 == 0:
            return ax, ay
        t = ((px - ax) * dx + (py - ay) * dy) / L2
        t = max(0.0, min(1.0, t))
        return ax + t * dx, ay + t * dy

    def _snap(self, x, y):
        """Snap (x, y) to the nearest corner/hole/edge within a view-relative
        tolerance. Returns (sx, sy, snapped?)."""
        if x is None or y is None:
            return x, y, False
        from math import hypot
        x0, x1 = sorted(self.ax.get_xlim())
        y0, y1 = sorted(self.ax.get_ylim())
        tol = 0.03 * max(x1 - x0, y1 - y0, 1e-6)
        best, bestd = None, tol
        for (px, py) in self._snap_pts:               # corners + hole centres
            d = hypot(x - px, y - py)
            if d < bestd:
                bestd, best = d, (px, py)
        for (ax_, ay_, bx_, by_) in self._snap_segs:  # outline edges
            qx, qy = self._project(x, y, ax_, ay_, bx_, by_)
            d = hypot(x - qx, y - qy)
            if d < bestd:
                bestd, best = d, (qx, qy)
        if best is not None:
            return best[0], best[1], True
        return x, y, False

    def _add_measure_artist(self):
        if not self._measure_line:
            return
        from math import hypot
        x0, y0, x1, y1 = self._measure_line
        col = "#ffd24a"
        self._measure_artists = [
            self.ax.plot([x0, x1], [y0, y1], color=col, lw=1.4, zorder=18)[0],
            self.ax.scatter([x0, x1], [y0, y1], s=32, facecolors=col,
                            edgecolors="#1e1e1e", linewidths=0.8, zorder=19),
        ]
        L = hypot(x1 - x0, y1 - y0)
        if L > 1e-6:
            mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            label = f"{L:.2f} mm   (dx {abs(x1 - x0):.2f}, dy {abs(y1 - y0):.2f})"
            self._measure_artists.append(
                self.ax.annotate(label, (mx, my), color="#1e1e1e", fontsize=8,
                                 ha="center", va="center", zorder=20,
                                 bbox=dict(boxstyle="round,pad=0.3", facecolor=col,
                                           edgecolor="none", alpha=0.95)))

    def _redraw_measure_only(self):
        for a in self._measure_artists:
            try:
                a.remove()
            except (ValueError, NotImplementedError):
                pass
        self._measure_artists = []
        self._add_measure_artist()
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
