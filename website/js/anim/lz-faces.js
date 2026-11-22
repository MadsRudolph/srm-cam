/* One sheet, the laser's jobs, and which face is up (window.py _laser_jobs; engine
   silkscreen.py, soldermask.py). KiCad draws the board seen from the top. A usual laser
   board has its copper on B.Cu: the sheet lies copper face up, so the laser sees the
   board straight on, not through it as KiCad draws it, and the copper is etched mirrored. The mask (B.Mask) is the same face,
   mirrored too. The silkscreen (F.Silkscreen) is on the component side: the sheet is
   turned over left-right, laminate up, and the drawing is as KiCad shows it. A board with
   copper on both faces is etched once per face, the sheet turned over between, with
   Copper face set to F.Cu for the second. Each time the same drilled holes are what
   Calibrate (traces) or Align (mask, silk) find. Schematic: a 50 x 32 mm board. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BW = 50, BH = 32;
  var HOLES = [[-21, -12], [21, -12], [-21, 12], [8, 11], [14, 11], [-6, -4]];
  var BCU = [[-21, -12], [-21, -2], [-6, -2], [-6, -4]];          // a trace on B.Cu
  var BCU2 = [[21, -12], [21, 4], [14, 4], [14, 11]];
  var FCU = [[-21, 12], [-12, 12], [-12, 2], [8, 2], [8, 11]];      // a trace on F.Cu

  var JOBS = {
    bcu: { face: "B", label: "Etch the traces", sub: "B.Cu — bottom copper", mirror: true, how: "Calibrate",
      say: "Copper face up, as it came off the mill. KiCad draws B.Cu as seen through the board; here you look straight at it, so it is etched mirrored. Calibrate finds the drilled holes." },
    mask: { face: "B", label: "Open the mask", sub: "B.Mask, inked copper face up", mirror: true, how: "Calibrate: five test pads",
      say: "The same face, now inked: the openings are mirrored like the copper. Calibrate finds the drilled holes through the ink, opens five test pads and lines the job up on their copper." },
    silk: { face: "F", label: "Mark the silkscreen", sub: "F.Silkscreen, laminate up", mirror: false, how: "Autofocus, then Align",
      say: "Turned over left to right: the laminate (the component side) is up and the drawing is as KiCad shows it, not mirrored. Autofocus on the laminate, then Align on the same holes." },
    fcu: { face: "F", label: "Etch the traces", sub: "F.Cu — top copper", mirror: false, how: "Calibrate again",
      say: "A board with copper on both faces: after B.Cu, turn the sheet over, set Copper face to F.Cu and Calibrate again. F.Cu is etched as drawn." }
  };

  A.define("lz-faces", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880;
    var PW = narrow ? 470 : 390, K = PW / 78;           // the panels show 78 mm across
    var PH = 56 * K;
    var LX = narrow ? 25 : 30, LY = 60, RX = narrow ? 25 : 460, RY = narrow ? LY + PH + 56 : 60;
    var H = narrow ? RY + PH + 170 : 430;
    var svg = A.stage(host, W, H, "The board as KiCad draws it, beside the sheet on the laser bed for each job: which face is up, and whether the drawing is mirrored");

    function panel(x, y, title) {
      A.text(svg, x, y - 14, title, { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
      A.el(svg, "rect", { x: x, y: y, width: PW, height: PH, fill: C.sunk, stroke: C.ruleStrong });
      return A.el(svg, "g", { transform: "translate(" + (x + PW / 2) + " " + (y + PH / 2) + ") scale(" + K + ")" });
    }
    function poly(g, pts, o) { return A.el(g, "polyline", Object.assign({ points: pts.map(function (p) { return p.join(","); }).join(" "), fill: "none", "stroke-linejoin": "round", "stroke-linecap": "round" }, o)); }

    // --- KiCad's view, from the top: F.Silkscreen reads right, B.Cu seen through
    var kg = panel(LX, LY, "IN KICAD, SEEN FROM THE TOP");
    A.el(kg, "rect", { x: -BW / 2, y: -BH / 2, width: BW, height: BH, fill: "#1b2a1f", stroke: C.fr4Hi, "stroke-width": 0.4 });
    poly(kg, BCU, { stroke: C.live, "stroke-width": 1.2, opacity: 0.55 });
    poly(kg, BCU2, { stroke: C.live, "stroke-width": 1.2, opacity: 0.55 });
    poly(kg, FCU, { stroke: C.danger, "stroke-width": 1.2, opacity: 0.55 });
    var ks = A.el(kg, "text", { x: 0, y: -5, "font-size": 7, "font-weight": 700, fill: C.text, "font-family": "sans-serif" }, "SRM");
    A.el(kg, "rect", { x: -9, y: 5, width: 8, height: 5, fill: "none", stroke: C.text, "stroke-width": 0.5 });
    HOLES.forEach(function (h) { A.el(kg, "circle", { cx: h[0], cy: h[1], r: 1.1, fill: C.ink, stroke: C.text3, "stroke-width": 0.3 }); });
    A.text(svg, LX + 8, LY + PH - 10, "B.Cu blue · F.Cu red · F.Silkscreen white", { size: 12, fill: C.text3 });

    // --- the laser bed
    var bg = panel(RX, RY, "ON THE LASER BED, SEEN FROM ABOVE");
    var flip = A.el(bg, "g");
    var sheet = A.el(flip, "rect", { x: -37, y: -25, width: 74, height: 50, fill: C.copper, stroke: C.copperDim, "stroke-width": 0.4 });
    var chan = A.el(flip, "rect", { x: -BW / 2 - 0.8, y: -BH / 2 - 0.8, width: BW + 1.6, height: BH + 1.6, fill: "none", stroke: C.ink, "stroke-width": 0.8 });
    var face = A.el(flip, "rect", { x: -BW / 2, y: -BH / 2, width: BW, height: BH, fill: C.copper });
    var ink = A.el(flip, "rect", { x: -BW / 2 - 2, y: -BH / 2 - 2, width: BW + 4, height: BH + 4, fill: "#1f5a35", opacity: 0 });
    var art = A.el(flip, "g");
    var holesG = A.el(flip, "g");
    HOLES.forEach(function (h) { A.el(holesG, "circle", { cx: h[0], cy: h[1], r: 1.1, fill: C.ink }); });
    var found = A.el(flip, "g");
    HOLES.forEach(function (h) { A.el(found, "circle", { cx: h[0], cy: h[1], r: 2.2, fill: "none", stroke: C.ok, "stroke-width": 0.5 }); });

    // words
    var TY = narrow ? RY + PH + 30 : LY + PH + 40, TX = LX;
    var t1 = A.text(svg, TX, TY, "", { size: 16, weight: 700, fill: C.text });
    var t2 = A.text(svg, TX, TY + 24, "", { size: 14, fill: C.text2 });
    var t3 = A.text(svg, TX, TY + 46, "", { size: 14, fill: C.text2 });
    var side = A.el(svg, "g", { transform: "translate(" + (narrow ? LX + 120 : RX + 120) + " " + (narrow ? TY + 100 : TY - 10) + ")" });

    var row = A.controls(host);
    var cur = "bcu", flipT = 1, flipFrom = 1, flipTo = 1, t0 = -1;
    var st = null;
    var seg = A.segmented(row, [["bcu", "Traces"], ["mask", "Mask"], ["silk", "Silk"], ["fcu", "Second face (F.Cu)"]], "bcu", function (v) { pick(v); });
    st = A.status(row);
    pick("bcu");

    function sideView(j) {
      while (side.firstChild) side.removeChild(side.firstChild);
      var top = { bcu: C.copperHi, mask: C.copperHi, silk: C.fr4Hi, fcu: C.copperHi }[cur];
      var bot = { bcu: C.fr4Hi, mask: C.fr4Hi, silk: C.copperHi, fcu: C.copperHi }[cur];
      A.text(side, 0, -4, "edge-on:", { size: 12, fill: C.text3 });
      A.el(side, "rect", { x: 60, y: -12, width: 120, height: 9, fill: C.fr4 });
      A.el(side, "rect", { x: 60, y: -14.5, width: 120, height: 2.5, fill: top });
      A.el(side, "rect", { x: 60, y: -3, width: 120, height: 2.5, fill: bot });
      if (cur === "mask") A.el(side, "rect", { x: 60, y: -18, width: 120, height: 3.5, fill: "#2f9a5d" });
      if (cur === "silk") A.el(side, "rect", { x: 60, y: -0.5, width: 120, height: 3, fill: "#2f9a5d" });
      A.arrow(side, 120, -40, 120, -20, { color: C.live, width: 2, head: 6 });
      A.text(side, 128, -30, "laser", { size: 12, fill: C.live });
    }

    function pick(v) {
      cur = v;
      var j = JOBS[v];
      flipFrom = flipT; flipTo = j.face === "B" ? 1 : -1; t0 = 0;
      // the face colour seen from above
      var copperUp = j.face === "B" || v === "fcu";
      A.set(face, { fill: copperUp ? C.copper : C.fr4 });
      A.set(sheet, { fill: copperUp ? C.copper : C.fr4 });
      A.set(ink, { opacity: v === "mask" ? 0.92 : 0 });
      while (art.firstChild) art.removeChild(art.firstChild);
      // art in board coordinates as seen from the top; the flip group mirrors it when B is up
      if (v === "bcu") {
        [BCU, BCU2].forEach(function (p) { poly(art, p, { stroke: C.live, "stroke-width": 2.2, opacity: 0.9 }); poly(art, p, { stroke: C.copper, "stroke-width": 1.2 }); });
      } else if (v === "fcu") {
        poly(art, FCU, { stroke: C.live, "stroke-width": 2.2, opacity: 0.9 }); poly(art, FCU, { stroke: C.copper, "stroke-width": 1.2 });
      } else if (v === "mask") {
        HOLES.forEach(function (h) { A.el(art, "circle", { cx: h[0], cy: h[1], r: 2.0, fill: C.copperHi, stroke: C.live, "stroke-width": 0.4 }); });
      } else {
        A.el(art, "text", { x: 0, y: -5, "font-size": 7, "font-weight": 700, fill: C.text, stroke: C.live, "stroke-width": 0.15, "font-family": "sans-serif" }, "SRM");
        A.el(art, "rect", { x: -9, y: 5, width: 8, height: 5, fill: "none", stroke: C.text, "stroke-width": 0.5 });
      }
      t1.textContent = j.label + " · " + j.sub;
      t2.textContent = (j.mirror ? "Drawing mirrored" : "Drawing as in KiCad") + " · lined up by " + j.how;
      t3.textContent = j.face === "B" ? "Copper face up, the same way up as on the mill" : "Sheet turned over left to right";
      sideView(j);
      if (st) { st.className = "anim-status"; st.textContent = j.say; }
    }
    A.loop(host, function (t, dt) {
      if (t0 < 0) return;
      t0 += dt;
      var p = A.ease(t0 / 0.9);
      flipT = A.lerp(flipFrom, flipTo, p);
      A.set(flip, { transform: "scale(" + (flipT * -1) + " 1)" });
      if (p >= 1) t0 = -1;
    }, 5);
    A.set(flip, { transform: "scale(-1 1)" });
    var q = /[?&]face=(\w+)/.exec(location.search);
    if (q && JOBS[q[1]]) { seg.set(q[1]); flipT = flipTo; t0 = -1; A.set(flip, { transform: "scale(" + (flipT * -1) + " 1)" }); }
  });
})();
