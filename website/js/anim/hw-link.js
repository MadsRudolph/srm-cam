/* "hw-link" — how the Arduino talks to the SRM-20.

   The Arduino Uno is not eavesdropping: it is the SPI master on the machine's own
   remote header, speaking Roland's remote protocol through Roland's SRM20SPIRemote
   library (hardware/SRM20SPIRemote, slave-select D9, ready D6). SRM-CAM talks to the
   Arduino over the black USB cable, one text line at a time (115200 baud, microns;
   engine/spi_probe.py), and the Arduino turns each line into SPI calls. VPanel keeps
   its own white USB cable and plays the files; the two coexist.

   Each button sends one real exchange along the cables, with the serial line and the
   SPI call it becomes. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  var SCENES = {
    pos: {
      label: "Read the position",
      steps: [
        ["black", 1, "Q", "SRM-CAM asks: where is the head? (three times a second)"],
        ["spi", 1, "getActualPosition()", "The Arduino asks the machine over SPI."],
        ["spi", -1, "x, y, z (µm)", "The controller answers with the machine position."],
        ["black", -1, "Q 60520 24420 -38000 0", "Back to SRM-CAM: X 60.52, Y 24.42, Z −38.00, no touch."]
      ],
      dro: "X 60.52  Y 24.42|Z −38.00"
    },
    jog: {
      label: "Jog Z down 0.5 mm",
      steps: [
        ["black", 1, "N 0 0 -500 …", "SRM-CAM: move Z down 0.5 mm (a timed relative move)."],
        ["spi", 1, "jumpTo(x, y, z − 500)", "The Arduino commands the move on the SPI header."],
        ["spi", -1, "ready", "The ready line (D6) says the move is done."],
        ["black", -1, "N … x y z", "SRM-CAM's readout follows the head."]
      ],
      dro: "X 60.52  Y 24.42|Z −38.50"
    },
    touch: {
      label: "Touch the copper",
      steps: [
        ["black", 1, "T", "SRM-CAM: step down from here until the probe touches."],
        ["spi", 1, "jumpTo(… z − 25 µm) ×n", "The Arduino steps Z down 25 µm at a time…"],
        ["probe", -1, "D7 → LOW", "…until the red clip's line D7 is pulled low: the bit is on the copper."],
        ["black", -1, "T 60520 24420 -38000", "The verified surface goes back to SRM-CAM."]
      ],
      dro: "X 60.52  Y 24.42|Touch −38.00"
    },
    vpanel: {
      label: "Play a file (VPanel)",
      steps: [
        ["white", 1, "…_drill.nc", "VPanel sends the file straight to the machine over the white USB."],
        ["white", -1, "running", "The Arduino is not in this path at all: VPanel and the link coexist."]
      ],
      dro: null
    }
  };

  A.define("hw-link", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 490 : 880, H = narrow ? 880 : 450;
    var svg = A.stage(host, W, H, "The laptop, the Arduino and the SRM-20, and the cables between them");

    // node boxes
    var L = narrow ? { x: 20, y: 20, w: 300, h: 170 } : { x: 18, y: 150, w: 230, h: 180 };
    var U = narrow ? { x: 20, y: 330, w: 300, h: 190 } : { x: 330, y: 150, w: 230, h: 200 };
    var M = narrow ? { x: 20, y: 600, w: 450, h: 260 } : { x: 640, y: 30, w: 222, h: 400 };

    function box(b, fill, stroke) {
      return A.el(svg, "rect", { x: b.x, y: b.y, width: b.w, height: b.h, rx: 6, fill: fill, stroke: stroke, "stroke-width": 2 });
    }

    // the machine
    box(M, C.panel, C.ruleStrong);
    A.text(svg, M.x + 16, M.y + 30, "SRM-20", { size: 18, weight: 700, font: "label" });
    var ctrl = narrow ? { x: M.x + 16, y: M.y + 50, w: 250, h: 130 } : { x: M.x + 16, y: M.y + 150, w: 190, h: 150 };
    A.el(svg, "rect", { x: ctrl.x, y: ctrl.y, width: ctrl.w, height: ctrl.h, rx: 4, fill: "#16301f", stroke: "#2e6b45" });
    A.text(svg, ctrl.x + 12, ctrl.y + 24, "controller", { size: 15, weight: 600, fill: "#9fd6b1" });
    // SPI remote header (pins) and USB port
    var hdr = narrow ? { x: ctrl.x + 12, y: ctrl.y + 40 } : { x: ctrl.x + 12, y: ctrl.y + 40 };
    for (var i = 0; i < 5; i++) {
      A.el(svg, "rect", { x: hdr.x + i * 14, y: hdr.y, width: 9, height: 9, fill: C.caution });
      A.el(svg, "rect", { x: hdr.x + i * 14, y: hdr.y + 13, width: 9, height: 9, fill: C.caution });
    }
    A.text(svg, hdr.x, hdr.y + 46, "SPI remote header", { size: 15, fill: C.text2 });
    var usbM = narrow ? { x: M.x + M.w - 110, y: M.y + 70 } : { x: M.x + 30, y: M.y + 70 };
    A.el(svg, "rect", { x: usbM.x, y: usbM.y, width: 30, height: 18, rx: 2, fill: C.steelDim, stroke: C.steel });
    A.text(svg, usbM.x + 40, usbM.y + 15, "USB", { size: 15, fill: C.text2 });
    // the probe clip on the copper
    var cu = narrow ? { x: M.x + 280, y: M.y + 200, w: 150 } : { x: M.x + 30, y: M.y + 350, w: 160 };
    A.el(svg, "rect", { x: cu.x, y: cu.y, width: cu.w, height: 10, fill: C.copper });
    A.el(svg, "rect", { x: cu.x, y: cu.y + 10, width: cu.w, height: 26, fill: C.board });
    A.text(svg, cu.x + cu.w / 2, cu.y + 29, "copper", { size: 15, anchor: "middle", fill: "#e8dccb" });
    var clip = { x: cu.x + cu.w - 26, y: cu.y - 4 };
    A.el(svg, "polygon", { points: [clip.x, clip.y, clip.x + 22, clip.y, clip.x + 18, clip.y - 16, clip.x + 4, clip.y - 16].join(","), fill: C.danger });

    // the Arduino
    box(U, "#0b4d63", "#2a8fb0");
    A.text(svg, U.x + 16, U.y + 30, "Arduino Uno", { size: 18, weight: 700, font: "label", fill: "#e6f6fb" });
    A.text(svg, U.x + 16, U.y + 52, "srm20_spi_probe, v3", { size: 15, fill: "#9fd3e3", font: "mono" });
    var pins = [["D9", "slave select"], ["D6", "ready"], ["D11–13", "SPI data, clock"], ["D7", "probe (red clip)"]];
    pins.forEach(function (p, k) {
      var y = U.y + 84 + k * 26;
      A.text(svg, U.x + 16, y, p[0], { size: 15, weight: 700, font: "mono", fill: k === 3 ? "#ffb3ad" : "#e6f6fb" });
      A.text(svg, U.x + 92, y, p[1], { size: 15, fill: "#bfe4ef" });
    });

    // the laptop
    box(L, C.raised, C.ruleStrong);
    A.el(svg, "rect", { x: L.x + 14, y: L.y + 14, width: L.w - 28, height: L.h - 64, rx: 3, fill: C.sunk });
    A.text(svg, L.x + 26, L.y + 42, "SRM-CAM", { size: 17, weight: 700 });
    A.text(svg, L.x + 26, L.y + 66, "VPanel", { size: 17, weight: 700 });
    var dro = A.text(svg, L.x + 26, L.y + 94, "", { size: 15, weight: 600, font: "mono", fill: C.ok });
    var dro2 = A.text(svg, L.x + 26, L.y + 114, "", { size: 15, weight: 600, font: "mono", fill: C.ok });
    function setDro(v) { var parts = v.split("|"); dro.textContent = parts[0]; dro2.textContent = parts[1] || ""; }
    A.text(svg, L.x + L.w / 2, L.y + L.h - 18, "the mill's PC, or your laptop", { size: 15, anchor: "middle", fill: C.text2 });

    // cables
    var p = {};
    function cable(key, d, color, width, label, lx, ly) {
      var under = A.el(svg, "path", { d: d, fill: "none", stroke: "#000", "stroke-width": width + 4, "stroke-linecap": "round", opacity: 0.5 });
      var path = A.el(svg, "path", { d: d, fill: "none", stroke: color, "stroke-width": width, "stroke-linecap": "round" });
      if (label) A.text(svg, lx, ly, label, { size: 15, weight: 600, fill: C.text2 });
      p[key] = { path: path, under: under, color: color };
    }
    if (narrow) {
      cable("black", "M 170 190 C 170 250, 170 270, 170 330", "#2a2d33", 7, "black USB · serial", 184, 268);
      cable("white", "M 320 150 C 420 160, 460 300, 460 420 S " + (usbM.x + 15) + " 560, " + (usbM.x + 15) + " " + usbM.y, "#e8ebef", 7, "white USB", 360, 300);
      cable("spi", "M 170 520 C 170 560, " + (hdr.x + 30) + " 610, " + (hdr.x + 30) + " " + hdr.y, C.caution, 5, "SPI ribbon", 186, 574);
      cable("probe", "M 320 470 C 420 480, " + (clip.x + 11) + " 700, " + (clip.x + 11) + " " + (clip.y - 16), C.danger, 3, null);
    } else {
      cable("black", "M 248 250 C 290 250, 290 250, 330 250", "#2a2d33", 7, "black USB", 254, 284);
      cable("white", "M 200 150 C 240 40, 500 40, " + usbM.x + " " + (usbM.y + 9), "#e8ebef", 7, "white USB", 360, 58);
      cable("spi", "M 560 230 C 600 230, " + (hdr.x - 30) + " " + (hdr.y + 10) + ", " + hdr.x + " " + (hdr.y + 10), C.caution, 5, "SPI ribbon", 568, 212);
      cable("probe", "M 560 327 C 610 330, " + (clip.x + 11) + " 400, " + (clip.x + 11) + " " + (clip.y - 16), C.danger, 3, "D7 → red clip", 568, 360);
    }
    // the bit's side: no clip, through the machine's own ground
    A.text(svg, M.x + 16, narrow ? M.y + 236 : M.y + 130, "bit: no clip, grounded", { size: 15, fill: C.text3 });

    // the travelling packet
    var pk = A.el(svg, "g", { opacity: 0 });
    A.el(pk, "circle", { r: 9, fill: C.live, stroke: "#fff", "stroke-width": 2 });
    var tag = A.el(svg, "g", { opacity: 0 });
    var tagR = A.el(tag, "rect", { rx: 3, height: 26, fill: C.ink, stroke: C.live });
    var tagT = A.text(tag, 0, 0, "", { size: 15, weight: 600, font: "mono", fill: C.text });

    var row = A.controls(host), st = A.status(row);
    var btns = [];
    Object.keys(SCENES).forEach(function (k) {
      btns.push(A.button(row, SCENES[k].label, function () { play(k); }));
    });
    st.textContent = "Press a button to send one exchange along the cables.";
    row.appendChild(st);

    var scene = null, t0 = 0, SEG = 1.5;
    function highlight(key) {
      Object.keys(p).forEach(function (k) {
        p[k].path.setAttribute("opacity", !key || k === key ? 1 : 0.35);
      });
    }
    function play(k) {
      scene = SCENES[k]; t0 = performance.now() / 1000;
      if (A.reduced) { finish(); return; }
      runner.restart();
    }
    function finish() {
      var s = scene.steps[scene.steps.length - 1];
      st.textContent = scene.steps.map(function (x) { return x[3]; }).join(" ");
      pk.setAttribute("opacity", 0); tag.setAttribute("opacity", 0);
      highlight(null);
      if (scene.dro) setDro(scene.dro);
      return s;
    }
    var runner = A.loop(host, function () {
      if (!scene) return;
      var t = performance.now() / 1000 - t0;
      var i = Math.floor(t / SEG);
      if (i >= scene.steps.length) { finish(); scene = null; return; }
      var s = scene.steps[i], f = A.ease((t - i * SEG) / (SEG * 0.8));
      var path = p[s[0]].path, len = path.getTotalLength();
      var pt = path.getPointAtLength(s[1] > 0 ? f * len : (1 - f) * len);
      highlight(s[0]);
      pk.setAttribute("opacity", 1);
      pk.setAttribute("transform", "translate(" + pt.x + "," + pt.y + ")");
      tagT.textContent = s[2];
      var tw = Math.max(40, s[2].length * 9.2 + 16);
      var tx = A.clamp(pt.x - tw / 2, 4, W - tw - 4), ty = pt.y - 44;
      if (ty < 4) ty = pt.y + 18;
      A.set(tagR, { x: tx, y: ty, width: tw });
      A.set(tagT, { x: tx + 8, y: ty + 18 });
      tag.setAttribute("opacity", 1);
      st.textContent = (i + 1) + "/" + scene.steps.length + " · " + s[3];
      if (i === scene.steps.length - 1 && scene.dro && f > 0.9) setDro(scene.dro);
    });
    setDro("X —  Y —|Z —");
  });
})();
