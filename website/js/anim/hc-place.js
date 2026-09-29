/* Telling SRM-CAM where the copper is. Until the sheet's corner is set, the app's
   copper is a placeholder at the machine origin, and its "on the copper" check is
   about a rectangle nobody measured. Set the corner from the tool reads the head's
   X and Y (gui2/window.py action_stock_corner_here: a pure read, nothing moves, the
   work origin is untouched). Centre it on the copper then centres the job on the
   part of the sheet the spindle can reach (gui2/window.py _centring_target); it is
   refused until the sheet is set. Centre it on the bed centres it on the travel.
   Numbers: the SRM-20 travel 203.2 x 152.4 mm (backends SRM20_BED), the 150 x 100 mm
   sheet from the recording, its corner found at X 60.52, Y 24.42. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BX = 203.2, BY = 152.4, SW = 150, SH = 100, RX = 60.52, RY = 24.42;
  var JW = 68, JH = 42;                           // two boards, butted

  A.define("hc-place", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 840 : 520;
    var K = narrow ? 2.3 : 2.62;
    var OX = narrow ? 24 : 26, OY = 64;
    var PX = narrow ? 24 : 590, PY = narrow ? OY + BY * K + 40 : 64, PW = narrow ? W - 48 : 266;
    var svg = A.stage(host, W, H, "The machine bed from above: where SRM-CAM thinks the copper is, where it really is, and the job");
    A.text(svg, OX, 32, "THE BED FROM ABOVE · MACHINE COORDINATES", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    function sx(mm) { return OX + mm * K; }
    function sy(mm) { return OY + (BY - mm) * K; }
    // the travel
    A.el(svg, "rect", { x: sx(0), y: sy(BY), width: BX * K, height: BY * K, fill: C.panel, stroke: C.ruleStrong, "stroke-width": 1.5 });
    A.el(svg, "circle", { cx: sx(0), cy: sy(0), r: 6, fill: C.caution });
    A.text(svg, sx(0) + 10, sy(0) + (narrow ? 22 : 24), "machine origin (X, Y stay here)", { size: 15, fill: C.caution });
    // the real copper: clipped to the drawing, the unreachable part hatched
    var pat = A.el(svg, "pattern", { id: "hcplace-hatch", width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
    A.el(pat, "line", { x1: 0, y1: 0, x2: 0, y2: 8, stroke: C.danger, "stroke-width": 2, opacity: 0.6 });
    var reachW = BX - RX;
    A.el(svg, "rect", { x: sx(RX), y: sy(RY + SH), width: reachW * K, height: SH * K, fill: C.copperFill, stroke: C.copper, "stroke-width": 2.5 });
    var outW = narrow ? 14 : 20;                       // a stub of the overhang, drawn past the travel
    A.el(svg, "rect", { x: sx(BX), y: sy(RY + SH), width: outW, height: SH * K, fill: "url(#hcplace-hatch)", stroke: C.copper, "stroke-width": 1.5, "stroke-dasharray": "4 3" });
    A.text(svg, sx(RX) + 8, sy(RY + SH) + 22, "the copper, really", { size: 15, fill: C.copperHi, weight: 600 });
    // what SRM-CAM thinks
    var gThink = A.el(svg, "g", {});
    var thinkR = A.el(gThink, "rect", { x: 0, y: 0, width: SW * K, height: SH * K, fill: "none", stroke: C.live, "stroke-width": 2, "stroke-dasharray": "8 6" });
    var thinkT = A.text(gThink, 0, 0, "where SRM-CAM thinks it is", { size: 15, fill: C.live, weight: 600 });
    // the job and the head
    var job = A.el(svg, "g", {});
    var jobR = A.el(job, "rect", { x: 0, y: 0, width: JW * K, height: JH * K, fill: C.copper, stroke: C.text, "stroke-width": 1.5 });
    A.el(job, "line", { x1: JW / 2 * K, y1: 0, x2: JW / 2 * K, y2: JH * K, stroke: C.sunk, "stroke-width": 2 });
    var jobT = A.text(job, JW / 2 * K, JH / 2 * K + 6, "the job", { size: 16, anchor: "middle", weight: 700, fill: C.ink });
    var head = A.el(svg, "g", {});
    A.el(head, "circle", { cx: 0, cy: 0, r: 9, fill: "none", stroke: C.text, "stroke-width": 2 });
    A.el(head, "line", { x1: -14, y1: 0, x2: 14, y2: 0, stroke: C.text, "stroke-width": 2 });
    A.el(head, "line", { x1: 0, y1: -14, x2: 0, y2: 14, stroke: C.text, "stroke-width": 2 });

    // side panel: the copper fields and the two truths
    A.el(svg, "rect", { x: PX, y: PY, width: PW, height: narrow ? H - PY - 16 : H - PY - 20, fill: C.panel, stroke: C.ruleStrong, rx: 3 });
    A.text(svg, PX + 14, PY + 28, "SET UP THE JOB › THE COPPER", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.04em" });
    A.text(svg, PX + 14, PY + 58, "Sheet 150 × 100 mm", { size: 16, fill: C.text });
    var cornerT = A.text(svg, PX + 14, PY + 84, "", { size: 16, font: "mono", fill: C.text });
    A.text(svg, PX + 14, PY + 124, "SRM-CAM'S CHECK", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var appT = A.text(svg, PX + 14, PY + 150, "", { size: 16, weight: 700 });
    var appT2 = A.text(svg, PX + 14, PY + 172, "", { size: 15, fill: C.text2 });
    A.text(svg, PX + 14, PY + 214, "AT THE MACHINE", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var realT = A.text(svg, PX + 14, PY + 240, "", { size: 16, weight: 700 });
    var realT2 = A.text(svg, PX + 14, PY + 262, "", { size: 15, fill: C.text2 });
    var realT3 = A.text(svg, PX + 14, PY + 282, "", { size: 15, fill: C.text2 });
    var reachT = A.text(svg, PX + 14, PY + 322, "", { size: 15, fill: C.caution });
    var reachT2 = A.text(svg, PX + 14, PY + 342, "", { size: 15, fill: C.caution });

    var s = { set: false, cx: 0, cy: 0, jx: 5, jy: 5, hx: 5, hy: 60 };
    var tw = null;                                    // a tween in flight

    function inside(x, y, w, h, X0, Y0, X1, Y1) { return x >= X0 - 1e-6 && y >= Y0 - 1e-6 && x + w <= X1 + 1e-6 && y + h <= Y1 + 1e-6; }
    function draw() {
      A.set(thinkR, { x: sx(s.cx), y: sy(s.cy + SH) });
      A.set(thinkT, { x: sx(s.cx) + 8, y: sy(s.cy + SH) + (s.set ? 46 : 22) });
      thinkT.textContent = s.set ? "SRM-CAM's copper (set)" : "where SRM-CAM thinks it is";
      job.setAttribute("transform", "translate(" + sx(s.jx) + "," + sy(s.jy + JH) + ")");
      head.setAttribute("transform", "translate(" + sx(s.hx) + "," + sy(s.hy) + ")");
      cornerT.textContent = "Corner  X " + s.cx.toFixed(2) + "  Y " + s.cy.toFixed(2);
      var appOn = inside(s.jx, s.jy, JW, JH, s.cx, s.cy, s.cx + SW, s.cy + SH);
      var realOn = inside(s.jx, s.jy, JW, JH, RX, RY, Math.min(BX, RX + SW), RY + SH);
      appT.textContent = appOn ? "The job is on the copper" : "The job runs off the copper";
      A.set(appT, { fill: appOn ? C.ok : C.danger });
      appT2.textContent = appOn ? (s.set ? "…the sheet you measured." : "…a sheet nobody measured.") : "Move the job, or centre it.";
      realT.textContent = realOn ? "It lands on the copper" : "It would cut bare spoilboard";
      A.set(realT, { fill: realOn ? C.ok : C.danger });
      realT2.textContent = realOn ? "Run the dry run to be sure." : (appOn ? "The check was wrong:" : "");
      realT3.textContent = !realOn && appOn ? "the corner isn't set." : "";
      reachT.textContent = s.set ? "Part of the copper is out of reach:" : "";
      reachT2.textContent = s.set ? (RX + SW - BX).toFixed(1) + " mm past the X travel." : "";
      jobR.setAttribute("stroke", realOn ? C.text : C.danger);
      cornerBtn.disabled = s.set; centreC.disabled = false;
    }

    function tween(to, dur, done) {
      var from = {}; for (var k in to) from[k] = s[k];
      var t0 = null;
      if (A.reduced) { for (var k2 in to) s[k2] = to[k2]; draw(); if (done) done(); return; }
      tw = to;
      function f(now) {
        if (tw !== to) return;
        if (t0 === null) t0 = now;
        var u = A.ease((now - t0) / (dur * 1000));
        for (var k3 in to) s[k3] = A.lerp(from[k3], to[k3], u);
        draw();
        if (u < 1) requestAnimationFrame(f); else { tw = null; if (done) done(); }
      }
      requestAnimationFrame(f);
    }

    var row = A.controls(host);
    var cornerBtn = A.button(row, "Set the corner from the tool", function () {
      st.textContent = "The head goes to the copper's front-left corner, found with the probe (see Milling a board)…";
      st.className = "anim-status";
      tween({ hx: RX, hy: RY }, 1.2, function () {
        tween({ cx: RX, cy: RY }, 0.9, function () {
          s.set = true; s.cx = RX; s.cy = RY; draw();
          st.textContent = "Copper corner set to X 60.52, Y 24.42: the sheet now sits 150 × 100 mm from there. Nothing moved; the work origin is untouched.";
          st.className = "anim-status ok";
        });
      });
    }, "primary");
    var centreC = A.button(row, "Centre it on the copper", function () {
      if (!s.set) {
        st.textContent = "Refused: say where the copper is first (its size, and its corner), then centre on it.";
        st.className = "anim-status bad";
        return;
      }
      var x0 = RX, x1 = Math.min(BX, RX + SW), y0 = RY, y1 = RY + SH;
      tween({ jx: x0 + (x1 - x0 - JW) / 2, jy: y0 + (y1 - y0 - JH) / 2 }, 0.9, function () {
        st.textContent = "Centred on the reachable part of the copper, with the margin shared on all sides.";
        st.className = "anim-status ok";
      });
    });
    A.button(row, "Centre it on the bed", function () {
      tween({ jx: (BX - JW) / 2, jy: (BY - JH) / 2 }, 0.9, function () {
        st.textContent = "Centred on the machine's travel. That is only right when the copper is centred there too.";
        st.className = "anim-status caution";
      });
    });
    A.button(row, "Reset", function () {
      tw = null; s = { set: false, cx: 0, cy: 0, jx: 5, jy: 5, hx: 5, hy: 60 }; draw();
      st.textContent = "SRM-CAM starts with its copper at the machine origin, and the job where it loaded.";
      st.className = "anim-status";
    });
    var st = A.status(row);
    st.textContent = "SRM-CAM starts with its copper at the machine origin, and the job where it loaded.";
    draw();
  });
})();
