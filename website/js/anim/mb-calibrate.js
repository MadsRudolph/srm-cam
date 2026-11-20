/* Calibrate on the laser page, one press: the drilled sheet lies anywhere on the 220 mm
   bed, even a quarter turn round. Photo; the board found by its holes over the whole bed in
   all four turns; autofocus at the job's middle; proof marks fired in the waste of the sheet
   to correct the camera; the job locked exactly onto the holes; the report. The marks are
   1.5 mm squares 3.0-4.5 mm outside the outline, beside three far-apart holes
   (engine/xtool.py proof_in_waste). The switch shows why the board stays on its tabs in its
   sheet: broken out, there is no copper beside it, so the marks go on the board itself,
   hatched on the isolation round the holes (proof_on_isolation). Bed, sheet and board sizes
   are to scale; the frame is drawn 1.35x and the camera's error is exaggerated. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  var STEPS = [
    ["Photo", "The sheet can lie anywhere on the bed, even a quarter turn round. The drawing is still where it was."],
    ["Find the board", "Its drilled holes are looked for over the whole bed, in all four quarter turns. The job jumps onto them, roughly."],
    ["Autofocus", "At the focus cross: the job's middle, kept 1.5 mm clear of holes and off the cut-out."],
    ["Correct the camera", "Three small marks, 1.5 mm squares, are fired in the waste 3 to 4.5 mm outside the board, beside three far-apart holes. The photo shows them a little off where they were aimed: that is the camera's correction."],
    ["Lock onto the holes", "With the camera corrected, the job goes exactly onto the drilled holes."],
    ["The report", "Each step with its numbers, and a verdict. Calibrate never etches: Etch the traces is still yours to press."]
  ];

  // Board frame, mm: 60 x 40 board, its holes; the sheet is 110 x 80 round it.
  var BW = 60, BH = 40, SW = 120, SH = 84, BX = -14, F = 1.35;  // F: the frame drawn larger than life      // board centre sits 12 mm left of the sheet's
  var HOLES = [[-26, -16], [26, -16], [-26, 16], [26, 16], [-14, -6], [-10, -6], [-6, -6],
               [6, 8], [10, 8], [14, 8], [-18, 10], [18, -8]];
  var TRACES = [[[-14, -6], [-14, 2], [6, 2], [6, 8]], [[-6, -6], [-6, -2], [18, -2], [18, -8]],
                [[-18, 10], [-2, 10], [-2, 8], [10, 8]], [[-10, -6], [-10, -12], [12, -12], [14, 8]]];
  // In the waste: each on the lane 3.0-4.5 mm out (centre 3.75 mm), at the point nearest
  // its hole; sheet frame (the board's centre is BX). Holes (-26,-16), (26,16), (26,-16).
  var MARKS = [[BX - 30 - 3.75, -16], [BX + 30 + 3.75, 16], [BX + 26, -20 - 3.75]];
  var MARKS_ON_BOARD = [[-26, -16], [26, 16], [26, -16]];   // no waste: round those holes, on the isolation
  // The sheet on the bed: centre and turn. The drawing starts elsewhere, not turned.
  var SHEET = { x: 150, y: 110, r: 90 };
  var START = { x: 66, y: 182, r: 0 };
  var ROUGH = { dx: 2.2, dy: -1.6, dr: 1.2 };               // after the coarse find
  var CAM = [2.0, 1.4];                                     // camera error, mm (exaggerated)

  A.define("mb-calibrate", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 760 : 470;
    var svg = A.stage(host, W, H, "Calibrate on the laser page: a photo of the bed, the board found by its drilled holes, autofocus, proof marks in the waste of the sheet to correct the camera, the job locked onto the holes, and the report");

    var BED = narrow ? 470 : 420, X0 = narrow ? 25 : 20, Y0 = 36, K = BED / 220;
    A.text(svg, X0, 24, "THE LASER BED, 220 × 220 MM", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: X0, y: Y0, width: BED, height: BED, fill: C.sunk, stroke: C.ruleStrong });
    for (var gx = 20; gx < 220; gx += 20) {
      A.el(svg, "line", { x1: X0 + gx * K, y1: Y0, x2: X0 + gx * K, y2: Y0 + BED, stroke: C.rule });
      A.el(svg, "line", { x1: X0, y1: Y0 + gx * K, x2: X0 + BED, y2: Y0 + gx * K, stroke: C.rule });
    }
    function tf(p) { return "translate(" + (X0 + p.x * K) + " " + (Y0 + p.y * K) + ") rotate(" + p.r + ") scale(" + K * F + ")"; }

    // --- the real sheet (or the board alone)
    var real = A.el(svg, "g", { transform: tf(SHEET) });
    var sheet = A.el(real, "rect", { x: -SW / 2, y: -SH / 2, width: SW, height: SH, fill: C.copperFill, stroke: C.copperDim, "stroke-width": 0.6 });
    var boardG = A.el(real, "g", { transform: "translate(" + BX + " 0)" });
    // the cut-out channel round the board, with four tabs on the long sides
    var cut = A.el(boardG, "g", { stroke: C.ink, "stroke-width": 1.6, fill: "none" });
    var L = BW / 2 + 1, T = BH / 2 + 1;
    [[[-L, -T], [-18, -T]], [[-14, -T], [14, -T]], [[18, -T], [L, -T]], [[L, -T], [L, T]],
     [[-L, T], [-18, T]], [[-14, T], [14, T]], [[18, T], [L, T]], [[-L, T], [-L, -T]]]
      .forEach(function (s) { A.el(cut, "line", { x1: s[0][0], y1: s[0][1], x2: s[1][0], y2: s[1][1] }); });
    var boardFace = A.el(boardG, "rect", { x: -BW / 2, y: -BH / 2, width: BW, height: BH, fill: C.copperDim, stroke: "none" });
    HOLES.forEach(function (h) { A.el(boardG, "circle", { cx: h[0], cy: h[1], r: 0.9, fill: C.ink }); });

    // proof marks: where aimed (dashed) and where the photo sees them
    var markG = A.el(svg, "g");
    var wl = (function () { var r = SHEET.r * Math.PI / 180, x = 28, y = 0;
      return [X0 + (SHEET.x + F * (x * Math.cos(r) - y * Math.sin(r))) * K, Y0 + (SHEET.y + F * (x * Math.sin(r) + y * Math.cos(r))) * K]; })();
    var wasteLbl = A.text(svg, wl[0], wl[1] + 4, "WASTE", { size: 12, weight: 600, anchor: "middle", fill: C.copperHi, font: "label", spacing: "0.08em" });

    // --- the drawing (the job), in live blue
    var job = A.el(svg, "g", { transform: tf(START) });
    var jb = A.el(job, "g", { transform: "translate(" + BX + " 0)" });
    A.el(jb, "rect", { x: -BW / 2, y: -BH / 2, width: BW, height: BH, fill: "none", stroke: C.live, "stroke-width": 0.7, "stroke-dasharray": "2 1.4" });
    TRACES.forEach(function (t) {
      A.el(jb, "polyline", { points: t.map(function (p) { return p.join(","); }).join(" "), fill: "none", stroke: C.live, "stroke-width": 0.9, opacity: 0.75 });
    });
    var jobHoles = HOLES.map(function (h) { return A.el(jb, "circle", { cx: h[0], cy: h[1], r: 1.6, fill: "none", stroke: C.live, "stroke-width": 0.5 }); });

    // scan ghosts (step 2): the hole pattern tried in four turns
    var ghost = A.el(svg, "g", { opacity: 0 });
    var gh = A.el(ghost, "g", { transform: "translate(" + BX + " 0)" });
    A.el(gh, "rect", { x: -BW / 2, y: -BH / 2, width: BW, height: BH, fill: "none", stroke: C.text3, "stroke-width": 0.6, "stroke-dasharray": "1.5 1.5" });
    HOLES.forEach(function (h) { A.el(gh, "circle", { cx: h[0], cy: h[1], r: 1.4, fill: "none", stroke: C.text3, "stroke-width": 0.5 }); });
    var found = A.el(svg, "g");                              // green rings on found holes

    // focus cross
    var focus = A.el(svg, "g", { opacity: 0 });
    var fr = A.el(focus, "circle", { r: 10, fill: "none", stroke: C.ok, "stroke-width": 2 });
    A.el(focus, "line", { x1: -14, y1: 0, x2: 14, y2: 0, stroke: C.ok, "stroke-width": 2 });
    A.el(focus, "line", { x1: 0, y1: -14, x2: 0, y2: 14, stroke: C.ok, "stroke-width": 2 });

    var flash = A.el(svg, "rect", { x: X0, y: Y0, width: BED, height: BED, fill: C.text, opacity: 0, "pointer-events": "none" });

    // --- the step list
    var LX = narrow ? X0 : X0 + BED + 34, LY = narrow ? Y0 + BED + 36 : Y0 + 8;
    A.text(svg, LX, LY - 14 + (narrow ? 0 : 0), "CALIBRATE, ONE PRESS", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var rows = STEPS.map(function (s, i) {
      var y = LY + 10 + i * (narrow ? 34 : 36);
      var bg = A.el(svg, "rect", { x: LX - 8, y: y - 2, width: W - LX - 12, height: 30, rx: 3, fill: "none" });
      var dot = A.el(svg, "circle", { cx: LX + 8, cy: y + 13, r: 9, fill: "none", stroke: C.ruleStrong, "stroke-width": 1.5 });
      var num = A.text(svg, LX + 8, y + 18, String(i + 1), { size: 12, weight: 700, anchor: "middle", fill: C.text3, font: "mono" });
      var t = A.text(svg, LX + 28, y + 19, s[0], { size: 16, weight: 600, fill: C.text2 });
      return { bg: bg, dot: dot, num: num, t: t };
    });
    var RY = LY + 10 + 6 * (narrow ? 34 : 36) + 14;
    var rep = A.el(svg, "g", { opacity: 0 });
    var repBox = A.el(rep, "rect", { x: LX - 8, y: RY, width: W - LX - 12, height: narrow ? 104 : 112, rx: 3, fill: C.okFill, stroke: C.ok });
    var repT = A.text(rep, LX + 6, RY + 26, "", { size: 17, weight: 700, fill: C.ok });
    var repL = [0, 1, 2].map(function (k) { return A.text(rep, LX + 6, RY + 50 + k * 20, "", { size: 13.5, fill: C.text2 }); });

    // --- controls
    var row = A.controls(host);
    var step = 0, p = 0, hold = 0, playing = !A.reduced, mode = "sheet", ready = false;
    var playBtn = A.button(row, playing ? "Pause" : "Play", function () {
      playing = !playing; playBtn.textContent = playing ? "Pause" : "Play";
      if (playing && step === STEPS.length - 1 && p >= 1) go(0);
    });
    A.button(row, "← Back", function () { go(Math.max(0, step - 1)); stopPlay(); });
    A.button(row, "Next →", function () { go(Math.min(STEPS.length - 1, step + 1)); stopPlay(); }, "primary");
    var seg = A.segmented(row, [["sheet", "Board in its sheet"], ["out", "Board broken out"]], "sheet", function (v) { mode = v; if (ready) draw(); });
    var st = A.status(row);
    function stopPlay() { playing = false; playBtn.textContent = "Play"; }
    function go(i) { step = i; p = 0; hold = 0; draw(); }

    // bed mm of a point in the board's frame, for a placement (sheet-like transform)
    function bedPt(pl, x, y) {
      var r = pl.r * Math.PI / 180, c = Math.cos(r), s = Math.sin(r);
      return [pl.x + F * (x * c - y * s), pl.y + F * (x * s + y * c)];
    }
    function px(pt) { return [X0 + pt[0] * K, Y0 + pt[1] * K]; }
    function mix(a, b, t) { return { x: A.lerp(a.x, b.x, t), y: A.lerp(a.y, b.y, t), r: A.lerp(a.r, b.r, t) }; }
    var rough = { x: SHEET.x + ROUGH.dx, y: SHEET.y + ROUGH.dy, r: SHEET.r + ROUGH.dr };

    function draw() {
      var out = mode === "out";
      A.set(sheet, { opacity: out ? 0 : 1 });
      A.set(cut, { opacity: out ? 0 : 1 });
      A.set(wasteLbl, { opacity: out ? 0 : 1 });
      A.set(boardFace, { fill: out ? C.copper : C.copperDim });

      // where the job is
      var pl = START;
      if (step === 1) pl = mix(START, rough, A.ease((p - 0.55) / 0.45));
      else if (step >= 2 && step <= 3) pl = rough;
      else if (step === 4) pl = mix(rough, SHEET, A.ease(p / 0.7));
      else if (step >= 5) pl = SHEET;
      A.set(job, { transform: tf(pl) });
      var locked = step >= 4 && (step > 4 || p > 0.7);
      jobHoles.forEach(function (c) { A.set(c, { stroke: locked ? C.ok : C.live }); });

      // photo flash
      A.set(flash, { opacity: step === 0 ? 0.35 * (1 - A.ease(p / 0.5)) : 0 });

      // scan ghosts
      while (found.firstChild) found.removeChild(found.firstChild);
      if (step === 1 && p < 0.55) {
        var k = Math.floor(p / 0.55 * 4) % 4;
        A.set(ghost, { opacity: 0.9, transform: tf({ x: SHEET.x + [-40, 30, -20, 0][k], y: SHEET.y + [-50, 40, 45, 0][k], r: 90 * k + (k === 1 ? 0 : 0) }) });
      } else A.set(ghost, { opacity: 0 });
      if (step >= 1 && (step > 1 || p > 0.5)) {
        HOLES.forEach(function (h) {
          var q = px(bedPt(SHEET, h[0] + BX, h[1]));
          A.el(found, "circle", { cx: q[0], cy: q[1], r: 4.5, fill: "none", stroke: C.ok, "stroke-width": 1.3, opacity: step >= 5 ? 0.5 : 0.9 });
        });
      }

      // focus cross at the job's middle (between holes)
      if (step >= 2) {
        var fc = px(bedPt(pl, BX + 0, 0));
        A.set(focus, { opacity: 1, transform: "translate(" + fc[0] + " " + fc[1] + ")" });
        A.set(fr, { r: step === 2 ? 6 + 10 * (1 - A.ease(p)) : 6 });
      } else A.set(focus, { opacity: 0 });

      // proof marks
      while (markG.firstChild) markG.removeChild(markG.firstChild);
      if (step >= 3) {
        var list = out ? MARKS_ON_BOARD.map(function (m) { return [m[0] + BX, m[1]]; }) : MARKS;
        var col = out ? C.caution : C.text;
        var seen = step > 3 || p > 0.35;
        var MS = 1.5 * F * K;                                 // a 1.5 mm square, on screen
        list.forEach(function (m, i) {
          var aim = px(bedPt(SHEET, m[0], m[1]));
          var hit = [aim[0] + CAM[0] * K, aim[1] + CAM[1] * K];
          A.el(markG, "circle", { cx: aim[0], cy: aim[1], r: out ? 2.5 * F * K : 6, fill: "none", stroke: out ? C.caution : C.text3, "stroke-width": 1, "stroke-dasharray": "2 2" });
          if (seen) {
            if (out) {
              // hatched on the isolation ring round the hole
              for (var hh = -3; hh <= 3; hh++) A.el(markG, "line", { x1: hit[0] - 6 + hh * 2, y1: hit[1] + 6, x2: hit[0] + 6 + hh * 2, y2: hit[1] - 6, stroke: col, "stroke-width": 1.1, opacity: 0.9 });
            } else {
              A.el(markG, "rect", { x: hit[0] - MS / 2, y: hit[1] - MS / 2, width: MS, height: MS, fill: C.ink, stroke: col, "stroke-width": 1.2 });
            }
            if (i === 0 && step === 3 && p > 0.6) A.arrow(markG, aim[0], aim[1], hit[0], hit[1], { color: C.caution, width: 1.5, head: 5 });
          }
        });
        if (step === 3 && p > 0.6) {
          var a0 = px([SHEET.x, 186]);
          A.text(markG, a0[0], a0[1] + 30, "camera correction", { size: 13, weight: 600, fill: C.caution, anchor: "middle" });
          A.text(markG, a0[0], a0[1] + 46, "(exaggerated)", { size: 12, fill: C.text3, anchor: "middle" });
        }
      }

      // the list
      rows.forEach(function (r, i) {
        var cur = i === step, done = i < step || (i === step && i === STEPS.length - 1 && p >= 1);
        var warn = out && i === 3 && step >= 3;
        A.set(r.bg, { fill: cur ? C.liveFill : "none" });
        A.set(r.dot, { fill: done ? (warn ? C.caution : C.ok) : "none", stroke: done ? (warn ? C.caution : C.ok) : cur ? C.live : C.ruleStrong });
        A.set(r.num, { fill: done ? C.ink : cur ? C.live : C.text3 });
        A.set(r.t, { fill: cur ? C.text : done ? C.text2 : C.text3 });
      });

      // report
      A.set(rep, { opacity: step === 5 ? A.ease(p / 0.4) : 0 });
      if (out) {
        A.set(repBox, { fill: C.okFill, stroke: C.caution });
        A.set(repT, { fill: C.ok }); repT.textContent = "Ready to cut";
        repL[0].textContent = "✓ Find the board: 12 of 12 holes";
        repL[1].textContent = "✓ Camera and holes: proof on 3 marks";
        repL[2].textContent = "   in the isolation, on the board itself";
      } else {
        A.set(repBox, { fill: C.okFill, stroke: C.ok });
        A.set(repT, { fill: C.ok }); repT.textContent = "Ready to cut";
        repL[0].textContent = "✓ Find the board: 12 of 12 holes";
        repL[1].textContent = "✓ Camera and holes: proof on 3 marks";
        repL[2].textContent = "   in the waste beside the board";
      }

      // words
      var words = STEPS[step][1];
      if (out && step === 3) words = "Broken out of its sheet, there is no copper beside the board to mark on. The marks go on the board itself, hatched on the isolation round three holes: copper the etch removes anyway. It works, but in its sheet the marks land in scrap.";
      if (out && step === 5) words = "The verdict is the same; the report says the marks went “in the isolation”. Keep the board on its tabs in its sheet until the laser is done.";
      say(out && step >= 3 ? "caution" : step === 5 ? "ok" : "", (step + 1) + " · " + STEPS[step][0] + ": " + words);
    }
    var lastSaid = "";
    function say(kind, s) {
      if (s === lastSaid) return;
      lastSaid = s;
      st.className = "anim-status" + (kind ? " " + kind : "");
      st.textContent = s;
    }

    ready = true;
    // ?mbstep=N (1-6) shows that step finished: for checking the drawing.
    var m = /[?&]mbstep=(\d)/.exec(location.search);
    var m2 = /[?&]mbmode=out/.test(location.search);
    if (m2) seg.set("out");
    if (m) { step = Math.min(5, Math.max(0, +m[1] - 1)); p = 1; playing = false; playBtn.textContent = "Play"; }
    draw();

    A.loop(host, function (t, dt) {
      if (!playing) return;
      if (p < 1) { p = Math.min(1, p + dt / 2.6); draw(); return; }
      hold += dt;
      if (hold > (step === STEPS.length - 1 ? 3.5 : 0.9)) {
        hold = 0;
        if (step < STEPS.length - 1) { step++; p = 0; } else { step = 0; p = 0; }
        draw();
      }
    }, 0);
    if (A.reduced) { step = STEPS.length - 1; p = 1; draw(); }
  });
})();
