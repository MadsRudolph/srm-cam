/* Essential and Full, the two tiers on the Interface menu. Flip the switch and the
   controls Full adds slide in, marked, while everything Essential has stays where it
   is: Full is a strict superset, and the exported files are byte for byte the same
   (gui2/tier.py, tests/test_gui2_tier.py). The lists are tier.ADDED_BY_FULL and
   tier.KEPT_IN_ESSENTIAL. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  // rail rows: [label, full only?]
  var RAIL = [["Set up the job", 0], ["Check before cutting", 0], ["0 Dry run", 0], ["1 Drill", 0],
    ["2 Isolation traces", 0], ["3 Cut the board out", 0], ["Level the bed", 0], ["Rework", 1]];
  // inspector rows for Isolation traces: [label, value, full only?]
  var INSP = [["Tool profile", "0.8 mm flat", 0], ["File", "…_traces.nc", 0], ["Time", "~14 min", 0],
    ["Bit diameter", "0.80 mm", 1], ["Cut depth", "0.15 mm", 1], ["Isolation passes", "1", 1],
    ["Pass overlap", "0.50", 1], ["☐ Cut gaps too narrow for the bit", "", 1]];
  var SETUP_FULL = ["Double-sided: dowels or fiducials, the flip", "Output format and mirroring", "Stream over the link (experimental)", "Machine test, save your own profiles"];

  A.define("gs-tiers", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 520 : 880, H = narrow ? 720 : 470;
    var s = A.stage(host, W, H, "The Essential and Full tiers: Full adds controls, Essential keeps the whole single-sided job");
    var fullEls = [];            // [element, appear order]
    var railX = 14, railW = narrow ? 230 : 250, top = 20;
    var inspX = narrow ? 256 : 280, inspW = narrow ? 250 : 300;
    var moreX = narrow ? 14 : 596, moreY = narrow ? 470 : top, moreW = narrow ? 492 : 270;

    function panel(x, y, w, h, title) {
      A.el(s, "rect", { x: x, y: y, width: w, height: h, rx: 6, fill: C.panel, stroke: C.ruleHi });
      A.text(s, x + 14, y + 26, title, { size: 13, fill: C.text3, weight: 700, spacing: 1 });
    }
    panel(railX, top, railW, 430, "THE RAIL");
    panel(inspX, top, inspW, 430, "ISOLATION TRACES");
    panel(moreX, moreY, moreW, narrow ? 236 : 430, "ALSO IN FULL");

    RAIL.forEach(function (r, i) {
      var y = top + 44 + i * 46, g = A.el(s, "g", {});
      A.el(g, "rect", { x: railX + 8, y: y, width: railW - 16, height: 38, rx: 3, fill: i === 4 ? "#243040" : C.panelHi, stroke: r[1] ? C.live : "none", "stroke-width": 2 });
      A.text(g, railX + 20, y + 25, r[0], { size: narrow ? 17 : 16 });
      if (r[1]) { A.text(g, railX + railW - 20, y + 25, "Full", { size: 13, anchor: "end", fill: C.live, weight: 600 }); fullEls.push([g, 0]); }
    });
    INSP.forEach(function (r, i) {
      var y = top + 44 + i * 46, g = A.el(s, "g", {});
      A.el(g, "rect", { x: inspX + 8, y: y, width: inspW - 16, height: 38, rx: 3, fill: C.panelHi, stroke: r[2] ? C.live : "none", "stroke-width": 2 });
      if (r[1]) {
        A.text(g, inspX + 20, y + 25, r[0], { size: narrow ? 15 : 15, fill: C.text2 });
        A.text(g, inspX + inspW - 20, y + 25, r[1], { size: narrow ? 15 : 15, anchor: "end", font: "mono" });
      } else {
        A.text(g, inspX + 20, y + 25, r[0], { size: narrow ? 15 : 15 });
      }
      if (r[2]) fullEls.push([g, i - 2]);
    });
    SETUP_FULL.forEach(function (t, i) {
      var y = moreY + 44 + i * (narrow ? 46 : 58), g = A.el(s, "g", {});
      A.el(g, "rect", { x: moreX + 8, y: y, width: moreW - 16, height: narrow ? 38 : 50, rx: 3, fill: C.liveFill, stroke: C.live, "stroke-width": 2 });
      var words = t.split(": ");
      if (narrow || words.length < 2) A.text(g, moreX + 20, y + (narrow ? 25 : 31), t, { size: 15 });
      else { A.text(g, moreX + 20, y + 22, words[0] + ":", { size: 15, weight: 600 }); A.text(g, moreX + 20, y + 42, words[1], { size: 14, fill: C.text2 }); }
      fullEls.push([g, 6 + i]);
    });
    var essNote = A.el(s, "g", {});
    var ny = narrow ? moreY + 70 : top + 140;
    A.text(essNote, moreX + moreW / 2, ny, "Essential: the whole", { size: 17, anchor: "middle", fill: C.text2 });
    A.text(essNote, moreX + moreW / 2, ny + 24, "single-sided job,", { size: 17, anchor: "middle", fill: C.text2 });
    A.text(essNote, moreX + moreW / 2, ny + 48, "levelling included.", { size: 17, anchor: "middle", fill: C.text2 });
    A.text(essNote, moreX + moreW / 2, ny + 90, "Same files, byte for byte.", { size: 15, anchor: "middle", fill: C.ok });

    var tier = "essential", switched = -1;
    var row = A.controls(host);
    var seg = A.segmented(row, [["essential", "Interface › Essential"], ["full", "Interface › Full"]], "essential", function (v) {
      if (v === tier) return;
      tier = v; switched = -1; ticker.restart();
      say();
    });
    var st = A.status(row);
    function say() {
      st.className = "anim-status" + (tier === "full" ? " ok" : "");
      st.textContent = tier === "full"
        ? "Full adds per-operation cutting parameters (and Cut gaps too narrow for the bit), Rework, double-sided, the output format, streaming and the machine test. Nothing moves; it only appears."
        : "Essential is the default: the whole single-sided job, including bed levelling, the dry run, the checks, hold-down screws and placing the job. In Essential the tool profile sets the cutting parameters.";
    }
    say();
    function paint(t) {
      fullEls.forEach(function (p) {
        var a = tier === "full" ? A.ease((t - 0.12 * p[1]) / 0.35) : 1 - A.ease(t / 0.25);
        p[0].setAttribute("opacity", a);
        p[0].setAttribute("transform", "translate(" + ((1 - a) * 18) + ",0)");
      });
      essNote.setAttribute("opacity", tier === "full" ? 1 - A.ease(t / 0.3) : A.ease((t - 0.2) / 0.3));
    }
    var ticker = A.loop(host, paint, 3);
    paint(3);
  });
})();
