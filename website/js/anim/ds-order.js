/* Double-sided run order, fiducial registration (the lab's): the plan the rail shows for a two-face job
   (gerber2rml/gui2/runplan.py, the double_sided branch), with the bit changes
   the tools force and the flip in the middle. On the right, what goes into
   VPanel in each sitting between two hands-on steps: VPanel lists the files it
   is given alphabetically, which is right before the flip and wrong after it
   (cutout sorts above top_traces). */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var NAME = "board";
  var FLAT = "0.80 mm flat endmill", VBIT = "30° V-bit (0.1 mm tip)";

  function plan(reg, bit) {
    var trace = bit === "vbit" ? VBIT : FLAT, fid = reg === "fiducial";
    var s = [];
    s.push({ hand: true, title: "Fit the " + FLAT + ", set the Z origin", detail: "Z on the copper, in G54. Never re-zero XY." });
    s.push({ n: 0, title: "Dry run", file: "airpass", tool: null, detail: "Spindle off, bit 5 mm up, tracing the outline" });
    s.push({ n: 1, title: fid ? "Fiducial holes" : "Dowel holes", file: "align", tool: FLAT,
      detail: fid ? "4 reference holes, through the stock only" : "3.1 and 1.9 mm rods, 5 mm into the bed", warn: !fid });
    s.push({ n: 2, title: "Drill the board", file: "bottom_drill", tool: FLAT, detail: "One bit, through the board" });
    s.push({ n: 3, title: "Bottom traces", file: "bottom_traces", tool: trace, detail: "Milled mirrored: the underside, from above" });
    s.push({ hand: true, flip: true, title: fid ? "Flip the board, re-place it, probe" : "Flip the board onto the pins",
      detail: "Re-zero Z on the new face, and move the clip to it", warn: true });
    if (fid) s.push({ hand: true, title: "Measure where it landed", detail: "Probe the reference holes; the top warps to match", warn: true });
    s.push({ hand: true, title: "Level the top face", detail: fid ? "Then Write the top traces and the cut-out"
      : "Level the bed › Top, then Write the top traces to this surface…" });
    s.push({ n: 4, title: "Top traces", file: "top_traces", tool: trace, detail: "Cut as plain F.Cu, as KiCad drew it" });
    s.push({ n: 5, title: "Cut the board out", file: "cutout", tool: FLAT, detail: "Last: it frees the board", last: true });
    // bit changes, exactly where the tool in the collet has to change
    var out = [], inCollet = FLAT;
    s.forEach(function (x) {
      if (!x.hand && x.tool && x.tool !== inCollet) {
        out.push({ hand: true, change: true, title: "Change to the " + x.tool, detail: "Then re-zero Z. Never XY." });
        inCollet = x.tool;
      }
      out.push(x);
    });
    return out;
  }

  // the files sent in each sitting: a hands-on step ends one
  function sittings(steps) {
    var b = [], cur = [];
    steps.forEach(function (x, i) {
      if (x.hand && i > 0) { if (cur.length) b.push(cur); cur = []; }
      if (x.file) cur.push(NAME + "_" + x.file + ".nc");
    });
    if (cur.length) b.push(cur);
    return b;
  }

  A.define("ds-order", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880;
    var LW = narrow ? 496 : 520;            // the step list's width
    var RX = narrow ? 12 : 556, RW = narrow ? 496 : 312;
    var svg = A.stage(host, W, narrow ? 1180 : 700, "The double-sided run order, with bit changes, the flip, and what VPanel lists in each sitting");
    var g = A.el(svg, "g", {});
    var row = A.controls(host);
    var reg = "fiducial", bit = "flat";      // the lab registers with fiducials only
    var st = A.status(row);

    function draw() {
      while (g.firstChild) g.removeChild(g.firstChild);
      var steps = plan(reg, bit);
      var y = 26, x0 = 12;
      A.text(g, x0 + 4, y, "THE RAIL", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
      y += 14;
      var rowH = narrow ? 58 : 50;
      steps.forEach(function (s) {
        var hand = !!s.hand;
        var fill = s.flip ? C.cautionFill : s.change ? C.liveFill : hand ? C.sunk : C.panel;
        var edge = s.flip ? C.caution : s.change ? C.live : s.last ? C.copperDim : C.ruleHi;
        A.el(g, "rect", { x: x0, y: y, width: LW, height: rowH - 6, rx: 3, fill: fill, stroke: edge });
        A.text(g, x0 + 22, y + (rowH - 6) / 2 + 7, hand ? "–" : String(s.n),
          { size: 22, weight: 700, anchor: "middle", font: "mono", fill: hand ? C.text3 : C.text });
        A.text(g, x0 + 46, y + 20, s.title, { size: 16, weight: 600, fill: s.change ? C.live : s.flip ? C.caution : C.text });
        var det = s.file ? NAME + "_" + s.file + ".nc" + (narrow ? "" : "  ·  " + s.detail) : s.detail;
        A.text(g, x0 + 46, y + 40, det, { size: 15, fill: s.file ? C.text2 : C.text3, font: s.file && narrow ? "mono" : "sans" });
        if (s.warn && !s.flip && !s.hand) {
          A.text(g, x0 + LW - 12, y + 20, "into the bed", { size: 15, anchor: "end", fill: C.caution, weight: 600 });
        }
        y += rowH;
      });
      // the sittings
      var by = narrow ? y + 20 : 26;
      A.text(g, RX + 4, by, "IN VPANEL, SITTING BY SITTING", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
      by += 16;
      var bad = 0;
      sittings(steps).forEach(function (files, k) {
        var sorted = files.slice().sort();
        var wrong = sorted.join() !== files.join();
        if (wrong) bad++;
        var h = 40 + files.length * 24 + (wrong ? 34 + files.length * 24 : 0);
        A.el(g, "rect", { x: RX, y: by, width: RW, height: h, rx: 3, fill: C.panel, stroke: wrong ? C.danger : C.ruleHi });
        A.text(g, RX + 12, by + 24, "Sitting " + (k + 1) + (wrong ? ": VPanel lists" : ": VPanel lists, fine"),
          { size: 15, weight: 600, fill: wrong ? C.danger : C.ok });
        var yy = by + 48;
        sorted.forEach(function (f) {
          A.text(g, RX + 16, yy, f, { size: 15, font: "mono", fill: wrong && f.indexOf("cutout") >= 0 ? C.danger : C.text });
          yy += 24;
        });
        if (wrong) {
          A.text(g, RX + 12, yy + 6, "Move the cut-out down, to run:", { size: 15, weight: 600, fill: C.ok });
          yy += 30;
          files.forEach(function (f) {
            A.text(g, RX + 16, yy, f, { size: 15, font: "mono", fill: C.text });
            yy += 24;
          });
        }
        by += h + 10;
      });
      // fit the drawing to what was drawn
      var bottom = Math.max(y, by) + 8;
      svg.setAttribute("viewBox", "0 0 " + W + " " + bottom);
      svg.style.aspectRatio = W + " / " + bottom;
      var changes = steps.filter(function (s) { return s.change; }).length;
      st.className = "anim-status" + (bad ? " bad" : "");
      st.textContent = (changes ? changes + " bit change" + (changes > 1 ? "s" : "") + ", each followed by a Z re-zero. " :
        "One bit for the whole job: Z is zeroed once per face. ") +
        (bad ? "After the flip VPanel lists the cut-out above the top traces: move it to the bottom before Output."
          : "Here the bit changes split the files into sittings of their own, so each list is already in order.");
    }

    A.segmented(row, [["flat", "One 0.8 mm flat bit"], ["vbit", "V-bit for the traces"]], bit, function (v) { bit = v; draw(); });
    row.appendChild(st);
    draw();
  });
})();
