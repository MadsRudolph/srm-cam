/* No Arduino? Level the bed › Measure it › "No Arduino? Write one file per point…"
   writes <name>_probe_01.nc … one per grid point, and a checklist. Each file goes to
   its point with the spindle off and stops 2 mm above Z 0. Zero Z on the copper at
   point 1 (the datum), then at each point lower Z until the bit just touches, read Z
   off VPanel and write it down; the numbers go into the table (engine/leveling.py,
   write_probe_files). Heights are the same illustrative 3 x 3 map as the probing
   figure above. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var S = [0.000, -0.052, -0.011, -0.071, -0.128, -0.064, -0.018, -0.083, 0.002];  // surface vs point 1
  var OLD = 0.27;                  // the coarse zero from earlier sits 0.27 mm above point 1's copper

  A.define("bl-hand", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 750 : 420;
    var svg = A.stage(host, W, H, "Probing by hand: one file per point in VPanel, lower Z to the copper, write the Z down");
    // side view
    var SX = 24, SY = 50, SW = narrow ? 472 : 330, SH = narrow ? 300 : 330;
    A.text(svg, SX, 34, "AT THE POINT · spindle off", { size: 15, font: "label", weight: 600, fill: C.text3 });
    A.el(svg, "rect", { x: SX, y: SY, width: SW, height: SH, fill: C.panel, stroke: C.ruleHi, rx: 3 });
    var CUY = SY + SH - 70, K = narrow ? 70 : 95;  // the gap is drawn on a square-root scale: 0.01 mm still shows
    A.el(svg, "rect", { x: SX + 20, y: CUY, width: SW - 40, height: 12, fill: C.copper });
    A.el(svg, "rect", { x: SX + 20, y: CUY + 12, width: SW - 40, height: 40, fill: C.board });
    var bit = A.el(svg, "g", {});
    A.el(bit, "rect", { x: -26, y: -110, width: 52, height: 40, fill: C.steelDim });
    A.el(bit, "rect", { x: -8, y: -70, width: 16, height: 70, fill: C.steel });
    A.el(bit, "line", { x1: -8, y1: 0, x2: 8, y2: 0, stroke: C.caution, "stroke-width": 3 });
    var touchT = A.text(svg, SX + SW / 2, CUY + 36, "", { size: 16, anchor: "middle", weight: 700, fill: C.ok });
    // VPanel and the checklist
    var VX = narrow ? 24 : SX + SW + 20, VY = narrow ? SY + SH + 20 : SY, VW = narrow ? 472 : W - VX - 24;
    A.el(svg, "rect", { x: VX, y: VY, width: VW, height: narrow ? 360 : SH, fill: C.panel, stroke: C.ruleHi, rx: 3 });
    A.text(svg, VX + 14, VY + 26, "VPANEL · G54", { size: 15, font: "label", weight: 600, fill: C.text3 });
    var fileT = A.text(svg, VX + 14, VY + 56, "", { size: 16, font: "mono", fill: C.copperHi });
    A.text(svg, VX + 14, VY + 96, "Z", { size: 22, font: "mono", fill: C.text2 });
    var zT = A.text(svg, VX + VW - 14, VY + 96, "", { size: 30, font: "mono", anchor: "end", fill: C.text, weight: 600 });
    A.text(svg, VX + 14, VY + 132, "CHECKLIST · measured Z", { size: 15, font: "label", weight: 600, fill: C.text3 });
    var rows = [];
    for (var i = 0; i < 9; i++) {
      var cx = VX + 14 + (i % 3) * ((VW - 28) / 3), cy = VY + 162 + Math.floor(i / 3) * 34;
      A.text(svg, cx, cy, (i + 1) + ".", { size: 15, fill: C.text3, font: "mono" });
      rows.push(A.text(svg, cx + 30, cy, "______", { size: 16, fill: C.text4, font: "mono" }));
    }

    var cur = 0, origin = S[0] + OLD, zero = false, tip = 0, step = 0.1, got = [];
    var row = A.controls(host), st, down, up, setO, write, next, auto;
    A.segmented(row, [[0.1, "×10 · 0.1 mm"], [0.01, "×1 · 0.01 mm"]], 0.1, function (v) { step = v; });
    down = A.button(row, "↓ Z", function () { jog(-1); }, "key", "Lower Z one step");
    up = A.button(row, "↑ Z", function () { jog(1); }, "key", "Raise Z one step");
    setO = A.button(row, "Set Origin Point › Z", function () {
      if (!touching()) return say("bad", "Lower until the bit just touches first.");
      origin = S[0]; zero = true; draw();
      say("ok", "Point 1 is the datum: Z 0 is this copper. Now Output the next file.");
    });
    write = A.button(row, "Write it down", function () {
      if (!touching()) return say("bad", "Not on the copper yet: keep lowering.");
      if (!zero) return say("bad", "Point 1 first: Set Origin Point › Z there. Every height is measured from it.");
      got[cur] = disp(); draw();
      say("ok", "Point " + (cur + 1) + ": Z " + fmt(got[cur]) + ". Output the next file.");
    });
    next = A.button(row, "Output the next file", function () {
      if (!zero) return say("bad", "Zero Z at point 1 first.");
      if (got[cur] === undefined && cur > 0) return say("bad", "Write point " + (cur + 1) + " down first.");
      if (cur >= 8) return say("ok", "All nine measured. Type them into the table (or Load a CSV) and the map is the same as a probed one.");
      cur++; tip = origin + 2.0; draw();
      say("", "The file drove to point " + (cur + 1) + " and stopped 2 mm above Z 0. Lower until the bit just touches.");
    });
    auto = A.button(row, "Do the rest for me", function () {
      if (!zero) { origin = S[0]; zero = true; }
      for (var k = 1; k < 9; k++) got[k] = Math.round((S[k] - S[0]) * 100) / 100;
      got[0] = 0; cur = 8; tip = S[8]; draw();
      say("ok", "The checklist, filled. Heights are relative to point 1; typed into the table they give the same map a probe run does.");
    });
    st = A.status(row);
    function fmt(v) { return (v >= 0 ? " " : "") + v.toFixed(2); }
    function disp() { return Math.round((tip - origin) * 100) / 100; }
    function touching() { return tip <= S[cur] + 1e-6; }
    function say(k, s) { st.className = "anim-status" + (k ? " " + k : ""); st.textContent = s; }
    function jog(dir) {
      var nt = Math.round((tip + dir * step) * 1000) / 1000;
      if (dir < 0 && touching()) return say("bad", "The bit is already on the copper: lowering further only digs in.");
      if (dir < 0 && nt < S[cur]) nt = S[cur] - 0;           // the copper stops it
      tip = nt; draw();
      if (touching()) say("ok", "Just touching. " + (zero ? "Write it down." : "Set Origin Point › Z: this is the datum."));
      else say("", "");
    }
    function draw() {
      var gap = Math.max(0, tip - S[cur]);
      bit.setAttribute("transform", "translate(" + (SX + SW / 2) + "," + (CUY - Math.sqrt(Math.min(gap, 2.4)) * K) + ")");
      touchT.textContent = touching() ? "just touching" : "";
      fileT.textContent = "_probe_0" + (cur + 1) + ".nc  (" + (cur + 1) + " of 9)";
      zT.textContent = fmt(disp());
      rows.forEach(function (r, i) {
        r.textContent = got[i] === undefined ? "______" : fmt(got[i]);
        r.setAttribute("fill", got[i] === undefined ? C.text4 : C.text);
      });
    }
    tip = origin + 2.0;
    draw();
    say("", "_probe_01.nc is at point 1, 2 mm above the old zero. Lower Z (×10, then ×1) until the bit just touches.");
  });
})();
