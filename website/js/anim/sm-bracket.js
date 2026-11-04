/* Locating the board, the first time. A milled blank goes into the corner of the bracket,
   the outline is scored at low power, and X and Y are adjusted until the score lands on
   the board's edges. Those numbers are noted and reused, for as long as the bracket stays
   screwed down. Top view; the numbers are an example, yours will differ. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C, B = window.SMBoard;
  var OFF_X = 3.4, OFF_Y = -2.6;                 // how far the first score misses, mm

  A.define("sm-bracket", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 560 : 440;
    var svg = A.stage(host, W, H, "A board pushed into the corner of the bracket, and the laser's scored outline adjusted until it lands on the board's edges");
    var K = narrow ? 7 : 6.2, OX = narrow ? 56 : 66, BOTTOM = narrow ? 382 : 362;
    function sx(x) { return OX + x * K; }
    function sy(y) { return BOTTOM - y * K; }
    A.text(svg, 20, 30, "TOP VIEW · THE LASER BED", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });

    // the bracket, a corner the board is pushed into
    var T = 16;
    A.el(svg, "polygon", {
      points: [[sx(0) - T, sy(40)], [sx(0), sy(40)], [sx(0), sy(0)], [sx(40), sy(0)], [sx(40), sy(0) + T], [sx(0) - T, sy(0) + T]].map(String).join(" "),
      fill: C.raised, stroke: C.ruleStrong
    });
    A.text(svg, sx(14), sy(0) + T + 20, "the printed bracket", { size: 15, fill: C.text2 });

    var board = A.el(svg, "g", {});
    A.el(board, "rect", { x: sx(0), y: sy(B.H), width: B.W * K, height: B.H * K, fill: C.copper, stroke: C.copperHi });
    B.PADS.forEach(function (p) { B.pad(board, p, sx, sy, K, { fill: C.copperDim }); });

    var ar1 = A.arrow(svg, sx(B.W) + 52, sy(B.H) - 18, sx(B.W) + 18, sy(B.H) + 2, { color: C.text, width: 2.5, head: 11 });

    var score = A.el(svg, "rect", { width: B.W * K, height: B.H * K, fill: "none", stroke: C.live, "stroke-width": 2.5, "stroke-dasharray": 2 * (B.W + B.H) * K });
    var RX = narrow ? 20 : sx(B.W) + 58, RY = narrow ? 436 : 92, RW = narrow ? W - 40 : W - RX - 18;
    A.el(svg, "rect", { x: RX, y: RY, width: RW, height: narrow ? 66 : 112, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(svg, RX + 14, RY + 24, "JOB POSITION · EXAMPLE", { size: 13, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var xT = A.text(svg, RX + 14, RY + (narrow ? 52 : 60), "", { size: 20, weight: 600, font: "mono" });
    var yT = A.text(svg, RX + (narrow ? 170 : 14), RY + (narrow ? 52 : 92), "", { size: 20, weight: 600, font: "mono" });

    var line = A.text(svg, 20, H - 18, "", { size: narrow ? 15 : 17, weight: 700 });
    var X0 = 80.0, Y0 = 60.0;

    function draw(t) {
      var slide = A.ease(t / 1.1);
      board.setAttribute("transform", "translate(" + A.lerp(34, 0, slide) + "," + A.lerp(-26, 0, slide) + ")");
      ar1.setAttribute("opacity", t < 1.1 ? 1 : 0);
      var ex = OFF_X * (1 - A.ease((t - 3.2) / 1)), ey = OFF_Y * (1 - A.ease((t - 4.4) / 1));
      var drawn = A.clamp((t - 1.4) / 1.5, 0, 1);
      var per = 2 * (B.W + B.H) * K;
      A.set(score, { x: sx(ex), y: sy(B.H + ey), "stroke-dashoffset": per * (1 - drawn), opacity: t < 1.4 ? 0 : 1 });
      xT.textContent = "X " + (X0 + OFF_X - (OFF_X - ex)).toFixed(2);
      yT.textContent = "Y " + (Y0 + OFF_Y - (OFF_Y - ey)).toFixed(2);
      var done = t >= 5.4;
      A.set(score, { stroke: done ? C.ok : C.live });
      xT.setAttribute("fill", done ? C.ok : C.text);
      yT.setAttribute("fill", done ? C.ok : C.text);
      line.textContent = t < 1.4 ? "Push a milled blank into the corner, and let go gently."
        : t < 3.2 ? "Score the outline at low power: the first try misses."
        : t < 5.4 ? "Adjust X, then Y, and score again, until it lands on the edges."
        : (narrow ? "On the edges. Note X and Y, and reuse them." : "On the edges. Note X and Y, and reuse them while the bracket stays put.");
      line.setAttribute("fill", done ? C.ok : C.text);
    }
    var play = B.player(host, 5.8, draw);
    var row = A.controls(host);
    A.button(row, "Play again", function () { play.replay(); }, "primary");
  });
})();
