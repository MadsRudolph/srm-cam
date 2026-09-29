/* A board held at points arches over air between the fixings. The probe measures the
   arch with a static tool at almost no force; the cutter arrives spinning and pushing
   down, and the unsupported part gives a little instead of being cut. So, held at
   points, the app deepens the cut (gui2/window.py _flex_margin):
     warp applied  -> min(arch / 4, 0.12) + 0.035 foil   (arch = what a plane can't explain)
     warp not on   -> the whole range + 0.035            (nothing cancels the tilt)
     bonded (tape) -> 0                                   (nowhere for it to go)
   A board that arches more than the cap wants re-fixing, not a deeper cut. The give
   drawn here is the app's own assumption, a quarter of the arch. Vertical ×190. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var FOIL = 0.035, DEPTH = 0.15, FRAC = 0.25, CAP = 0.12;

  A.define("hc-flex", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 560 : 500;
    var VK = 190;                                   // px per mm, vertically
    var X0 = 60, X1 = W - 60, BASE = narrow ? 330 : 300, TH = 46;
    var svg = A.stage(host, W, H, "A board held at two points, arched between them, and the cutter pushing the middle down");
    A.text(svg, 24, 32, "SECTION BETWEEN TWO FIXINGS · HEIGHTS ×190", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: 20, y: BASE + TH + 10, width: W - 40, height: 16, fill: C.board, opacity: 0.6 });
    A.text(svg, 28, BASE + TH + 48, "spoilboard", { size: 15, fill: C.text2 });
    var gBoard = A.el(svg, "g", {});
    var fix1 = A.el(svg, "g", {}), fix2 = A.el(svg, "g", {});
    [fix1, fix2].forEach(function (f, k) {
      var x = k ? X1 : X0;
      A.el(f, "rect", { x: x - 16, y: BASE - 34, width: 32, height: 26, fill: C.steelDim, rx: 4 });
      A.el(f, "rect", { x: x - 4, y: BASE - 10, width: 8, height: TH + 26, fill: C.steelDim });
    });
    var fixT = A.text(svg, X0 - 22, BASE - 44, "", { size: 15, fill: C.text2 });
    var bit = A.el(svg, "g", {});
    A.el(bit, "rect", { x: -9, y: -86, width: 18, height: 86, fill: C.steel });
    A.el(bit, "rect", { x: -26, y: -122, width: 52, height: 38, fill: C.steelDim, rx: 4 });
    var push = A.arrow(svg, 0, 0, 0, 0, { color: C.caution, head: 9 });
    var archT = A.text(svg, W / 2 + 40, 0, "", { size: 15, fill: C.live });

    var rT1 = A.text(svg, 24, H - 58, "", { size: 18, weight: 700 });
    var rT2 = A.text(svg, 24, H - 30, "", { size: 15, fill: C.text2 });

    var s = { arch: 0.4, hold: "points", warp: true, p: 0 };

    function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
    function give() { return s.hold === "bonded" ? 0 : FRAC * s.arch; }
    function margin() {
      if (s.hold !== "points") return 0;
      if (!s.warp) return s.arch + FOIL;
      return Math.min(s.arch * FRAC, CAP) + FOIL;
    }
    function surf(x, pushed) {
      var t = (x - X0) / (X1 - X0);
      if (t < 0 || t > 1) return BASE;
      var up = s.hold === "bonded" ? 0 : s.arch;
      var down = pushed ? give() * s.p : 0;
      return BASE - (up - down) * VK * Math.sin(Math.PI * t);
    }
    function draw() {
      clear(gBoard);
      var top = [], mid = W / 2, pts = [], n = 60;
      for (var i = 0; i <= n; i++) {
        var x = 20 + (W - 40) * i / n;
        pts.push([x, surf(x, true)]);
      }
      var poly = pts.map(function (p) { return p[0] + "," + p[1]; }).join(" ");
      var under = pts.slice().reverse().map(function (p) { return p[0] + "," + (p[1] + TH); }).join(" ");
      A.el(gBoard, "polygon", { points: poly + " " + under, fill: C.fr4 });
      var foil = pts.slice().reverse().map(function (p) { return p[0] + "," + (p[1] + FOIL * VK); }).join(" ");
      A.el(gBoard, "polygon", { points: poly + " " + foil, fill: C.copper });
      // the air under the arch
      if (s.hold !== "bonded" && s.arch > 0.02) {
        var gap = [];
        for (var k = 0; k <= n; k++) { var xx = X0 + (X1 - X0) * k / n; gap.push(xx + "," + (surf(xx, true) + TH)); }
        A.el(gBoard, "polygon", { points: gap.join(" ") + " " + X1 + "," + (BASE + TH) + " " + X0 + "," + (BASE + TH), fill: C.sunk, opacity: 0.9 });
        A.text(gBoard, mid, BASE + TH - 4, "air", { size: 15, anchor: "middle", fill: C.text3 });
      }
      // the channel at the middle: asked depth, minus what the board gives
      var asked = DEPTH + margin(), eff = asked - give() * s.p;
      var sm = surf(mid, true);
      var chBot = sm + Math.min(Math.max(0, eff) * VK, TH);
      A.el(gBoard, "rect", { x: mid - 9, y: sm - 1, width: 18, height: chBot - sm + 1, fill: C.sunk });
      var through = eff >= FOIL - 1e-9;
      A.el(gBoard, "line", { x1: mid - 40, y1: sm + FOIL * VK, x2: mid + 40, y2: sm + FOIL * VK, stroke: through ? C.ok : C.danger, "stroke-width": 2, "stroke-dasharray": "5 4" });
      bit.setAttribute("transform", "translate(" + mid + "," + (sm - 2) + ")");
      A.set(push.children[0], { x1: mid + 44, y1: sm - 70, x2: mid + 44, y2: sm - 20 });
      push.children[1].setAttribute("points", [mid + 44, sm - 16, mid + 38, sm - 28, mid + 50, sm - 28].join(","));
      push.setAttribute("opacity", s.hold === "bonded" ? 0 : 1);
      A.set(archT, { y: surf(mid, false) - 100 });
      archT.textContent = s.hold === "bonded" ? "bonded: no arch" : "arch " + s.arch.toFixed(2) + " mm";
      fixT.textContent = s.hold === "bonded" ? "tape across the whole back" : "screwed or clamped at points";
      [fix1, fix2].forEach(function (f) { f.setAttribute("opacity", s.hold === "bonded" ? 0.15 : 1); });

      var m = margin(), capped = s.hold === "points" && s.warp && s.arch * FRAC > CAP;
      if (s.hold === "bonded") { rT1.textContent = "Nothing added"; A.set(rT1, { fill: C.ok }); }
      else { rT1.textContent = "Cut deeper by " + m.toFixed(3) + " mm" + (capped ? " (capped)" : ""); A.set(rT1, { fill: capped ? C.caution : C.text }); }
      rT2.textContent = narrow ? "" : explain(m, capped);
      st.textContent = narrow ? explain(m, capped) : "Play pushes the cutter in. Without the extra depth the middle " +
        ((DEPTH - give() < FOIL) ? "would leave copper behind." : "would still reach through the foil.");
      st.className = "anim-status";
    }
    function explain(m, capped) {
      if (s.hold === "bonded") return "Bonded across the whole back: nowhere for it to go, the probed surface IS the cut surface.";
      if (!s.warp) return "The map isn't applied, so nothing cancels the tilt: the whole " + s.arch.toFixed(2) + " mm range, plus the foil.";
      if (capped) return "A quarter of the arch is over the 0.12 mm cap: re-fix the board rather than cut deeper.";
      return "A quarter of the " + s.arch.toFixed(2) + " mm arch, plus the 0.035 mm foil: what the cutter pushes it down by.";
    }

    var row = A.controls(host);
    var st = A.status(row);
    A.segmented(row, [["points", "Screwed or clamped at points"], ["bonded", "Bonded (tape)"]], "points", function (v) { s.hold = v; if (st) draw(); });
    A.segmented(row, [[true, "Warp on"], [false, "Warp off"]], true, function (v) { s.warp = v; if (st) draw(); });
    A.slider(row, "Arch the map shows", 0, 0.8, 0.01, 0.4, function (v) { s.arch = v; if (st) draw(); }, function (v) { return v.toFixed(2) + " mm"; });
    var anim = null;
    A.button(row, "Play", function () {
      if (anim) anim.stop();
      if (A.reduced) { s.p = 1; draw(); return; }
      var t0 = null;
      anim = A.loop(host, function (t) {
        if (t0 === null) t0 = t;
        var u = (t - t0) / 2.4;
        s.p = u < 0.5 ? A.ease(u * 2) : 1;
        draw();
        if (u >= 1) anim.stop();
      }, 1.2);
    }, "primary");
    row.appendChild(st);
    s.p = 1;
    draw();
  });
})();
