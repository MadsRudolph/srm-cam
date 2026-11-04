/* Why the laminate side gets Kapton tape. A cross-section, copper side up: the ink runs
   over the copper, into a channel and down a drilled hole. With tape it stops there; with
   no tape it comes out underneath and sets on the back. Not to scale. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C, B = window.SMBoard;

  A.define("sm-tape", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = 310;
    var svg = A.stage(host, W, H, "A cross-section of the board with ink running over the copper and down a drilled hole, stopped by Kapton tape on the laminate side");
    var L = 30, R = W - 30, TOP = 124, CU = 10, FR = 62;          // copper top, thicknesses
    var CH = L + (R - L) * 0.28, HOLE = L + (R - L) * 0.66;       // channel and hole, left edges
    var CHW = 24, HW = 34;
    var FRY = TOP + CU, BOT = FRY + FR;

    A.text(svg, L, 30, "CROSS-SECTION · COPPER SIDE UP · NOT TO SCALE", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    // the board, with the channel through the copper and the hole through it all
    A.el(svg, "rect", { x: L, y: FRY, width: R - L, height: FR, fill: C.fr4 });
    A.el(svg, "rect", { x: L, y: TOP, width: R - L, height: CU, fill: C.copper });
    A.el(svg, "rect", { x: CH, y: TOP, width: CHW, height: CU + 4, fill: C.fr4Hi });
    A.el(svg, "rect", { x: HOLE, y: TOP, width: HW, height: CU + FR, fill: C.sunk });

    var coat = A.el(svg, "rect", { x: L, y: TOP - 14, height: 14, fill: B.INK_WET });
    var inCh = A.el(svg, "rect", { x: CH, y: TOP, width: CHW, height: 0, fill: B.INK_WET });
    var inHole = A.el(svg, "rect", { x: HOLE, y: TOP, width: HW, height: 0, fill: B.INK_WET });
    var blob = A.el(svg, "path", { fill: B.INK_WET });
    var tape = A.el(svg, "rect", { x: L, y: BOT, width: R - L, height: 7, fill: C.caution, opacity: 0.85 });

    A.text(svg, R - 4, FRY + 38, "FR-4", { size: 16, weight: 600, anchor: "end", fill: "#2a2612" });
    A.text(svg, L, TOP - 24, "ink", { size: 16, fill: B.INK_WET, weight: 600 });
    A.text(svg, CH + CHW / 2, TOP - 24, "channel", { size: 15, fill: C.text2, anchor: "middle" });
    A.text(svg, HOLE + HW / 2, TOP - 24, "drilled hole", { size: 15, fill: C.text2, anchor: "middle" });
    var tapeLabel = A.text(svg, L, BOT + 28, "Kapton tape on the laminate side", { size: 16, fill: C.caution, weight: 600 });
    var verdict = A.text(svg, L, H - 22, "", { size: narrow ? 16 : 18, weight: 700 });

    var taped = true;
    function draw(t) {
      var run = A.ease(t / 2.2), x = A.lerp(L, R, run);
      A.set(coat, { width: x - L });
      A.set(inCh, { height: x > CH + CHW ? CU + 4 : 0 });
      var fall = A.clamp((t - 1.1) / 1.2, 0, 1);
      var reach = (x > HOLE ? fall : 0) * (CU + FR);
      A.set(inHole, { height: reach });
      A.set(tape, { opacity: taped ? 0.85 : 0 });
      tapeLabel.setAttribute("opacity", taped ? 1 : 0);
      var drip = taped ? 0 : A.clamp((t - 2.3) / 1.2, 0, 1);
      var cx = HOLE + HW / 2;
      blob.setAttribute("d", drip ? "M" + (cx - HW / 2 - drip * 26) + " " + BOT + " Q" + cx + " " + (BOT + 62 * drip) + " " + (cx + HW / 2 + drip * 26) + " " + BOT + " Z" : "");
      var end = t >= 3.4;
      verdict.textContent = !end ? "" : taped
        ? (narrow ? "The tape stops it. A pin vise clears the hole later."
                  : "The tape stops it. The ink in the hole comes out with a pin vise at the end.")
        : (narrow ? "No tape: the ink sets on the back of the board."
                  : "No tape: the ink comes through and sets on the back of the board.");
      verdict.setAttribute("fill", taped ? C.ok : C.danger);
    }
    var play = B.player(host, 3.5, draw);
    var row = A.controls(host);
    A.segmented(row, [[true, "Kapton on the laminate side"], [false, "No tape"]], true, function (v) {
      taped = v;
      if (A.reduced) draw(3.5);
      play.replay();
    });
    A.button(row, "Play again", function () { play.replay(); }, "primary");
  });
})();
