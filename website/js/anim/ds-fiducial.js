/* Fiducial registration (gerber2rml/engine/fiducial.py, gui2/fiducial.py): after
   the flip the board sits wherever it was put down. Probe the reference holes;
   a rigid fit (rotation + shift, Umeyama, scale locked to 1) maps where a perfect
   flip would have put them onto where they are, and the top traces are warped by
   it. The readout is the worst residual: under 0.05 mm good, under 0.15 usable,
   beyond that re-seat and probe again. Holes: 4 in the waste, 4 mm out from the
   corners (the defaults); 2 uses corners 1 and 3, 3 uses 1, 2 and 4
   (doublesided.py _CORNER_PICK). Board 50 x 36 mm, landed 1.2° and 0.9 mm off:
   illustrative. Residuals are drawn x80. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BW = 50, BH = 36, OFF = 4, EXAG = 80;
  var TH = 1.2 * Math.PI / 180, TX = 0.9, TY = -0.6;          // how it landed
  var NOISE = [[0.006, -0.004], [-0.005, 0.007], [0.004, 0.005], [-0.007, -0.003]];
  var PICK = { 2: [0, 2], 3: [0, 1, 3], 4: [0, 1, 2, 3] };
  var CORN = [[-OFF, -OFF], [BW + OFF, -OFF], [BW + OFF, BH + OFF], [-OFF, BH + OFF]];
  var HOLES = [[9, 8], [21, 27], [38, 12], [44, 30]];         // the board's own holes, design frame
  var TRACES = [[[9, 8], [9, 18], [21, 18], [21, 27]], [[38, 12], [38, 22], [44, 22], [44, 30]]];

  function landed(p, wrong) {
    var x = p[0], y = p[1];
    if (wrong) { x = BW - x; y = BH - y; }                   // the other turn: 180° about the centre
    var cx = BW / 2, cy = BH / 2, c = Math.cos(TH), s = Math.sin(TH);
    return [cx + c * (x - cx) - s * (y - cy) + TX, cy + s * (x - cx) + c * (y - cy) + TY];
  }
  function fit(P, Q) {
    var n = P.length, px = 0, py = 0, qx = 0, qy = 0;
    P.forEach(function (p, i) { px += p[0]; py += p[1]; qx += Q[i][0]; qy += Q[i][1]; });
    px /= n; py /= n; qx /= n; qy /= n;
    var dot = 0, cr = 0;
    P.forEach(function (p, i) {
      var ax = p[0] - px, ay = p[1] - py, bx = Q[i][0] - qx, by = Q[i][1] - qy;
      dot += ax * bx + ay * by; cr += ax * by - ay * bx;
    });
    var th = Math.atan2(cr, dot), c = Math.cos(th), s = Math.sin(th);
    var t = { th: th, tx: qx - (c * px - s * py), ty: qy - (s * px + c * py) };
    t.apply = function (p) { return [c * p[0] - s * p[1] + t.tx, s * p[0] + c * p[1] + t.ty]; };
    return t;
  }

  A.define("ds-fiducial", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 900 : 520;
    var K = narrow ? 6.6 : 7.4;
    var OX = narrow ? 70 : 64, OY = narrow ? 420 : 430;          // screen of design (0,0)
    var svg = A.stage(host, W, H, "Fiducial registration: probe the reference holes, fit, and warp the top traces");
    var g = A.el(svg, "g", {});
    var PX = narrow ? 16 : 548, PY = narrow ? 470 : 16, PW = narrow ? 488 : 316;
    var row = A.controls(host);
    var st = A.status(row);
    var n = 4, measured = [], mis = 0, wrong = false, probing = -1, anim = 0, bitAt = null;

    function S(p) { return [OX + p[0] * K, OY - p[1] * K]; }
    function holesUsed() { return PICK[n]; }
    function measure(i) {
      // Probing near nominal hole i finds whichever hole is there. After the other
      // turn that is the opposite corner's, at the same spot: the fit cannot tell.
      var q = landed(CORN[i], false), e = NOISE[i];
      q = [q[0] + e[0], q[1] + e[1]];
      if (i === 0) q = [q[0] + mis * 0.8, q[1] + mis * 0.6];     // a mis-probe on hole 1
      return q;
    }
    function current() {
      var P = [], Q = [], idx = [];
      holesUsed().forEach(function (i) { if (measured.indexOf(i) >= 0) { P.push(CORN[i]); Q.push(measure(i)); idx.push(i); } });
      if (P.length < 2) return null;
      var t = fit(P, Q), worst = 0, res = {};
      P.forEach(function (p, k) {
        var a = t.apply(p), r = Math.hypot(a[0] - Q[k][0], a[1] - Q[k][1]);
        res[idx[k]] = [Q[k][0] - a[0], Q[k][1] - a[1], r];
        worst = Math.max(worst, r);
      });
      return { t: t, worst: worst, res: res };
    }

    function poly(parent, pts, attrs) {
      attrs.points = pts.map(function (p) { var s = S(p); return s[0] + "," + s[1]; }).join(" ");
      return A.el(parent, "polygon", attrs);
    }
    function outline(f) { return [[0, 0], [BW, 0], [BW, BH], [0, BH]].map(f); }

    function draw() {
      while (g.firstChild) g.removeChild(g.firstChild);
      var F = current();
      // the board as it really landed, with its drilled holes (from the bottom)
      poly(g, outline(function (p) { return landed(p, wrong); }), { fill: C.copperDim, stroke: C.copperHi, "stroke-width": 2 });
      HOLES.forEach(function (h) { var s = S(landed(h, wrong)); A.el(g, "circle", { cx: s[0], cy: s[1], r: 5, fill: C.ink }); });
      // where a perfect flip would have put it
      poly(g, outline(function (p) { return p; }), { fill: "none", stroke: C.text3, "stroke-width": 1.5, "stroke-dasharray": "6 5" });
      // the top traces: nominal (dashed) until fitted, then warped onto the board
      var tf = F ? F.t.apply : function (p) { return p; };
      TRACES.forEach(function (tr) {
        A.el(g, "polyline", { points: tr.map(function (p) { var s = S(tf(p)); return s[0] + "," + s[1]; }).join(" "),
          fill: "none", stroke: F ? C.copperHi : C.text3, "stroke-width": F ? 5 : 2, "stroke-dasharray": F ? null : "4 4", "stroke-linecap": "round" });
      });
      var miss = 0;
      HOLES.forEach(function (h) {
        var s = S(tf(h)), real = landed(h, wrong), d = Math.hypot(tf(h)[0] - real[0], tf(h)[1] - real[1]);
        if (F && d > 0.3) miss++;
        A.el(g, "circle", { cx: s[0], cy: s[1], r: 10, fill: "none", stroke: !F ? C.text3 : d > 0.3 ? C.danger : C.copperHi,
          "stroke-width": F ? 4 : 1.5, "stroke-dasharray": F ? null : "3 3" });
      });
      // the reference holes: nominal pins, and where they were found
      holesUsed().forEach(function (i, k) {
        var nom = S(CORN[i]), real = S(landed(CORN[i], wrong));
        A.el(g, "circle", { cx: real[0], cy: real[1], r: 7, fill: C.ink, stroke: C.copper, "stroke-width": 2 });
        A.el(g, "circle", { cx: nom[0], cy: nom[1], r: 11, fill: "none", stroke: C.caution, "stroke-width": 2, "stroke-dasharray": "4 3" });
        A.text(g, nom[0] + (CORN[i][0] < 0 ? -16 : 16), nom[1] + (CORN[i][1] < 0 ? 22 : -14), String(i + 1),
          { size: 16, weight: 700, anchor: "middle", fill: C.caution });
        if (measured.indexOf(i) >= 0) {
          var m = S(measure(i));
          A.el(g, "path", { d: "M" + (m[0] - 7) + "," + m[1] + " h14 M" + m[0] + "," + (m[1] - 7) + " v14", stroke: C.live, "stroke-width": 2.5 });
          if (F && F.res[i]) {
            var r = F.res[i];
            var ex = -r[0] * K * EXAG, ey = r[1] * K * EXAG, len = Math.hypot(ex, ey), cap = 60;
            if (len > cap) { ex *= cap / len; ey *= cap / len; }
            if (len > 3) A.arrow(g, m[0], m[1], m[0] + ex, m[1] + ey, { color: r[2] < 0.05 ? C.ok : r[2] < 0.15 ? C.caution : C.danger, head: 7 });
          }
        }
      });
      if (bitAt) {
        A.el(g, "circle", { cx: bitAt[0], cy: bitAt[1], r: 0.4 * K + 2, fill: C.steel, stroke: C.ink, "stroke-width": 1.5, opacity: 0.9 });
      }
      A.text(g, 16, 30, "TOP VIEW · the board as it landed", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
      A.text(g, 16, 52, "dashed: where a perfect flip puts it · errors ×" + EXAG, { size: 15, fill: C.text3 });

      // the table
      A.el(g, "rect", { x: PX, y: PY, width: PW, height: narrow ? 410 : 488, rx: 3, fill: C.panel, stroke: C.ruleHi });
      A.text(g, PX + 14, PY + 28, "MEASURE WHERE IT LANDED", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
      A.text(g, PX + 14, PY + 56, "#", { size: 15, fill: C.text3 });
      A.text(g, PX + 44, PY + 56, "found X, Y", { size: 15, fill: C.text3 });
      A.text(g, PX + PW - 14, PY + 56, "error", { size: 15, fill: C.text3, anchor: "end" });
      var y = PY + 84;
      holesUsed().forEach(function (i) {
        A.text(g, PX + 14, y, String(i + 1), { size: 16, weight: 700, fill: C.caution });
        if (measured.indexOf(i) >= 0) {
          var q = measure(i);
          A.text(g, PX + 44, y, q[0].toFixed(2) + ", " + q[1].toFixed(2), { size: 16, font: "mono", fill: C.text });
          var r = F && F.res[i] ? F.res[i][2] : null;
          A.text(g, PX + PW - 14, y, r === null ? "—" : r.toFixed(3), { size: 16, font: "mono", anchor: "end",
            fill: r === null ? C.text3 : r < 0.05 ? C.ok : r < 0.15 ? C.caution : C.danger });
        } else {
          A.text(g, PX + 44, y, probing === i ? "probing…" : "not yet", { size: 15, fill: C.text3 });
        }
        y += 30;
      });
      y += 14;
      A.text(g, PX + 14, y, "Worst-case error", { size: 15, fill: C.text2 });
      var col = !F ? C.text3 : F.worst < 0.05 ? C.ok : F.worst < 0.15 ? C.caution : C.danger;
      A.text(g, PX + PW - 14, y, F ? F.worst.toFixed(3) + " mm" : "—", { size: 20, weight: 700, font: "mono", anchor: "end", fill: col });
      y += 32;
      var lines;
      if (!F) lines = ["Measure two holes: the fit", "is applied as soon as it exists."];
      else if (F.worst < 0.05) lines = ["Good: turned " + (F.t.th * 180 / Math.PI).toFixed(2) + "°, and every", "hole agrees to " + F.worst.toFixed(3) + " mm."];
      else if (F.worst < 0.15) lines = ["Usable, but check it: re-probe", "the worst hole before you cut."];
      else lines = ["Too far out to cut: re-seat", "the board and probe again."];
      lines.forEach(function (l) { A.text(g, PX + 14, y, l, { size: 15, fill: col === C.text3 ? C.text2 : col }); y += 22; });
      if (F && wrong) {
        y += 8;
        A.el(g, "rect", { x: PX + 10, y: y - 18, width: PW - 20, height: 74, rx: 3, fill: C.dangerFill, stroke: C.danger });
        ["The fit looks perfect, and every", "hole misses its pad: flipped the", "other way. Jog-check a drilled hole."]
          .forEach(function (l, k) { A.text(g, PX + 18, y + 2 + k * 21, l, { size: 15, fill: C.danger, weight: 600 }); });
      }
      return { F: F, miss: miss };
    }

    function report(r) {
      var F = r.F;
      if (!F) { st.className = "anim-status"; st.textContent = "The top traces are nominal until you measure: they are drawn where a perfect flip would put them."; return; }
      if (wrong) { st.className = "anim-status bad"; st.textContent = "Corner holes make a symmetric rectangle, so the other turn fits just as well: the number is good and the top would be cut rotated. Pick the Flipped direction you actually do, and jog to a drilled hole before cutting."; return; }
      var used = holesUsed().filter(function (i) { return measured.indexOf(i) >= 0; }).length;
      if (mis > 0 && used === 2 && F.worst < 0.05) { st.className = "anim-status caution"; st.textContent = "Hole 1 is mis-probed, but with only two holes the error hides inside the fit. Four holes let one bad measurement show up as a residual."; return; }
      st.className = "anim-status " + (F.worst < 0.05 ? "ok" : F.worst < 0.15 ? "caution" : "bad");
      st.textContent = "Fitted from " + used + " holes: the top traces are warped onto the board where it really is. Next: probe this face on Level the bed, then Write the top traces and the cut-out.";
    }
    function redraw() { report(draw()); }

    function findNext() {
      var todo = holesUsed().filter(function (i) { return measured.indexOf(i) < 0; });
      if (!todo.length || probing >= 0) return;
      var i = todo[0], target = S(landed(CORN[i], wrong)), from = bitAt || [OX + BW / 2 * K, OY - BH / 2 * K];
      probing = i;
      if (A.reduced) { measured.push(i); probing = -1; bitAt = target; redraw(); return; }
      var t0 = null;
      function stp(now) {
        if (t0 === null) t0 = now;
        var q = Math.min((now - t0) / 1100, 1), e = A.ease(q);
        bitAt = [A.lerp(from[0], target[0], e) + (q > 0.7 ? Math.sin(q * 60) * 3 : 0), A.lerp(from[1], target[1], e)];
        draw();
        if (q < 1) anim = requestAnimationFrame(stp);
        else { measured.push(i); probing = -1; redraw(); }
      }
      anim = requestAnimationFrame(stp);
    }
    function reset() { cancelAnimationFrame(anim); measured = []; probing = -1; bitAt = null; redraw(); }

    A.button(row, "Find it for me", findNext, "primary", "Probe the next reference hole: the bit walks its edges and finds the centre");
    A.button(row, "Measure them all", function () {
      cancelAnimationFrame(anim); probing = -1;
      holesUsed().forEach(function (i) { if (measured.indexOf(i) < 0) measured.push(i); });
      bitAt = null; redraw();
    });
    A.button(row, "Start over", reset);
    A.segmented(row, [[2, "2 holes"], [3, "3"], [4, "4"]], 4, function (v) { n = v; reset(); });
    A.slider(row, "Mis-probe hole 1 by", 0, 0.3, 0.01, 0, function (v) { mis = v; if (st) redraw(); }, function (v) { return v.toFixed(2) + " mm"; });
    var wl = document.createElement("label");
    wl.className = "anim-slider";
    wl.style.flex = "0 1 auto";
    var wc = document.createElement("input");
    wc.type = "checkbox";
    wc.addEventListener("change", function () { wrong = wc.checked; reset(); });
    var wt = document.createElement("span");
    wt.className = "k";
    wt.textContent = "Flipped the other way";
    wl.appendChild(wc); wl.appendChild(wt);
    row.appendChild(wl);
    row.appendChild(st);
    redraw();
  });
})();
