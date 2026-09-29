/* "corner" — Find the copper corner with the probe. A to-scale top view of the front-left
   corner (1 mm grid): the bit is its 0.8 mm face, and it reads Touch while any of that
   face is over the copper. Jog it in −Y until the touch goes out, back one, creep in
   0.1 mm steps, back one; the same in X; then Set the corner from the tool reads the
   position. The demo replays the recorded walk and ends on X 60.52, Y 24.42.
   The copper's edges (X 60.87, Y 24.77) are the hidden truth the touch is computed from. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var XE = 60.87, YE = 24.77, R = 0.4, START = [66.02, 28.02], ROW = 25.42;
  var CX = 60.52, CY = 24.42;                     // the last points that touch, per axis

  function touches(x, y) { return Math.hypot(Math.max(XE - x, 0), Math.max(YE - y, 0)) < R; }
  function r2(v) { return Math.round(v * 100) / 100; }

  /** The recorded walk, as graphics.corner_moves: [x, y, step, touching]. */
  function walk() {
    var out = [], x = START[0], y = START[1];
    ["y", "x"].forEach(function (ax) {
      if (ax === "x") { y = ROW; out.push([x, y, 1, true]); }
      [1, 0.1].forEach(function (st) {
        for (;;) {
          if (ax === "y") y = r2(y - st); else x = r2(x - st);
          var t = touches(x, y);
          out.push([x, y, st, t]);
          if (!t) break;
        }
        if (ax === "y") y = r2(y + st); else x = r2(x + st);
        out.push([x, y, st, true]);
      });
    });
    out.push([CX, CY, 0.1, null]);
    return out;
  }

  A.define("corner", function (host) {
    // under 560 px the right-hand panel goes under the drawing, so the text stays readable
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 560 : 880, H = narrow ? 1040 : 520;
    var svg = A.stage(host, W, H, "Finding the copper's front-left corner with the probe, in 1 mm and 0.1 mm steps");
    var K = 62;
    function sx(x) { return 30 + (x - 59) * K; }
    function sy(y) { return 492 - (y - 22.8) * K; }

    // main view
    A.el(svg, "rect", { x: 10, y: 10, width: 540, height: 500, rx: 4, fill: C.panel, stroke: C.ruleHi });
    var clip = A.el(A.el(svg, "defs"), "clipPath", { id: "cornerClip" });
    A.el(clip, "rect", { x: 11, y: 11, width: 538, height: 498, rx: 4 });
    var main = A.el(svg, "g", { "clip-path": "url(#cornerClip)" });
    var ex = sx(XE), ey = sy(YE);
    A.el(main, "rect", { x: ex, y: 0, width: 600, height: ey, fill: C.copper });
    for (var gx = 61; gx <= 67; gx++) A.el(main, "line", { x1: sx(gx), x2: sx(gx), y1: 0, y2: ey, stroke: "#a3652f", "stroke-width": 1 });
    for (var gy = 25; gy <= 30; gy++) A.el(main, "line", { x1: ex, x2: 560, y1: sy(gy), y2: sy(gy), stroke: "#a3652f", "stroke-width": 1 });
    A.el(main, "line", { x1: ex, y1: ey, x2: ex, y2: 0, stroke: C.copperHi, "stroke-width": 3 });
    A.el(main, "line", { x1: ex, y1: ey, x2: 560, y2: ey, stroke: C.copperHi, "stroke-width": 3 });
    A.text(svg, 530, 40, "COPPER", { size: 16, weight: 700, fill: "#4a2810", anchor: "end", font: "label" });
    A.text(svg, 530, ey + 44, "front edge (−Y)", { size: 15, fill: C.text2, anchor: "end" });
    A.text(svg, ex - 10, 40, "left edge (−X)", { size: 15, fill: C.text2, anchor: "end" });
    A.text(svg, 26, 500, "TOP VIEW · to scale, 1 mm grid", { size: 15, weight: 600, fill: C.text3 });
    var foundY = A.el(main, "line", { stroke: C.caution, "stroke-width": 2, "stroke-dasharray": "8 6", opacity: 0 });
    var foundX = A.el(main, "line", { stroke: C.caution, "stroke-width": 2, "stroke-dasharray": "8 6", opacity: 0 });
    var trail = A.el(main, "g");
    var bitG = A.el(main, "g");
    var bitC = A.el(bitG, "circle", { r: R * K, "stroke-width": 3 });
    A.el(bitG, "line", { x1: -7, x2: 7, y1: 0, y2: 0, stroke: C.ink, "stroke-width": 2 });
    A.el(bitG, "line", { x1: 0, x2: 0, y1: -7, y2: 7, stroke: C.ink, "stroke-width": 2 });
    var ring = A.el(main, "g", { opacity: 0 });
    A.el(ring, "circle", { cx: sx(CX), cy: sy(CY), r: 38, fill: "none", stroke: C.caution, "stroke-width": 3 });
    A.text(ring, sx(CX) + 44, sy(CY) + 46, "the corner", { size: 18, weight: 700, fill: C.caution });

    // right: zoom inset and readouts
    var RP = A.el(svg, "g", { transform: narrow ? "translate(-556,520)" : null });
    var IX = 566, IY = 10, IW = 304, IH = 250, KZ = 170;
    A.el(RP, "rect", { x: IX, y: IY, width: IW, height: IH, rx: 4, fill: C.panel, stroke: C.caution });
    var iclip = A.el(svg.querySelector("defs"), "clipPath", { id: "cornerInset" });
    A.el(iclip, "rect", { x: IX + 1, y: IY + 1, width: IW - 2, height: IH - 2, rx: 4 });
    var inset = A.el(RP, "g", { "clip-path": "url(#cornerInset)" });
    A.el(RP, "rect", { x: IX + 10, y: IY + 10, width: 214, height: 28, rx: 3, fill: C.sunk, opacity: 0.85 });
    A.text(RP, IX + 20, IY + 30, "ZOOM · 0.1 mm = 17 px", { size: 15, weight: 600, fill: C.caution });

    A.el(RP, "rect", { x: IX, y: 272, width: IW, height: 238, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(RP, IX + 18, 304, "STEP", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var stepT = A.text(RP, IX + IW - 18, 304, "", { size: 17, weight: 700, fill: C.caution, anchor: "end" });
    var xT = A.text(RP, IX + 18, 348, "", { size: 22, weight: 600, font: "mono" });
    var yT = A.text(RP, IX + 18, 382, "", { size: 22, weight: 600, font: "mono" });
    var tBox = A.el(RP, "rect", { x: IX + 18, y: 404, width: IW - 36, height: 88, rx: 4, "stroke-width": 2 });
    var tL1 = A.text(RP, IX + IW / 2, 442, "", { size: 22, weight: 700, anchor: "middle", font: "label" });
    var tL2 = A.text(RP, IX + IW / 2, 472, "", { size: 15, anchor: "middle" });

    var bx = START[0], by = START[1], step = 1, hist = [], found = null;
    var tw = null;                                      // {x0,y0,x1,y1,t0}
    var clock = 0, demo = null;                         // clock: seconds, performance.now()                         // demo: {moves, i, next}

    function state() {
      if (found) return null;
      return touches(bx, by);
    }

    function draw(px, py) {
      var t = state();
      A.set(bitG, { transform: "translate(" + sx(px) + "," + sy(py) + ")" });
      A.set(bitC, {
        fill: "rgba(201,206,214,0.55)",
        stroke: t === null ? C.caution : t ? C.steel : C.danger
      });
      trail.textContent = "";
      hist.forEach(function (m) {
        A.el(trail, "circle", { cx: sx(m[0]), cy: sy(m[1]), r: 4.5, fill: m[2] ? C.ok : C.danger });
      });
      A.set(foundY, { x1: 0, x2: 560, y1: sy(CY), y2: sy(CY), opacity: found ? 1 : 0 });
      A.set(foundX, { x1: sx(CX), x2: sx(CX), y1: 0, y2: 520, opacity: found ? 1 : 0 });
      ring.setAttribute("opacity", found ? 1 : 0);
      stepT.textContent = step >= 1 ? "×100 = 1 mm" : "×10 = 0.1 mm";
      xT.textContent = "X " + bx.toFixed(2).padStart(6, " ");
      yT.textContent = "Y " + by.toFixed(2).padStart(6, " ");
      if (t === null) {
        A.set(tBox, { fill: C.cautionFill, stroke: C.caution });
        tL1.textContent = "CORNER"; tL1.setAttribute("fill", C.caution);
        tL2.textContent = "X " + CX.toFixed(2) + " · Y " + CY.toFixed(2); tL2.setAttribute("fill", C.text);
      } else if (t) {
        A.set(tBox, { fill: C.dangerFill, stroke: C.danger });
        tL1.textContent = "TOUCH"; tL1.setAttribute("fill", C.danger);
        tL2.textContent = "the bit is on the copper"; tL2.setAttribute("fill", C.text);
      } else {
        A.set(tBox, { fill: C.sunk, stroke: C.ruleStrong });
        tL1.textContent = "no touch"; tL1.setAttribute("fill", C.text2);
        tL2.textContent = "off the edge"; tL2.setAttribute("fill", C.text2);
      }
      // inset: centred on the bit
      inset.textContent = "";
      var ix = function (x) { return IX + IW / 2 + (x - px) * KZ; };
      var iy = function (y) { return IY + IH / 2 + 10 - (y - py) * KZ; };
      A.el(inset, "rect", { x: IX, y: IY, width: IW, height: IH, fill: C.panel });
      var cx0 = Math.max(ix(XE), IX - 5), cy0 = Math.min(iy(YE), IY + IH + 5);
      A.el(inset, "rect", { x: cx0, y: IY - 5, width: Math.max(IX + IW + 5 - cx0, 0), height: Math.max(cy0 - IY + 5, 0), fill: C.copper });
      A.el(inset, "line", { x1: ix(XE), x2: ix(XE), y1: IY - 5, y2: iy(YE), stroke: C.copperHi, "stroke-width": 3 });
      A.el(inset, "line", { x1: ix(XE), x2: IX + IW + 5, y1: iy(YE), y2: iy(YE), stroke: C.copperHi, "stroke-width": 3 });
      hist.forEach(function (m) {
        A.el(inset, "circle", { cx: ix(m[0]), cy: iy(m[1]), r: 5, fill: m[2] ? C.ok : C.danger });
      });
      A.el(inset, "circle", { cx: ix(px), cy: iy(py), r: R * KZ, fill: "rgba(201,206,214,0.55)", stroke: t === null ? C.caution : t ? C.steel : C.danger, "stroke-width": 3 });
      A.el(inset, "circle", { cx: ix(px), cy: iy(py), r: 4, fill: C.ink });
    }

    function now() { return performance.now() / 1000; }   // own clock: restart() resets the loop's
    function tick() {
      var tt = clock = now();
      if (demo && tt >= demo.next) {
        if (demo.i >= demo.moves.length) { demo = null; }
        else {
          var m = demo.moves[demo.i++];
          step = m[2];
          if (m[3] === null) { go(m[0], m[1], false); found = true; say("ok", "Corner: X 60.52, Y 24.42. Now Set the corner from the tool."); }
          else go(m[0], m[1], true);
          demo.next = tt + (m[2] >= 1 ? 0.55 : 0.36);
          seg.set(step >= 1 ? 1 : 0.1);
        }
      }
      var px = bx, py = by;
      if (tw) {
        var k = A.ease((tt - tw.t0) / 0.16);
        px = A.lerp(tw.x0, tw.x1, k); py = A.lerp(tw.y0, tw.y1, k);
        if (k >= 1) tw = null;
      }
      draw(px, py);
      if (!tw && !demo && lp) lp.stop();
    }

    function go(x, y, record) {
      x = r2(A.clamp(x, 59.02, 66.82)); y = r2(A.clamp(y, 23.02, 29.22));
      tw = { x0: bx, y0: by, x1: x, y1: y, t0: now() };
      bx = x; by = y;
      if (record) hist.push([bx, by, touches(bx, by)]);
      if (lp && !A.reduced) { if (!lp.running()) lp.restart(); } else { tw = null; draw(bx, by); }
    }

    function jog(dx, dy) {
      demo = null; found = false;
      go(bx + dx * step, by + dy * step, true);
      var t = touches(bx, by);
      say(t ? "" : "caution", t ? "Touch: still on the copper." : "No touch: off the edge. Step back one" + (step >= 1 ? ", then creep in with ×10." : ": that is the last point that touches."));
    }

    var row = A.controls(host);
    A.button(row, "−X", function () { jog(-1, 0); }, "key", "Jog towards the left edge");
    A.button(row, "+X", function () { jog(1, 0); }, "key", "Jog right");
    A.button(row, "−Y", function () { jog(0, -1); }, "key", "Jog towards the front edge");
    A.button(row, "+Y", function () { jog(0, 1); }, "key", "Jog back");
    var seg = A.segmented(row, [[1, "×100 · 1 mm"], [0.1, "×10 · 0.1 mm"]], 1, function (v) { step = v; if (lp) draw(bx, by); });
    A.button(row, "Play the demo", function () {
      reset(true);
      if (A.reduced) {
        walk().forEach(function (m) { if (m[3] !== null) hist.push([m[0], m[1], m[3]]); });
        bx = CX; by = CY; found = true; step = 0.1; seg.set(0.1); draw(bx, by);
        say("ok", "Corner: X 60.52, Y 24.42. Now Set the corner from the tool.");
        return;
      }
      demo = { moves: walk(), i: 0, next: now() + 0.4 };
      if (!lp.running()) lp.restart();
      say("", "Y first: 1 mm steps to the front edge, back one, then 0.1 mm steps.");
    }, "primary");
    A.button(row, "Set the corner from the tool", setCorner);
    A.button(row, "Reset", function () { reset(false); });
    var st = A.status(row);
    function say(kind, s) { st.className = "anim-status" + (kind ? " " + kind : ""); st.textContent = s; }

    function setCorner() {
      demo = null;
      var okX = Math.abs(bx - CX) < 0.05, okY = Math.abs(by - CY) < 0.05;
      if (okX && okY) {
        found = true; draw(bx, by);
        say("ok", "Corner set: X 60.52, Y 24.42 — the sheet on the stage moves to where the copper really is.");
        return;
      }
      var why = [];
      if (!okY) why.push(by > CY ? "Y is still on the copper: step −Y until the touch goes out, then back one (0.1 mm steps at the end)" : "Y is past the edge: step +Y back to the last point that touched");
      if (!okX) why.push(bx > CX ? "X is still on the copper: step −X until the touch goes out, then back one" : "X is past the edge: step +X back to the last point that touched");
      say("bad", "Not the corner yet. " + why.join(". ") + ".");
    }

    function reset(quiet) {
      demo = null; tw = null; found = false; hist = [];
      bx = START[0]; by = START[1]; step = 1; seg.set(1);
      draw(bx, by);
      if (!quiet) say("", "The bit starts on the copper, touching. Find the front edge (−Y) first, then the left edge (−X).");
    }

    var lp = null;
    lp = A.loop(host, tick, 0);
    reset(false);
  });
})();
