/* Calibrate misses: which line of the report, what the photo shows, and the fix. The
   messages are the app's own (gui2/laser_autocal.py, gui2/stencil_laser.py proof,
   engine/xtool_camera.py); the numbers in them are examples. The photo beside each is a
   schematic of what to look for. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var CASES = [
    { k: "notfound", btn: "Board not found",
      msg: "✗ Find the board: The board was not found on the bed: at best 3 of 12 holes matched. Check it lies under the camera, drilled face up, or drag the drawing onto it and press Calibrate again.",
      look: "The sheet is turned well off square, or lies partly outside the camera's view.",
      fix: "Lay the sheet square to the bed's edges (Calibrate allows about 4°), copper face up, the board near the middle. Press Calibrate again. Dragging the drawing makes no difference: the search covers the whole bed.",
      draw: { turn: 14, dx: 62 } },
    { k: "lam", btn: "Laminate in the photo",
      msg: "No message: the report can even say “Board found”.",
      look: "The photo shows pale laminate where the copper should shine: the sheet is upside down. A symmetric hole pattern fits either way up.",
      fix: "Turn the sheet over, copper face up, the same way up as it came off the mill. Press Calibrate again.",
      draw: { lam: true } },
    { k: "marks", btn: "Marks did not show",
      msg: "The proof marks in the waste beside the board did not show in the photo (1 of 3). Nothing was moved. Raise Mark passes under Proof options, or mark the isolation instead.",
      look: "Faint or missing marks in the waste. Glare, or a dull spot of copper.",
      fix: "Press Calibrate again. If it repeats, ask for Pro: Mark passes and the marks' place are under Proof options, which Novice does not show.",
      draw: { faint: true } },
    { k: "holes", btn: "Holes not found",
      msg: "✗ Camera and holes: Proof on 3 marks in the waste beside the board: the camera was 0.42 mm off and is corrected. The drilled holes could not be found (found 5 of 12), so the job was not moved: drag it closer and press Align.",
      look: "Holes that read grey, not dark: full of swarf, or not drilled through.",
      fix: "Brush or vacuum the swarf out of the holes and press Calibrate again. Holes not through: back to the mill to drill them again.",
      draw: { swarf: 7 } },
    { k: "few", btn: "Only a of b holes",
      msg: "⚠ Only 10 of 12 holes were seen on the lock: check the pads sit round the holes in the photo.",
      look: "A few holes grey or hidden. The job did move; the verdict asks you to check first.",
      fix: "Zoom in on the photo: if every pad sits round its hole, press Etch the traces. If not, clean the holes and Calibrate again.",
      draw: { swarf: 2 } },
    { k: "camera", btn: "Camera over 1.5 mm",
      msg: "⚠ The camera's correction changed by more than 1.5 mm: look at the photo closely before cutting.",
      look: "A big correction: the marks landed far from where the camera expected.",
      fix: "Check the drawing sits on the pads in the photo, and press Show where: the blue diode traces the outline on the board. If it sits right, etch. If not, Calibrate again.",
      draw: { shift: true } },
    { k: "iso", btn: "Marks on the isolation",
      msg: "✓ Camera and holes: Proof on 3 marks in the isolation: the camera was 0.42 mm off and is corrected. …",
      look: "The board was broken out of its sheet, or the sheet ends too close to it: no copper beside it to mark on.",
      fix: "Nothing to fix: the marks went on copper the etch removes anyway. Next time keep the board in its sheet, with waste round it.",
      draw: { out: true } },
    { k: "dot", btn: "No dot (Autofocus)",
      msg: "✗ Autofocus: No dot in the photo: is the lid closed and the material under the head?",
      look: "The blue dot did not show at the focus cross.",
      fix: "Close the lid, check the sheet is under the head, and press Calibrate again.",
      draw: { nodot: true } }
  ];
  var HOLES = [[-26, -16], [26, -16], [-26, 16], [26, 16], [-14, -6], [-10, -6], [-6, -6], [6, 8], [10, 8], [14, 8], [-18, 10], [18, -8]];

  A.define("ts-calib", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, PW = narrow ? 470 : 380, PH = PW * 0.72, X0 = 20, Y0 = 40;
    var H = narrow ? Y0 + PH + 30 : Y0 + PH + 30;
    var svg = A.stage(host, W, H, "A schematic photo of the laser bed for each Calibrate message: what to look for");
    A.text(svg, X0, 26, "WHAT THE PHOTO SHOWS · SCHEMATIC", { size: 14, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    A.el(svg, "rect", { x: X0, y: Y0, width: PW, height: PH, fill: C.sunk, stroke: C.ruleStrong });
    var cp = A.el(A.el(svg, "defs"), "clipPath", { id: "tsc-clip" });
    A.el(cp, "rect", { x: X0, y: Y0, width: PW, height: PH });
    var photo = A.el(svg, "g", { "clip-path": "url(#tsc-clip)" });
    var K = PW / 160;
    var TX = narrow ? X0 : X0 + PW + 26, TW = W - TX - 16;
    var fo = null;
    if (!narrow) {
      fo = A.el(svg, "foreignObject", { x: TX, y: Y0 - 4, width: TW, height: PH + 10 });
    }
    var row = A.controls(host);
    var box = document.createElement("div");
    box.className = "ts-calib-text";
    if (fo) {
      var inner = document.createElementNS("http://www.w3.org/1999/xhtml", "div");
      inner.appendChild(box); fo.appendChild(inner);
    }
    var pick = document.createElement("div");
    pick.className = "anim-seg ts-calib-pick";
    var btns = CASES.map(function (c, i) {
      var b = document.createElement("button");
      b.type = "button"; b.textContent = c.btn;
      b.addEventListener("click", function () { show(i); });
      pick.appendChild(b);
      return b;
    });
    row.appendChild(pick);
    if (!fo) row.appendChild(box);

    function drawPhoto(d) {
      while (photo.firstChild) photo.removeChild(photo.firstChild);
      var cx = X0 + PW / 2 + (d.dx || 0) * K, cy = Y0 + PH / 2;
      var g = A.el(photo, "g", { transform: "translate(" + cx + " " + cy + ") rotate(" + (d.turn || 0) + ") scale(" + K * 1.15 + ")" });
      if (!d.out) A.el(g, "rect", { x: -60, y: -40, width: 120, height: 80, fill: d.lam ? "#9a9a6a" : C.copper });
      A.el(g, "rect", { x: -31, y: -21, width: 62, height: 42, fill: "none", stroke: C.ink, "stroke-width": d.out ? 0 : 1.4 });
      A.el(g, "rect", { x: -30, y: -20, width: 60, height: 40, fill: d.lam ? "#b5b386" : C.copper });
      HOLES.forEach(function (h, i) {
        var grey = d.swarf && i < d.swarf;
        A.el(g, "circle", { cx: h[0], cy: h[1], r: 1.1, fill: grey ? C.steelDim : C.ink });
      });
      if (!d.lam && !d.nodot) {
        var marks = d.out ? [[-26, -12], [26, 12], [26, -12]] : [[-35.75, -16], [35.75, 16], [26, -25.75]];
        marks.forEach(function (m, i) {
          var faint = d.faint && i > 0;
          A.el(g, "rect", { x: m[0] - 0.75, y: m[1] - 0.75, width: 1.5, height: 1.5, fill: faint ? C.copper : "#3a2a1c", stroke: d.out ? C.caution : "none", "stroke-width": 0.3 });
          A.el(g, "circle", { cx: m[0], cy: m[1], r: 3.4, fill: "none", stroke: faint ? C.danger : C.text2, "stroke-width": 0.35, "stroke-dasharray": "1 1" });
        });
      }
      if (d.shift) {
        var j = A.el(g, "g", { transform: "translate(2.2 1.4)" });
        A.el(j, "rect", { x: -30, y: -20, width: 60, height: 40, fill: "none", stroke: C.live, "stroke-width": 0.5, "stroke-dasharray": "2 1.4" });
        HOLES.forEach(function (h) { A.el(j, "circle", { cx: h[0], cy: h[1], r: 1.8, fill: "none", stroke: C.live, "stroke-width": 0.35 }); });
      }
      if (d.nodot) {
        A.el(g, "circle", { cx: 0, cy: 0, r: 5, fill: "none", stroke: C.danger, "stroke-width": 0.5, "stroke-dasharray": "1 1" });
        A.el(g, "line", { x1: -7, y1: 0, x2: 7, y2: 0, stroke: C.ok, "stroke-width": 0.5 });
        A.el(g, "line", { x1: 0, y1: -7, x2: 0, y2: 7, stroke: C.ok, "stroke-width": 0.5 });
      }
    }
    function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
    function show(i) {
      var c = CASES[i];
      btns.forEach(function (b, k) { b.classList.toggle("on", k === i); });
      drawPhoto(c.draw);
      box.innerHTML = '<p class="m">' + esc(c.msg) + '</p><p><span class="k">Look</span> ' + esc(c.look) + '</p><p><span class="k">Fix</span> ' + esc(c.fix) + "</p>";
    }
    show(0);
  });
})();
