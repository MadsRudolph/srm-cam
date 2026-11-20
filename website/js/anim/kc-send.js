/* From KiCad to SRM-CAM (kicad.html): what the two KiCad buttons do, in order.
   Strings and file names from kicad-plugin/ (action_send_to_srmcam.py, srm20area/
   methods.py, plot.py, sendto.py) and gui2/window.py. The folder is srm-cam/ beside
   the .kicad_pcb; the names are KiCad's with Protel extensions, as the plugin plots
   them (here for a board called boost_v2). Schematic. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  var FILES = ["boost_v2-F_Cu.gtl", "boost_v2-B_Cu.gbl", "boost_v2-Edge_Cuts.gm1",
    "boost_v2-F_Mask.gts", "boost_v2-B_Mask.gbs", "boost_v2-F_Silkscreen.gto",
    "boost_v2-B_Silkscreen.gbo", "boost_v2-F_Paste.gtp", "boost_v2-B_Paste.gbp",
    "boost_v2-PTH.drl", "boost_v2-NPTH.drl"];
  var STAGES = [
    ["rules", "1 · Set design rules", "Pick Fiber laser copper, Apply, save. The choice is kept in srm-cam/method.json.", "Fiber laser copper, Apply, save."],
    ["check", "2 · Send: the check", "Send to SRM-CAM checks the board against that method first.", "First, the board is checked."],
    ["plot", "3 · Send: the plot", "KiCad plots every layer and both drill files into srm-cam/, as on screen.", "Every layer and drill file, plotted."],
    ["hand", "4 · Send: the hand-over", "The folder goes to SRM-CAM: the open window, or it starts one.", "The folder goes to SRM-CAM."],
    ["open", "5 · In SRM-CAM", "The board opens; the chip at the top reads Laser · from KiCad.", "Opened: Laser · from KiCad."]
  ];

  A.define("kc-send", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 760 : 420;
    var svg = A.stage(host, W, H, "KiCad's Set design rules and Send to SRM-CAM: the method file, the check, the plotted files in the srm-cam folder, and the board opening in SRM-CAM with the chip Laser from KiCad");
    A.text(svg, W - 16, 26, "schematic", { size: 13, anchor: "end", fill: C.text4, font: "label", spacing: "0.1em" });
    var head = A.text(svg, 16, 30, "", { size: 18, weight: 700 });

    // three columns (desktop) or three rows (phone)
    var box = narrow
      ? [[16, 60, W - 32, 280], [16, 356, W - 32, 210], [16, 582, W - 32, 140]]
      : [[16, 56, 250, 300], [300, 56, 290, 300], [624, 56, 240, 300]];
    var titles = ["KiCad · PCB editor", "srm-cam/ beside the board", "SRM-CAM"];
    var frames = box.map(function (b, i) {
      var r = A.el(svg, "rect", { x: b[0], y: b[1], width: b[2], height: b[3], rx: 8, fill: C.panel, stroke: C.ruleHi, "stroke-width": 1.5 });
      A.text(svg, b[0] + 12, b[1] + 24, titles[i], { size: 14, weight: 600, fill: C.text2, font: "label", spacing: "0.06em" });
      return r;
    });

    // KiCad: the board file, the two buttons
    var kb = box[0];
    A.text(svg, kb[0] + 14, kb[1] + 54, "boost_v2.kicad_pcb", { size: 14, font: "mono", fill: C.text });
    function btn(x, y, w, label) {
      var g = A.el(svg, "g", {});
      var r = A.el(g, "rect", { x: x, y: y, width: w, height: 30, rx: 5, fill: C.raised, stroke: C.ruleStrong });
      A.text(g, x + w / 2, y + 20, label, { size: 13, anchor: "middle", weight: 600 });
      return r;
    }
    var bw = kb[2] - 28;
    var bRules = btn(kb[0] + 14, kb[1] + 72, bw, "Set design rules for SRM-CAM");
    var bSend = btn(kb[0] + 14, kb[1] + 112, bw, "Send to SRM-CAM");
    var method = A.text(svg, kb[0] + 14, kb[1] + 166, "", { size: 13, fill: C.live });

    // the check: a warning card that can show
    var warn = A.el(svg, "g", { opacity: 0 });
    var wx = narrow ? kb[0] + 250 : kb[0] + 14, wy = narrow ? kb[1] + 54 : kb[1] + 186;
    var ww = narrow ? kb[2] - 264 : bw;
    if (narrow) { wx = kb[0] + 14; wy = kb[1] + 178; ww = bw; }
    A.el(warn, "rect", { x: wx, y: wy, width: ww, height: 100, rx: 6, fill: C.cautionFill, stroke: C.caution });
    A.text(warn, wx + 10, wy + 22, "Board asks more than its method?", { size: 12.5, fill: C.caution, weight: 600 });
    A.text(warn, wx + 10, wy + 42, "Set the rules… · Send anyway · Cancel", { size: 12.5, fill: C.text2 });
    var okline = A.text(warn, wx + 10, wy + 72, "This board: within the laser's rules ✓", { size: 12.5, fill: C.ok });
    if (narrow) A.set(warn, { transform: "translate(0,0)" });

    // the folder
    var fb = box[1];
    var json = A.text(svg, fb[0] + 14, fb[1] + 52, "method.json", { size: 13, font: "mono", fill: C.live, opacity: 0 });
    var files = FILES.map(function (f, i) {
      var col = narrow ? (i < 6 ? 0 : 1) : 0, rowi = narrow ? (i % 6) : i;
      var x = fb[0] + 14 + col * (fb[2] / 2), y = fb[1] + 74 + rowi * (narrow ? 22 : 20);
      return A.text(svg, x, y, f, { size: narrow ? 13.5 : 12.5, font: "mono", fill: C.text2, opacity: 0 });
    });

    // SRM-CAM
    var sb = box[2];
    var chip = A.el(svg, "g", { opacity: 0 });
    A.el(chip, "rect", { x: sb[0] + 14, y: sb[1] + 44, width: 196, height: 32, rx: 4, fill: C.liveFill, stroke: C.live });
    A.el(chip, "circle", { cx: sb[0] + 30, cy: sb[1] + 60, r: 4.5, fill: C.live });
    A.text(chip, sb[0] + 42, sb[1] + 65, "LASER · FROM KICAD", { size: 13, fill: C.live, weight: 600, font: "label", spacing: "0.1em" });
    var toast = A.text(svg, sb[0] + 14, sb[1] + 104, "", { size: 12.5, fill: C.text2 });
    var toast2 = A.text(svg, sb[0] + 14, sb[1] + 122, "", { size: 12.5, fill: C.text2 });
    var rail = A.el(svg, "g", { opacity: 0 });
    ["Your board", "Check it", "Drill and cut out  MILL", "Etch the traces  LASER"].forEach(function (t, i) {
      A.text(rail, sb[0] + 14, sb[1] + (narrow ? 104 : 150) + i * 22 + (narrow ? 0 : 0), t, { size: 13, fill: i > 1 ? (i === 2 ? C.copperHi : C.live) : C.text });
    });
    if (narrow) A.set(rail, { transform: "translate(" + (sb[2] / 2) + ",-50)" });

    // a moving packet
    var packet = A.el(svg, "rect", { width: 26, height: 18, rx: 3, fill: C.copperHi, opacity: 0 });
    var line = A.text(svg, 16, H - 16, "", { size: narrow ? 15 : 15, fill: C.text2 });

    var D = 3.2;
    function centre(b) { return [b[0] + b[2] / 2, b[1] + b[3] / 2]; }
    function draw(t) {
      var s = A.clamp(Math.floor(t / D), 0, STAGES.length - 1);
      var p = A.clamp((t - s * D) / (D * 0.8), 0, 1);
      head.textContent = STAGES[s][1].replace(/^\d · /, "");
      line.textContent = narrow ? (STAGES[s][3] || STAGES[s][2]) : STAGES[s][2];
      frames.forEach(function (f, i) {
        var on = (i === 0 && s <= 1) || (i === 1 && (s === 0 || s === 2)) || (i === 2 && s >= 3);
        A.set(f, { stroke: on ? C.live : C.ruleHi });
      });
      A.set(bRules, { fill: s === 0 ? C.select || "#1d3550" : C.raised, stroke: s === 0 ? C.live : C.ruleStrong });
      A.set(bSend, { fill: s >= 1 && s <= 3 ? "#1d3550" : C.raised, stroke: s >= 1 && s <= 3 ? C.live : C.ruleStrong });
      method.textContent = s >= 0 && p > 0.4 || s > 0 ? "Fiber laser copper: Apply, then Ctrl+S" : "";
      A.set(json, { opacity: s === 0 ? p : 1 });
      A.set(warn, { opacity: s === 1 ? Math.min(1, p * 3) : 0 });
      A.set(okline, { opacity: s === 1 && p > 0.5 ? 1 : 0 });
      files.forEach(function (f, i) {
        var shown = s > 2 || (s === 2 && p * FILES.length > i);
        A.set(f, { opacity: shown ? 1 : 0, fill: s === 2 ? C.text : C.text2 });
      });
      // packet from folder to SRM-CAM
      if (s === 3) {
        var a = centre(box[1]), b = centre(box[2]), e = A.ease(p);
        A.set(packet, { x: A.lerp(a[0], b[0], e) - 13, y: A.lerp(a[1], b[1], e) - 9, opacity: 1 });
      } else A.set(packet, { opacity: 0 });
      A.set(chip, { opacity: s >= 4 ? 1 : 0 });
      A.set(rail, { opacity: s >= 4 ? 1 : 0 });
      toast.textContent = s === 3 ? "Running? It loads there." : s >= 4 ? (narrow ? "" : "Laser copper (mill drills and") : "";
      toast2.textContent = s === 3 ? "Not running? It starts." : s >= 4 ? (narrow ? "" : "cuts out), as set in KiCad.") : "";
    }
    var now = 0, t0 = 0, END = STAGES.length * D;
    var play = A.loop(host, function (t) { now = t; draw(Math.min(t - t0, END - 0.001)); }, END - 0.001);
    var row = A.controls(host), quiet = false;
    var seg = A.segmented(row, STAGES.map(function (x) { return [x[0], x[1].split(" · ")[0]]; }), "rules", function (v) {
      if (quiet) return;
      for (var i = 0; i < STAGES.length; i++) if (STAGES[i][0] === v) { if (A.reduced) { draw((i + 1) * D - 0.001); } else { t0 = now - i * D; play.restart(); t0 = -i * D; } }
    });
    A.button(row, "Play again", function () { if (A.reduced) draw(0); else { t0 = 0; play.restart(); } }, "primary");
  });
})();
