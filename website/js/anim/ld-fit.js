/* Drill a board made elsewhere (gui2/boardfit.py, engine/boardfit.py): the laser-etched
   board is clamped anywhere; the picture is dragged roughly onto it. Suggest three
   picks three holes far apart and out of line. Each is measured by which pin it is
   (Find it for me, or centre by eye and Capture); after two, Go to it aims by the fit.
   At three the rigid fit (engine/fiducial.py) is applied and every hole moves onto the
   real board. Worst pad: good < 0.10 mm, too far out >= 0.25 (GOOD, USABLE). With the
   picture mirrored against the board the same three pins cannot be fitted rigidly and
   the worst pad comes out in millimetres; two pads alone would fit a mirror too.
   Board 60 x 44 mm lying 2.4° turned: illustrative. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BW = 60, BH = 44;
  var HOLES = [[6, 6], [6, 14], [6, 22], [18, 10], [26, 10], [34, 10], [42, 10], [50, 36], [54, 30], [54, 22],
    [30, 30], [30, 36], [22, 36], [14, 36], [42, 26], [46, 16]];
  var REAL = { th: 2.4 * Math.PI / 180, tx: 14.6, ty: 9.2 };           // where the board really is
  var PIC = { th: 0, tx: 16.5, ty: 7.8 };                               // where the picture was dragged
  var NOISE = [[0.012, -0.008], [-0.009, 0.014], [0.006, 0.011]];

  function place(T, p, mir) {
    var x = mir ? BW - p[0] : p[0], y = p[1], c = Math.cos(T.th), s = Math.sin(T.th);
    return [c * x - s * y + T.tx, s * x + c * y + T.ty];
  }
  function fit(P, Q) {
    var n = P.length, px = 0, py = 0, qx = 0, qy = 0;
    P.forEach(function (p, i) { px += p[0]; py += p[1]; qx += Q[i][0]; qy += Q[i][1]; });
    px /= n; py /= n; qx /= n; qy /= n;
    var dot = 0, cr = 0;
    P.forEach(function (p, i) { var ax = p[0] - px, ay = p[1] - py, bx = Q[i][0] - qx, by = Q[i][1] - qy; dot += ax * bx + ay * by; cr += ax * by - ay * bx; });
    var th = Math.atan2(cr, dot), c = Math.cos(th), s = Math.sin(th);
    var tx = qx - (c * px - s * py), ty = qy - (s * px + c * py);
    return { th: th, apply: function (p) { return [c * p[0] - s * p[1] + tx, s * p[0] + c * p[1] + ty]; } };
  }
  function suggest() {
    // far apart and well out of line: the widest triangle
    var best = null, bestA = -1;
    for (var i = 0; i < HOLES.length; i++) for (var j = i + 1; j < HOLES.length; j++) for (var k = j + 1; k < HOLES.length; k++) {
      var a = Math.abs((HOLES[j][0] - HOLES[i][0]) * (HOLES[k][1] - HOLES[i][1]) - (HOLES[k][0] - HOLES[i][0]) * (HOLES[j][1] - HOLES[i][1]));
      if (a > bestA) { bestA = a; best = [i, j, k]; }
    }
    return best;
  }

  A.define("ld-fit", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 860 : 500;
    var svg = A.stage(host, W, H, "Three measured pads fit the drill pattern onto a laser-etched board");
    var VX = 16, VY = 16, VW = narrow ? 488 : 560, VH = narrow ? 470 : 468;
    var K = narrow ? 5.6 : 6.4;
    var OX = VX + 22 - 8 * K, OY = VY + VH - 26 + 4 * K;
    function S(p) { return [OX + p[0] * K, OY - p[1] * K]; }
    var PX = narrow ? 16 : 592, PY = narrow ? 502 : 16, PW = narrow ? 488 : 272;
    A.el(svg, "rect", { x: VX, y: VY, width: VW, height: VH, rx: 3, fill: C.sunk, stroke: C.ruleHi });
    A.text(svg, VX + 12, VY + 26, "THE BED · top view, to scale", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var g = A.el(svg, "g", {});
    var row = A.controls(host);
    var st = A.status(row);
    var pads = [], meas = {}, mirror = false, bit = null, anim = 0;

    function nominal(i) { return place(PIC, HOLES[i], mirror); }
    function real(i) { return place(REAL, HOLES[i], false); }
    function current() {
      var P = [], Q = [], ids = [];
      pads.forEach(function (i) { if (meas[i]) { P.push(nominal(i)); Q.push(meas[i]); ids.push(i); } });
      if (P.length < 2) return null;
      var t = fit(P, Q), worst = 0;
      P.forEach(function (p, k) { var a = t.apply(p); worst = Math.max(worst, Math.hypot(a[0] - Q[k][0], a[1] - Q[k][1])); });
      return { t: t, n: P.length, worst: worst };
    }
    function outline(M) {
      return [[0, 0], [BW, 0], [BW, BH], [0, BH]].map(function (p) { return S(M(p)).join(","); }).join(" ");
    }

    function draw() {
      while (g.firstChild) g.removeChild(g.firstChild);
      var F = current(), applied = F && F.n >= 3;
      // the real laser board with its etched pads
      A.el(g, "polygon", { points: outline(function (p) { return place(REAL, p, false); }), fill: "#5d3f22", stroke: C.copperHi, "stroke-width": 1.5 });
      HOLES.forEach(function (h, i) {
        var s = S(real(i));
        A.el(g, "circle", { cx: s[0], cy: s[1], r: 1.0 * K, fill: C.copper });
        A.el(g, "circle", { cx: s[0], cy: s[1], r: 0.25 * K, fill: "#3a2614" });
      });
      // the holes to drill: where the picture puts them, or where the fit moved them
      var M = applied ? function (p) { return F.t.apply(p); } : function (p) { return p; };
      A.el(g, "polygon", { points: outline(function (p) { return M(place(PIC, p, mirror)); }), fill: "none", stroke: applied ? C.ok : C.live, "stroke-width": 1.5, "stroke-dasharray": "7 5" });
      var worstHit = 0;
      HOLES.forEach(function (h, i) {
        var q = M(nominal(i)), s = S(q), off = Math.hypot(q[0] - real(i)[0], q[1] - real(i)[1]);
        worstHit = Math.max(worstHit, off);
        var ok = off < 0.4;
        A.el(g, "circle", { cx: s[0], cy: s[1], r: 0.4 * K, fill: "none", stroke: applied ? (ok ? C.ok : C.danger) : C.live, "stroke-width": 2 });
      });
      pads.forEach(function (i, k) {
        var s = S(nominal(i));
        var lab = S(M(nominal(i)));
        A.text(g, lab[0] + 10, lab[1] - 10, String(k + 1), { size: 16, weight: 700, fill: C.caution });
        if (meas[i]) { var m = S(meas[i]); A.el(g, "path", { d: "M" + (m[0] - 8) + "," + m[1] + " h16 M" + m[0] + "," + (m[1] - 8) + " v16", stroke: C.caution, "stroke-width": 2.5 }); }
      });
      if (bit) { var b = S(bit); A.el(g, "circle", { cx: b[0], cy: b[1], r: 0.4 * K + 3, fill: C.steel, "fill-opacity": 0.6, stroke: C.text, "stroke-width": 2 }); }
      // legend
      var ly = VY + VH - 14;
      A.el(g, "circle", { cx: VX + 20, cy: ly - 5, r: 6, fill: C.copper });
      A.text(g, VX + 32, ly, "etched pads (the real board)", { size: 15, fill: C.text2 });
      A.el(g, "circle", { cx: VX + (narrow ? 270 : 290), cy: ly - 5, r: 6, fill: "none", stroke: applied ? C.ok : C.live, "stroke-width": 2 });
      A.text(g, VX + (narrow ? 282 : 302), ly, applied ? "holes, fitted" : "holes, as dragged", { size: 15, fill: C.text2 });

      // the panel
      A.el(g, "rect", { x: PX, y: PY, width: PW, height: narrow ? 330 : 468, rx: 3, fill: C.panel, stroke: C.ruleHi });
      A.text(g, PX + 14, PY + 28, "THE PADS TO MEASURE", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
      var y = PY + 60;
      if (!pads.length) { A.text(g, PX + 14, y, "Suggest three, first.", { size: 15, fill: C.text3 }); y += 30; }
      pads.forEach(function (i, k) {
        A.text(g, PX + 14, y, String(k + 1), { size: 16, weight: 700, fill: C.caution });
        A.text(g, PX + 40, y, meas[i] ? meas[i][0].toFixed(2) + ", " + meas[i][1].toFixed(2) : "not yet", { size: 16, font: meas[i] ? "mono" : "sans", fill: meas[i] ? C.text : C.text3 });
        y += 30;
      });
      y += 10;
      A.text(g, PX + 14, y, "Worst pad", { size: 15, fill: C.text2 });
      var col = !applied ? C.text3 : F.worst < 0.10 ? C.ok : F.worst < 0.25 ? C.caution : C.danger;
      A.text(g, PX + PW - 14, y, applied ? F.worst.toFixed(3) + " mm" : "—", { size: 19, weight: 700, font: "mono", anchor: "end", fill: col });
      y += 30;
      var lines = !applied ? (F ? ["Two pads: Go to it now aims", "by the fit. One more."] : ["At three pads the fit", "is applied."])
        : F.worst < 0.10 ? ["Good: turned " + (F.t.th * 180 / Math.PI).toFixed(2) + "°, every pad", "agrees within " + F.worst.toFixed(3) + " mm."]
        : F.worst < 0.25 ? ["Usable, but re-measure", "the worst pad."]
        : ["Too far out to drill: a pad", "mis-measured, or the picture", "is mirrored. Check Mirror."];
      lines.forEach(function (l) { A.text(g, PX + 14, y, l, { size: 15, fill: col === C.text3 ? C.text2 : col }); y += 22; });
      return { F: F, applied: applied, worstHit: worstHit };
    }

    function report(r) {
      if (!pads.length) { st.className = "anim-status"; st.textContent = "The picture was dragged roughly onto the board. Suggest three picks pads far apart and out of line."; return; }
      var n = pads.filter(function (i) { return meas[i]; }).length;
      if (!r.applied) { st.className = "anim-status"; st.textContent = "Pad " + (n + 1) + ": Go to it, then Find it for me (from about 2 mm above), or centre by eye and Capture. Measure it by which pin it is, not where it sits in the picture."; return; }
      if (r.F.worst >= 0.25) { st.className = "anim-status bad"; st.textContent = "The picture is mirrored against the board: no rigid turn and shift puts these three pins on their pads. Toggle Mirror for bottom-up milling under Set up the job and measure again."; return; }
      st.className = "anim-status ok";
      st.textContent = "Fitted: every hole moved onto the real board (green). Write the drill file writes <name>_drill_fitted.nc. Don't move the board or reset XY now.";
    }
    function redraw() { report(draw()); }

    function moveBit(to, then) {
      cancelAnimationFrame(anim);
      var from = bit || [to[0] - 20, to[1] - 14];
      if (A.reduced) { bit = to; if (then) then(); redraw(); return; }
      var t0 = null;
      function stp(now) {
        if (t0 === null) t0 = now;
        var q = A.ease(Math.min((now - t0) / 900, 1));
        bit = [A.lerp(from[0], to[0], q), A.lerp(from[1], to[1], q)]; draw();
        if (q < 1) anim = requestAnimationFrame(stp); else { if (then) then(); redraw(); }
      }
      anim = requestAnimationFrame(stp);
    }
    function nextPad() { for (var k = 0; k < pads.length; k++) if (!meas[pads[k]]) return k; return -1; }
    function goTo() {
      var k = nextPad(); if (k < 0) return;
      var i = pads[k], F = current();
      moveBit(F ? F.t.apply(nominal(i)) : nominal(i));
    }
    function findIt() {
      var k = nextPad(); if (k < 0) return;
      var i = pads[k], r = real(i), e = NOISE[k];
      moveBit([r[0] + e[0], r[1] + e[1]], function () { meas[i] = bit.slice(); });
    }

    A.button(row, "Suggest three", function () { pads = suggest(); meas = {}; bit = null; redraw(); });
    A.button(row, "Go to it", goTo);
    A.button(row, "Find it for me", findIt, "primary");
    A.button(row, "Start over", function () { cancelAnimationFrame(anim); pads = []; meas = {}; bit = null; redraw(); });
    var wl = document.createElement("label");
    wl.className = "anim-slider"; wl.style.flex = "0 1 auto";
    var wc = document.createElement("input"); wc.type = "checkbox";
    wc.addEventListener("change", function () { mirror = wc.checked; meas = {}; bit = null; redraw(); });
    var wt = document.createElement("span"); wt.className = "k"; wt.textContent = "Picture mirrored against the board";
    wl.appendChild(wc); wl.appendChild(wt); row.appendChild(wl);
    row.appendChild(st);
    redraw();
  });
})();
