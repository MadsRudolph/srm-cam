/* The laser page's Focus map, in section. The F1 Ultra's head does not move
   in X or Y: the galvo steers the beam, and only Z changes. Focus map measures
   the height with the blue dot at a grid over the job - corners, edges and the
   middle, 3 mm in from its edge, about 30 mm apart, kept 1.5 mm clear of every
   hole (engine/laser_focus.py: grid_points, safe_area). If the heights spread
   no more than twice the tolerance (+-0.3 mm, the field test of 2026-11-19),
   the job is one run; otherwise it is split into bands no deeper than 0.6 mm,
   from the lowest up, and the head is moved to each band's middle before it
   is etched (plan_zones). A 100 mm board, heights drawn x20. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var TOL = 0.3, BOARD = 100, SAMPLES = 120;
  var HOLES = [26, 74], HOLE_D = 3.2, HOLE_CLEAR = 1.5;
  var GRID = [3, 26.5, 50, 73.5, 97];          // where the grid puts the points
  var T_START = 0.6, T_POINT = 0.75, T_MAP = 1.2, T_BAND = 1.9;

  // Points kept clear of the holes: moved towards the board's middle.
  var PTS = GRID.map(function (x) {
    for (var i = 0; i < HOLES.length; i++) {
      var need = HOLE_D / 2 + HOLE_CLEAR;
      if (Math.abs(x - HOLES[i]) < need) {
        return { x: HOLES[i] + (x < 50 ? need + 1.5 : -need - 1.5), moved: true };
      }
    }
    return { x: x, moved: false };
  });

  A.define("lz-focus", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = 500;
    var X1 = narrow ? 40 : 90, X2 = W - (narrow ? 40 : 170);
    var PX = (X2 - X1) / BOARD, KZ = PX * 20;        // heights x20
    var Y0 = 270;                                    // the autofocus height, on screen
    var LENS = 92;                                   // lens to focus, on screen
    var HX = (X1 + X2) / 2;

    var svg = A.stage(host, W, H, "Section of a sheet on the laser bed: the blue dot measures the height at points along the job, and a sheet more than 0.3 mm off focus is etched in bands, the head refocused for each");
    A.text(svg, 24, 32, "FOCUS MAP · SECTION", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    A.text(svg, W - 24, 32, "heights drawn ×20", { size: 15, anchor: "end", fill: C.text3 });

    function X(mm) { return X1 + mm * PX; }
    function Y(dz) { return Y0 - dz * KZ; }

    var gGuides = A.el(svg, "g", {});
    var gBandFill = A.el(svg, "rect", { x: X1 - 20, width: X2 - X1 + 40, fill: C.live, "fill-opacity": 0.12 });
    var gFocus = A.el(svg, "line", { x1: X1 - 20, x2: X2 + 20, stroke: C.live, "stroke-width": 1.5, "stroke-dasharray": "6 5" });
    var gFocusLbl = A.text(svg, X2 + 26, 0, "", { size: 14, fill: C.live });
    var gFr4 = A.el(svg, "path", { fill: C.fr4 });
    var gCu = A.el(svg, "path", { fill: C.copper });
    var gHoles = A.el(svg, "g", {});
    var gStrip = A.el(svg, "g", {});
    var gMap = A.el(svg, "path", { fill: "none", stroke: C.live, "stroke-width": 2, "stroke-dasharray": "2 4" });
    var gBeam = A.el(svg, "g", {});
    var gPts = A.el(svg, "g", {});
    var gHead = A.el(svg, "g", {});
    A.el(gHead, "rect", { x: -34, y: -58, width: 68, height: 46, rx: 4, fill: C.raised, stroke: C.ruleStrong, "stroke-width": 2 });
    A.el(gHead, "rect", { x: -12, y: -12, width: 24, height: 12, fill: C.panelHi, stroke: C.ruleStrong, "stroke-width": 2 });
    A.text(gHead, 0, -29, "HEAD", { size: 13, weight: 600, anchor: "middle", fill: C.text2, font: "label", spacing: "0.08em" });
    var gHeadLbl = A.text(svg, 0, 0, "", { size: 14, fill: C.text2 });
    var gAnn = A.el(svg, "g", {});

    // the board's width, under it
    var yDim = H - 26;
    A.arrow(gAnn, HX - 30, yDim, X1, yDim, { color: C.text3, head: 7, width: 1.5 });
    A.arrow(gAnn, HX + 30, yDim, X2, yDim, { color: C.text3, head: 7, width: 1.5 });
    A.text(gAnn, HX, yDim + 5, "100 mm", { size: 14, anchor: "middle", fill: C.text3 });

    var row = A.controls(host);
    var shape = "bow", amount = 0.9, st, anim;

    function surf(x) {                                // mm, relative to the middle
      var u = x / BOARD * 2 - 1;
      return shape === "bow" ? -amount * u * u : amount * u / 2;
    }
    var meas = [], lo = 0, hi = 0, bands = [];
    function plan() {
      meas = PTS.map(function (p) { return { x: p.x, z: surf(p.x), moved: p.moved }; });
      function mapAt(x) {                             // piecewise linear through the points
        if (x <= meas[0].x) return meas[0].z;
        for (var i = 1; i < meas.length; i++) if (x <= meas[i].x) {
          var t = (x - meas[i - 1].x) / (meas[i].x - meas[i - 1].x);
          return A.lerp(meas[i - 1].z, meas[i].z, t);
        }
        return meas[meas.length - 1].z;
      }
      var zs = [], i;
      for (i = 0; i <= SAMPLES; i++) zs.push(mapAt(BOARD * i / SAMPLES));
      lo = Math.min.apply(null, zs); hi = Math.max.apply(null, zs);
      bands = [];
      if (hi - lo <= 2 * TOL + 1e-9) {
        bands.push({ z: (lo + hi) / 2, segs: [[0, BOARD]] });
      } else {
        var n = Math.ceil((hi - lo) / (2 * TOL) - 1e-9), k;
        for (k = 0; k < n; k++) bands.push({ zs: [], segs: [] });
        var cur = -1;
        for (i = 0; i <= SAMPLES; i++) {
          k = Math.min(Math.floor((zs[i] - lo) / (2 * TOL)), n - 1);
          var x = BOARD * i / SAMPLES;
          bands[k].zs.push(zs[i]);
          if (k !== cur) { bands[k].segs.push([x, x]); cur = k; }
          var s = bands[k].segs; s[s.length - 1][1] = x;
        }
        bands = bands.filter(function (b) { return b.zs.length; });
        bands.forEach(function (b) {
          b.z = (Math.min.apply(null, b.zs) + Math.max.apply(null, b.zs)) / 2;
        });
      }
      var path = "M";
      for (i = 0; i <= SAMPLES; i++) path += (i ? "L" : "") + X(BOARD * i / SAMPLES).toFixed(1) + "," + Y(zs[i]).toFixed(1);
      A.set(gMap, { d: path });

      // the sheet itself: copper over FR4, with the two holes through it
      var top = [], cuB = [], frB = [];
      for (i = 0; i <= SAMPLES; i++) {
        var xx = BOARD * i / SAMPLES, z = surf(xx);
        top.push([X(xx), Y(z)]); cuB.push([X(xx), Y(z) + 4]); frB.push([X(xx), Y(z) + 20]);
      }
      function poly(a, b) { return "M" + a.concat(b.slice().reverse()).map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join("L") + "Z"; }
      A.set(gCu, { d: poly(top, cuB) });
      A.set(gFr4, { d: poly(cuB, frB) });
      while (gHoles.firstChild) gHoles.removeChild(gHoles.firstChild);
      HOLES.forEach(function (h) {
        var w = Math.max(HOLE_D * PX, 6), a = h - w / 2 / PX, b = h + w / 2 / PX;
        A.el(gHoles, "polygon", { fill: C.base, points: [X(a), Y(surf(a)) - 1, X(b), Y(surf(b)) - 1,
          X(b), Y(surf(b)) + 21, X(a), Y(surf(a)) + 21].join(",") });
      });
      // band guides: where each band starts, from the lowest up
      while (gGuides.firstChild) gGuides.removeChild(gGuides.firstChild);
      if (bands.length > 1) {
        for (var b = 0; b <= bands.length; b++) {
          var gz = Math.min(lo + b * 2 * TOL, hi);
          A.el(gGuides, "line", { x1: X1 - 20, x2: X2 + 20, y1: Y(gz), y2: Y(gz), stroke: C.text4, "stroke-width": 1, "stroke-dasharray": "2 5" });
        }
      }
    }

    function headAt(f) {                              // focus height f, mm
      var fy = Y(f);
      A.set(gHead, { transform: "translate(" + HX + "," + (fy - LENS) + ")" });
      A.set(gFocus, { y1: fy, y2: fy });
      A.set(gBandFill, { y: Y(f + TOL), height: 2 * TOL * KZ });
      A.set(gFocusLbl, { y: fy + 5 });
      gFocusLbl.textContent = narrow ? "" : "focus ±0.3 mm";
      A.set(gHeadLbl, { x: HX + 44, y: fy - LENS - 28 });
      gHeadLbl.textContent = "head " + (f >= 0 ? "+" : "−") + Math.abs(f).toFixed(2) + " mm";
    }

    function clear(g) { while (g.firstChild) g.removeChild(g.firstChild); }

    function ray(x, z, colour, dash) {
      A.el(gBeam, "line", { x1: HX, y1: Y(curF) - LENS, x2: X(x), y2: Y(z), stroke: colour, "stroke-width": 2, "stroke-dasharray": dash || null });
      A.el(gBeam, "circle", { cx: X(x), cy: Y(z), r: 4, fill: colour });
    }

    var curF = 0;
    var total = 0;
    // ?lzt=<seconds> draws that moment and holds it (for checking the drawing).
    var fixedM = /[?&]lzt=([\d.]+)/.exec(window.location.search || "");
    var fixedT = fixedM ? parseFloat(fixedM[1]) : null;
    function duration() { return T_START + meas.length * T_POINT + T_MAP + bands.length * T_BAND + 0.4; }

    function tick(t) {
      clear(gBeam); clear(gPts); clear(gStrip);
      var tm = t - T_START, k = Math.floor(tm / T_POINT), shown = A.clamp(k, 0, meas.length);
      if (tm >= meas.length * T_POINT) shown = meas.length;
      // measured points so far
      for (var i = 0; i < shown; i++) {
        var p = meas[i];
        A.el(gPts, "circle", { cx: X(p.x), cy: Y(p.z), r: 5.5, fill: C.live, stroke: C.base, "stroke-width": 2 });
        if (!narrow || i % 2 === 0) A.text(gPts, A.clamp(X(p.x), X1 + 18, X2 - 18), Y(p.z) - 22, (p.z >= 0 ? "+" : "−") + Math.abs(p.z).toFixed(2), { size: 13, anchor: "middle", fill: C.live, font: "mono" });
      }
      var measuring = tm >= 0 && k < meas.length;
      var tAfter = tm - meas.length * T_POINT;
      gMap.style.opacity = tAfter > 0 ? A.ease(tAfter / 0.6) : 0;

      if (t < T_START || measuring) {
        curF = 0; headAt(0);
        gBandFill.style.opacity = 1; gFocus.style.opacity = 1;
        if (measuring) {
          var q = meas[k], f = (tm - k * T_POINT) / T_POINT;
          if (f < 0.75) ray(q.x, q.z, C.live, "5 4");
          st.className = "anim-status";
          st.textContent = "Autofocus put the head at the middle. Now the blue dot reads the height at point " + (k + 1) + " of " + meas.length +
            (q.moved ? ", moved to keep 1.5 mm clear of a hole." : ".");
        } else {
          st.className = "anim-status";
          st.textContent = "Autofocus first, at the job's middle. Then Focus map measures over the whole job.";
        }
        return;
      }

      var spread = hi - lo, one = bands.length === 1;
      if (tAfter < T_MAP) {
        curF = 0; headAt(0);
        st.className = "anim-status " + (one ? "ok" : "caution");
        st.textContent = "Spread " + spread.toFixed(2) + " mm. " + (one
          ? "Within ±0.3 mm of one height: one run, in focus all over."
          : "More than the ±0.3 mm the laser etches cleanly: " + bands.length + " bands, the head refocused for each.");
        drawStrip(-1, 0);
        return;
      }
      var tb = tAfter - T_MAP, b = Math.min(Math.floor(tb / T_BAND), bands.length - 1);
      var fb = A.clamp((tb - b * T_BAND) / T_BAND, 0, 1);
      if (tb >= bands.length * T_BAND) { b = bands.length; fb = 1; }
      var band = bands[Math.min(b, bands.length - 1)];
      var prevZ = b > 0 && b < bands.length ? bands[b - 1].z : (b === 0 ? 0 : band.z);
      var move = A.ease(fb / 0.3);
      curF = b < bands.length ? A.lerp(prevZ, band.z, move) : band.z;
      headAt(curF);
      drawStrip(b, b < bands.length ? A.clamp((fb - 0.3) / 0.7, 0, 1) : 1);
      if (b < bands.length && fb > 0.3) {
        // the beam sweeps along this band's stretches of the board
        var len = 0, segs = band.segs;
        segs.forEach(function (s) { len += s[1] - s[0]; });
        var at = ((fb - 0.3) / 0.7) * len, x = segs[0][0];
        for (var j = 0; j < segs.length; j++) {
          var l = segs[j][1] - segs[j][0];
          if (at <= l) { x = segs[j][0] + at; break; }
          at -= l; x = segs[j][1];
        }
        ray(x, surf(x), C.caution);
      }
      if (b < bands.length) {
        st.className = "anim-status " + (one ? "ok" : "caution");
        st.textContent = one
          ? "One run: the head at the middle of the range, " + fmt(band.z) + " mm, and the whole board within ±0.3 mm."
          : "Band " + (b + 1) + " of " + bands.length + ": the head moves to " + fmt(band.z) + " mm, then etches only the stretches at that height.";
      } else {
        st.className = "anim-status ok";
        st.textContent = one
          ? "Done in one run. Spread " + spread.toFixed(2) + " mm: no bands needed."
          : "Done: " + bands.length + " bands, each etched in focus. Spread " + spread.toFixed(2) + " mm.";
      }
    }
    function fmt(z) { return (z >= 0 ? "+" : "−") + Math.abs(z).toFixed(2); }

    // a strip over the copper: which band each stretch is in, and how far it is etched
    function drawStrip(active, frac) {
      var cols = [C.steel, C.copperHi, C.fr4Hi, C.steelDim];
      bands.forEach(function (bd, i) {
        var col = bands.length === 1 ? C.steel : cols[i % cols.length];
        var done = i < active || active >= bands.length;
        var len = 0;
        bd.segs.forEach(function (s) { len += s[1] - s[0]; });
        var left = (i === active) ? frac * len : (done ? len : 0);
        bd.segs.forEach(function (s) {
          var path = "M", n = 24;
          for (var j = 0; j <= n; j++) {
            var xx = s[0] + (s[1] - s[0]) * j / n;
            path += (j ? "L" : "") + X(xx).toFixed(1) + "," + (Y(surf(xx)) - 7).toFixed(1);
          }
          A.el(gStrip, "path", { d: path, fill: "none", stroke: col, "stroke-width": 4, opacity: done || i === active ? 0.35 : 0.6, "stroke-linecap": "butt" });
          var e = Math.min(left, s[1] - s[0]);
          if (e > 0) {
            var p2 = "M";
            for (j = 0; j <= n; j++) {
              var x2 = s[0] + e * j / n;
              p2 += (j ? "L" : "") + X(x2).toFixed(1) + "," + (Y(surf(x2)) - 7).toFixed(1);
            }
            A.el(gStrip, "path", { d: p2, fill: "none", stroke: done ? C.ok : C.caution, "stroke-width": 4 });
          }
          left -= Math.max(0, Math.min(left, s[1] - s[0]));
        });
        if (bands.length > 1 && !narrow) {
          var s0 = bd.segs[0], mid = (s0[0] + s0[1]) / 2;
          A.text(gStrip, X(mid), Y(surf(mid)) + 40, "band " + (i + 1), { size: 13, anchor: "middle", fill: col, font: "label", weight: 600 });
        }
      });
    }

    function restart() {
      plan();
      total = duration();
      if (fixedT !== null) tick(Math.min(fixedT, total));
      else if (anim) anim.restart();
    }

    A.segmented(row, [["bow", "Bowed"], ["tilt", "Tilted"]], shape, function (v) { shape = v; if (st) restart(); });
    A.slider(row, "Off flat", 0, 1.2, 0.05, amount, function (v) { amount = v; if (st) restart(); },
      function (v) { return v.toFixed(2) + " mm"; });
    A.button(row, "Measure again", function () { restart(); }, "primary");
    st = A.status(row);
    plan();
    total = duration();
    if (fixedT !== null) { tick(Math.min(fixedT, total)); return; }
    anim = A.loop(host, function (t) { tick(Math.min(t, total)); }, 999);
  });
})();
