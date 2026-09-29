/* Watch it cut: the run in the order we prefer. The dry run traces the outline with
   the spindle off; the drill plunges the small holes and mills the big ones as circles;
   the isolation traces cut channels in the copper around every track and pad; the
   cut-out goes last, leaving four tabs. A schematic board, not to scale. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  var STEPS = [
    ["Dry run", "Step 0 · dry run: spindle off, bit 5 mm up, tracing the outline. Is the job on the copper?"],
    ["Drill", "Step 1 · drill: every hole with the same 0.8 mm bit; the big ones milled as circles."],
    ["Traces", "Step 2 · isolation traces: a channel through the copper around every track and pad."],
    ["Cut-out", "Step 3 · cut-out, always last: it frees the board, held in the sheet by four tabs."]
  ];

  A.define("cutting", function (host) {
    var W = 880, H = 420;
    var s = A.stage(host, W, H, "Playback of a milling job: dry run, drill, isolation traces and cut-out");
    var CH = "#3a3322";                    // the FR-4 a channel exposes
    var BIT = 7;                           // the bit's width in this drawing

    A.text(s, 20, 30, "SCHEMATIC · not to scale", { size: 15, weight: 600, fill: C.text3, font: "label" });
    // the copper sheet
    A.el(s, "rect", { x: 190, y: 40, width: 500, height: 340, fill: C.copper });
    var channels = A.el(s, "g", { fill: "none", stroke: CH, "stroke-linecap": "round", "stroke-linejoin": "round" });
    var copper = A.el(s, "g", { fill: C.copperHi, stroke: C.copperHi, "stroke-linecap": "round", "stroke-linejoin": "round" });
    var holes = A.el(s, "g");
    var cut = A.el(s, "g", { fill: "none", stroke: C.sunk, "stroke-width": BIT });
    var dry = A.el(s, "g", { fill: "none", stroke: C.live, "stroke-width": 2, "stroke-dasharray": "6 6" });
    var head = A.el(s, "g");

    var small = [[390, 150], [390, 175], [390, 200], [390, 225], [470, 150], [470, 175], [470, 200], [470, 225], [540, 160], [540, 240]];
    var big = [[290, 110], [290, 290], [590, 110], [590, 290]];
    var tracks = [
      "M290 110 H350 L390 150", "M290 290 H350 L390 225", "M470 150 H515 L540 160",
      "M470 225 H515 L540 240", "M540 160 L590 110", "M540 240 L590 290", "M390 175 H430 V200 H470"
    ];

    var segs = [];                          // {step, len, fn(p), a:[x,y] start, pathEl}
    function pathSeg(step, parent, d, attrs, headOn) {
      var p = A.el(parent, "path", Object.assign({ d: d }, attrs || {}));
      var L = p.getTotalLength();
      p.setAttribute("stroke-dasharray", L + " " + L);
      p.setAttribute("stroke-dashoffset", L);
      segs.push({ step: step, len: L, el: p, kind: "path" });
      return p;
    }
    // 0: dry run, around the outline
    pathSeg(0, dry, "M240 60 H640 V340 H240 Z");
    // 1: drill
    small.forEach(function (h) {
      var c = A.el(holes, "circle", { cx: h[0], cy: h[1], r: 4, fill: C.sunk, opacity: 0 });
      segs.push({ step: 1, len: 40, el: c, kind: "plunge", at: h });
    });
    big.forEach(function (h) {
      var core = A.el(holes, "circle", { cx: h[0], cy: h[1], r: 10, fill: C.sunk, opacity: 0 });
      var ring = pathSeg(1, holes, "M" + (h[0] + 10 - BIT / 2) + " " + h[1] + " a" + (10 - BIT / 2) + " " + (10 - BIT / 2) +
        " 0 1 1 -" + (2 * (10 - BIT / 2)) + " 0 a" + (10 - BIT / 2) + " " + (10 - BIT / 2) + " 0 1 1 " + (2 * (10 - BIT / 2)) + " 0",
        { fill: "none", stroke: C.sunk, "stroke-width": BIT });
      segs[segs.length - 1].after = core;
    });
    // copper that stays: tracks and pads (drawn before the channels are revealed, above them)
    tracks.forEach(function (d) { A.el(copper, "path", { d: d, fill: "none", "stroke-width": 8 }); });
    small.forEach(function (h) { A.el(copper, "circle", { cx: h[0], cy: h[1], r: 9, stroke: "none" }); });
    big.forEach(function (h) { A.el(copper, "circle", { cx: h[0], cy: h[1], r: 16, stroke: "none" }); });
    s.insertBefore(holes, cut);             // holes above the copper
    // 2: isolation traces: one channel around each track, one around each pad
    tracks.forEach(function (d) { pathSeg(2, channels, d, { "stroke-width": 8 + 2 * BIT }); });
    small.forEach(function (h) {
      var r = 9 + BIT / 2;
      pathSeg(2, channels, "M" + (h[0] + r) + " " + h[1] + " a" + r + " " + r + " 0 1 1 -" + 2 * r + " 0 a" + r + " " + r + " 0 1 1 " + 2 * r + " 0", { "stroke-width": BIT });
    });
    big.forEach(function (h) {
      var r = 16 + BIT / 2;
      pathSeg(2, channels, "M" + (h[0] + r) + " " + h[1] + " a" + r + " " + r + " 0 1 1 -" + 2 * r + " 0 a" + r + " " + r + " 0 1 1 " + 2 * r + " 0", { "stroke-width": BIT });
    });
    // 3: cut-out, four passes between four tabs
    ["M448 60 H640 V192", "M640 208 V340 H448", "M432 340 H240 V208", "M240 192 V60 H432"].forEach(function (d) {
      pathSeg(3, cut, d, { "stroke-linecap": "butt" });
    });
    var tabs = A.el(s, "g", { opacity: 0 });
    [[440, 60], [640, 200], [440, 340], [240, 200]].forEach(function (t) {
      A.el(tabs, "circle", { cx: t[0], cy: t[1], r: 11, fill: "none", stroke: C.caution, "stroke-width": 2 });
    });
    A.text(tabs, 440, 34, "tab", { anchor: "middle", size: 15, fill: C.caution });
    s.insertBefore(tabs, head);

    // travel moves between segments, so the head never teleports
    function startOf(g) {
      if (g.kind === "plunge") return { x: g.at[0], y: g.at[1] };
      return g.el.getPointAtLength(0);
    }
    function endOf(g) {
      if (g.kind === "plunge") return { x: g.at[0], y: g.at[1] };
      return g.el.getPointAtLength(g.len);
    }
    var timeline = [], tot = 0, stepStart = [0, 0, 0, 0];
    var prev = { x: 120, y: 60 };
    var cur = -1;
    segs.forEach(function (g) {
      if (g.step !== cur) { cur = g.step; stepStart[cur] = tot; }
      var a = startOf(g), dd = Math.hypot(a.x - prev.x, a.y - prev.y);
      timeline.push({ travel: true, from: prev, to: a, len: dd / 3, step: g.step, t0: tot });
      tot += dd / 3;
      timeline.push({ seg: g, len: g.len, step: g.step, t0: tot });
      tot += g.len;
      prev = endOf(g);
    });
    var TOTAL = tot;

    // the head: a ring (spindle off, up) or a filled bit (cutting)
    var ring = A.el(head, "circle", { r: 9, fill: "none", stroke: C.live, "stroke-width": 3 });
    var bit = A.el(head, "circle", { r: BIT / 2 + 1, fill: C.steel, stroke: C.ink, "stroke-width": 1 });
    var hl = A.text(head, 0, 0, "", { size: 15, fill: C.live, weight: 600 });

    // step chips across the top
    var chips = STEPS.map(function (st, i) {
      var x = 250 + i * 150;
      var g = A.el(s, "g");
      var r = A.el(g, "rect", { x: x - 66, y: 392, width: 132, height: 24, rx: 12, fill: C.panel, stroke: C.ruleHi });
      var t = A.text(g, x, 409, i + " · " + st[0], { anchor: "middle", size: 15, fill: C.text2 });
      return { r: r, t: t };
    });

    var pos = 0, playing = true, speed = 1;
    var row = A.controls(host);
    var bPlay = A.button(row, "Pause", function () {
      playing = !playing;
      if (playing && pos >= TOTAL) pos = 0;
      bPlay.textContent = playing ? "Pause" : "Play";
    });
    A.button(row, "Restart", function () { pos = 0; playing = true; bPlay.textContent = "Pause"; render(); });
    var jumping = true;                    // the switch reports its first value while it is built
    var seg = A.segmented(row, [[0, "0 Dry run"], [1, "1 Drill"], [2, "2 Traces"], [3, "3 Cut-out"]], 0, function (v) {
      if (jumping) return;
      pos = stepStart[v]; render();
    });
    A.segmented(row, [[1, "1×"], [2, "2×"], [4, "4×"]], 1, function (v) { speed = v; });
    jumping = false;
    var st = A.status(row);

    var shownStep = -1;
    function render() {
      var hx = 120, hy = 60, step = 0, active = null;
      timeline.forEach(function (e) {
        var p = A.clamp((pos - e.t0) / (e.len || 1), 0, 1);
        if (e.travel) {
          if (pos >= e.t0 && pos < e.t0 + e.len) { hx = A.lerp(e.from.x, e.to.x, p); hy = A.lerp(e.from.y, e.to.y, p); step = e.step; active = e; }
          return;
        }
        var g = e.seg;
        if (g.kind === "plunge") g.el.setAttribute("opacity", p > 0.6 ? 1 : 0);
        else g.el.setAttribute("stroke-dashoffset", g.len * (1 - p));
        if (g.after) g.after.setAttribute("opacity", p >= 1 ? 1 : 0);
        if (pos >= e.t0 && pos < e.t0 + e.len) {
          var q = g.kind === "plunge" ? { x: g.at[0], y: g.at[1] } : g.el.getPointAtLength(g.len * p);
          hx = q.x; hy = q.y; step = e.step; active = e;
        }
      });
      if (pos >= TOTAL) { var q = endOf(segs[segs.length - 1]); hx = q.x; hy = q.y; step = 3; }
      tabs.setAttribute("opacity", pos >= TOTAL ? 1 : 0);
      dry.setAttribute("opacity", step === 0 && pos < TOTAL ? 1 : 0.3);
      var off = step === 0;
      ring.setAttribute("opacity", off ? 1 : 0);
      bit.setAttribute("opacity", off ? 0 : 1);
      A.set(ring, { cx: hx, cy: hy });
      A.set(bit, { cx: hx, cy: hy });
      A.set(hl, { x: hx + 14, y: hy - 12 });
      hl.textContent = off ? "spindle off · 5 mm up" : "";
      chips.forEach(function (c, i) {
        c.r.setAttribute("stroke", i === step ? C.copperHi : C.ruleHi);
        c.r.setAttribute("fill", i === step ? C.copperFill : C.panel);
        c.t.setAttribute("fill", i === step ? C.text : C.text2);
      });
      if (step !== shownStep) {
        shownStep = step;
        jumping = true; seg.set(step); jumping = false;
      }
      st.textContent = pos >= TOTAL ? "Done. The board sits in the sheet on its four tabs: snap them, sand, then inspect." : STEPS[step][1];
    }

    if (A.reduced) { pos = TOTAL; playing = false; bPlay.textContent = "Play"; render(); }
    A.loop(host, function (t, dt) {
      if (playing && pos < TOTAL) {
        pos = Math.min(TOTAL, pos + dt * 150 * speed);
        if (pos >= TOTAL) { playing = false; bPlay.textContent = "Play"; }
      }
      render();
    }, 0);
    render();
  });
})();
