/* Why the board stays in its sheet, and how much sheet it needs (make-a-board.html).
   Drawn to scale in millimetres. A 50 x 34 mm board on a 72 x 52 mm sheet, the
   lab's bracket at the back-right corner (top-right here: the drawing looks down on
   the bed with the back of the mill at the top).

   The real numbers:
   - corner placement (engine/bracket.py corner_place, engine/autorun.py
     PLACE_MARGIN_MM): 3.0 mm in from the bracket's side arm; on the back edge the
     board is pushed off the probe tongue (4.0 mm over the sheet, 2.5-26 mm from the
     corner, bit 0.5 mm clear of it, plus the 0.8 mm bit and 0.2 mm), so 5.5 mm;
   - the cut-out channel: 0.8 mm bit, four 1.5 mm tabs (one per side on a board
     this shape), at least 2 mm from a corner;
   - Calibrate's camera marks (gui2/xtool.py proof_in_waste): 1.5 mm squares from
     3.0 to 4.5 mm outside the outline, beside three far-apart holes; if any square
     would not be on sheet copper, all three go on the isolation round the holes
     instead (proof_on_isolation, within 2.5 mm of each hole). */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  var SW = 72, SH = 52, BW = 50, BH = 34;
  // holes the marks are made beside (board mm, y down), and a few others
  var KEY = [[3, 17], [25, 31.2], [47, 12]];
  var SIDE = ["left", "bottom", "right"];
  var OTHER = [[3, 4], [3, 30], [47, 30], [47, 4], [12, 8], [15, 8], [18, 8], [21, 8],
    [30, 20], [33, 20], [36, 20], [39, 20]];
  var STATES = {
    corner: { label: "Corner (as it opens)", at: [SW - 3 - BW, 5.5], sheet: true, cut: true },
    centre: { label: "Centre ticked", at: [(SW - BW) / 2, (SH - BH) / 2], sheet: true, cut: true },
    nocut: { label: "“No cut-out” ticked", at: [0, SH - BH], sheet: true, cut: false },
    out: { label: "Broken out", at: [(SW - BW) / 2, (SH - BH) / 2], sheet: false, cut: true }
  };

  function markCentre(i) {
    var h = KEY[i], s = SIDE[i];
    if (s === "left") return [-3.75, h[1]];
    if (s === "bottom") return [h[0], BH + 3.75];
    return [BW + 3.75, h[1]];
  }

  A.define("mb-sheet", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 720 : 440;
    var svg = A.stage(host, W, H, "To scale: a board on its sheet, the bracket at the back-right, the cut-out channel and tabs, and the lane 3.0 to 4.5 mm outside the outline where Calibrate puts its camera marks");
    var k = narrow ? 5.8 : 5.6;                         // px per mm
    var ox = narrow ? 18 : 30, oy = narrow ? 112 : 96;  // sheet's top-left
    function X(x) { return ox + x * k; }
    function Y(y) { return oy + y * k; }

    var title = A.text(svg, 16, 30, "", { size: narrow ? 19 : 18, weight: 700 });
    A.text(svg, W - 16, 28, "to scale · mm", { size: 13, anchor: "end", fill: C.text4, font: "label", spacing: "0.1em" });
    A.text(svg, X(0), oy - 8, "BACK ↑", { size: 12, fill: C.text3, font: "label", spacing: "0.12em" });

    var g = A.el(svg, "g", {});
    // side panel (desktop) or below (phone): the verdict and the numbers
    var px = narrow ? 18 : 530, py = narrow ? Y(SH) + 58 : 130;
    var verdictBox = A.el(svg, "rect", { x: px - 10, y: py - 26, width: narrow ? W - 26 : W - px + 2, height: 46, rx: 6, fill: C.okFill, stroke: C.ok });
    var verdict = A.text(svg, px, py + 4, "", { size: narrow ? 16 : 14, weight: 600, fill: C.ok });
    var lines = [];
    for (var i = 0; i < 7; i++) lines.push(A.text(svg, px, py + 50 + i * (narrow ? 27 : 25), "", { size: narrow ? 16.5 : 14, fill: C.text2 }));

    function draw(st) {
      while (g.firstChild) g.removeChild(g.firstChild);
      var s = STATES[st], bx = s.at[0], by = s.at[1];
      function bX(x) { return X(bx + x); }
      function bY(y) { return Y(by + y); }
      if (s.sheet) {
        A.el(g, "rect", { x: X(0), y: Y(0), width: SW * k, height: SH * k, fill: C.copperDim, stroke: C.copper, "stroke-width": 1 });
        // the bracket: bar 10 mm outside the back and right edges, tongue over the sheet
        var bw = 10 * k;
        A.el(g, "path", { d: "M" + X(SW - 61 + 10) + " " + (Y(0) - bw) + " H" + (X(SW) + bw) + " V" + Y(61 - 10) + " H" + X(SW) + " V" + Y(0) + " H" + X(SW - 61 + 10) + " Z", fill: C.fr4, opacity: 0.85 });
        A.el(g, "rect", { x: X(SW - 26), y: Y(0), width: (26 - 2.5) * k, height: 4 * k, fill: C.fr4Hi, opacity: 0.9 });
        A.text(g, X(SW - 14.25), Y(0) - 8 - (narrow ? 0 : 0), "tongue", { size: 12, anchor: "middle", fill: C.ink, weight: 600 });
        A.text(g, X(SW) + bw / 2, Y(30), "bracket", { size: 12, anchor: "middle", fill: C.ink, weight: 600 }).setAttribute("transform", "rotate(90," + (X(SW) + bw / 2) + "," + Y(30) + ")");
      } else {
        A.el(g, "rect", { x: X(0), y: Y(0), width: SW * k, height: SH * k, fill: "none", stroke: C.ruleHi, "stroke-dasharray": "5 5" });
        A.text(g, X(SW / 2), Y(SH) + 18, "no sheet round it", { size: 13, anchor: "middle", fill: C.text3 });
      }
      // the channel (0.8 mm) with four 1.5 mm tabs, one mid-side
      if (s.cut && s.sheet) {
        A.el(g, "rect", { x: bX(-0.4), y: bY(-0.4), width: (BW + 0.8) * k, height: (BH + 0.8) * k, fill: "none", stroke: C.ink, "stroke-width": 0.8 * k });
        [[BW / 2, -0.4, 1.5, 0.8], [BW / 2, BH + 0.4, 1.5, 0.8], [-0.4, BH / 2, 0.8, 1.5], [BW + 0.4, BH / 2, 0.8, 1.5]].forEach(function (t) {
          A.el(g, "rect", { x: bX(t[0] - t[2] / 2) - (t[2] < 1 ? 1 : 0), y: bY(t[1] - t[3] / 2) - (t[3] < 1 ? 1 : 0), width: t[2] * k + (t[2] < 1 ? 2 : 0), height: t[3] * k + (t[3] < 1 ? 2 : 0), fill: C.copperDim });
        });
      }
      // the board
      A.el(g, "rect", { x: bX(0), y: bY(0), width: BW * k, height: BH * k, fill: C.copper, stroke: C.copperHi, "stroke-width": 1 });
      OTHER.concat(KEY).forEach(function (h) {
        A.el(g, "circle", { cx: bX(h[0]), cy: bY(h[1]), r: 1.3 * k, fill: C.copperHi });
        A.el(g, "circle", { cx: bX(h[0]), cy: bY(h[1]), r: 0.4 * k, fill: C.ink });
      });
      // the mark lane, 3.0-4.5 mm out
      A.el(g, "rect", { x: bX(-3.75), y: bY(-3.75), width: (BW + 7.5) * k, height: (BH + 7.5) * k, rx: 3.75 * k, fill: "none", stroke: C.live, "stroke-width": 1.5 * k, opacity: 0.32 });
      // which squares land on sheet copper?
      var ok = s.sheet && [0, 1, 2].every(function (i) {
        var m = markCentre(i), x = bx + m[0], y = by + m[1];
        return x - 0.75 >= 0 && x + 0.75 <= SW && y - 0.75 >= 0 && y + 0.75 <= SH;
      });
      [0, 1, 2].forEach(function (i) {
        var m = markCentre(i), x = bx + m[0], y = by + m[1];
        var on = s.sheet && x - 0.75 >= 0 && x + 0.75 <= SW && y - 0.75 >= 0 && y + 0.75 <= SH;
        if (ok) {
          A.el(g, "rect", { x: X(x - 0.75), y: Y(y - 0.75), width: 1.5 * k, height: 1.5 * k, fill: C.live });
        } else {
          // would-be square (dashed, red if off the sheet) ...
          A.el(g, "rect", { x: X(x - 0.75), y: Y(y - 0.75), width: 1.5 * k, height: 1.5 * k, fill: "none", stroke: on ? C.text3 : C.danger, "stroke-width": 1.5, "stroke-dasharray": "3 2" });
          // ... and the hatch on the isolation round the hole instead
          var h = KEY[i];
          A.el(g, "circle", { cx: bX(h[0]), cy: bY(h[1]), r: 2.5 * k, fill: "none", stroke: C.caution, "stroke-width": 2, "stroke-dasharray": "2 3" });
        }
      });
      // dimension: the waste on each side
      var dims = [["left", bx], ["right", SW - bx - BW], ["back", by], ["front", SH - by - BH]];
      title.textContent = s.label;
      if (ok) {
        verdict.textContent = "Proof on 3 marks in the waste beside the board";
        A.set(verdict, { fill: C.ok }); A.set(verdictBox, { fill: C.okFill, stroke: C.ok });
      } else {
        verdict.textContent = "Proof on 3 marks in the isolation";
        A.set(verdict, { fill: C.caution }); A.set(verdictBox, { fill: C.cautionFill, stroke: C.caution });
      }
      var L = [];
      if (s.sheet) {
        L.push("Waste: left " + dims[0][1].toFixed(1) + " · right " + dims[1][1].toFixed(1) + " mm,");
        L.push("back " + dims[2][1].toFixed(1) + " · front " + dims[3][1].toFixed(1) + " mm.");
      } else { L.push("No sheet round the board."); L.push(""); }
      if (st === "corner") L.push("Right: 3.0 mm, a mark needs 4.5: off the sheet.");
      if (st === "centre") L.push("6 mm or more each side: marks on spare copper.");
      if (st === "nocut") L.push("No outline cut, board at the far edges.");
      if (st === "out") L.push("Nothing round the board to mark on.");
      L.push(ok ? "The marks never touch the board." : "Orange rings: marks go on the isolation,");
      if (!ok) L.push("copper the etch clears anyway. Still fine.");
      else L.push("");
      L.push("Blue band: 3.0-4.5 mm out, 1.5 mm marks.");
      L.push("Black ring: 0.8 mm cut-out, 1.5 mm tabs.");
      lines.forEach(function (t, i) {
        t.textContent = L[i] || "";
        A.set(t, { fill: i === 2 ? (ok ? C.ok : C.caution) : C.text2 });
      });
    }

    var row = A.controls(host);
    A.segmented(row, Object.keys(STATES).map(function (key) {
      return [key, narrow ? { corner: "Corner", centre: "Centre", nocut: "No cut-out", out: "Out" }[key] : STATES[key].label];
    }), "corner", draw);
  });
})();
