/* The flip, and why the bottom is cut mirrored (gerber2rml/doublesided.py).
   The bottom face is milled from above, so it is cut as B.Cu seen from below:
   mirrored about the flip axis. Turn the board over about that same axis and the
   bottom lands the way KiCad drew it, and the top is cut as plain F.Cu. Turn it
   over the other way and every point lands rotated 180° about the centre: the
   holes drilled from the bottom miss the top's pads. On a fiducial job (the lab's)
   nothing stops a wrong turn, and the corner reference holes fit equally well
   either way (gui2/inspector.py, "Flipped"): the direction is set there and checked
   by hand. The letters stand in for the copper: any asymmetric pattern does. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var HOLES = [[-0.7, -0.62], [0.72, -0.6], [0.05, 0.68]];   // design, board units (u right, v up)
  var FU = -0.42, FV = -0.02, RU = 0.4, RV = 0.02, GS = 1.25;   // where the letters sit, and their size

  A.define("ds-flip", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 860 : 500;
    var svg = A.stage(host, W, H, "Flipping a double-sided board: the bottom is cut mirrored, the top as drawn");
    // panels
    var KX = 16, KY = 16, KW = narrow ? 488 : 262, KH = narrow ? 250 : 468;
    var BX = narrow ? 16 : 294, BY = narrow ? 282 : 16, BW = narrow ? 488 : 570, BH = narrow ? 562 : 468;
    A.el(svg, "rect", { x: KX, y: KY, width: KW, height: KH, rx: 3, fill: C.panel, stroke: C.ruleHi });
    A.el(svg, "rect", { x: BX, y: BY, width: BW, height: BH, rx: 3, fill: C.panel, stroke: C.ruleHi });
    A.text(svg, KX + 14, KY + 26, "IN KICAD, FROM THE TOP", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var bedTitle = A.text(svg, BX + 14, BY + 26, "", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });

    // the KiCad reference
    var kcx = KX + KW / 2, kcy = KY + (narrow ? 132 : 190), khw = narrow ? 120 : 100, khh = narrow ? 82 : 70;
    var kg = A.el(svg, "g", {});
    A.el(kg, "rect", { x: kcx - khw, y: kcy - khh, width: 2 * khw, height: 2 * khh, rx: 4, fill: C.fr4, stroke: C.fr4Hi });
    glyph(kg, "R", kcx + RU * khw, kcy - RV * khh, 1, 1, khh * GS, C.live, 0.85);
    glyph(kg, "F", kcx + FU * khw, kcy - FV * khh, 1, 1, khh * GS, C.copperHi, 1);
    HOLES.forEach(function (h) {
      var x = kcx + h[0] * khw, y = kcy - h[1] * khh;
      A.el(kg, "circle", { cx: x, cy: y, r: 10, fill: "none", stroke: C.copperHi, "stroke-width": 4 });
      A.el(kg, "circle", { cx: x, cy: y, r: 4, fill: C.ink });
    });
    var ly = kcy + khh + 32;
    A.el(svg, "rect", { x: KX + 18, y: ly - 12, width: 14, height: 14, fill: C.copperHi });
    A.text(svg, KX + 40, ly, "F.Cu, the top", { size: 15, fill: C.text2 });
    A.el(svg, "rect", { x: KX + 18, y: ly + 12, width: 14, height: 14, fill: C.live });
    A.text(svg, KX + 40, ly + 24, "B.Cu, the bottom", { size: 15, fill: C.text2 });
    if (!narrow) {
      A.text(svg, KX + 18, ly + 62, "The letters stand in", { size: 15, fill: C.text3 });
      A.text(svg, KX + 18, ly + 82, "for the copper: any", { size: 15, fill: C.text3 });
      A.text(svg, KX + 18, ly + 102, "lopsided pattern shows", { size: 15, fill: C.text3 });
      A.text(svg, KX + 18, ly + 122, "a mirror the same way.", { size: 15, fill: C.text3 });
    }

    // the bed
    var cx = BX + BW / 2, cy = BY + BH / 2 + (narrow ? 0 : 6);
    var hw = narrow ? 150 : 170, hh = narrow ? 110 : 120;
    var g = A.el(svg, "g", {});
    var cap = A.text(svg, BX + BW / 2, BY + BH - 18, "", { size: 16, anchor: "middle", fill: C.text2, weight: 600 });

    var row = A.controls(host);
    var st = A.status(row);
    var axis = "vertical", face = "bottom", phi = 0, wrong = false, anim = 0;

    function glyph(parent, s, x, y, sx, sy, size, fill, op) {
      var t = A.el(parent, "text", {
        x: 0, y: 0, fill: fill, opacity: op, "font-size": size, "font-weight": 800, "font-family": A.FONT.sans,
        "text-anchor": "middle", "dominant-baseline": "central",
        transform: "translate(" + x + "," + y + ") scale(" + sx + "," + sy + ")"
      }, s);
      return t;
    }
    // the four reference holes, just outside the board's corners (in the waste)
    function refs() {
      var ox = 1 + 22 / hw, oy = 1 + 22 / hh;
      return [[-ox, -oy], [ox, -oy], [ox, oy], [-ox, oy]];
    }
    function mir(u, v) { return axis === "vertical" ? [-u, v] : [u, -v]; }

    function draw() {
      while (g.firstChild) g.removeChild(g.firstChild);
      var c = Math.cos(phi), s = Math.sin(phi);
      var shownTop = c < 0;
      var k = Math.max(Math.abs(c), 0.03);
      var lift = s * 26;
      // the axis
      if (axis === "vertical") A.el(g, "line", { x1: cx, y1: BY + 44, x2: cx, y2: BY + BH - 44, stroke: C.caution, "stroke-dasharray": "8 6", "stroke-width": 2 });
      else A.el(g, "line", { x1: BX + 24, y1: cy, x2: BX + BW - 24, y2: cy, stroke: C.caution, "stroke-dasharray": "8 6", "stroke-width": 2 });
      // shadow while in the air
      var ax0 = wrong ? (axis === "vertical" ? "horizontal" : "vertical") : axis;
      if (s > 0.02) A.el(g, "rect", { x: cx - hw * (ax0 === "vertical" ? k : 1), y: cy - hh * (ax0 === "vertical" ? 1 : k) + 8,
        width: 2 * hw * (ax0 === "vertical" ? k : 1), height: 2 * hh * (ax0 === "vertical" ? 1 : k), rx: 6, fill: C.ink, opacity: 0.35 * s });
      // the turn actually made: the set axis, or the other one by mistake
      var ax = wrong ? (axis === "vertical" ? "horizontal" : "vertical") : axis;
      var sx = ax === "vertical" ? k : 1, sy = ax === "vertical" ? 1 : k;
      var b = A.el(g, "g", { transform: "translate(" + cx + "," + (cy - lift) + ") scale(" + sx + "," + sy + ")" });
      A.el(b, "rect", { x: -hw, y: -hh, width: 2 * hw, height: 2 * hh, rx: 5, fill: C.copperDim, stroke: C.copperHi, "stroke-width": 2 });
      var P = function (u, v) { return [u * hw, -v * hh]; };
      if (!shownTop) {
        // side 1: B.Cu cut mirrored; holes where the design's land when seen from below
        var gm = mir(RU, RV);
        glyph(b, "R", gm[0] * hw, -gm[1] * hh, axis === "vertical" ? -1 : 1, axis === "vertical" ? 1 : -1, hh * GS, C.live, 0.9);
        HOLES.forEach(function (h) { var m = mir(h[0], h[1]), q = P(m[0], m[1]); A.el(b, "circle", { cx: q[0], cy: q[1], r: 6, fill: C.ink }); });
      } else {
        // side 2, seen from above: plain F.Cu with its pads, and where the holes and the bottom really are
        var rot = wrong;   // a turn about the other axis = the design rotated 180°
        var rg = rot ? [-RU, -RV] : [RU, RV];
        glyph(b, "R", rg[0] * hw, -rg[1] * hh, rot ? -1 : 1, rot ? -1 : 1, hh * GS, C.live, 0.28);
        glyph(b, "F", FU * hw, -FV * hh, 1, 1, hh * GS, C.copperHi, 1);
        HOLES.forEach(function (h) {
          var q = P(h[0], h[1]);
          A.el(b, "circle", { cx: q[0], cy: q[1], r: 13, fill: "none", stroke: C.copperHi, "stroke-width": 5 });
        });
        HOLES.forEach(function (h) {
          var q = rot ? P(-h[0], -h[1]) : P(h[0], h[1]);
          A.el(b, "circle", { cx: q[0], cy: q[1], r: 6, fill: C.ink });
          if (rot) A.el(b, "circle", { cx: q[0], cy: q[1], r: 11, fill: "none", stroke: C.danger, "stroke-width": 2.5 });
        });
      }
      // the reference holes: drilled from side 1, and a rectangle looks the same either way round
      refs().forEach(function (p) {
        A.el(g, "circle", { cx: cx + p[0] * hw, cy: cy - p[1] * hh, r: 9, fill: C.ink, stroke: shownTop ? C.ok : C.copperHi,
          "stroke-width": 2, opacity: s > 0.05 ? 0.35 : 1 });
      });
    }

    function say() {
      var turn = axis === "vertical" ? "left-right, about a vertical line" : "top-bottom, about a horizontal line";
      if (face === "bottom") {
        bedTitle.textContent = "ON THE BED: SIDE 1, BOTTOM UP";
        cap.textContent = "B.Cu is milled mirrored: you are cutting the underside from above";
        st.className = "anim-status";
        st.textContent = "Flipped is set to " + turn + ": the direction you will physically turn the board. The four reference holes sit just outside the corners.";
      } else if (!wrong) {
        bedTitle.textContent = "ON THE BED: SIDE 2, TOP UP";
        cap.textContent = "Top cut as plain F.Cu; every hole lands in its pad";
        st.className = "anim-status ok";
        st.textContent = "Turned over " + turn + ", the way it was set: the mirror cancels, the bottom (faint) reads as KiCad drew it, and the holes land in the top's pads. Re-zero Z on this face; never XY.";
      } else {
        bedTitle.textContent = "ON THE BED: TURNED THE OTHER WAY";
        cap.textContent = "Every hole misses its pad";
        st.className = "anim-status bad";
        st.textContent = "Turned the other way, everything from side 1 lands rotated 180°: the holes miss the pads. The four reference holes still make the same rectangle (green), so the fit looks perfect. Jog to a drilled hole before cutting the top.";
      }
    }

    function flipTo(toTop, asWrong) {
      cancelAnimationFrame(anim);
      if (toTop) wrong = !!asWrong;
      var from = phi, to = toTop ? Math.PI : 0;
      face = toTop ? "top" : "bottom";
      if (A.reduced || from === to) { phi = to; draw(); say(); return; }
      var t0 = null;
      function stp(now) {
        if (t0 === null) t0 = now;
        var q = A.ease((now - t0) / 1400);
        phi = A.lerp(from, to, q);
        draw();
        if (q < 1) anim = requestAnimationFrame(stp); else say();
      }
      anim = requestAnimationFrame(stp);
    }

    A.segmented(row, [["vertical", "Flipped: left-right"], ["horizontal", "Flipped: top-bottom"]], axis, function (v) {
      axis = v; phi = 0; face = "bottom"; wrong = false; draw(); say();
    });
    A.button(row, "Flip it", function () { if (face === "top") { phi = 0; face = "bottom"; } flipTo(true, false); }, "primary");
    A.button(row, "Flip it the other way (a mistake)", function () { if (face === "top") { phi = 0; face = "bottom"; } flipTo(true, true); });
    A.button(row, "Back to side 1", function () { flipTo(false); });
    row.appendChild(st);
    draw(); say();
  });
})();
