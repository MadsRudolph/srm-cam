/* Several boards on one sheet, as the setup page does it.
   - Add another board: lands to the right of everything already there, 4 mm clear, its
     front edge level with the panel's (app/panel.py next_slot, PANEL_GAP_MM = 4.0).
     The same folder again is "buck 2", "buck 3" (app/panel.py read_board).
   - Lay them side by side / Butt them together: left to right in list order, the first
     staying where it is, 4 mm apart or touching (app/panel.py arrange_row).
   - Pick a board by clicking it; drag it, or nudge it (arrow keys: 0.1 mm in the app,
     Shift 1 mm; here each press is 1 mm).
   - The files are named after every board: buck+buck_2_traces.nc (gui2/window.py _auto_name).
   - The checks are the app's: the panel check (overlap / shared cut / strip) and whether
     the job is on the copper (0.5 mm rule, engine/cutout.py SHEET_EDGE_MM).
   The sheet is the 150 x 100 mm one from the recording; the board is 34 x 42 mm. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var SW = 150, SH = 100, BW = 34, BH = 42, BIT = 0.8, GAP = 4.0, EDGE = 0.5, COMF = 2 * BIT + 1;

  A.define("pn-sheet", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 800 : 500;
    var K = narrow ? 3.1 : 3.55;                   // px per mm
    var OX = 30, OY = 70;                          // screen of the sheet's back-left corner
    var PX = narrow ? 24 : 600, PY = narrow ? OY + SH * K + 56 : 40, PW = narrow ? W - 48 : 256;
    var svg = A.stage(host, W, H, "A copper sheet with boards on it; add, arrange and move them, and read the checks");
    A.text(svg, OX, 34, "Set up the job › Where it sits on the bed", { size: 16, font: "mono", fill: C.copperHi });
    A.text(svg, OX, 56, "Copper sheet 150 × 100 mm, top view to scale", { size: 15, fill: C.text3 });
    // sheet (copper) and a 10 mm grid on it
    A.el(svg, "rect", { x: OX, y: OY, width: SW * K, height: SH * K, fill: C.copperDim, stroke: C.copper, "stroke-width": 2 });
    for (var gx = 10; gx < SW; gx += 10) A.el(svg, "line", { x1: OX + gx * K, y1: OY, x2: OX + gx * K, y2: OY + SH * K, stroke: C.copper, "stroke-width": 0.6, opacity: 0.35 });
    for (var gy = 10; gy < SH; gy += 10) A.el(svg, "line", { x1: OX, y1: OY + gy * K, x2: OX + SW * K, y2: OY + gy * K, stroke: C.copper, "stroke-width": 0.6, opacity: 0.35 });
    var gCut = A.el(svg, "g", {}), gB = A.el(svg, "g", {}), gSeam = A.el(svg, "g", {});

    // side panel
    A.el(svg, "rect", { x: PX, y: PY, width: PW, height: narrow ? H - PY - 16 : H - PY - 20, fill: C.panel, stroke: C.ruleStrong, rx: 3 });
    A.text(svg, PX + 14, PY + 28, "ON THE SHEET", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var gList = A.el(svg, "g", {});
    var fileT = A.text(svg, PX + 14, PY + (narrow ? 150 : 196), "", { size: 15, font: "mono", fill: C.text });
    A.text(svg, PX + 14, PY + (narrow ? 124 : 170), "THE FILES", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.text(svg, PX + 14, PY + (narrow ? 186 : 240), "THE CHECKS", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var gChk = A.el(svg, "g", {});

    var boards = [], picked = 0;
    function add() {
      var n = boards.length ? boards.length + 1 : 1;
      var name = n === 1 ? "buck" : "buck " + n;
      var b = { name: name, x: 8, y: 10 };
      if (boards.length) {
        var e = extent();
        b.x = e[2] + GAP; b.y = e[1];
      }
      boards.push(b); picked = boards.length - 1;
    }
    function extent() {
      var x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      boards.forEach(function (b) { x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y); x1 = Math.max(x1, b.x + BW); y1 = Math.max(y1, b.y + BH); });
      return [x0, y0, x1, y1];
    }
    function arrange(gap) {
      for (var i = 1; i < boards.length; i++) { boards[i].x = boards[i - 1].x + BW + gap; boards[i].y = boards[i - 1].y; }
    }
    function pairGap(a, b) {
      var dx = Math.max(0, Math.max(a.x, b.x) - Math.min(a.x + BW, b.x + BW));
      var dy = Math.max(0, Math.max(a.y, b.y) - Math.min(a.y + BH, b.y + BH));
      var overlap = Math.min(a.x + BW, b.x + BW) - Math.max(a.x, b.x) > 1e-6 && Math.min(a.y + BH, b.y + BH) - Math.max(a.y, b.y) > 1e-6;
      return { gap: overlap ? 0 : Math.hypot(dx, dy), overlap: overlap };
    }
    function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
    // sheet coordinates: y is measured from the FRONT edge (machine Y), drawn upwards
    function sx(mm) { return OX + mm * K; }
    function sy(mm) { return OY + (SH - mm) * K; }

    function draw() {
      clear(gCut); clear(gB); clear(gSeam); clear(gList); clear(gChk);
      // pairs that share one cut (closer than the bit, side by side)
      var shared = [];
      for (var i = 0; i < boards.length; i++) for (var j = 0; j < boards.length; j++) {
        if (i === j) continue;
        var a = boards[i], b = boards[j], pg = pairGap(a, b);
        if (!pg.overlap && b.x >= a.x + BW - 1e-6 && b.x - (a.x + BW) <= BIT + 1e-6 &&
            Math.min(a.y + BH, b.y + BH) - Math.max(a.y, b.y) > 1) shared.push([i, j, (a.x + BW + b.x) / 2]);
      }
      // cut-out centre lines: half a cutter outside each outline, one shared line in a close seam
      boards.forEach(function (b, i) {
        var r = BIT / 2, L = b.x - r, R = b.x + BW + r, F = b.y - r, T = b.y + BH + r;
        var skipR = shared.some(function (s) { return s[0] === i; }), skipL = shared.some(function (s) { return s[1] === i; });
        var segs = [[L, F, R, F], [L, T, R, T]];
        if (!skipR) segs.push([R, F, R, T]);
        if (!skipL) segs.push([L, F, L, T]);
        segs.forEach(function (s) {
          A.el(gCut, "line", { x1: sx(s[0]), y1: sy(s[1]), x2: sx(s[2]), y2: sy(s[3]), stroke: C.sunk, "stroke-width": Math.max(2, BIT * K), "stroke-linecap": "square" });
        });
      });
      shared.forEach(function (s) {
        var a = boards[s[0]], b = boards[s[1]];
        // drawn over the boards: the shared channel eats 0.4 mm of each
        A.el(gSeam, "line", { x1: sx(s[2]), y1: sy(Math.max(a.y, b.y) - BIT / 2), x2: sx(s[2]), y2: sy(Math.min(a.y + BH, b.y + BH) + BIT / 2), stroke: C.sunk, "stroke-width": Math.max(3, BIT * K) });
      });
      boards.forEach(function (b, i) {
        var g = A.el(gB, "g", { tabindex: 0, role: "button", "aria-label": b.name + (i === picked ? ", picked" : ""), style: "cursor:grab" });
        A.el(g, "rect", { x: sx(b.x), y: sy(b.y + BH), width: BW * K, height: BH * K, fill: C.copper,
          stroke: i === picked ? C.live : C.copperHi, "stroke-width": i === picked ? 3 : 1 });
        var tx = sx(b.x + 6), ty = sy(b.y + 32);
        A.el(g, "path", { d: "M" + tx + "," + ty + " h" + 14 * K + " v" + 12 * K + " h" + 8 * K + " M" + tx + "," + (ty + 20 * K) + " h" + 20 * K,
          fill: "none", stroke: C.copperHi, "stroke-width": 2.5, opacity: 0.85 });
        A.text(g, sx(b.x + BW / 2), sy(b.y + BH) - 8, b.name, { size: 16, anchor: "middle", weight: 700, fill: i === picked ? C.live : C.text });
        g.addEventListener("pointerdown", function (e) { startDrag(e, i); });
        g.addEventListener("focus", function () { if (picked !== i) { picked = i; draw(); focusPicked(); } });
        g.addEventListener("keydown", function (e) {
          var d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }[e.key];
          if (!d) return;
          e.preventDefault();
          nudge(d[0], d[1]);
        });
      });
      // list
      boards.forEach(function (b, i) {
        var y = PY + 56 + i * 24;
        if (narrow && i > 3) return;
        A.text(gList, PX + 14, y, (i === picked ? "▸ " : "   ") + b.name, { size: 16, fill: i === picked ? C.live : C.text, font: "mono" });
        A.text(gList, PX + PW - 14, y, "X " + b.x.toFixed(1) + "  Y " + b.y.toFixed(1), { size: 15, anchor: "end", fill: C.text3, font: "mono" });
      });
      var nm = boards.map(function (b) { return b.name.replace(/ /g, "_"); }).join("+");
      var shown = nm + "_traces.nc";
      fileT.textContent = shown.length > (narrow ? 44 : 28) ? shown.slice(0, narrow ? 41 : 25) + "…" : shown;
      fileT.setAttribute("aria-label", shown);
      // checks
      var checks = [];
      if (boards.length > 1) {
        var worst = null;
        for (var p = 0; p < boards.length; p++) for (var q = p + 1; q < boards.length; q++) {
          var pg2 = pairGap(boards[p], boards[q]);
          var cand = { a: boards[p].name, b: boards[q].name, gap: pg2.gap, overlap: pg2.overlap };
          if (!worst || (cand.overlap && !worst.overlap) || (cand.overlap === worst.overlap && cand.gap < worst.gap)) worst = cand;
        }
        if (worst.overlap) checks.push(["fail", "Two boards overlap", worst.a + " and " + worst.b + ": nothing can be cut."]);
        else if (worst.gap <= BIT + 1e-6) checks.push([(BIT - worst.gap) / 2 >= 0.2 ? "warn" : "ok", "Two boards share one cut", "each loses " + ((BIT - worst.gap) / 2).toFixed(2) + " mm on that edge."]);
        else if (worst.gap < COMF && worst.gap - 2 * BIT > 0) checks.push(["warn", "Two boards are nearly touching", (worst.gap - 2 * BIT).toFixed(2) + " mm strip can jam the cutter."]);
        else checks.push(["ok", "The boards keep clear", "nearest pair " + worst.gap.toFixed(1) + " mm apart."]);
      }
      var e = extent(), over = Math.max(-e[0], -e[1], e[2] - SW, e[3] - SH);
      if (over > EDGE + 1e-9) checks.push(["fail", "The job runs off the copper", "it hangs " + over.toFixed(1) + " mm off the sheet."]);
      else if (over > 1e-9) checks.push(["warn", "The job reaches the edge", "the cut-out skips that side."]);
      else checks.push(["ok", "The job is on the copper", "nearest edge " + (-over).toFixed(1) + " mm to spare."]);
      var cy = PY + (narrow ? 212 : 268);
      checks.forEach(function (c, k) {
        var col = { ok: C.ok, warn: C.caution, fail: C.danger }[c[0]];
        A.el(gChk, "circle", { cx: PX + 20, cy: cy + k * 58 - 5, r: 6, fill: col });
        A.text(gChk, PX + 34, cy + k * 58, c[1], { size: 16, weight: 700, fill: col });
        A.text(gChk, PX + 34, cy + k * 58 + 22, c[2], { size: 15, fill: C.text2 });
      });
      removeBtn.disabled = boards.length < 2;
      addBtn.disabled = boards.length >= 5;
      var bad = checks.filter(function (c) { return c[0] !== "ok"; })[0];
      st.className = "anim-status" + (bad ? (bad[0] === "fail" ? " bad" : " caution") : " ok");
      st.textContent = bad ? bad[1] + ": " + bad[2] : "Everything checks out. Click a board to pick it; drag it, or use the arrows.";
    }

    function focusPicked() {
      var n = gB.children[picked];
      if (n && document.activeElement !== n && host.contains(document.activeElement)) n.focus();
    }
    function nudge(dx, dy) { var b = boards[picked]; b.x = Math.round((b.x + dx) * 10) / 10; b.y = Math.round((b.y + dy) * 10) / 10; draw(); focusPicked(); }

    function toMM(e) {
      var pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
      var p = pt.matrixTransform(svg.getScreenCTM().inverse());
      return [(p.x - OX) / K, SH - (p.y - OY) / K];
    }
    function startDrag(e, i) {
      picked = i;
      var b = boards[i], m0 = toMM(e), bx = b.x, by = b.y;
      e.preventDefault();
      function mv(ev) {
        var m = toMM(ev);
        b.x = Math.round((bx + m[0] - m0[0]) * 2) / 2; b.y = Math.round((by + m[1] - m0[1]) * 2) / 2;
        draw();
      }
      function up() { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); }
      window.addEventListener("pointermove", mv);
      window.addEventListener("pointerup", up);
      draw();
    }

    var row = A.controls(host);
    var addBtn = A.button(row, "Add another board…", function () { add(); draw(); });
    A.button(row, "Lay them side by side", function () { arrange(GAP); draw(); });
    A.button(row, "Butt them together", function () { arrange(0); draw(); });
    var removeBtn = A.button(row, "Take this board off", function () {
      if (boards.length < 2) return;
      boards.splice(picked, 1);
      picked = Math.min(picked, boards.length - 1);
      draw();
    });
    [["←", -1, 0], ["→", 1, 0], ["↑", 0, 1], ["↓", 0, -1]].forEach(function (d) {
      A.button(row, d[0], function () { nudge(d[1], d[2]); }, "key", "Move the picked board 1 mm");
    });
    A.button(row, "Reset", function () { boards = []; add(); draw(); });
    var st = A.status(row);
    add(); add(); add();                      // start with three: room for a lesson on the fourth
    picked = 0;
    draw();
  });
})();
