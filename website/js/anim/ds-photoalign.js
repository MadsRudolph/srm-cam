/* The phone photo on the bed (gui2/window.py action_phone_photo / action_load_photo,
   gui2/photo.py, engine/photofit.py). View › Take one with a phone… shows a QR code;
   the photo arrives, is cropped to the copper, and you click four anchor holes in the
   order the design map asks. The four clicks fit a homography that pins the photo
   onto those holes' positions on the bed, straightening a lean as well as a turn; the
   worst anchor says how well it landed (over ~0.5 mm: a click was off). Two sliders
   set Photo (its strength) and Fade the design.

   What it is for, at the lab: rework. With the real board and the design in one
   frame, a spot the mill did not cut through shows where it really is, and a box drawn
   over it on Rework lands on it. It is pinned to the board's own holes, so it cannot
   say where the board sits on the bed: that is what probing measures. Schematic. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var HOLES = [[8, 6], [40, 7], [42, 30], [7, 29], [20, 14], [30, 22], [16, 24]];
  var ANCH = [0, 1, 2, 3];
  var BW = 50, BH = 36;
  var PADOFF = {};
  var MISS = [[33, 14.5], [36, 14.5]];     // a stretch of channel the mill left uncut: copper bridging two traces

  A.define("ds-photoalign", function (host) {
    var laser = host.getAttribute("data-context") === "laser";
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 820 : 470;
    var svg = A.stage(host, W, H, "A phone photo of the board laid on the bed, pinned to its holes");
    // left: the phone / the anchor dialog; right: the bed
    var LX = 16, LY = 16, LW = narrow ? 488 : 330, LH = narrow ? 330 : 438;
    var BX = narrow ? 16 : 362, BY = narrow ? 362 : 16, BWp = narrow ? 488 : 502, BHp = narrow ? 438 : 438;
    A.el(svg, "rect", { x: LX, y: LY, width: LW, height: LH, rx: 3, fill: C.panel, stroke: C.ruleHi });
    A.el(svg, "rect", { x: BX, y: BY, width: BWp, height: BHp, rx: 3, fill: C.sunk, stroke: C.ruleHi });
    var lt = A.text(svg, LX + 14, LY + 26, "", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    A.text(svg, BX + 14, BY + 26, "THE BED IN SRM-CAM", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var gl = A.el(svg, "g", {}), gb = A.el(svg, "g", {});
    var row = A.controls(host);
    var st = A.status(row);
    var stage = 0, clicks = 0, opacity = 0.85, fade = 0.55, anim = 0, warpT = 1;

    var K = narrow ? 8 : 8.4, OX = BX + (BWp - BW * K) / 2, OY = BY + 54 + BH * K;
    function S(x, y) { return [OX + x * K, OY - y * K]; }
    // the photo's own frame: turned 7°, leaning (a keystone), in the dialog
    var PK = narrow ? 7.2 : 5.4, PCX = LX + LW / 2, PCY = LY + (narrow ? 180 : 230);
    function P(x, y) {
      var u = x - BW / 2, v = y - BH / 2, a = 7 * Math.PI / 180;
      var lean = 1 + v * 0.006;
      var ru = (u * Math.cos(a) - v * Math.sin(a)) * lean, rv = u * Math.sin(a) + v * Math.cos(a);
      return [PCX + ru * PK, PCY - rv * PK];
    }

    function board(g, M, alpha, showMiss) {
      var c = [[0, 0], [BW, 0], [BW, BH], [0, BH]].map(function (p) { return M(p[0], p[1]); });
      A.el(g, "polygon", { points: c.map(function (p) { return p.join(","); }).join(" "), fill: "#6a4526", stroke: C.copperHi, "stroke-width": 1.5, opacity: alpha });
      // a few traces
      [[[8, 6], [8, 14], [20, 14]], [[40, 7], [30, 7], [30, 22]], [[7, 29], [16, 29], [16, 24]], [[42, 30], [42, 22], [30, 22]]].forEach(function (tr) {
        A.el(g, "polyline", { points: tr.map(function (p) { return M(p[0], p[1]).join(","); }).join(" "), fill: "none", stroke: "#e3a46b", "stroke-width": 5, opacity: alpha, "stroke-linecap": "round" });
      });
      // the copper left in a channel: a bridge between two traces
      var m0 = M(MISS[0][0], MISS[0][1]), m1 = M(MISS[1][0], MISS[1][1]), mc = M(34.5, 14.5);
      var bw = 1.8 * K * (g === gl ? PK / K : 1);
      A.el(g, "line", { x1: m0[0], y1: m0[1], x2: m1[0], y2: m1[1], stroke: "#e3a46b", "stroke-width": bw, opacity: alpha });
      if (showMiss) A.el(g, "rect", { x: mc[0] - 3.4 * K, y: mc[1] - 2.2 * K, width: 6.8 * K, height: 4.4 * K, fill: "none", stroke: C.danger, "stroke-width": 3, "stroke-dasharray": "6 4" });
      HOLES.forEach(function (h, i) {
        var o = PADOFF[i] || [0, 0], pc = M(h[0] + o[0], h[1] + o[1]), hc = M(h[0], h[1]);
        A.el(g, "circle", { cx: pc[0], cy: pc[1], r: 1.6 * K * (g === gl ? PK / K : 1), fill: "#e3a46b", opacity: alpha });
        A.el(g, "circle", { cx: hc[0], cy: hc[1], r: 0.6 * K * (g === gl ? PK / K : 1), fill: C.ink, opacity: alpha });
      });
    }
    function design(g, alpha) {
      A.el(g, "rect", { x: S(0, BH)[0], y: S(0, BH)[1], width: BW * K, height: BH * K, fill: "none", stroke: C.text2, "stroke-dasharray": "6 5", "stroke-width": 1.5, opacity: alpha });
      HOLES.forEach(function (h, i) {
        var s = S(h[0], h[1]);
        A.el(g, "circle", { cx: s[0], cy: s[1], r: 1.6 * K, fill: "none", stroke: C.live, "stroke-width": 2, opacity: alpha });
        var k = ANCH.indexOf(i);
        if (k >= 0 && stage < 3) A.text(g, s[0] + 12, s[1] - 10, String(k + 1), { size: 16, weight: 700, fill: C.caution, opacity: 1 });
      });
    }

    function draw() {
      while (gl.firstChild) gl.removeChild(gl.firstChild);
      while (gb.firstChild) gb.removeChild(gb.firstChild);
      if (stage === 0) {
        lt.textContent = "VIEW › TAKE ONE WITH A PHONE…";
        var q = narrow ? 150 : 170, qx = PCX - q / 2, qy = PCY - q / 2 - 20;
        A.el(gl, "rect", { x: qx, y: qy, width: q, height: q, fill: "#f3f4f6", rx: 4 });
        // a QR-ish pattern, deterministic
        var n = 21, cs = (q - 16) / n;
        for (var i = 0; i < n; i++) for (var j = 0; j < n; j++) {
          var fin = (i < 7 && j < 7) || (i > 13 && j < 7) || (i < 7 && j > 13);
          var on = fin ? (i % 6 === 0 || j % 6 === 0 || (i % 6 > 1 && i % 6 < 5 && j % 6 > 1 && j % 6 < 5)) : ((i * 7 + j * 13 + i * j) % 5 < 2);
          if (fin && (i > 13)) on = ((i - 14) % 6 === 0 || j % 6 === 0 || ((i - 14) % 6 > 1 && (i - 14) % 6 < 5 && j % 6 > 1 && j % 6 < 5));
          if (fin && (j > 13)) on = (i % 6 === 0 || (j - 14) % 6 === 0 || (i % 6 > 1 && i % 6 < 5 && (j - 14) % 6 > 1 && (j - 14) % 6 < 5));
          if (on) A.el(gl, "rect", { x: qx + 8 + i * cs, y: qy + 8 + j * cs, width: cs + 0.3, height: cs + 0.3, fill: C.ink });
        }
        A.text(gl, PCX, qy + q + 34, "Scan it and take the photo:", { size: 15, anchor: "middle", fill: C.text2 });
        A.text(gl, PCX, qy + q + 56, "straight down, evenly lit, sharp", { size: 15, anchor: "middle", fill: C.text2 });
      } else {
        lt.textContent = stage === 1 ? "THE PHOTO: CLICK THE HOLES IN ORDER" : "THE PHOTO, ANCHORED";
        board(gl, P, 1, false);
        ANCH.forEach(function (idx, k) {
          var p = P(HOLES[idx][0], HOLES[idx][1]);
          if (k < clicks) {
            A.el(gl, "circle", { cx: p[0], cy: p[1], r: 11, fill: "none", stroke: C.caution, "stroke-width": 3 });
            A.text(gl, p[0] + 14, p[1] - 12, String(k + 1), { size: 16, weight: 700, fill: C.caution });
          }
        });
        if (stage === 1 && clicks < 4) {
          var nxt = P(HOLES[ANCH[clicks]][0], HOLES[ANCH[clicks]][1]);
          A.el(gl, "circle", { cx: nxt[0], cy: nxt[1], r: 16, fill: "none", stroke: C.live, "stroke-width": 2, "stroke-dasharray": "4 3" });
        }
        A.text(gl, LX + 14, LY + LH - 18, stage === 1 ? "Anchor " + Math.min(clicks + 1, 4) + " of 4: the one the map numbers " + Math.min(clicks + 1, 4) : "Four clicks fit a homography", { size: 15, fill: C.text2 });
      }
      // the bed: grid, then photo under the design
      for (var gx = 0; gx <= BW; gx += 10) { var a1 = S(gx, 0), a2 = S(gx, BH); A.el(gb, "line", { x1: a1[0], y1: a1[1] + 20, x2: a2[0], y2: a2[1] - 20, stroke: C.rule }); }
      if (stage >= 2) {
        // warp: the photo frame eases onto the bed frame
        var t = A.ease(warpT);
        var M = function (x, y) { var p = P(x, y), s = S(x, y); return [A.lerp(p[0], s[0], t), A.lerp(p[1], s[1], t)]; };
        board(gb, M, opacity, stage >= 3);
      }
      design(gb, stage >= 2 ? Math.max(1 - fade, 0.12) : 1);
    }

    function say() {
      if (stage === 0) { st.className = "anim-status"; st.textContent = "View › Take one with a phone… shows a QR code. The photo arrives in the app, cropped to the copper."; }
      else if (stage === 1) { st.className = "anim-status"; st.textContent = "Click the anchor holes in the order the design map asks: " + clicks + " of 4. Scroll to zoom; undo the last click if you miss."; }
      else if (stage === 2) { st.className = "anim-status ok"; st.textContent = "Laid on the bed: worst anchor 0.18 mm (over about 0.5 means a click was off). The photo is pinned to the board's own holes."; }
      else { st.className = "anim-status caution"; st.textContent = "The real board and the design now share a frame, so a spot the mill did not cut through shows where it really is: here copper still bridges two traces. Box it on Rework, and only that box is cut again."; }
    }
    function all() { draw(); say(); }

    function next() {
      cancelAnimationFrame(anim);
      if (stage === 0) { stage = 1; clicks = 0; }
      else if (stage === 1) {
        clicks++;
        if (clicks >= 4) {
          stage = 2; warpT = 0;
          if (A.reduced) { warpT = 1; stage = 3; }
          else {
            var t0 = null;
            var stp = function (now) {
              if (t0 === null) t0 = now;
              warpT = Math.min((now - t0) / 1400, 1); draw();
              if (warpT < 1) anim = requestAnimationFrame(stp); else { say(); setTimeout(function () { if (stage === 2) { stage = 3; all(); } }, 1600); }
            };
            anim = requestAnimationFrame(stp);
          }
        }
      }
      btn.textContent = stage === 0 ? "The photo arrives" : stage === 1 ? "Click anchor " + Math.min(clicks + 1, 4) : "Done";
      btn.disabled = stage >= 2;
      all();
    }
    var btn = A.button(row, "The photo arrives", next, "primary");
    A.button(row, "Start over", function () { cancelAnimationFrame(anim); stage = 0; clicks = 0; btn.disabled = false; btn.textContent = "The photo arrives"; all(); });
    A.slider(row, "Photo", 0, 1, 0.05, opacity, function (v) { opacity = v; if (gb) draw(); }, function (v) { return Math.round(v * 100) + " %"; });
    A.slider(row, "Fade the design", 0, 1, 0.05, fade, function (v) { fade = v; if (gb) draw(); }, function (v) { return Math.round(v * 100) + " %"; });
    row.appendChild(st);
    all();
  });
})();
