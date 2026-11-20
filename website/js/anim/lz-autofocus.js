/* Autofocus on the F1 Ultra (engine/xtool.py autofocus, xtool_camera.py): lights off,
   the blue diode at a glow aimed at the focus cross, a photo, the dot found. The diode
   comes in at an angle, so when the surface is higher or lower the dot lands further
   along; its place in the photo, read against the factory's table of 21 heights from
   -50 to +50 mm, says how far to move the head. Moved, then measured again, until within
   0.1 mm, at most 4 tries. Schematic: the angle and the distances are drawn large. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var TOL = 0.1, TRIES = 4;

  A.define("lz-autofocus", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 580 : 400;
    var svg = A.stage(host, W, H, "Side view of the laser head: the blue diode's dot lands further along the surface the further the surface is from focus, and the camera reads how far");
    A.text(svg, 24, 30, "AUTOFOCUS · SIDE VIEW · SCHEMATIC", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var SX = narrow ? 260 : 300, FOCUS_Y = 300, KZ = 26;    // px per mm of height
    var ANG = 0.3;                                          // the diode's slope, drawn
    // the surface (moves with the sheet's height error)
    var surf = A.el(svg, "g");
    A.el(surf, "rect", { x: SX - 200, y: 0, width: 400, height: 14, fill: C.fr4 });
    A.el(surf, "rect", { x: SX - 200, y: -4, width: 400, height: 4, fill: C.copper });
    var fl = A.el(svg, "g");
    A.el(fl, "line", { x1: SX - 220, y1: 0, x2: SX + 220, y2: 0, stroke: C.live, "stroke-dasharray": "6 5" });
    A.text(fl, SX - 220, -8, "focus", { size: 12, fill: C.live });
    // head
    var head = A.el(svg, "g");
    A.el(head, "rect", { x: -60, y: -70, width: 120, height: 50, rx: 4, fill: C.raised, stroke: C.ruleStrong, "stroke-width": 2 });
    A.el(head, "rect", { x: -12, y: -20, width: 24, height: 12, fill: C.panelHi, stroke: C.ruleStrong, "stroke-width": 2 });
    A.text(head, 0, -40, "HEAD", { size: 13, weight: 600, anchor: "middle", fill: C.text2, font: "label" });
    A.el(head, "circle", { cx: -49, cy: -14, r: 6, fill: C.live });           // the diode
    A.el(head, "rect", { x: 38, y: -22, width: 18, height: 12, rx: 2, fill: C.panelHi, stroke: C.text3 });   // the camera
    A.text(head, -49, 6, "diode", { size: 11, anchor: "middle", fill: C.live });
    A.text(head, 47, 6, "camera", { size: 11, anchor: "middle", fill: C.text3 });
    var beam = A.el(svg, "line", { stroke: C.live, "stroke-width": 2, opacity: 0.8 });
    var view = A.el(svg, "line", { stroke: C.text3, "stroke-width": 1, "stroke-dasharray": "3 3" });
    var dot = A.el(svg, "circle", { r: 6, fill: C.live });
    // the camera's photo: a strip with the factory's heights
    var PX = narrow ? 40 : SX + 260, PY = narrow ? 420 : 80, PW = narrow ? 440 : 240, PH = 40;
    A.text(svg, PX, PY - 12, "THE PHOTO: WHERE THE DOT IS", { size: 12, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: PX, y: PY, width: PW, height: PH, fill: C.ink, stroke: C.ruleStrong });
    for (var i = 0; i <= 20; i++) {
      var tx = PX + 8 + i * (PW - 16) / 20;
      A.el(svg, "line", { x1: tx, y1: PY + PH, x2: tx, y2: PY + PH - (i % 5 === 0 ? 12 : 6), stroke: C.text3 });
      if (i % 5 === 0) A.text(svg, tx, PY + PH + 16, String(-50 + i * 5), { size: 11, anchor: "middle", fill: C.text3, font: "mono" });
    }
    A.text(svg, PX + PW / 2, PY + PH + 32, "the factory's 21 heights, mm", { size: 11, anchor: "middle", fill: C.text3 });
    var pdot = A.el(svg, "circle", { cy: PY + PH / 2 - 4, r: 5, fill: C.live });
    var readT = A.text(svg, PX, PY + PH + 60, "", { size: 15, weight: 600, fill: C.text, font: "mono" });
    var tryT = A.text(svg, PX, PY + PH + 84, "", { size: 14, fill: C.text2 });

    var row = A.controls(host);
    var off = 1.6, headZ = 0, tries = 0, running = false, phase = 0, t0 = 0, ready = false;
    var runBtn = A.button(row, "Autofocus", function () { start(); }, "primary");
    A.slider(row, "Sheet off focus", -3, 3, 0.1, off, function (x) { off = x; headZ = 0; tries = 0; running = false; if (ready) draw(); }, function (x) { return (x > 0 ? "+" : "") + x.toFixed(1) + " mm"; });
    var st = A.status(row);

    function err() { return off - headZ; }   // how far the surface is from focus now
    function draw() {
      var e = err();
      var surfY = FOCUS_Y - off * KZ, focusY = FOCUS_Y - headZ * KZ, hy = focusY - 150;
      A.set(surf, { transform: "translate(0 " + surfY + ")" });
      A.set(fl, { transform: "translate(0 " + focusY + ")" });
      A.set(head, { transform: "translate(" + SX + " " + hy + ")" });
      var by = hy - 14, bx = SX - (focusY - by) * ANG;
      var dotX = SX - e * KZ * ANG;
      A.set(beam, { x1: bx, y1: by, x2: dotX, y2: surfY - 4 });
      A.set(view, { x1: SX + 47, y1: hy - 16, x2: dotX, y2: surfY - 4 });
      A.set(dot, { cx: dotX, cy: surfY - 4 });
      // in the photo: -50..+50 mm across, drawn so the error shows
      var px = PX + PW / 2 + A.clamp(-e * 18, -PW / 2 + 10, PW / 2 - 10);
      A.set(pdot, { cx: px });
      readT.textContent = "off focus: " + (e >= 0 ? "+" : "") + e.toFixed(2) + " mm";
      A.set(readT, { fill: Math.abs(e) <= TOL ? C.ok : C.text });
      tryT.textContent = tries ? "try " + tries + " of " + TRIES : "the photo is drawn magnified";
    }
    function start() {
      if (running) return;
      tries = 0; running = true; phase = 0; t0 = 0;
      say("", "Lights off, the blue dot at a glow, a photo.");
    }
    function say(k, s) { st.className = "anim-status" + (k ? " " + k : ""); st.textContent = s; }
    A.loop(host, function (t, dt) {
      if (!running) return;
      t0 += dt;
      if (t0 < 0.9) return;
      t0 = 0;
      var e = err();
      if (Math.abs(e) <= TOL) {
        running = false; draw();
        say("ok", "“In focus. Photo refreshed at the new head height; ready to align.” " + tries + (tries === 1 ? " try." : " tries."));
        return;
      }
      if (tries >= TRIES) { running = false; draw(); say("caution", "Four tries and still not within 0.1 mm."); return; }
      tries++;
      // the reading is good but not perfect: each move takes out most of the error
      headZ += e * (tries === 1 ? 0.86 : 0.97);
      draw();
      say("", "Try " + tries + ": the dot read " + (e >= 0 ? "+" : "") + e.toFixed(2) + " mm; the head moved. Measure again.");
    }, 0);
    ready = true;
    draw();
    say("", "Move the slider to put the sheet off focus, then press Autofocus.");
  });
})();
