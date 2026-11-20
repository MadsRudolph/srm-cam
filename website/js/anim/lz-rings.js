/* How the laser etches the traces: a close-up of a real-sized piece of board, a trace
   and pad and a second trace in a ground pour, with a mounting hole in the pour and the
   board's edge along the bottom. Three ways to clear the copper:

   - Concentric passes (the default): rings traced round every copper edge, 6 of them,
     0.04 mm kerf at 285 lines/cm, so about a 0.22 mm band (engine/xtool.py,
     DEFAULT_TRACE_OFFSETS and DEFAULT_TRACE_KERF). Rings from the trace and from the pour
     meet in the 0.25 mm gap, so the gap is cleared.
   - Moat hatch: the same band, cross-hatched.
   - Full rubout: every bare millimetre of the board, in scanlines across the whole board,
     like XCS. Its path grows with the board's area, the rings' with its edges.

   Auto-skip (needless_trenches): the ring round a mounting hole's clearance in a pour
   isolates nothing, pour on one side and bare stock copper on the other, so it is left
   out; traces and pads always keep theirs. The board's edge is never etched as a trace.

   Drawn to scale, except the hatch and scan lines, which are drawn about three times
   sparser than the laser runs them so they can be seen. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  // the recipe (mm)
  var RINGS = 6, KERF = 0.04, STEP = 10 / 285;
  var BAND = KERF + (RINGS - 1) * STEP;          // ~0.215 mm
  // the piece of board (mm): x 0..VW, board edge at EDGE, nothing below it
  var VW = 7.6, VH = 4.6, EDGE = 4.2;
  var GAP = 0.25;                                // pour to trace, as the laser rules set it
  var TW = 0.3;
  var A_Y = 1.3, PAD_X = 3.4, PAD_R = 0.75, PAD_DRILL = 0.4;   // trace A ends in a pad
  var B_Y = 3.3;                                  // trace B runs across
  var HX = 6.2, HY = 1.5, H_CLR = 1.0, H_DRILL = 0.6;          // mounting hole in the pour
  var LAM = "#5f5a3a";                            // bare laminate where copper is gone
  var HATCH = 0.1;                                // drawn hatch spacing (real ~0.035-0.042)

  var METHODS = {
    rings: { name: "Concentric passes", note: "6 rings round every copper edge · 0.04 mm kerf · about a 0.22 mm band. The default.", dur: 6 * 0.75 + 0.9 },
    moat: { name: "Moat hatch", note: "The same band round the copper, cross-hatched: lines one way, then across.", dur: 3.4 },
    rubout: { name: "Full rubout", note: "Every bare millimetre, in scanlines across the whole board, like XCS's fill.", dur: 3.6 }
  };

  A.define("lz-rings", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 900 : 470;
    var K = narrow ? 63 : 70, OX = 20, OY = 46, F = narrow ? 1.3 : 1;
    var svg = A.stage(host, W, H, "A close-up of a trace, a pad and a ground pour, and the laser clearing the copper between them: concentric rings, a cross-hatched moat, or a full rubout");
    function sx(x) { return OX + x * K; }
    function sy(y) { return OY + y * K; }
    var PW = VW * K, PH = VH * K;

    A.text(svg, OX, 30, "CLOSE-UP · TO SCALE", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    // scale bar: 1 mm
    A.el(svg, "line", { x1: sx(VW) - K, y1: 25, x2: sx(VW), y2: 25, stroke: C.text2, "stroke-width": 2 });
    A.text(svg, sx(VW) - K / 2, 18, "1 mm", { size: 13, anchor: "middle", fill: C.text2, font: "mono" });

    var defs = A.el(svg, "defs");
    var uid = "lzr" + Math.floor(Math.random() * 1e6);
    function clip(id, build) {
      var cp = A.el(defs, "clipPath", { id: uid + id });
      build(cp);
      return "url(#" + uid + id + ")";
    }
    // the board's own area, so nothing draws off its edge
    var boardClip = clip("b", function (cp) { A.el(cp, "rect", { x: sx(0), y: sy(0), width: PW, height: EDGE * K }); });

    // ---- geometry, as SVG paths in px
    function islandD(e, closed) {        // trace A and its pad, grown by e mm
      var h = TW / 2 + e, R = PAD_R + e, dx = Math.sqrt(R * R - h * h), xj = PAD_X - dx;
      var d = "M" + sx(-0.4) + " " + sy(A_Y - h) + " L" + sx(xj) + " " + sy(A_Y - h) +
        " A" + R * K + " " + R * K + " 0 1 1 " + sx(xj) + " " + sy(A_Y + h) + " L" + sx(-0.4) + " " + sy(A_Y + h);
      return closed ? d + " Z" : d;
    }
    function lineD(y) { return "M" + sx(-0.4) + " " + sy(y) + " L" + sx(VW + 0.4) + " " + sy(y); }
    function circleD(x, y, r) {
      return "M" + sx(x + r) + " " + sy(y) + " A" + r * K + " " + r * K + " 0 1 1 " + sx(x - r) + " " + sy(y) +
        " A" + r * K + " " + r * K + " 0 1 1 " + sx(x + r) + " " + sy(y);
    }
    // the gaps the Gerber leaves (what has to be cleared), and the hole's clearance
    var gapClip = clip("g", function (cp) {
      A.el(cp, "path", { d: islandD(GAP, true) });
      A.el(cp, "rect", { x: sx(-0.4), y: sy(B_Y - TW / 2 - GAP), width: (VW + 0.8) * K, height: (TW + 2 * GAP) * K });
    });
    var holeClip = clip("h", function (cp) { A.el(cp, "circle", { cx: sx(HX), cy: sy(HY), r: H_CLR * K }); });

    // ---- layers, bottom to top
    var board = A.el(svg, "g", { "clip-path": boardClip });
    A.el(board, "rect", { x: sx(0), y: sy(0), width: PW, height: EDGE * K, fill: C.copper });
    var cleared = A.el(board, "g");              // what the laser takes away
    var top = A.el(board, "g");                  // copper that stays, drawn over the cleared layer
    var over = A.el(board, "g");                 // the laser's own path, drawn on top
    // off the board
    A.el(svg, "rect", { x: sx(0), y: sy(EDGE), width: PW, height: (VH - EDGE) * K, fill: C.ink });
    A.el(svg, "rect", { x: sx(0), y: sy(0), width: PW, height: PH, fill: "none", stroke: C.ruleStrong });
    A.el(svg, "line", { x1: sx(0), y1: sy(EDGE), x2: sx(VW), y2: sy(EDGE), stroke: C.text2, "stroke-width": 2 });
    A.text(svg, sx(0.15), sy(EDGE) + 0.27 * K, "Board edge: never etched as a trace", { size: 13 * F, fill: C.text2, baseline: "middle" });

    // copper that stays: the nets (brighter), the hole's stock-copper disc, the drills
    A.el(top, "path", { d: islandD(0, true), fill: C.copperHi });
    A.el(top, "rect", { x: sx(-0.4), y: sy(B_Y - TW / 2), width: (VW + 0.8) * K, height: TW * K, fill: C.copperHi });
    var disc = A.el(top, "circle", { cx: sx(HX), cy: sy(HY), r: (H_CLR - BAND) * K, fill: C.copper });
    A.el(top, "circle", { cx: sx(PAD_X), cy: sy(A_Y), r: PAD_DRILL * K, fill: C.ink });
    A.el(top, "circle", { cx: sx(HX), cy: sy(HY), r: H_DRILL * K, fill: C.ink });
    var skipRing = A.el(top, "circle", { cx: sx(HX), cy: sy(HY), r: H_CLR * K, fill: "none", stroke: C.caution, "stroke-width": 2, "stroke-dasharray": "6 5", opacity: 0 });
    // labels on the copper
    function tag(x, y, s) { A.text(top, sx(x), sy(y), s, { size: 13 * F, weight: 700, fill: C.ink, baseline: "middle" }); }
    tag(0.15, 0.5, "trace + pad");
    tag(0.15, 2.55, "pour (GND)");
    tag(0.15, 3.95, "trace");
    A.text(top, sx(HX), sy(HY + H_CLR) + 0.22 * K, "mounting hole", { size: 13 * F, weight: 700, fill: C.ink, anchor: "middle", baseline: "middle" });

    // ---- concentric rings: per round, every edge's ring i
    var rounds = [];                    // [{paths:[{el,live,L}], hole:[...]}]
    var ringG = A.el(cleared, "g", { fill: "none", "stroke-width": KERF * K + 0.6, stroke: LAM });
    var liveG = A.el(over, "g", { fill: "none", "stroke-width": 1.4, stroke: C.live });
    function ringPath(d, hole) {
      var p = A.el(ringG, "path", { d: d });
      var q = A.el(liveG, "path", { d: d });
      var L = p.getTotalLength();
      [p, q].forEach(function (n) { n.setAttribute("stroke-dasharray", L + " " + L); });
      return { el: p, live: q, L: L, hole: !!hole };
    }
    for (var i = 0; i < RINGS; i++) {
      var d = KERF / 2 + i * STEP, r = [];
      r.push(ringPath(islandD(d)));                          // round trace A + pad
      r.push(ringPath(islandD(GAP - d)));                    // the pour's edge facing it
      [B_Y - TW / 2 - d, B_Y + TW / 2 + d, B_Y - TW / 2 - GAP + d, B_Y + TW / 2 + GAP - d]
        .forEach(function (y) { r.push(ringPath(lineD(y))); });
      r.push(ringPath(circleD(HX, HY, H_CLR - d), true));    // the pour's edge round the hole
      rounds.push(r);
    }
    var ringLen = 0;
    rounds.forEach(function (r) { r.forEach(function (p) { ringLen += p.L / K; }); });

    // ---- moat hatch and rubout: fills revealed by a sweep, lines on top
    function sweepClip(id) {
      var rect;
      var url = clip(id, function (cp) { rect = A.el(cp, "rect", { x: sx(0), y: sy(0), width: 0, height: 0 }); });
      return { url: url, rect: rect };
    }
    function hatchLines(parent, horizontal, onlyFill) {
      var g = A.el(parent, "g", { stroke: C.live, "stroke-width": 1, opacity: 0.75 });
      var n = Math.ceil((horizontal ? EDGE : VW) / HATCH);
      for (var k = 0; k <= n; k++) {
        var v = k * HATCH;
        if (horizontal) A.el(g, "line", { x1: sx(0), y1: sy(v), x2: sx(VW), y2: sy(v) });
        else A.el(g, "line", { x1: sx(v), y1: sy(0), x2: sx(v), y2: sy(EDGE) });
      }
      return g;
    }
    // moat: gaps + the hole's band, cleared; hatch one way then across
    var moat = A.el(cleared, "g");
    var moatS1 = sweepClip("m1"), moatS2 = sweepClip("m2");
    var moatFill = A.el(moat, "g", { "clip-path": moatS1.url });
    A.el(A.el(moatFill, "g", { "clip-path": gapClip }), "rect", { x: sx(0), y: sy(0), width: PW, height: EDGE * K, fill: LAM });
    var moatHole = A.el(A.el(moatFill, "g", { "clip-path": holeClip }), "rect", { x: sx(0), y: sy(0), width: PW, height: EDGE * K, fill: LAM });
    var moatLines = A.el(over, "g");
    var mh1 = A.el(A.el(moatLines, "g", { "clip-path": moatS1.url }), "g");
    var mh2 = A.el(A.el(moatLines, "g", { "clip-path": moatS2.url }), "g");
    [mh1, mh2].forEach(function (g, k) {
      hatchLines(A.el(g, "g", { "clip-path": gapClip }), k === 0);
      g._hole = hatchLines(A.el(g, "g", { "clip-path": holeClip }), k === 0);
    });
    // cover the hatch where copper stays (the nets, and the disc inside the hole's band)
    function stays(parent, discToo) {
      var g = A.el(parent, "g");
      A.el(g, "path", { d: islandD(0, true), fill: C.copperHi });
      A.el(g, "rect", { x: sx(-0.4), y: sy(B_Y - TW / 2), width: (VW + 0.8) * K, height: TW * K, fill: C.copperHi });
      if (discToo) A.el(g, "circle", { cx: sx(HX), cy: sy(HY), r: (H_CLR - BAND) * K, fill: C.copper });
      A.el(g, "circle", { cx: sx(PAD_X), cy: sy(A_Y), r: PAD_DRILL * K, fill: C.ink });
      A.el(g, "circle", { cx: sx(HX), cy: sy(HY), r: H_DRILL * K, fill: C.ink });
      return g;
    }
    stays(moatLines, true);

    // rubout: scanlines over the whole board; fire over bare, travel over copper
    var rub = A.el(cleared, "g");
    var rubS = sweepClip("r");
    var rubFill = A.el(rub, "g", { "clip-path": rubS.url });
    A.el(A.el(rubFill, "g", { "clip-path": gapClip }), "rect", { x: sx(0), y: sy(0), width: PW, height: EDGE * K, fill: LAM });
    var rubHole = A.el(A.el(rubFill, "g", { "clip-path": holeClip }), "rect", { x: sx(0), y: sy(0), width: PW, height: EDGE * K, fill: LAM });
    var rubLines = A.el(over, "g", { "clip-path": rubS.url });
    function inIsland(x, y, e) {
      if (x <= PAD_X && Math.abs(y - A_Y) <= TW / 2 + e) return true;
      var dx = x - PAD_X, dy = y - A_Y, R = PAD_R + e;
      return dx * dx + dy * dy <= R * R;
    }
    function bare(x, y, skip) {
      if (inIsland(x, y, GAP) && !inIsland(x, y, 0)) return true;
      var t = Math.abs(y - B_Y);
      if (t > TW / 2 && t <= TW / 2 + GAP) return true;
      if (!skip) { var hx = x - HX, hy = y - HY; if (hx * hx + hy * hy <= H_CLR * H_CLR) return true; }
      return false;
    }
    var rubFire = [A.el(rubLines, "g", { stroke: C.live, "stroke-width": 1.6 }), A.el(rubLines, "g", { stroke: C.live, "stroke-width": 1.6 })];
    var rubTravel = A.el(rubLines, "g", { stroke: C.text, "stroke-width": 0.8, opacity: 0.35, "stroke-dasharray": "2 4" });
    // two sets of fire segments: with and without the hole (auto-skip)
    function scan(skip, gFire, travel) {
      var dxs = 0.01, fireLen = 0;
      for (var y = HATCH / 2; y < EDGE; y += HATCH) {
        if (travel) A.el(travel, "line", { x1: sx(0), y1: sy(y), x2: sx(VW), y2: sy(y) });
        var on = false, x0 = 0;
        for (var x = 0; x <= VW + dxs; x += dxs) {
          var b = x <= VW && bare(x, y, skip);
          if (b && !on) { on = true; x0 = x; }
          if (!b && on) { on = false; A.el(gFire, "line", { x1: sx(x0), y1: sy(y), x2: sx(x), y2: sy(y) }); fireLen += x - x0; }
        }
      }
      return fireLen;
    }
    scan(false, rubFire[0], rubTravel);
    scan(true, rubFire[1], null);

    // ---- relative path lengths, one pass, real line spacing (285 lines/cm; rubout 240)
    function bareArea(skip, onlyBand) {
      var a = 0, s = 0.02;
      for (var y = s / 2; y < EDGE; y += s) for (var x = s / 2; x < VW; x += s) {
        if (!bare(x, y, true)) {
          if (skip) continue;
          var hx = x - HX, hy = y - HY, rr = Math.sqrt(hx * hx + hy * hy);
          if (rr <= H_CLR && (!onlyBand || rr >= H_CLR - BAND)) a += s * s;
          continue;
        }
        a += s * s;
      }
      return a;
    }
    var holeRingLen = 0;
    rounds.forEach(function (r) { r.forEach(function (p) { if (p.hole) holeRingLen += p.L / K; }); });
    function pathLen(m, skip) {
      if (m === "rings") return ringLen - (skip ? holeRingLen : 0);
      if (m === "moat") return 2 * bareArea(skip, true) / (10 / 285);
      return VW * EDGE / (10 / 240);                 // the scan crosses the whole board
    }

    // ---- the side panel
    var RX = narrow ? OX : sx(VW) + 22, RY = narrow ? sy(VH) + 92 : OY, RW = narrow ? W - 2 * OX : W - RX - 16;
    var RH = H - RY - 14;
    A.el(svg, "rect", { x: RX, y: RY, width: RW, height: RH, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(svg, RX + 14, RY + 26, "METHOD", { size: 13, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var mName = A.text(svg, RX + 14, RY + 54, "", { size: 19 * F, weight: 700 });
    var noteG = A.el(svg, "g");
    function wrap(g, x, y, s, width, o) {
      while (g.firstChild) g.removeChild(g.firstChild);
      var words = s.split(" "), line = "", n = 0, per = Math.floor(width / ((o.size || 14) * 0.52));
      words.forEach(function (w) {
        if ((line + " " + w).trim().length > per) { A.text(g, x, y + n * (o.size + 5), line.trim(), o); n++; line = w; }
        else line += " " + w;
      });
      if (line.trim()) { A.text(g, x, y + n * (o.size + 5), line.trim(), o); n++; }
      return n;
    }
    var BY = RY + (narrow ? 170 : 156);
    A.text(svg, RX + 14, BY, "LASER PATH, ONE PASS · THIS PIECE", { size: 12 * F, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var bars = {};
    ["rings", "moat", "rubout"].forEach(function (m, k) {
      var y = BY + 16 + k * 34 * F;
      var lbl = A.text(svg, RX + 14, y + 12, METHODS[m].name, { size: 13 * F, fill: C.text2, baseline: "middle" });
      var bx = RX + 14 + (narrow ? 175 : 140), bw = RW - (bx - RX) - 14;
      A.el(svg, "rect", { x: bx, y: y + 4, width: bw, height: 16, rx: 2, fill: C.sunk });
      var b = A.el(svg, "rect", { x: bx, y: y + 4, width: 0, height: 16, rx: 2, fill: C.text4 });
      bars[m] = { lbl: lbl, bar: b, bw: bw };
    });
    var foot = A.el(svg, "g");
    var skipNote = A.el(svg, "g");
    var stat = A.text(svg, OX, sy(VH) + 30, "", { size: 16 * F, weight: 700 });
    // legend, under the drawing
    [[C.copperHi, "copper that stays"], [LAM, "bare laminate"], [C.live, "laser path"]].forEach(function (l, k) {
      var lx = OX + k * (narrow ? 175 : 180), ly = sy(VH) + 62;
      A.el(svg, "rect", { x: lx, y: ly - 9, width: 18, height: 10, rx: 2, fill: l[0] });
      A.text(svg, lx + 25, ly, l[1], { size: 13 * F, fill: C.text2 });
    });

    // ---- state
    var method = "rings", skip = true;
    function setBars() {
      var lens = { rings: pathLen("rings", skip), moat: pathLen("moat", skip), rubout: pathLen("rubout", skip) };
      var max = Math.max(lens.rings, lens.moat, lens.rubout);
      Object.keys(bars).forEach(function (m) {
        var b = bars[m];
        A.set(b.bar, { width: b.bw * lens[m] / max, fill: m === method ? C.live : C.text4 });
        b.lbl.setAttribute("fill", m === method ? C.text : C.text2);
        b.lbl.setAttribute("font-weight", m === method ? 700 : 500);
      });
    }
    function setStatic() {
      mName.textContent = METHODS[method].name;
      wrap(noteG, RX + 14, RY + 54 + 26 * F, METHODS[method].note, RW - 28, { size: 14 * F, fill: C.text2 });
      var fy = BY + 16 + 3 * 34 * F + 24;
      var fl = wrap(foot, RX + 14, fy, "Rubout grows with the board's area; rings only with its edges. The proven recipe runs 20 passes.", RW - 28, { size: 13 * F, fill: C.text3 });
      wrap(skipNote, RX + 14, fy + fl * (13 * F + 5) + 12, skip
        ? "Auto-skip on: the mounting hole's ring is left out. It isolates nothing: pour on one side, bare copper on the other. Traces and pads keep theirs."
        : "Auto-skip off: the mounting hole's ring is etched too. It costs time and isolates nothing.",
        RW - 28, { size: 13 * F, fill: skip ? C.caution : C.text2 });
      ringG.style.display = liveG.style.display = method === "rings" ? "" : "none";
      moat.style.display = moatLines.style.display = method === "moat" ? "" : "none";
      rub.style.display = rubLines.style.display = method === "rubout" ? "" : "none";
      disc.style.display = method === "rubout" && !skip ? "none" : "";
      rubFire[0].style.display = skip ? "none" : "";
      rubFire[1].style.display = skip ? "" : "none";
      moatHole.style.display = rubHole.style.display = skip ? "none" : "";
      mh1._hole.style.display = mh2._hole.style.display = skip ? "none" : "";
      skipRing.setAttribute("opacity", skip ? 1 : 0);
      setBars();
    }

    var RS = 0.75;               // seconds per round of rings
    function draw(t) {
      var dur = METHODS[method].dur, done = t >= dur - 0.6;
      if (method === "rings") {
        rounds.forEach(function (r, i) {
          var u = A.clamp((t - i * RS) / RS, 0, 1);
          r.forEach(function (p) {
            var show = !(p.hole && skip);
            p.el.style.display = p.live.style.display = show ? "" : "none";
            p.el.setAttribute("stroke-dashoffset", p.L * (1 - u));
            p.live.setAttribute("stroke-dashoffset", p.L * (1 - u));
            p.live.setAttribute("opacity", u > 0 && u < 1 ? 1 : 0);
          });
        });
        var n = Math.min(RINGS, Math.floor(t / RS) + 1);
        stat.textContent = done ? "Done: the gaps are clear." : "Ring " + n + " of " + RINGS + ", round every edge";
      } else if (method === "moat") {
        var u1 = A.clamp(t / 1.4, 0, 1), u2 = A.clamp((t - 1.4) / 1.4, 0, 1);
        A.set(moatS1.rect, { width: PW, height: EDGE * K * u1 });
        A.set(moatS2.rect, { width: PW * u2, height: EDGE * K });
        stat.textContent = done ? "Done: the gaps are clear." : (u1 < 1 ? "Hatch, one way" : "Hatch, across");
      } else {
        var u = A.clamp(t / 3.0, 0, 1);
        A.set(rubS.rect, { width: PW, height: EDGE * K * u });
        stat.textContent = done ? "Done: every bare mm cleared." : "Scanning the whole board";
      }
      stat.setAttribute("fill", done ? C.ok : C.text);
    }

    var lp = A.loop(host, function (t) { draw(Math.min(t, METHODS[method].dur)); }, 99);
    function replay() { setStatic(); draw(0); lp.restart(); }

    var row = A.controls(host);
    A.segmented(row, [["rings", "Concentric"], ["moat", "Moat hatch"], ["rubout", "Full rubout"]], "rings",
      function (v) { method = v; replay(); });
    A.segmented(row, [["on", "Auto-skip on"], ["off", "Auto-skip off"]], "on",
      function (v) { skip = v === "on"; replay(); });
    A.button(row, "Play again", replay, "primary");
    setStatic();
  });
})();
