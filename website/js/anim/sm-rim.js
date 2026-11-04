/* The alignment check: three pads far apart, opened first, with the board left in place.
   Each opening was drawn 0.1 mm per side smaller than its pad, so a true job leaves an
   even rim of ink 0.1 mm wide all round, and a job off by 0.1 mm brings the opening to the
   pad's edge. That is why 0.10 mm is the limit. A turn hurts the pads furthest from the
   middle, and a mirrored job misses by millimetres. The numbers are worked out from the
   real board's pads (sm-board.js), to scale. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C, B = window.SMBoard;
  var CASES = {
    good: { dx: 0, dy: 0, rot: 0, mirror: false },
    shift: { dx: 0.25, dy: -0.15, rot: 0, mirror: false },
    turn: { dx: 0, dy: 0, rot: 0.6, mirror: false },
    mirror: { dx: 0, dy: 0, rot: 0, mirror: true }
  };

  A.define("sm-rim", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 480 : 300;
    var svg = A.stage(host, W, H, "Three pads under the ink with the laser's opening on each: an even rim of ink when the job is lined up, a lopsided one when it is not");

    // the board, small, to say which three
    var K = narrow ? 4 : 4.6, OX = 22, OY = 42;
    function sx(x) { return OX + x * K; }
    function sy(y) { return OY + (B.H - y) * K; }
    A.text(svg, OX, 28, "THE THREE, FAR APART", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: sx(0), y: sy(B.H), width: B.W * K, height: B.H * K, fill: B.INK, stroke: C.ruleStrong });
    B.PADS.forEach(function (p) { B.pad(svg, p, sx, sy, K, { fill: B.UNDER, opacity: 0.55 }); });
    B.CHECK.forEach(function (i, n) {
      var p = B.PADS[i];
      A.el(svg, "circle", { cx: sx(p[0]), cy: sy(p[1]), r: 10, fill: "none", stroke: C.caution, "stroke-width": 2 });
      A.text(svg, sx(p[0]) + (p[0] > 27 ? -14 : 14), sy(p[1]) + 5, "ABC"[n], { size: 15, weight: 700, anchor: p[0] > 27 ? "end" : "start", fill: C.caution });
    });

    // three zooms: 2.6 mm across
    var ZY = narrow ? OY + B.H * K + 42 : 42, ZS = narrow ? 150 : 172, GAP = narrow ? 11 : 14;
    var ZX0 = narrow ? (W - 3 * ZS - 2 * GAP) / 2 : sx(B.W) + 22;
    if (!narrow) ZS = Math.min(ZS, (W - ZX0 - 16 - 2 * GAP) / 3);
    var ZK = ZS / 2.6;
    var defs = A.el(svg, "defs");
    var zooms = B.CHECK.map(function (i, n) {
      var p = B.PADS[i], x = ZX0 + n * (ZS + GAP), id = "smRim" + n;
      A.el(A.el(defs, "clipPath", { id: id }), "rect", { x: x, y: ZY, width: ZS, height: ZS });
      var g = A.el(svg, "g", { "clip-path": "url(#" + id + ")" });
      A.el(g, "rect", { x: x, y: ZY, width: ZS, height: ZS, fill: B.INK });
      var cx = x + ZS / 2, cy = ZY + ZS / 2;
      var pw = p[2] + 0.2, ph = p[3] + 0.2;
      A.el(g, "rect", { x: cx - pw / 2 * ZK, y: cy - ph / 2 * ZK, width: pw * ZK, height: ph * ZK, fill: B.UNDER });
      var op = A.el(g, "rect", { width: p[2] * ZK, height: p[3] * ZK, fill: C.copperHi, stroke: "#f2c189", "stroke-width": 1 });
      A.el(svg, "rect", { x: x, y: ZY, width: ZS, height: ZS, fill: "none", stroke: C.ruleStrong });
      A.text(svg, x + 8, ZY + 20, "ABC"[n], { size: 15, weight: 700, fill: C.caution });
      var t1 = A.text(svg, x + ZS / 2, ZY + ZS + 24, "", { size: 15, weight: 700, font: "mono", anchor: "middle" });
      var t2 = A.text(svg, x + ZS / 2, ZY + ZS + 44, "", { size: narrow ? 13 : 12.5, anchor: "middle", fill: C.text2 });
      return { p: p, op: op, cx: cx, cy: cy, t1: t1, t2: t2 };
    });

    var cases = "good", nx = 0, ny = 0, nrot = 0, ready = false;

    /* Where the job puts a pad's opening, given the error and the operator's nudges. */
    function placed(p) {
      var c = CASES[cases];
      var x = c.mirror ? B.W - p[0] : p[0], y = p[1];
      var rot = (c.rot + nrot) * Math.PI / 180;
      var mx = x - B.W / 2, my = y - B.H / 2;
      return [B.W / 2 + mx * Math.cos(rot) - my * Math.sin(rot) + c.dx + nx,
              B.H / 2 + mx * Math.sin(rot) + my * Math.cos(rot) + c.dy + ny];
    }

    function draw() {
      var worst = 0;
      zooms.forEach(function (z) {
        var q = placed(z.p), ex = q[0] - z.p[0], ey = q[1] - z.p[1], err = Math.hypot(ex, ey);
        worst = Math.max(worst, err);
        var deg = -(CASES[cases].rot + nrot);
        A.set(z.op, {
          x: z.cx + ex * ZK - z.p[2] / 2 * ZK, y: z.cy - ey * ZK - z.p[3] / 2 * ZK,
          transform: "rotate(" + deg + " " + (z.cx + ex * ZK) + " " + (z.cy - ey * ZK) + ")"
        });
        z.t1.textContent = err >= 10 ? err.toFixed(0) + " mm off" : err.toFixed(2) + " mm off";
        z.t1.setAttribute("fill", err <= 0.1001 ? C.ok : C.danger);
        z.t2.textContent = err <= 0.005 ? (narrow ? "even rim" : "even rim, 0.10 mm all round")
          : err <= 0.1001 ? (narrow ? "thin on one side" : "rim thin on one side")
          : err > 2 ? (narrow ? "nowhere near" : "nowhere near its pad")
          : (narrow ? "over the edge" : "over the pad's edge");
      });
      if (CASES[cases].mirror) {
        say("bad", "Openings nowhere near their pads: the job is mirrored. The file is already mirrored, so it was flipped again in the xTool software. Stop, and re-import it.");
      } else if (worst <= 0.1001) {
        say("ok", "Worst pad " + worst.toFixed(2) + " mm: within 0.10 mm. Open the rest without moving the board.");
      } else {
        say("caution", "Worst pad " + worst.toFixed(2) + " mm: over 0.10 mm. Nudge X, Y or the rotation below until all three are within it.");
      }
    }

    var row = A.controls(host);
    var seg = A.segmented(row, [["good", "Lined up"], ["shift", "Shifted"], ["turn", "Turned"], ["mirror", "Mirrored"]], "good", function (v) {
      cases = v;
      if (!ready) return;
      if (sX) { sX.value = 0; sY.value = 0; sR.value = 0; sX.dispatchEvent(new Event("input")); sY.dispatchEvent(new Event("input")); sR.dispatchEvent(new Event("input")); }
      draw();
    });
    var sX = A.slider(row, "Nudge X", -0.4, 0.4, 0.05, 0, function (v) { nx = v; if (ready) draw(); }, function (v) { return v.toFixed(2) + " mm"; });
    var sY = A.slider(row, "Nudge Y", -0.4, 0.4, 0.05, 0, function (v) { ny = v; if (ready) draw(); }, function (v) { return v.toFixed(2) + " mm"; });
    var sR = A.slider(row, "Turn", -0.8, 0.8, 0.05, 0, function (v) { nrot = v; if (ready) draw(); }, function (v) { return v.toFixed(2) + "°"; });
    var st = A.status(row);
    function say(kind, s) { st.className = "anim-status" + (kind ? " " + kind : ""); st.textContent = s; }
    ready = true;
    draw();
  });
})();
