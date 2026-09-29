/* The drift check (Level the bed › Measure it › Drift check, Full tier, the v2 firmware).
   Over a long grid the reference itself moves: the spindle warms, the board settles in
   its clamps. Every height is stored relative to point 1, so a point probed minutes later
   reads low by however far the reference has moved. The run re-touches point 1 before
   the first point, every N points and at the end, and corrects each point by the drift
   interpolated to the moment it was probed (engine/spi_probe.py, _interp_drift).
   The drift curve here is illustrative: 60 µm that settles over the run. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var N = 20;                                        // a 5 x 4 grid
  function drift(s) { return 0.060 * (1 - Math.exp(-s / 7)); }   // mm, after s points

  A.define("bl-drift", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 470 : 400;
    var PX = narrow ? 64 : 80, PY = 60, PW = W - PX - 24, PH = narrow ? 300 : 250;
    var svg = A.stage(host, W, H, "How far each point is off, probed in order, with and without the drift check");
    A.text(svg, 24, 34, "ERROR OF EACH POINT, IN THE ORDER IT WAS PROBED", { size: 15, font: "label", weight: 600, fill: C.text3 });
    var EMAX = 0.07;
    function sx(i) { return PX + (i + 0.5) / N * PW; }
    function sy(e) { return PY + PH / 2 - e / EMAX * PH / 2; }
    A.el(svg, "rect", { x: PX, y: PY, width: PW, height: PH, fill: C.panel, stroke: C.ruleHi, rx: 3 });
    [-0.06, -0.03, 0, 0.03, 0.06].forEach(function (e) {
      A.el(svg, "line", { x1: PX, y1: sy(e), x2: PX + PW, y2: sy(e), stroke: e ? C.rule : C.ruleStrong });
      A.text(svg, PX - 8, sy(e) + 5, (e > 0 ? "+" : "") + Math.round(e * 1000), { size: 15, fill: C.text3, anchor: "end", font: "mono" });
    });
    A.text(svg, PX - 8, PY - 10, "µm", { size: 15, fill: C.text3, anchor: "end" });
    for (var i = 0; i < N; i += (narrow ? 4 : 2)) A.text(svg, sx(i), PY + PH + 22, String(i + 1), { size: 15, fill: C.text3, anchor: "middle", font: "mono" });
    A.text(svg, PX + PW, PY + PH + 44, "point, in probing order →", { size: 15, fill: C.text3, anchor: "end" });
    var marks = A.el(svg, "g", {});
    var rawG = A.el(svg, "g", {}), corG = A.el(svg, "g", {});
    var ly = PY + PH + 44;
    A.el(svg, "circle", { cx: PX + 8, cy: ly - 5, r: 6, fill: C.danger });
    A.text(svg, PX + 20, ly, "as read", { size: 15, fill: C.text2 });
    var legC = A.el(svg, "circle", { cx: PX + 108, cy: ly - 5, r: 6, fill: C.ok });
    var legT = A.text(svg, PX + 120, ly, "corrected", { size: 15, fill: C.text2 });

    var row = A.controls(host);
    var st;
    A.segmented(row, [[0, "Drift check: off"], [3, "every 3"], [6, "every 6"], [10, "every 10"]], 6, draw);
    st = A.status(row);
    draw(6);

    function draw(every) {
      if (!st) return;
      [marks, rawG, corG].forEach(function (g) { while (g.firstChild) g.removeChild(g.firstChild); });
      // re-touches: before the first point, every N points, and at the end
      var rt = [];
      if (every) {
        rt.push([0, drift(0)]);
        for (var s = every; s < N; s += every) rt.push([s, drift(s)]);
        rt.push([N, drift(N)]);
      }
      function interp(s) {
        if (s <= rt[0][0]) return rt[0][1];
        for (var k = 0; k < rt.length - 1; k++) if (s <= rt[k + 1][0]) {
          var t = (s - rt[k][0]) / (rt[k + 1][0] - rt[k][0]);
          return rt[k][1] + (rt[k + 1][1] - rt[k][1]) * t;
        }
        return rt[rt.length - 1][1];
      }
      rt.forEach(function (r) {
        var x = PX + r[0] / N * PW;
        A.el(marks, "line", { x1: x, y1: PY + 2, x2: x, y2: PY + PH - 2, stroke: C.live, "stroke-width": 2, "stroke-dasharray": "4 4" });
      });
      if (rt.length) A.text(marks, PX + rt[Math.min(1, rt.length - 1)][0] / N * PW + 6, PY + 22, "re-touch point 1", { size: 15, fill: C.live });
      var worstRaw = 0, worstCor = 0;
      for (var i = 0; i < N; i++) {
        var raw = -drift(i + 0.5);                    // reads low by the drift since the start
        worstRaw = Math.max(worstRaw, Math.abs(raw));
        A.el(rawG, "circle", { cx: sx(i), cy: sy(raw), r: 6, fill: C.danger, opacity: every ? 0.35 : 1 });
        if (every) {
          var cor = raw + (interp(i + 0.5) - rt[0][1]);
          worstCor = Math.max(worstCor, Math.abs(cor));
          A.el(corG, "circle", { cx: sx(i), cy: sy(cor), r: 6, fill: C.ok });
        }
      }
      legC.setAttribute("opacity", every ? 1 : 0.25);
      legT.setAttribute("opacity", every ? 1 : 0.25);
      if (!every) {
        st.className = "anim-status bad";
        st.textContent = "Off: the last points read " + Math.round(worstRaw * 1000) +
          " µm low. That is a third of the 150 µm cut depth, and the map shows it as a slope the board doesn't have.";
      } else {
        st.className = "anim-status ok";
        st.textContent = "Every " + every + " points: " + rt.length + " re-touches of point 1, and the worst point is off by " +
          Math.max(1, Math.round(worstCor * 1000)) + " µm instead of " + Math.round(worstRaw * 1000) +
          " µm. The run says how far the reference moved when it finishes.";
      }
    }
  });
})();
