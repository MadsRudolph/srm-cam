/* "zeroz" — Zero Z on the copper, VPanel by hand. Pick the coordinate system (it must be
   G54: NC files run in G54), lower Z a press at a time — ×100 is 1 mm, ×10 a tenth,
   ×1 a hundredth — until SRM-CAM's Z readout says Touch, then Set Origin Point › Z.
   Positions are machine Z in hundredths of a millimetre, so no float drift. The copper
   is at machine Z −38.00, the same head as the Z-travel figure. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var SURF = -3800;                 // copper surface, machine Z, 0.01 mm
  var START = -3313;                // 4.87 mm above it
  var OFFS = { Machine: 0, User: -3000, G54: -3640 };   // each system's zero, in machine Z

  A.define("zeroz", function (host) {
    // under 560 px the right-hand panel goes under the drawing, so the text stays readable
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 490 : 880, H = narrow ? 870 : 440;
    var svg = A.stage(host, W, H, "Lowering Z onto the copper in VPanel and setting the G54 Z origin");
    var pos = START, sys = "Machine", step = 100, g54 = OFFS.G54, done = false, shown = START;

    // ---- side view ---------------------------------------------------------
    A.el(svg, "rect", { x: 10, y: 10, width: 470, height: 420, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(svg, 28, 40, "SIDE VIEW · SPINDLE OFF", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var CU = 350, K = 52;                           // px per mm above the copper
    A.el(svg, "rect", { x: 40, y: CU, width: 420, height: 10, fill: C.copper });
    A.el(svg, "rect", { x: 40, y: CU + 10, width: 420, height: 50, fill: C.board });
    var zc = A.el(A.el(svg, "defs"), "clipPath", { id: "zerozClip" });
    A.el(zc, "rect", { x: 11, y: 52, width: 468, height: 377 });
    var head = A.el(A.el(svg, "g", { "clip-path": "url(#zerozClip)" }), "g");
    A.el(head, "rect", { x: 222, y: -400, width: 16, height: 400, fill: C.steel });
    A.el(head, "line", { x1: 222, x2: 238, y1: 0, y2: 0, stroke: C.copperHi, "stroke-width": 3 });
    var gapG = A.el(svg, "g");
    var gapL = A.el(gapG, "line", { x1: 262, x2: 262, stroke: C.text3, "stroke-width": 1.5 });
    var gapT = A.text(gapG, 272, 0, "", { size: 18, weight: 600, font: "mono", fill: C.text });
    // magnifier for the last millimetre
    var mag = A.el(svg, "g", { opacity: 0 });
    A.el(mag, "rect", { x: 280, y: 70, width: 180, height: 170, rx: 4, fill: C.sunk, stroke: C.caution });
    A.text(mag, 292, 94, "ZOOM", { size: 15, weight: 700, fill: C.caution, font: "mono" });
    A.el(mag, "rect", { x: 281, y: 200, width: 178, height: 39, fill: C.copper });
    var magBit = A.el(mag, "rect", { x: 350, width: 40, fill: C.steel });
    var zeroLine = A.el(svg, "g", { opacity: 0 });
    A.el(zeroLine, "line", { x1: 30, x2: 470, y1: CU, y2: CU, stroke: C.caution, "stroke-width": 2, "stroke-dasharray": "7 5" });
    A.text(zeroLine, 40, CU - 12, "G54 Z 0", { size: 16, weight: 700, fill: C.caution });

    // ---- VPanel + SRM-CAM readouts ------------------------------------------
    var RP = A.el(svg, "g", { transform: narrow ? "translate(-486,440)" : null });
    A.el(RP, "rect", { x: 496, y: 10, width: 374, height: 420, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(RP, 514, 40, "VPANEL", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var sysBox = A.el(RP, "rect", { x: 514, y: 54, width: 338, height: 38, rx: 3, fill: "#ececec", "stroke-width": 3 });
    var sysT = A.text(RP, 526, 79, "", { size: 16, fill: "#141414" });
    var rows = {};
    ["X", "Y", "Z"].forEach(function (a, i) {
      var y = 136 + i * 40;
      A.text(RP, 514, y, a, { size: 22, weight: 700, font: "mono", fill: C.text2 });
      rows[a] = A.text(RP, 852, y, "", { size: 24, weight: 600, font: "mono", anchor: "end" });
    });
    A.text(RP, 514, 244, "Cursor step", { size: 15, fill: C.text2 });
    var stepT = A.text(RP, 852, 244, "", { size: 16, weight: 600, font: "mono", anchor: "end", fill: C.caution });
    A.el(RP, "line", { x1: 514, y1: 266, x2: 852, y2: 266, stroke: C.rule });
    A.text(RP, 514, 296, "SRM-CAM · Z READOUT", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var tBox = A.el(RP, "rect", { x: 514, y: 310, width: 338, height: 56, rx: 4, "stroke-width": 2 });
    var tLab = A.text(RP, 530, 345, "", { size: 20, weight: 700, font: "label" });
    var tVal = A.text(RP, 836, 345, "", { size: 22, weight: 600, font: "mono", anchor: "end" });
    A.text(RP, 514, 392, "machine Z; red while the bit is on the copper", { size: 15, fill: C.text2 });

    function f2(v) { var x = v / 100; return (x < 0 ? "−" : " ") + Math.abs(x).toFixed(2); }
    function touching() { return pos <= SURF; }

    function draw() {
      var gap = (shown - SURF) / 100;
      var y = CU - Math.min(gap, 5.4) * K;
      A.set(head, { transform: "translate(0," + y + ")" });
      A.set(gapL, { y1: y, y2: CU });
      A.set(gapT, { y: (y + CU) / 2 + 6 });
      gapT.textContent = gap > 0.004 ? gap.toFixed(2) + " mm" : "";
      mag.setAttribute("opacity", gap <= 1.0 ? 1 : 0);
      A.set(magBit, { y: 71, height: 200 - Math.min(gap, 1) * 120 - 71 });   // the last millimetre over 120 px
      sysT.textContent = sys === "Machine" ? "Machine Coord. System" : sys === "User" ? "User Coord. System" : "G54";
      sysBox.setAttribute("stroke", sys === "G54" ? C.ok : C.caution);
      var z0 = sys === "G54" ? g54 : OFFS[sys];
      rows.X.textContent = " 60.52";                 // X and Y: G54's XY is the machine origin
      rows.Y.textContent = " 24.42";
      rows.Z.textContent = f2(pos - z0);
      stepT.textContent = { 100: "×100 = 1 mm", 10: "×10 = 0.1 mm", 1: "×1 = 0.01 mm" }[step];
      var t = touching();
      A.set(tBox, { fill: t ? C.dangerFill : C.sunk, stroke: t ? C.danger : C.ruleStrong });
      tLab.textContent = t ? "Touch" : "Z";
      tLab.setAttribute("fill", t ? C.danger : C.text2);
      tVal.textContent = f2(pos);
      tVal.setAttribute("fill", t ? C.danger : C.text);
      zeroLine.setAttribute("opacity", done ? 1 : 0);
    }

    // a short tween so a press reads as a move
    var tw = { a: pos, b: pos, t0: 0 };
    function tick(tt) {
      var k = A.ease((tt - tw.t0) / 0.2);
      shown = Math.round(A.lerp(tw.a, tw.b, k));
      draw();
      if (k >= 1 && lp) lp.stop();
    }
    function moveTo(p) {
      tw = { a: shown, b: p, t0: 0 };                // restart() puts the clock back to 0
      pos = p;
      if (A.reduced || !lp) { shown = p; draw(); } else lp.restart();
    }

    var row = A.controls(host);
    A.segmented(row, [["Machine", "Machine"], ["User", "User"], ["G54", "G54"]], sys, function (v) {
      sys = v; draw(); if (lp) msg(v === "G54" ? "ok" : "warn", v === "G54" ? "G54: the system NC files run in." : v + " is not what the files use: set the origin in G54.");
    });
    A.segmented(row, [[100, "×100"], [10, "×10"], [1, "×1"]], step, function (v) { step = v; draw(); });
    A.button(row, "↓ Z", function () { jog(-1); }, "key", "Lower Z one step");
    A.button(row, "↑ Z", function () { jog(1); }, "key", "Raise Z one step");
    A.button(row, "Set Origin Point › Z", setZ, "primary");
    A.button(row, "Reset", function () { done = false; g54 = OFFS.G54; sys = "Machine"; seg1Reset(); moveTo(START); msg("", "Start again: 4.87 mm above the copper, VPanel on Machine."); });
    var st = A.status(row);
    function msg(kind, s) { st.className = "anim-status" + (kind ? " " + kind : ""); st.textContent = s; }
    function seg1Reset() { row.querySelector(".anim-seg").querySelectorAll("button").forEach(function (b, i) { b.classList.toggle("on", i === 0); }); }

    function jog(dir) {
      if (dir < 0) {
        if (touching()) { msg("bad", "Refused: the bit is already touching. SRM-CAM won't jog down while it reads Touch."); return; }
        var n = pos - step;
        if (n < SURF) {
          if (SURF - n > 10) { msg("bad", "That press would drive the bit " + ((SURF - n) / 100).toFixed(2) + " mm into the copper. Use a smaller step this close."); return; }
          n = SURF;                                 // within a tenth: it lands on the copper
        }
        moveTo(n);
        msg(n === SURF ? "ok" : "", n === SURF ? "TOUCH: the bit is on the copper. One press up and it goes out; one down and it's back." : ((n - SURF) / 100).toFixed(2) + " mm above the copper.");
      } else {
        moveTo(pos + step);
        msg("", ((pos - SURF) / 100).toFixed(2) + " mm above the copper.");
      }
    }
    function setZ() {
      if (sys !== "G54") { msg("bad", "VPanel is on " + sys + ": switch to G54 first."); return; }
      if (!touching()) { msg("bad", "Lower until TOUCH first."); return; }
      g54 = SURF; done = true; draw();
      msg("ok", "Z origin set on the copper: G54 Z reads 0.00. X and Y stay where they are.");
    }

    var lp = null;
    lp = A.loop(host, tick, 0);
    draw();
    msg("", "VPanel starts on Machine. Pick G54, then lower Z until SRM-CAM reads Touch.");
  });
})();
