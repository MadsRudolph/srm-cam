/* What the cutting numbers become. SRM-CAM keeps feeds in mm/s; the G-code backend
   writes them in mm/min (F = mm/s x 60, the only unit the SRM-20 takes) and depths
   in millimetres, while RML writes speeds in mm/s (VS, !VZ) and coordinates in
   0.01 mm units (backends/gcode.py, backends/srm20.py). The bit above runs a 100 mm
   channel in real time at the chosen feed. Defaults: the lab's 0.8 mm profile. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  function g(v) { var s = v.toFixed(3).replace(/0+$/, ""); return s; }   // the backend's number style: "4." "0.15"
  function secs(s) { return s >= 60 ? Math.floor(s / 60) + " min " + Math.round(s % 60) + " s" : s.toFixed(1) + " s"; }

  A.define("rf-feeds", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 560 : 380;
    var svg = A.stage(host, W, H, "What a feed and a depth become in G-code and RML");
    var L = 100, x0 = 30, x1 = W - 30, K = (x1 - x0) / L;           // 100 mm channel
    var ty = 70;

    A.text(svg, x0, 32, "A 100 mm channel, in real time", { size: 16, weight: 600, fill: C.text2, font: "label" });
    var clock = A.text(svg, x1, 32, "", { size: 16, anchor: "end", font: "mono", fill: C.text });
    A.el(svg, "rect", { x: x0 - 10, y: ty - 26, width: x1 - x0 + 20, height: 52, rx: 3, fill: C.copper });
    var chan = A.el(svg, "rect", { x: x0, y: ty - 6, width: 0, height: 12, fill: C.fr4 });
    var bit = A.el(svg, "circle", { cx: x0, cy: ty, r: 9, fill: C.steel, "fill-opacity": 0.5, stroke: C.steel, "stroke-width": 2.5 });
    for (var m = 0; m <= 100; m += 10) {
      A.el(svg, "line", { x1: x0 + m * K, y1: ty + 30, x2: x0 + m * K, y2: ty + 36, stroke: C.text3, "stroke-width": 1.5 });
      if (m % (narrow ? 50 : 20) === 0) A.text(svg, x0 + m * K, ty + 54, m + " mm", { size: 15, anchor: "middle", fill: C.text3 });
    }

    // the two formats
    var by = narrow ? 150 : 150, bw = narrow ? W - 60 : (W - 80) / 2, bh = narrow ? 170 : 190;
    function box(x, y, title, sub) {
      A.el(svg, "rect", { x: x, y: y, width: bw, height: bh, rx: 3, fill: C.panel, stroke: C.ruleHi });
      A.text(svg, x + 16, y + 28, title, { size: 16, weight: 700, fill: C.text, font: "label" });
      A.text(svg, x + 16, y + 50, sub, { size: 15, fill: C.text3 });
      return { x: x + 16, y: y + 86 };
    }
    var gb = box(x0, by, "G-code (.nc)", "mm · feed in mm/min");
    var rb = box(narrow ? x0 : x0 + bw + 20, narrow ? by + bh + 16 : by, "RML (.rml)", "0.01 mm units · speed in mm/s");
    var FS = narrow ? 17 : 18;
    function codeLine(p, dy) { return A.text(svg, p.x, p.y + dy, "", { size: FS, font: "mono", fill: C.text }); }
    var gl1 = codeLine(gb, 0), gl2 = codeLine(gb, 32), gn = A.text(svg, gb.x, gb.y + 70, "", { size: 15, fill: C.text2 });
    var rl1 = codeLine(rb, 0), rl2 = codeLine(rb, 32), rn = A.text(svg, rb.x, rb.y + 70, "", { size: 15, fill: C.text2 });

    function tsp(parent, parts) {
      while (parent.firstChild) parent.removeChild(parent.firstChild);
      parts.forEach(function (p) { A.el(parent, "tspan", { fill: p[1] || C.text }, p[0]); });
    }

    var feed = 4.0, plunge = 1.0, depth = 0.15;
    var row = A.controls(host);
    A.slider(row, "XY feed", 0.5, 8, 0.5, feed, function (v) { feed = v; show(); }, function (v) { return v.toFixed(1) + " mm/s"; });
    A.slider(row, "Plunge", 0.25, 2, 0.25, plunge, function (v) { plunge = v; show(); }, function (v) { return v.toFixed(2) + " mm/s"; });
    A.slider(row, "Cut depth", 0.05, 0.3, 0.01, depth, function (v) { depth = v; show(); }, function (v) { return v.toFixed(2) + " mm"; });
    var st = A.status(row);

    function show() {
      if (!st) return;                          // the sliders fire once while they are built
      tsp(gl1, [["G1 X30. Y20. Z-" + g(depth) + " ", C.text], ["F" + g(plunge * 60), C.caution]]);
      tsp(gl2, [["G1 X130. Y20. ", C.text], ["F" + g(feed * 60), C.live]]);
      gn.textContent = "F" + g(feed * 60) + " = " + feed.toFixed(1) + " mm/s × 60";
      tsp(rl1, [["VS" + feed.toFixed(1) + ";", C.live], ["!VZ" + plunge.toFixed(1) + ";", C.caution]]);
      tsp(rl2, [["Z3000,2000,", C.text], [String(-Math.round(depth * 100)), C.copperHi], [";", C.text]]);
      rn.textContent = "Z " + (-Math.round(depth * 100)) + " = −" + depth.toFixed(2) + " mm × 100";
      var t = L / feed;
      st.className = "anim-status";
      st.textContent = "100 mm of channel takes " + secs(t) + " at " + feed.toFixed(1) + " mm/s. " +
        (depth < 0.1 ? "Shallower than 0.1 mm leaves little margin over the 0.035 mm foil on a sheet that is not flat." :
          depth > 0.2 ? "Deeper than needed: the foil is 0.035 mm, and a deeper cut only wears the bit." :
            "The lab's 0.15 mm: through the 0.035 mm foil with margin for an uneven surface.");
      if (A.reduced) place(1);
    }

    function place(f) {
      var x = x0 + f * L * K;
      A.set(bit, { cx: x });
      A.set(chan, { width: Math.max(0, x - x0) });
      clock.textContent = secs(f * L / feed) + " / " + secs(L / feed);
    }

    var start = null;
    A.loop(host, function (t) {
      if (start === null) start = t;
      var per = L / feed + 1.2;                 // run, then a short rest at the end
      var e = (t - start) % per;
      place(Math.min(e * feed / L, 1));
    }, 0);
    show();
    if (A.reduced) place(1);
  });
})();
