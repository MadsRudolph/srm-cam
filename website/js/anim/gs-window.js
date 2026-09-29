/* The SRM-CAM window, drawn as its four regions that never move: the rail, the
   stage, the inspector and the machine bar (plus the header's frame switch).
   Tap a region to read what it is for; tap a step on the rail and the stage
   draws that step's toolpath, as the app does. A tour highlights each region in
   turn until the reader takes over. The step names and order are the app's
   (gui2/runplan.py) for the lab's one-bit profile. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C, SELECT = "#243040";

  var REGIONS = {
    rail: ["The rail", "The run plan: the same order, and the same files, the export writes. Numbered steps are files you send; the rows between them (fit the bit, set the Z origin) are things you do by hand. Click any step, any time. The worst finding stays on the red banner; Export the job is at the bottom."],
    stage: ["The stage", "The bed in machine coordinates: the copper sheet, the board, and the toolpath of the selected step. Drag the board, or nudge it with the arrow keys (0.1 mm; Shift 1 mm, Ctrl 0.01 mm). Scroll to zoom, right-drag to pan."],
    inspector: ["The inspector", "The selected step: the setup page, the checks, or a step's file, time and (in the Full tier) its cutting parameters."],
    bar: ["The machine bar", "Always there: Connect, the position readout, Z jog, Probe Z and Zero Z, Spindle, Click to jog, and STOP. Esc stops the machine from anywhere, even with a dialog open."],
    head: ["The header", "Bed — as cut is the only frame the machine understands. Design X-ray shows the board as KiCad drew it, for checking that the two faces of a double-sided board register."]
  };
  // [short label, ordinal or null, key, inspector title]
  var STEPS = [
    ["Set up the job", null, "setup", "Set up the job"],
    ["Check before cutting", null, "checks", "Check before cutting"],
    ["· Fit the bit, zero Z", null, "origin", "By hand: fit the bit, set the Z origin"],
    ["Dry run", 0, "airpass", "0 · Dry run"],
    ["Drill", 1, "drill", "1 · Drill"],
    ["Isolation traces", 2, "traces", "2 · Isolation traces"],
    ["Cut the board out", 3, "cutout", "3 · Cut the board out"],
    ["Level the bed", null, "level", "Level the bed"]
  ];

  A.define("gs-window", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 520 : 880, H = narrow ? 760 : 520;
    var s = A.stage(host, W, H, "The SRM-CAM window: the rail on the left, the stage in the middle, the inspector on the right, the machine bar along the bottom");
    var fs = narrow ? 17 : 15;              // step text
    // layout
    var L = narrow
      ? { x0: 10, x1: 510, hy: 10, hh: 44, ry: 54, rw: 210, ix: 0, iw: 0, by: 700, bh: 50 }
      : { x0: 10, x1: 870, hy: 10, hh: 44, ry: 54, rw: 220, ix: 650, iw: 220, by: 460, bh: 50 };
    var stageX = L.x0 + L.rw, stageW = (narrow ? L.x1 : L.ix) - stageX;
    var stageY = L.ry, stageH = (narrow ? 470 : L.by - L.ry);
    if (narrow) { L.ix = L.x0; L.iw = L.x1 - L.x0; }
    var inspY = narrow ? stageY + stageH : L.ry, inspH = narrow ? L.by - inspY : L.by - L.ry;

    A.el(s, "rect", { x: L.x0, y: L.hy, width: L.x1 - L.x0, height: L.by + L.bh - L.hy, rx: 8, fill: C.base, stroke: C.ruleStrong, "stroke-width": 2 });

    var groups = {};
    function region(key, x, y, w, h) {
      var g = A.el(s, "g", { tabindex: 0, role: "button", "aria-label": REGIONS[key][0], style: "cursor:pointer;outline:none" });
      var r = A.el(g, "rect", { x: x, y: y, width: w, height: h, fill: C.panel, stroke: C.rule, "stroke-width": 1 });
      var hl = A.el(s, "rect", { x: x + 2, y: y + 2, width: w - 4, height: h - 4, fill: "none", stroke: C.copperHi, "stroke-width": 3, rx: 3, opacity: 0, "pointer-events": "none" });
      g.addEventListener("click", function () { take(); pick(key); });
      g.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); take(); pick(key); } });
      g.addEventListener("focus", function () { take(); pick(key); });
      groups[key] = { g: g, r: r, hl: hl };
      return g;
    }

    // header
    var hg = region("head", L.x0, L.hy, L.x1 - L.x0, L.hh);
    A.text(hg, L.x0 + 14, L.hy + 29, "SRM·CAM", { size: 18, weight: 700, font: "label" });
    var segX = L.x0 + (narrow ? 118 : 140);
    A.el(hg, "rect", { x: segX, y: L.hy + 10, width: narrow ? 120 : 130, height: 24, rx: 3, fill: SELECT, stroke: "#3d5069" });
    A.text(hg, segX + (narrow ? 60 : 65), L.hy + 27, "Bed — as cut", { size: 14, anchor: "middle", weight: 600 });
    A.el(hg, "rect", { x: segX + (narrow ? 124 : 134), y: L.hy + 10, width: narrow ? 120 : 130, height: 24, rx: 3, fill: C.panelHi, stroke: C.ruleStrong });
    A.text(hg, segX + (narrow ? 184 : 199), L.hy + 27, "Design X-ray", { size: 14, anchor: "middle", fill: C.text2 });

    // rail
    var rg = region("rail", L.x0, L.ry, L.rw, (narrow ? stageY + stageH : L.by) - L.ry);
    A.el(rg, "rect", { x: L.x0 + 8, y: L.ry + 8, width: L.rw - 16, height: 30, rx: 3, fill: C.dangerFill, stroke: "#5e1f22" });
    A.el(rg, "circle", { cx: L.x0 + 22, cy: L.ry + 23, r: 5, fill: C.danger });
    A.text(rg, L.x0 + 34, L.ry + 28, "13 spots will be shorted", { size: 14, fill: C.danger });
    var rowH = narrow ? 44 : 38, rows = [];
    var railBottom = (narrow ? stageY + stageH : L.by);
    STEPS.forEach(function (st, i) {
      var y = L.ry + 48 + i * rowH;
      var row = A.el(s, "g", { tabindex: 0, role: "button", "aria-label": "Rail step: " + st[0], style: "cursor:pointer;outline:none" });
      var bg = A.el(row, "rect", { x: L.x0 + 2, y: y, width: L.rw - 4, height: rowH - 2, fill: "transparent" });
      if (st[1] !== null) A.text(row, L.x0 + 12, y + rowH / 2 + 7, String(st[1]), { size: 20, weight: 700, fill: C.text3, font: "label" });
      A.text(row, L.x0 + (st[1] !== null ? 36 : (st[2] === "origin" ? 30 : 14)), y + rowH / 2 + 5, st[0],
        { size: st[2] === "origin" ? fs - 2 : fs, fill: st[2] === "origin" ? C.text2 : C.text });
      row.addEventListener("click", function (e) { e.stopPropagation(); take(); select(i); });
      row.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); take(); select(i); } });
      rows.push(bg);
    });
    A.el(rg, "rect", { x: L.x0 + 8, y: railBottom - 40, width: L.rw - 16, height: 30, rx: 3, fill: C.primary || C.text });
    A.text(rg, L.x0 + L.rw / 2, railBottom - 20, "Export the job", { size: 15, anchor: "middle", fill: C.ink, weight: 600 });
    // bring step rows above the region rect
    rows.forEach(function (r) { s.appendChild(r.parentNode); });

    // stage
    var sg = region("stage", stageX, stageY, stageW, stageH);
    A.el(sg, "rect", { x: stageX, y: stageY, width: stageW, height: stageH, fill: C.sunk });
    for (var gx = stageX + 20; gx < stageX + stageW; gx += 30) A.el(sg, "line", { x1: gx, y1: stageY, x2: gx, y2: stageY + stageH, stroke: C.rule });
    for (var gy = stageY + 20; gy < stageY + stageH; gy += 30) A.el(sg, "line", { x1: stageX, y1: gy, x2: stageX + stageW, y2: gy, stroke: C.rule });
    var bw = Math.min(stageW - 70, 300), bh = Math.min(stageH - 70, 230);
    var bx = stageX + (stageW - bw) / 2, by = stageY + (stageH - bh) / 2;
    A.el(sg, "rect", { x: bx - 18, y: by - 18, width: bw + 36, height: bh + 36, fill: C.copperFill, stroke: C.copperDim });
    A.el(sg, "rect", { x: bx, y: by, width: bw, height: bh, rx: 10, fill: "none", stroke: C.text3, "stroke-width": 1.5 });
    // a small board: pads and tracks, in board units 0..1
    var PADS = [[0.15, 0.2], [0.85, 0.2], [0.15, 0.8], [0.85, 0.8], [0.5, 0.35], [0.5, 0.65], [0.3, 0.5], [0.7, 0.5]];
    var TRACKS = [[[0.15, 0.2], [0.3, 0.2], [0.3, 0.5]], [[0.85, 0.2], [0.7, 0.2], [0.7, 0.5]], [[0.15, 0.8], [0.5, 0.8], [0.5, 0.65]],
      [[0.85, 0.8], [0.85, 0.5], [0.7, 0.5]], [[0.3, 0.5], [0.5, 0.5], [0.5, 0.35]]];
    function P(p) { return [bx + p[0] * bw, by + p[1] * bh]; }
    var art = A.el(sg, "g", {});
    function drawStep(key) {
      while (art.firstChild) art.removeChild(art.firstChild);
      var trackCol = C.copperHi;
      TRACKS.forEach(function (t) {
        A.el(art, "polyline", { points: t.map(function (p) { return P(p).join(","); }).join(" "), fill: "none", stroke: trackCol, "stroke-width": 7, "stroke-linejoin": "round", opacity: key === "traces" ? 0.35 : 0.8 });
      });
      PADS.forEach(function (p) { var q = P(p); A.el(art, "circle", { cx: q[0], cy: q[1], r: 9, fill: C.copperHi, opacity: 0.85 }); });
      if (key === "traces") {
        TRACKS.forEach(function (t) {
          A.el(art, "polyline", { points: t.map(function (p) { return P(p).join(","); }).join(" "), fill: "none", stroke: C.live, "stroke-width": 16, "stroke-linejoin": "round", opacity: 0.28 });
        });
        PADS.forEach(function (p) { var q = P(p); A.el(art, "circle", { cx: q[0], cy: q[1], r: 16, fill: "none", stroke: C.live, "stroke-width": 2 }); });
      }
      if (key === "drill") PADS.forEach(function (p) { var q = P(p); A.el(art, "circle", { cx: q[0], cy: q[1], r: 5, fill: C.live }); });
      if (key === "cutout") {
        A.el(art, "rect", { x: bx - 5, y: by - 5, width: bw + 10, height: bh + 10, rx: 13, fill: "none", stroke: C.live, "stroke-width": 3, "stroke-dasharray": (bw / 2 - 8) + " 16" });
      }
      if (key === "airpass") {
        A.el(art, "rect", { x: bx - 5, y: by - 5, width: bw + 10, height: bh + 10, rx: 13, fill: "none", stroke: C.text2, "stroke-width": 2, "stroke-dasharray": "6 6" });
      }
      if (key === "level") {
        [0.1, 0.5, 0.9].forEach(function (u) { [0.12, 0.5, 0.88].forEach(function (v) { var q = P([u, v]); A.el(art, "circle", { cx: q[0], cy: q[1], r: 6, fill: C.ok }); }); });
      }
      if (key === "checks") {
        var q = P([0.5, 0.5]);
        A.text(art, q[0] + 10, q[1] - 12, "✕", { size: 22, fill: C.danger, weight: 700 });
      }
    }

    // inspector
    var ig = region("inspector", L.ix, inspY, L.iw, inspH);
    A.text(ig, L.ix + 14, inspY + 24, "STEP", { size: 12, fill: C.text3, weight: 700, spacing: 1 });
    var inspTitle = A.text(ig, L.ix + 14, inspY + 48, "", { size: narrow ? 18 : 16, weight: 600 });
    var bars = A.el(ig, "g", {});
    var nb = narrow ? 4 : 7;
    for (var k = 0; k < nb; k++) {
      A.el(bars, "rect", { x: L.ix + 14, y: inspY + 66 + k * 30, width: 70, height: 9, rx: 3, fill: C.raised });
      A.el(bars, "rect", { x: L.ix + 94, y: inspY + 62 + k * 30, width: L.iw - 110, height: 16, rx: 3, fill: C.panelHi, stroke: C.ruleHi });
    }

    // machine bar
    var mg = region("bar", L.x0, L.by, L.x1 - L.x0, L.bh);
    var bx0 = L.x0 + 12;
    [["Connect", 74], ["X 60.52", 70], ["Y 24.42", 70], ["Z −38.00", 78], ["Probe Z", 66], ["Zero Z", 58]].forEach(function (b, i) {
      if (narrow && i > 3) return;
      A.el(mg, "rect", { x: bx0, y: L.by + 12, width: b[1], height: 26, rx: 3, fill: i ? C.panelHi : C.raised, stroke: C.ruleStrong });
      A.text(mg, bx0 + b[1] / 2, L.by + 30, b[0], { size: 13, anchor: "middle", font: i && i < 4 ? "mono" : "sans", fill: C.text });
      bx0 += b[1] + 8;
    });
    A.el(mg, "rect", { x: L.x1 - 84, y: L.by + 10, width: 72, height: 30, rx: 3, fill: C.danger });
    A.text(mg, L.x1 - 48, L.by + 31, "STOP", { size: 16, anchor: "middle", weight: 700, fill: "#fff", font: "label" });

    // highlight rectangles above everything
    ["head", "rail", "stage", "inspector", "bar"].forEach(function (k) { s.appendChild(groups[k].hl); });

    var row = A.controls(host);
    var st = A.status(row);
    var cur = null, sel = 4, touring = true;

    function pick(key) {
      cur = key;
      Object.keys(groups).forEach(function (k) { groups[k].hl.setAttribute("opacity", k === key ? 1 : 0); });
      st.innerHTML = "<strong>" + REGIONS[key][0] + ".</strong> " + REGIONS[key][1];
    }
    function select(i) {
      sel = i;
      rows.forEach(function (r, j) { r.setAttribute("fill", j === i ? SELECT : "transparent"); });
      inspTitle.textContent = STEPS[i][3];
      drawStep(STEPS[i][2]);
      if (!touring) {
        st.innerHTML = "<strong>" + STEPS[i][0].replace("· ", "") + ".</strong> " + ({
          setup: "The board, the tool profile, the copper and where the job sits on the bed.",
          checks: "Every finding, marked on the stage too: here a spot where two nets are closer than the bit.",
          origin: "A hand step, not a file: fit the bit and set the Z origin on the copper, in G54. X and Y stay at the machine origin.",
          airpass: "Step 0, the dry run: spindle off, bit 5 mm up, tracing the outline so you can see the job is on the copper.",
          drill: "Step 1 on a one-bit job: every hole, with the same 0.8 mm bit; the bigger ones milled as circles.",
          traces: "Step 2: a channel around every copper feature, so the nets stop touching.",
          cutout: "Step 3, always last: the outline with four tabs. It frees the board.",
          level: "When you need it: probe a grid over the board, and every cut follows the measured surface."
        })[STEPS[i][2]];
      }
    }
    function take() { touring = false; }
    select(4);
    pick("rail");

    var order = ["rail", "stage", "inspector", "bar", "head"];
    A.loop(host, function (t) {
      if (!touring) return;
      var k = Math.floor(t / 3.2) % order.length;
      if (order[k] !== cur) pick(order[k]);
      var si = 3 + Math.floor(t / 1.6) % 4;          // walk the numbered steps
      if (si !== sel) select(si);
    }, 0);
    A.button(row, "Tour again", function () { touring = true; }, "", "Replay the tour of the regions");
  });
})();
