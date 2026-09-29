/* Wrong coordinate system when zeroing. VPanel lists Machine, User and G54. The
   exported files are NC code and move in G54 (backends/gcode.py writes G54 in every
   file), so Set Origin Point › Z only counts when VPanel is on G54. Machine is the
   mill's own frame and its origin cannot move; User is what Roland's RML software
   uses. Set Z anywhere else and the job runs from whatever G54 zero the last person
   left. The old zeros here are illustrative. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  A.define("ts-coords", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 460 : 400;
    var svg = A.stage(host, W, H, "Where the traces cut when Z is set in the wrong coordinate system");
    var K = narrow ? 70 : 80;                      // px per mm, vertical (schematic)
    var S = narrow ? 250 : 230;                    // copper surface y
    var bx0 = 30, bx1 = narrow ? W - 30 : 600;
    A.text(svg, 30, 32, "SIDE VIEW · depths to scale, the old zero is illustrative", { size: 15, fill: C.text3, font: "label", weight: 600 });
    A.el(svg, "rect", { x: bx0, y: S + 1.6 * K, width: bx1 - bx0, height: H - (S + 1.6 * K) - (narrow ? 110 : 30), fill: C.board });
    A.el(svg, "rect", { x: bx0, y: S, width: bx1 - bx0, height: 1.6 * K, fill: C.fr4 });
    var foil = A.el(svg, "rect", { x: bx0, y: S - 5, width: bx1 - bx0, height: 5, fill: C.copperHi });
    A.text(svg, bx1 - 10, S + 1.6 * K - 12, "FR-4 1.6 mm", { size: 15, anchor: "end", fill: C.ink, weight: 600 });
    A.text(svg, bx1 - 10, S + 1.6 * K + 24, "spoilboard", { size: 15, anchor: "end", fill: "#d9c9a8" });

    var cut = A.el(svg, "g", {});
    var zeroG = A.el(svg, "g", {});
    var zLine = A.el(zeroG, "line", { x1: bx0 - 10, x2: bx1 + 10, "stroke-width": 2.5, "stroke-dasharray": "8 6" });
    var zLab = A.text(zeroG, bx0, 0, "", { size: 16, weight: 700 });
    var head = A.el(svg, "g", {});
    A.el(head, "rect", { x: -26, y: -150, width: 52, height: 92, fill: "#5b616b" });
    A.el(head, "rect", { x: -16, y: -58, width: 32, height: 22, fill: "#9aa0a8" });
    A.el(head, "rect", { x: -5, y: -36, width: 10, height: 36, fill: C.steel });

    // right-hand panel (below on a phone)
    var px = narrow ? 30 : 630, py = narrow ? H - 100 : 60, pw = narrow ? W - 60 : 220;
    A.el(svg, "rect", { x: px, y: py, width: pw, height: narrow ? 84 : 290, rx: 3, fill: C.panel, stroke: C.ruleHi });
    A.text(svg, px + 14, py + 26, "VPANEL", { size: 15, fill: C.text3, font: "label", weight: 600 });
    var sysBox = A.el(svg, "rect", { x: px + 14, y: py + 38, width: pw - 28, height: 32, rx: 2, fill: "#ececec" });
    var sysTxt = A.text(svg, px + 24, py + 60, "", { size: 16, fill: "#141414" });
    var g54Txt = narrow ? null : A.text(svg, px + 14, py + 110, "", { size: 16, fill: C.text, font: "mono" });
    var g54Sub = narrow ? null : A.text(svg, px + 14, py + 134, "", { size: 15, fill: C.text2 });

    var OLD = { above: 2.0, below: -0.6 };        // mm: where the last user's G54 Z zero sits vs this copper
    var sys = "Machine", old = "above", g54 = OLD.above, ran = 0, running = false, t0 = 0;
    var row = A.controls(host);
    A.segmented(row, [["Machine", "Machine"], ["User", "User"], ["G54", "G54"]], sys, function (v) { sys = v; if (st) reset(); });
    A.button(row, "Set Origin Point › Z", function () { setZ(); });
    var runBtn = A.button(row, "Run the traces", function () { run(); }, "primary");
    A.segmented(row, [["above", "Old zero: 2 mm up"], ["below", "Old zero: 0.6 mm in"]], old, function (v) { old = v; if (st) reset(); });
    var st = A.status(row);

    function yOf(z) { return S - z * K; }
    function say(k, m) { if (!st) return; st.className = "anim-status" + (k ? " " + k : ""); st.textContent = m; }

    function drawZero() {
      var ok = Math.abs(g54) < 1e-9;
      A.set(zLine, { y1: yOf(g54), y2: yOf(g54), stroke: ok ? C.ok : C.caution });
      A.set(zLab, { y: yOf(g54) - 10, fill: ok ? C.ok : C.caution });
      zLab.textContent = ok ? "G54 Z 0 = this copper" : "G54 Z 0: the last user's";
      sysTxt.textContent = sys === "Machine" ? "Machine Coord." : sys === "User" ? "User Coord." : "G54";
      if (g54Txt) {
        g54Txt.textContent = "G54 zero: " + (ok ? "on the copper" : (g54 > 0 ? "+" : "") + g54.toFixed(1) + " mm");
        g54Sub.textContent = "the files move in G54";
      }
    }

    function headAt(x, z) { A.set(head, { transform: "translate(" + x + "," + yOf(z) + ")" }); }

    function reset() {
      g54 = OLD[old]; ran = 0; running = false;
      while (cut.firstChild) cut.removeChild(cut.firstChild);
      drawZero();
      headAt(bx0 + 60, 0.0);
      say("", sys === "G54" ? "VPanel is on G54. Lower Z until Touch, then Set Origin Point › Z." :
        "VPanel is on " + sys + ". Try setting Z here, then run the traces.");
    }

    function setZ() {
      while (cut.firstChild) cut.removeChild(cut.firstChild);
      if (sys === "Machine") {
        say("bad", "Nothing was set: Machine is the mill's own frame, and its origin can't be moved. Switch VPanel to G54.");
      } else if (sys === "User") {
        say("caution", "The User origin moved, but the files ignore it: they move in G54, which still has the last user's zero. Switch to G54.");
      } else {
        g54 = 0;
        say("ok", "G54 Z 0 is now this copper. The files will cut 0.15 mm below it.");
      }
      drawZero();
    }

    function run() {
      while (cut.firstChild) cut.removeChild(cut.firstChild);
      running = true; t0 = null;
      if (A.reduced) { step(99); }            // no motion: show where it ends
    }

    function finish() {
      var z = g54 - 0.15;
      if (z > 0.001) say("bad", "The bit cut " + z.toFixed(2) + " mm above the copper: air. The job ran and the board is untouched.");
      else if (z < -0.2) say("bad", "The bit went " + (-z).toFixed(2) + " mm deep instead of 0.15: through the foil and into the FR-4, a wide, deep channel, and a strained 0.8 mm bit.");
      else say("ok", "A clean 0.15 mm channel through the 0.035 mm foil: Z was set on G54.");
    }

    function step(e) {
      var z = g54 - 0.15, xa = bx0 + 60, xb = bx1 - 60;
      if (e < 0.8) { headAt(xa, A.lerp(3.0, z, A.ease(e / 0.8))); return; }
      var f = Math.min((e - 0.8) / 2.2, 1), x = A.lerp(xa, xb, f);
      headAt(x, z);
      while (cut.firstChild) cut.removeChild(cut.firstChild);
      if (z < 0) A.el(cut, "rect", { x: xa - 5, y: S - 5, width: x - xa + 10, height: (-z) * K + 5, fill: C.sunk });
      else A.el(cut, "line", { x1: xa, x2: x, y1: yOf(z), y2: yOf(z), stroke: C.live, "stroke-width": 2, "stroke-dasharray": "3 5" });
      if (f >= 1) { running = false; finish(); }
    }

    A.loop(host, function (t) {
      if (!running) return;
      if (t0 === null) t0 = t;
      step(t - t0);
    }, 0);
    reset();
  });
})();
