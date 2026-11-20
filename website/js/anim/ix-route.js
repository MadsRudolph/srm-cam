/* One sheet's way through the usual route (make-a-board.html): on the mill the
   holes are drilled and the outline cut on tabs, so the board stays in its
   sheet; the whole sheet goes to the laser; Calibrate fires faint marks in the
   waste beside the board, finds the drilled holes in the photo and puts the job
   on them; the laser etches the isolation trenches; at the bench the tabs are
   broken. A schematic board, drawn in millimetres on a 100 x 70 mm sheet. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  // The sheet and the board on it, in mm (y down).
  var SW = 100, SH = 70;
  var BX = 20, BY = 15, BW = 60, BH = 40;
  var TABS = [[35, BY], [65, BY], [35, BY + BH], [65, BY + BH]];   // on the long sides
  var PADS = [[28, 22], [28, 48], [72, 22], [72, 48],
    [42, 24], [48, 24], [54, 24], [60, 24], [42, 46], [48, 46], [54, 46], [60, 46]];
  var TRACES = [
    [[42, 24], [42, 34], [60, 34], [60, 46]],
    [[48, 24], [48, 30], [72, 30], [72, 22]],
    [[54, 46], [54, 40], [28, 40], [28, 48]],
    [[60, 24], [66, 24], [66, 48], [72, 48]],
    [[48, 46], [48, 52], [28, 52], [28, 48]]
  ];
  var MARKS = [[9, 8], [91, 8], [91, 62]];                          // in the waste

  var STAGES = [
    ["mill", "1 · Mill", "Drill the holes, cut the outline on tabs. The board stays in its sheet."],
    ["move", "2 · To the laser", "The whole sheet goes to the laser, board still on its tabs."],
    ["cal", "3 · Calibrate", "Marks in the waste correct the camera; the drilled holes place the job."],
    ["etch", "4 · Etch", "The laser etches a trench round every net."],
    ["done", "5 · Break out", "At the bench: break the tabs. The board is done."]
  ];
  var D = 3.4;                                                        // seconds a stage

  A.define("ix-route", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 860 : 480;
    var svg = A.stage(host, W, H, "One sheet through the usual route: drilled and cut out on tabs on the mill, moved to the laser, calibrated on its holes and the waste, etched, then broken out of the sheet");

    // The two beds.
    var bedW = narrow ? 488 : 410, bedH = narrow ? 330 : 330;
    var beds = narrow ? [[16, 84], [16, 470]] : [[16, 84], [454, 84]];
    var k = narrow ? 3.8 : 3.6;
    var bedEls = [], tagEls = [];
    [["MILL · SRM-20", C.copperHi, C.copperDim], ["LASER · xTool F1 Ultra", C.live, "#1d466e"]].forEach(function (b, i) {
      var x = beds[i][0], y = beds[i][1];
      tagEls.push(A.text(svg, x + 2, y - 14, b[0], { size: 15, weight: 600, font: "label", fill: b[1], spacing: "0.12em" }));
      bedEls.push(A.el(svg, "rect", { x: x, y: y, width: bedW, height: bedH, rx: 4, fill: C.panel, stroke: C.ruleHi, "stroke-width": 1.5 }));
      if (i === 1) {                                                  // the laser's field grid
        for (var gx = 1; gx < 8; gx++) A.el(svg, "line", { x1: x + gx * bedW / 8, y1: y + 6, x2: x + gx * bedW / 8, y2: y + bedH - 6, stroke: C.rule });
        for (var gy = 1; gy < 6; gy++) A.el(svg, "line", { x1: x + 6, y1: y + gy * bedH / 6, x2: x + bedW - 6, y2: y + gy * bedH / 6, stroke: C.rule });
      }
    });
    // Where the sheet sits on each bed (its top-left corner).
    function home(i) {
      return [beds[i][0] + (bedW - SW * k) / 2, beds[i][1] + (bedH - SH * k) / 2 + 6];
    }
    // The bracket on the mill: an L at the sheet's back-right corner.
    var h0 = home(0);
    A.el(svg, "path", {
      d: "M" + (h0[0] + SW * k - 70) + " " + (h0[1] - 9) + " H" + (h0[0] + SW * k + 9) + " V" + (h0[1] + 70),
      fill: "none", stroke: C.fr4Hi, "stroke-width": 9, "stroke-linejoin": "round", opacity: 0.85
    });

    // The sheet, drawn in mm inside a group that moves between the beds.
    var sheet = A.el(svg, "g", {});
    function X(x) { return x * k; }
    function P(pts) { return pts.map(function (p, j) { return (j ? "L" : "M") + X(p[0]) + " " + X(p[1]); }).join(" "); }
    var waste = A.el(sheet, "g", {});
    A.el(waste, "rect", { x: 0, y: 0, width: X(SW), height: X(SH), rx: 2, fill: C.copper, stroke: C.copperHi, "stroke-width": 1 });
    // where the board was, once it is out
    var gap = A.el(sheet, "rect", { x: X(BX), y: X(BY), width: X(BW), height: X(BH), fill: C.panel, opacity: 0 });

    // The cut-out channel round the board, with the tabs left standing.
    var perim = 2 * (BW + BH) * k;
    var channel = A.el(sheet, "rect", {
      x: X(BX), y: X(BY), width: X(BW), height: X(BH), fill: "none", stroke: C.ink, "stroke-width": X(1.6),
      "stroke-dasharray": perim + " " + perim
    });
    var tabs = A.el(sheet, "g", {});
    TABS.forEach(function (t) {
      A.el(tabs, "rect", { x: X(t[0] - 2), y: X(t[1] - 1.1), width: X(4), height: X(2.2), fill: C.copper });
    });

    // The board itself: what lifts out at the end.
    var board = A.el(sheet, "g", {});
    var shadow = A.el(board, "rect", { x: X(BX) + 6, y: X(BY) + 8, width: X(BW), height: X(BH), rx: 2, fill: C.ink, opacity: 0 });
    var body = A.el(board, "rect", { x: X(BX), y: X(BY), width: X(BW), height: X(BH), rx: 1, fill: C.copper, opacity: 0 });
    // trenches under the copper they isolate, revealed by a dash as the laser goes
    var trenchG = A.el(board, "g", { stroke: C.ink, fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round" });
    var trenches = TRACES.map(function (t) {
      var len = 0;
      for (var j = 1; j < t.length; j++) len += Math.abs(t[j][0] - t[j - 1][0]) + Math.abs(t[j][1] - t[j - 1][1]);
      len *= k;
      var p = A.el(trenchG, "path", { d: P(t), "stroke-width": X(2.4), "stroke-dasharray": len + " " + len, "stroke-dashoffset": len });
      return { el: p, len: len };
    });
    var ringG = A.el(board, "g", {});
    var rings = PADS.map(function (p) {
      return A.el(ringG, "circle", { cx: X(p[0]), cy: X(p[1]), r: X(2.6), fill: C.ink, opacity: 0 });
    });
    var copperG = A.el(board, "g", { stroke: C.copper, fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round" });
    TRACES.forEach(function (t) { A.el(copperG, "path", { d: P(t), "stroke-width": X(1) }); });
    PADS.forEach(function (p) { A.el(board, "circle", { cx: X(p[0]), cy: X(p[1]), r: X(1.7), fill: C.copper }); });
    var holes = PADS.map(function (p) {
      return A.el(board, "circle", { cx: X(p[0]), cy: X(p[1]), r: X(0.8), fill: C.ink, opacity: 0 });
    });
    // the laser's cutting point while it etches
    var spot = A.el(board, "circle", { r: 5, fill: C.danger, opacity: 0 });

    // Calibrate: marks in the waste, rings round the holes found, the job snapping on.
    var marks = MARKS.map(function (m) {
      var g = A.el(sheet, "g", { stroke: C.live, "stroke-width": 1.6, opacity: 0 });
      A.el(g, "line", { x1: X(m[0]) - 7, y1: X(m[1]), x2: X(m[0]) + 7, y2: X(m[1]) });
      A.el(g, "line", { x1: X(m[0]), y1: X(m[1]) - 7, x2: X(m[0]), y2: X(m[1]) + 7 });
      return g;
    });
    var found = PADS.map(function (p) {
      return A.el(sheet, "circle", { cx: X(p[0]), cy: X(p[1]), r: X(2.4), fill: "none", stroke: C.live, "stroke-width": 1.6, opacity: 0 });
    });
    var job = A.el(sheet, "g", { opacity: 0 });
    A.el(job, "rect", { x: X(BX), y: X(BY), width: X(BW), height: X(BH), fill: "none", stroke: C.live, "stroke-width": 1.5, "stroke-dasharray": "6 4" });
    PADS.forEach(function (p) { A.el(job, "circle", { cx: X(p[0]), cy: X(p[1]), r: X(1), fill: "none", stroke: C.live, "stroke-width": 1.2 }); });

    // Words.
    var lineY = narrow ? H - 46 : H - 24;
    var head = A.text(svg, 16, 28, "", { size: narrow ? 20 : 18, weight: 700 });
    var line = A.text(svg, 16, lineY, "", { size: narrow ? 18 : 16, fill: C.text2 });
    var line2 = A.text(svg, 16, lineY + 24, "", { size: 18, fill: C.text2 });
    function say(msg) {
      if (!narrow) { line.textContent = msg; return; }
      // two lines on a phone: break at the first stop past the start
      var m = /^(.{18,}?[.;,:]) (.*)$/.exec(msg);
      line.textContent = m ? m[1] : msg;
      line2.textContent = m ? m[2] : "";
    }
    var note = A.text(svg, W - 16, 26, "schematic", { size: 13, anchor: "end", fill: C.text4, font: "label", spacing: "0.1em" });
    note.setAttribute("font-style", "normal");

    var sheetCx = SW * k / 2, sheetCy = SH * k / 2;
    function place(at, turn) {
      sheet.setAttribute("transform", "translate(" + at[0] + "," + at[1] + ") rotate(" + (turn || 0) + "," + sheetCx + "," + sheetCy + ")");
    }

    var current = -1, seg;
    function draw(t) {
      var s = A.clamp(Math.floor(t / D), 0, STAGES.length - 1);
      var p = A.clamp((t - s * D) / (D * 0.82), 0, 1);       // the stage's progress, then a rest
      var done = function (i) { return s > i ? 1 : s === i ? p : 0; };

      // 1 · mill: holes one by one, then the outline
      var dr = done(0);
      holes.forEach(function (h, i) { A.set(h, { opacity: dr * 1.9 > (i + 1) / PADS.length ? 1 : 0 }); });
      var cut = A.clamp((dr - 0.5) / 0.5, 0, 1);
      A.set(channel, { "stroke-dashoffset": perim * (1 - cut) });

      // 2 · the sheet moves to the laser
      var mv = A.ease(done(1));
      var a = home(0), b = home(1);
      var turn = s >= 1 ? A.lerp(0, -4, mv) : 0;            // put down a little crooked
      place([A.lerp(a[0], b[0], mv), A.lerp(a[1], b[1], mv)], turn);
      bedEls[0].setAttribute("stroke", s === 0 ? C.copperDim : C.ruleHi);
      bedEls[1].setAttribute("stroke", s >= 2 && s <= 3 ? "#1d466e" : C.ruleHi);

      // 3 · calibrate
      var cal = done(2);
      marks.forEach(function (m, i) { A.set(m, { opacity: s === 2 ? (cal > 0.08 + i * 0.08 ? 0.9 : 0) : s > 2 ? 0.35 : 0 }); });
      var seen = A.clamp((cal - 0.35) / 0.25, 0, 1);
      found.forEach(function (f) { A.set(f, { opacity: s === 2 ? seen : 0 }); });
      var snap = A.ease(A.clamp((cal - 0.62) / 0.38, 0, 1));
      if (s >= 2 && s < 4) {
        // the job starts where the drawing was, then lands on the holes
        var dx = A.lerp(X(7), 0, snap), dy = A.lerp(X(-5), 0, snap), rot = A.lerp(4, 0, snap);
        job.setAttribute("transform", "translate(" + dx + "," + dy + ") rotate(" + rot + "," + sheetCx + "," + sheetCy + ")");
        A.set(job, { opacity: s === 2 ? Math.min(1, cal * 5) : 0.6 });
      } else {
        A.set(job, { opacity: 0 });
      }

      // 4 · etch
      var et = done(3);
      var n = trenches.length;
      trenches.forEach(function (tr, i) {
        var f = A.clamp(et * n - i, 0, 1);
        A.set(tr.el, { "stroke-dashoffset": tr.len * (1 - f) });
      });
      rings.forEach(function (r) { A.set(r, { opacity: A.clamp((et - 0.85) / 0.15, 0, 1) }); });
      if (s === 3 && et < 1) {
        var i0 = Math.min(n - 1, Math.floor(et * n)), tr0 = trenches[i0];
        var pt = tr0.el.getPointAtLength(tr0.len * A.clamp(et * n - i0, 0, 1));
        A.set(spot, { cx: pt.x, cy: pt.y, opacity: 0.9 });
      } else {
        A.set(spot, { opacity: 0 });
      }

      // 5 · break out
      var br = A.ease(done(4));
      A.set(tabs, { opacity: 1 - A.clamp(br * 3, 0, 1) });
      var lift = A.clamp((br - 0.3) / 0.7, 0, 1);
      board.setAttribute("transform", "translate(" + X(14) * lift + "," + X(-10) * lift + ")");
      A.set(waste, { opacity: 1 - 0.55 * lift });
      A.set(gap, { opacity: lift });
      A.set(shadow, { opacity: 0.5 * lift });
      A.set(body, { opacity: lift > 0 ? 1 : 0, stroke: C.copperHi, "stroke-width": lift > 0 ? 1 : 0 });
      A.set(channel, { opacity: 1 - lift });

      // words
      var on = s === 0 ? C.copperHi : s === 1 || s === 4 ? C.text : C.live;
      head.textContent = STAGES[s][1].replace(/^\d · /, "");
      head.setAttribute("fill", on);
      say(STAGES[s][2]);
      if (s !== current) {
        current = s;
        if (seg) { quiet = true; seg.set(STAGES[s][0]); quiet = false; }
      }
    }

    // A clock that the stage buttons can move.
    var t0 = 0, now = 0, END = STAGES.length * D;
    // data-at="seconds" draws one moment and holds it (for stills of the figure)
    var at = parseFloat(host.getAttribute("data-at"));
    var play = isNaN(at) ? A.loop(host, function (t) { now = t; draw(Math.min(t - t0, END - 0.001)); }, END - 0.001)
      : { restart: function () {}, stop: function () {}, running: function () { return false; } };
    function jump(i) {
      if (A.reduced) { draw((i + 1) * D - 0.001); return; }
      t0 = now - i * D;
      play.restart();
      t0 = -i * D;
    }

    var row = A.controls(host);
    var quiet = false;
    seg = A.segmented(row, STAGES.map(function (x) { return [x[0], narrow ? x[1].split(" · ")[0] : x[1]]; }), "mill", function (v) {
      if (quiet) return;
      for (var i = 0; i < STAGES.length; i++) if (STAGES[i][0] === v) jump(i);
    });
    A.button(row, "Play again", function () { jump(0); }, "primary");
    if (!isNaN(at)) draw(Math.min(at, END - 0.001));
  });
})();
