/* Is the grid fine enough? A section across the board: the real surface, the probe
   lines, and the straight line the map draws between them (bilinear between probe
   lines is straight along each one, engine/leveling.py HeightMap.from_grid).
   The numbers are the app's own rules:
   - suggest_refinement_rows: neighbouring probe lines that differ by more than 80 µm
     want a line between them;
   - recommend_depth: estimated error = worst spread between neighbours / 3 + 30 µm
     of probe noise, and the trace depth = max(0.15, ceil((0.035 + error + 0.02) x 100) / 100).
   The surface itself is illustrative: a 0.13 mm bow with a clamp lifting one side. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var L = 100;                                     // section length, mm
  function surf(x) {                               // mm, 0 = the datum plane
    return -0.13 * Math.sin(Math.PI * x / L) + 0.06 * Math.exp(-Math.pow((x - 82) / 6, 2));
  }
  function lines(n) {                              // probe lines, 2 mm in from each edge
    var out = [];
    for (var i = 0; i < n; i++) out.push(2 + (L - 4) * i / (n - 1));
    return out;
  }

  A.define("bl-density", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 560 : 430;
    var PX = narrow ? 30 : 40, PW = narrow ? 460 : 560, PY = 60, PH = 250;
    var svg = A.stage(host, W, H, "A section across the board: the real surface, the probe lines and the map between them");
    A.text(svg, PX, 34, "SECTION ACROSS THE BOARD", { size: 15, font: "label", fill: C.text3, weight: 600 });
    A.text(svg, PX + PW, 34, "heights ×1500", { size: 15, fill: C.text3, anchor: "end" });
    var ZTOP = 0.08, ZBOT = -0.18;
    function sx(x) { return PX + x / L * PW; }
    function sy(z) { return PY + (ZTOP - z) / (ZTOP - ZBOT) * PH; }
    A.el(svg, "rect", { x: PX, y: PY, width: PW, height: PH, fill: C.panel, stroke: C.ruleHi, rx: 3 });
    A.el(svg, "line", { x1: PX, y1: sy(0), x2: PX + PW, y2: sy(0), stroke: C.live, "stroke-dasharray": "5 5", opacity: 0.6 });
    A.text(svg, PX + 8, sy(0) - 8, "Z 0 at point 1", { size: 15, fill: C.live });
    // the real surface, as copper
    var d = "", k;
    for (k = 0; k <= 200; k++) { var x = k / 200 * L; d += (k ? "L" : "M") + sx(x).toFixed(1) + " " + sy(surf(x)).toFixed(1); }
    A.el(svg, "path", { d: d + "L" + sx(L) + " " + (PY + PH) + "L" + sx(0) + " " + (PY + PH) + "Z", fill: C.copperFill });
    A.el(svg, "path", { d: d, fill: "none", stroke: C.copperHi, "stroke-width": 3 });
    var gap = A.el(svg, "path", { fill: C.danger, opacity: 0.35 });
    var model = A.el(svg, "path", { fill: "none", stroke: C.live, "stroke-width": 2.5, "stroke-dasharray": "7 5" });
    var dotsG = A.el(svg, "g", {});
    var missG = A.el(svg, "g", {});
    // legend
    var ly = PY + PH + 30;
    A.el(svg, "line", { x1: PX, y1: ly, x2: PX + 30, y2: ly, stroke: C.copperHi, "stroke-width": 3 });
    A.text(svg, PX + 38, ly + 5, "the real surface", { size: 15, fill: C.text2 });
    A.el(svg, "line", { x1: PX + 190, y1: ly, x2: PX + 220, y2: ly, stroke: C.live, "stroke-width": 2.5, "stroke-dasharray": "7 5" });
    A.text(svg, PX + 228, ly + 5, "what the map believes", { size: 15, fill: C.text2 });

    // the readout panel
    var RX = narrow ? PX : PX + PW + 24, RY = narrow ? ly + 28 : PY, RW = narrow ? PW : W - RX - 20;
    A.el(svg, "rect", { x: RX, y: RY, width: RW, height: narrow ? 160 : PH + 45, fill: C.panel, stroke: C.ruleHi, rx: 3 });
    A.text(svg, RX + 14, RY + 26, "CHECK THE MESH", { size: 15, font: "label", weight: 600, fill: C.text3 });
    var r1 = A.text(svg, RX + 14, RY + 56, "", { size: 16, fill: C.text });
    var r2 = A.text(svg, RX + 14, RY + 82, "", { size: 16, fill: C.text });
    var r3 = A.text(svg, RX + 14, RY + (narrow ? 112 : 124), "", { size: 16, weight: 600 });
    var r4 = A.text(svg, RX + 14, RY + (narrow ? 138 : 150), "", { size: 15, fill: C.text2 });
    var r5 = A.text(svg, RX + 14, RY + (narrow ? 999 : 200), "", { size: 22, weight: 700, font: "mono", fill: C.copperHi });
    var r6 = A.text(svg, RX + 14, RY + (narrow ? 999 : 224), "", { size: 15, fill: C.text2 });

    var row = A.controls(host), st;
    A.slider(row, "Probe lines across", 2, 9, 1, 3, draw, function (v) { return v + " lines"; });
    st = A.status(row);

    function draw(n) {
      if (!st) return;
      var xs = lines(n), zs = xs.map(surf);
      function mdl(x) {
        if (x <= xs[0]) return zs[0];
        if (x >= xs[n - 1]) return zs[n - 1];
        for (var i = 0; i < n - 1; i++) if (x <= xs[i + 1]) {
          var t = (x - xs[i]) / (xs[i + 1] - xs[i]);
          return zs[i] + (zs[i + 1] - zs[i]) * t;
        }
        return zs[n - 1];
      }
      var md = "", top = "", bot = "", worstMiss = 0, wx = 0;
      for (var k = 0; k <= 200; k++) {
        var x = k / 200 * L, a = surf(x), b = mdl(x);
        md += (k ? "L" : "M") + sx(x).toFixed(1) + " " + sy(b).toFixed(1);
        top += (k ? "L" : "M") + sx(x).toFixed(1) + " " + sy(Math.max(a, b)).toFixed(1);
        bot = "L" + sx(x).toFixed(1) + " " + sy(Math.min(a, b)).toFixed(1) + bot;
        if (Math.abs(a - b) > worstMiss) { worstMiss = Math.abs(a - b); wx = x; }
      }
      A.set(model, { d: md });
      A.set(gap, { d: top + bot + "Z" });
      while (dotsG.firstChild) dotsG.removeChild(dotsG.firstChild);
      while (missG.firstChild) missG.removeChild(missG.firstChild);
      var worst = 0, adds = [];
      xs.forEach(function (x, i) {
        A.el(dotsG, "line", { x1: sx(x), y1: PY + 4, x2: sx(x), y2: PY + PH - 4, stroke: C.ruleStrong, "stroke-dasharray": "3 5" });
        A.el(dotsG, "circle", { cx: sx(x), cy: sy(zs[i]), r: 6, fill: C.ok, stroke: C.ink, "stroke-width": 1.5 });
        if (i) {
          var j = Math.abs(zs[i] - zs[i - 1]);
          worst = Math.max(worst, j);
          if (j > 0.08) adds.push((x + xs[i - 1]) / 2);
        }
      });
      adds.forEach(function (x) {
        A.el(missG, "line", { x1: sx(x), y1: PY + 4, x2: sx(x), y2: PY + PH - 4, stroke: C.caution, "stroke-width": 2, "stroke-dasharray": "8 5" });
        A.text(missG, sx(x), PY + PH - 10, "add a line", { size: 15, fill: C.caution, anchor: "middle", weight: 600 });
      });
      A.el(missG, "circle", { cx: sx(wx), cy: sy((surf(wx) + mdl(wx)) / 2), r: 13, fill: "none", stroke: C.danger, "stroke-width": 2.5 });
      var est = worst / 3 + 0.03;
      var depth = Math.max(0.15, Math.ceil((0.035 + est + 0.02) * 100 - 1e-9) / 100);
      r1.textContent = n + " lines · worst step";
      r2.textContent = "between neighbours: " + Math.round(worst * 1000) + " µm";
      r3.textContent = adds.length ? "Too coarse: add " + adds.length + " line" + (adds.length > 1 ? "s" : "") : worstMiss > 0.08 ? "Passes, but blind to the bow" : "The grid is fine enough";
      r3.setAttribute("fill", adds.length || worstMiss > 0.08 ? C.caution : C.ok);
      r4.textContent = "limit 80 µm · misses up to " + Math.round(worstMiss * 1000) + " µm";
      if (narrow) {
        r4.textContent += " · cut ≥ " + depth.toFixed(2) + " mm";
      } else {
        r5.textContent = "cut ≥ " + depth.toFixed(2) + " mm";
        r6.textContent = "the depth this mesh supports";
      }
      st.className = "anim-status " + (adds.length ? "bad" : worstMiss > 0.08 ? "caution" : "ok");
      st.textContent = adds.length
        ? "Check the mesh… would offer to add a line at X " + adds.map(function (x) { return x.toFixed(1); }).join(", ") +
          " mm and keep every point already measured. Until then, cut at least " + depth.toFixed(2) + " mm deep."
        : worstMiss > 0.08
          ? "Passes, and still wrong: two lines that sit at the same height hide the bow between them, and the check only compares neighbouring lines. That is why the grid starts at 3 × 3."
          : "No two neighbouring lines differ by more than 80 µm. The traces need to go at least " + depth.toFixed(2) + " mm deep.";
    }
    st = row.querySelector(".anim-status");
    draw(3);
  });
})();
