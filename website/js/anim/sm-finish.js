/* Finishing: the tape comes off the laminate side, and a pin vise, from the copper side,
   clears the ink out of the hole. A cross-section, not to scale. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C, B = window.SMBoard;

  A.define("sm-finish", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = 330;
    var svg = A.stage(host, W, H, "Kapton tape peeled from the laminate side, then a pin vise clearing the ink from a hole, from the copper side");
    var L = 40, R = W - 40, TOP = 190, CU = 9, FR = 52, HX = W / 2 - 16, HW = 32, BOT = TOP + CU + FR;
    A.text(svg, L, 30, "CROSS-SECTION · COPPER SIDE UP · NOT TO SCALE", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });

    A.el(svg, "rect", { x: L, y: TOP + CU, width: R - L, height: FR, fill: C.fr4 });
    A.el(svg, "rect", { x: L, y: TOP, width: R - L, height: CU, fill: C.copper });
    A.el(svg, "rect", { x: L, y: TOP - 7, width: R - L, height: 7, fill: B.INK });
    A.el(svg, "rect", { x: HX, y: TOP - 7, width: HW, height: CU + FR + 7, fill: C.sunk });
    var plug = A.el(svg, "rect", { x: HX, y: TOP - 7, width: HW, fill: B.INK });
    var tape = A.el(svg, "path", { fill: "none", stroke: C.caution, "stroke-width": 6 });
    var tapeT = A.text(svg, L, BOT + 30, "Kapton", { size: 15, weight: 600, fill: C.caution });

    var vise = A.el(svg, "g", {});
    A.el(vise, "rect", { x: -4, y: -92, width: 8, height: 92, fill: C.steel });
    A.el(vise, "rect", { x: -16, y: -146, width: 32, height: 56, rx: 3, fill: C.raised, stroke: C.ruleStrong });
    var spin = A.el(vise, "line", { x1: -10, x2: 10, y1: -118, y2: -118, stroke: C.text2, "stroke-width": 2 });
    A.text(vise, 26, -118, "pin vise", { size: 15, fill: C.text2 });

    var line = A.text(svg, L, H - 14, "", { size: narrow ? 15 : 17, weight: 700 });
    var PEEL = 1.6, DRILL = 3.6;

    function draw(t) {
      // the tape lifts from the right, along the board's underside
      var p = A.ease(t / PEEL), lift = A.lerp(R, L, p);
      tape.setAttribute("d", "M" + L + " " + (BOT + 3) + " L" + lift + " " + (BOT + 3)
        + " Q" + (lift + 40) + " " + (BOT + 5) + " " + (lift + 60 + 60 * p) + " " + (BOT + 42));
      tape.setAttribute("opacity", p >= 1 ? 0 : 1);
      tapeT.setAttribute("opacity", p >= 1 ? 0 : 1);

      var d = A.clamp((t - PEEL - 0.2) / (DRILL - PEEL - 0.2), 0, 1);
      var tip = TOP - 40 + (CU + FR + 56) * d;
      A.set(vise, { transform: "translate(" + (W / 2) + "," + tip + ")", opacity: t < PEEL ? 0.25 : 1 });
      spin.setAttribute("transform", "rotate(" + (t * 300) + " 0 -118)");
      var left = Math.max(CU + FR + 7 - (CU + FR + 56) * d, 0);
      A.set(plug, { y: BOT - left, height: left });

      var done = t >= DRILL;
      line.textContent = t < PEEL ? "Wipe with IPA, then peel the tape."
        : !done ? "Clear each hole with the pin vise, from the copper side."
        : (narrow ? "Holes clear. Check continuity, and tin a few pads." : "Holes clear. Check continuity, and tin a few pads to see them take solder.");
      line.setAttribute("fill", done ? C.ok : C.text);
    }
    var play = B.player(host, DRILL + 0.2, draw);
    var row = A.controls(host);
    A.button(row, "Play again", function () { play.replay(); }, "primary");
  });
})();
