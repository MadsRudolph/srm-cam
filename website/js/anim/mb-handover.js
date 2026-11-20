/* The hand-over: the sheet from the mill on the laser's bed (make-a-board.html#handover).
   To scale: the 220 mm field the laser page draws, its middle at (110, 110), and the
   72 x 52 mm sheet with the 50 x 34 mm board of mb-sheet.js, still on its tabs.

   The real numbers:
   - Calibrate looks for the board over the whole field (gui2/laser_autocal.py
     WIDE_SEARCH_MM = 105 either way of the middle) in each quarter turn, and within
     WIDE_MAX_TURN = 4 degrees of it; below 75 % of the holes matched (DRILLED_NEED)
     it stops with "The board was not found on the bed: at best a of b holes matched."
   - find_board does not try the mirror image: a sheet laid laminate up shows its hole
     pattern mirrored, so it is usually not found; a symmetric pattern can still match,
     and then only the photo (pale laminate, not copper) tells you.
   - Trenches further than 45 mm from the middle get 10 more passes (engine/xtool.py
     EDGE_RADIUS_MM, EDGE_PASSES); the field test cleared nothing past about 57 mm. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BED = 220, MID = 110, EDGE = 45, FIELD = 57;
  var SW = 72, SH = 52, BW = 50, BH = 34;
  var HOLES = [[3, 17], [25, 31.2], [47, 12], [3, 4], [3, 30], [47, 30], [47, 4], [12, 8], [15, 8],
    [18, 8], [21, 8], [30, 20], [33, 20], [36, 20], [39, 20]];

  var STATES = {
    ok: { label: "Right", short: "Right", c: [MID, MID], turn: 0, up: true },
    flip: { label: "Upside down", short: "Flipped", c: [MID, MID], turn: 0, up: false },
    skew: { label: "Not square", short: "Skewed", c: [MID, MID], turn: 10, up: true },
    edge: { label: "Near the edge", short: "Edge", c: [MID + 62, MID - 42], turn: 0, up: true }
  };

  A.define("mb-handover", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 930 : 470;
    var svg = A.stage(host, W, H, "To scale: the laser's 220 mm bed from above with the sheet from the mill on it, and a side view showing which face is up");
    var S = narrow ? 470 : 400, X0 = narrow ? 25 : 24, Y0 = 50, K = S / BED;
    A.text(svg, X0, 30, "THE LASER BED, 220 × 220 MM · TO SCALE", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: X0, y: Y0, width: S, height: S, fill: C.sunk, stroke: C.ruleStrong });
    for (var gd = 20; gd < BED; gd += 20) {
      A.el(svg, "line", { x1: X0 + gd * K, y1: Y0, x2: X0 + gd * K, y2: Y0 + S, stroke: C.rule });
      A.el(svg, "line", { x1: X0, y1: Y0 + gd * K, x2: X0 + S, y2: Y0 + gd * K, stroke: C.rule });
    }
    var cx = X0 + MID * K, cy = Y0 + MID * K;
    A.el(svg, "circle", { cx: cx, cy: cy, r: EDGE * K, fill: C.okFill, "fill-opacity": 0.6, stroke: C.ok, "stroke-opacity": 0.5 });
    A.el(svg, "circle", { cx: cx, cy: cy, r: FIELD * K, fill: "none", stroke: C.caution, "stroke-dasharray": "5 5", "stroke-opacity": 0.7 });
    A.text(svg, cx, cy - EDGE * K + 16, "45 mm", { size: 12, anchor: "middle", fill: C.ok });
    A.text(svg, cx, cy - FIELD * K - 6, "57 mm", { size: 12, anchor: "middle", fill: C.caution });

    var sheetG = A.el(svg, "g", {});

    // side view (schematic): laser head, beam, the sheet's two faces
    var sx = narrow ? 25 : 460, sy = narrow ? Y0 + S + 34 : 58, sw = narrow ? 470 : 396;
    A.text(svg, sx, sy, "SIDE VIEW · SCHEMATIC", { size: 13, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var head = A.el(svg, "rect", { x: sx + sw / 2 - 30, y: sy + 12, width: 60, height: 26, rx: 4, fill: C.raised, stroke: C.ruleStrong });
    A.text(svg, sx + sw / 2, sy + 30, "laser", { size: 12, anchor: "middle", fill: C.text2 });
    A.el(svg, "line", { x1: sx + sw / 2, y1: sy + 38, x2: sx + sw / 2, y2: sy + 76, stroke: C.danger, "stroke-width": 2, "stroke-dasharray": "4 3" });
    var layTop = A.el(svg, "rect", { x: sx + 20, y: sy + 78, width: sw - 40, height: 6 });
    var layMid = A.el(svg, "rect", { x: sx + 20, y: sy + 84, width: sw - 40, height: 22, fill: C.fr4 });
    var layBot = A.el(svg, "rect", { x: sx + 20, y: sy + 106, width: sw - 40, height: 6 });
    [0.3, 0.55, 0.8].forEach(function (f) {
      A.el(svg, "rect", { x: sx + 20 + f * (sw - 40) - 3, y: sy + 78, width: 6, height: 34, fill: C.sunk });
    });
    A.el(svg, "rect", { x: sx, y: sy + 112, width: sw, height: 8, fill: C.panelHi });
    var topLbl = A.text(svg, sx + 20, sy + 70, "", { size: 12.5, fill: C.text2 });

    var vy = sy + 150;
    var verdictBox = A.el(svg, "rect", { x: sx - 6, y: vy - 24, width: sw + 12, height: 40, rx: 6 });
    var verdict = A.text(svg, sx + 4, vy + 2, "", { size: narrow ? 17 : 15, weight: 600 });
    var lines = [];
    for (var i = 0; i < 6; i++) lines.push(A.text(svg, sx + 4, vy + 42 + i * (narrow ? 27 : 24), "", { size: narrow ? 16 : 14, fill: C.text2 }));

    function draw(st) {
      var s = STATES[st];
      while (sheetG.firstChild) sheetG.removeChild(sheetG.firstChild);
      var px = X0 + s.c[0] * K, py = Y0 + s.c[1] * K;
      var g = A.el(sheetG, "g", { transform: "translate(" + px + "," + py + ") rotate(" + s.turn + ")" });
      var face = s.up ? C.copper : C.fr4Hi, waste = s.up ? C.copperDim : C.fr4;
      A.el(g, "rect", { x: -SW / 2 * K, y: -SH / 2 * K, width: SW * K, height: SH * K, fill: waste, stroke: s.up ? C.copper : C.fr4Hi });
      // the 0.8 mm channel round the board, tabs left standing
      A.el(g, "rect", { x: (-BW / 2 - 0.4) * K, y: (-BH / 2 - 0.4) * K, width: (BW + 0.8) * K, height: (BH + 0.8) * K, fill: "none", stroke: C.ink, "stroke-width": Math.max(0.8 * K, 1.4) });
      A.el(g, "rect", { x: -BW / 2 * K, y: -BH / 2 * K, width: BW * K, height: BH * K, fill: face });
      HOLES.forEach(function (h) {
        var x = s.up ? h[0] : BW - h[0];           // turned over: the pattern is mirrored
        A.el(g, "circle", { cx: (x - BW / 2) * K, cy: (h[1] - BH / 2) * K, r: Math.max(0.4 * K, 1.1), fill: C.ink });
      });
      // the board's middle and its distance from the bed's middle
      var d = Math.hypot(s.c[0] - MID, s.c[1] - MID);
      if (d > 1) {
        A.el(sheetG, "line", { x1: cx, y1: cy, x2: px, y2: py, stroke: C.caution, "stroke-width": 1.5, "stroke-dasharray": "3 3" });
      }
      A.el(sheetG, "circle", { cx: cx, cy: cy, r: 3, fill: C.text3 });

      A.set(layTop, { fill: s.up ? C.copper : C.fr4Hi });
      A.set(layBot, { fill: s.up ? C.fr4 : C.copper });
      A.set(layMid, { fill: C.fr4 });
      topLbl.textContent = s.up ? "copper face up" : "laminate up: copper underneath";

      var tone, v, L;
      if (st === "ok") {
        tone = "ok"; v = "Copper up, square, board near the middle";
        L = ["As it came off the mill, not turned over.", "Sheet edge along the bed's edge.",
          "Every trench inside the green 45 mm circle:", "the recipe's own passes, nothing extra.",
          "Calibrate finds it by its holes and locks on."];
      } else if (st === "flip") {
        tone = "danger"; v = "Upside down: the holes are mirrored";
        L = ["Calibrate does not try the mirror image.", "Usually it stops: “The board was not found",
          "on the bed: at best … holes matched.”", "A symmetric board may still match: then the",
          "photo shows pale laminate, not copper.", "Turn the sheet over and Calibrate again."];
      } else if (st === "skew") {
        tone = "caution"; v = "Turned 10°: square it to the bed";
        L = ["Calibrate looks for the board in each", "quarter turn, within 4° of it.",
          "At 10° the holes do not match, and it", "stops: “The board was not found on the bed”.",
          "Line the sheet's edge up with the bed's."];
      } else {
        tone = "caution"; v = "Board " + Math.round(d) + " mm from the middle";
        L = ["Calibrate still finds it (it looks over", "the whole bed), but the field is weaker here:",
          "trenches past 45 mm get 10 more passes,", "and past about 57 mm the field test",
          "cleared nothing. Move it to the middle."];
      }
      var col = { ok: [C.ok, C.okFill], caution: [C.caution, C.cautionFill], danger: [C.danger, C.dangerFill] }[tone];
      verdict.textContent = v;
      A.set(verdict, { fill: col[0] }); A.set(verdictBox, { fill: col[1], stroke: col[0] });
      lines.forEach(function (t, i) { t.textContent = L[i] || ""; });
    }

    var row = A.controls(host);
    A.segmented(row, Object.keys(STATES).map(function (k) {
      return [k, narrow ? STATES[k].short : STATES[k].label];
    }), "ok", draw);
  });
})();
