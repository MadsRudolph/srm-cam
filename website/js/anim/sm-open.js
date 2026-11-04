/* Opening the rest: six passes of the RemoveSolderMask preset, cross-hatched, so each pass
   runs at right angles to the last. The ink goes from whole to hazy to bare copper. One pad
   comes out hazy on purpose: that is what the look before taking the board out is for,
   and running it again costs nothing while the board has not moved. Sped up a lot. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C, B = window.SMBoard;
  var PASSES = 6, PASS_S = 0.75;

  A.define("sm-open", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 610 : 430;
    var svg = A.stage(host, W, H, "The laser sweeping back and forth over the board in six crossed passes, the ink clearing from each pad to bare copper");
    var K = narrow ? 8.8 : 7.6, OX = narrow ? 22 : 22, OY = 42;
    function sx(x) { return OX + x * K; }
    function sy(y) { return OY + (B.H - y) * K; }
    var PW = B.W * K, PH = B.H * K;
    A.text(svg, OX, 28, "COPPER SIDE UP · SPED UP", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: sx(0), y: sy(B.H), width: PW, height: PH, fill: B.INK, stroke: C.ruleStrong });
    // one pad stays hazy: not in the check set, and easy to see
    var HAZY = B.PADS.indexOf(B.PADS.filter(function (p) { return p[0] === 16 && p[1] === 35.5; })[0]);
    var rects = B.PADS.map(function (p) { return B.pad(svg, p, sx, sy, K, { fill: B.UNDER }); });
    var sweep = A.el(svg, "line", { stroke: "#ff5a3c", "stroke-width": 2.5, opacity: 0 });
    var ring = A.el(svg, "circle", { cx: sx(B.PADS[HAZY][0]), cy: sy(B.PADS[HAZY][1]), r: 19, fill: "none", stroke: C.caution, "stroke-width": 2.5, opacity: 0 });

    // the side panel: the pass, and the preset
    var RX = narrow ? 22 : sx(B.W) + 24, RY = narrow ? sy(0) + 16 : OY, RW = narrow ? W - 44 : W - RX - 18;
    A.el(svg, "rect", { x: RX, y: RY, width: RW, height: narrow ? 100 : PH, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(svg, RX + 14, RY + 26, "PASS", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var pass = A.text(svg, RX + 14, RY + 68, "", { size: 38, weight: 700, font: "mono" });
    var dir = A.text(svg, RX + (narrow ? 130 : 14), RY + (narrow ? 66 : 94), "", { size: 15, fill: C.text2 });
    var PRESET = ["RemoveSolderMask", "Fiber IR · 40 %", "800 mm/s · 6 passes", "300 lines/cm · 30 kHz", "uni-directional", "cross hatch"];
    if (!narrow) PRESET.forEach(function (s, i) {
      A.text(svg, RX + 14, RY + 140 + i * 24, s, { size: i ? 14 : 15, weight: i ? 500 : 700, fill: i ? C.text2 : C.text });
    });

    var line = A.text(svg, narrow ? 22 : 22, H - 18, "", { size: narrow ? 15 : 17, weight: 700 });
    var DUR = PASSES * PASS_S + 0.8;

    function draw(t) {
      var run = Math.min(t / PASS_S, PASSES);
      var n = Math.min(Math.floor(run), PASSES - 1), u = run - n;
      var across = n % 2 === 0;           // cross hatch: odd passes one way, even the other
      var live = run < PASSES;
      if (across) {
        var yy = sy(B.H) + PH * u;
        A.set(sweep, { x1: sx(0), x2: sx(B.W), y1: yy, y2: yy, opacity: live ? 1 : 0 });
      } else {
        var xx = sx(0) + PW * u;
        A.set(sweep, { y1: sy(B.H), y2: sy(0), x1: xx, x2: xx, opacity: live ? 1 : 0 });
      }
      rects.forEach(function (r, i) {
        var p = B.PADS[i];
        var hit = across ? (B.H - p[1]) / B.H < u : p[0] / B.W < u;
        var clear = (n + (hit ? 1 : 0)) / PASSES;
        if (i === HAZY) clear *= 0.55;
        var c = clear < 0.5 ? B.mix(B.UNDER, "#b09a68", clear * 2) : B.mix("#b09a68", C.copperHi, (clear - 0.5) * 2);
        r.setAttribute("fill", c);
      });
      pass.textContent = (Math.min(n + 1, PASSES)) + "/" + PASSES;
      pass.setAttribute("fill", live ? C.text : C.ok);
      dir.textContent = live ? (across ? "this way, then across" : "across, then back") : "done";
      var over = t >= PASSES * PASS_S + 0.2;
      ring.setAttribute("opacity", over ? 1 : 0);
      line.textContent = !over ? "The board does not move."
        : narrow ? "That pad is hazy: run it again, board in place."
        : "Before you take it out: that pad is hazy. Run it again, board still in place.";
      line.setAttribute("fill", over ? C.caution : C.text);
    }
    var play = B.player(host, DUR, draw);
    var row = A.controls(host);
    A.button(row, "Play again", function () { play.replay(); }, "primary");
    if (narrow) { var st = A.status(row); st.textContent = "RemoveSolderMask: Fiber IR, 40 %, 800 mm/s, 6 passes, 300 lines/cm, 30 kHz, uni-directional, cross hatch."; }
  });
})();
