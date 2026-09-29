/* The Gerber folder, file by file. Tick a file off and see what Open Gerber folder…
   makes of what is left, the way gerber2rml/loader.py does: no B.Cu or no Edge.Cuts
   and the folder is refused (with the app's own reason); no drill file loads, with
   no holes to drill; F.Cu is only used for a double-sided board. Files are found
   by KiCad's names (-B_Cu, -Edge_Cuts, -PTH/-NPTH .drl), and the job is named
   after the KiCad project. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  var FILES = [
    ["bcu", "feedback-B_Cu.gbr", "bottom copper: the traces", true],
    ["edge", "feedback-Edge_Cuts.gbr", "the outline: the cut-out", true],
    ["pth", "feedback-PTH.drl", "plated holes", true],
    ["npth", "feedback-NPTH.drl", "unplated holes", true],
    ["fcu", "feedback-F_Cu.gbr", "top copper: double-sided only", false]
  ];

  A.define("gs-files", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 520 : 880, H = narrow ? 700 : 400;
    var s = A.stage(host, W, H, "The files KiCad has to give SRM-CAM, and what happens when one is missing");
    var on = {};
    FILES.forEach(function (f) { on[f[0]] = f[3]; });

    // the folder
    var fx = 14, fy = 16, fw = narrow ? 492 : 400, fh = 360;
    if (narrow) fh = 300;
    A.el(s, "path", { d: "M" + fx + " " + (fy + 14) + " h120 l14 -14 h" + (fw - 134) + " v" + (fh) + " h-" + fw + " z", fill: C.panel, stroke: C.ruleHi, "stroke-width": 2 });
    A.text(s, fx + 16, fy + 42, "Gerbers/  — one folder", { size: 15, fill: C.text2, font: "mono" });
    var rows = [];
    FILES.forEach(function (f, i) {
      var y = fy + 60 + i * (narrow ? 46 : 58);
      var g = A.el(s, "g", { tabindex: 0, role: "checkbox", "aria-label": f[1], style: "cursor:pointer;outline:none" });
      var box = A.el(g, "rect", { x: fx + 12, y: y, width: fw - 24, height: narrow ? 40 : 50, rx: 4, fill: C.panelHi, stroke: C.ruleHi, "stroke-width": 2 });
      var tick = A.text(g, fx + 30, y + (narrow ? 27 : 32), "", { size: 18, weight: 700 });
      var name = A.text(g, fx + 56, y + (narrow ? 26 : 22), f[1], { size: 15, font: "mono" });
      if (!narrow) A.text(g, fx + 56, y + 41, f[2], { size: 13, fill: C.text2 });
      function toggle() { on[f[0]] = !on[f[0]]; update(); }
      g.addEventListener("click", toggle);
      g.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
      rows.push({ f: f, g: g, box: box, tick: tick, name: name });
    });

    // what the app makes of it
    var px = narrow ? 14 : 434, py = narrow ? 330 : 16, pw = narrow ? 492 : 432, ph = narrow ? 360 : 368;
    A.el(s, "rect", { x: px, y: py, width: pw, height: ph, rx: 6, fill: C.sunk, stroke: C.ruleHi });
    A.text(s, px + 14, py + 26, "FILE › OPEN GERBER FOLDER…", { size: 13, fill: C.text3, weight: 700, spacing: 1 });
    var view = A.el(s, "g", {});
    var msg = A.el(s, "g", {});

    // a board drawn in panel coordinates
    var bx = px + 60, by = py + 60, bw = pw - 120, bh = narrow ? 200 : 210;
    var PADS = [[0.12, 0.2], [0.88, 0.2], [0.12, 0.8], [0.88, 0.8], [0.4, 0.5], [0.6, 0.5]];
    var TR = [[[0.12, 0.2], [0.4, 0.2], [0.4, 0.5]], [[0.88, 0.2], [0.6, 0.2], [0.6, 0.5]], [[0.12, 0.8], [0.88, 0.8]]];
    function P(p) { return (bx + p[0] * bw) + "," + (by + p[1] * bh); }

    function line(g, y, t, col, size) { return A.text(g, px + 16, y, t, { size: size || 15, fill: col || C.text }); }
    function wrap(g, y, t, col, max) {
      var words = t.split(" "), l = "", out = [];
      words.forEach(function (w) { if ((l + " " + w).length > max) { out.push(l); l = w; } else l = l ? l + " " + w : w; });
      out.push(l);
      out.forEach(function (x, k) { line(g, y + k * 21, x, col); });
      return y + out.length * 21;
    }

    var row = A.controls(host);
    var st = A.status(row);
    A.button(row, "All four needed", function () { FILES.forEach(function (f) { on[f[0]] = f[3]; }); update(); });

    function update() {
      rows.forEach(function (r) {
        var o = on[r.f[0]];
        r.box.setAttribute("fill", o ? C.panelHi : C.base);
        r.box.setAttribute("stroke", o ? (r.f[3] ? C.copperDim : C.ruleStrong) : C.rule);
        r.tick.textContent = o ? "✓" : "–";
        r.tick.setAttribute("fill", o ? C.ok : C.text4);
        r.name.setAttribute("fill", o ? C.text : C.text4);
        r.name.setAttribute("text-decoration", o ? "none" : "line-through");
        r.g.setAttribute("aria-checked", o ? "true" : "false");
      });
      while (view.firstChild) view.removeChild(view.firstChild);
      while (msg.firstChild) msg.removeChild(msg.firstChild);
      var maxc = narrow ? 50 : 46, y = by + bh + 34;
      if (!on.bcu) {
        A.text(view, px + pw / 2, by + bh / 2, "✕", { size: 60, anchor: "middle", fill: C.danger, weight: 700 });
        y = wrap(msg, y, "No bottom-copper (B.Cu) gerber found. SRM-CAM mills bottom-side up, so the copper it cuts has to be B.Cu.", C.danger, maxc);
        st.className = "anim-status bad"; st.textContent = "Refused: without B.Cu there is nothing to isolate. Plot B.Cu, or move a top-layer design to B.Cu in KiCad.";
        return;
      }
      if (!on.edge) {
        A.text(view, px + pw / 2, by + bh / 2, "✕", { size: 60, anchor: "middle", fill: C.danger, weight: 700 });
        y = wrap(msg, y, "No board outline (Edge.Cuts) gerber found.", C.danger, maxc);
        st.className = "anim-status bad"; st.textContent = "Refused: the outline is what the cut-out follows and what places the board. Plot Edge.Cuts into the same folder.";
        return;
      }
      A.el(view, "rect", { x: bx, y: by, width: bw, height: bh, rx: 12, fill: C.copperFill, stroke: C.text2, "stroke-width": 2 });
      TR.forEach(function (t) { A.el(view, "polyline", { points: t.map(P).join(" "), fill: "none", stroke: C.copperHi, "stroke-width": 9, "stroke-linejoin": "round" }); });
      var holes = on.pth || on.npth;
      PADS.forEach(function (p, i) {
        var q = P(p).split(",");
        A.el(view, "circle", { cx: q[0], cy: q[1], r: 12, fill: C.copperHi });
        var drilled = (i < 4 && on.pth) || (i >= 4 && on.npth);
        if (drilled) A.el(view, "circle", { cx: q[0], cy: q[1], r: 5, fill: C.sunk });
      });
      if (on.fcu) A.text(view, bx + bw - 8, by - 10, "F.Cu: used only for double-sided", { size: 13, anchor: "end", fill: C.live });
      var n = (on.pth ? 4 : 0) + (on.npth ? 2 : 0);
      line(msg, y, "Loaded feedback — " + n + " holes", C.ok);
      if (!holes) {
        wrap(msg, y + 24, "No drill file found: holes will be empty, and the drill step has nothing to do.", C.caution, maxc);
        st.className = "anim-status caution"; st.textContent = "It loads, but without holes. Generate Drill Files into the same folder: Excellon, millimetres.";
      } else if (!(on.pth && on.npth)) {
        wrap(msg, y + 24, "Only one of KiCad's two drill files: the other holes are missing.", C.caution, maxc);
        st.className = "anim-status caution"; st.textContent = "KiCad splits the holes into -PTH and -NPTH files; keep both in the folder.";
      } else {
        wrap(msg, y + 24, "The job is named after the KiCad project; the plan fills in on the rail.", C.text2, maxc);
        st.className = "anim-status ok"; st.textContent = "Everything a single-sided board needs: B.Cu, Edge.Cuts and the drill files, in one folder." + (on.fcu ? " F.Cu does no harm; it is only used for a double-sided board." : "");
      }
    }
    update();
  });
})();
