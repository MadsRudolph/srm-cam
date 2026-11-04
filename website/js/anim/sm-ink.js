/* Applying the mask: a bead of Mechanic ink across one end, then the squeegee, through a
   silkscreen frame or over a transparency sheet. The bead runs out as the coat is laid,
   and the channels fill behind the blade: one of them traps a bubble, which is the thing
   to look for. A cross-section, not to scale. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C, B = window.SMBoard;

  A.define("sm-ink", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = 350;
    var svg = A.stage(host, W, H, "A squeegee pulling a bead of solder mask ink across the board, through a silkscreen frame or over a sheet");
    var L = 50, R = W - 50, TOP = 236, CU = 9, FR = 34;
    var N = narrow ? 5 : 8, CHW = 14, CHS = [];
    for (var i = 0; i < N; i++) CHS.push(L + (R - L) * (i + 0.8) / (N + 0.6));
    var BUB = CHS[Math.floor(N * 0.6)];                      // the channel that traps a bubble

    A.text(svg, L, 30, "CROSS-SECTION · NOT TO SCALE", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: L, y: TOP + CU, width: R - L, height: FR, fill: C.fr4 });
    A.el(svg, "rect", { x: L, y: TOP, width: R - L, height: CU, fill: C.copper });
    CHS.forEach(function (x) { A.el(svg, "rect", { x: x, y: TOP, width: CHW, height: CU + 3, fill: C.fr4Hi }); });
    A.text(svg, R - 6, TOP + CU + 24, narrow ? "the milled board" : "the milled board, copper side up", { size: 15, weight: 600, anchor: "end", fill: "#2a2612" });

    var coat = A.el(svg, "rect", { x: L, y: TOP - 7, height: 7, fill: B.INK_WET });
    var fills = CHS.map(function (x) { return A.el(svg, "rect", { x: x, y: TOP, width: CHW, height: 0, fill: B.INK_WET }); });
    var bubble = A.el(svg, "circle", { cx: BUB + CHW / 2, cy: TOP + 6, r: 5, fill: C.sunk, stroke: C.text, "stroke-width": 1.2, opacity: 0 });
    var ring = A.el(svg, "circle", { cx: BUB + CHW / 2, cy: TOP + 6, r: 19, fill: "none", stroke: C.caution, "stroke-width": 2.5, opacity: 0 });
    var ringT = A.text(svg, BUB + CHW / 2, TOP - 66, "a bubble in a channel", { size: 16, weight: 600, anchor: "middle", fill: C.caution, opacity: 0 });
    var bead = A.el(svg, "ellipse", { fill: B.INK_WET });

    // the frame, or the sheet
    var frame = A.el(svg, "g", {});
    A.el(frame, "rect", { x: L - 26, y: TOP - 66, width: 20, height: 40, fill: C.raised, stroke: C.ruleStrong });
    A.el(frame, "rect", { x: R + 6, y: TOP - 66, width: 20, height: 40, fill: C.raised, stroke: C.ruleStrong });
    var mesh = A.el(frame, "polyline", { fill: "none", stroke: C.text2, "stroke-width": 1.5, "stroke-dasharray": "2 3" });
    var frameT = A.text(frame, L - 20, TOP - 76, "silkscreen frame", { size: 15, fill: C.text2 });
    var sheet = A.el(svg, "g", {});
    var film = A.el(sheet, "polyline", { fill: "none", stroke: C.steel, "stroke-width": 2, opacity: 0.75 });
    A.text(sheet, L, TOP - 62, "transparency sheet", { size: 15, fill: C.text2 });

    var blade = A.el(svg, "g", {});
    A.el(blade, "polygon", { points: "-8,0 8,0 26,-104 8,-104", fill: C.steelDim, stroke: C.steel });
    A.text(blade, 2, -86, "squeegee", { size: 15, anchor: "end", fill: C.text2 });

    var verdict = A.text(svg, L, H - 20, "", { size: narrow ? 16 : 18, weight: 700, fill: C.caution });
    var mode = "frame";

    function draw(t) {
      var k = A.clamp(t / 3.6, 0, 1), x = A.lerp(L + 30, R - 20, k);
      var y = mode === "frame" ? TOP - 7 : TOP - 9;
      A.set(blade, { transform: "translate(" + x + "," + y + ")" });
      A.set(coat, { width: Math.max(x - L, 0) });
      fills.forEach(function (f, i) { f.setAttribute("height", x > CHS[i] + CHW ? CU + 3 : 0); });
      var size = A.lerp(1, 0.32, k);
      A.set(bead, { cx: x + 19, cy: TOP - 7 - 11 * size, rx: 24 * size, ry: 13 * size });
      var passed = x > BUB + CHW;
      bubble.setAttribute("opacity", passed ? 1 : 0);
      var show = A.clamp((t - 3.8) / 0.4, 0, 1);
      ring.setAttribute("opacity", show);
      ringT.setAttribute("opacity", show);

      frame.setAttribute("opacity", mode === "frame" ? 1 : 0);
      sheet.setAttribute("opacity", mode === "sheet" ? 1 : 0);
      // the mesh is held clear of the board, and the blade presses it down to the ink
      A.set(mesh, { points: [[L - 6, TOP - 46], [x - 40, TOP - 46], [x, TOP - 7], [x + 40, TOP - 46], [R + 6, TOP - 46]].map(String).join(" ") });
      A.set(film, { points: [[L - 8, TOP - 8], [x, TOP - 8], [x + 70, TOP - 50], [R + 8, TOP - 56]].map(String).join(" ") });
      verdict.textContent = t < 3.8 ? "" : narrow ? "Look along the channels: work bubbles out now."
        : "Look along the channels before you cure: work a bubble out now.";
    }

    var play = B.player(host, 4.4, draw);
    var row = A.controls(host);
    A.segmented(row, [["frame", "Silkscreen frame"], ["sheet", "Transparency sheet"]], "frame", function (v) {
      mode = v;
      if (A.reduced) draw(4.4);
      play.replay();
    });
    A.button(row, "Play again", function () { play.replay(); }, "primary");
    var st = A.status(row);
    st.textContent = "sphawes finds the frame the more consistent of the two. Either way: an even coat, thin enough to see the pads through.";
  });
})();
