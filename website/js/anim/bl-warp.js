/* Warp the exported cut to this surface (engine/leveling.py, apply_leveling): every
   cutting Z gets the map's height added at that X, Y, and each feed move is split into
   steps of at most 1 mm so the depth ramps along the surface instead of only changing at
   the ends of a long move. The dry run is left alone: it is in the air.
   Top: one trace channel crossing the measured map. Bottom: the same channel in section,
   the tip of the bit riding along it. Heights are drawn x1500; the map is illustrative. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var L = 60;                                         // the channel's length, mm
  function surf(s) { return -0.13 * Math.sin(Math.PI * (s + 12) / 84); }  // mm along the path
  var DEPTH = 0.15, CU = 0.035;

  A.define("bl-warp", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 560 : 470;
    var TX = 30, TY = 50, TW = W - 60, TH = narrow ? 150 : 130;
    var SX = 30, SY = TY + TH + 60, SW = W - 60, SH = narrow ? 240 : 200;
    var svg = A.stage(host, W, H, "A trace channel over the measured map, and the bit's depth along it with the warp off and on");
    A.text(svg, TX, 34, "TOP VIEW · THE MAP UNDER ONE CHANNEL", { size: 15, font: "label", weight: 600, fill: C.text3 });
    // heat strip: blue low, copper high
    var NS = 40;
    for (var k = 0; k < NS; k++) {
      var z = surf((k + 0.5) / NS * L), t = A.clamp((z + 0.13) / 0.13, 0, 1);
      var c = [78 + (213 - 78) * t, 168 + (148 - 168) * t, 255 + (86 - 255) * t].map(Math.round);
      A.el(svg, "rect", { x: TX + k * TW / NS, y: TY, width: TW / NS + 0.5, height: TH, fill: "rgb(" + c.join(",") + ")", opacity: 0.85 });
    }
    A.el(svg, "rect", { x: TX, y: TY, width: TW, height: TH, fill: "none", stroke: C.ruleHi, rx: 3 });
    var cy = TY + TH / 2;
    A.el(svg, "line", { x1: TX + 10, y1: cy, x2: TX + TW - 10, y2: cy, stroke: C.ink, "stroke-width": 10, "stroke-linecap": "round", opacity: 0.55 });
    var segG = A.el(svg, "g", {});
    for (var m = 0; m <= L; m++) A.el(segG, "circle", { cx: TX + 10 + m / L * (TW - 20), cy: cy, r: 2.6, fill: C.text });
    A.text(svg, TX + TW - 8, TY + TH - 10, "a point every ≤ 1 mm", { size: 15, fill: C.ink, anchor: "end", weight: 600 });
    A.text(svg, TX + 8, TY + 22, "high", { size: 15, fill: C.ink, weight: 600 });
    A.text(svg, TX + TW / 2, TY + 22, "low", { size: 15, fill: C.ink, weight: 600, anchor: "middle" });
    var headTop = A.el(svg, "circle", { cx: TX + 10, cy: cy, r: 9, fill: C.steel, stroke: C.ink, "stroke-width": 2 });

    A.text(svg, SX, SY - 16, "SECTION ALONG THE CHANNEL · heights ×1500", { size: 15, font: "label", weight: 600, fill: C.text3 });
    var ZT = 0.05, ZB = -0.33;
    function px(s) { return SX + 10 + s / L * (SW - 20); }
    function py(z) { return SY + (ZT - z) / (ZT - ZB) * SH; }
    A.el(svg, "rect", { x: SX, y: SY, width: SW, height: SH, fill: C.panel, stroke: C.ruleHi, rx: 3 });
    var cu = "", fr = "", k2;
    for (k2 = 0; k2 <= 120; k2++) {
      var s = k2 / 120 * L;
      cu += (k2 ? "L" : "M") + px(s).toFixed(1) + " " + py(surf(s)).toFixed(1);
      fr = "L" + px(s).toFixed(1) + " " + py(surf(s) - CU).toFixed(1) + fr;
    }
    A.el(svg, "path", { d: cu + "L" + px(L) + " " + (SY + SH - 2) + "L" + px(0) + " " + (SY + SH - 2) + "Z", fill: C.fr4, opacity: 0.55 });
    A.el(svg, "path", { d: cu + fr + "Z", fill: C.copper });
    A.el(svg, "line", { x1: SX + 4, y1: py(0), x2: SX + SW - 4, y2: py(0), stroke: C.live, "stroke-dasharray": "5 5", opacity: 0.6 });
    A.text(svg, SX + 12, py(0) - 8, "Z 0 at point 1", { size: 15, fill: C.live });
    var tipPath = A.el(svg, "path", { fill: "none", stroke: C.text, "stroke-width": 2.5 });
    var leftG = A.el(svg, "g", {});
    var tip = A.el(svg, "g", {});
    A.el(tip, "rect", { x: -5, y: -60, width: 10, height: 60, fill: C.steel });
    A.el(tip, "line", { x1: -5, y1: 0, x2: 5, y2: 0, stroke: C.caution, "stroke-width": 3 });
    var zRead = A.text(svg, SX + SW - 12, SY + 26, "", { size: 16, font: "mono", anchor: "end", fill: C.text });

    var warp = true, st;
    var row = A.controls(host);
    A.segmented(row, [[false, "Flat cut"], [true, "Warp the exported cut to this surface"]], true, function (v) { warp = v; redraw(); });
    st = A.status(row);

    function cutZ(s) { return warp ? surfStep(s) - DEPTH : -DEPTH; }
    function surfStep(s) {                          // straight between the 1 mm points, as the file does
      var a = Math.floor(s), b = Math.min(L, a + 1), t = s - a;
      return surf(a) + (surf(b) - surf(a)) * t;
    }
    function redraw() {
      if (!st) return;
      var d = "";
      for (var k = 0; k <= 240; k++) { var s = k / 240 * L; d += (k ? "L" : "M") + px(s).toFixed(1) + " " + py(cutZ(s)).toFixed(1); }
      A.set(tipPath, { d: d, stroke: warp ? C.ok : C.text });
      while (leftG.firstChild) leftG.removeChild(leftG.firstChild);
      var bad = 0, run = null;
      for (var k3 = 0; k3 <= 240; k3++) {
        var s3 = k3 / 240 * L, left = cutZ(s3) > surf(s3) - CU;
        if (left) bad++;
        if (left && run === null) run = s3;
        if ((!left || k3 === 240) && run !== null) {
          A.el(leftG, "rect", { x: px(run), y: SY + 2, width: Math.max(2, px(s3) - px(run)), height: SH - 4, fill: C.danger, opacity: 0.18 });
          run = null;
        }
      }
      st.className = "anim-status " + (bad ? "bad" : "ok");
      st.textContent = warp
        ? "Warped: the bit stays 0.15 mm below the copper it is actually over, the whole way. The file carries a point at least every millimetre."
        : "Flat: the same Z everywhere. Where the sheet sits " + Math.round((DEPTH - CU) * 1000) + " µm or more below point 1, the bit never gets through the copper (red).";
    }
    redraw();
    A.loop(host, function (t) {
      var u = (t % 7) / 6;
      if (u > 1) u = 1;
      var s = u * L;
      A.set(headTop, { cx: TX + 10 + s / L * (TW - 20) });
      tip.setAttribute("transform", "translate(" + px(s) + "," + py(cutZ(s)) + ")");
      zRead.textContent = "Z " + cutZ(s).toFixed(3);
    }, 3.5);
  });
})();
