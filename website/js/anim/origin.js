/* "origin" — Zero Z only. Side view: the bit comes down until SRM-CAM reads Touch, and
   that surface becomes Z 0 (VPanel: G54, Set Origin Point › Z). Top view: X and Y stay
   at the machine origin, the front-left corner of the bed; the copper's own corner is
   found with the probe and told to SRM-CAM instead. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  A.define("origin", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var PW = 420, PH = 390;                       // one panel
    var W = narrow ? 440 : 880, H = narrow ? 2 * PH + 30 : PH + 20;
    var svg = A.stage(host, W, H, "Zero Z only: Z zero on the copper surface; X and Y stay at the machine origin");
    var P1 = { x: 10, y: 10 }, P2 = narrow ? { x: 10, y: PH + 20 } : { x: 450, y: 10 };

    function panel(p, title) {
      var g = A.el(svg, "g", { transform: "translate(" + p.x + "," + p.y + ")" });
      A.el(g, "rect", { x: 0, y: 0, width: PW, height: PH, rx: 4, fill: C.panel, stroke: C.ruleHi });
      A.text(g, 18, 30, title, { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
      return g;
    }

    // ---- side view -------------------------------------------------------
    var s = panel(P1, "SIDE VIEW");
    var CU = 292;                                   // copper surface
    A.el(s, "rect", { x: 40, y: CU + 8, width: 340, height: 44, fill: C.board });
    A.el(s, "rect", { x: 40, y: CU, width: 340, height: 8, fill: C.copper });
    A.text(s, 210, CU + 36, "copper on the spoilboard", { size: 15, anchor: "middle", fill: "#e6d9c4" });
    var zline = A.el(s, "g", { opacity: 0 });
    A.el(zline, "line", { x1: 20, y1: CU, x2: 400, y2: CU, stroke: C.caution, "stroke-width": 2, "stroke-dasharray": "7 5" });
    A.text(zline, 250, CU - 58, "Z 0 = the copper", { size: 20, weight: 700, fill: C.caution });
    A.text(zline, 250, CU - 34, "G54 › Set Origin Point › Z", { size: 15, fill: C.text2 });
    var bit = A.el(s, "g");
    A.el(bit, "rect", { x: 138, y: -140, width: 64, height: 80, rx: 3, fill: "#5b616c" });
    A.el(bit, "rect", { x: 150, y: -60, width: 40, height: 24, fill: C.steelDim });
    A.el(bit, "rect", { x: 164, y: -36, width: 12, height: 36, fill: C.steel });
    A.el(bit, "line", { x1: 164, y1: 0, x2: 176, y2: 0, stroke: C.copperHi, "stroke-width": 3 });
    var touch = A.el(s, "g", { opacity: 0 });
    A.el(touch, "rect", { x: 18, y: 48, width: 118, height: 34, rx: 4, fill: C.dangerFill, stroke: C.danger });
    A.text(touch, 77, 71, "TOUCH", { size: 17, weight: 700, fill: C.danger, anchor: "middle", font: "label" });
    var down = A.arrow(s, 100, 120, 100, 220, { color: C.text3 });

    // ---- top view --------------------------------------------------------
    var t = panel(P2, "TOP VIEW · THE BED");
    var bx = 40, by = 56, bw = 345, bh = 258, k = bw / 203;       // 203 × 152 mm travel
    A.el(t, "rect", { x: bx, y: by, width: bw, height: bh, fill: C.sunk, stroke: C.ruleStrong });
    var cx = bx + 60.52 * k, cy = by + bh - 24.42 * k;               // copper corner (the recording's numbers)
    A.el(t, "rect", { x: cx, y: cy - 90 * k, width: 120 * k, height: 90 * k, fill: C.copper, opacity: 0.9 });
    A.el(t, "circle", { cx: bx, cy: by + bh, r: 8, fill: C.caution });
    A.text(t, bx + 14, by + bh + 26, "X, Y = machine origin: leave alone", { size: 16, weight: 600, fill: C.caution });
    A.text(t, bx + 14, by + bh + 48, "the files assume it (G54)", { size: 15, fill: C.text2 });
    var corner = A.el(t, "g", { opacity: 0 });
    A.el(corner, "circle", { cx: cx, cy: cy, r: 13, fill: "none", stroke: C.text, "stroke-width": 2 });
    A.el(corner, "circle", { cx: cx, cy: cy, r: 6, fill: C.text });
    var clabel = A.el(t, "g", { opacity: 0 });
    A.el(clabel, "rect", { x: cx + 10, y: cy - 150, width: 238, height: 58, rx: 4, fill: C.panel, opacity: 0.92 });
    A.text(clabel, cx + 22, cy - 126, "copper corner: found with", { size: 16, weight: 600 });
    A.text(clabel, cx + 22, cy - 104, "the probe, told to SRM-CAM", { size: 16, weight: 600 });

    function tick(tt) {
      var k1 = A.ease((tt - 0.5) / 1.8);
      var y = A.lerp(170, CU, k1);
      A.set(bit, { transform: "translate(0," + y + ")" });
      var on = tt >= 2.3;
      touch.setAttribute("opacity", on ? 1 : 0);
      down.setAttribute("opacity", on ? 0 : 1);
      zline.setAttribute("opacity", A.ease((tt - 2.8) / 0.5));
      corner.setAttribute("opacity", A.ease((tt - 3.5) / 0.4));
      clabel.setAttribute("opacity", A.ease((tt - 4.0) / 0.5));
      if (tt > 5 && lp) lp.stop();                 // finished: stop ticking until Replay
    }
    var lp = null;
    lp = A.loop(host, tick, 6);
    var row = A.controls(host);
    A.button(row, "Replay", function () { lp.restart(); if (A.reduced) tick(6); });
  });
})();
