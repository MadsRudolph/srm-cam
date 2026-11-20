/* Why even a laser board is levelled (mill.html, make-a-board.html).
   The run drills every hole and cuts the outline 2.0 mm deep into a 1.6 mm board:
   0.4 mm to spare (engine config, gui2/autorun.py). A sheet that dips by more than
   that, zeroed at one spot and not levelled, leaves holes that are not through
   where it is low: drums1 (2026-11-19), a 124 mm sheet, came out with only its left-
   and right-most holes through. Levelled (12 touches, 4 x 3), the cut follows the
   copper and every hole goes through. The run refuses a sheet more than 1.0 mm out
   of flat. Lengths in mm along the sheet; heights stretched x40 so 0.1 mm shows. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var L = 124, T = 1.6, DEPTH = 2.0, ZERO_AT = 15;
  var HOLES = [6, 20, 34, 48, 62, 76, 90, 104, 118];

  A.define("ml-level", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 420 : 340;
    var svg = A.stage(host, W, H, "A cross-section of a 124 mm sheet that dips in the middle, drilled 2.0 mm deep, zeroed at one spot or levelled");
    var x0 = 24, kx = (W - 48) / L, ky = 40;          // px per mm across, and up (x40)
    var base = narrow ? 150 : 112;                      // y of z = 0 (the zero spot's copper)
    function X(x) { return x0 + x * kx; }
    function Y(z) { return base - z * ky; }
    A.text(svg, 16, 30, "", { size: 18, weight: 700 });
    var head = svg.lastChild;
    A.text(svg, W - 16, 28, "heights ×40", { size: 13, anchor: "end", fill: C.text4, font: "label", spacing: "0.1em" });
    var g = A.el(svg, "g", {});
    var out = A.text(svg, 16, H - 50, "", { size: narrow ? 17 : 15, fill: C.text2 });
    var out2 = A.text(svg, 16, H - 24, "", { size: narrow ? 17 : 15, fill: C.text2 });
    var bow = 0.8, mode = "one";

    function surf(x) { return -bow * Math.sin(Math.PI * x / L); }   // dips in the middle
    function draw() {
      while (g.firstChild) g.removeChild(g.firstChild);
      // the bed
      A.el(g, "rect", { x: X(0) - 10, y: Y(-T - bow), width: L * kx + 20, height: 12, fill: C.raised });
      A.text(g, X(L) + 4, Y(-T - bow) + 28, "bed", { size: 12, anchor: "end", fill: C.text3 });
      // the board (FR-4 under copper), as a polygon along the dip
      var top = [], bot = [];
      for (var i = 0; i <= 62; i++) {
        var x = L * i / 62;
        top.push(X(x) + "," + Y(surf(x)));
        bot.unshift(X(x) + "," + Y(surf(x) - T));
      }
      A.el(g, "polygon", { points: top.concat(bot).join(" "), fill: C.fr4, opacity: 0.9 });
      A.el(g, "polyline", { points: top.join(" "), fill: "none", stroke: C.copperHi, "stroke-width": 3 });
      var z0 = surf(ZERO_AT);
      // the zero touch
      A.el(g, "line", { x1: X(ZERO_AT), y1: Y(z0) - 40, x2: X(ZERO_AT), y2: Y(z0) - 4, stroke: C.live, "stroke-width": 2 });
      A.text(g, X(ZERO_AT) + 6, Y(z0) - 30, mode === "one" ? "Z zero here" : "", { size: 13, fill: C.live });
      if (mode === "lev") {
        for (var j = 0; j < 4; j++) {
          var tx = 2 + j * (L - 4) / 3;
          A.el(g, "path", { d: "M" + (X(tx) - 6) + " " + (Y(surf(tx)) - 40) + " h12 l-6 10 z", fill: C.live });
        }
      }
      var through = 0;
      HOLES.forEach(function (hx) {
        var s = surf(hx), bottom = mode === "one" ? z0 - DEPTH : s - DEPTH;
        var ok = bottom <= s - T + 1e-9;
        if (ok) through++;
        A.el(g, "rect", { x: X(hx) - 4, y: Y(s) - 1, width: 8, height: Math.max(0, Y(bottom) - Y(s)) + 1, fill: C.ink });
        A.el(g, "circle", { cx: X(hx), cy: Y(s) - 14, r: 6, fill: ok ? C.ok : C.danger });
      });
      // 0.4 mm spare tick near the zero
      head.textContent = mode === "one" ? (narrow ? "One spot, not levelled" : "Zeroed at one spot, not levelled") : (narrow ? "Levelled: 12 touches" : "Levelled: 12 touches, the cut follows the copper");
      out.textContent = narrow ? "Cut 2.0 mm into 1.6 mm: 0.4 mm spare." : "Dip " + bow.toFixed(2) + " mm over 124 mm · cut 2.0 mm into 1.6 mm: 0.4 mm spare.";
      out2.textContent = through + " of " + HOLES.length + " holes through" + (narrow ? "" : " (green dot = through)") +
        (bow > 1.0 ? (narrow ? " · over 1.0 mm: refused." : " · the run refuses a sheet over 1.0 mm out of flat.") : through < HOLES.length ? ": the low middle is missed." : ".");
      out2.setAttribute("fill", through === HOLES.length && bow <= 1.0 ? C.ok : C.caution);
    }
    var row = A.controls(host);
    A.segmented(row, [["one", narrow ? "One spot" : "One spot, not levelled"], ["lev", narrow ? "Levelled" : "Levelled (4 × 3)"]], "one", function (v) { mode = v; draw(); });
    A.slider(row, "Dip", 0, 1.2, 0.05, bow, function (v) { bow = v; draw(); }, function (v) { return v.toFixed(2) + " mm"; });
  });
})();
