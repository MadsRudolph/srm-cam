/* One gap, three methods. Two nets of copper with a gap between them, to scale,
   under each way SRM-CAM makes copper: the 0.8 mm flat end mill (a 0.8 mm channel),
   the 0.8 mm ball mill (0.44 mm at the copper surface) and the fiber laser (rings
   that clear about 0.22 mm out from every copper edge, nothing under 0.20 mm).
   Drag the gap: each panel says whether its tool can separate the nets. The numbers
   under each panel are what KiCad's "Set design rules for SRM-CAM" writes for that
   method (kicad-plugin/srm20area/methods.py). */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  var METHODS = [
    { name: "Flat mill", tool: "0.8 mm flat end mill", kind: "mill", width: 0.80,
      floor: 0.80, clearance: 0.85, track: 1.0, color: C.copperHi },
    { name: "Ball mill", tool: "0.44 mm channel at the copper", kind: "mill", width: 0.44,
      floor: 0.44, clearance: 0.50, track: 0.5, color: C.caution },
    { name: "Laser", tool: "rings, 0.22 mm from each edge", kind: "laser", width: 0.22,
      floor: 0.20, clearance: 0.25, track: 0.3, color: C.live }
  ];
  var GMIN = 0.15, GMAX = 1.0;

  A.define("mb-rules", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 900;
    var PW = narrow ? 472 : 278, PG = 13, PX0 = 24;
    var DH = 170;                               // the to-scale drawing's height
    var PH = 372;                               // one panel
    var K = narrow ? 120 : 112;                 // px per mm
    var top = 18;
    var scaleY = narrow ? top + 3 * (PH + 14) + 6 : top + PH + 26;
    var L = scaleY + 58;                        // the scale's line
    var H = L + 46;
    var svg = A.stage(host, W, H, "One gap between two nets under the flat mill, the ball mill and the laser, to scale, with each method's design rules");

    var uid = "mbr" + Math.floor(Math.random() * 1e6);
    var panels = METHODS.map(function (m, i) {
      var x = narrow ? PX0 : PX0 + i * (PW + PG);
      var y = narrow ? top + i * (PH + 14) : top;
      var g = A.el(svg, "g", {});
      A.el(g, "rect", { x: x, y: y, width: PW, height: PH, rx: 4, fill: C.panel, stroke: C.ruleHi });
      A.el(g, "rect", { x: x, y: y, width: PW, height: 3, fill: m.color });
      A.text(g, x + 14, y + 28, m.name, { size: 19, weight: 700, font: "label", fill: C.text });
      A.text(g, x + 14, y + 48, m.tool, { size: 13, fill: C.text3 });

      var dx = x + 10, dy = y + 60, dw = PW - 20;
      var clip = A.el(svg, "clipPath", { id: uid + "c" + i });
      A.el(clip, "rect", { x: dx, y: dy, width: dw, height: DH, rx: 3 });
      var d = A.el(g, "g", { "clip-path": "url(#" + uid + "c" + i + ")" });
      A.el(d, "rect", { x: dx, y: dy, width: dw, height: DH, fill: C.fr4 });
      var p = {
        m: m, x: x, y: y, cx: dx + dw / 2, dy: dy, dw: dw,
        left: A.el(d, "rect", { y: dy, height: DH, fill: C.copper }),
        right: A.el(d, "rect", { y: dy, height: DH, fill: C.copper }),
        bridge: A.el(d, "rect", { y: dy, height: DH, fill: C.copper }),
        cuts: [A.el(d, "rect", { y: dy, height: DH, fill: C.fr4Hi, opacity: 0.0 }),
               A.el(d, "rect", { y: dy, height: DH, fill: C.fr4Hi, opacity: 0.0 })],
        tool: A.el(d, "rect", { y: dy + 8, height: DH - 16, rx: 3, fill: "none",
          stroke: m.color, "stroke-width": 2, "stroke-dasharray": "6 4" }),
        edgeL: A.el(d, "line", { y1: dy, y2: dy + DH, stroke: C.text, "stroke-width": 1, "stroke-dasharray": "3 3", opacity: 0.55 }),
        edgeR: A.el(d, "line", { y1: dy, y2: dy + DH, stroke: C.text, "stroke-width": 1, "stroke-dasharray": "3 3", opacity: 0.55 })
      };
      A.text(d, dx + 8, dy + 20, "net A", { size: 13, font: "mono", fill: C.copperFill });
      A.text(d, dx + dw - 8, dy + 20, "net B", { size: 13, font: "mono", fill: C.copperFill, anchor: "end" });
      // 1 mm scale bar
      A.el(g, "rect", { x: dx + 8, y: dy + DH - 14, width: K, height: 4, fill: C.text, opacity: 0.8 });
      A.text(g, dx + 8 + K + 6, dy + DH - 8, "1 mm", { size: 12, font: "mono", fill: C.text });

      p.verdict = A.text(g, x + 14, dy + DH + 28, "", { size: 16, weight: 700, font: "label" });
      p.why = A.text(g, x + 14, dy + DH + 48, "", { size: 13, fill: C.text2 });

      // The rules this method writes into KiCad
      var ry = dy + DH + 70;
      A.el(g, "line", { x1: x + 14, y1: ry - 6, x2: x + PW - 14, y2: ry - 6, stroke: C.rule });
      A.text(g, x + 14, ry + 12, "Clearance", { size: 13, fill: C.text3 });
      A.text(g, x + PW - 14, ry + 12, m.clearance.toFixed(2) + " mm", { size: 13, font: "mono", fill: C.text, anchor: "end" });
      A.text(g, x + 14, ry + 32, "Minimum clearance", { size: 13, fill: C.text3 });
      A.text(g, x + PW - 14, ry + 32, m.floor.toFixed(2) + " mm", { size: 13, font: "mono", fill: m.color, anchor: "end" });
      A.text(g, x + 14, ry + 52, "Track", { size: 13, fill: C.text3 });
      A.text(g, x + PW - 14, ry + 52, m.track.toFixed(2) + " mm", { size: 13, font: "mono", fill: C.text, anchor: "end" });
      // the track, to scale
      var th = Math.min(m.track * K, 12);
      A.el(g, "rect", { x: x + 70, y: ry + 47 - th / 2, width: m.track * K, height: th, rx: 2, fill: C.copper });
      return p;
    });

    // The scale under the panels: the gap, with each method's minimum clearance.
    var sx0 = PX0 + 10, sx1 = W - PX0 - 10;
    function sx(v) { return sx0 + (v - GMIN) / (GMAX - GMIN) * (sx1 - sx0); }
    A.text(svg, PX0, scaleY + 4, "Gap between the two nets · each method's minimum", { size: 14, fill: C.text2 });
    A.text(svg, W - PX0, scaleY + 4, "Top view, to scale", { size: 12, fill: C.text3, anchor: "end" });
    A.el(svg, "line", { x1: sx0, y1: L, x2: sx1, y2: L, stroke: C.ruleStrong, "stroke-width": 2 });
    [0.2, 0.4, 0.6, 0.8, 1.0].forEach(function (v) {
      A.el(svg, "line", { x1: sx(v), y1: L - 4, x2: sx(v), y2: L + 4, stroke: C.text3 });
      A.text(svg, sx(v), L + 36, v.toFixed(1), { size: 12, font: "mono", fill: C.text3, anchor: "middle" });
    });
    METHODS.forEach(function (m) {
      var x = sx(m.floor);
      A.el(svg, "line", { x1: x, y1: L - 12, x2: x, y2: L + 6, stroke: m.color, "stroke-width": 3 });
      A.text(svg, x, L - 18, m.name + " " + m.floor.toFixed(2), { size: 12, weight: 600, font: "label", fill: m.color, anchor: "middle" });
    });
    var pointer = A.el(svg, "polygon", { fill: C.text });

    function draw(g) {
      pointer.setAttribute("points", [sx(g), L + 2, sx(g) - 7, L + 16, sx(g) + 7, L + 16].join(","));
      panels.forEach(function (p) {
        var m = p.m, gp = g * K, cx = p.cx;
        var xl = cx - gp / 2, xr = cx + gp / 2;
        A.set(p.left, { x: p.cx - p.dw, width: xl - (p.cx - p.dw) });
        A.set(p.right, { x: xr, width: p.dw });
        A.set(p.edgeL, { x1: xl, x2: xl }); A.set(p.edgeR, { x1: xr, x2: xr });
        var ok = g >= m.floor - 1e-9;
        if (!ok) {
          // the tool cannot separate them: the copper between stays, the nets join
          A.set(p.bridge, { x: xl, width: gp, opacity: 1 });
          p.cuts.forEach(function (c) { A.set(c, { width: 0, opacity: 0 }); });
          var tw = m.width * K;
          A.set(p.tool, { x: cx - tw / 2, width: tw, stroke: C.danger });
          A.set(p.verdict, { fill: C.danger }); p.verdict.textContent = "Shorted";
          p.why.textContent = m.kind === "laser"
            ? "Under 0.20 mm: finer than the laser"
            : "The " + m.width.toFixed(2) + " mm channel does not fit";
          return;
        }
        A.set(p.tool, { stroke: m.color });
        p.verdict.textContent = "Isolated"; A.set(p.verdict, { fill: C.ok });
        if (m.kind === "mill") {
          var w = Math.min(m.width, g) * K;
          // a cut along each outline; past twice the bit, copper is left between
          A.set(p.cuts[0], { x: xl, width: w, opacity: 1 });
          A.set(p.cuts[1], { x: xr - w, width: w, opacity: 1 });
          A.set(p.bridge, { x: xl, width: gp, opacity: g > 2 * m.width ? 1 : 0 });
          A.set(p.tool, { x: xl, width: Math.min(m.width * K, gp) });
          p.why.textContent = g > 2 * m.width ? "Two cuts; the copper between is on no net"
            : "The channel fits the gap";
        } else {
          var r = Math.min(0.22, g / 2 + 0.001) * K;
          A.set(p.cuts[0], { x: xl, width: Math.min(r, gp), opacity: 1 });
          A.set(p.cuts[1], { x: xr - Math.min(r, gp), width: Math.min(r, gp), opacity: 1 });
          A.set(p.bridge, { x: xl, width: gp, opacity: g > 0.44 ? 1 : 0 });
          A.set(p.tool, { x: xl, width: gp });
          p.why.textContent = g > 0.44 ? "Rings from each edge; the rest is on no net"
            : "The rings clear the whole gap";
        }
      });
    }
    // the bridge sits under the cuts so a cut shows on top of left-over copper
    panels.forEach(function (p) {
      p.bridge.parentNode.insertBefore(p.bridge, p.cuts[0]);
    });

    var row = A.controls(host);
    A.slider(row, "Gap", GMIN, GMAX, 0.01, 0.5, draw, function (v) { return v.toFixed(2) + " mm"; });
  });
})();
