/* The whole job in five stages, each a link to its part of the page. A highlight
   travels along them so the order reads at a glance. A row on a wide screen, a
   column on a phone. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  var STAGES = [
    ["export", "Export", "KiCad"],
    ["setup", "Set up", "SRM-CAM"],
    ["zero", "Zero & level", "at the machine"],
    ["check", "Check & export", "SRM-CAM"],
    ["cut", "Cut", "VPanel"]
  ];

  A.define("roadmap", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 440 : 880, H = narrow ? 470 : 250;
    var s = A.stage(host, W, H, "The whole job: export from KiCad, set up in SRM-CAM, zero and level at the machine, check and export, cut in VPanel");
    var boxes = [], centres = [];
    var cw, ch, gap, x0, y0;
    if (narrow) { cw = 330; ch = 70; gap = 16; x0 = 80; y0 = 44; }
    else { cw = 150; ch = 130; gap = 27; x0 = (W - (5 * cw + 4 * gap)) / 2; y0 = 60; }
    STAGES.forEach(function (st, i) {
      var x = narrow ? x0 : x0 + i * (cw + gap), y = narrow ? y0 + i * (ch + gap) : y0;
      centres.push(narrow ? [40, y + ch / 2] : [x + cw / 2, y0 + ch + 30]);
    });
    var a0 = centres[0], a4 = centres[4];
    A.el(s, "line", { x1: a0[0], y1: a0[1], x2: a4[0], y2: a4[1], stroke: C.ruleStrong, "stroke-width": 3 });
    centres.forEach(function (c) { A.el(s, "circle", { cx: c[0], cy: c[1], r: 5, fill: C.ruleStrong }); });
    var dot = A.el(s, "circle", { r: 9, fill: C.copperHi });
    var hold = -1;
    STAGES.forEach(function (st, i) {
      var x = narrow ? x0 : x0 + i * (cw + gap), y = narrow ? y0 + i * (ch + gap) : y0;
      var a = A.el(s, "a", { href: "#" + st[0], "aria-label": (i + 1) + ". " + st[1] + ", " + st[2] });
      var r = A.el(a, "rect", { x: x, y: y, width: cw, height: ch, rx: 6, fill: C.panel, stroke: C.ruleHi, "stroke-width": 2 });
      A.text(a, x + 14, y + 30, String(i + 1), { size: 22, weight: 700, fill: C.copperHi, font: "label" });
      if (narrow) {
        A.text(a, x + 44, y + 32, st[1], { size: 22, weight: 600, font: "label" });
        A.text(a, x + 44, y + 56, st[2], { size: 17, fill: C.text2 });
      } else {
        var name = st[1].split(" & ");
        if (name.length > 1) {
          A.text(a, x + cw / 2, y + 70, name[0] + " &", { anchor: "middle", size: 20, weight: 600, font: "label" });
          A.text(a, x + cw / 2, y + 94, name[1], { anchor: "middle", size: 20, weight: 600, font: "label" });
        } else {
          A.text(a, x + cw / 2, y + 82, st[1], { anchor: "middle", size: 22, weight: 600, font: "label" });
        }
        A.text(a, x + cw / 2, y + 118, st[2], { anchor: "middle", size: 15, fill: C.text2 });
        if (i) A.arrow(s, x - gap + 4, y + ch / 2, x - 4, y + ch / 2, { color: C.text3, head: 7 });
      }
      a.addEventListener("focus", function () { hold = i; });
      a.addEventListener("blur", function () { hold = -1; });
      a.addEventListener("mouseenter", function () { hold = i; });
      a.addEventListener("mouseleave", function () { hold = -1; });
      boxes.push(r);
    });
    A.text(s, W / 2, narrow ? 26 : 34, "Tap a stage to jump to it", { anchor: "middle", size: 15, fill: C.text3 });

    function paint(pos) {
      var k = Math.round(pos);
      boxes.forEach(function (r, i) {
        var on = hold >= 0 ? i === hold : i === k;
        r.setAttribute("stroke", on ? C.copperHi : C.ruleHi);
        r.setAttribute("fill", on ? C.copperFill : C.panel);
      });
      var p = hold >= 0 ? hold : pos, i0 = Math.floor(p), f = p - i0, i1 = Math.min(i0 + 1, 4);
      dot.setAttribute("cx", A.lerp(centres[i0][0], centres[i1][0], f));
      dot.setAttribute("cy", A.lerp(centres[i0][1], centres[i1][1], f));
    }
    A.loop(host, function (t) {
      // 1.6 s on each stage, 0.6 s travelling to the next, then back to the start
      var per = 2.2, n = STAGES.length, c = (t % (per * n)) / per, i = Math.floor(c), f = c - i;
      var m = f < 0.73 ? 0 : A.ease((f - 0.73) / 0.27);
      paint(i < n - 1 ? i + m : (n - 1) * (1 - m));
    }, 4);
  });
})();
