/* Rework (on the rail, under When you need it): box the spots the first pass did not
   finish, each box with its own depth, and export ONE program that repeats the pass
   clipped to the boxes (gui2/rework.py). Full tier adds two helpers:
   - Propose boxes from the photo: walks every channel and looks for stretches with no
     cut in them at all. A cut that is merely too shallow still looks like a channel in
     any photo, so it can't see those;
   - Probe the boxes over the link: taps the middle of each box (after the map's first
     point, for a datum); where the copper sits lower than the map believed, that box is
     deepened by exactly the difference (deepen_from_probe).
   Box depths are measured from the surface the map believes, as in the app. The board
   and its three faults are schematic; spot 3 is the shallow one. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BW = 80, BH = 50, CU = 0.035;
  var TRACES = [[[6, 40], [34, 40], [44, 30], [74, 30]], [[6, 22], [30, 22], [30, 10], [74, 10]], [[50, 44], [74, 44]]];
  // faults in a channel: x, y (mm), how much lower the copper sits than the map believed, photo-visible?
  var FAULTS = [
    { x: 20, y: 38.2, low: 0.18, seen: true, what: "never cut" },
    { x: 60, y: 11.8, low: 0.20, seen: true, what: "never cut" },
    { x: 17, y: 23.8, low: 0.13, seen: false, what: "too shallow" }
  ];
  var SERIES = [C.live, C.caution, C.ok, "#c58cff", C.copperHi, C.danger];

  A.define("pr-rework", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var S = narrow ? 5.9 : 7.0, BX = 24, BY = 50;
    var W = narrow ? 520 : 880, H = narrow ? BY + BH * S + 190 : BY + BH * S + 24;
    var svg = A.stage(host, W, H, "A cut board with three faults, the rework boxes over them, and the re-cut");
    A.text(svg, BX, 34, "THE BOARD, CUT ONCE · drag a box over a fault", { size: 15, font: "label", weight: 600, fill: C.text3 });
    function m(p) { return [BX + p[0] * S, BY + (BH - p[1]) * S]; }
    A.el(svg, "rect", { x: BX, y: BY, width: BW * S, height: BH * S, fill: C.copper, stroke: C.copperHi, rx: 3 });
    var chan = A.el(svg, "g", {}), trk = A.el(svg, "g", {});
    function pl(t) { return t.map(function (p) { return m(p).join(","); }).join(" "); }
    TRACES.forEach(function (t) {
      A.el(chan, "polyline", { points: pl(t), fill: "none", stroke: "#3a2a1c", "stroke-width": 4.4 * S, "stroke-linejoin": "round", "stroke-linecap": "round" });
      A.el(trk, "polyline", { points: pl(t), fill: "none", stroke: C.copperHi, "stroke-width": 2.8 * S, "stroke-linejoin": "round", "stroke-linecap": "round" });
    });
    var faultG = [];
    FAULTS.forEach(function (f, i) {
      var q = m([f.x, f.y]), g = A.el(svg, "g", {});
      if (f.seen) A.el(g, "rect", { x: q[0] - 1.4 * S, y: q[1] - 0.75 * S, width: 2.8 * S, height: 1.5 * S, fill: C.copperHi, stroke: "#f3c48f", "stroke-width": 1.5 });
      else A.el(g, "rect", { x: q[0] - 3.5 * S, y: q[1] - 0.5 * S, width: 7 * S, height: 1.0 * S, fill: C.copperHi, opacity: 0.35 });
      A.text(g, q[0], q[1] + (f.y > 30 ? 2.6 : -1.4) * S, String(i + 1), { size: 16, weight: 700, anchor: "middle", fill: C.ink });
      faultG.push(g);
    });
    var boxG = A.el(svg, "g", {}), recut = A.el(svg, "g", {});
    var drag = A.el(svg, "rect", { fill: "none", stroke: C.text, "stroke-width": 2, "stroke-dasharray": "6 4", opacity: 0 });

    // the table of boxes
    var TX = narrow ? BX : BX + BW * S + 20, TY = narrow ? BY + BH * S + 20 : BY, TW = narrow ? BW * S : W - TX - 20;
    A.el(svg, "rect", { x: TX, y: TY, width: TW, height: narrow ? 150 : BH * S, fill: C.panel, stroke: C.ruleHi, rx: 3 });
    A.text(svg, TX + 12, TY + 24, "BOXES · depth", { size: 15, font: "label", weight: 600, fill: C.text3 });
    var tbl = A.el(svg, "g", {});

    var boxes = [], depth = 0.25, st, running = null;
    function toMM(ev) {
      var p = svg.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY;
      var q = p.matrixTransform(svg.getScreenCTM().inverse());
      return [A.clamp((q.x - BX) / S, 0, BW), A.clamp(BH - (q.y - BY) / S, 0, BH)];
    }
    var start = null;
    svg.addEventListener("pointerdown", function (ev) {
      var p = toMM(ev);
      if (p[0] <= 0 || p[0] >= BW || p[1] <= 0 || p[1] >= BH) return;
      start = p; svg.setPointerCapture && svg.setPointerCapture(ev.pointerId); ev.preventDefault();
    });
    svg.addEventListener("pointermove", function (ev) {
      if (!start) return;
      var p = toMM(ev), a = m([Math.min(start[0], p[0]), Math.max(start[1], p[1])]);
      A.set(drag, { x: a[0], y: a[1], width: Math.abs(p[0] - start[0]) * S, height: Math.abs(p[1] - start[1]) * S, opacity: 1 });
    });
    svg.addEventListener("pointerup", function (ev) {
      if (!start) return;
      var p = toMM(ev), b = [Math.min(start[0], p[0]), Math.min(start[1], p[1]), Math.max(start[0], p[0]), Math.max(start[1], p[1])];
      start = null; drag.setAttribute("opacity", 0);
      if (b[2] - b[0] < 1.5 || b[3] - b[1] < 1.5) return;
      add(b, depth);
    });

    function inBox(f, b) { return f.x >= b[0] && f.x <= b[2] && f.y >= b[1] && f.y <= b[3]; }
    function add(b, d) {
      if (boxes.length >= 6) return say("bad", "That's plenty of boxes for one board: export these first.");
      boxes.push({ b: b, d: d, probed: null }); clearRecut(); draw();
      var hit = FAULTS.map(function (f, i) { return inBox(f, b) ? i + 1 : 0; }).filter(Boolean);
      say("", "Box " + boxes.length + " at " + d.toFixed(2) + " mm" + (hit.length ? ", over spot " + hit.join(" and ") + "." : ": no fault inside it, it only costs time."));
    }
    function draw() {
      while (boxG.firstChild) boxG.removeChild(boxG.firstChild);
      while (tbl.firstChild) tbl.removeChild(tbl.firstChild);
      boxes.forEach(function (x, i) {
        var a = m([x.b[0], x.b[3]]), col = SERIES[i % SERIES.length];
        A.el(boxG, "rect", { x: a[0], y: a[1], width: (x.b[2] - x.b[0]) * S, height: (x.b[3] - x.b[1]) * S, fill: col, "fill-opacity": 0.12, stroke: col, "stroke-width": 2.5 });
        A.text(boxG, a[0] + 4, a[1] + 17, String(i + 1), { size: 15, weight: 700, fill: col });
        var y = TY + 54 + i * (narrow ? 16 : 30);
        if (narrow && i > 5) return;
        A.el(tbl, "rect", { x: TX + 12, y: y - 12, width: 12, height: 12, fill: col });
        A.text(tbl, TX + 32, y, (i + 1) + ".  " + x.d.toFixed(2) + " mm" + (x.probed ? "  +" + x.probed.toFixed(2) + " probed" : ""), { size: 15, font: "mono", fill: C.text });
      });
      if (!boxes.length) A.text(tbl, TX + 12, TY + 54, "none yet", { size: 15, fill: C.text3 });
    }
    function clearRecut() { while (recut.firstChild) recut.removeChild(recut.firstChild); faultG.forEach(function (g) { g.setAttribute("opacity", 1); }); }

    var row = A.controls(host);
    A.slider(row, "Depth for the next box", 0.15, 0.40, 0.05, 0.25, function (v) { depth = v; }, function (v) { return v.toFixed(2) + " mm"; });
    A.button(row, "Box the next spot", function () {
      var i = FAULTS.findIndex(function (f) { return !boxes.some(function (x) { return inBox(f, x.b); }); });
      if (i < 0) return say("", "Every spot has a box.");
      var f = FAULTS[i]; add([f.x - 4, f.y - 3, f.x + 4, f.y + 3], depth);
    });
    A.button(row, "Propose boxes from the photo", function () {
      var n = 0;
      FAULTS.forEach(function (f) { if (f.seen && !boxes.some(function (x) { return inBox(f, x.b); })) { boxes.push({ b: [f.x - 4, f.y - 3, f.x + 4, f.y + 3], d: depth, probed: null }); n++; } });
      clearRecut(); draw();
      say("caution", (n ? n + " boxes proposed, over the stretches with no cut at all (spots 1 and 2). " : "Nothing new to propose. ") +
        "Spot 3 was cut, only not deep enough: in a photo it looks like any other channel, so box it yourself (a multimeter beep between two nets says where).");
    });
    A.button(row, "Probe the boxes over the link", function () {
      if (!boxes.length) return say("bad", "Draw a box first: the probe taps the middle of each one.");
      var deeper = 0;
      boxes.forEach(function (x) {
        var f = FAULTS.filter(function (g) { return inBox(g, x.b); })[0];
        var low = f ? f.low : 0;
        if (low > 0.005 && !x.probed) { x.probed = low; x.d = Math.round((x.d + low) * 100) / 100; deeper++; }
      });
      clearRecut(); draw();
      say("ok", "The bit tapped the map's first point, then the middle of each box. " + (deeper ? deeper + " box" + (deeper > 1 ? "es sit" : " sits") + " lower than the map believed and " + (deeper > 1 ? "were" : "was") + " deepened by exactly the difference." : "Every box agrees with the map."));
    });
    A.button(row, "Export the rework program…", function () {
      if (!boxes.length) return say("bad", "Draw a box first: there is nothing to re-cut.");
      clearRecut();
      boxes.forEach(function (x, i) {
        var id = "rwclip" + Math.random().toString(36).slice(2), cp = A.el(recut, "clipPath", { id: id });
        var a = m([x.b[0], x.b[3]]);
        A.el(cp, "rect", { x: a[0], y: a[1], width: (x.b[2] - x.b[0]) * S, height: (x.b[3] - x.b[1]) * S });
        var g = A.el(recut, "g", { "clip-path": "url(#" + id + ")" });
        TRACES.forEach(function (t) {
          A.el(g, "polyline", { points: pl(t), fill: "none", stroke: C.ok, "stroke-width": 4.4 * S, "stroke-linejoin": "round", opacity: 0.35 });
          A.el(g, "polyline", { points: pl(t), fill: "none", stroke: C.copperHi, "stroke-width": 2.8 * S, "stroke-linejoin": "round" });
        });
      });
      var fixed = [], left = [];
      FAULTS.forEach(function (f, i) {
        var bx = boxes.filter(function (x) { return inBox(f, x.b); });
        var ok = bx.some(function (x) { return x.d - f.low >= CU; });
        if (ok) { fixed.push(i + 1); faultG[i].setAttribute("opacity", 0); }
        else left.push(i + 1 + (bx.length ? " (box too shallow)" : " (no box)"));
      });
      say(left.length ? "bad" : "ok", "feedback_circuit_2_traces_rework.nc: the traces pass, clipped to " + boxes.length + " box" + (boxes.length > 1 ? "es" : "") +
        ". Re-zero Z first; don't touch the XY origin. " + (fixed.length ? "Cleared: spot " + fixed.join(", ") + ". " : "") + (left.length ? "Still copper: " + left.join(", ") + "." : "Every fault is gone, and the rest of the board was left alone."));
    }, "primary");
    A.button(row, "Remove all", function () { boxes = []; clearRecut(); draw(); say("", "No boxes."); });
    st = A.status(row);
    function say(k, s) { st.className = "anim-status" + (k ? " " + k : ""); st.textContent = s; }
    draw();
    say("", "Three spots came out wrong. Drag a box over each (or Box the next spot), then Export.");
  });
})();
