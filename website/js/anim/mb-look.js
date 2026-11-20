/* Look, then re-etch a spot (make-a-board.html#etch). Schematic: a close-up of a few
   trenches as the photo shows them after the etch. Etched trenches are dark; a stretch
   that still shines is copper left behind, so the two traces it joins are shorted. In
   Rework mode a box (at least 0.3 mm) is drawn over it, the button reads "Re-etch 1 box"
   (gui2/stencil_laser.py), and only the box is etched again, with Rework passes (5 by
   default) in place of the recipe's passes. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  var STEPS = [
    ["look", "After the etch", ["Dark trenches: etched through to the laminate.", "One stretch still shines: copper left behind.", "It joins two traces: a short."]],
    ["box", "Rework: box it", ["Choose Rework above the bed and drag a box", "over the shiny stretch. The button now", "reads Re-etch 1 box. The sheet must not move."]],
    ["done", "Re-etched", ["Only the box was etched again. The trench is", "dark all along. Check the two traces with", "a multimeter: no continuity between them."]]
  ];

  A.define("mb-look", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 620 : 340;
    var svg = A.stage(host, W, H, "Schematic close-up of etched trenches: dark where etched through, one shiny stretch, a rework box over it, and the trench dark after the re-etch");
    var px = narrow ? 20 : 24, py = 44, pw = narrow ? 480 : 470, ph = 260;
    A.text(svg, px, 28, "THE PHOTO, CLOSE UP · SCHEMATIC", { size: 13, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: px, y: py, width: pw, height: ph, fill: C.copper, rx: 4 });
    // three traces separated by two trenches, with a pad
    var t1 = py + 70, t2 = py + 160;
    var g = A.el(svg, "g", {});
    var tx = narrow ? 20 : 530, ty = narrow ? py + ph + 46 : 80;
    var cap = A.text(svg, tx, ty, "", { size: narrow ? 19 : 17, weight: 700 });
    var lines = [];
    for (var i = 0; i < 3; i++) lines.push(A.text(svg, tx, ty + 34 + i * (narrow ? 28 : 26), "", { size: narrow ? 16.5 : 14.5, fill: C.text2 }));
    var btn = A.el(svg, "g", {});

    function trench(y, shinyFrom, shinyTo) {
      // the trench: a dark band 14 px wide; where it shines, copper bridges it
      A.el(g, "rect", { x: px, y: y - 7, width: pw, height: 14, fill: C.ink });
      A.el(g, "rect", { x: px, y: y - 7, width: pw, height: 14, fill: "none", stroke: C.copperDim, "stroke-width": 1 });
      if (shinyFrom !== null) {
        A.el(g, "rect", { x: px + shinyFrom, y: y - 7, width: shinyTo - shinyFrom, height: 14, fill: C.copperHi });
        for (var x = shinyFrom + 6; x < shinyTo; x += 12) {
          A.el(g, "line", { x1: px + x, y1: y - 5, x2: px + x + 6, y2: y + 5, stroke: "#f6d3a5", "stroke-width": 1.5, opacity: 0.8 });
        }
      }
    }

    function draw(key) {
      var st = STEPS.filter(function (s) { return s[0] === key; })[0];
      while (g.firstChild) g.removeChild(g.firstChild);
      while (btn.firstChild) btn.removeChild(btn.firstChild);
      var s0 = pw * 0.52, s1 = pw * 0.52 + 46;
      trench(t1, null, null);
      trench(t2, key === "done" ? null : s0, s1);
      // a round pad with its ring trench
      A.el(g, "circle", { cx: px + pw * 0.18, cy: py + 115, r: 22, fill: "none", stroke: C.ink, "stroke-width": 12 });
      A.el(g, "circle", { cx: px + pw * 0.18, cy: py + 115, r: 6, fill: C.sunk });
      A.text(g, px + 12, py + 22, "trace", { size: 12.5, fill: C.ink, weight: 600 });
      A.text(g, px + 12, t1 + 30, "trace", { size: 12.5, fill: C.ink, weight: 600 });
      A.text(g, px + 12, t2 + 30, "trace", { size: 12.5, fill: C.ink, weight: 600 });
      if (key === "look") {
        A.el(g, "circle", { cx: px + (s0 + s1) / 2, cy: t2, r: 34, fill: "none", stroke: C.danger, "stroke-width": 2.5 });
        A.el(g, "rect", { x: px + (s0 + s1) / 2 + 34, y: t2 - 50, width: 118, height: 26, rx: 4, fill: C.ink });
        A.text(g, px + (s0 + s1) / 2 + 93, t2 - 32, "still shines", { size: 14, anchor: "middle", fill: C.danger, weight: 700 });
      }
      if (key === "box" || key === "done") {
        A.el(g, "rect", { x: px + s0 - 14, y: t2 - 22, width: s1 - s0 + 28, height: 44, fill: key === "box" ? C.liveFill : "none", "fill-opacity": 0.35, stroke: C.live, "stroke-width": 2, "stroke-dasharray": "6 4" });
        A.text(g, px + s0 - 10, t2 - 28, "1", { size: 13, fill: C.live, weight: 700 });
      }
      if (key === "done") {
        A.el(g, "circle", { cx: px + (s0 + s1) / 2, cy: t2, r: 34, fill: "none", stroke: C.ok, "stroke-width": 2.5 });
      }
      cap.textContent = st[1];
      lines.forEach(function (t, i) { t.textContent = st[2][i] || ""; });
      var by = narrow ? ty + 130 : ty + 130;
      if (key === "box") {
        A.el(btn, "rect", { x: tx, y: by, width: 190, height: 40, rx: 6, fill: C.text, stroke: C.text });
        A.text(btn, tx + 95, by + 26, "Re-etch 1 box", { size: 15, anchor: "middle", fill: C.ink, weight: 700 });
        A.text(btn, tx + 206, by + 26, "Rework passes 5", { size: 14, fill: C.text3 });
      } else if (key === "done") {
        A.el(btn, "rect", { x: tx, y: by, width: 230, height: 40, rx: 6, fill: C.okFill, stroke: C.ok });
        A.text(btn, tx + 115, by + 26, "No short: re-etched", { size: 15, anchor: "middle", fill: C.ok, weight: 700 });
      }
    }

    var row = A.controls(host);
    A.segmented(row, STEPS.map(function (s) { return [s[0], s[1]]; }), "look", draw);
  });
})();
