/* The set-up in the xTool software, a step at a time: import, the outline to its own
   colour with output off, three check pads to another colour, Make Compound Vector on the
   rest, Engrave with the RemoveSolderMask preset. Schematic: it shows what happens to the
   drawing, not the program's own window. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C, B = window.SMBoard;

  var STEPS = [
    ["Import the DXF", "It is already mirrored. Do not flip it."],
    ["The outline: its own colour", "Output off. It is there to place by."],
    ["Three check pads: another colour", "Far apart, not in a line."],
    ["The rest: Make Compound Vector", "One shape, so they fill as one job."],
    ["Engrave, RemoveSolderMask", "Pick the preset on the xTool PC, for both colours."]
  ];

  A.define("sm-xtool", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 880 : 400;
    var svg = A.stage(host, W, H, "The steps in the xTool software, shown on the drawing: outline set aside, three pads picked, the rest combined and set to engrave");
    var K = narrow ? 8.8 : 7.2, OX = narrow ? 22 : 24, OY = 46;
    function sx(x) { return OX + x * K; }
    function sy(y) { return OY + (B.H - y) * K; }
    A.text(svg, OX - 2, 28, "SCHEMATIC · NOT THE XTOOL WINDOW", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: OX - 8, y: OY - 8, width: B.W * K + 16, height: B.H * K + 16, rx: 4, fill: C.panel, stroke: C.ruleHi });

    var defs = A.el(svg, "defs");
    var hatch = A.el(defs, "pattern", { id: "smHatch", width: 3.2, height: 3.2, patternUnits: "userSpaceOnUse" });
    A.el(hatch, "path", { d: "M0 0H3.2M0 0V3.2", stroke: C.text, "stroke-width": 0.9 });

    var outline = A.el(svg, "rect", { x: sx(0), y: sy(B.H), width: B.W * K, height: B.H * K, fill: "none", "stroke-width": 2 });
    var outT = A.text(svg, sx(B.W) + 7, 28, "outline: output off", { size: 14, weight: 600, anchor: "end", fill: C.danger });
    var box = A.el(svg, "rect", { x: sx(1), y: sy(B.H - 0.4), width: (B.W - 2) * K, height: (B.H - 1) * K, fill: "none", stroke: C.ok, "stroke-width": 1.5, "stroke-dasharray": "7 6" });
    var rects = B.PADS.map(function (p) { return B.pad(svg, p, sx, sy, K, { "stroke-width": 1.2 }); });
    var rings = B.CHECK.map(function (i) {
      var p = B.PADS[i];
      return A.el(svg, "circle", { cx: sx(p[0]), cy: sy(p[1]), r: 15, fill: "none", stroke: C.caution, "stroke-width": 2.5 });
    });

    // the steps, as a list beside (or under) the drawing
    var LX = narrow ? 22 : OX + B.W * K + 26, LY = narrow ? OY + B.H * K + 34 : OY, LH = narrow ? 76 : 68;
    var LW = narrow ? W - 44 : W - LX - 18;
    var items = STEPS.map(function (s, i) {
      var g = A.el(svg, "g", { transform: "translate(" + LX + "," + (LY + i * LH) + ")" });
      var bg = A.el(g, "rect", { x: 0, y: 0, width: LW, height: LH - 8, rx: 3 });
      var n = A.text(g, 12, 25, String(i + 1), { size: 19, weight: 700, font: "mono" });
      var t1 = A.text(g, 38, 25, s[0], { size: narrow ? 16 : 15, weight: 700 });
      var t2 = A.text(g, 38, 48, s[1], { size: narrow ? 14 : 13 });
      return { bg: bg, n: n, t1: t1, t2: t2 };
    });

    var step = 0, DWELL = 2;
    function show(s) {
      step = s;
      items.forEach(function (it, i) {
        var on = i === s, done = i < s;
        A.set(it.bg, { fill: on ? C.panelHi : C.panel, stroke: on ? C.live : C.ruleHi });
        it.n.setAttribute("fill", on ? C.live : done ? C.ok : C.text3);
        it.t1.setAttribute("fill", on || done ? C.text : C.text3);
        it.t2.setAttribute("fill", on ? C.text2 : C.text3);
      });
      A.set(outline, { stroke: s >= 1 ? C.danger : C.live, "stroke-dasharray": s >= 1 ? "8 6" : "none" });
      outT.setAttribute("opacity", s >= 1 ? 1 : 0);
      box.setAttribute("opacity", s === 3 ? 1 : 0);
      rects.forEach(function (r, i) {
        var check = B.CHECK.indexOf(i) >= 0 && s >= 2;
        var filled = s >= 4;
        A.set(r, { stroke: check ? C.caution : s >= 3 ? C.ok : C.live, fill: filled ? "url(#smHatch)" : "none" });
      });
      rings.forEach(function (r) { r.setAttribute("opacity", s >= 2 ? 1 : 0); });
      back.disabled = s === 0;
      next.disabled = s === STEPS.length - 1;
    }

    var row = A.controls(host);
    var back = A.button(row, "← Back", function () { auto = false; show(Math.max(step - 1, 0)); });
    var next = A.button(row, "Next →", function () { auto = false; show(Math.min(step + 1, STEPS.length - 1)); });
    A.button(row, "Play from the start", function () { auto = true; show(0); lp.restart(); }, "primary");

    var auto = true;
    show(0);
    var lp = A.loop(host, function (t) {
      if (!auto) { if (lp) lp.stop(); return; }
      var s = Math.min(Math.floor(t / DWELL), STEPS.length - 1);
      if (s !== step) show(s);
      if (s === STEPS.length - 1 && lp) lp.stop();
    }, DWELL * STEPS.length);
  });
})();
