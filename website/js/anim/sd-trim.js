/* Fine pitch on the ball mill: the 0.8 mm ball mill cuts a 0.44 mm channel at the copper
   (docs/bit-capabilities.md). Where two pads are closer than that, "Cut gaps too narrow
   for the bit" runs one cut down the middle of the gap, which trims both pads: each is
   left at most pitch - 0.44 mm wide. The channel and the pitches are to scale; the pad
   widths are typical footprint values, drawn for the picture. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var CH = 0.44;
  var PARTS = {
    soic: { name: "SOIC, 1.27 mm pitch", pitch: 1.27, pad: 0.6 },
    tssop: { name: "TSSOP, 0.65 mm pitch", pitch: 0.65, pad: 0.4 },
    p05: { name: "0.5 mm pitch (QFN, fine TSSOP)", pitch: 0.5, pad: 0.3 }
  };

  A.define("sd-trim", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, X0 = 30, Y0 = 70, PADL = 1.4;
    var K = narrow ? (W - 60) / 3.6 : 150, VIEW = (W - 60) / K;
    var H = Y0 + PADL * K + 110;
    var svg = A.stage(host, W, H, "Three pads at the part's pitch, with the ball mill's 0.44 mm channel cut down each gap, to scale");
    A.text(svg, X0, 30, "BALL MILL, FROM ABOVE · TO SCALE", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var g = A.el(svg, "g");
    var t1 = A.text(svg, X0, Y0 + PADL * K + 70, "", { size: 16, weight: 700, fill: C.text });
    var t2 = A.text(svg, X0, Y0 + PADL * K + 96, "", { size: 14, fill: C.text2 });
    var row = A.controls(host);
    var st = A.status(row);
    var cur = "soic";
    A.segmented(row, [["soic", "SOIC 1.27"], ["tssop", "TSSOP 0.65"], ["p05", "0.5 mm pitch"]], "soic", function (v) { cur = v; draw(); });
    row.appendChild(st);

    function draw() {
      while (g.firstChild) g.removeChild(g.firstChild);
      var p = PARTS[cur], mid = VIEW / 2;
      function X(mm) { return X0 + mm * K; }
      A.el(g, "rect", { x: X(0), y: Y0 - 10, width: VIEW * K, height: PADL * K + 20, fill: C.copper });   // the copper around
      var left = Math.min(p.pad, p.pitch - CH);
      [-1, 0, 1].forEach(function (k) {
        var c = mid + k * p.pitch;
        // the channel round each pad (isolation), then the pad
        A.el(g, "rect", { x: X(c - p.pad / 2 - CH), y: Y0 - 10, width: (p.pad + 2 * CH) * K, height: PADL * K + 20, fill: C.fr4 });
      });
      [-1, 0, 1].forEach(function (k) {
        var c = mid + k * p.pitch;
        A.el(g, "rect", { x: X(c - p.pad / 2), y: Y0, width: p.pad * K, height: PADL * K, fill: "none", stroke: C.text3, "stroke-dasharray": "4 3" });
        A.el(g, "rect", { x: X(c - left / 2), y: Y0, width: Math.max(left, 0) * K, height: PADL * K, fill: C.copperHi });
      });
      // the cut down each gap
      if (p.pitch - p.pad < CH) [-0.5, 0.5].forEach(function (k) {
        var c = mid + k * p.pitch;
        A.el(g, "rect", { x: X(c - CH / 2), y: Y0 - 10, width: CH * K, height: PADL * K + 20, fill: C.live, "fill-opacity": 0.25, stroke: C.live, "stroke-width": 1 });
      });
      // dimension: pitch
      var y = Y0 + PADL * K + 26;
      A.el(g, "line", { x1: X(mid), y1: y, x2: X(mid + p.pitch), y2: y, stroke: C.text3 });
      A.text(g, X(mid + p.pitch / 2), y + 18, "pitch " + p.pitch.toFixed(2), { size: 13, anchor: "middle", fill: C.text2 });
      if (p.pitch - p.pad < CH) A.text(g, X(mid + p.pitch / 2), Y0 - 18, "0.44 cut down the gap", { size: 13, anchor: "middle", fill: C.live });
      else A.text(g, X(mid + p.pitch / 2), Y0 - 18, "gap " + (p.pitch - p.pad).toFixed(2) + ": the 0.44 channel fits", { size: 13, anchor: "middle", fill: C.text2 });
      t1.textContent = p.name;
      var trimmed = p.pitch - CH < p.pad;
      t2.textContent = "Pad left at most " + p.pitch.toFixed(2) + " − 0.44 = " + (p.pitch - CH).toFixed(2) + " mm" + (trimmed ? " (dashed: the pad as drawn)" : ": the pad is untouched");
      var verdict = { soic: ["ok", "Fine: the cut fits between the pads."], tssop: ["caution", "Marginal: about 0.21 mm of pad is left."], p05: ["bad", "Not usable: about 0.06 mm of pad is left."] }[cur];
      st.className = "anim-status " + verdict[0];
      st.textContent = verdict[1] + " The laser goes finer: see Make a board.";
    }
    draw();
  });
})();
