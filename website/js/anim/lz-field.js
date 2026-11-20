/* Where on the laser bed. The F1 Ultra's galvo field is weaker towards its edges: the
   field test of 2026-11-19 (20 passes at 100 %, 1000 mm/s) cleared every coupon within
   about 57 mm of the bed's middle and none from 58 mm out. So the proven recipe adds 10
   more passes to the parts of the trenches further than 45 mm from the middle
   (engine/xtool.py: EDGE_PASSES = 10, EDGE_RADIUS_MM = 45, edge_rings), and the run
   reads "Pass k of 30" instead of "of 20". To scale: the 220 mm bed the page draws, its
   middle at (110, 110), the 83 x 69.5 mm example board. Drag the board, or pick a place. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BED = 220, MID = 110, EDGE = 45, FIELD = 57, BW = 83, BH = 69.5;

  // Pseudo-random trench pieces inside the board (board mm), the same every time.
  var TR = [];
  (function () {
    var s = 7;
    function r() { s = (s * 9301 + 49297) % 233280; return s / 233280; }
    // Copper fills the board but not its very corners, as on most boards.
    while (TR.length < 70) {
      var x = 4 + r() * (BW - 8), y = 4 + r() * (BH - 8), h = r() < 0.5, l = 4 + r() * 9;
      var t = h ? [x, y, Math.min(BW - 4, x + l), y] : [x, y, x, Math.min(BH - 4, y + l)];
      if (Math.hypot(t[2] - BW / 2, t[3] - BH / 2) < 43 && Math.hypot(t[0] - BW / 2, t[1] - BH / 2) < 43) TR.push(t);
    }
  })();

  A.define("lz-field", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 770 : 520;
    var S = narrow ? 470 : 440, X0 = narrow ? 25 : 30, Y0 = 44, K = S / BED;
    var svg = A.stage(host, W, H, "The 220 mm laser bed seen from above, its middle, a 45 mm circle beyond which the trenches get 10 extra passes, and the board you place on it");
    A.text(svg, X0, 26, "THE LASER BED, 220 × 220 MM · TO SCALE", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: X0, y: Y0, width: S, height: S, fill: C.sunk, stroke: C.ruleStrong });
    for (var g = 20; g < BED; g += 20) {
      A.el(svg, "line", { x1: X0 + g * K, y1: Y0, x2: X0 + g * K, y2: Y0 + S, stroke: C.rule });
      A.el(svg, "line", { x1: X0, y1: Y0 + g * K, x2: X0 + S, y2: Y0 + g * K, stroke: C.rule });
    }
    var cx = X0 + MID * K, cy = Y0 + MID * K;
    A.el(svg, "circle", { cx: cx, cy: cy, r: EDGE * K, fill: C.okFill, "fill-opacity": 0.6 });
    var board = A.el(svg, "g", { style: "cursor: grab" });
    var sheet = A.el(board, "rect", { x: -6 * K, y: -6 * K, width: (BW + 12) * K, height: (BH + 12) * K, fill: C.copperFill, stroke: C.copperDim, "stroke-width": 1 });
    A.el(board, "rect", { x: 0, y: 0, width: BW * K, height: BH * K, fill: C.copperDim, stroke: C.copper, "stroke-width": 1 });
    var lines = TR.map(function (t) {
      return A.el(board, "line", { x1: t[0] * K, y1: t[1] * K, x2: t[2] * K, y2: t[3] * K, stroke: C.text, "stroke-width": 2.2, "stroke-linecap": "round" });
    });

    var ov = A.el(svg, "g", { "pointer-events": "none" });
    A.el(ov, "circle", { cx: cx, cy: cy, r: FIELD * K, fill: "none", stroke: C.text3, "stroke-width": 1.2, "stroke-dasharray": "3 4" });
    A.el(ov, "circle", { cx: cx, cy: cy, r: EDGE * K, fill: "none", stroke: C.ok, "stroke-width": 1.6 });
    A.el(ov, "line", { x1: cx - 6, y1: cy, x2: cx + 6, y2: cy, stroke: C.ok, "stroke-width": 1.5 });
    A.el(ov, "line", { x1: cx, y1: cy - 6, x2: cx, y2: cy + 6, stroke: C.ok, "stroke-width": 1.5 });
    A.text(ov, cx, cy - EDGE * K + 16, "45 mm", { size: 13, anchor: "middle", fill: C.ok, weight: 600 });
    A.text(ov, cx, cy - FIELD * K - 6, "≈57 mm: the field test's limit", { size: 12, anchor: "middle", fill: C.text3 });

    // Read-out panel
    var PX = narrow ? X0 : X0 + S + 30, PY = narrow ? Y0 + S + 40 : Y0 + 10, PW = W - PX - (narrow ? 25 : 20);
    A.text(svg, PX, PY, "THE RUN WILL READ", { size: 13, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var passT = A.text(svg, PX, PY + 40, "", { size: 30, weight: 700, font: "mono" });
    var sub = A.text(svg, PX, PY + 70, "", { size: 14, fill: C.text2 });
    var sub2 = A.text(svg, PX, PY + 92, "", { size: 14, fill: C.text2 });
    var keyY = PY + (narrow ? 130 : 150);
    [[C.text, "trench: 20 passes"], [C.caution, "beyond 45 mm: 20 + 10 passes"], [C.ok, "the bed's middle, 45 mm round it"]].forEach(function (k, i) {
      A.el(svg, "line", { x1: PX, y1: keyY + i * 24 - 5, x2: PX + 22, y2: keyY + i * 24 - 5, stroke: k[0], "stroke-width": 3 });
      A.text(svg, PX + 32, keyY + i * 24, k[1], { size: 13.5, fill: C.text2 });
    });
    if (!narrow) {
      A.text(svg, PX, keyY + 96, "Drag the board.", { size: 14, fill: C.text3 });
    }

    var pos = { x: MID - BW / 2, y: MID - BH / 2 };
    var row = A.controls(host);
    var seg = A.segmented(row, [["mid", "Near the middle"], ["side", "Off to one side"], ["corner", "In a corner"]], "mid", function (v) {
      if (v === "mid") pos = { x: MID - BW / 2, y: MID - BH / 2 };
      if (v === "side") pos = { x: 128, y: MID - BH / 2 };
      if (v === "corner") pos = { x: 8, y: 8 };
      draw();
    });
    var st = A.status(row);

    function draw() {
      pos.x = A.clamp(pos.x, 6, BED - BW - 6);
      pos.y = A.clamp(pos.y, 6, BED - BH - 6);
      A.set(board, { transform: "translate(" + (X0 + pos.x * K) + " " + (Y0 + pos.y * K) + ")" });
      var far = 0, worst = 0;
      TR.forEach(function (t, i) {
        var d = 0;
        for (var u = 0; u <= 1.0001; u += 0.25) {
          var x = pos.x + t[0] + (t[2] - t[0]) * u, y = pos.y + t[1] + (t[3] - t[1]) * u;
          d = Math.max(d, Math.hypot(x - MID, y - MID));
        }
        worst = Math.max(worst, d);
        var out = d > EDGE;
        if (out) far++;
        A.set(lines[i], { stroke: out ? C.caution : C.text });
      });
      passT.textContent = far ? "Pass k of 30" : "Pass k of 20";
      A.set(passT, { fill: far ? C.caution : C.ok });
      sub.textContent = far ? far + " of " + TR.length + " trenches reach past 45 mm" : "Every trench within 45 mm";
      sub2.textContent = "Furthest copper: " + worst.toFixed(0) + " mm from the middle";
      st.className = "anim-status" + (worst > FIELD ? " caution" : far ? "" : " ok");
      st.textContent = worst > FIELD
        ? "Part of the board is beyond about 57 mm, where the field test cleared nothing even with the extra passes. Move it nearer the middle."
        : far ? "The parts past 45 mm get 10 more passes, after the others: the run takes longer. Nearer the middle is better."
        : "The whole board is inside 45 mm: 20 passes, the proven recipe as it is.";
    }

    // drag
    var drag = null;
    function mm(ev) {
      var pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
      var p = pt.matrixTransform(svg.getScreenCTM().inverse());
      return { x: (p.x - X0) / K, y: (p.y - Y0) / K };
    }
    board.addEventListener("pointerdown", function (ev) {
      var p = mm(ev); drag = { dx: p.x - pos.x, dy: p.y - pos.y };
      board.setPointerCapture(ev.pointerId); board.style.cursor = "grabbing"; ev.preventDefault();
    });
    board.addEventListener("pointermove", function (ev) {
      if (!drag) return;
      var p = mm(ev); pos = { x: p.x - drag.dx, y: p.y - drag.dy }; draw();
    });
    function end() { drag = null; board.style.cursor = "grab"; }
    board.addEventListener("pointerup", end);
    board.addEventListener("pointercancel", end);
    board.style.touchAction = "none";
    draw();
  });
})();
