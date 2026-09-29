/* "zlimit" — Mind the Z travel. How far the bit sticks out of the collet decides how far
   down the head must go before the tip reaches the copper. The mill's Z ends at machine
   Z −55; with the bit on the copper, machine Z must stay above −50, or the drill and the
   cut-out keep hitting the limit and stop. VPanel's G54 readout hides this (it reads 0
   at the copper once zeroed): switch it to Machine to check, or read SRM-CAM's bottom
   bar, which is always machine Z. Schematic: one fixed copper height, head to scale. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var D = 58;                 // machine Z the collet nose would reach with the tip flush (stick-out 0)

  function zone(z) {
    if (z <= -55) return { c: C.danger, w: "end of travel" };
    if (z < -50) return { c: C.caution, w: "too low" };
    return { c: C.ok, w: "fine" };
  }

  A.define("zlimit", function (host) {
    // under 560 px the right-hand panel goes under the drawing, so the text stays readable
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 540 : 880, H = narrow ? 990 : 500;
    var svg = A.stage(host, W, H, "Machine Z of the head when the bit touches the copper, against the mill's Z travel");
    var Y0 = 58, K = 6.3;                            // screen y of machine Z 0; px per mm
    function zy(z) { return Y0 - z * K; }
    var CU = zy(-D);                                 // the copper surface (tip lands here)

    // left panel: side view
    A.el(svg, "rect", { x: 10, y: 10, width: 520, height: 480, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(svg, 28, 40, "SIDE VIEW", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    A.el(svg, "rect", { x: 90, y: CU, width: 310, height: 9, fill: C.copper });
    A.el(svg, "rect", { x: 90, y: CU + 9, width: 310, height: 36, fill: C.board });
    A.text(svg, 245, CU + 33, "copper on the spoilboard", { size: 15, anchor: "middle", fill: "#e6d9c4" });

    // the ruler, zones and labels
    var RX = 452;
    A.el(svg, "rect", { x: RX - 6, y: zy(0), width: 12, height: zy(-50) - zy(0), fill: C.ok, opacity: 0.35 });
    A.el(svg, "rect", { x: RX - 6, y: zy(-50), width: 12, height: zy(-55) - zy(-50), fill: C.caution });
    A.el(svg, "rect", { x: RX - 6, y: zy(-55), width: 12, height: zy(-60.5) - zy(-55), fill: C.danger });
    for (var z = 0; z >= -60; z -= 10) {
      A.el(svg, "line", { x1: RX - 14, y1: zy(z), x2: RX - 6, y2: zy(z), stroke: C.text3, "stroke-width": 2 });
      A.text(svg, RX + 14, zy(z) + 5, z === 0 ? "0" : "−" + (-z), { size: 15, fill: C.text2, font: "mono" });
    }
    A.text(svg, RX - 16, zy(-52.5) + 5, "too low", { size: 15, weight: 600, fill: C.caution, anchor: "end" });
    A.text(svg, RX - 16, zy(-57.8) + 5, "end −55", { size: 15, weight: 600, fill: C.danger, anchor: "end" });
    A.text(svg, RX - 16, zy(-6) + 5, "keep above −50", { size: 15, weight: 600, fill: C.ok, anchor: "end" });

    // the head
    var head = A.el(svg, "g");
    var HX = 250;
    A.el(head, "rect", { x: HX - 32, y: -98, width: 64, height: 70, rx: 3, fill: "#5b616c" });
    A.el(head, "rect", { x: HX - 24, y: -28, width: 48, height: 28, fill: C.steelDim });
    var bitR = A.el(head, "rect", { x: HX - 6, y: 0, width: 12, height: 10, fill: C.steel });
    var tipL = A.el(head, "line", { x1: HX - 6, x2: HX + 6, y1: 10, y2: 10, stroke: C.copperHi, "stroke-width": 3 });
    var stickDim = A.el(head, "g");
    var sdLine = A.el(stickDim, "line", { x1: HX - 30, x2: HX - 30, y1: 0, y2: 10, stroke: C.text3, "stroke-width": 1.5 });
    var sdText = A.text(stickDim, HX - 38, 5, "", { size: 15, anchor: "end", fill: C.text2 });
    var pointer = A.el(svg, "line", { stroke: C.ok, "stroke-width": 2, "stroke-dasharray": "5 4" });
    var dot = A.el(svg, "circle", { r: 9, fill: C.ok });
    var zlab = A.text(svg, 0, 0, "", { size: 18, weight: 700, font: "mono" });

    // right panel: the readouts
    var RP = A.el(svg, "g", { transform: narrow ? "translate(-536,500)" : null });
    A.el(RP, "rect", { x: 546, y: 10, width: 324, height: 480, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(RP, 564, 40, "VPANEL", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    A.el(RP, "rect", { x: 564, y: 56, width: 288, height: 38, rx: 3, fill: "#ececec" });
    var sysT = A.text(RP, 576, 81, "", { size: 16, fill: "#141414" });
    A.el(RP, "polygon", { points: "830,70 842,70 836,80", fill: "#141414" });
    A.text(RP, 564, 140, "Z", { size: 26, weight: 700, font: "mono", fill: C.text2 });
    var vpZ = A.text(RP, 852, 140, "", { size: 34, weight: 700, font: "mono", anchor: "end" });
    var vpNote = A.text(RP, 564, 172, "", { size: 15, fill: C.text2 });
    var vpNote2 = A.text(RP, 564, 194, "", { size: 15, fill: C.text2 });
    A.el(RP, "line", { x1: 564, y1: 226, x2: 852, y2: 226, stroke: C.rule });
    A.text(RP, 564, 258, "SRM-CAM · BOTTOM BAR", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    A.el(RP, "rect", { x: 564, y: 272, width: 288, height: 50, rx: 3, fill: C.sunk, stroke: C.ruleStrong });
    var scZ = A.text(RP, 580, 305, "", { size: 22, weight: 600, font: "mono" });
    A.text(RP, 564, 346, "always machine Z", { size: 15, fill: C.text2 });
    var verdict = A.el(RP, "g");
    var vRect = A.el(verdict, "rect", { x: 564, y: 372, width: 288, height: 100, rx: 4 });
    var vT1 = A.text(verdict, 580, 402, "", { size: 18, weight: 700 });
    var vT2 = A.text(verdict, 580, 428, "", { size: 15, fill: C.text });
    var vT3 = A.text(verdict, 580, 452, "", { size: 15, fill: C.text });

    var stick = 20, sys = "Machine", cur = -10, from = -10, target = -38, t0 = 0, phase = "idle";
    function touchZ() { return stick - D; }
    function fmt(z) { return (z < 0 ? "−" : " ") + Math.abs(z).toFixed(2); }

    function draw(z, touching) {
      var sp = stick * K;
      A.set(head, { transform: "translate(0," + zy(z) + ")" });
      A.set(bitR, { height: sp });
      A.set(tipL, { y1: sp, y2: sp });
      A.set(sdLine, { y2: sp });
      A.set(sdText, { y: sp / 2 + 5 });
      sdText.textContent = stick + " mm";
      var zn = zone(z);
      A.set(pointer, { x1: HX + 32, y1: zy(z) - 60, x2: RX - 10, y2: zy(z), stroke: zn.c });
      A.set(dot, { cx: RX, cy: zy(z), fill: zn.c });
      A.set(zlab, { x: HX + 40, y: zy(z) - 66, fill: zn.c });       // beside the head, clear of the ruler labels
      zlab.textContent = touching ? fmt(z) : "";
      sysT.textContent = sys === "G54" ? "G54" : "Machine Coord. System";
      var shown = sys === "G54" ? (touching ? 0 : z - touchZ()) : z;
      vpZ.textContent = fmt(shown);
      vpZ.setAttribute("fill", sys === "G54" ? C.text : zn.c);
      vpNote.textContent = sys === "G54" ? "zeroed on the copper: always 0.00" : "the head's real height";
      vpNote2.textContent = sys === "G54" ? "here — switch to Machine to check" : "back to G54 before you zero Z";
      scZ.textContent = (touching ? "Touch " : "Z     ") + fmt(z);
      scZ.setAttribute("fill", touching ? C.danger : C.text);
      verdict.setAttribute("opacity", touching ? 1 : 0.25);
      var tz = touchZ(), zt = zone(tz);
      A.set(vRect, { fill: tz < -50 ? (tz <= -55 ? C.dangerFill : C.cautionFill) : C.okFill, stroke: zt.c });
      vT1.setAttribute("fill", zt.c);
      vT1.textContent = "Machine Z " + fmt(tz).trim() + ": " + zt.w;
      if (tz <= -55) { vT2.textContent = "The head can't go lower: it"; vT3.textContent = "can't cut. Refit the bit."; }
      else if (tz < -50) { vT2.textContent = "Drill and cut-out hit the limit"; vT3.textContent = "and stop. Let the bit stick out."; }
      else { vT2.textContent = "Room for the drill and the"; vT3.textContent = "cut-out below the surface."; }
    }

    function tick(tt) {
      var z, touching = false;
      if (phase === "up") {
        var k = A.ease((tt - t0) / 0.35);
        z = A.lerp(from, -8, k);
        if (k >= 1) { phase = "down"; t0 = tt; from = -8; }
      } else if (phase === "down") {
        var k2 = A.ease((tt - t0) / 1.1);
        z = A.lerp(from, touchZ(), k2);
        if (k2 >= 1) { phase = "idle"; }
      } else {
        z = touchZ();
      }
      touching = phase === "idle";
      cur = z;
      draw(z, touching);
      if (phase === "idle" && lp) lp.stop();
    }

    var row = A.controls(host);
    var st = A.status(row);
    function say() {
      var tz = touchZ();
      if (tz <= -55) { st.className = "anim-status bad"; st.textContent = "Machine Z −55.0 is the end of the travel: with this little bit sticking out, the head can't cut at all."; }
      else if (tz < -50) { st.className = "anim-status bad"; st.textContent = "Machine Z " + fmt(tz).trim() + ": below −50. The drill and the cut-out will keep hitting the limit and stop. Refit the bit so it sticks out further."; }
      else { st.className = "anim-status ok"; st.textContent = "Machine Z " + fmt(tz).trim() + ": above −50, fine."; }
      if (sys === "G54") st.textContent = "VPanel on G54 reads 0.00 at the copper whatever the bit: switch to Machine to see the real height.";
      if (sys === "G54") st.className = "anim-status caution";
    }
    var lp = null;
    var first = true;
    A.slider(row, "Bit sticks out", 3, 26, 1, stick, function (v) {
      stick = v;
      if (first) { first = false; return; }
      if (A.reduced) { draw(touchZ(), true); say(); return; }
      from = cur; phase = "up"; t0 = accT; lp.restart(); say();
    }, function (v) { return v + " mm"; });
    A.segmented(row, [["G54", "VPanel: G54"], ["Machine", "VPanel: Machine"]], "Machine", function (v) {
      sys = v; if (lp) { draw(cur, phase === "idle"); say(); }
    });
    var accT = 0;
    lp = A.loop(host, function (tt) { accT = tt; tick(tt); }, 99);
    phase = "down"; from = -8; t0 = 0.3;
    if (A.reduced) { phase = "idle"; draw(touchZ(), true); }
    say();
    // restart() resets the clock to 0: keep phase times relative to it
    var rs = lp.restart;
    lp.restart = function () { accT = 0; t0 = 0; rs(); };
  });
})();
