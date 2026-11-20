/* Lining the mask up on the laser page (gui2/stencil_laser.py align; engine/xtool_camera.py
   align): the Mask job has no Calibrate. The inked board goes on the bed copper face up;
   Autofocus on the ink ("ready to align"); the drawing dragged roughly onto the board;
   Align takes a photo and looks for the drilled holes, dark dots through the ink, within
   about 25 mm and 6 degrees, in all four quarter turns, and moves the job only if it finds
   at least 75 % of them. Show where then traces the outline in blue. A 54 x 45.8 mm board
   with 27 holes, to scale; the misplacement is an example. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BW = 54, BH = 45.8, VW = 130, VH = 100, SEARCH = 25;
  var HOLES = [];
  (function () {
    var s = 11;
    function r() { s = (s * 9301 + 49297) % 233280; return s / 233280; }
    for (var i = 0; i < 27; i++) HOLES.push([4 + r() * (BW - 8), 4 + r() * (BH - 8)]);
  })();
  var BOARD = { x: 38, y: 27 };                       // where the board really is, view mm
  var STEPS = [
    ["Board on the bed", "Inked copper face up, in its sheet if you can, square to the bed. The drilled holes show as dark dots through the ink."],
    ["Autofocus", "On the ink, at the focus cross. “In focus. Photo refreshed at the new head height; ready to align.”"],
    ["Drag it close", "Drag the drawing roughly onto the board in the photo: Align searches about 25 mm round it."],
    ["Align", ""],
    ["Show where", "The blue diode traces the outline on the board, without marking. Then Open the mask."]
  ];

  A.define("sm-align", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, SW = narrow ? 480 : 520, K = SW / VW, SH = VH * K;
    var X0 = 20, Y0 = 40, H = narrow ? Y0 + SH + 230 : Y0 + SH + 30;
    var svg = A.stage(host, W, H, "The mask job on the laser page: the inked board's drilled holes seen as dark dots, the drawing dragged close, and Align moving it onto the holes");
    function X(mm) { return X0 + mm * K; }
    function Y(mm) { return Y0 + mm * K; }
    A.text(svg, X0, 26, "THE MASK JOB ON THE LASER PAGE · TO SCALE", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: X0, y: Y0, width: SW, height: SH, fill: C.sunk, stroke: C.ruleStrong });
    for (var g = 10; g < VW; g += 10) A.el(svg, "line", { x1: X(g), y1: Y0, x2: X(g), y2: Y0 + SH, stroke: C.rule });
    for (g = 10; g < VH; g += 10) A.el(svg, "line", { x1: X0, y1: Y(g), x2: X0 + SW, y2: Y(g), stroke: C.rule });
    // the sheet and the inked board, as the photo shows them
    A.el(svg, "rect", { x: X(BOARD.x - 9), y: Y(BOARD.y - 9), width: (BW + 18) * K, height: (BH + 18) * K, fill: C.copperDim });
    A.el(svg, "rect", { x: X(BOARD.x - 1.5), y: Y(BOARD.y - 1.5), width: (BW + 3) * K, height: (BH + 3) * K, fill: "#1f5a35" });
    A.el(svg, "rect", { x: X(BOARD.x), y: Y(BOARD.y), width: BW * K, height: BH * K, fill: "none", stroke: C.ink, "stroke-width": 0.8 * K });
    HOLES.forEach(function (h) { A.el(svg, "circle", { cx: X(BOARD.x + h[0]), cy: Y(BOARD.y + h[1]), r: 0.5 * K + 1, fill: C.ink }); });
    var search = A.el(svg, "circle", { r: SEARCH * K, fill: C.live, "fill-opacity": 0.05, stroke: C.live, "stroke-dasharray": "5 5", opacity: 0 });
    var found = A.el(svg, "g");
    // the drawing (the job): openings over the holes, the outline
    var job = A.el(svg, "g");
    A.el(job, "rect", { x: 0, y: 0, width: BW * K, height: BH * K, fill: "none", stroke: C.live, "stroke-width": 1.5, "stroke-dasharray": "6 4" });
    HOLES.forEach(function (h) { A.el(job, "circle", { cx: h[0] * K, cy: h[1] * K, r: 1.4 * K, fill: "none", stroke: C.live, "stroke-width": 1.4 }); });
    var trace = A.el(svg, "rect", { x: X(BOARD.x), y: Y(BOARD.y), width: BW * K, height: BH * K, fill: "none", stroke: C.live, "stroke-width": 3, opacity: 0 });
    var cross = A.el(svg, "g", { opacity: 0 });
    var cr = A.el(cross, "circle", { r: 9, fill: "none", stroke: C.ok, "stroke-width": 2 });
    A.el(cross, "line", { x1: -13, y1: 0, x2: 13, y2: 0, stroke: C.ok, "stroke-width": 2 });
    A.el(cross, "line", { x1: 0, y1: -13, x2: 0, y2: 13, stroke: C.ok, "stroke-width": 2 });

    var PX = narrow ? X0 : X0 + SW + 24, PY = narrow ? Y0 + SH + 30 : Y0 + 6;
    var rows = STEPS.map(function (s, i) {
      var y = PY + 14 + i * 32;
      var dot = A.el(svg, "circle", { cx: PX + 9, cy: y + 6, r: 9, fill: "none", stroke: C.ruleStrong, "stroke-width": 1.5 });
      var num = A.text(svg, PX + 9, y + 10.5, String(i + 1), { size: 11, weight: 700, anchor: "middle", fill: C.text3, font: "mono" });
      var t = A.text(svg, PX + 28, y + 11, s[0], { size: 15, weight: 600, fill: C.text3 });
      return { dot: dot, num: num, t: t };
    });

    var row = A.controls(host);
    var step = 0, far = false, ready = false;
    A.button(row, "← Back", function () { step = Math.max(0, step - 1); draw(); });
    A.button(row, "Next →", function () { step = Math.min(STEPS.length - 1, step + 1); draw(); }, "primary");
    A.segmented(row, [["near", "Dragged close"], ["far", "Left 40 mm away"]], "near", function (v) { far = v === "far"; if (ready) draw(); });
    var st = A.status(row);

    var START = { x: 4, y: 52, r: 0 };
    function pos() {
      if (step < 2) return START;
      var near = far ? { x: BOARD.x + 34, y: BOARD.y + 22, r: 0 } : { x: BOARD.x + 3.1, y: BOARD.y - 2.4, r: 2.5 };
      if (step === 2) return near;
      return far ? near : { x: BOARD.x, y: BOARD.y, r: 0 };
    }
    function draw() {
      var p = pos();
      A.set(job, { transform: "translate(" + X(p.x) + " " + Y(p.y) + ") rotate(" + p.r + ")" });
      var mid = [X(p.x + BW / 2), Y(p.y + BH / 2)];
      A.set(search, { cx: mid[0], cy: mid[1], opacity: step === 2 || (step === 3 && far) ? 1 : 0 });
      A.set(cross, { opacity: step >= 1 ? 1 : 0, transform: "translate(" + X(BOARD.x + BW / 2 + 5) + " " + Y(BOARD.y + BH / 2) + ")" });
      while (found.firstChild) found.removeChild(found.firstChild);
      var ok = step >= 3 && !far;
      if (ok) HOLES.forEach(function (h) { A.el(found, "circle", { cx: X(BOARD.x + h[0]), cy: Y(BOARD.y + h[1]), r: 2.4 * K, fill: "none", stroke: C.ok, "stroke-width": 1.4 }); });
      A.set(trace, { opacity: step === 4 && !far ? 1 : 0 });
      rows.forEach(function (r, i) {
        var bad = far && i === 3 && step >= 3;
        var done = i < step && !(far && i === 3), cur = i === step;
        A.set(r.dot, { fill: done ? C.ok : bad ? C.caution : "none", stroke: done ? C.ok : bad ? C.caution : cur ? C.live : C.ruleStrong });
        A.set(r.num, { fill: done || bad ? C.ink : cur ? C.live : C.text3 });
        A.set(r.t, { fill: cur ? C.text : done ? C.text2 : C.text3 });
      });
      var words = STEPS[step][1], kind = "";
      if (step === 3) {
        words = far ? "“Could not match the references: at best 4 of 27 (needs 21). Drag the drawing closer, choose clearer references, or pick matching points.” Nothing moved."
          : "“Aligned on 27 of 27 references: moved 3.92 mm (X -3.10, Y +2.40), turned -2.5°. Check with Show where before cutting.”";
        kind = far ? "caution" : "ok";
      }
      if (step === 4 && far) { words = "Align first: drag the drawing within about 25 mm of the board and press Align again."; kind = "caution"; }
      st.className = "anim-status" + (kind ? " " + kind : "");
      st.textContent = (step + 1) + " · " + STEPS[step][0] + ": " + words;
    }
    ready = true;
    var m = /[?&]smstep=(\d)/.exec(location.search);
    if (m) step = Math.min(4, +m[1] - 1);
    draw();
  });
})();
