/* The silkscreen job, as the student does it (window.py _laser_jobs: F.Silkscreen, not
   mirrored; no Calibrate on the Silk job; Align on the drilled holes). After the mask the
   sheet lies inked copper face up with Kapton on the laminate side. Peel the tape, turn the
   sheet over left to right, so the laminate (the component side) is up, square it to the
   bed near the middle, Autofocus on the laminate, drag the drawing close and Align on the
   same drilled holes, seen now from the other side; then Mark the silkscreen. Schematic:
   a 50 x 32 mm board in its sheet. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BW = 50, BH = 32, SWm = 74, SHm = 52;
  var HOLES = [[-21, -12], [21, -12], [-21, 12], [8, 11], [14, 11], [-6, -4]];
  var STEPS = [
    ["After the mask", "Inked copper face up, Kapton tape still on the laminate side."],
    ["Peel the Kapton", "Off the laminate side: the silkscreen goes there."],
    ["Turn it over", "Left to right, like a page. The laminate (the component side) is up now, and the holes are seen from the other side."],
    ["On the bed", "Square to the bed's edges, the board near the middle. Click Silkscreen on the rail: the Silk job, drawn as in KiCad, not mirrored."],
    ["Autofocus", "On the laminate, at the focus cross."],
    ["Drag close, Align", "Drag the drawing within about 25 mm of the board, then Align: it finds the same drilled holes and moves the drawing onto them."],
    ["Mark the silkscreen", "Check with Show where, then Mark the silkscreen. Outlines shows the result on the photo."]
  ];

  A.define("sk-flip", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, K = narrow ? 6.2 : 5.6;
    var CX = narrow ? 260 : 270, CY = 70 + SHm * K / 2;
    var SY = CY + SHm * K / 2 + 60;                 // the side view
    var H = narrow ? SY + 300 : SY + 60;
    var svg = A.stage(host, W, H, "Turning the sheet over for the silkscreen: peel the tape, flip left to right, laminate up, Autofocus and Align on the drilled holes, then mark");
    A.text(svg, 20, 28, "THE SILKSCREEN · SCHEMATIC", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.text(svg, CX, 54, "seen from above", { size: 12, anchor: "middle", fill: C.text3 });

    var top = A.el(svg, "g", { transform: "translate(" + CX + " " + CY + ")" });
    var flipG = A.el(top, "g");
    var sc = A.el(flipG, "g", { transform: "scale(" + K + ")" });
    var sheetR = A.el(sc, "rect", { x: -SWm / 2, y: -SHm / 2, width: SWm, height: SHm, fill: C.copper, stroke: C.copperDim, "stroke-width": 0.3 });
    A.el(sc, "rect", { x: -BW / 2 - 0.8, y: -BH / 2 - 0.8, width: BW + 1.6, height: BH + 1.6, fill: "none", stroke: C.ink, "stroke-width": 0.8 });
    var faceR = A.el(sc, "rect", { x: -BW / 2, y: -BH / 2, width: BW, height: BH, fill: "#1f5a35" });
    var tapeR = A.el(sc, "rect", { x: -BW / 2 - 3, y: -BH / 2 - 3, width: BW + 6, height: BH + 6, fill: "#d39a2a", opacity: 0 });
    var holesG = A.el(sc, "g");
    HOLES.forEach(function (h) { A.el(holesG, "circle", { cx: h[0], cy: h[1], r: 0.9, fill: C.ink }); });
    // the silk, as marked (in board coordinates seen from the top)
    var marked = A.el(sc, "g", { opacity: 0 });
    A.el(marked, "text", { x: 0, y: -5, "font-size": 7, "font-weight": 700, fill: C.text, "font-family": "sans-serif" }, "SRM");
    A.el(marked, "rect", { x: -9, y: 5, width: 8, height: 5, fill: "none", stroke: C.text, "stroke-width": 0.5 });

    // the drawing (not mirrored), as a separate layer above the photo
    var job = A.el(svg, "g", { opacity: 0 });
    var js = A.el(job, "g", { transform: "scale(" + K + ")" });
    A.el(js, "rect", { x: -BW / 2, y: -BH / 2, width: BW, height: BH, fill: "none", stroke: C.live, "stroke-width": 0.35, "stroke-dasharray": "1.4 1" });
    A.el(js, "text", { x: 0, y: -5, "font-size": 7, "font-weight": 700, fill: "none", stroke: C.live, "stroke-width": 0.25, "font-family": "sans-serif" }, "SRM");
    A.el(js, "rect", { x: -9, y: 5, width: 8, height: 5, fill: "none", stroke: C.live, "stroke-width": 0.4 });
    HOLES.forEach(function (h) { A.el(js, "circle", { cx: h[0], cy: h[1], r: 1.6, fill: "none", stroke: C.live, "stroke-width": 0.3 }); });
    var cross = A.el(svg, "g", { opacity: 0, transform: "translate(" + (CX + 5 * K) + " " + (CY + 2 * K) + ")" });
    A.el(cross, "circle", { r: 9, fill: "none", stroke: C.ok, "stroke-width": 2 });
    A.el(cross, "line", { x1: -13, y1: 0, x2: 13, y2: 0, stroke: C.ok, "stroke-width": 2 });
    A.el(cross, "line", { x1: 0, y1: -13, x2: 0, y2: 13, stroke: C.ok, "stroke-width": 2 });

    // side view
    A.text(svg, CX, SY - 26, "edge-on", { size: 12, anchor: "middle", fill: C.text3 });
    var side = A.el(svg, "g", { transform: "translate(" + CX + " " + SY + ")" });
    var sideFlip = A.el(side, "g");
    var L = SWm * K / 2;
    A.el(sideFlip, "rect", { x: -L, y: -6, width: 2 * L, height: 12, fill: C.fr4 });
    A.el(sideFlip, "rect", { x: -L, y: -9, width: 2 * L, height: 3, fill: C.copperHi });          // copper (B)
    var sInk = A.el(sideFlip, "rect", { x: -BW * K / 2, y: -13, width: BW * K, height: 4, fill: "#2f9a5d" });
    var sTape = A.el(sideFlip, "rect", { x: -BW * K / 2 - 18, y: 6, width: BW * K + 36, height: 3, fill: "#d39a2a" });
    var sSilk = A.el(sideFlip, "rect", { x: -60, y: 6, width: 80, height: 2, fill: C.text, opacity: 0 });
    A.text(side, L + 12, 4, "", { size: 12, fill: C.text3 });

    // steps list
    var PX = narrow ? 20 : 560, PY = narrow ? SY + 50 : 60;
    var rows = STEPS.map(function (s, i) {
      var y = PY + i * 32;
      var dot = A.el(svg, "circle", { cx: PX + 9, cy: y + 6, r: 9, fill: "none", stroke: C.ruleStrong, "stroke-width": 1.5 });
      var num = A.text(svg, PX + 9, y + 10.5, String(i + 1), { size: 11, weight: 700, anchor: "middle", fill: C.text3, font: "mono" });
      var t = A.text(svg, PX + 28, y + 11, s[0], { size: 15, weight: 600, fill: C.text3 });
      return { dot: dot, num: num, t: t };
    });

    var row = A.controls(host);
    var step = 0, flipT = -1, anim = -1, from = -1;
    var playBtn;
    A.button(row, "← Back", function () { go(Math.max(0, step - 1)); });
    A.button(row, "Next →", function () { go(Math.min(STEPS.length - 1, step + 1)); }, "primary");
    var st = A.status(row);

    function go(i) {
      var was = step; step = i;
      var target = step >= 2 ? 1 : -1;
      if ((was >= 2) !== (step >= 2)) { from = flipT; anim = 0; tgt = target; } else { flipT = target; }
      draw();
    }
    var tgt = -1;
    function draw() {
      var lam = flipT > 0;                       // laminate up (KiCad's view)
      A.set(flipG, { transform: "scale(" + flipT + " 1)" });
      A.set(sideFlip, { transform: "scale(" + (-flipT) + " " + (lam ? -1 : 1) + ")" });
      A.set(sheetR, { fill: lam ? C.fr4 : C.copper });
      A.set(faceR, { fill: lam ? C.fr4Hi : "#1f5a35" });
      A.set(tapeR, { opacity: !lam && step === 0 ? 0.0 : 0 });
      A.set(sTape, { opacity: step === 0 ? 1 : 0 });
      A.set(sSilk, { opacity: step >= 6 ? 1 : 0 });
      A.set(marked, { opacity: step >= 6 ? 1 : 0 });
      var jx = step >= 5 ? 0 : 14, jy = step >= 5 ? 0 : 9, jr = step >= 5 ? 0 : 4;
      A.set(job, { opacity: step >= 3 ? 1 : 0, transform: "translate(" + (CX + jx * K) + " " + (CY + jy * K) + ") rotate(" + jr + ")" });
      A.set(cross, { opacity: step >= 4 ? 1 : 0 });
      rows.forEach(function (r, i) {
        var done = i < step, cur = i === step;
        A.set(r.dot, { fill: done ? C.ok : "none", stroke: done ? C.ok : cur ? C.live : C.ruleStrong });
        A.set(r.num, { fill: done ? C.ink : cur ? C.live : C.text3 });
        A.set(r.t, { fill: cur ? C.text : done ? C.text2 : C.text3 });
      });
      st.className = "anim-status" + (step === STEPS.length - 1 ? " ok" : "");
      st.textContent = (step + 1) + " · " + STEPS[step][0] + ": " + STEPS[step][1];
    }
    A.loop(host, function (t, dt) {
      if (anim < 0) return;
      anim += dt;
      var p = A.ease(anim / 1.1);
      flipT = A.lerp(from, tgt, p);
      if (Math.abs(flipT) < 0.02) flipT = flipT < 0 ? -0.02 : 0.02;
      if (p >= 1) { flipT = tgt; anim = -1; }
      draw();
    }, 0);
    var m = /[?&]skstep=(\d)/.exec(location.search);
    if (m) { step = Math.min(STEPS.length - 1, +m[1] - 1); flipT = step >= 2 ? 1 : -1; }
    draw();
  });
})();
