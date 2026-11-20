/* Mark a clamp (no-go zone) (holding-the-copper.html). engine/nogo.py and
   hardware/probe_bracket/hold_down.py: the lab's printed cam clamp is 26 mm across,
   its screw 5.5 mm off centre, its flat lip 2 mm over the copper. Clicking the bed
   hole the clamp is screwed into places it, turned onto the sheet's nearest edge.
   The bit keeps 1 mm from a clamp; a surface touch that would land on it is moved
   (up to 15 mm, engine/autorun.py); travel is led round it. To scale in mm: a
   100 x 70 mm sheet in the back-right bracket, 2 mm-in touch grid of 4 x 3. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var SW = 100, SH = 70, D = 26, LIP = 2, IN = 2;
  // a board as big as the sheet allows, against the two edges away from the bracket
  var BX = 0, BY = 15, BW = 80, BH = 55;

  A.define("ml-nogo", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 900, H = narrow ? 610 : 440;
    var svg = A.stage(host, W, H, "To scale: a sheet in the bracket with a printed cam clamp on a free edge, marked as a no-go zone; the surface touch that would land under it is moved and the travel goes round it");
    var k = narrow ? 3.9 : 3.9, ox = narrow ? 120 : 140, oy = 80;
    function X(x) { return ox + x * k; }
    function Y(y) { return oy + y * k; }
    A.text(svg, W - 16, 26, "to scale · mm", { size: 13, anchor: "end", fill: C.text4, font: "label", spacing: "0.1em" });
    var head = A.text(svg, 16, 30, "", { size: 18, weight: 700 });
    var g = A.el(svg, "g", {});
    var tx = narrow ? 16 : X(SW) + 70, ty = narrow ? Y(SH) + 140 : 130;
    var lines = [0, 1, 2, 3].map(function (i) { return A.text(svg, tx, ty + i * 26, "", { size: narrow ? 16 : 14, fill: C.text2 }); });

    // touch grid: 4 x 3, 2 mm in from the sheet's edges (schematic: the run measures in from the board)
    function grid() {
      var pts = [];
      for (var j = 0; j < 3; j++) for (var i = 0; i < 4; i++)
        pts.push([BX + IN + i * (BW - 2 * IN) / 3, BY + IN + j * (BH - 2 * IN) / 2]);
      return pts;
    }
    function draw(which) {
      while (g.firstChild) g.removeChild(g.firstChild);
      // bed holes
      for (var hx = -10; hx <= SW + 20; hx += 10) for (var hy = -10; hy <= SH + 20; hy += 10)
        A.el(g, "circle", { cx: X(hx), cy: Y(hy), r: 2.2, fill: C.rule });
      A.el(g, "rect", { x: X(0), y: Y(0), width: SW * k, height: SH * k, fill: C.copperDim, stroke: C.copper });
      A.el(g, "rect", { x: X(BX), y: Y(BY), width: BW * k, height: BH * k, fill: C.copper, opacity: 0.55, stroke: C.copperHi, "stroke-dasharray": "5 4" });
      // the bracket on the back and right
      A.el(g, "path", { d: "M" + X(SW - 51) + " " + Y(-10) + " H" + X(SW + 10) + " V" + Y(51) + " H" + X(SW) + " V" + Y(0) + " H" + X(SW - 51) + " Z", fill: C.fr4, opacity: 0.85 });
      A.text(g, X(SW - 30), Y(-3.5), "bracket", { size: 12, fill: C.ink, weight: 600, anchor: "middle" });
      var clamp = null;
      if (which === "left") clamp = { cx: -D / 2 + LIP, cy: BY + BH / 2, screw: [-D / 2 + LIP - 5.5, BY + BH / 2] };
      if (which === "front") clamp = { cx: BX + IN + (BW - 2 * IN) / 3, cy: SH + D / 2 - LIP, screw: [BX + IN + (BW - 2 * IN) / 3, SH + D / 2 - LIP + 5.5] };
      var pts = grid(), moved = -1, from = null;
      if (clamp) {
        A.el(g, "circle", { cx: X(clamp.cx), cy: Y(clamp.cy), r: (D / 2 + 1) * k, fill: C.dangerFill, stroke: C.danger, "stroke-dasharray": "4 3", opacity: 0.9 });
        A.el(g, "circle", { cx: X(clamp.cx), cy: Y(clamp.cy), r: D / 2 * k, fill: C.raised, stroke: C.steel, "stroke-width": 1.5 });
        A.el(g, "circle", { cx: X(clamp.screw[0]), cy: Y(clamp.screw[1]), r: 4, fill: C.steel });
        A.text(g, X(clamp.cx), Y(clamp.cy) + 5, "clamp", { size: 12, anchor: "middle", fill: C.text });
        // move touches inside the zone straight away from the clamp
        pts = pts.map(function (p, i) {
          var dx = p[0] - clamp.cx, dy = p[1] - clamp.cy, d = Math.sqrt(dx * dx + dy * dy), need = D / 2 + 1 + 1;
          if (d < need) { moved = i; from = p.slice(); return [clamp.cx + dx / d * need, clamp.cy + dy / d * need]; }
          return p;
        });
      }
      if (from) {
        A.el(g, "circle", { cx: X(from[0]), cy: Y(from[1]), r: 4, fill: "none", stroke: C.danger, "stroke-dasharray": "2 2" });
        A.arrow(g, X(from[0]), Y(from[1]), X(pts[moved][0]), Y(pts[moved][1]), { color: C.ok, head: 7, width: 1.5 });
      }
      // travel between two touches round the clamp (schematic path)
      pts.forEach(function (p, i) {
        A.el(g, "path", { d: "M" + (X(p[0]) - 5) + " " + Y(p[1]) + " h10 M" + X(p[0]) + " " + (Y(p[1]) - 5) + " v10", stroke: i === moved ? C.ok : C.ok, "stroke-width": 1.6 });
      });
      head.textContent = which === "none" ? "No clamp marked" : "Clamp marked on the " + which + " edge";
      var L = which === "none"
        ? ["The bracket holds two edges.", "Free edges: tape under the sheet, or clamps.", "Dashed: the board. Green: the 12 touches.", "Pick a clamp to see what marking does."]
        : ["26 mm cam clamp, its lip 2 mm on the copper.", "The bit keeps 1 mm from it (red ring).", "A touch under it moves to free copper.", "Travel is led round it; a cut in it is refused."];
      lines.forEach(function (t, i) { t.textContent = L[i]; });
    }
    var row = A.controls(host);
    A.segmented(row, [["none", "No clamp"], ["left", "Clamp left"], ["front", "Clamp front"]], "left", draw);
  });
})();
