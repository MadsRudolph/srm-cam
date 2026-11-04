/* Curing under the big UV lamp in the student lab, then the scrape test on a scrap board.
   UV reaches the top of the ink first, so a channel, where the ink is deepest, is the last
   place to harden. There is deliberately no cure time here: the scrape is what says when
   it is done. Schematic, not to scale. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C, B = window.SMBoard;

  A.define("sm-cure", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 730 : 400;
    var svg = A.stage(host, W, H, "A board curing under the big UV lamp, then a scraper testing the ink in a channel on a scrap board");

    // -- the lamp -------------------------------------------------------
    var PW = narrow ? W - 40 : 460, PX = 20, PY = 44;
    A.text(svg, PX, 30, "UNDER THE BIG UV LAMP · STUDENT LAB", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: PX, y: PY, width: PW, height: 300, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.el(svg, "rect", { x: PX + 50, y: PY + 20, width: PW - 100, height: 42, rx: 4, fill: C.raised, stroke: C.ruleStrong });
    A.el(svg, "rect", { x: PX + 62, y: PY + 56, width: PW - 124, height: 8, fill: B.UV });
    A.text(svg, PX + PW / 2, PY + 47, "the big UV lamp", { size: 16, weight: 600, anchor: "middle", fill: C.text });
    var rays = [];
    for (var i = 0; i < 7; i++) {
      var rx = PX + 80 + (PW - 160) * i / 6;
      rays.push(A.el(svg, "line", { x1: rx, y1: PY + 72, x2: rx, y2: PY + 212, stroke: B.UV, "stroke-width": 2.5, "stroke-dasharray": "10 12" }));
    }
    var boardTop = PY + 216;
    A.el(svg, "rect", { x: PX + 90, y: boardTop + 10, width: PW - 180, height: 16, fill: C.fr4 });
    var ink = A.el(svg, "rect", { x: PX + 90, y: boardTop, width: PW - 180, height: 12, fill: B.INK_WET });
    var lampWord = A.text(svg, PX + PW / 2, boardTop + 58, "", { size: 16, weight: 600, anchor: "middle" });

    // -- the scrape -----------------------------------------------------
    var SX = narrow ? 20 : 500, SY = narrow ? 386 : 44, SW = narrow ? W - 40 : W - 520;
    A.text(svg, SX, SY - 14, "SCRAP BOARD · ONE CHANNEL, ZOOMED", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: SX, y: SY, width: SW, height: 300, rx: 4, fill: C.panel, stroke: C.ruleHi });
    var cu = SY + 150, chL = SX + SW / 2 - 50, chW = 100, chD = 88;
    A.el(svg, "rect", { x: SX + 1, y: cu + 40, width: SW - 2, height: 96, fill: C.fr4 });
    A.el(svg, "rect", { x: SX + 1, y: cu, width: SW - 2, height: 40, fill: C.copper });
    A.el(svg, "rect", { x: chL, y: cu, width: chW, height: chD, fill: C.fr4Hi });
    A.el(svg, "rect", { x: SX + 1, y: cu - 22, width: SW - 2, height: 22, fill: B.INK });
    var chHard = A.el(svg, "rect", { x: chL, y: cu - 22, width: chW, fill: B.INK });
    var chWet = A.el(svg, "rect", { x: chL, width: chW, fill: B.INK_WET });
    A.text(svg, chL + chW + 8, cu + 26, "copper", { size: 15, fill: "#3a2108", weight: 600 });
    A.text(svg, SX + SW - 12, cu + 118, "FR-4", { size: 15, fill: "#2a2612", weight: 600, anchor: "end" });
    var smear = A.el(svg, "path", { fill: B.INK_WET });
    var tool = A.el(svg, "g", {});
    A.el(tool, "polygon", { points: "0,0 26,-18 60,-92 40,-100", fill: C.steelDim, stroke: C.steel });
    var word = A.text(svg, SX + 14, SY + 30, "", { size: 16, weight: 700 });

    var verdict = A.text(svg, 20, H - 18, "", { size: narrow ? 15 : 18, weight: 700 });
    var cured = true;
    var GO = 2.6, END = 5.0;

    function draw(t) {
      var c = A.clamp(t / GO, 0, 1);
      var under = t < GO;
      rays.forEach(function (r) { A.set(r, { "stroke-dashoffset": -t * 44, opacity: under ? 0.9 : 0.15 }); });
      ink.setAttribute("fill", B.mix(B.INK_WET, B.INK, c));
      lampWord.textContent = under ? "curing…" : "out from under the lamp";
      lampWord.setAttribute("fill", under ? B.UV : C.text2);
      // hard from the top down: all the way, or part of the way
      var reach = (cured ? 1 : 0.42) * c;
      var hard = 22 + chD * reach;
      A.set(chHard, { height: hard });
      A.set(chWet, { y: cu - 22 + hard, height: Math.max(chD + 22 - hard, 0) });

      var k = A.clamp((t - GO) / (END - GO), 0, 1);
      var x = A.lerp(SX + 16, chL + chW / 2, k), y;
      if (cured) {
        y = cu - 24;                                   // skids over the hard ink
      } else {
        y = cu - 24 + (k > 0.55 ? A.ease((k - 0.55) / 0.3) * (hard + 30) : 0);  // digs into the soft
      }
      A.set(tool, { transform: "translate(" + x + "," + y + ")", opacity: t < GO ? 0 : 1 });
      smear.setAttribute("d", !cured && k > 0.85
        ? "M" + (chL + 16) + " " + (cu - 22) + " q 34 -44 74 -8 q -30 -6 -40 8 Z" : "");
      word.textContent = k < 0.85 ? "" : cured ? "skids: hard to the bottom" : "digs in: still soft below";
      word.setAttribute("fill", cured ? C.ok : C.danger);
      verdict.textContent = t < END ? "" : cured
        ? "Cured. This is your lamp time: give the real board the same."
        : (narrow ? "Back under the lamp, then scrape another channel." : "Not yet. Back under the lamp for longer, then scrape another channel.");
      verdict.setAttribute("fill", cured ? C.ok : C.caution);
    }

    var play = B.player(host, END, draw);
    var row = A.controls(host);
    A.segmented(row, [[true, "Cured all the way down"], [false, "Hard on top, soft below"]], true, function (v) {
      cured = v;
      if (A.reduced) draw(END);
      play.replay();
    });
    A.button(row, "Play again", function () { play.replay(); }, "primary");
  });
})();
