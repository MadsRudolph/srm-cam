/* "hw-touch" — how one touch is measured (srm20_spi_probe.ino: descendUntilTouch,
   descendFast, verifyTouch).

   A touch is found twice. The coarse descent steps Z down 25 µm at a time until the probe
   reads contact; the tool lifts 150 µm and comes down again at 10 µm, the machine's own
   step. The two contacts must agree within 60 µm. If they don't, the fine touch becomes
   the new reference and it tries once more; two disagreements and the point is reported
   E UNSTABLE instead of poisoning the height map. Once copper has been found, later
   points rapid down to 1 mm above the highest copper seen, step 150 µm until 100 µm
   above it, and only then go fine. The numbers are the firmware's; the surface heights
   are an example. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  function descend(from, step, surface, out, kind) {
    var z = from;
    for (;;) {
      z -= step;
      var hit = z <= surface;
      out.push({ z: z, kind: hit ? "contact" : kind });
      if (hit) return z;
    }
  }

  function build(name) {
    var ev = [], z, coarse, fine;
    if (name === "first") {
      ev.push({ z: 290, kind: "start" });
      coarse = descend(290, 25, 0, ev, "coarse");
      ev.push({ z: coarse + 150, kind: "lift" });
      fine = descend(coarse + 150, 10, 0, ev, "fine");
      return { ev: ev, lo: -60, hi: 330, ok: true, coarse: coarse, fine: fine,
        text: "First point: 25 µm steps to contact at " + coarse + " µm, lift 150 µm, then 10 µm steps. The fine touch at " +
          fine + " µm agrees within 60 µm, so it is recorded." };
    }
    if (name === "later") {
      ev.push({ z: 1000, kind: "start" });
      z = 1000;
      while (z > 100) { z = Math.max(z - 150, 100); ev.push({ z: z, kind: "rapid" }); }
      coarse = descend(100, 25, -40, ev, "coarse");
      ev.push({ z: coarse + 150, kind: "lift" });
      fine = descend(coarse + 150, 10, -40, ev, "fine");
      return { ev: ev, lo: -90, hi: 1060, ok: true, coarse: coarse, fine: fine,
        text: "Later points: from the approach plane 1 mm above the highest copper seen, 150 µm steps (no copper can be there), 25 µm from 100 µm above it, then the same 10 µm check. This copper sits 40 µm lower; the touch agrees and is recorded." };
    }
    // flaky: a chip under the bit gives an early contact, and again on the retry
    ev.push({ z: 290, kind: "start" });
    coarse = descend(290, 25, 90, ev, "coarse");
    ev.push({ z: coarse + 150, kind: "lift" });
    fine = descend(coarse + 150, 10, 0, ev, "fine");
    ev.push({ z: fine + 150, kind: "lift" });
    var again = descend(fine + 150, 10, 70, ev, "fine");
    return { ev: ev, lo: -60, hi: 330, ok: false, coarse: coarse, fine: fine, again: again,
      text: "A flaky touch: the coarse contact at " + coarse + " µm and the fine one at " + fine + " µm are " +
        (coarse - fine) + " µm apart, over 60. It retries once from the fine touch and disagrees again (" + again +
        " µm), so the point comes back E UNSTABLE and is not put in the map." };
  }

  A.define("hw-touch", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 490 : 880, H = narrow ? 470 : 400;
    var svg = A.stage(host, W, H, "Z against time while the firmware measures one touch");
    var X0 = narrow ? 76 : 96, X1 = W - 24, Y0 = narrow ? 84 : 60, Y1 = H - 64;
    A.el(svg, "rect", { x: 10, y: 10, width: W - 20, height: H - 20, rx: 4, fill: C.panel, stroke: C.ruleHi });
    var title = A.text(svg, W - 28, 40, "", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em", anchor: "end" });
    A.text(svg, X1, H - 30, "time →", { size: 15, fill: C.text3, anchor: "end" });
    var grid = A.el(svg, "g"), band = A.el(svg, "rect", { x: X0, width: X1 - X0, fill: C.okFill, opacity: 0 });
    var cuLine = A.el(svg, "line", { x1: X0, x2: X1, stroke: C.copperHi, "stroke-width": 2, "stroke-dasharray": "8 5" });
    var cuT = A.text(svg, X0 + 6, 0, "copper", { size: 15, weight: 600, fill: C.copperHi });
    var trace = A.el(svg, "polyline", { fill: "none", stroke: C.live, "stroke-width": 3, "stroke-linejoin": "round" });
    var marks = A.el(svg, "g");
    var note = A.text(svg, 28, narrow ? 66 : 40, "", { size: 16, weight: 700, font: "label" });

    var cur = "first", sc = null, t0 = 0, shown = -1, st = null;
    var row = A.controls(host);
    var seg = A.segmented(row, [["first", "First point"], ["later", "Later points"], ["flaky", "A flaky touch"]], "first",
      function (v) { if (st) start(v); });
    A.button(row, "Replay", function () { start(cur); });
    st = A.status(row);
    function ymap(z) { return Y1 - (z - sc.lo) / (sc.hi - sc.lo) * (Y1 - Y0); }
    function xmap(i) { return X0 + 10 + i * (X1 - X0 - 20) / (sc.ev.length - 1); }
    function start(name) {
      cur = name; sc = build(name); t0 = performance.now() / 1000; shown = -1;
      title.textContent = name === "later" ? "LATER POINTS · FAST APPROACH" : name === "flaky" ? "A FLAKY TOUCH" : "THE FIRST POINT";
      while (grid.firstChild) grid.removeChild(grid.firstChild);
      var stepU = sc.hi - sc.lo > 600 ? 250 : 50;
      for (var z = Math.ceil(sc.lo / stepU) * stepU; z <= sc.hi; z += stepU) {
        A.el(grid, "line", { x1: X0, x2: X1, y1: ymap(z), y2: ymap(z), stroke: C.rule });
        A.text(grid, X0 - 8, ymap(z) + 5, (z > 0 ? "+" : z < 0 ? "−" : "") + Math.abs(z), { size: 15, font: "mono", anchor: "end", fill: C.text3 });
      }
      A.text(grid, X0 - 8, Y1 + 24, "µm", { size: 15, fill: C.text3, anchor: "end" });
      var surf = name === "later" ? -40 : 0;
      A.set(cuLine, { y1: ymap(surf), y2: ymap(surf) });
      A.set(cuT, { y: ymap(surf) - 8 });
      band.setAttribute("opacity", 0);
      note.textContent = "";
      st.className = "anim-status";
      st.textContent = "Measuring…";
      if (A.reduced) reveal(sc.ev.length - 1);
    }
    function reveal(n) {
      if (n === shown) return;
      shown = n;
      trace.setAttribute("points", sc.ev.slice(0, n + 1).map(function (e, i) { return xmap(i) + "," + ymap(e.z); }).join(" "));
      while (marks.firstChild) marks.removeChild(marks.firstChild);
      var contacts = 0;
      sc.ev.slice(0, n + 1).forEach(function (e, i) {
        if (e.kind === "contact") {
          contacts++;
          A.el(marks, "circle", { cx: xmap(i), cy: ymap(e.z), r: 7, fill: C.danger, stroke: "#fff", "stroke-width": 2 });
          var lab = contacts === 1 ? "coarse" : contacts === 2 ? "fine" : "retry";
          var right = narrow || xmap(i) > X1 - 90;
          A.text(marks, xmap(i) + (right ? -8 : 10), ymap(e.z) + 24, lab, { size: 15, weight: 600, fill: C.danger, anchor: right ? "end" : "start" });
        }
        if (e.kind === "lift") {
          A.text(marks, xmap(i) + 6, ymap(e.z) - 10, "lift 150", { size: 15, fill: C.text2 });
        }
      });
      if (contacts >= 2 || (sc.ok && contacts >= 1)) {
        var ref = sc.coarse;
        A.set(band, { y: ymap(ref + 60), height: ymap(ref - 60) - ymap(ref + 60) });
        band.setAttribute("opacity", contacts >= 2 ? 0.9 : 0);
      }
      if (n === sc.ev.length - 1) {
        note.textContent = sc.ok ? "✓ agree within 60 µm: recorded" : "✕ E UNSTABLE: not recorded";
        note.setAttribute("fill", sc.ok ? C.ok : C.danger);
        st.className = "anim-status " + (sc.ok ? "ok" : "bad");
        st.textContent = sc.text;
      }
    }
    A.loop(host, function () {
      if (!sc) return;
      var n = Math.min(sc.ev.length - 1, Math.floor((performance.now() / 1000 - t0) / 0.16));
      reveal(n);
    });
    seg.set("first");
  });
})();
