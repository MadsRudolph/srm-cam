/* How the pieces fit: KiCad's Gerbers go into SRM-CAM, which checks them, plans the
   run and writes one .nc file per step plus the run sheet; VPanel plays those files
   on the SRM-20. Beside that, the optional Arduino probe link lets SRM-CAM read the
   position, jog, probe the bed and zero Z (it does not play the files). A file token
   travels the main line; tap a stop to read what happens there and follow the link
   to its page. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  var STOPS = [
    ["KiCad", "Gerbers + drill", "getting-started.html#kicad",
      "Plot B.Cu and Edge.Cuts, and generate the Excellon drill files, into one folder."],
    ["SRM-CAM", "checks · plan", "milling-a-board.html#setup",
      "Open the folder: the board lands on the bed, the checks mark every short, and the rail becomes the run plan."],
    [".nc files", "+ run sheet", "reference.html",
      "Export the job writes one file per step: dry run, drill, isolation traces, cut-out, and the run sheet with the order."],
    ["VPanel", "Cut › Add › Output", "milling-a-board.html#cut",
      "Roland's VPanel plays the files on the machine. It lists them alphabetically: move the cut-out to the bottom."],
    ["SRM-20", "the board", "milling-a-board.html#finish",
      "The mill cuts the copper; out comes a board ready to sand, check with a multimeter, and solder."]
  ];

  A.define("ix-pipeline", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 440 : 880, H = narrow ? 540 : 250;
    var s = A.stage(host, W, H, "KiCad Gerbers go into SRM-CAM, which writes .nc files; VPanel plays them on the SRM-20. The optional probe link connects SRM-CAM to the machine for jogging, probing and zeroing Z.");
    var cw = narrow ? 250 : 140, ch = narrow ? 72 : 96, gap = narrow ? 34 : 34;
    var x0 = narrow ? 30 : (W - (5 * cw + 4 * gap)) / 2, y0 = narrow ? 20 : 40;
    var boxes = [], centres = [];
    STOPS.forEach(function (st, i) {
      var x = narrow ? x0 : x0 + i * (cw + gap), y = narrow ? y0 + i * (ch + gap) : y0;
      var a = A.el(s, "a", { href: st[2], "aria-label": st[0] + ": " + st[3] });
      var r = A.el(a, "rect", { x: x, y: y, width: cw, height: ch, rx: 6, fill: C.panel, stroke: i === 1 ? C.copperDim : C.ruleHi, "stroke-width": 2 });
      A.text(a, x + cw / 2, y + ch / 2 - (narrow ? 2 : 4), st[0], { size: narrow ? 21 : 20, weight: 700, anchor: "middle", font: "label", fill: i === 1 ? C.copperHi : C.text });
      A.text(a, x + cw / 2, y + ch / 2 + (narrow ? 22 : 22), st[1], { size: 15, anchor: "middle", fill: C.text2 });
      a.addEventListener("mouseenter", function () { hold(i); });
      a.addEventListener("focus", function () { hold(i); });
      a.addEventListener("mouseleave", function () { hold(-1); });
      a.addEventListener("blur", function () { hold(-1); });
      boxes.push(r);
      centres.push(narrow ? [x + cw / 2, y + ch / 2] : [x + cw / 2, y + ch / 2]);
      if (i) {
        if (narrow) A.arrow(s, x + cw / 2, y - gap + 4, x + cw / 2, y - 4, { color: C.text3, head: 7 });
        else A.arrow(s, x - gap + 4, y + ch / 2, x - 4, y + ch / 2, { color: C.text3, head: 7 });
      }
    });
    // the probe link: SRM-CAM <-> SRM-20, dashed, beside the main line
    var c1 = centres[1], c4 = centres[4], link;
    if (narrow) {
      var lx = x0 + cw + 50;
      link = A.el(s, "path", { d: "M" + (x0 + cw) + " " + c1[1] + " H" + lx + " V" + c4[1] + " H" + (x0 + cw), fill: "none", stroke: C.live, "stroke-width": 2.5, "stroke-dasharray": "7 6" });
      A.text(s, lx + 10, (c1[1] + c4[1]) / 2 - 10, "probe", { size: 15, fill: C.live, weight: 600 });
      A.text(s, lx + 10, (c1[1] + c4[1]) / 2 + 10, "link", { size: 15, fill: C.live, weight: 600 });
    } else {
      var ly = y0 + ch + 60;
      link = A.el(s, "path", { d: "M" + c1[0] + " " + (y0 + ch) + " V" + ly + " H" + c4[0] + " V" + (y0 + ch), fill: "none", stroke: C.live, "stroke-width": 2.5, "stroke-dasharray": "7 6" });
      A.text(s, (c1[0] + c4[0]) / 2, ly + 26, "optional probe link (Arduino): position, jog, probe the bed, zero Z", { size: 15, anchor: "middle", fill: C.live });
    }
    var token = A.el(s, "g", {});
    A.el(token, "rect", { x: -16, y: -11, width: 32, height: 22, rx: 3, fill: C.copperHi });
    var tokText = A.text(token, 0, 5, "gbr", { size: 12, anchor: "middle", fill: C.ink, weight: 700, font: "mono" });
    var pulse = A.el(s, "circle", { r: 6, fill: C.live });

    var row = A.controls(host);
    var st = A.status(row);
    var held = -1, lastK = -1;
    function hold(i) { held = i; if (i >= 0) show(i); }
    function show(i) {
      lastK = i;
      boxes.forEach(function (r, j) { r.setAttribute("stroke", j === i ? C.copperHi : (j === 1 ? C.copperDim : C.ruleHi)); r.setAttribute("fill", j === i ? C.copperFill : C.panel); });
      st.innerHTML = "<strong>" + STOPS[i][0] + ".</strong> " + STOPS[i][3];
    }
    var len = link.getTotalLength ? link.getTotalLength() : 0;
    A.loop(host, function (t) {
      var per = 2.4, n = STOPS.length, c = (t % (per * n)) / per, i = Math.floor(c), f = c - i;
      if (held < 0 && i !== lastK) show(i);
      var m = f < 0.6 ? 0 : A.ease((f - 0.6) / 0.4), j = Math.min(i + 1, n - 1);
      if (i === n - 1) m = 0;
      // Gerbers until SRM-CAM has written the files; .nc from there on
      tokText.textContent = (i + m) < 1.5 ? "gbr" : "nc";
      var p = [A.lerp(centres[i][0], centres[j][0], m), A.lerp(centres[i][1], centres[j][1], m)];
      token.setAttribute("transform", "translate(" + (p[0] - (narrow ? cw / 2 + 2 : 0)) + "," + (p[1] + (narrow ? 0 : -ch / 2 - 18)) + ")");
      if (len) {
        var q = link.getPointAtLength(((t * 0.35) % 1) * len);
        pulse.setAttribute("cx", q.x); pulse.setAttribute("cy", q.y);
      }
    }, 0);
    show(0);
  });
})();
