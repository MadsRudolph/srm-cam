/* "hw-probe" — the probe is one wire and a switch.

   The red alligator clip puts the copper on the Arduino's D7, which the chip holds HIGH
   through its internal pull-up (pinMode INPUT_PULLUP). The bit needs no clip: it is on
   the machine's ground, which is the Arduino's ground. Bit on copper closes the switch
   and pulls D7 LOW. The firmware only believes it after 3 consecutive LOW reads 1 ms
   apart (srm20_spi_probe.ino, probeTouched), so a stepper-noise spike cannot fake one.
   The spoilboard is wood: nothing else needs insulating. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  A.define("hw-probe", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 490 : 880, H = narrow ? 820 : 420;
    var svg = A.stage(host, W, H, "The probe circuit: the red clip on the copper to D7, the bit grounded");

    // ---- side view ------------------------------------------------------
    A.el(svg, "rect", { x: 10, y: 10, width: 470, height: 400, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(svg, 28, 40, "SIDE VIEW · SPINDLE OFF", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var CU = 300;
    A.el(svg, "rect", { x: 40, y: CU, width: 420, height: 10, fill: C.copper });
    A.el(svg, "rect", { x: 40, y: CU + 10, width: 420, height: 24, fill: C.fr4 });
    A.el(svg, "rect", { x: 30, y: CU + 34, width: 440, height: 50, fill: "#5d4a33" });
    A.text(svg, 250, CU + 66, "spoilboard: wood, does not conduct", { size: 15, anchor: "middle", fill: "#e2d2bb" });
    var head = A.el(svg, "g");
    A.el(head, "rect", { x: 180, y: -140, width: 100, height: 70, rx: 4, fill: "#5a606b" });
    A.el(head, "rect", { x: 204, y: -70, width: 52, height: 30, fill: "#9aa0aa" });
    A.el(head, "rect", { x: 222, y: -40, width: 16, height: 40, fill: C.steel });
    A.text(head, 246, -12, "bit: machine ground", { size: 15, fill: C.text2 });
    // the red clip and its wire
    A.el(svg, "polygon", { points: "400,296 428,296 424,276 404,276", fill: C.danger });
    A.el(svg, "path", { d: "M 414 276 C 414 200, 440 150, 470 120", fill: "none", stroke: C.danger, "stroke-width": 4 });
    A.text(svg, 330, 262, "red clip", { size: 15, weight: 600, fill: "#ffb3ad" });
    var gapT = A.text(svg, 30, CU - 20, "", { size: 16, weight: 600, font: "mono", fill: C.text });
    var spark = A.el(svg, "circle", { cx: 230, cy: CU, r: 14, fill: "none", stroke: C.danger, "stroke-width": 3, opacity: 0 });

    // ---- schematic -------------------------------------------------------
    var S = A.el(svg, "g", { transform: narrow ? "translate(-480,410)" : null });
    A.el(S, "rect", { x: 490, y: 10, width: 380, height: 400, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(S, 508, 40, "THE CIRCUIT", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var wire = { stroke: C.text2, "stroke-width": 3, fill: "none" };
    // 5 V rail, pull-up, D7 node, switch (bit/copper), ground
    A.text(S, 540, 78, "+5 V", { size: 16, weight: 700, font: "mono" });
    A.el(S, "line", Object.assign({ x1: 560, y1: 86, x2: 560, y2: 108 }, wire));
    A.el(S, "rect", { x: 550, y: 108, width: 20, height: 56, fill: "none", stroke: C.text2, "stroke-width": 3 });
    A.text(S, 580, 142, "pull-up, inside the Arduino", { size: 15, fill: C.text2 });
    var hot = A.el(S, "g");
    A.el(hot, "line", Object.assign({ x1: 560, y1: 164, x2: 560, y2: 210 }, wire));
    var node = A.el(S, "circle", { cx: 560, cy: 210, r: 7, fill: C.text });
    A.el(hot, "line", Object.assign({ x1: 560, y1: 210, x2: 780, y2: 210 }, wire));
    A.text(S, 508, 216, "D7", { size: 18, weight: 700, font: "mono" });
    A.text(S, 600, 202, "red clip → copper", { size: 15, fill: "#ffb3ad" });
    // switch: copper contact (fixed) and bit contact (moving)
    A.el(hot, "line", Object.assign({ x1: 780, y1: 210, x2: 780, y2: 250 }, wire));
    A.el(S, "circle", { cx: 780, cy: 250, r: 5, fill: C.text2 });
    var blade = A.el(S, "line", { x1: 780, y1: 300, x2: 820, y2: 258, stroke: C.text2, "stroke-width": 3, "stroke-linecap": "round" });
    A.el(S, "circle", { cx: 780, cy: 300, r: 5, fill: C.text2 });
    A.text(S, 766, 270, "bit on", { size: 15, fill: C.text2, anchor: "end" });
    A.text(S, 766, 288, "copper", { size: 15, fill: C.text2, anchor: "end" });
    A.el(S, "line", Object.assign({ x1: 780, y1: 300, x2: 780, y2: 340 }, wire));
    [0, 1, 2].forEach(function (k) {
      A.el(S, "line", { x1: 764 + k * 6, y1: 340 + k * 7, x2: 796 - k * 6, y2: 340 + k * 7, stroke: C.text2, "stroke-width": 3 });
    });
    A.text(S, 806, 346, "machine", { size: 15, fill: C.text2 });
    A.text(S, 806, 364, "ground", { size: 15, fill: C.text2 });
    // logic readout + debounce
    A.text(S, 508, 272, "D7 reads", { size: 15, fill: C.text2 });
    var lvl = A.text(S, 508, 302, "", { size: 24, weight: 700, font: "mono" });
    A.text(S, 508, 344, "3 reads, 1 ms apart", { size: 15, fill: C.text2 });
    var dots = [0, 1, 2].map(function (k) {
      return A.el(S, "rect", { x: 508 + k * 34, y: 356, width: 26, height: 26, rx: 3, fill: C.sunk, stroke: C.ruleStrong, "stroke-width": 2 });
    });
    var verdict = A.text(S, 616, 376, "", { size: 16, weight: 700, font: "label" });

    // ---- state -------------------------------------------------------------
    var height = 0.6, spike = 0, count = 0, tAcc = 0, lastTouch = null;
    var row = A.controls(host), st = null;
    A.slider(row, "Bit above the copper", 0, 1, 0.05, height, function (v) {
      height = v; count = 0; tAcc = 0; if (st) paint(0);
    }, function (v) { return v.toFixed(2) + " mm"; });
    A.button(row, "Noise spike", function () { spike = 0.45; count = 0; tAcc = 0; paint(0); },
      "Stepper noise pulls D7 low for an instant");
    st = A.status(row);

    function paint(dt) {
      var touching = height <= 0.001;
      var low = touching || spike > 0;
      var y = CU - height * 120;
      A.set(head, { transform: "translate(0," + y + ")" });
      gapT.textContent = touching ? "0.00 mm" : height.toFixed(2) + " mm";
      spark.setAttribute("opacity", touching ? 1 : 0);
      // debounce: count consecutive LOW reads, one every 0.3 s here (1 ms on the chip)
      tAcc += dt;
      while (tAcc > 0.3) {
        tAcc -= 0.3;
        count = low ? Math.min(count + 1, 3) : 0;
      }
      if (A.reduced) count = low && !spike ? 3 : 0;
      if (spike > 0) spike = Math.max(0, spike - dt);
      var col = low ? C.danger : C.ok;
      [hot].forEach(function (g) { g.setAttribute("stroke", col); Array.prototype.forEach.call(g.children, function (c) { c.setAttribute("stroke", col); }); });
      node.setAttribute("fill", col);
      A.set(blade, touching ? { x2: 780, y2: 250 } : { x2: 820, y2: 258 });
      blade.setAttribute("stroke", touching ? C.danger : C.text2);
      lvl.textContent = low ? "LOW" : "HIGH";
      lvl.setAttribute("fill", col);
      dots.forEach(function (d, k) { d.setAttribute("fill", k < count ? C.danger : C.sunk); });
      var isTouch = count >= 3;
      verdict.textContent = isTouch ? "TOUCH" : low ? "counting…" : "no touch";
      verdict.setAttribute("fill", isTouch ? C.danger : low ? C.caution : C.text3);
      if (isTouch !== lastTouch || spike > 0) {
        lastTouch = isTouch;
        st.className = "anim-status" + (isTouch ? " bad" : "");
        st.textContent = isTouch
          ? "Bit on the copper: the switch closes, D7 goes LOW three reads in a row, and SRM-CAM's Z readout turns red: Touch."
          : spike > 0 || (low && !touching)
            ? "A noise spike pulls D7 low for an instant: one LOW read, then HIGH again, so the count resets. No false touch."
            : "Bit in the air: the circuit is open, the pull-up holds D7 HIGH.";
      }
    }
    A.loop(host, function (t, dt) { paint(dt); }, 0);
    paint(0);
  });
})();
