/* Screwing the copper down through the spoilboard grid (engine/spoilboard.py).
   - The grid: 10 mm pitch, measured on the lab's spoilboard; hole (0,0) at machine
     X 6.42, Y 14.58; the outer ring is the spoilboard's own mounting screws.
   - Only holes the spindle can reach (inside the 203.2 x 152.4 mm travel).
   - A hole qualifies when the whole 8 mm screw HEAD lands on copper, 1 mm clear of
     the edge (inset 5 mm), and clear of the design, or the cutter runs into it.
   - Four picked by farthest-point spread from the front-left corner: screws bunched
     in a line are a hinge, not a clamp.
   - The heads stand 3 mm above the copper; the default lift between cuts is 2 mm, so
     ticking "Held down with M4 screws" raises it to 4 mm on all three operations
     (gui2/inspector.py; spoilboard.min_travel_z = head 3 + clearance 1).
   Sheet and job as in the recording: 150 x 100 mm at X 60.52, Y 24.42, the job centred. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var BX = 203.2, BY = 152.4, OXg = 6.42, OYg = 14.58, P = 10, NX = 20, NY = 13;
  var SX0 = 60.52, SY0 = 24.42, SW = 150, SH = 100;
  var JW = 68, JH = 42, JX = 60.52 + (BX - 60.52 - JW) / 2, JY = 24.42 + (SH - JH) / 2;
  var HEAD_D = 8, HEAD_H = 3, INSET = HEAD_D / 2 + 1;

  var holes = [];
  for (var j = 1; j < NY - 1; j++) for (var i = 1; i < NX - 1; i++) {
    var x = OXg + i * P, y = OYg + j * P;
    holes.push({ x: x, y: y, reach: x >= 0 && x <= BX && y >= 0 && y <= BY });
  }
  function onCopper(h) { return h.x >= SX0 + INSET && h.x <= SX0 + SW - INSET && h.y >= SY0 + INSET && h.y <= SY0 + SH - INSET; }
  function clearOfDesign(h) {
    var dx = Math.max(JX - h.x, 0, h.x - (JX + JW)), dy = Math.max(JY - h.y, 0, h.y - (JY + JH));
    return Math.hypot(dx, dy) > HEAD_D / 2;
  }
  function problem(h) {
    if (!h.reach) return "is out of the machine's reach";
    if (!(h.x >= SX0 && h.x <= SX0 + SW && h.y >= SY0 && h.y <= SY0 + SH)) return "is not on the copper at all";
    if (!onCopper(h)) return "is too close to the edge: the head would overhang the copper and tip";
    if (!clearOfDesign(h)) return "is under the design: the cutter would run into the screw head";
    return null;
  }
  function autoPick() {
    var pool = holes.filter(function (h) { return !problem(h); });
    if (!pool.length) return [];
    var start = pool.reduce(function (a, b) {
      return Math.hypot(b.x - SX0, b.y - SY0) < Math.hypot(a.x - SX0, a.y - SY0) ? b : a;
    });
    var chosen = [start];
    while (chosen.length < 4) {
      var best = null, bd = -1;
      pool.forEach(function (p) {
        if (chosen.indexOf(p) >= 0) return;
        var d = Math.min.apply(null, chosen.map(function (c) { return Math.hypot(p.x - c.x, p.y - c.y); }));
        if (d > bd) { bd = d; best = p; }
      });
      if (!best) break;
      chosen.push(best);
    }
    return chosen;
  }

  A.define("hc-screws", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 800 : 500;
    var K = narrow ? 2.3 : 2.62, OX = 26, OY = 58;
    var PX = narrow ? 24 : 596, PY = narrow ? OY + BY * K + 34 : 58, PW = narrow ? W - 48 : 260;
    var svg = A.stage(host, W, H, "The spoilboard's screw grid under the copper, the screw holes the app picks, and the lift over the screw heads");
    A.text(svg, OX, 32, "THE SPOILBOARD GRID · 10 MM PITCH", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    function sx(mm) { return OX + mm * K; }
    function sy(mm) { return OY + (BY - mm) * K; }
    A.el(svg, "rect", { x: sx(0), y: sy(BY), width: BX * K, height: BY * K, fill: C.panel, stroke: C.ruleStrong, "stroke-width": 1.5 });
    A.el(svg, "rect", { x: sx(SX0), y: sy(SY0 + SH), width: (BX - SX0) * K, height: SH * K, fill: C.copperFill, stroke: C.copper, "stroke-width": 2 });
    A.el(svg, "rect", { x: sx(JX), y: sy(JY + JH), width: JW * K, height: JH * K, fill: C.copper, opacity: 0.9 });
    A.text(svg, sx(JX + JW / 2), sy(JY + JH / 2) + 6, "the design", { size: 15, anchor: "middle", weight: 700, fill: C.ink });
    var gHoles = A.el(svg, "g", {}), gScrews = A.el(svg, "g", {});

    // side view: the head, the lift, the rapid
    A.el(svg, "rect", { x: PX, y: PY, width: PW, height: narrow ? 230 : 250, fill: C.panel, stroke: C.ruleStrong, rx: 3 });
    A.text(svg, PX + 14, PY + 26, "SIDE VIEW · ×18", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var ZK = 18, baseY = PY + (narrow ? 190 : 200), cx0 = PX + 20, cx1 = PX + PW - 20;
    A.el(svg, "rect", { x: cx0, y: baseY, width: cx1 - cx0, height: 10, fill: C.copper });
    A.text(svg, cx0, baseY - 8, "Z 0", { size: 15, fill: C.copperHi });
    var hx = cx0 + (cx1 - cx0) * 0.56;
    A.el(svg, "rect", { x: hx - HEAD_D / 2 * 9, y: baseY - HEAD_H * ZK, width: HEAD_D * 9, height: HEAD_H * ZK, fill: C.steelDim, rx: 6 });
    A.text(svg, hx, baseY + 30, "M4 head, 3 mm", { size: 15, anchor: "middle", fill: C.text2 });
    var rapid = A.el(svg, "line", { x1: cx0, x2: cx1, y1: 0, y2: 0, stroke: C.live, "stroke-width": 3, "stroke-dasharray": "10 6" });
    var rapidT = A.text(svg, cx0, 0, "", { size: 15, weight: 600 });
    var crash = A.el(svg, "circle", { cx: hx, cy: 0, r: 16, fill: "none", stroke: C.danger, "stroke-width": 3 });

    var gChk = A.el(svg, "g", {});
    var s = { screwed: true, lift: 4, mine: false, picks: autoPick(), msg: "" };

    function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
    function draw() {
      clear(gHoles); clear(gScrews); clear(gChk);
      holes.forEach(function (h) {
        var bad = problem(h);
        var col = !h.reach ? C.text4 : (!bad ? C.ok : (/design/.test(bad) ? C.danger : C.text3));
        var c = A.el(gHoles, "circle", { cx: sx(h.x), cy: sy(h.y), r: narrow ? 2.6 : 3, fill: col, opacity: !h.reach ? 0.5 : 0.95 });
        if (s.screwed && s.mine && h.reach) {
          c.setAttribute("r", 5); c.style.cursor = "pointer";
          c.setAttribute("tabindex", 0); c.setAttribute("role", "button");
          c.setAttribute("aria-label", "hole at X " + h.x.toFixed(1) + " Y " + h.y.toFixed(1));
          var toggle = function () {
            var k = s.picks.indexOf(h);
            if (k >= 0) { s.picks.splice(k, 1); s.msg = ""; }
            else { s.picks.push(h); var p = problem(h); s.msg = p ? "That hole " + p + ". Reported, not refused." : ""; }
            draw();
          };
          c.addEventListener("click", toggle);
          c.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
        }
      });
      if (s.screwed) s.picks.forEach(function (h, n) {
        var bad = problem(h);
        A.el(gScrews, "circle", { cx: sx(h.x), cy: sy(h.y), r: HEAD_D / 2 * K, fill: C.steelDim, stroke: bad ? C.danger : C.text, "stroke-width": 2 });
        A.el(gScrews, "line", { x1: sx(h.x) - 6, y1: sy(h.y), x2: sx(h.x) + 6, y2: sy(h.y), stroke: C.ink, "stroke-width": 2 });
        A.text(gScrews, sx(h.x) + HEAD_D / 2 * K + 3, sy(h.y) - 6, String(n + 1), { size: 15, weight: 700, fill: C.text });
      });
      // side view
      var ly = baseY - s.lift * ZK;
      A.set(rapid, { y1: ly, y2: ly });
      A.set(rapidT, { y: ly - 8 });
      var hits = s.screwed && s.lift < HEAD_H + 1;
      rapidT.textContent = "lift " + s.lift + " mm";
      A.set(rapidT, { fill: hits ? C.danger : C.live });
      A.set(crash, { cy: ly, opacity: hits ? 1 : 0 });
      // checks
      var chk = [];
      if (!s.screwed) chk.push(["ok", "No screws", "the copper is clamped; lift 2 mm."]);
      else {
        chk.push(hits ? ["fail", "A rapid would hit a screw head", "raise the lift to 4 mm."] : ["ok", "Lift clears the heads", "lifting " + s.lift + " mm over 3 mm heads."]);
        var n = s.picks.length;
        if (n < 4) chk.push(["warn", "Only " + n + " usable holes", "move the design or use a bigger sheet."]);
        else {
          var xs = s.picks.map(function (p) { return p.x; }), ys = s.picks.map(function (p) { return p.y; });
          var spanX = Math.max.apply(null, xs) - Math.min.apply(null, xs), spanY = Math.max.apply(null, ys) - Math.min.apply(null, ys);
          if (spanX < SW * 0.25 || spanY < SH * 0.25) chk.push(["warn", "The screws are in a line", "the copper can pivot about it."]);
          else chk.push(["ok", "Four screws, spread wide", "one towards each corner."]);
        }
      }
      var cy = PY + (narrow ? 262 : 290);
      chk.forEach(function (c, k) {
        var col = { ok: C.ok, warn: C.caution, fail: C.danger }[c[0]];
        A.el(gChk, "circle", { cx: PX + 8, cy: cy + k * 54 - 5, r: 6, fill: col });
        A.text(gChk, PX + 22, cy + k * 54, c[1], { size: 16, weight: 700, fill: col });
        A.text(gChk, PX + 22, cy + k * 54 + 21, c[2], { size: 15, fill: C.text2 });
      });
      st.textContent = s.msg || (s.screwed ? (s.mine ? "Click holes to screw through, and click one again to drop it." :
        "Green: a screw fits. Red: under the design. Grey: the head would overhang the copper. Dim: out of reach.") :
        "Clamped, not screwed: nothing to pick, and the lift stays at 2 mm.");
      st.className = "anim-status" + (s.msg ? " caution" : "");
    }

    var row = A.controls(host);
    var st = A.status(row);
    var segScrew = A.segmented(row, [[true, "Held down with M4 screws"], [false, "Clamped"]], true, function (v) {
      s.screwed = v; s.lift = v ? 4 : 2; if (segLift) segLift.set(s.lift); else draw();
    });
    var segLift = A.segmented(row, [[2, "Lift 2 mm"], [4, "Lift 4 mm"]], 4, function (v) { s.lift = v; draw(); });
    A.button(row, "Choose the screw holes myself", function () { s.mine = !s.mine; s.msg = ""; this.textContent = s.mine ? "Done choosing" : "Choose the screw holes myself"; draw(); });
    A.button(row, "Let the app choose", function () { s.picks = autoPick(); s.msg = ""; draw(); });
    row.appendChild(st);
    draw();
    void segScrew;
  });
})();
