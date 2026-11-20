/* Cutting the paste stencil (engine/stencil.py, engine/xtool.py stencil_job). The holes
   are split into 4 zones, pie slices round their middle. The recipe, 0.1 mm 304 stainless:
   100 %, 550 mm/s, 30 kHz, 30 passes per hole in bursts of 5: every zone gets a burst in
   turn, with a 6 s laser-off rest after every burst, so no spot of the thin steel gets
   30 passes in a row and warps. Round 1 is every zone once; 6 rounds make 30 passes. The
   run reads "Zone k of 4 · round r of 6". Each hole is drawn smaller than its pad by half
   the kerf (0.08 mm), 0.04 mm a side, so the cut comes out pad-sized. Time is sped up a
   lot; the pad layout is an example. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var ZONES = 4, ROUNDS = 6, BURST = 5, REST = 6;
  var PADS = [];
  (function () {
    for (var i = 0; i < 8; i++) { PADS.push([-10.5 + i * 1.27 * 2.3, -9, 1.2, 3.2]); PADS.push([-10.5 + i * 1.27 * 2.3, 9, 1.2, 3.2]); }
    [[-24, -4], [-24, 4], [24, -4], [24, 4], [-18, 16], [18, -16]].forEach(function (p) { PADS.push([p[0] - 1.6, p[1], 1.8, 1.6]); PADS.push([p[0] + 1.6, p[1], 1.8, 1.6]); });
  })();
  function zoneOf(p) {
    var a = (Math.atan2(p[1], p[0]) + Math.PI / ZONES) % (2 * Math.PI);
    if (a < 0) a += 2 * Math.PI;
    return Math.floor(a / (2 * Math.PI / ZONES)) % ZONES;
  }

  A.define("sd-stencil", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, K = narrow ? 7.6 : 7.2;
    var CX = narrow ? 260 : 250, CY = 64 + 22 * K, H = narrow ? CY + 22 * K + 330 : CY + 22 * K + 40;
    var svg = A.stage(host, W, H, "The stencil's holes in four zones, each cut in bursts of 5 passes with a rest between, and a close-up of one hole drawn 0.04 mm inside its pad");
    A.text(svg, 20, 28, "THE STENCIL, 0.1 MM STEEL · ZONES AND BURSTS", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: CX - 32 * K, y: CY - 22 * K, width: 64 * K, height: 44 * K, fill: C.steelDim, stroke: C.steel, "stroke-width": 1 });
    var zcol = [C.live, C.ok, C.caution, C.copperHi];
    var heat = [0, 0, 0, 0];
    var padEls = PADS.map(function (p) {
      var z = zoneOf(p);
      return { z: z, el: A.el(svg, "rect", { x: CX + (p[0] - p[2] / 2) * K, y: CY + (p[1] - p[3] / 2) * K, width: p[2] * K, height: p[3] * K, fill: C.ink, stroke: zcol[z], "stroke-width": 1.5 }) };
    });
    // zone dividers
    for (var z = 0; z < ZONES; z++) {
      var a = z * 2 * Math.PI / ZONES - Math.PI / ZONES;
      A.el(svg, "line", { x1: CX, y1: CY, x2: CX + Math.cos(a) * 30 * K, y2: CY + Math.sin(a) * 30 * K, stroke: C.text3, "stroke-dasharray": "3 4", opacity: 0.6 });
    }
    // close-up of a hole: the pad, the cut 0.04 mm inside it, the kerf
    var IX = narrow ? 40 : CX + 34 * K + 40, IY = narrow ? CY + 22 * K + 40 : 70, IK = narrow ? 120 : 130;
    A.text(svg, IX, IY - 10, "ONE HOLE, CLOSE UP · TO SCALE", { size: 12, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: IX, y: IY, width: 1.6 * IK, height: 1.2 * IK, fill: C.steelDim });
    var pw = 1.0, ph = 0.7, ox = IX + 0.3 * IK, oy = IY + 0.25 * IK;
    A.el(svg, "rect", { x: ox, y: oy, width: pw * IK, height: ph * IK, fill: C.ink });
    A.el(svg, "rect", { x: ox + 0.04 * IK, y: oy + 0.04 * IK, width: (pw - 0.08) * IK, height: (ph - 0.08) * IK, fill: "none", stroke: C.live, "stroke-width": 2 });
    A.el(svg, "rect", { x: ox, y: oy, width: pw * IK, height: ph * IK, fill: "none", stroke: C.text, "stroke-dasharray": "4 3", "stroke-width": 1 });
    A.text(svg, IX, IY + 1.2 * IK + 20, "dashed: the pad · blue: the beam's path", { size: 12, fill: C.text2 });
    A.text(svg, IX, IY + 1.2 * IK + 38, "0.04 mm inside: the 0.08 mm kerf", { size: 12, fill: C.text2 });
    A.text(svg, IX, IY + 1.2 * IK + 56, "takes it back out to the pad's size", { size: 12, fill: C.text2 });

    var RX = IX, RY = IY + 1.2 * IK + 96;
    var runT = A.text(svg, RX, RY, "", { size: 18, weight: 700, font: "mono", fill: C.text });
    var subT = A.text(svg, RX, RY + 24, "", { size: 13, fill: C.text2 });

    var row = A.controls(host);
    var playing = !A.reduced, k = 0, phase = 0, t = 0;   // k: burst index; phase 0 cut, 1 rest
    var pb = A.button(row, playing ? "Pause" : "Play", function () { playing = !playing; pb.textContent = playing ? "Pause" : "Play"; });
    A.button(row, "Restart", function () { k = 0; phase = 0; t = 0; heat = [0, 0, 0, 0]; draw(); });
    var st = A.status(row);
    st.textContent = "100 %, 550 mm/s, 30 kHz · 30 passes per hole, in bursts of 5 · a 6 s rest after every burst · 4 zones. Sped up a lot.";

    function draw() {
      var r = Math.floor(k / ZONES), zc = k % ZONES, done = k >= ZONES * ROUNDS;
      padEls.forEach(function (p) {
        var h = heat[p.z];
        A.set(p.el, { fill: done ? C.ink : (p.z === zc && phase === 0 ? "#ff6b4a" : "rgb(" + Math.round(8 + 140 * h) + "," + Math.round(9 + 40 * h) + "," + Math.round(11) + ")") });
      });
      if (done) { runT.textContent = "Done"; subT.textContent = "Push out any slugs; re-cut the holes that did not go through."; A.set(runT, { fill: C.ok }); return; }
      A.set(runT, { fill: phase === 0 ? "#ff6b4a" : C.text2 });
      runT.textContent = phase === 0 ? "Zone " + (zc + 1) + " of 4 · round " + (r + 1) + " of 6" : "Resting, laser off";
      subT.textContent = phase === 0 ? "a burst of 5 passes on this zone's holes" : "6 s, then the next zone";
    }
    A.loop(host, function (tt, dt) {
      for (var i = 0; i < ZONES; i++) heat[i] = Math.max(0, heat[i] - dt * 0.35);
      if (!playing || k >= ZONES * ROUNDS) { draw(); return; }
      t += dt;
      if (phase === 0) { heat[k % ZONES] = Math.min(1, heat[k % ZONES] + dt * 1.6); if (t > 0.8) { t = 0; phase = 1; } }
      else if (t > 0.45) { t = 0; phase = 0; k++; }
      draw();
    }, 0);
    draw();
  });
})();
