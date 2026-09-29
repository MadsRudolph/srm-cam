/* Why level the bed: a section along one isolation channel of a bowed sheet.
   Z zero is set at the datum (the left end here), the copper foil is 0.035 mm and
   the channel is cut 0.15 mm deep. Depths are drawn 100 times the horizontal scale.
   A flat cut leaves copper wherever the surface sags more than 0.115 mm below the
   datum; a levelled cut follows the measured surface and clears it everywhere. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var CU = 0.035, CUT = 0.15;       // mm
  var TOP = 150, KZ = 700;          // screen y of the datum surface; px per mm of depth (x100 the horizontal)
  var N = 160;

  A.define("bow", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;   // a phone: a narrower drawing
    var W = narrow ? 520 : 880, H = 450;
    var X1 = narrow ? 44 : 70, X2 = W - 50;                         // the section
    var svg = A.stage(host, W, H, "Cross-section of a bowed copper sheet and the isolation cut, flat or levelled");
    A.text(svg, 24, 34, "SECTION ALONG A CHANNEL", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    A.text(svg, W - 24, 34, "depths drawn ×100", { size: 15, anchor: "end", fill: C.text3 });

    var gFr4 = A.el(svg, "path", { fill: C.fr4 });
    var gCu = A.el(svg, "path", { fill: C.copper });
    var pat = A.el(A.el(svg, "defs", {}), "pattern", { id: "bow-hatch", width: 10, height: 10, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
    A.el(pat, "rect", { width: 10, height: 10, fill: C.sunk, opacity: 0.55 });
    A.el(pat, "line", { x1: 0, y1: 0, x2: 0, y2: 10, stroke: C.text3, "stroke-width": 2 });
    var gGone = A.el(svg, "path", { fill: "url(#bow-hatch)" });           // what the channel removes
    var gLeft = A.el(svg, "path", { fill: C.danger, opacity: 0.9 });      // copper the cut missed
    var gCut = A.el(svg, "path", { fill: "none", "stroke-width": 3 });
    var gAnn = A.el(svg, "g", {});
    // datum
    A.el(svg, "line", { x1: X1 - 34, y1: TOP, x2: X1 + 60, y2: TOP, stroke: C.live, "stroke-width": 2, "stroke-dasharray": "6 4" });
    A.text(svg, X1 - 34, TOP - 12, "Z 0 at the datum", { size: 15, fill: C.live });

    var row = A.controls(host);
    var bow = 0.13, level = false;
    var st;

    function surf(i) { var u = i / N * 2 - 1; return bow * (1 - u * u); }   // mm below the datum
    function X(i) { return X1 + (X2 - X1) * i / N; }
    function Y(mm) { return TOP + mm * KZ; }

    function draw() {
      var top = [], cuB = [], frB = [], cut = [], gone, miss = 0, spans = [], inSpan = false;
      for (var i = 0; i <= N; i++) {
        var s = surf(i), c = level ? s + CUT : CUT;
        top.push([X(i), Y(s)]); cuB.push([X(i), Y(s + CU)]); frB.push([X(i), Y(s + CU) + 70]);
        cut.push([X(i), Y(c)]);
        var m = c < s + CU;
        if (m) miss++;
        if (m && !inSpan) { spans.push([i, i]); inSpan = true; }
        if (m) spans[spans.length - 1][1] = i;
        if (!m) inSpan = false;
      }
      function poly(a, b) { return "M" + a.concat(b.slice().reverse()).map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join("L") + "Z"; }
      A.set(gFr4, { d: poly(cuB, frB) });
      A.set(gCu, { d: poly(top, cuB) });
      // removed: from the surface down to the cut line (clipped to the copper+board)
      gone = cut.map(function (p, i) { return [p[0], Math.max(p[1], top[i][1])]; });
      A.set(gGone, { d: poly(top, gone) });
      // left behind: copper between the cut line and the copper's underside
      var lt = [];
      spans.forEach(function (sp) {
        var a = [], b = [];
        for (var i = sp[0]; i <= sp[1]; i++) { a.push([X(i), Math.max(cut[i][1], top[i][1])]); b.push([X(i), cuB[i][1]]); }
        lt.push(poly(a, b));
      });
      A.set(gLeft, { d: lt.join(" ") || "M0,0" });
      A.set(gCut, { d: "M" + cut.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join("L"),
        stroke: level ? C.ok : C.caution });

      while (gAnn.firstChild) gAnn.removeChild(gAnn.firstChild);
      // labels at the right end, where the surface is at the datum
      A.text(gAnn, X2 - 4, Y(CU / 2) + 5, "copper 0.035 mm", { size: 15, anchor: "end", fill: C.text, weight: 600 });
      A.text(gAnn, X2 - 4, Y(CUT) + 22, level ? "cut follows the surface" : "flat cut, 0.15 mm below Z 0",
        { size: 15, anchor: "end", fill: level ? C.ok : C.caution, weight: 600 });
      if (bow > 0.004) {
        var mx = X(N / 2);
        var ax = mx + (narrow ? 40 : 150);
        A.arrow(gAnn, ax, Y(0), ax, Y(bow), { color: C.text2, head: 7 });
        A.el(gAnn, "line", { x1: mx - 40, y1: Y(0), x2: ax + 10, y2: Y(0), stroke: C.text4, "stroke-dasharray": "3 4" });
        A.text(gAnn, ax + 10, Y(bow / 2) + 5, "sags " + bow.toFixed(3) + " mm", { size: 15, fill: C.text2 });
      }
      A.text(gAnn, X(12), Y(CUT) - 30, "cut away", { size: 15, fill: C.text });
      if (spans.length) {
        var sp = spans[0], cx = (X(sp[0]) + X(sp[1])) / 2;
        A.text(gAnn, cx, Y(bow + CU) + 100, "copper left in the channel: traces stay shorted",
          { size: 16, anchor: "middle", fill: C.danger, weight: 600 });
      }
      var pct = Math.round(100 * miss / (N + 1));
      st.className = "anim-status " + (miss ? "bad" : "ok");
      st.textContent = level
        ? "Levelled: the cut follows the measured surface, 0.15 mm into it everywhere. Every channel is clear."
        : miss
          ? "Flat cut: " + pct + " % of the channel leaves copper behind, where the sheet sags more than 0.115 mm."
          : "Flat cut: this sheet sags less than 0.115 mm, so a flat cut still gets through the foil.";
    }

    A.slider(row, "Sheet bow", 0, 0.2, 0.005, bow, function (v) { bow = v; if (st) draw(); },
      function (v) { return v.toFixed(3) + " mm"; });
    A.segmented(row, [[false, "Flat cut"], [true, "Levelled"]], false, function (v) { level = v; if (st) draw(); });
    st = A.status(row);
    draw();
  });
})();
