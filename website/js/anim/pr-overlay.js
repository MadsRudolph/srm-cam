/* View › Lay a photo of the board on the bed… Click the anchor holes in the photo in
   the order the design map beside it asks for (undo the last click if you miss); the
   app fits a homography from the four and warps the photo into machine millimetres
   (engine/photofit.py). Then View's two sliders, Photo and Fade the design, set how
   strongly the photo shows and how far the copper and toolpaths are faded over it
   (gui2/photo.py, PhotoControls). This drawing's photo is only turned and scaled, so
   the fit here is exact; a real phone photo also leans, which is why the app needs four.
   The board, its defects and the photo are schematic. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BW = 60, BH = 42;                                             // board, mm
  var TR = [[6, 8, 22, 8, 22, 20, 36, 20], [6, 34, 30, 34, 30, 26, 50, 26], [42, 8, 54, 8, 54, 16]];
  var PADS = [[6, 8], [22, 20], [36, 20], [6, 34], [50, 26], [42, 8], [54, 16]];
  var ANCH = [[3, 39], [57, 39], [57, 3], [3, 3]];                  // numbered 1-4, clockwise from top left
  var HOLES = ANCH.concat([[30, 3], [30, 39]]);
  var TORN = [36, 20], BRIDGE = [[26, 23], [26, 31]];               // what the photo shows and the design doesn't

  A.define("pr-overlay", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 716 : 370;
    var svg = A.stage(host, W, H, "Anchoring a photo of the board on the design, then fading one over the other");
    var P = narrow ? { x: 24, y: 50, w: 472, h: 300 } : { x: 24, y: 50, w: 400, h: 300 };
    var D = narrow ? { x: 24, y: 400, w: 472, h: 300 } : { x: 456, y: 50, w: 400, h: 300 };
    A.text(svg, P.x, 34, "THE PHOTO · click the holes", { size: 15, font: "label", weight: 600, fill: C.text3 });
    var dTitle = A.text(svg, D.x, D.y - 16, "THE DESIGN MAP · which hole next", { size: 15, font: "label", weight: 600, fill: C.text3 });
    A.el(svg, "rect", { x: P.x, y: P.y, width: P.w, height: P.h, fill: "#2c2a26", rx: 3 });
    A.el(svg, "rect", { x: D.x, y: D.y, width: D.w, height: D.h, fill: C.panel, stroke: C.ruleHi, rx: 3 });

    // photo transform: design mm -> photo px (turned 4°, scaled, image y down)
    var ang = 4 * Math.PI / 180, sc = narrow ? 6.2 : 5.2, ox = P.x + P.w / 2, oy = P.y + P.h / 2 + 4;
    function toPhoto(p) {
      var x = p[0] - BW / 2, y = -(p[1] - BH / 2);
      return [ox + sc * (x * Math.cos(ang) - y * Math.sin(ang)), oy + sc * (x * Math.sin(ang) + y * Math.cos(ang))];
    }
    var dsc = narrow ? 7.2 : 6.0, dox = D.x + (D.w - BW * dsc) / 2, doy = D.y + (D.h - BH * dsc) / 2;
    function toMap(p) { return [dox + p[0] * dsc, doy + (BH - p[1]) * dsc]; }

    function board(g, f, s, real) {
      var c = [[0, 0], [BW, 0], [BW, BH], [0, BH]].map(f);
      A.el(g, "polygon", { points: c.map(function (q) { return q.join(","); }).join(" "), fill: real ? "#9c6a3c" : "none",
        stroke: real ? "#c08a58" : C.copperHi, "stroke-width": 2 });
      TR.forEach(function (t) {
        var pts = [];
        for (var i = 0; i < t.length; i += 2) pts.push(f([t[i], t[i + 1]]));
        A.el(g, "polyline", { points: pts.map(function (q) { return q.join(","); }).join(" "), fill: "none",
          stroke: real ? "#e6b07a" : C.copperHi, "stroke-width": 2.4 * s, "stroke-linejoin": "round", opacity: real ? 1 : 0.9 });
      });
      PADS.forEach(function (p) {
        var q = f(p);
        A.el(g, "circle", { cx: q[0], cy: q[1], r: 1.6 * s, fill: real ? "#e6b07a" : "none", stroke: real ? "none" : C.copperHi, "stroke-width": 2 });
      });
      HOLES.forEach(function (p) { var q = f(p); A.el(g, "circle", { cx: q[0], cy: q[1], r: 0.9 * s, fill: real ? "#1b1a18" : C.panel, stroke: real ? "none" : C.text2 }); });
      if (real) {                                                  // the damage the design can't show
        var t = f(TORN);
        A.el(g, "path", { d: "M" + (t[0] - 1.8 * s) + " " + t[1] + " l" + (1.2 * s) + " " + (-1.6 * s) + " l" + (1.8 * s) + " " + (0.4 * s) + " l" + (0.6 * s) + " " + (1.6 * s) + "z", fill: "#2c2a26" });
        var b0 = f(BRIDGE[0]), b1 = f(BRIDGE[1]);
        A.el(g, "line", { x1: b0[0], y1: b0[1], x2: b1[0], y2: b1[1], stroke: "#e6b07a", "stroke-width": 1.4 * s });
      }
    }
    var photo = A.el(svg, "g", {});
    board(photo, toPhoto, sc, true);
    var mapG = A.el(svg, "g", {});
    board(mapG, toMap, dsc, false);
    var num = [];
    ANCH.forEach(function (p, i) {
      var q = toMap(p);
      var c = A.el(mapG, "circle", { cx: q[0], cy: q[1], r: 13, fill: "none", stroke: C.text3, "stroke-width": 2 });
      A.text(mapG, q[0] + (i === 1 || i === 2 ? -20 : 20), q[1] + 6, String(i + 1), { size: 18, weight: 700, anchor: "middle", fill: C.text2 });
      num.push(c);
    });
    // click targets on the photo's holes
    var picks = [], pickG = A.el(svg, "g", {});
    HOLES.forEach(function (p, i) {
      var q = toPhoto(p);
      var hit = A.el(svg, "circle", { cx: q[0], cy: q[1], r: 16, fill: "transparent", style: "cursor:crosshair" });
      hit.addEventListener("click", function () { pick(i); });
    });

    // the bed view, after the fit
    var bed = A.el(svg, "g", { opacity: 0 });
    A.el(bed, "rect", { x: D.x, y: D.y, width: D.w, height: D.h, fill: C.panel, stroke: C.ruleHi, rx: 3 });
    var bedPhoto = A.el(bed, "g", {});
    board(bedPhoto, toMap, dsc, true);
    var bedDesign = A.el(bed, "g", {});
    board(bedDesign, toMap, dsc, false);
    var ring = A.el(bed, "g", { opacity: 0 });
    var tq = toMap(TORN), bq = toMap([(BRIDGE[0][0] + BRIDGE[1][0]) / 2, (BRIDGE[0][1] + BRIDGE[1][1]) / 2]);
    A.el(ring, "circle", { cx: tq[0], cy: tq[1], r: 26, fill: "none", stroke: C.danger, "stroke-width": 3 });
    A.el(ring, "circle", { cx: bq[0], cy: bq[1], r: 30, fill: "none", stroke: C.danger, "stroke-width": 3 });

    var row = A.controls(host), st, undo, opS, fadeS, op = 1, fade = 0.55;
    A.button(row, "Pick the next hole for me", function () { if (picks.length < 4) pick(picks.length); });
    undo = A.button(row, "Undo the last", function () {
      if (!picks.length) return;
      picks.pop(); drawPicks(); fitted(false);
      say("", "Undone. Click hole " + (picks.length + 1) + ".");
    });
    A.button(row, "Start again", function () { picks = []; drawPicks(); fitted(false); say("", "Click hole 1 in the photo, the one the map marks."); });
    opS = A.slider(row, "Photo", 0, 1, 0.05, 1, function (v) { op = v; paintBed(); }, function (v) { return Math.round(v * 100) + " %"; });
    fadeS = A.slider(row, "Fade the design", 0, 1, 0.05, 0.55, function (v) { fade = v; paintBed(); }, function (v) { return Math.round(v * 100) + " %"; });
    st = A.status(row);
    opS.disabled = fadeS.disabled = true;

    function say(k, s) { st.className = "anim-status" + (k ? " " + k : ""); st.textContent = s; }
    function drawPicks() {
      while (pickG.firstChild) pickG.removeChild(pickG.firstChild);
      picks.forEach(function (i, k) {
        var q = toPhoto(HOLES[i]);
        A.el(pickG, "circle", { cx: q[0], cy: q[1], r: 11, fill: "none", stroke: C.ok, "stroke-width": 3 });
        A.text(pickG, q[0], q[1] - 16, String(k + 1), { size: 17, weight: 700, anchor: "middle", fill: C.ok });
      });
      num.forEach(function (c, k) {
        c.setAttribute("stroke", k < picks.length ? C.ok : k === picks.length ? C.caution : C.text3);
        c.setAttribute("stroke-width", k === picks.length ? 4 : 2);
      });
    }
    function pick(i) {
      if (picks.length >= 4) return;
      var want = picks.length;
      if (i !== want) {
        return say("bad", i < 4 ? "That is hole " + (i + 1) + "; the map asks for hole " + (want + 1) + " next." : "That hole is not an anchor. The map marks hole " + (want + 1) + ".");
      }
      picks.push(i); drawPicks();
      if (picks.length < 4) say("", "Hole " + picks.length + " placed. Now hole " + (picks.length + 1) + ".");
      else fitted(true);
    }
    function fitted(on) {
      bed.setAttribute("opacity", on ? 1 : 0);
      mapG.setAttribute("opacity", on ? 0 : 1);
      dTitle.textContent = on ? "ON THE BED · machine mm" : "THE DESIGN MAP · which hole next";
      opS.disabled = fadeS.disabled = !on;
      ring.setAttribute("opacity", on ? 1 : 0);
      if (on) { paintBed(); say("ok", "Fitted on four holes: the photo lands within 0.1 mm of the design. A torn pad and a copper bridge show up where the design has none; a rework box drawn here lands on them."); }
    }
    function paintBed() {
      bedPhoto.setAttribute("opacity", op);
      bedDesign.setAttribute("opacity", 1 - fade);
    }
    drawPicks();
    say("", "Click hole 1 in the photo: the one ringed on the design map.");
  });
})();
