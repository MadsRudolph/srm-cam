/* VPanel's Cut dialog. Add puts the exported files in the Output File List in
   alphabetical order, as in the recording: cut-out, drill, traces. VPanel runs the
   list from the top, so the cut-out has to go to the bottom before Output. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var NAME = "feedback_circuit_2";
  var KIND = { airpass: "dry run", cutout: "cut-out", drill: "drill", traces: "traces" };

  A.define("joblist", function (host) {
    // a phone gets a narrower dialog without the preview, so the file names stay readable
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 440 : 880, H = 360;
    var s = A.stage(host, W, H, "A simplified VPanel Cut dialog with the Output File List");
    var GREY = "#ececec", DARK = "#1e1e1e", EDGE = "#a9a9a9", SEL = "#0a64d6";
    var DX = narrow ? 12 : 40, DW = W - 2 * DX, LX = DX + (narrow ? 10 : 20), LW = narrow ? DW - 20 : 560;
    var FS = narrow ? 16 : 15;
    // the dialog
    A.el(s, "rect", { x: DX, y: 24, width: DW, height: 312, rx: 4, fill: GREY, stroke: "#8a8a8a" });
    A.el(s, "rect", { x: DX, y: 24, width: DW, height: 34, rx: 4, fill: "#ffffff" });
    A.text(s, DX + 16, 47, "Cut", { size: 16, fill: DARK, weight: 500 });
    A.text(s, DX + DW - 16, 47, "✕", { size: 16, fill: DARK, anchor: "end" });
    A.text(s, LX, 84, "Output File List :", { size: 15, fill: DARK });
    A.el(s, "rect", { x: LX, y: 94, width: LW, height: 170, fill: "#ffffff", stroke: EDGE });
    if (!narrow) {
      A.text(s, 640, 84, "Preview :", { size: 15, fill: DARK });
      A.el(s, "rect", { x: 640, y: 94, width: 180, height: 170, fill: "#ffffff", stroke: EDGE });
    }
    var prevText = A.el(s, "g");
    // dialog buttons, drawn for the look; the real controls are under the figure
    var bw = narrow ? 64 : 84, bs = narrow ? 70 : 96;
    ["Add", "Delete", "↑", "↓"].forEach(function (b, i) {
      var x = LX + i * bs;
      A.el(s, "rect", { x: x, y: 278, width: bw, height: 30, rx: 2, fill: "#fdfdfd", stroke: EDGE });
      A.text(s, x + bw / 2, 298, b, { size: 15, fill: DARK, anchor: "middle" });
    });
    var OX = narrow ? LX + 4 * bs : 640;
    A.el(s, "rect", { x: OX, y: 278, width: bw, height: 30, rx: 2, fill: "#fdfdfd", stroke: EDGE });
    A.text(s, OX + bw / 2, 298, "Output", { size: 15, fill: DARK, anchor: "middle" });
    if (!narrow) {
      A.el(s, "rect", { x: 736, y: 278, width: 84, height: 30, rx: 2, fill: "#fdfdfd", stroke: EDGE });
      A.text(s, 778, 298, "Cancel", { size: 15, fill: DARK, anchor: "middle" });
    }
    var rowsG = A.el(s, "g");
    var badge = A.el(s, "g");

    var files = [], sel = -1;
    var row = A.controls(host);
    var bAdd = A.button(row, "Add", add, "", "Add the three exported files");
    var bDry = A.button(row, "Add the dry run", addDry, "", "Add " + NAME + "_airpass.nc");
    var bUp = A.button(row, "↑", function () { move(-1); }, "key", "Move the selected file up");
    var bDown = A.button(row, "↓", function () { move(1); }, "key", "Move the selected file down");
    var bDel = A.button(row, "Delete", del, "", "Remove the selected file");
    var bOut = A.button(row, "Output", output, "primary", "Start the job");
    A.button(row, "Show me", showMe, "", "Do it the way it was done in the video");
    A.button(row, "Reset", reset);
    var st = A.status(row);

    function say(msg, kind) { st.textContent = msg; st.className = "anim-status" + (kind ? " " + kind : ""); }

    function draw() {
      while (rowsG.firstChild) rowsG.removeChild(rowsG.firstChild);
      while (badge.firstChild) badge.removeChild(badge.firstChild);
      while (prevText.firstChild) prevText.removeChild(prevText.firstChild);
      files.forEach(function (f, i) {
        var y = 100 + i * 32;
        var g = A.el(rowsG, "g", { tabindex: 0, role: "option", "aria-selected": i === sel, "aria-label": NAME + "_" + f + ".nc, row " + (i + 1) });
        g.style.cursor = "pointer";
        A.el(g, "rect", { x: LX + 2, y: y, width: LW - 4, height: 28, fill: i === sel ? SEL : "#ffffff" });
        A.text(g, LX + 10, y + 20, (narrow ? "…_2_" : "p\\feedback\\" + NAME + "_") + f + ".nc", { size: FS, fill: i === sel ? "#ffffff" : DARK, font: "mono" });
        A.text(g, LX + LW - 8, y + 20, (i + 1) + ". " + KIND[f], { size: FS, fill: i === sel ? "#dbe8ff" : "#6b6b6b", anchor: "end" });
        g.addEventListener("click", function () { sel = i; draw(); });
        g.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") { sel = i; draw(); e.preventDefault(); }
        });
      });
      if (!narrow && sel >= 0 && files[sel]) {
        var p = { airpass: ["%", "O0001", "(dry run)", "(spindle off,", " 5 mm up)"], cutout: ["%", "O0001", "(cut-out)", "(frees the", " board)"],
          drill: ["%", "O0001", "(drill)", "(bit 0.8 mm)"], traces: ["%", "O0001", "(isolation)", "(bit 0.8 mm)"] }[files[sel]];
        p.forEach(function (l, k) { A.text(prevText, 650, 118 + k * 20, l, { size: 15, fill: DARK, font: "mono" }); });
      }
      bUp.disabled = sel <= 0;
      bDown.disabled = sel < 0 || sel >= files.length - 1;
      bDel.disabled = sel < 0;
      bOut.disabled = !files.length;
      bAdd.disabled = files.indexOf("drill") >= 0;
      bDry.disabled = files.indexOf("airpass") >= 0;
    }

    function add() {
      ["cutout", "drill", "traces"].forEach(function (f) { if (files.indexOf(f) < 0) files.push(f); });
      files.sort(function (a, b) { return a < b ? -1 : 1; });   // VPanel lists them alphabetically
      sel = -1; draw();
      say("The files landed alphabetically, and VPanel runs the list from the top: the cut-out would go first.", "warn");
    }
    function addDry() {
      if (files.indexOf("airpass") < 0) files.push("airpass");
      files.sort(function (a, b) { return a < b ? -1 : 1; });
      sel = files.indexOf("airpass"); draw();
      say("The dry run traces the outline with the spindle off, 5 mm up. It belongs at the top.");
    }
    function move(d) {
      var j = sel + d;
      if (sel < 0 || j < 0 || j >= files.length) return;
      var t = files[sel]; files[sel] = files[j]; files[j] = t; sel = j; draw();
      say("Moved " + KIND[files[sel]] + " to row " + (sel + 1) + ".");
    }
    function del() {
      if (sel < 0) return;
      var f = files.splice(sel, 1)[0]; sel = -1; draw();
      say("Removed the " + KIND[f] + " file.");
    }
    function output() {
      var run = files.filter(function (f) { return f !== "airpass"; });
      var mark = function (ok) {
        A.el(badge, "rect", { x: OX, y: 278, width: bw, height: 30, rx: 2, fill: "none", stroke: ok ? "#1b8a4c" : "#d93030", "stroke-width": 3 });
      };
      if (!files.length) return;
      if (files.indexOf("airpass") > 0) { mark(false); say("Refused: the dry run goes first, before anything cuts.", "bad"); return; }
      if (run[0] === "cutout") { mark(false); say("Refused: never start with the cut-out. It frees the boards, and the rest would cut a loose board.", "bad"); return; }
      if (run.indexOf("cutout") >= 0 && run.indexOf("cutout") !== run.length - 1) { mark(false); say("Refused: the cut-out must be last. It frees the boards.", "bad"); return; }
      if (run.length < 3) { mark(false); say("Something is missing: the job needs the drill, the traces and the cut-out.", "warn"); return; }
      mark(true);
      if (run[0] === "drill") say("OK: drill, traces, cut-out. The order we prefer. VPanel starts at the top.", "ok");
      else say("OK: traces first works, but we prefer the drill first. The cut-out is last, as it must be.", "ok");
    }
    var timer = 0;
    function showMe() {
      clearTimeout(timer);
      files = ["cutout", "drill", "traces"]; sel = -1; draw();
      say("As in the video: the files land as cut-out, drill, traces.", "warn");
      var steps = [
        function () { sel = 1; draw(); say("Select the drill…"); },
        function () { move(-1); say("…and move it up. Now the cut-out is second."); },
        function () { sel = 1; draw(); say("Select the cut-out…"); },
        function () { move(1); say("…and move it to the bottom."); },
        function () { output(); }
      ];
      var k = 0;
      (function next() {
        if (k >= steps.length) return;
        timer = setTimeout(function () { steps[k++](); next(); }, A.reduced ? 10 : 1300);
      })();
    }
    function reset() { clearTimeout(timer); files = []; sel = -1; draw(); say("Press Add to put the exported files in the list."); }
    reset();
  });
})();
