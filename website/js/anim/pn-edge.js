/* A board edge on the sheet's edge is not cut. engine/cutout.py SHEET_EDGE_MM = 0.5:
   once the copper's size and corner are set, a board edge within 0.5 mm of the sheet's
   edge (either side) IS the sheet's edge, and the cut-out leaves that side out. Hanging
   off by that little is a warning (the board is short by that much); more is a failure,
   "The job runs off the copper" (gui2/window.py _stock_checks). Without the sheet set,
   the app knows only the bed and cuts the whole ring. 50 px per mm. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BIT = 0.8, EDGE = 0.5;

  A.define("pn-edge", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 440 : 380;
    var ZK = narrow ? 40 : 50;
    var VX = 24, VY = 50, VW = W - 48, VH = narrow ? 260 : 230;
    var SX = VX + (narrow ? 150 : 250);          // screen x of the sheet's left edge
    var svg = A.stage(host, W, H, "A board's left edge near the copper sheet's left edge, to scale");
    A.text(svg, 24, 32, "THE SHEET'S LEFT EDGE · TO SCALE", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: VX, y: VY, width: VW, height: VH, fill: C.panel, stroke: C.ruleStrong, rx: 3 });
    var clip = A.el(svg, "clipPath", { id: "pnedge-clip" });
    A.el(clip, "rect", { x: VX + 1, y: VY + 1, width: VW - 2, height: VH - 2 });
    var g = A.el(svg, "g", { "clip-path": "url(#pnedge-clip)" });
    var verdict = A.text(svg, 24, H - 58, "", { size: 18, weight: 700 });
    var detail = A.text(svg, 24, H - 30, "", { size: 15, fill: C.text2 });

    var row = A.controls(host);
    var sheetSet = true, off = 1.5;
    A.segmented(row, [[true, "Copper size and corner set"], [false, "Not set"]], true, function (v) { sheetSet = v; draw(); });
    A.slider(row, "Board edge", -1.5, 3, 0.05, 1.5, function (v) { off = v; draw(); },
      function (v) { return (v >= 0 ? v.toFixed(2) + " mm in" : (-v).toFixed(2) + " mm off"); });
    var st = A.status(row);

    function X(mm) { return SX + mm * ZK; }
    function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }

    function draw() {
      if (!st) return;               // controls still being built
      clear(g);
      var top = VY + 14, bot = VY + VH - 14;
      // the copper sheet: everything right of its edge; the bed (spoilboard) to the left
      A.el(g, "rect", { x: VX, y: top, width: SX - VX, height: bot - top, fill: C.board, opacity: 0.55 });
      A.text(g, VX + 14, bot - 14, "spoilboard", { size: 16, fill: C.text2 });
      A.el(g, "rect", { x: SX, y: top, width: VX + VW - SX, height: bot - top, fill: C.copperFill });
      A.el(g, "line", { x1: SX, y1: top, x2: SX, y2: bot, stroke: C.copperHi, "stroke-width": 2 });
      A.text(g, SX + 8, top + 22, "sheet's edge", { size: 15, fill: C.copperHi });
      // the board (its copper), from its edge rightwards
      var bx = X(off);
      A.el(g, "rect", { x: bx, y: top + 36, width: VX + VW - bx, height: bot - top - 72, fill: C.copper, opacity: off < 0 ? 0.9 : 1 });
      A.el(g, "line", { x1: bx, y1: top + 30, x2: bx, y2: bot - 30, stroke: C.text, "stroke-width": 1.5, "stroke-dasharray": "6 5" });
      A.text(g, bx + 12, top + 62, "board edge", { size: 15, fill: C.ink, weight: 700 });
      var onEdge = sheetSet && Math.abs(off) <= EDGE + 1e-9;
      var runsOff = sheetSet && off < -EDGE - 1e-9;
      if (!onEdge) {
        // the cut-out channel, one cutter wide, just outside the board edge
        var c0 = X(off - BIT), cut = A.el(g, "rect", { x: c0, y: top + 30, width: BIT * ZK, height: bot - top - 60, fill: C.sunk });
        if (off - BIT < 0 && sheetSet === false) cut.setAttribute("opacity", 0.9);
        A.text(g, c0 - 8, bot - 40, "cut-out", { size: 15, anchor: "end", fill: C.text });
      }
      if (sheetSet && off > 0) {
        // the rim of copper between the sheet edge and the board
        A.el(g, "rect", { x: SX, y: top + 36, width: off * ZK, height: bot - top - 72, fill: C.copperHi, opacity: onEdge ? 0.85 : 0.35 });
      }
      if (sheetSet && off < 0) {
        A.el(g, "rect", { x: bx, y: top + 36, width: SX - bx, height: bot - top - 72, fill: C.danger, opacity: 0.6 });
      }

      var v;
      if (!sheetSet) v = ["The whole ring is cut", C.text, "Without the sheet's size and corner, the app knows only the bed. Set them under Set up the job › The copper."];
      else if (runsOff) v = ["The job runs off the copper", C.danger, "It hangs " + (-off).toFixed(2) + " mm off the sheet: a failure. Move the job, or set the sheet's real size and corner."];
      else if (onEdge && off < 0) v = ["On the edge, a hair over: a warning", C.caution, "The sheet's edge is the board's edge here. The cut-out skips this side, and the board is " + (-off).toFixed(2) + " mm short."];
      else if (onEdge) v = ["On the sheet's edge: not cut", C.ok, off > 0.01 ? "Within 0.5 mm, so this side is left uncut. The " + off.toFixed(2) + " mm rim breaks off by hand." : "The sheet's edge is the board's edge. The cut-out leaves this side out."];
      else v = ["Cut as usual", C.ok, "More than 0.5 mm in: the cut-out runs one cutter wide outside the board edge."];
      A.set(verdict, { fill: v[1] });
      verdict.textContent = v[0];
      detail.textContent = narrow ? "" : v[2];
      st.textContent = narrow ? v[2] : "Slide the board towards the sheet's edge, and past it.";
    }
    draw();
  });
})();
