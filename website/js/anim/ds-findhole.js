/* "Find it for me": the electrical hole finder, played out step by step with the
   strategy the code uses (gerber2rml/gui2/fiducial.py FidFindRun, engine/fidfind.py).

   1. Latch the datum where the bit is; touch copper once for a surface reference,
      2.5 mm west, else east, north, south of the hole (_REF_DIRS).
   2. Hole test at the start. Copper there? Hunt in rings, step max(0.2 mm, the
      clearance), out to 1.5 mm, until a point reads "hole".
   3. March right in 0.4 mm steps until copper, bisect the edge to 50 µm; the same
      to the left. The midpoint is the centre in X.
   4. Up and down at that X, each first bracketed ±0.15 mm around where the X chord
      says it is (commit 3ff0c92); a march only if the bracket misses.
   5. A second X pass at the found Y, only when the start was more than 0.4 mm off
      the middle in Y (a chord far from the middle crosses the rim at a slant).
   A hole test is a physical descent: copper = contact. The bit's flat 0.8 mm face
   touches copper as soon as any of it overhangs the rim, so the "hole" the bisection
   sees is the circle of radius (hole - bit) / 2 around the centre. Where there is no
   copper the bit presses about 0.2 mm into bare laminate (docs/usage.md). */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BIT_R = 0.4;

  // The finder, as a list of touches. Returns {touches:[{x,y,copper,kind,label}], cx, cy} or {fail}.
  function simulate(R, hx, hy, x0, y0, clearance) {
    var T = [], eff = R - BIT_R;
    function copper(x, y) { return Math.hypot(x - hx, y - hy) > eff; }
    function test(x, y, kind, label) { var c = copper(x, y); T.push({ x: x, y: y, copper: c, kind: kind, label: label }); return c; }
    // the surface reference: 2.5 mm out, first side with copper (outside the hole = copper here)
    T.push({ x: x0 - 2.5, y: y0, copper: true, kind: "ref", label: "Surface reference: copper 2.5 mm west" });
    // the seed
    var sx = x0, sy = y0;
    if (test(x0, y0, "seed", "Hole test where you aimed")) {
      var step = Math.max(0.2, clearance), found = false;
      for (var ring = 1; ring * step <= 1.5 + 1e-9 && !found; ring++) {
        var r = ring * step, n = Math.max(6, Math.round(2 * Math.PI * r / step));
        for (var k = 0; k < n; k++) {
          var a = 2 * Math.PI * k / n, x = x0 + r * Math.cos(a), y = y0 + r * Math.sin(a);
          if (!test(x, y, "hunt", "Hunting for the hole, " + r.toFixed(1) + " mm out")) { sx = x; sy = y; found = true; break; }
        }
      }
      if (!found) return { touches: T, fail: "No hole within 1.5 mm of the bit: copper everywhere. Jog to the hole you can see." };
    }
    function edge(ox, oy, dx, dy, guess, label) {
      var lo = 0, hi = null, d = 0.4;
      function t(dd) { return test(ox + dx * dd, oy + dy * dd, "edge", label); }
      if (guess !== undefined && guess - 0.15 > 0) {
        var gl = guess - 0.15, gh = guess + 0.15;
        if (!t(gl)) { lo = gl; if (t(gh)) hi = gh; else { lo = gh; d = gh + 0.4; } }
        else hi = gl;
      }
      while (hi === null && d <= 4.0) { if (t(d)) { hi = d; break; } lo = d; d += 0.4; }
      if (hi === null) return null;
      while (hi - lo > 0.05) { var mid = (lo + hi) / 2; if (t(mid)) hi = mid; else lo = mid; }
      return (lo + hi) / 2;
    }
    var right = edge(sx, sy, 1, 0, undefined, "Right edge: march 0.4 mm, bisect to 50 µm");
    var left = edge(sx, sy, -1, 0, undefined, "Left edge");
    var cx = sx + (right - left) / 2, half = (right + left) / 2;
    var up = edge(cx, sy, 0, 1, half, "Up: bracket where the X chord says, then bisect");
    var down = edge(cx, sy, 0, -1, 2 * half - up, "Down: bracketed the same way");
    var cy = sy + (up - down) / 2, second = false;
    if (Math.abs(cy - sy) > 0.4) {
      second = true;
      var rad = (up + down) / 2;
      var r2 = edge(cx, cy, 1, 0, rad, "Second X pass at the found Y");
      var l2 = edge(cx, cy, -1, 0, rad, "Second X pass, left");
      cx = cx + (r2 - l2) / 2;
    }
    return { touches: T, cx: cx, cy: cy, second: second };
  }

  A.define("ds-findhole", function (host) {
    var laser = host.getAttribute("data-context") === "laser";
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 800 : 520;
    var svg = A.stage(host, W, H, "The electrical hole finder walking a hole's edges to find its centre");
    var VX = 16, VY = 16, VW = narrow ? 488 : 540, VH = narrow ? 488 : 488;
    var K = VW / 6.6;                                    // px per mm: 6.6 mm across, room for the reference touch
    var OX = VX + VW / 2, OY = VY + VH / 2 + 10;         // screen of the view centre
    var PX = narrow ? 16 : 576, PY = narrow ? 520 : 16, PW = narrow ? 488 : 288;
    A.el(svg, "rect", { x: VX, y: VY, width: VW, height: VH, rx: 3, fill: C.copperDim, stroke: C.ruleHi });
    A.text(svg, VX + 12, VY + 26, "TOP VIEW · to scale · grid 1 mm", { size: 15, weight: 600, fill: "#f3dcc4", font: "label", spacing: "0.06em" });
    var gv = A.el(svg, "g", {});
    var gp = A.el(svg, "g", {});
    var row = A.controls(host);
    var st = A.status(row);
    var dia = laser ? 1.6 : 1.6, hx = 0.23, hy = -0.31, aimX = -0.35, aimY = 0.42, res = null, shown = 0, anim = 0, running = false;

    function S(x, y) { return [OX + x * K, OY - y * K]; }
    function drawView() {
      while (gv.firstChild) gv.removeChild(gv.firstChild);
      for (var g = -4; g <= 4; g++) {
        A.el(gv, "line", { x1: OX + g * K, y1: VY + 36, x2: OX + g * K, y2: VY + VH, stroke: "#8f5a2e", "stroke-width": 1, opacity: 0.6 });
        A.el(gv, "line", { x1: VX, y1: OY + g * K, x2: VX + VW, y2: OY + g * K, stroke: "#8f5a2e", "stroke-width": 1, opacity: 0.6 });
      }
      var c = S(hx, hy);
      A.el(gv, "circle", { cx: c[0], cy: c[1], r: dia / 2 * K, fill: C.fr4, stroke: C.copperHi, "stroke-width": 2 });
      A.el(gv, "circle", { cx: c[0], cy: c[1], r: Math.max(dia / 2 - BIT_R, 0) * K, fill: "none", stroke: C.ink, "stroke-dasharray": "5 4", "stroke-width": 1.5, opacity: 0.7 });
      A.text(gv, c[0], c[1] + dia / 2 * K + 22, laser ? "copper-free circle at the pad" : "reference hole " + dia.toFixed(1) + " mm", { size: 15, anchor: "middle", fill: "#f3dcc4" });
      var T = res ? res.touches.slice(0, shown) : [];
      T.forEach(function (t, i) {
        var p = S(t.x, t.y);
        if (t.kind === "ref") {
          A.el(gv, "rect", { x: p[0] - 7, y: p[1] - 7, width: 14, height: 14, fill: C.live, stroke: C.ink });
          A.text(gv, p[0], p[1] - 14, "surface ref", { size: 15, anchor: "middle", fill: "#f3dcc4" });
          return;
        }
        A.el(gv, "circle", { cx: p[0], cy: p[1], r: i === shown - 1 ? 6 : 4, fill: t.copper ? C.danger : C.ok, stroke: C.ink, "stroke-width": 1 });
      });
      var cur = T.length ? T[T.length - 1] : null;
      var bp = cur ? S(cur.x, cur.y) : S(aimX, aimY);
      if (cur && cur.kind === "ref") bp = S(cur.x, cur.y);
      A.el(gv, "circle", { cx: bp[0], cy: bp[1], r: BIT_R * K, fill: C.steel, "fill-opacity": 0.55, stroke: C.text, "stroke-width": 2 });
      var a = S(aimX, aimY);
      A.el(gv, "path", { d: "M" + (a[0] - 9) + "," + a[1] + " h18 M" + a[0] + "," + (a[1] - 9) + " v18", stroke: C.live, "stroke-width": 2.5 });
      if (res && !res.fail && shown >= res.touches.length) {
        var f = S(res.cx, res.cy);
        A.el(gv, "circle", { cx: f[0], cy: f[1], r: 12, fill: "none", stroke: C.caution, "stroke-width": 3 });
        A.el(gv, "path", { d: "M" + (f[0] - 16) + "," + f[1] + " h32 M" + f[0] + "," + (f[1] - 16) + " v32", stroke: C.caution, "stroke-width": 2 });
      }
    }
    function drawPanel() {
      while (gp.firstChild) gp.removeChild(gp.firstChild);
      var ph = narrow ? 256 : 488;
      A.el(gp, "rect", { x: PX, y: PY, width: PW, height: ph, rx: 3, fill: C.panel, stroke: C.ruleHi });
      A.text(gp, PX + 14, PY + 28, "FIND IT FOR ME", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
      var T = res ? res.touches.slice(0, shown) : [], cur = T.length ? T[T.length - 1] : null;
      var n = T.filter(function (t) { return t.kind !== "ref"; }).length;
      var y = PY + 60;
      function line(k, v, col) {
        A.text(gp, PX + 14, y, k, { size: 15, fill: C.text2 });
        A.text(gp, PX + PW - 14, y, v, { size: 17, font: "mono", anchor: "end", fill: col || C.text, weight: 600 });
        y += 30;
      }
      line("Touches", String(n));
      if (res && !res.fail && shown >= res.touches.length) {
        var e = Math.hypot(res.cx - hx, res.cy - hy) * 1000;
        line("Error", e.toFixed(0) + " µm", e < 50 ? C.ok : C.caution);
        line("2nd X pass", res.second ? "yes" : "not needed");
      } else { line("Error", "—", C.text3); line("2nd X pass", "—", C.text3); }
      // side view of one test: start 2 mm up, the descent
      var zx = PX + 14, zy = y + 14, zw = PW - 28, zh = narrow ? 70 : 150;
      A.text(gp, zx, zy + 14, "SIDE VIEW OF A TEST", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
      var surf = zy + zh + 6;
      A.el(gp, "rect", { x: zx, y: surf, width: zw, height: 6, fill: C.copper });
      A.el(gp, "rect", { x: zx, y: surf + 6, width: zw, height: 18, fill: C.fr4 });
      var down = cur && cur.kind !== "ref" ? (cur.copper ? 0 : 0.2) : 0;
      var tipY = cur ? surf + down * 60 : zy + 26;
      A.el(gp, "rect", { x: zx + zw / 2 - 6, y: tipY - 60, width: 12, height: 60, fill: C.steel });
      A.el(gp, "line", { x1: zx, y1: zy + 26, x2: zx + zw, y2: zy + 26, stroke: C.live, "stroke-dasharray": "5 4" });
      A.text(gp, zx + zw, zy + 46, "start: 2 mm above", { size: 15, anchor: "end", fill: C.live });
      A.text(gp, zx, surf + 46, cur && cur.kind !== "ref" ? (cur.copper ? "copper: contact" : "no copper: 0.2 mm into laminate") : "", { size: 15, fill: cur && cur.copper ? C.danger : C.ok });
      if (!narrow) {
        var yy = surf + 84;
        [["●", C.ok, "a test that read no copper"], ["●", C.danger, "a test that touched copper"], ["+", C.live, "where you aimed"], ["+", C.caution, "the centre it found"]]
          .forEach(function (l) { A.text(gp, zx, yy, l[0], { size: 16, fill: l[1], weight: 700 }); A.text(gp, zx + 22, yy, l[2], { size: 15, fill: C.text2 }); yy += 24; });
      }
    }
    function say() {
      var T = res ? res.touches.slice(0, shown) : [], cur = T.length ? T[T.length - 1] : null;
      if (!res) { st.className = "anim-status"; st.textContent = "Jog the bit over the " + (laser ? "circle" : "hole") + ", about 2 mm above the copper, never at Z0: its first move is sideways. Then Find it for me."; return; }
      if (res.fail && shown >= res.touches.length) { st.className = "anim-status bad"; st.textContent = res.fail; return; }
      if (shown >= res.touches.length) {
        st.className = "anim-status ok";
        st.textContent = "Found in " + T.filter(function (t) { return t.kind !== "ref"; }).length + " touches, " + (Math.hypot(res.cx - hx, res.cy - hy) * 1000).toFixed(0) + " µm from the true centre. Go to it jogs back to this centre, so you can check it by eye.";
        return;
      }
      st.className = "anim-status"; st.textContent = cur ? cur.label : "";
    }
    function all() { drawView(); drawPanel(); say(); }

    function run() {
      cancelAnimationFrame(anim);
      res = simulate(dia / 2, hx, hy, aimX, aimY, Math.max(0.1, (dia - 2 * BIT_R) / 2));
      if (A.reduced) { shown = res.touches.length; all(); return; }
      shown = 0; running = true;
      var t0 = null;
      function stp(now) {
        if (t0 === null) t0 = now;
        var want = Math.min(res.touches.length, 1 + Math.floor((now - t0) / 260));
        if (want !== shown) { shown = want; all(); }
        if (shown < res.touches.length) anim = requestAnimationFrame(stp); else running = false;
      }
      anim = requestAnimationFrame(stp);
    }
    function newHole() {
      cancelAnimationFrame(anim); res = null; shown = 0;
      hx = (Math.random() - 0.5) * 0.9; hy = (Math.random() - 0.5) * 0.9;
      all();
    }

    A.button(row, "Find it for me", run, "primary");
    A.button(row, "Aim somewhere else", function () {
      cancelAnimationFrame(anim); res = null; shown = 0;
      var a = Math.random() * 2 * Math.PI, r = Math.random() * (dia / 2 + 0.5);
      aimX = hx + r * Math.cos(a); aimY = hy + r * Math.sin(a); all();
    }, "", "Aim off, even onto the copper beside the hole: the finder hunts for it in rings");
    A.button(row, "Another hole", newHole);
    A.slider(row, laser ? "Circle" : "Reference hole", 1.2, 2.4, 0.1, dia, function (v) { dia = v; cancelAnimationFrame(anim); res = null; shown = 0; if (gv) all(); },
      function (v) { return v.toFixed(1) + " mm"; });
    row.appendChild(st);
    // click in the view to aim
    svg.addEventListener("click", function (e) {
      var pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
      var p = pt.matrixTransform(svg.getScreenCTM().inverse());
      if (p.x < VX || p.x > VX + VW || p.y < VY + 36 || p.y > VY + VH) return;
      cancelAnimationFrame(anim); res = null; shown = 0;
      aimX = (p.x - OX) / K; aimY = (OY - p.y) / K; all();
    });
    all();
  });
})();
