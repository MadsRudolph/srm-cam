/* No PC at the mill: your own laptop runs both programs. The white USB cable is the
   mill itself (VPanel drives it); the black one is the Arduino probe link inside the
   machine (SRM-CAM reads position and touch through it). */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  A.define("laptop", function (host) {
    var W = 880, H = 400;
    var s = A.stage(host, W, H, "A laptop running SRM-CAM and VPanel, wired to the SRM-20 by a white USB cable and to the Arduino probe link by a black one");

    // the laptop
    var lx = 70, ly = 110;
    A.el(s, "rect", { x: lx, y: ly, width: 250, height: 160, rx: 10, fill: C.raised, stroke: C.ruleStrong, "stroke-width": 3 });
    A.el(s, "rect", { x: lx + 14, y: ly + 14, width: 222, height: 132, rx: 4, fill: C.panelHi });
    var winA = A.el(s, "rect", { x: lx + 26, y: ly + 28, width: 198, height: 44, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(s, lx + 125, ly + 57, "SRM-CAM", { anchor: "middle", size: 23, weight: 600, font: "label" });
    var winB = A.el(s, "rect", { x: lx + 26, y: ly + 86, width: 198, height: 44, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(s, lx + 125, ly + 115, "VPanel", { anchor: "middle", size: 23, weight: 600, font: "label" });
    A.el(s, "path", { d: "M" + (lx - 26) + " " + (ly + 170) + " h302 l18 22 h-338 z", fill: C.steelDim });
    A.text(s, lx + 125, ly + 232, "your laptop: install both", { anchor: "middle", size: 20, fill: C.text2 });

    // the machine, and the Arduino inside it
    var mx = 560, my = 40;
    A.el(s, "rect", { x: mx, y: my, width: 290, height: 320, rx: 10, fill: C.panel, stroke: C.ruleStrong, "stroke-width": 2 });
    A.text(s, mx + 16, my + 30, "SRM-20", { size: 20, weight: 600, font: "label", fill: C.text2 });
    // gantry and spindle
    A.el(s, "rect", { x: mx + 30, y: my + 60, width: 230, height: 16, fill: C.steelDim });
    A.el(s, "rect", { x: mx + 128, y: my + 76, width: 34, height: 58, fill: C.steel });
    A.el(s, "polygon", { points: [mx + 140, my + 134, mx + 150, my + 134, mx + 145, my + 158].join(","), fill: C.text });
    A.el(s, "rect", { x: mx + 40, y: my + 160, width: 210, height: 14, fill: C.copper });
    A.el(s, "rect", { x: mx + 40, y: my + 174, width: 210, height: 12, fill: C.board });
    // controller port area
    var mill = A.el(s, "rect", { x: mx + 20, y: my + 214, width: 120, height: 86, rx: 6, fill: C.raised, stroke: C.ruleStrong });
    A.text(s, mx + 80, my + 250, "the mill", { anchor: "middle", size: 21, weight: 600 });
    A.text(s, mx + 80, my + 272, "(USB port)", { anchor: "middle", size: 17, fill: C.text3 });
    var ard = A.el(s, "rect", { x: mx + 152, y: my + 214, width: 120, height: 86, rx: 6, fill: "#0b4f66", stroke: "#2a8fb0" });
    for (var i = 0; i < 6; i++) A.el(s, "rect", { x: mx + 162 + i * 17, y: my + 220, width: 8, height: 6, fill: C.text2 });
    A.text(s, mx + 212, my + 256, "Arduino", { anchor: "middle", size: 21, weight: 600 });
    A.text(s, mx + 212, my + 278, "probe link", { anchor: "middle", size: 17, fill: C.text2 });

    // cables: white to the mill, black to the Arduino
    var pWhite = "M" + (lx + 250) + " " + (ly + 50) + " C 450 160, 460 " + (my + 257) + ", " + (mx + 20) + " " + (my + 257);
    var pBlack = "M" + (lx + 250) + " " + (ly + 110) + " C 420 360, " + (mx + 212) + " 395, " + (mx + 212) + " " + (my + 300);
    function cable(d, col, core) {
      var g = A.el(s, "g");
      A.el(g, "path", { d: d, fill: "none", stroke: core, "stroke-width": 13, "stroke-linecap": "round" });
      var main = A.el(g, "path", { d: d, fill: "none", stroke: col, "stroke-width": 9, "stroke-linecap": "round" });
      return { g: g, main: main };
    }
    var cw = cable(pWhite, "#eceef1", "#9aa1ab");
    var cb = cable(pBlack, "#26282c", "#5b616b");
    var labW = A.text(s, 400, 140, "white USB", { size: 22, weight: 600, fill: C.text });
    var labB = A.text(s, 380, 330, "black USB", { size: 22, weight: 600, fill: C.text2 });

    // data pulses
    var pw = cw.main, pb = cb.main;
    var Lw = pw.getTotalLength(), Lb = pb.getTotalLength();
    var dotsW = [], dotsB = [];
    for (i = 0; i < 3; i++) {
      dotsW.push(A.el(s, "circle", { r: 5, fill: C.live }));
      dotsB.push(A.el(s, "circle", { r: 5, fill: C.ok }));
    }

    var row = A.controls(host);
    var st = A.status(row);
    var focus = null;
    function show(which) {
      focus = which;
      var w = which !== "black", b = which !== "white";
      cw.g.setAttribute("opacity", w ? 1 : 0.25);
      cb.g.setAttribute("opacity", b ? 1 : 0.25);
      mill.setAttribute("stroke", which === "white" ? C.live : C.ruleStrong);
      ard.setAttribute("stroke", which === "black" ? C.ok : "#2a8fb0");
      winB.setAttribute("stroke", which === "white" ? C.live : C.ruleHi);
      winA.setAttribute("stroke", which === "black" ? C.ok : C.ruleHi);
      labW.setAttribute("opacity", w ? 1 : 0.3);
      labB.setAttribute("opacity", b ? 1 : 0.3);
      dotsW.forEach(function (d) { d.setAttribute("opacity", w ? 1 : 0); });
      dotsB.forEach(function (d) { d.setAttribute("opacity", b ? 1 : 0); });
      st.textContent = which === "white"
        ? "White USB → the mill. VPanel sends the .nc files and jogs the machine through it."
        : which === "black"
          ? "Black USB → the Arduino probe link. SRM-CAM reads the head's position and the touch through it."
          : "Plug in both cables. Each program only needs its own: VPanel the white one, SRM-CAM the black one.";
    }
    A.button(row, "White: the mill", function () { show("white"); });
    A.button(row, "Black: the probe link", function () { show("black"); });
    A.button(row, "Both", function () { show(null); });
    row.appendChild(st);
    [[cw.g, "white"], [cb.g, "black"], [mill, "white"], [ard, "black"]].forEach(function (p) {
      p[0].style.cursor = "pointer";
      p[0].addEventListener("mouseenter", function () { show(p[1]); });
      p[0].addEventListener("click", function () { show(p[1]); });
    });
    show(null);

    A.loop(host, function (t) {
      for (var k = 0; k < 3; k++) {
        var fw = ((t * 0.35 + k / 3) % 1), fb = ((t * 0.35 + k / 3 + 0.15) % 1);
        var a = pw.getPointAtLength(fw * Lw), b2 = pb.getPointAtLength((1 - fb) * Lb);
        A.set(dotsW[k], { cx: a.x, cy: a.y });
        A.set(dotsB[k], { cx: b2.x, cy: b2.y });
      }
    }, 0.4);
  });
})();
