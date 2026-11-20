/* The rail, built the way the app builds it (getting-started.html). Titles and
   details are the app's own: gui2/runplan.py (the plan, LASER_JOBS) and
   gui2/window.py NOVICE_RAIL (Novice's words for the first rows). Pick the method,
   the tier and the layers the folder has; the rows follow. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  function rows(o) {
    var laser = o.method === "laser", pro = o.tier === "pro", R = [];
    R.push(pro ? ["Set up the job", "Board, copper, tool, placement"] : ["Your board", "How it is made, one side or two"]);
    R.push(pro ? ["Check before cutting", "Fit, depth, reach, shorts"] : ["Check it", "Can it be made as drawn?"]);
    R.push({ head: "On the mill" });
    R.push([laser ? "Drill and cut out" : "Mill it",
      pro ? (laser ? "Holes and outline, on tabs - stays in the sheet" : "Finds the stock, probes, cuts the whole board") : "Stock in the bracket, then Start", "MILL"]);
    if (pro) R.push({ head: "One step at a time", fold: laser ? "2 steps" : "3 steps" });
    var lz = [];
    if (laser) lz.push(["Etch the traces", "On the drilled holes · the whole sheet", "LASER"]);
    if (o.mask) lz.push(["Solder mask", "Openings over the pads", "LASER"]);
    if (o.silk) lz.push(["Silkscreen", "The component side", "LASER"]);
    if (o.paste) lz.push(["Paste stencil", "Steel foil", "LASER"]);
    if (lz.length) { R.push({ head: "On the laser" }); R = R.concat(lz); }
    if (pro) {
      R.push({ head: "When you need it" });
      R.push(["Fix spots", "Box what did not cut through, and run it again"]);
      R.push(["Level the bed", "Measure the surface so cut depth follows it"]);
      R.push(["Drill a board made elsewhere", "Measure three pads; the holes move onto the board"]);
    }
    return R;
  }

  A.define("rl-rail", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = 640;
    var svg = A.stage(host, W, H, "The rail of SRM-CAM for the chosen method, tier and layers, row by row as the app shows it");
    var rx = 16, rw = narrow ? W - 32 : 470;
    var g = A.el(svg, "g", {});
    var nx = narrow ? 16 : 520;
    var note = [];
    if (!narrow) for (var i = 0; i < 9; i++) note.push(A.text(svg, nx, 60 + i * 26, "", { size: 15, fill: C.text2 }));
    var o = { method: "laser", tier: "novice", mask: true, silk: true, paste: false };

    function draw() {
      while (g.firstChild) g.removeChild(g.firstChild);
      A.el(g, "rect", { x: rx, y: 14, width: rw, height: H - 28, rx: 6, fill: C.panel, stroke: C.ruleHi });
      var y = 30, R = rows(o), fs = narrow ? 19 : 16;
      R.forEach(function (r) {
        if (r.head) {
          y += 12;
          A.text(g, rx + 16, y + 14, (r.fold ? "▸ " : "") + r.head.toUpperCase(), { size: fs - 3, weight: 600, fill: C.text3, font: "label", spacing: "0.14em" });
          if (r.fold) A.text(g, rx + rw - 14, y + 14, r.fold, { size: fs - 3, anchor: "end", fill: C.text3 });
          else A.el(g, "line", { x1: rx + 16 + r.head.length * (fs - 3) * 0.78, y1: y + 9, x2: rx + rw - 16, y2: y + 9, stroke: C.rule });
          y += 26;
          return;
        }
        A.text(g, rx + 16, y + 18, "›", { size: fs + 2, fill: C.text3 });
        A.text(g, rx + 34, y + 18, r[0], { size: fs, fill: C.text });
        var d = r[1];
        var maxc = narrow ? 40 : 46;
        if (d.length > maxc) d = d.slice(0, maxc - 1) + "…";
        A.text(g, rx + 34, y + 18 + fs + 3, d, { size: fs - 2.5, fill: C.text3 });
        if (r[2]) {
          var tw = r[2] === "MILL" ? 40 : 48;
          A.el(g, "rect", { x: rx + rw - tw - 14, y: y + 4, width: tw, height: 20, rx: 3,
            fill: r[2] === "MILL" ? C.copperFill : C.liveFill, stroke: r[2] === "MILL" ? C.copperDim : "#1d466e" });
          A.text(g, rx + rw - 14 - tw / 2, y + 19, r[2], { size: 12, anchor: "middle", weight: 600, font: "label", spacing: "0.1em", fill: r[2] === "MILL" ? C.copperHi : C.live });
        }
        y += 2 * fs + 16;
      });
      var foot = o.tier === "pro" ? "Export for VPanel…" : "Save the files…";
      A.el(g, "rect", { x: rx + 16, y: H - 66, width: rw - 32, height: 34, rx: 4, fill: C.raised, stroke: C.ruleStrong });
      A.text(g, rx + rw / 2, H - 43, foot, { size: fs - 2, anchor: "middle" });
      if (!narrow) {
        var N = [];
        N.push(o.method === "laser" ? "A laser board: one MILL row," : "A mill-only board: the mill makes it all,");
        N.push(o.method === "laser" ? "Drill and cut out, then the laser." : "with one MILL row, Mill it.");
        N.push("");
        N.push(o.tier === "pro" ? "Pro: every step as its own page," : "Novice: three rows before the laser.");
        N.push(o.tier === "pro" ? "folded under One step at a time," : "Rows a Novice does not need are hidden.");
        N.push(o.tier === "pro" ? "and the When you need it rows." : "");
        N.push("");
        N.push("A LASER row appears for each layer");
        N.push("the folder has (Send to SRM-CAM plots them).");
        note.forEach(function (t, i) { t.textContent = N[i] || ""; });
      }
      // fit the height to the rows
      var need = y + 90;
      svg.setAttribute("viewBox", "0 0 " + W + " " + Math.max(need, narrow ? 300 : 300));
      svg.style.aspectRatio = W + " / " + Math.max(need, 300);
      A.set(g.firstChild, { height: need - 28 });
      var btn = g.childNodes[g.childNodes.length - 2], lab = g.lastChild;
      A.set(btn, { y: need - 66 }); A.set(lab, { y: need - 43 });
    }
    var row = A.controls(host);
    A.segmented(row, [["laser", "Laser"], ["flat", "Flat mill"]], "laser", function (v) { o.method = v; draw(); });
    A.segmented(row, [["novice", "Novice"], ["pro", "Pro"]], "novice", function (v) { o.tier = v; draw(); });
    ["mask", "silk", "paste"].forEach(function (k) {
      var b = A.button(row, { mask: "Has mask", silk: "Has silkscreen", paste: "Has paste" }[k], function () {
        o[k] = !o[k]; b.classList.toggle("primary", o[k]); draw();
      });
      if (o[k]) b.classList.add("primary");
    });
  });
})();
