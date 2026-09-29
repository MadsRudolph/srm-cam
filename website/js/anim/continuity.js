/* The finished board, checked with a multimeter: continuity where you want it, and
   none where you don't. One strand of copper the mill didn't clear bridges two nets
   that should be separate; the meter finds it, a scrape fixes it. Schematic. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  var PADS = [
    { id: "A", net: "GND", x: 100, y: 110 }, { id: "B", net: "GND", x: 340, y: 110 },
    { id: "C", net: "SIG", x: 160, y: 170 }, { id: "D", net: "SIG", x: 420, y: 170 },
    { id: "E", net: "VIN", x: 100, y: 300 }, { id: "F", net: "VIN", x: 340, y: 250 },
    { id: "G", net: "OUT", x: 490, y: 110 }, { id: "H", net: "OUT", x: 490, y: 300 }
  ];
  var TRACKS = [["GND", "M100 110 H340"], ["SIG", "M160 170 H420"], ["VIN", "M100 300 H250 L300 250 H340"], ["OUT", "M490 110 V300"]];

  A.define("continuity", function (host) {
    var W = 880, H = 400;
    var s = A.stage(host, W, H, "A finished board and a multimeter: click two pads to measure between them");
    var CH = "#3a3322";
    A.text(s, 30, 30, "SCHEMATIC · click two pads", { size: 15, weight: 600, fill: C.text3, font: "label" });
    // board: copper everywhere, channels cut around tracks and pads
    A.el(s, "rect", { x: 40, y: 50, width: 520, height: 320, rx: 12, fill: C.copper });
    var ch = A.el(s, "g", { fill: "none", stroke: CH, "stroke-linecap": "round", "stroke-linejoin": "round" });
    TRACKS.forEach(function (t) { A.el(ch, "path", { d: t[1], "stroke-width": 30 }); });
    PADS.forEach(function (p) { A.el(ch, "circle", { cx: p.x, cy: p.y, r: 20, fill: CH, stroke: "none" }); });
    var cu = A.el(s, "g", { fill: "none", stroke: C.copperHi, "stroke-linecap": "round", "stroke-linejoin": "round" });
    TRACKS.forEach(function (t) { A.el(cu, "path", { d: t[1], "stroke-width": 10 }); });
    // the strand: a hair of copper across the channel between GND and SIG
    var strand = A.el(s, "path", { d: "M244 114 q9 14 -3 22 q-7 6 4 30", fill: "none", stroke: C.copperHi, "stroke-width": 2.2 });
    var ringStrand = A.el(s, "circle", { cx: 246, cy: 140, r: 26, fill: "none", stroke: C.danger, "stroke-width": 3, opacity: 0 });
    var padEls = {};
    PADS.forEach(function (p) {
      var g = A.el(s, "g", { tabindex: 0, role: "button", "aria-label": "Pad " + p.id + ", net " + p.net });
      g.style.cursor = "pointer";
      A.el(g, "circle", { cx: p.x, cy: p.y, r: 30, fill: "transparent" });   // a finger-sized target
      var c = A.el(g, "circle", { cx: p.x, cy: p.y, r: 13, fill: C.copperHi, stroke: C.copperHi, "stroke-width": 3 });
      A.el(g, "circle", { cx: p.x, cy: p.y, r: 4, fill: C.sunk });
      A.text(g, p.x, p.y - 22, p.id, { anchor: "middle", size: 15, weight: 700, fill: C.ink });
      g.addEventListener("click", function () { probe(p); });
      g.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { probe(p); e.preventDefault(); } });
      padEls[p.id] = c;
    });
    // the meter
    A.el(s, "rect", { x: 610, y: 60, width: 230, height: 300, rx: 22, fill: "#e3b21c", stroke: "#8a6a0c", "stroke-width": 3 });
    A.el(s, "rect", { x: 632, y: 84, width: 186, height: 96, rx: 6, fill: "#aeb8a2", stroke: "#56604c", "stroke-width": 2 });
    var lcd = A.text(s, 810, 150, "----", { anchor: "end", size: 46, weight: 600, fill: "#1b2016", font: "mono" });
    var unit = A.text(s, 642, 108, "", { size: 16, fill: "#1b2016", font: "mono" });
    var beep = A.text(s, 725, 222, "", { anchor: "middle", size: 22, weight: 700, fill: "#1b2016" });
    A.el(s, "circle", { cx: 725, cy: 290, r: 36, fill: "#2b2b2b", stroke: "#111" });
    A.el(s, "line", { x1: 725, y1: 290, x2: 700, y2: 266, stroke: "#ddd", "stroke-width": 5, "stroke-linecap": "round" });
    A.text(s, 690, 262, "·))", { anchor: "end", size: 15, fill: "#1b2016", weight: 700 });
    // leads
    var leadR = A.el(s, "path", { fill: "none", stroke: C.danger, "stroke-width": 4, opacity: 0 });
    var leadB = A.el(s, "path", { fill: "none", stroke: "#111", "stroke-width": 4, opacity: 0 });
    var tipR = A.el(s, "circle", { r: 7, fill: C.danger, opacity: 0 });
    var tipB = A.el(s, "circle", { r: 7, fill: "#111", stroke: "#666", opacity: 0 });

    var row = A.controls(host);
    var bScrape = A.button(row, "Scrape the strand", function () {
      strandOn = false; strand.setAttribute("opacity", 0); ringStrand.setAttribute("opacity", 0);
      bScrape.disabled = true; measure();
      if (!pr || !pb) say("Scraped away with a knife. Measure again.", "");
    });
    A.button(row, "Inspect closely", function () {
      ringStrand.setAttribute("opacity", strandOn ? 1 : 0);
      say(strandOn ? "There: a hair of copper the mill didn't clear, across the channel between GND and SIG." : "Every channel is clean.", strandOn ? "caution" : "ok");
    });
    A.button(row, "Reset", reset);
    var st = A.status(row);
    function say(m, k) { st.textContent = m; st.className = "anim-status" + (k ? " " + k : ""); }

    var pr = null, pb = null, next = 0, strandOn = true;
    function probe(p) {
      if (next === 0) pr = p; else pb = p;
      next = 1 - next;
      measure();
    }
    function joined(a, b) {
      if (a.net === b.net) return true;
      var pair = [a.net, b.net].sort().join("+");
      return strandOn && pair === "GND+SIG";
    }
    function lead(path, tip, p, ox) {
      path.setAttribute("opacity", p ? 1 : 0);
      tip.setAttribute("opacity", p ? 1 : 0);
      if (!p) return;
      A.set(tip, { cx: p.x, cy: p.y });
      path.setAttribute("d", "M" + ox + " 360 C " + ox + " 395, " + (p.x + 40) + " 400, " + p.x + " " + p.y);
    }
    function measure() {
      lead(leadR, tipR, pr, 700);
      lead(leadB, tipB, pb, 750);
      PADS.forEach(function (p) { padEls[p.id].setAttribute("stroke", p === pr ? C.danger : p === pb ? "#111" : C.copperHi); });
      if (!pr || !pb) { lcd.textContent = "OL"; unit.textContent = "Ω"; beep.textContent = ""; say("Now touch a second pad."); return; }
      if (pr === pb) { lcd.textContent = "0.0"; unit.textContent = "Ω"; beep.textContent = "beep"; say("Both probes on one pad: that only checks the meter."); return; }
      var on = joined(pr, pb);
      lcd.textContent = on ? "0.2" : "OL"; unit.textContent = "Ω"; beep.textContent = on ? "beep" : "";
      var nm = pr.id + " (" + pr.net + ") to " + pb.id + " (" + pb.net + ")";
      if (pr.net === pb.net) say(nm + ": continuity, as it should be. Same net.", "ok");
      else if (on) say(nm + ": it beeps, but these are separate nets. A short: inspect the channel between them.", "bad");
      else say(nm + ": OL, no continuity. Good: separate nets stay separate.", "ok");
    }
    function reset() {
      pr = pb = null; next = 0; strandOn = true;
      strand.setAttribute("opacity", 1); ringStrand.setAttribute("opacity", 0); bScrape.disabled = false;
      measure();
      say("Click two pads. Try A to B, then B to C.");
    }
    reset();
  });
})();
