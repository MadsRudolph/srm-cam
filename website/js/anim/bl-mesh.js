/* Check the mesh… (Level the bed › Measured heights). For every point the app fits a
   smooth surface to all the OTHER points (a quadratic once eight or more remain, since a
   bow and a saddle are real board shapes) and flags the point if it disagrees by more
   than 0.10 mm: the flaky touch no smooth board can explain (engine/leveling.py,
   flag_outliers). A whole row read late is ambiguous from geometry alone; that is what
   the drift check is for. Heights relative to point 1, illustrative, a 4 x 4 grid
   numbered row by row from the bottom left as the app numbers it. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var XS = [4, 28, 52, 76], YS = [4, 22, 40, 58];
  function z(x, y) { return -0.13 * Math.sin(Math.PI * x / 80) * (0.7 + 0.3 * Math.sin(Math.PI * y / 62)) + 0.0004 * y; }

  function solve(M, b) {
    var n = b.length, a = M.map(function (r, i) { return r.concat([b[i]]); });
    for (var c = 0; c < n; c++) {
      var p = c;
      for (var r = c + 1; r < n; r++) if (Math.abs(a[r][c]) > Math.abs(a[p][c])) p = r;
      var t = a[c]; a[c] = a[p]; a[p] = t;
      if (Math.abs(a[c][c]) < 1e-12) return null;
      for (var r2 = 0; r2 < n; r2++) if (r2 !== c) {
        var f = a[r2][c] / a[c][c];
        for (var k = c; k <= n; k++) a[r2][k] -= f * a[c][k];
      }
    }
    return a.map(function (r, i) { return r[n] / r[i]; });
  }
  function flagOutliers(pts, tol) {                 // leave-one-out, as the app does it
    var out = [];
    pts.forEach(function (q, k) {
      var rest = pts.filter(function (_, i) { return i !== k; });
      var quad = rest.length >= 8;
      function basis(x, y) { return quad ? [1, x, y, x * x, x * y, y * y] : [1, x, y]; }
      var m = quad ? 6 : 3, AtA = [], Atb = [], i, j;
      for (i = 0; i < m; i++) { AtA.push([0, 0, 0, 0, 0, 0].slice(0, m)); Atb.push(0); }
      rest.forEach(function (p) {
        var b = basis(p[0], p[1]);
        for (i = 0; i < m; i++) { Atb[i] += b[i] * p[2]; for (j = 0; j < m; j++) AtA[i][j] += b[i] * b[j]; }
      });
      var c = solve(AtA, Atb);
      if (!c) return;
      var b = basis(q[0], q[1]), pred = 0;
      for (i = 0; i < m; i++) pred += c[i] * b[i];
      var r = Math.abs(q[2] - pred);
      if (r > tol) out.push([k, r]);
    });
    return out.sort(function (a, b) { return b[1] - a[1]; });
  }

  A.define("bl-mesh", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 610 : 390;
    var GX = 30, GY = 56, CW = narrow ? 115 : 104, CH = narrow ? 72 : 68;
    var svg = A.stage(host, W, H, "A 4 by 4 grid of measured heights, and the mesh check's verdict");
    A.text(svg, GX, 34, "MEASURED HEIGHTS · mm from point 1 · tap a point to spoil it", { size: 15, font: "label", weight: 600, fill: C.text3 });
    var cells = [], extra = [];
    for (var i = 0; i < 16; i++) extra.push(0);
    for (var k = 0; k < 16; k++) (function (k) {
      var c = k % 4, r = Math.floor(k / 4);
      var x = GX + c * CW, y = GY + (3 - r) * CH;
      var g = A.el(svg, "g", { style: "cursor:pointer" });
      var rect = A.el(g, "rect", { x: x + 2, y: y + 2, width: CW - 4, height: CH - 4, rx: 3, stroke: C.ruleHi, "stroke-width": 1.5 });
      A.text(g, x + 10, y + 22, String(k + 1), { size: 15, fill: C.ink, weight: 600 });
      var v = A.text(g, x + CW - 10, y + CH - 14, "", { size: 17, font: "mono", anchor: "end", fill: C.ink, weight: 600 });
      g.addEventListener("click", function () { extra[k] = extra[k] ? 0 : (k % 3 ? 0.15 : -0.14); fault.set("custom"); });
      cells.push({ rect: rect, v: v });
    })(k);
    var RX = narrow ? GX : GX + 4 * CW + 24, RY = narrow ? GY + 4 * CH + 24 : GY, RW = narrow ? 4 * CW : W - RX - 20;
    A.el(svg, "rect", { x: RX, y: RY, width: RW, height: narrow ? 220 : 4 * CH, fill: C.panel, stroke: C.ruleHi, rx: 3 });
    A.text(svg, RX + 14, RY + 26, "HOW GOOD IS THIS MEASUREMENT?", { size: 15, font: "label", weight: 600, fill: C.text3 });
    var verdict = A.el(svg, "g", {});

    function pts() {
      var out = [], z0 = z(XS[0], YS[0]);
      YS.forEach(function (y, r) { XS.forEach(function (x, c) { var k = r * 4 + c; out.push([x, y, z(x, y) - z0 + extra[k]]); }); });
      return out;
    }
    function colour(v) {
      var t = A.clamp((v + 0.12) / 0.16, 0, 1);
      return "rgb(" + [78 + (213 - 78) * t, 168 + (148 - 168) * t, 255 + (86 - 255) * t].map(Math.round).join(",") + ")";
    }
    function paint(flags) {
      var p = pts(), bad = {};
      (flags || []).forEach(function (f) { bad[f[0]] = f[1]; });
      p.forEach(function (q, k) {
        cells[k].rect.setAttribute("fill", colour(q[2]));
        cells[k].rect.setAttribute("stroke", bad[k] !== undefined ? C.caution : C.ruleHi);
        cells[k].rect.setAttribute("stroke-width", bad[k] !== undefined ? 5 : 1.5);
        cells[k].v.textContent = (q[2] >= 0 ? "+" : "") + q[2].toFixed(3);
      });
    }
    function say(lines, col) {
      while (verdict.firstChild) verdict.removeChild(verdict.firstChild);
      lines.forEach(function (s, i) {
        A.text(verdict, RX + 14, RY + 58 + i * 26, s, { size: 16, fill: i ? C.text2 : col, weight: i ? 500 : 600 });
      });
    }

    var row = A.controls(host), st;
    var fault = A.segmented(row, [["none", "Clean"], ["flaky", "A flaky touch"], ["row", "A row read late"], ["custom", "Your own"]], "none", function (v) {
      if (v === "none") extra = extra.map(function () { return 0; });
      if (v === "flaky") { extra = extra.map(function () { return 0; }); extra[6] = 0.15; }
      if (v === "row") { extra = extra.map(function (_, k) { return k >= 8 && k < 12 ? -0.06 : 0; }); }
      paint();
      say(["Press Check the mesh…"], C.text);
      if (st) { st.className = "anim-status"; st.textContent = "The table as probed. Tap a point to give it a bad touch, or pick a case."; }
    });
    A.button(row, "Check the mesh…", check, "primary");
    st = A.status(row);
    fault.set("flaky");

    function check() {
      var f = flagOutliers(pts(), 0.10);
      paint(f);
      if (f.length) {
        var lines = [f.length + " point" + (f.length > 1 ? "s sit" : " sits") + " where no smooth"];
        lines.push("board surface can put " + (f.length > 1 ? "them" : "it") + ": re-probe:");
        f.slice(0, narrow ? 3 : 4).forEach(function (q) { lines.push("point " + (q[0] + 1) + " · " + Math.round(q[1] * 1000) + " µm off the fit"); });
        say(lines, C.caution);
        st.className = "anim-status caution";
        st.textContent = "Usually a flaky touch: clean the copper there, check the clip, and probe again. The rest of the map is fine.";
      } else if (fault && extra.some(function (v, k) { return v && k >= 8 && k < 12; })) {
        say(["Nothing flagged.", "A whole row off by the same", "amount still looks like a", "smooth board."], C.ok);
        st.className = "anim-status caution";
        st.textContent = "Row 3 reads 60 µm low because it was probed late, and no fit can tell. That is what the drift check is for (Full tier).";
      } else {
        say(["Every point agrees with a", "smooth surface through", "the others."], C.ok);
        st.className = "anim-status ok";
        st.textContent = "No point sits more than 0.10 mm off a smooth surface through the others.";
      }
    }
  });
})();
