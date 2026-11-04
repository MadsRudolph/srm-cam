/* What the option does to the Gerber: B.Mask as KiCad plots it, seen from the top, is
   mirrored once with the outline, so it matches the copper side lying face up, and each
   opening comes in 0.1 mm per side. A real board (sm-board.js), and the real pad: the
   ESP32 module's 0.9 x 1.5 mm pads come out 0.7 x 1.3. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C, B = window.SMBoard;

  A.define("sm-files", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 790 : 452;
    var svg = A.stage(host, W, H, "The board's mask openings being mirrored, with the outline, and each pad shrunk by 0.1 mm per side");
    var K = narrow ? 8.8 : 7.4, OX = narrow ? 22 : 24, OY = 60;
    function sx(x) { return OX + x * K; }
    function sy(y) { return OY + (B.H - y) * K; }
    var head = A.text(svg, OX, 34, "", { size: 16, weight: 600, font: "mono", fill: C.text });

    A.el(svg, "rect", { x: OX - 8, y: OY - 8, width: B.W * K + 16, height: B.H * K + 16, rx: 4, fill: C.panel, stroke: C.ruleHi });
    var art = A.el(svg, "g", {});
    A.el(art, "rect", { x: sx(0), y: sy(B.H), width: B.W * K, height: B.H * K, fill: "none", stroke: C.danger, "stroke-width": 2 });
    var rects = B.PADS.map(function (p) { return B.pad(art, p, sx, sy, K, { fill: C.live }); });
    // one pad ringed, so the eye can follow where it goes
    var mark = B.PADS[B.CHECK[0]];
    A.el(art, "circle", { cx: sx(mark[0]), cy: sy(mark[1]), r: 16, fill: "none", stroke: C.caution, "stroke-width": 2.5 });

    // the pad, zoomed
    var ZX = narrow ? 30 : OX + B.W * K + 34, ZY = narrow ? OY + B.H * K + 46 : OY - 8;
    var ZW = narrow ? W - 60 : W - ZX - 20, ZH = narrow ? 230 : B.H * K + 16;
    A.el(svg, "rect", { x: ZX, y: ZY, width: ZW, height: ZH, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(svg, ZX + 14, ZY + 26, "ONE PAD, ZOOMED", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var ZK = narrow ? 80 : 86, CX = ZX + ZW / 2 - (narrow ? 50 : 14), CY = ZY + ZH / 2 + 8;
    A.el(svg, "rect", { x: CX - 0.45 * ZK, y: CY - 0.75 * ZK, width: 0.9 * ZK, height: 1.5 * ZK, fill: C.copperDim, stroke: C.copperHi, "stroke-width": 1.5 });
    var zo = A.el(svg, "rect", { fill: C.live, opacity: 0.85 });
    var dimW = A.text(svg, CX, CY + 0.75 * ZK + 24, "", { size: 15, font: "mono", anchor: "middle", fill: C.text2 });
    var dimH = A.text(svg, CX + 0.45 * ZK + 12, CY + 5, "", { size: 15, font: "mono", fill: C.text2 });
    A.text(svg, CX - 0.45 * ZK - 12, CY - 0.75 * ZK + 14, "pad", { size: 15, anchor: "end", fill: C.copperHi });
    var opT = A.text(svg, CX - 0.45 * ZK - 12, CY + 5, "opening", { size: 15, anchor: "end", fill: C.live });

    var line = A.text(svg, OX - 2, H - 16, "", { size: narrow ? 15 : 17, weight: 700 });

    function draw(t) {
      var flip = A.ease((t - 1.2) / 1.4);
      var scale = A.lerp(-1, 1, flip);                 // the data is the file's frame
      var pivot = sx(B.W / 2);
      art.setAttribute("transform", "translate(" + pivot + ",0) scale(" + scale + ",1) translate(" + (-pivot) + ",0)");
      var s = 0.1 * A.ease((t - 3.2) / 1);
      var w = 0.9 - 2 * s, h = 1.5 - 2 * s;
      A.set(zo, { x: CX - w / 2 * ZK, y: CY - h / 2 * ZK, width: w * ZK, height: h * ZK });
      dimW.textContent = w.toFixed(2) + " mm";
      dimH.textContent = h.toFixed(2);
      rects.forEach(function (r, i) {
        var p = B.PADS[i], gw = p[2] + 0.2 - 2 * s, gh = p[3] + 0.2 - 2 * s;
        A.set(r, { x: sx(p[0]) - gw * K / 2, y: sy(p[1]) - gh * K / 2, width: gw * K, height: gh * K });
      });
      if (t < 1.2) {
        head.textContent = "esp32solder-B_Mask.gbs";
        line.textContent = "As KiCad plots it: seen from the top, through the board.";
        line.setAttribute("fill", C.text);
      } else if (t < 3.2) {
        head.textContent = "esp32solder-B_Mask.gbs, mirrored";
        line.textContent = "Mirrored once, outline with it: now it matches the copper side up.";
        line.setAttribute("fill", C.text);
      } else {
        head.textContent = "esp32solder_mask_mirrored.dxf";
        line.textContent = narrow ? "In mm, 1:1. Do not flip it again." : "In mm, 1:1, closed shapes. Do not flip it again in the xTool software.";
        line.setAttribute("fill", C.ok);
      }
    }
    var play = B.player(host, 4.6, draw);
    var row = A.controls(host);
    A.button(row, "Play again", function () { play.replay(); }, "primary");
    var st = A.status(row);
    st.textContent = "A real board: 78 openings, 54 × 45.8 mm. The red rectangle is the outline, on its own layer.";
  });
})();
