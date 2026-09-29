/* Nets closer than the bit. Two pads of different nets, a gap between them, and the
   0.8 mm flat end mill. A gap narrower than the bit cannot be separated and left
   whole: off, SRM-CAM leaves it uncut and the checks mark it (the two nets stay
   shorted); on ("Cut gaps too narrow for the bit", Full tier, Isolation traces ›
   Cutting parameters) the cutter goes down the middle and takes (0.8 - gap) / 2 off
   each pad. The source's own example: a 0.45 mm gap costs 0.175 mm a side. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BIT = 0.8, PW = 1.7, PH = 2.3;   // mm

  A.define("gaps", function (host) {
    // A phone gets its own layout: a narrower drawing, the bit-vs-gap panel under it
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 690 : 470;
    var K = narrow ? 70 : 90;                                    // px per mm
    var DW = narrow ? 472 : 612, DY = narrow ? 80 : 56, DH = 370; // the drawing's box
    var CX = 24 + DW / 2, CY = DY + DH / 2;                      // centre of the gap on screen
    var PX = narrow ? 24 : 660, PY = narrow ? DY + DH + 16 : 56, QW = narrow ? 472 : 196, QH = narrow ? 170 : 330;
    var svg = A.stage(host, W, H, "Two pads closer than the 0.8 mm bit, cut or left shorted");
    if (narrow) {
      A.text(svg, 24, 34, "Interface › Full, then", { size: 16, font: "mono", fill: C.copperHi });
      A.text(svg, 24, 58, "Isolation traces › Cutting parameters", { size: 16, font: "mono", fill: C.copperHi });
    } else {
      A.text(svg, 24, 34, "Interface › Full, then Isolation traces › Cutting parameters", { size: 16, font: "mono", fill: C.copperHi });
    }
    A.text(svg, 24, H - 18, "Top view, to scale · copper where nothing is cut", { size: 15, fill: C.text3 });

    var clip = A.el(svg, "clipPath", { id: "gaps-clip" });
    A.el(clip, "rect", { x: 24, y: DY, width: DW, height: DH, rx: 3 });
    var g = A.el(svg, "g", { "clip-path": "url(#gaps-clip)" });
    var ann = A.el(svg, "g", {});
    var bitG = A.el(svg, "g", { "clip-path": "url(#gaps-clip)" });
    var bitC = A.el(bitG, "circle", { r: BIT / 2 * K, fill: C.steel, "fill-opacity": 0.35, stroke: C.steel, "stroke-width": 2.5 });
    var side = A.el(svg, "g", {});

    var row = A.controls(host);
    var gap = 0.45, pinch = false, st;
    var box = document.createElement("label");
    box.className = "anim-slider";
    box.style.flex = "0 1 auto";
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.style.accentColor = C.copperHi;
    cb.style.width = "18px"; cb.style.height = "18px"; cb.style.flex = "0 0 auto"; cb.style.minWidth = "0";
    var cbt = document.createElement("span");
    cbt.textContent = "Cut gaps too narrow for the bit (trims pads)";
    cbt.style.color = C.text;
    box.appendChild(cb); box.appendChild(cbt);

    function sx(mm) { return CX + mm * K; }
    function sy(mm) { return CY - mm * K; }

    function draw() {
      while (g.firstChild) g.removeChild(g.firstChild);
      while (ann.firstChild) ann.removeChild(ann.firstChild);
      while (side.firstChild) side.removeChild(side.firstChild);
      var fits = gap >= BIT - 1e-9, h = gap / 2, r = BIT / 2;
      var aL = -h - PW, aR = -h, bL = h, bR = h + PW;
      // the isolation around both pads: everything within a bit width of them is cut
      A.el(g, "rect", { x: 0, y: 0, width: W, height: H, fill: C.copper });
      A.el(g, "rect", { x: sx(aL - BIT), y: sy(PH / 2 + BIT), width: (bR - aL + 2 * BIT) * K, height: (PH + 2 * BIT) * K,
        fill: C.fr4, rx: BIT * K });
      var bite = (!fits && pinch) ? (BIT - gap) / 2 : 0;
      // pads (trimmed if the cutter goes through)
      A.el(g, "rect", { x: sx(aL), y: sy(PH / 2), width: (PW - bite) * K, height: PH * K, fill: C.copper, stroke: C.copperHi, "stroke-width": 1.5 });
      A.el(g, "rect", { x: sx(bL + bite), y: sy(PH / 2), width: (PW - bite) * K, height: PH * K, fill: C.copper, stroke: C.copperHi, "stroke-width": 1.5 });
      A.text(g, sx(aL + PW / 2), sy(0) + 6, "net A", { size: 18, anchor: "middle", fill: C.ink, weight: 700 });
      A.text(g, sx(bR - PW / 2), sy(0) + 6, "net B", { size: 18, anchor: "middle", fill: C.ink, weight: 700 });
      var cur = null;
      if (!fits && !pinch) {
        // the gap stays copper: a bridge between the nets
        A.el(g, "rect", { x: sx(-h), y: sy(PH / 2), width: gap * K, height: PH * K, fill: C.copper });
        A.el(g, "rect", { x: sx(-h), y: sy(PH / 2), width: gap * K, height: PH * K, fill: C.danger, opacity: 0.35 });
        var m = 16;
        A.el(ann, "path", { d: "M" + (CX - m) + "," + (CY - m) + "L" + (CX + m) + "," + (CY + m) + "M" + (CX + m) + "," + (CY - m) + "L" + (CX - m) + "," + (CY + m),
          stroke: C.danger, "stroke-width": 5, "stroke-linecap": "round" });
        A.text(ann, CX, sy(PH / 2) - 16, "uncut: A and B shorted", { size: 17, anchor: "middle", fill: C.danger, weight: 700 });
      } else {
        // the channel down the middle of the gap, one bit wide
        A.el(g, "rect", { x: sx(-r), y: sy(PH / 2 + BIT), width: BIT * K, height: (PH + 2 * BIT) * K, fill: C.fr4 });
        if (bite > 0) {
          [aR, bL].forEach(function (x) {
            A.el(ann, "line", { x1: sx(x), y1: sy(PH / 2), x2: sx(x), y2: sy(-PH / 2), stroke: C.copperHi, "stroke-dasharray": "5 5", "stroke-width": 1.5 });
          });
          A.text(ann, CX, sy(PH / 2) - 16, "−" + bite.toFixed(3) + " mm off each pad", { size: 17, anchor: "middle", fill: C.caution, weight: 700 });
        } else {
          A.text(ann, CX, sy(PH / 2) - 16, "the bit fits: nothing trimmed", { size: 17, anchor: "middle", fill: C.ok, weight: 700 });
        }
        cur = true;
      }
      bitG.style.display = cur ? "" : "none";
      // gap dimension under the pads
      var dy = sy(-PH / 2) + 34;
      A.el(ann, "line", { x1: sx(-h), y1: dy - 12, x2: sx(-h), y2: dy + 4, stroke: C.text2 });
      A.el(ann, "line", { x1: sx(h), y1: dy - 12, x2: sx(h), y2: dy + 4, stroke: C.text2 });
      A.text(ann, CX, dy + 24, "gap " + gap.toFixed(2) + " mm", { size: 16, anchor: "middle", fill: C.text, weight: 600 });

      // the side panel: the bit against the gap
      var px = PX, py = PY - 56, bc = px + 98;
      A.el(side, "rect", { x: px, y: PY, width: QW, height: QH, fill: C.panel, stroke: C.ruleStrong, rx: 3 });
      A.text(side, px + 14, py + 84, "BIT vs GAP", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
      var bw = BIT * 150, gw = Math.min(gap, 1.2) * 150;
      A.el(side, "rect", { x: bc - bw / 2, y: py + 110, width: bw, height: 18, fill: C.steel, rx: 2 });
      A.text(side, bc, py + 150, "bit 0.80 mm", { size: 15, anchor: "middle", fill: C.text2 });
      A.el(side, "rect", { x: bc - gw / 2, y: py + 172, width: gw, height: 18, fill: fits ? C.ok : C.danger, rx: 2 });
      A.text(side, bc, py + 212, "gap " + gap.toFixed(2) + " mm", { size: 15, anchor: "middle", fill: C.text2 });
      var lx = narrow ? px + 220 : px + 14, ly = narrow ? py + 110 : py + 256;
      var lines = fits ? ["It fits. Both pads", "stay whole, the", "switch changes", "nothing here."]
        : pinch ? ["Cut anyway. Nothing", "is left shorted;", "each pad is " + bite.toFixed(3), "mm smaller."]
          : ["Off: left uncut.", "The checks mark it", "✕ and the nets", "stay shorted."];
      lines.forEach(function (s, i) {
        A.text(side, lx, ly + i * 24, s, { size: 16, fill: fits ? C.ok : pinch ? C.caution : C.danger });
      });

      st.className = "anim-status " + (fits ? "ok" : pinch ? "" : "bad");
      st.style.color = !fits && pinch ? C.caution : "";
      st.textContent = fits
        ? "A " + gap.toFixed(2) + " mm gap takes the 0.8 mm bit: the nets are separated whatever the switch says."
        : pinch
          ? "On: the cutter goes down the middle anyway, " + bite.toFixed(3) + " mm off each pad, and nothing is left shorted. The proper fix is still more clearance in KiCad."
          : "Off: a " + gap.toFixed(2) + " mm gap cannot take the 0.8 mm bit, so it is left uncut and the two nets stay shorted, whatever the depth.";
    }

    // the bit slides down the channel while it is cut
    A.loop(host, function (t) {
      var y = ((t * 0.9) % (PH + 2 * BIT)) - PH / 2 - BIT;
      A.set(bitC, { cx: CX, cy: sy(-y) });
    }, (PH / 2 + BIT) / 0.9);      // reduced motion: the bit stands in the middle of the gap

    A.slider(row, "Gap", 0.2, 1.2, 0.05, gap, function (v) { gap = v; if (st) draw(); },
      function (v) { return v.toFixed(2) + " mm"; });
    row.appendChild(box);
    cb.addEventListener("change", function () { pinch = cb.checked; draw(); });
    st = A.status(row);
    draw();
  });
})();
