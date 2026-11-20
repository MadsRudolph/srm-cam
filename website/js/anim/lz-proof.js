/* Calibrate's camera marks, close up and to scale (engine/xtool.py proof_in_waste,
   proof_on_isolation; engine/xtool_camera.py sheet_continues, locate_change).
   In its sheet: each mark is a filled square 1.5 mm across, 3.0 to 4.5 mm outside the
   board's outline, on the point of that lane nearest its drilled hole; before firing,
   photo A must show sheet (bright copper) under every mark. Out of its sheet: no copper
   there, so the marks go on the isolation the job removes anyway, hatched, within
   2.5 mm of the hole. Photo A, the marks (3 passes), photo B: what changed between them
   is where the laser really fired; the gap to where it was aimed is the camera's
   correction. The board edge, the 0.8 mm cut-out channel and a 1.5 mm tab are drawn to
   scale; the pad and the camera's error are examples. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var X1 = -6.5, X2 = 8.5, Y1 = -4.6, Y2 = 4.6;      // the view, mm (outline at x = 0)
  var HOLE = [-2.6, -0.6], PAD = 1.0, HOLE_R = 0.4, ISO = 0.22;
  var TAB = [2.2, 3.7];                               // a tab across the channel, y range
  var STEPS = [
    ["Is there sheet?", "Photo A is checked for bright copper under each mark's spot, 3 to 4.5 mm outside the outline."],
    ["Photo A", "A photo before any mark."],
    ["Fire the marks", "Three small marks, 3 passes each: enough for the camera to see, far fewer than the etch."],
    ["Photo B", "What changed between A and B is where the laser really fired."],
    ["The correction", "The gap between where it was aimed and where it landed is the camera's error. It is corrected for every job on this PC."]
  ];

  A.define("lz-proof", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, VW = narrow ? 480 : 560, X0 = 20, Y0 = 40;
    var K = VW / (X2 - X1), VH = (Y2 - Y1) * K;
    var H = narrow ? Y0 + VH + 300 : Y0 + VH + 40;
    var svg = A.stage(host, W, H, "Close-up of the board's edge on the laser bed, to scale: the drilled hole, the cut-out channel, a tab, and the 1.5 mm camera mark 3 to 4.5 mm out in the waste, or on the isolation when there is no waste");
    function X(mm) { return X0 + (mm - X1) * K; }
    function Y(mm) { return Y0 + (mm - Y1) * K; }
    A.text(svg, X0, 26, "THE BOARD'S EDGE, CLOSE UP · TO SCALE", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });

    var clip = A.el(A.el(svg, "defs"), "clipPath", { id: "lzp-clip" });
    A.el(clip, "rect", { x: X0, y: Y0, width: VW, height: VH });
    var hatchP = A.el(svg.querySelector("defs"), "pattern", { id: "lzp-hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
    A.el(hatchP, "rect", { width: 6, height: 6, fill: C.copperDim });
    A.el(hatchP, "line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: C.caution, "stroke-width": 2.4 });
    var v = A.el(svg, "g", { "clip-path": "url(#lzp-clip)" });
    A.el(v, "rect", { x: X0, y: Y0, width: VW, height: VH, fill: C.ink });          // the bed
    var waste = A.el(v, "rect", { x: X(0.8), y: Y0, width: X(X2) - X(0.8), height: VH, fill: C.copper });
    var tab = A.el(v, "rect", { x: X(0), y: Y(TAB[0]), width: 0.8 * K, height: (TAB[1] - TAB[0]) * K, fill: C.copper });
    A.el(v, "rect", { x: X0, y: Y0, width: X(0) - X0, height: VH, fill: C.copper });  // the board
    // a trace and the pad round the hole, with their isolation trench (laminate shows)
    var iso = A.el(v, "g", {});
    A.el(iso, "rect", { x: X(X1), y: Y(HOLE[1]) - (0.3 + ISO) * K, width: (HOLE[0] - X1) * K, height: (0.6 + 2 * ISO) * K, fill: C.fr4 });
    A.el(iso, "circle", { cx: X(HOLE[0]), cy: Y(HOLE[1]), r: (PAD + ISO) * K, fill: C.fr4 });
    var isoHatch = A.el(v, "g", { opacity: 0 });
    A.el(isoHatch, "circle", { cx: X(HOLE[0]), cy: Y(HOLE[1]), r: (PAD + ISO) * K, fill: "url(#lzp-hatch)" });
    A.el(v, "rect", { x: X(X1), y: Y(HOLE[1]) - 0.3 * K, width: (HOLE[0] - X1) * K, height: 0.6 * K, fill: C.copperHi });
    A.el(v, "circle", { cx: X(HOLE[0]), cy: Y(HOLE[1]), r: PAD * K, fill: C.copperHi });
    A.el(v, "circle", { cx: X(HOLE[0]), cy: Y(HOLE[1]), r: HOLE_R * K, fill: C.ink });
    var r25 = A.el(v, "circle", { cx: X(HOLE[0]), cy: Y(HOLE[1]), r: 2.5 * K, fill: "none", stroke: C.caution, "stroke-width": 1.2, "stroke-dasharray": "4 4", opacity: 0 });
    var outl = A.el(v, "line", { x1: X(0), y1: Y0, x2: X(0), y2: Y0 + VH, stroke: C.text3, "stroke-width": 1, "stroke-dasharray": "5 4" });
    // the mark lane, 3.0-4.5 mm out
    var lane = A.el(v, "rect", { x: X(3.0), y: Y0, width: 1.5 * K, height: VH, fill: C.text, "fill-opacity": 0.06, stroke: C.text3, "stroke-dasharray": "2 4" });
    var patch = A.el(v, "rect", { x: X(3.15), y: Y(HOLE[1]) - 0.3 * K, width: 1.2 * K, height: 0.6 * K, fill: "none", stroke: C.live, "stroke-width": 1.6 });
    var aim = A.el(v, "rect", { x: X(3.0), y: Y(HOLE[1] - 0.75), width: 1.5 * K, height: 1.5 * K, fill: "none", stroke: C.text, "stroke-width": 1.4, "stroke-dasharray": "4 3" });
    var hit = A.el(v, "rect", { width: 1.5 * K, height: 1.5 * K, fill: "#3a2a1c", stroke: C.ink, "stroke-width": 1 });
    var corr = A.el(v, "g", {});

    // dimension labels, above the view
    function dim(x1, x2, y, s) {
      var g = A.el(svg, "g");
      A.el(g, "line", { x1: X(x1), y1: y, x2: X(x2), y2: y, stroke: C.text3, "stroke-width": 1 });
      [x1, x2].forEach(function (x) { A.el(g, "line", { x1: X(x), y1: y - 4, x2: X(x), y2: y + 4, stroke: C.text3 }); });
      A.text(g, (X(x1) + X(x2)) / 2, y - 6, s, { size: 12, anchor: "middle", fill: C.text2 });
      return g;
    }
    var dimCh = dim(0, 0.8, Y0 + VH + 16, "0.8");
    dim(3.0, 4.5, Y0 + VH + 16, "3.0 – 4.5 mm out");
    var lblBoard = A.text(svg, X(-0.3), Y(Y2) - 8, "board", { size: 13, anchor: "end", fill: C.ink, weight: 700 });
    var lblWaste = A.text(svg, X(6.6), Y(Y2) - 8, "waste", { size: 13, anchor: "middle", fill: C.ink, weight: 700 });
    var lblTab = A.text(svg, X(1.0), Y(TAB[1]) + 14, "tab", { size: 12, fill: C.ink, weight: 700 });

    // words panel
    var PX = narrow ? X0 : X0 + VW + 26, PY = narrow ? Y0 + VH + 46 : Y0 + 6, PW = W - PX - 16;
    A.text(svg, PX, PY + 10, "CALIBRATE: CAMERA AND HOLES", { size: 13, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var rows = STEPS.map(function (s, i) {
      var y = PY + 30 + i * 30;
      var dot = A.el(svg, "circle", { cx: PX + 9, cy: y + 6, r: 8, fill: "none", stroke: C.ruleStrong, "stroke-width": 1.5 });
      var num = A.text(svg, PX + 9, y + 10.5, String(i + 1), { size: 11, weight: 700, anchor: "middle", fill: C.text3, font: "mono" });
      var t = A.text(svg, PX + 26, y + 11, s[0], { size: 14.5, weight: 600, fill: C.text3 });
      return { dot: dot, num: num, t: t };
    });
    var rep = A.text(svg, PX, PY + 30 + STEPS.length * 30 + 14, "", { size: 13, fill: C.text2 });
    var rep2 = A.text(svg, PX, PY + 30 + STEPS.length * 30 + 32, "", { size: 13, fill: C.text2 });
    var rep3 = A.text(svg, PX, PY + 30 + STEPS.length * 30 + 50, "", { size: 13, fill: C.text2 });

    var row = A.controls(host);
    var mode = "sheet", err = 0.6, step = 0, ready = false;
    A.button(row, "← Back", function () { step = Math.max(0, step - 1); draw(); });
    A.button(row, "Next →", function () { step = Math.min(STEPS.length - 1, step + 1); draw(); }, "primary");
    A.segmented(row, [["sheet", "In its sheet"], ["out", "Broken out"]], "sheet", function (m) { mode = m; if (ready) draw(); });
    A.slider(row, "Camera off by", 0, 1.5, 0.05, err, function (x) { err = x; if (ready) draw(); }, function (x) { return x.toFixed(2) + " mm"; });
    var st = A.status(row);

    function draw() {
      var out = mode === "out";
      A.set(waste, { opacity: out ? 0 : 1 });
      A.set(tab, { opacity: out ? 0 : 1 });
      A.set(lblWaste, { opacity: out ? 0 : 1 });
      A.set(lblTab, { opacity: out ? 0 : 1 });
      A.set(lane, { opacity: out ? 0.35 : 1 });
      A.set(patch, { opacity: step === 0 ? 1 : 0, stroke: out ? C.danger : C.live });
      A.set(r25, { opacity: out && step >= 2 ? 1 : 0 });
      A.set(aim, { opacity: !out && step >= 2 ? 1 : 0 });
      var fired = step >= 2, seen = step >= 3;
      // where it really fired: the camera's error shifts the photo, the beam lands true
      var dx = err * 0.8, dy = err * 0.6;
      A.set(hit, { opacity: !out && fired ? 1 : 0, x: X(3.0) + (seen ? 0 : 0), y: Y(HOLE[1] - 0.75) });
      A.set(isoHatch, { opacity: out && fired ? 1 : 0 });
      // the photo's view of the mark, offset by the camera's error
      while (corr.firstChild) corr.removeChild(corr.firstChild);
      if (seen && err > 0.02) {
        var ax = out ? X(HOLE[0]) : X(3.75), ay = Y(HOLE[1]);
        var px = ax + dx * K, py = ay + dy * K;
        if (!out) A.el(corr, "rect", { x: px - 0.75 * K, y: py - 0.75 * K, width: 1.5 * K, height: 1.5 * K, fill: "none", stroke: C.caution, "stroke-width": 1.6 });
        else A.el(corr, "circle", { cx: px, cy: py, r: (PAD + ISO) * K, fill: "none", stroke: C.caution, "stroke-width": 1.6 });
        A.text(corr, px + 0.9 * K + 4, py + 4, "in the photo", { size: 12, fill: C.caution });
        if (step >= 4) A.arrow(corr, px, py, ax, ay, { color: C.ok, width: 2, head: 7 });
      }
      rows.forEach(function (r, i) {
        var done = i < step, cur = i === step;
        A.set(r.dot, { fill: done ? C.ok : "none", stroke: done ? C.ok : cur ? C.live : C.ruleStrong });
        A.set(r.num, { fill: done ? C.ink : cur ? C.live : C.text3 });
        A.set(r.t, { fill: cur ? C.text : done ? C.text2 : C.text3 });
      });
      var where = out ? "the isolation" : "the waste beside the board";
      A.set(dimCh, { opacity: out ? 0 : 1 });
      rep.textContent = step >= 4 ? "“Proof on 3 marks in " + where : "";
      rep2.textContent = step >= 4 ? ": the camera was " + err.toFixed(2) + " mm off" : "";
      rep3.textContent = step >= 4 ? "and is corrected.”" : "";
      var words = STEPS[step][1];
      if (out && step === 0) words = "No bright copper under the spots: the board is out of its sheet. The marks will go on the isolation the job removes anyway.";
      if (out && step === 2) words = "Hatched on the isolation round the pad, within 2.5 mm of the hole: copper the etch takes off anyway. It works, but the marks are on the board.";
      st.className = "anim-status" + (out && step <= 2 ? " caution" : step === 4 ? " ok" : "");
      st.textContent = (step + 1) + " · " + STEPS[step][0] + ": " + words;
    }
    ready = true;
    var m = /[?&]lzpstep=(\d)/.exec(location.search);
    if (m) step = Math.min(4, +m[1] - 1);
    if (/[?&]lzpout/.test(location.search)) mode = "out";
    draw();
  });
})();
