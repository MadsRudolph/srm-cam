/* Two boards on one sheet: side by side (a 4 mm strip of waste between them,
   app/panel.py PANEL_GAP_MM) or butted together (one cut down the seam separates
   both, and each board loses half the 0.8 mm cutter along that edge). The tabs are
   the cut-out's four per ring (config.py tabs = 4, 1.5 mm wide), drawn at the middle
   of each side: schematic, the app spaces them evenly along the ring. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BW = 34, BH = 42, BIT = 0.8, GAP = 4.0, TAB = 1.5;   // mm
  var ZK = 42;                                             // px per mm, seam inset

  A.define("butt", function (host) {
    // A phone gets its own layout: a narrower drawing, the seam inset under the sheet
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 690 : 470;
    var K = narrow ? 6 : 7;                                  // px per mm, main view
    var X0 = narrow ? 42 : 60, Y0 = narrow ? 140 : 118;      // board 1's back-left corner on screen
    var svg = A.stage(host, W, H, "Two boards on one sheet, side by side or butted together, with the cut-out drawn");
    A.text(svg, 24, 34, "File › Add another board to the sheet…", { size: 16, font: "mono", fill: C.text2 });
    if (narrow) A.text(svg, 24, 58, "Set up the job › Where it sits on the bed ›", { size: 16, font: "mono", fill: C.copperHi });
    var pathTxt = A.text(svg, 24, narrow ? 82 : 60, "", { size: 16, font: "mono", fill: C.copperHi });
    A.text(svg, 24, H - 18, narrow ? "Top view, to scale · tabs schematic" : "Top view, to scale · 0.8 mm cutter · tabs drawn schematically",
      { size: 15, fill: C.text3 });

    // sheet
    A.el(svg, "rect", { x: X0 - 3 * K, y: Y0 - 3 * K, width: (2 * BW + GAP + 6) * K, height: (BH + 6) * K,
      fill: C.copperFill, stroke: C.copperDim, "stroke-width": 1.5, rx: 2 });
    var gCut = A.el(svg, "g", {});
    var gBoards = A.el(svg, "g", {});
    var gLbl = A.el(svg, "g", {});

    // seam inset
    var IX = narrow ? 24 : 650, IY = narrow ? 428 : 110, IW = narrow ? 472 : 206, IH = narrow ? 160 : 300;
    A.el(svg, "rect", { x: IX, y: IY, width: IW, height: IH, fill: C.panel, stroke: C.ruleStrong, rx: 3 });
    A.text(svg, IX + 12, IY + 26, "THE SEAM, ×6", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var clip = A.el(svg, "clipPath", { id: "butt-clip" });
    A.el(clip, "rect", { x: IX + 1, y: IY + 36, width: IW - 2, height: IH - 37 });
    var gIn = A.el(svg, "g", { "clip-path": "url(#butt-clip)" });
    var inTxt1 = A.text(svg, IX + IW / 2, IY + IH + 26, "", { size: 16, anchor: "middle", fill: C.text });
    var inTxt2 = A.text(svg, IX + IW / 2, IY + IH + 48, "", { size: 15, anchor: "middle", fill: C.text2 });

    var row = A.controls(host);
    var st = A.status(row);
    var mode = null, gapNow = GAP, anim = 0;

    function rectCut(g, x, y, w, h, k, ox, oy, tabs, skipRight, skipLeft) {
      // channel centred half a cutter outside the board edge: a ring of width BIT
      var r = BIT / 2, sw = BIT * k;
      var L = x - r, R = x + w + r, B = y - r, T = y + h + r;
      // sides as [x1,y1,x2,y2] in mm (y up); tab at each side's middle
      var sides = [[L, B, R, B], [R, B, R, T], [R, T, L, T], [L, T, L, B]];
      sides.forEach(function (s, i) {
        if (skipRight && i === 1) return;
        if (skipLeft && i === 3) return;
        var len = Math.hypot(s[2] - s[0], s[3] - s[1]);
        var cuts = tabs ? [[0, len / 2 - TAB / 2], [len / 2 + TAB / 2, len]] : [[0, len]];
        cuts.forEach(function (c) {
          var f0 = c[0] / len, f1 = c[1] / len;
          var ax = s[0] + (s[2] - s[0]) * f0, ay = s[1] + (s[3] - s[1]) * f0;
          var bx = s[0] + (s[2] - s[0]) * f1, by = s[1] + (s[3] - s[1]) * f1;
          A.el(g, "line", { x1: ox + ax * k, y1: oy - ay * k, x2: ox + bx * k, y2: oy - by * k,
            stroke: C.sunk, "stroke-width": sw, "stroke-linecap": "square" });
        });
      });
    }

    function draw(gap, showCut) {
      while (gCut.firstChild) gCut.removeChild(gCut.firstChild);
      while (gBoards.firstChild) gBoards.removeChild(gBoards.firstChild);
      while (gLbl.firstChild) gLbl.removeChild(gLbl.firstChild);
      while (gIn.firstChild) gIn.removeChild(gIn.firstChild);
      var oy = Y0 + BH * K;          // screen y of mm y = 0 (front edge)
      var bx = BW + gap;             // board B's left edge, mm
      var butted = gap < 0.01;
      // boards (the copper that stays)
      [0, bx].forEach(function (x, i) {
        var lose = butted ? BIT / 2 : 0;
        var x1 = x + (i === 1 ? lose : 0), x2 = x + BW - (i === 0 ? lose : 0);
        A.el(gBoards, "rect", { x: X0 + x1 * K, y: oy - BH * K, width: (x2 - x1) * K, height: BH * K,
          fill: C.copper, stroke: C.copperHi, "stroke-width": 1 });
        // a few traces so it reads as a board
        var tx = X0 + (x + 6) * K, ty = oy - 30 * K;
        A.el(gBoards, "path", { d: "M" + tx + "," + ty + " h" + 14 * K + " v" + 12 * K + " h" + 8 * K,
          fill: "none", stroke: C.copperHi, "stroke-width": 3, opacity: 0.8 });
        A.text(gLbl, X0 + (x + BW / 2) * K, oy - 26, i ? "board 2" : "board 1",
          { size: 16, anchor: "middle", fill: C.ink, weight: 700 });
      });
      if (showCut) {
        if (butted) {
          // outer ring of the pair + one channel centred on the seam
          rectCut(gCut, 0, 0, BW, BH, K, X0, oy, true, true, false);
          rectCut(gCut, BW, 0, BW, BH, K, X0, oy, true, false, true);
          // top and bottom of each already drawn; the seam: one channel on x = BW
          var sx = X0 + BW * K;
          [[-BIT / 2, BH / 2 - TAB / 2], [BH / 2 + TAB / 2, BH + BIT / 2]].forEach(function (c) {
            A.el(gCut, "line", { x1: sx, y1: oy - c[0] * K, x2: sx, y2: oy - c[1] * K,
              stroke: C.sunk, "stroke-width": BIT * K, "stroke-linecap": "butt" });
          });
        } else {
          rectCut(gCut, 0, 0, BW, BH, K, X0, oy, true);
          rectCut(gCut, bx, 0, BW, BH, K, X0, oy, true);
        }
      }
      // dimension over the gap
      if (!butted && gap > 0.5) {
        var gx1 = X0 + BW * K, gx2 = X0 + bx * K, gy = Y0 - 3 * K - 10;
        A.el(gLbl, "line", { x1: gx1, y1: gy, x2: gx2, y2: gy, stroke: C.caution, "stroke-width": 2 });
        A.el(gLbl, "line", { x1: gx1, y1: gy - 6, x2: gx1, y2: gy + 6, stroke: C.caution, "stroke-width": 2 });
        A.el(gLbl, "line", { x1: gx2, y1: gy - 6, x2: gx2, y2: gy + 6, stroke: C.caution, "stroke-width": 2 });
        A.text(gLbl, gx2 + 10, gy + 5, gap.toFixed(1) + " mm of waste", { size: 16, fill: C.caution, weight: 600 });
      }
      // inset: 5 mm around the seam, centred at the middle of the gap
      var cx = BW + gap / 2, cy = BH * 0.72;
      var ix = function (mm) { return IX + IW / 2 + (mm - cx) * ZK; };
      var iy = function (mm) { return IY + 36 + (IH - 36) / 2 - (mm - cy) * ZK; };
      A.el(gIn, "rect", { x: IX, y: IY + 36, width: IW, height: IH, fill: C.copperFill });
      var lose2 = butted ? BIT / 2 : 0;
      A.el(gIn, "rect", { x: ix(0), y: iy(BH), width: ix(BW - lose2) - ix(0), height: iy(0) - iy(BH), fill: C.copper });
      A.el(gIn, "rect", { x: ix(bx + lose2), y: iy(BH), width: ix(bx + 40) - ix(bx + lose2), height: iy(0) - iy(BH), fill: C.copper });
      if (showCut) {
        var chans = butted ? [BW] : [BW + BIT / 2, bx - BIT / 2];
        chans.forEach(function (c) {
          A.el(gIn, "rect", { x: ix(c - BIT / 2), y: IY + 36, width: BIT * ZK, height: IH, fill: C.sunk });
        });
      }
      if (butted) {
        // the original edges, dashed: what each board gives up
        [BW, BW].forEach(function (x) {
          A.el(gIn, "line", { x1: ix(x), y1: IY + 40, x2: ix(x), y2: IY + IH, stroke: C.copperHi,
            "stroke-dasharray": "5 5", "stroke-width": 1.5 });
        });
        var ay = iy(cy) + (narrow ? 20 : 60);
        A.arrow(gIn, ix(BW) - 40, ay, ix(BW - BIT / 2) - 2, ay, { color: C.caution, head: 7 });
        A.arrow(gIn, ix(BW) + 40, ay, ix(BW + BIT / 2) + 2, ay, { color: C.caution, head: 7 });
        A.text(gIn, ix(BW) - 44, ay + 6, "0.4 mm", { size: 16, anchor: "end", fill: C.caution, weight: 600 });
        A.text(gIn, ix(BW) + 44, ay + 6, "0.4 mm", { size: 16, fill: C.caution, weight: 600 });
      }
      if (showCut) {
        inTxt1.textContent = butted ? "one channel, shared" : "two channels, waste between";
        inTxt2.textContent = butted ? "each board loses 0.4 mm" : "no copper lost";
      } else {
        inTxt1.textContent = ""; inTxt2.textContent = "";
      }
    }

    function go(m) {
      if (m === mode) return;
      mode = m;
      var from = gapNow, to = m === "butt" ? 0 : GAP;
      pathTxt.textContent = (narrow ? "" : "Set up the job › Where it sits on the bed › ") +
        (m === "butt" ? "Butt them together" : "Lay them side by side");
      st.textContent = m === "butt"
        ? "Butt them together: the boards touch, one cut down the seam separates both, and each loses 0.4 mm along that edge."
        : "Lay them side by side: 4 mm of waste between the boards, and each is cut out all round.";
      var t0 = null;
      cancelAnimationFrame(anim);
      if (A.reduced || from === to) { gapNow = to; draw(to, true); return; }
      function step(now) {
        if (t0 === null) t0 = now;
        var k = A.ease((now - t0) / 900);
        gapNow = A.lerp(from, to, k);
        draw(gapNow, k >= 1);
        if (k < 1) anim = requestAnimationFrame(step);
      }
      anim = requestAnimationFrame(step);
    }

    A.segmented(row, [["side", "Lay them side by side"], ["butt", "Butt them together"]], "butt", go);
    row.appendChild(st);
  });
})();
