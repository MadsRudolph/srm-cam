/* How close two boards may sit, and what the cut-out does about it. The rules are
   the app's panel check (gui2/window.py _panel_checks) and the cut-out's grouping
   (engine/cutout.py): with the lab's 0.8 mm cutter,
     overlap              -> refused: nothing can be cut
     gap <= 0.8 mm        -> ONE channel, centred in the gap; each board loses (0.8 - gap) / 2
     0.8 < gap < 2.6 mm   -> two channels; the strip left between them (gap - 1.6) can break
                             loose and jam the cutter (a warning), unless nothing is left
     gap >= 2.6 mm        -> comfortable (2 x bit + 1 mm)
   Drawn to scale in the seam: 40 px per mm. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BIT = 0.8, COMF = 2 * BIT + 1.0;

  A.define("pn-gap", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 500 : 440;
    var ZK = narrow ? 44 : 52;                  // px per mm
    var VX = 24, VY = 58, VW = W - 48, VH = narrow ? 250 : 240;
    var CX = VX + VW / 2;
    var svg = A.stage(host, W, H, "The seam between two boards, to scale, as the gap between them changes");
    A.text(svg, 24, 34, "THE SEAM BETWEEN TWO BOARDS · TO SCALE", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: VX, y: VY, width: VW, height: VH, fill: C.copperFill, stroke: C.ruleStrong, rx: 3 });
    var clip = A.el(svg, "clipPath", { id: "pngap-clip" });
    A.el(clip, "rect", { x: VX + 1, y: VY + 1, width: VW - 2, height: VH - 2 });
    var g = A.el(svg, "g", { "clip-path": "url(#pngap-clip)" });
    var lbl = A.el(svg, "g", {});
    var ruleY = VY + VH + 34;
    var verdict = A.text(svg, 24, H - 58, "", { size: 18, weight: 700 });
    var detail = A.text(svg, 24, H - 30, "", { size: 15, fill: C.text2 });

    var row = A.controls(host);
    var st = A.status(row);
    var gapIn = A.slider(row, "Gap between the boards", -1, 5, 0.05, 4, function (v) { draw(v); },
      function (v) { return v < 0 ? "overlap" : v.toFixed(2) + " mm"; });
    [["Butted", 0], ["0.5 mm", 0.5], ["1.2 mm", 1.2], ["2 mm", 2], ["Side by side, 4 mm", 4]].forEach(function (p) {
      A.button(row, p[0], function () { gapIn.value = p[1]; gapIn.dispatchEvent(new Event("input")); });
    });
    row.appendChild(st);

    function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
    function X(mm) { return CX + mm * ZK; }

    function draw(gap) {
      clear(g); clear(lbl);
      var top = VY + 16, bot = VY + VH - 16;
      var aR = -gap / 2, bL = gap / 2;          // board edges, mm from the centre of the gap
      var kind, lostEach = 0, strip = 0;
      if (gap < 0) kind = "overlap";
      else if (gap <= BIT + 1e-6) { kind = "shared"; lostEach = (BIT - gap) / 2; }
      else if (gap < COMF) { strip = gap - 2 * BIT; kind = strip <= 0 ? "merged" : "strip"; }
      else { kind = "ok"; strip = gap - 2 * BIT; }

      // copper of the two boards (as drawn), then the channels on top
      var aKeep = kind === "shared" ? -BIT / 2 : aR, bKeep = kind === "shared" ? BIT / 2 : bL;
      A.el(g, "rect", { x: VX, y: top, width: X(aKeep) - VX, height: bot - top, fill: C.copper });
      A.el(g, "rect", { x: X(bKeep), y: top, width: VX + VW - X(bKeep), height: bot - top, fill: C.copper });
      if (kind === "overlap") {
        A.el(g, "rect", { x: X(bL), y: top, width: X(aR) - X(bL), height: bot - top, fill: C.danger, opacity: 0.55 });
      }
      var chans = [];
      if (kind === "shared") chans = [[-BIT / 2, BIT / 2]];
      else if (kind !== "overlap") chans = [[aR, aR + BIT], [bL - BIT, bL]];
      chans.forEach(function (c) {
        A.el(g, "rect", { x: X(c[0]), y: top, width: (c[1] - c[0]) * ZK, height: bot - top, fill: C.sunk });
      });
      if (kind === "strip") {
        A.el(g, "rect", { x: X(aR + BIT), y: top, width: strip * ZK, height: bot - top, fill: C.caution, opacity: 0.9 });
      }
      // the edges as drawn in KiCad, dashed
      [aR, bL].forEach(function (e) {
        A.el(g, "line", { x1: X(e), y1: top - 10, x2: X(e), y2: bot + 10, stroke: C.text, "stroke-width": 1.5, "stroke-dasharray": "6 5", opacity: 0.8 });
      });
      A.text(g, X(Math.min(aR, 0)) - 16, top + 30, "board 1", { size: 17, anchor: "end", weight: 700, fill: C.ink });
      A.text(g, X(Math.max(bL, 0)) + 16, top + 30, "board 2", { size: 17, weight: 700, fill: C.ink });

      // a millimetre rule under the view
      for (var m = -6; m <= 6; m++) {
        var x = X(m);
        if (x < VX || x > VX + VW) continue;
        A.el(lbl, "line", { x1: x, y1: ruleY - 10, x2: x, y2: ruleY - (m % 5 ? 4 : 0), stroke: C.text3, "stroke-width": 1.5 });
      }
      A.el(lbl, "line", { x1: Math.max(VX, X(-6)), y1: ruleY - 10, x2: Math.min(VX + VW, X(6)), y2: ruleY - 10, stroke: C.text3, "stroke-width": 1.5 });
      A.text(lbl, X(0), ruleY + 12, "1 mm per tick · the cutter is 0.8 mm", { size: 15, anchor: "middle", fill: C.text3 });

      if (kind === "shared") {
        var ay = VY + VH * 0.62;
        A.text(lbl, X(0), ay - (narrow ? 72 : 60), "one cut", { size: 17, anchor: "middle", weight: 700, fill: C.text });
        if (lostEach > 0.005) {
          A.arrow(lbl, X(aR) - 46, ay, X(-BIT / 2), ay, { color: C.caution, head: 7 });
          A.arrow(lbl, X(bL) + 46, ay, X(BIT / 2), ay, { color: C.caution, head: 7 });
        }
      }
      if (kind === "strip") {
        A.text(lbl, X(0), VY + VH * 0.3, strip.toFixed(2) + " mm strip", { size: 16, anchor: "middle", weight: 700, fill: C.caution });
      }

      var say = {
        overlap: ["Two boards overlap", C.danger, "Nothing can be cut like this: the export refuses. Move one of them."],
        shared: [lostEach < 0.2 ? "One shared cut" : "One shared cut: a warning", lostEach < 0.2 ? C.ok : C.caution,
          "Closer than the cutter: one channel, centred in the gap. Each board loses " + lostEach.toFixed(2) + " mm along that edge."],
        merged: ["Two channels, nothing between", C.ok, "The two cut-outs overlap and leave no stock between them."],
        strip: ["Nearly touching: a warning", C.caution, "A " + strip.toFixed(2) + " mm strip is left between the cuts. It can break loose and jam the cutter. 2.6 mm or more, or butt them."],
        ok: ["Clear of each other", C.ok, "Two channels with " + strip.toFixed(1) + " mm of waste between them, wide enough to stay put."]
      }[kind];
      A.set(verdict, { fill: say[1] });
      verdict.textContent = say[0];
      detail.textContent = narrow ? "" : say[2];
      st.textContent = narrow ? say[2] : "Drag the slider or pick a gap. The dashed lines are the edges as drawn in KiCad.";
      st.className = "anim-status";
    }
  });
})();
