/* The dry run, step 0 of every single-sided plan: <name>_airpass.nc, spindle off, the
   bit held 5 mm up, tracing the outline slowly enough to follow (engine/airpass.py;
   gui2/runplan.py AIRPASS_NOTE). If it wanders off the copper, stop and re-place the
   stock: nothing has been cut. Two cases: the copper where SRM-CAM thinks it is, and a
   sheet that shifted when it was clamped. Top view, to scale. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var SW = 150, SH = 100, JW = 68, JH = 42, JX = 71, JY = 29;     // the job centred on the sheet

  A.define("hc-dryrun", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 540 : 470;
    var K = narrow ? 2.9 : 3.3;
    var OX = narrow ? 30 : 40, OY = 70;
    var svg = A.stage(host, W, H, "The dry run tracing the job's outline over the copper, spindle off");
    A.text(svg, OX, 32, "STEP 0 · DRY RUN · TOP VIEW", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    function sx(mm) { return OX + mm * K; }
    function sy(mm) { return OY + (SH - mm) * K; }
    var gSheet = A.el(svg, "g", {});
    var sheet = A.el(gSheet, "rect", { x: 0, y: 0, width: SW * K, height: SH * K, fill: C.copperFill, stroke: C.copper, "stroke-width": 2.5 });
    A.text(gSheet, SW * K - 10, 24, "the copper", { size: 15, anchor: "end", fill: C.copperHi, weight: 600 });
    A.el(svg, "rect", { x: sx(0), y: sy(SH), width: SW * K, height: SH * K, fill: "none", stroke: C.live, "stroke-width": 1.5, "stroke-dasharray": "7 6" });
    A.text(svg, sx(0), sy(0) + 22, "where SRM-CAM thinks the copper is", { size: 15, fill: C.live });
    A.el(svg, "rect", { x: sx(JX), y: sy(JY + JH), width: JW * K, height: JH * K, fill: "none", stroke: C.text3, "stroke-width": 1.5 });
    var trail = A.el(svg, "polyline", { points: "", fill: "none", stroke: C.ok, "stroke-width": 3 });
    var bad = A.el(svg, "polyline", { points: "", fill: "none", stroke: C.danger, "stroke-width": 4 });
    var headG = A.el(svg, "g", {});
    A.el(headG, "circle", { r: 11, fill: "none", stroke: C.text, "stroke-width": 2 });
    A.el(headG, "circle", { r: 3, fill: C.text });
    var badge = A.el(svg, "g", {});
    var bx = narrow ? OX : OX + SW * K + 24, by = narrow ? OY + SH * K + 44 : OY;
    A.el(badge, "rect", { x: bx, y: by, width: narrow ? W - 2 * OX : W - bx - 20, height: narrow ? 60 : 120, rx: 3, fill: C.panel, stroke: C.ruleStrong });
    A.text(badge, bx + 14, by + 26, "spindle OFF", { size: 16, weight: 700, fill: C.text });
    A.text(badge, bx + 14, by + 48, "bit held 5 mm up", { size: 15, fill: C.text2 });
    if (!narrow) A.text(badge, bx + 14, by + 70, "this file cannot cut", { size: 15, fill: C.text2 });
    var verdict = A.text(svg, 24, H - 26, "", { size: 18, weight: 700 });

    var shift = 0;                                   // how far the real sheet sits from where the app thinks (mm, X)
    var path = [[JX, JY], [JX + JW, JY], [JX + JW, JY + JH], [JX, JY + JH], [JX, JY]];
    var per = 2 * (JW + JH);
    function at(d) {
      var acc = 0;
      for (var i = 0; i < 4; i++) {
        var a = path[i], b = path[i + 1], L = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (d <= acc + L) { var u = (d - acc) / L; return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u]; }
        acc += L;
      }
      return path[4];
    }
    function onCopper(p) { return p[0] >= shift && p[0] <= shift + SW && p[1] >= 0 && p[1] <= SH; }

    var off = false, t0 = null;
    function frame(t) {
      if (t0 === null) t0 = t;
      var d = Math.min(per, (t - t0) * 32);            // 32 mm/s: slow enough to follow, scaled up
      var pts = [], badPts = [];
      for (var x = 0; x <= d; x += 1.5) {
        var p = at(x), q = sx(p[0]) + "," + sy(p[1]);
        if (onCopper(p)) pts.push(q); else badPts.push(q);
        if (!onCopper(p) && !off) { off = true; }
      }
      trail.setAttribute("points", pts.join(" "));
      bad.setAttribute("points", badPts.join(" "));
      var h = at(d);
      headG.setAttribute("transform", "translate(" + sx(h[0]) + "," + sy(h[1]) + ")");
      if (off) {
        verdict.textContent = "Off the copper: STOP, and re-place the stock. Nothing has been cut.";
        A.set(verdict, { fill: C.danger });
        if (loop) loop.stop();
      } else if (d >= per) {
        verdict.textContent = "Stayed on the copper. Now the drill and the traces.";
        A.set(verdict, { fill: C.ok });
        if (loop) loop.stop();
      } else {
        verdict.textContent = "Tracing the outline…";
        A.set(verdict, { fill: C.text });
      }
    }
    var loop = null;
    function run() {
      gSheet.setAttribute("transform", "translate(" + sx(shift) + "," + sy(SH) + ")");
      off = false; t0 = null;
      if (loop) loop.stop();
      if (A.reduced) { loop = null; t0 = 0; frame(per / 32 + 1); return; }
      loop = A.loop(host, frame);
    }

    var row = A.controls(host);
    A.segmented(row, [[0, "Copper where SRM-CAM thinks"], [-24, "Sheet clamped 24 mm to the left"]], 0, function (v) { shift = v; run(); });
    A.button(row, "Run it again", function () { run(); }, "primary");
    var st = A.status(row);
    st.textContent = "Step 0, before every job: twenty seconds instead of a board.";
  });
})();
