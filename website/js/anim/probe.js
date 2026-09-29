/* Level the bed: a 3 x 3 grid over the board (Grid 3 x 3 › Build the grid over the
   board). You jog to point 1 and set the final Z zero there: every height is measured
   from it (engine/leveling.py: point 1 is the datum). Probe over the link then drives
   to each point in turn, row-major, bottom row first, left to right, the order the
   points are numbered; it touches down twice at each (a coarse touch, a lift and a
   fine re-descend, gui2/leveling.py) and the table fills. A finished probe switches
   on "Warp the exported cut to this surface". The heights are illustrative, with the
   0.13 mm spread measured in the recording. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  // heights relative to point 1, mm; index = point number - 1 (bottom row first)
  var Z = [0.000, -0.052, -0.011, -0.071, -0.128, -0.064, -0.018, -0.083, 0.002];
  var M = 44;                                    // grid inset
  var T_JOG = 1.6, T_MOVE = 0.55, T_TOUCH = 0.95, T_END = 1.2;

  function colour(z) {                            // low = blue, high = copper
    var k = A.clamp((z + 0.13) / 0.135, 0, 1);
    var a = [78, 168, 255], b = [213, 148, 86];
    return "rgb(" + a.map(function (v, j) { return Math.round(v + (b[j] - v) * k); }).join(",") + ")";
  }
  function bilerp(u, v) {                         // u, v in 0..1 over the grid
    var fx = u * 2, fy = v * 2, c = Math.min(Math.floor(fx), 1), r = Math.min(Math.floor(fy), 1);
    var tx = fx - c, ty = fy - r;
    var z00 = Z[r * 3 + c], z10 = Z[r * 3 + c + 1], z01 = Z[(r + 1) * 3 + c], z11 = Z[(r + 1) * 3 + c + 1];
    return (z00 * (1 - tx) + z10 * tx) * (1 - ty) + (z01 * (1 - tx) + z11 * tx) * ty;
  }

  // the script: [start, end, kind, point]
  var PLAN = [], t = 0;
  PLAN.push([t, t += T_JOG, "jog", 0]);
  PLAN.push([t, t += 0.8, "zero", 0]);
  for (var i = 0; i < 9; i++) {
    if (i) PLAN.push([t, t += T_MOVE, "move", i]);
    PLAN.push([t, t += T_TOUCH, "touch", i]);
  }
  PLAN.push([t, t += T_END, "map", 8]);
  var TOTAL = t;

  A.define("probe", function (host) {
    // A phone gets its own layout: the table, the machine and the warp switch under the board
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 896 : 500;
    var BX = narrow ? 24 : 40, BY = narrow ? 96 : 70, BW = narrow ? 472 : 470, BH = narrow ? 330 : 350;
    var TX = narrow ? 24 : 560, TY = narrow ? BY + BH + 104 : 70, CW = narrow ? 157 : 98, CH = narrow ? 58 : 62;
    var GX = narrow ? 24 : 560, GY = narrow ? TY + 3 * CH + 20 : 290, GW = narrow ? 472 : 290;
    var CHY = narrow ? GY + 112 : 400;
    function pt(i) {                               // screen position of point i (0-based)
      var c = i % 3, r = Math.floor(i / 3);
      return [BX + M + c * (BW - 2 * M) / 2, BY + BH - M - r * (BH - 2 * M) / 2];
    }
    var svg = A.stage(host, W, H, "Probing a 3 by 3 grid over the board, point 1 first, and the measured surface");
    if (narrow) {
      A.text(svg, 24, 34, "Level the bed › Grid 3 × 3 ›", { size: 16, font: "mono", fill: C.copperHi });
      A.text(svg, 24, 58, "Build the grid over the board", { size: 16, font: "mono", fill: C.copperHi });
    } else {
      A.text(svg, 24, 34, "Level the bed › Grid 3 × 3 › Build the grid over the board", { size: 16, font: "mono", fill: C.copperHi });
    }

    A.el(svg, "rect", { x: BX, y: BY, width: BW, height: BH, fill: C.copper, stroke: C.copperHi, "stroke-width": 1.5, rx: 3 });
    // surface overlay (fades in at the end)
    var surf = A.el(svg, "g", { opacity: 0 });
    var NX = 24, NY = 18;
    for (var yy = 0; yy < NY; yy++) for (var xx = 0; xx < NX; xx++) {
      var cx0 = BX + (xx + 0.5) * BW / NX, cy0 = BY + (yy + 0.5) * BH / NY;
      var gu = A.clamp((cx0 - BX - M) / (BW - 2 * M), 0, 1);      // 0 at the left column
      var gv = A.clamp((BY + BH - M - cy0) / (BH - 2 * M), 0, 1); // 0 at the bottom row (points 1-3)
      A.el(surf, "rect", { x: BX + xx * BW / NX, y: BY + yy * BH / NY, width: BW / NX + 0.6, height: BH / NY + 0.6,
        fill: colour(bilerp(gu, gv)) });
    }
    // grid lines and points
    var gGrid = A.el(svg, "g", {});
    [[0, 1, 2], [3, 4, 5], [6, 7, 8]].forEach(function (r) {
      A.el(gGrid, "line", { x1: pt(r[0])[0], y1: pt(r[0])[1], x2: pt(r[2])[0], y2: pt(r[2])[1], stroke: C.copperDim, "stroke-dasharray": "4 5" });
    });
    [[0, 3, 6], [1, 4, 7], [2, 5, 8]].forEach(function (c) {
      A.el(gGrid, "line", { x1: pt(c[0])[0], y1: pt(c[0])[1], x2: pt(c[2])[0], y2: pt(c[2])[1], stroke: C.copperDim, "stroke-dasharray": "4 5" });
    });
    var dots = [];
    for (var k = 0; k < 9; k++) {
      var p = pt(k);
      var d = A.el(svg, "circle", { cx: p[0], cy: p[1], r: 9, fill: C.sunk, stroke: C.text2, "stroke-width": 2 });
      A.text(svg, p[0] + 14, p[1] - 12, String(k + 1), { size: 16, fill: C.ink, weight: 700 });
      dots.push(d);
    }
    // point 1 callout
    var p1 = pt(0);
    A.el(svg, "circle", { cx: p1[0], cy: p1[1], r: 20, fill: "none", stroke: C.caution, "stroke-width": 3 });
    var call = A.el(svg, "g", {});
    var cx1 = narrow ? BX : BX + 70;
    A.el(call, "rect", { x: cx1, y: BY + BH + 12, width: narrow ? BW : 440, height: 56, fill: C.cautionFill, stroke: C.caution, rx: 3 });
    A.text(call, cx1 + 14, BY + BH + 35, "1 · the datum: jog here and set your final Z zero.", { size: 15, fill: C.caution, weight: 600 });
    A.text(call, cx1 + 14, BY + BH + 57, "Every height in the map is measured from it.", { size: 15, fill: C.text2 });

    // the bit (top view) and its Z gauge
    var head = A.el(svg, "g", {});
    A.el(head, "circle", { r: 16, fill: C.steel, "fill-opacity": 0.35, stroke: C.steel, "stroke-width": 2.5 });
    A.el(head, "path", { d: "M-8,0H8M0,-8V8", stroke: C.ink, "stroke-width": 2.5 });
    var ring = A.el(svg, "circle", { r: 0, fill: "none", stroke: C.danger, "stroke-width": 3, opacity: 0 });

    // table: the grid as a table, top row = points 7-9
    A.text(svg, TX, TY - 12, "HEIGHT vs POINT 1 (mm)", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var cells = [];
    for (var r = 0; r < 3; r++) for (var c = 0; c < 3; c++) {
      var idx = (2 - r) * 3 + c, x = TX + c * CW, y = TY + r * CH;
      A.el(svg, "rect", { x: x, y: y, width: CW - 4, height: CH - 4, fill: C.panel, stroke: C.ruleStrong, rx: 3 });
      A.text(svg, x + 8, y + 20, String(idx + 1), { size: 15, fill: C.text3 });
      cells[idx] = A.text(svg, x + CW - 12, y + 44, "—", { size: 17, font: "mono", anchor: "end", fill: C.text4 });
    }
    // Z gauge
    A.el(svg, "rect", { x: GX, y: GY, width: GW, height: 96, fill: C.panel, stroke: C.ruleStrong, rx: 3 });
    A.text(svg, GX + 12, GY + 24, "AT THE MACHINE", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    A.el(svg, "rect", { x: GX + GW - 68, y: GY + 76, width: 58, height: 8, fill: C.copper });
    var bit = A.el(svg, "g", {});
    A.el(bit, "rect", { x: -14, y: -44, width: 28, height: 22, fill: C.steelDim });
    A.el(bit, "rect", { x: -4, y: -22, width: 8, height: 22, fill: C.steel });
    var zTxt = A.text(svg, GX + 12, GY + 56, "", { size: 16, fill: C.text });
    var zTxt2 = A.text(svg, GX + 12, GY + 80, "", { size: 15, fill: C.text2 });
    // warp chip
    var chip = A.el(svg, "g", {});
    var chipR = A.el(chip, "rect", { x: GX, y: CHY, width: GW, height: 40, rx: 3, fill: C.panel, stroke: C.ruleStrong });
    var chipT = A.text(chip, GX + 14, CHY + 26, "Warp the exported cut to this surface: off", { size: 15, fill: C.text3 });
    var legend = A.text(svg, BX, BY - 12, "", { size: 15, fill: C.text2 });

    var row = A.controls(host);
    var clock = 0, running = false, stopped = false;
    var st;
    A.button(row, "Probe over the link", function () { clock = 0; running = true; stopped = false; }, "primary");
    A.button(row, "STOP", stopIt, "", "STOP, or the Escape key, stops the probing at any time");
    A.button(row, "Reset", function () { clock = 0; running = false; stopped = false; render(0); });
    st = A.status(row);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && running) stopIt();
    });
    function stopIt() {
      if (!running) return;
      running = false; stopped = true;
      render(clock);
    }

    function render(tt) {
      var cur = PLAN[0], done = -1;
      for (var n = 0; n < PLAN.length; n++) {
        if (tt >= PLAN[n][0]) cur = PLAN[n];
        if (PLAN[n][2] === "touch" && tt >= PLAN[n][1]) done = Math.max(done, PLAN[n][3]);
      }
      var f = A.clamp((tt - cur[0]) / (cur[1] - cur[0]), 0, 1);
      // head position
      var hx, hy;
      if (cur[2] === "jog") {
        var from = [BX + BW * 0.62, BY + BH * 0.3], to = pt(0), e = A.ease(f);
        hx = A.lerp(from[0], to[0], e); hy = A.lerp(from[1], to[1], e);
      } else if (cur[2] === "move") {
        var a = pt(cur[3] - 1), b = pt(cur[3]), e2 = A.ease(f);
        hx = A.lerp(a[0], b[0], e2); hy = A.lerp(a[1], b[1], e2);
      } else {
        var q = pt(cur[2] === "map" ? 8 : cur[3]); hx = q[0]; hy = q[1];
      }
      A.set(head, { transform: "translate(" + hx.toFixed(1) + "," + hy.toFixed(1) + ")" });
      // Z: two touches during "touch"
      var z = 0, touching = false;
      if (cur[2] === "touch") {
        var s = f * 2, ph = s % 1;           // two cycles
        z = ph < 0.45 ? A.ease(ph / 0.45) : 1 - A.ease((ph - 0.45) / 0.55);
        touching = ph > 0.38 && ph < 0.55;
      } else if (cur[2] === "zero") { z = f < 0.6 ? A.ease(f / 0.6) : 1; touching = f > 0.5; }
      A.set(bit, { transform: "translate(" + (GX + GW - 39) + "," + (GY + 76 - 30 * (1 - z)).toFixed(1) + ")" });
      A.set(ring, { cx: hx, cy: hy, r: touching ? 24 : 0, opacity: touching ? 1 : 0 });
      // table and dots
      for (var k2 = 0; k2 < 9; k2++) {
        var got = k2 <= done;
        cells[k2].textContent = got ? (Z[k2] >= 0 ? "+" : "−") + Math.abs(Z[k2]).toFixed(3) : "—";
        A.set(cells[k2], { fill: got ? C.text : C.text4 });
        A.set(dots[k2], { fill: got ? C.ok : C.sunk, stroke: got ? C.ok : C.text2 });
      }
      var mapOn = cur[2] === "map" && !stopped;
      A.set(surf, { opacity: mapOn ? (0.9 * A.ease(f)).toFixed(2) : 0 });
      A.set(chipR, { stroke: mapOn && f > 0.5 ? C.ok : C.ruleStrong, fill: mapOn && f > 0.5 ? C.okFill : C.panel });
      chipT.textContent = "Warp the exported cut to this surface: " + (mapOn && f > 0.5 ? "on" : "off");
      A.set(chipT, { fill: mapOn && f > 0.5 ? C.ok : C.text3 });
      legend.textContent = mapOn ? "Measured: 0.13 mm, lowest (blue) to highest (copper)" : "";
      // words
      var zt = "", zt2 = "";
      if (cur[2] === "jog") { zt = "You jog to point 1."; zt2 = "A couple of mm up."; }
      else if (cur[2] === "zero") { zt = "Final Z zero here."; zt2 = "G54 › Set Origin Point Z"; }
      else if (cur[2] === "map") { zt = "Done: 9 of 9 points."; zt2 = "Each point touched twice."; }
      else { zt = "Point " + (cur[3] + 1) + (cur[2] === "touch" ? (f < 0.5 ? ": coarse touch" : ": fine touch") : ": moving"); zt2 = "Touch, lift, next."; }
      if (stopped) { zt = "Stopped at point " + (Math.max(done, -1) + 2 > 9 ? 9 : Math.max(done, -1) + 2) + "."; zt2 = "Raise the bit."; }
      zTxt.textContent = zt; zTxt2.textContent = zt2;
      if (st) {
        st.className = "anim-status" + (mapOn ? " ok" : "");
        st.style.color = stopped ? C.caution : "";
        st.textContent = stopped
          ? "Stopped. The " + (done + 1) + " points measured so far are kept; the missing ones can be probed on their own."
          : mapOn ? "Probed: this sheet varies by 0.13 mm, and a finished probe switches the warp on, so every cut follows the map."
            : tt < T_JOG ? "Jog the bit over the first marked point, a couple of millimetres above the copper."
              : "SRM-CAM drives the head to each point and touches down twice; the table fills as it goes.";
      }
    }

    render(0);
    A.loop(host, function (tt, dt) {
      if (running) {
        clock = Math.min(clock + dt, TOTAL);
        if (clock >= TOTAL) running = false;
      }
      render(clock);
    }, TOTAL);
    // start by itself the first time it is seen
    running = !A.reduced;
    if (A.reduced) { clock = TOTAL; render(TOTAL); }
  });
})();
