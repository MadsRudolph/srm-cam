/* Two cables to the mill, one to the laser, on each OS (getting-started.html,
   hardware.html). gui2/window.py Machine menu, engine/rmlspool.py, linuxmill.py,
   macmill.py, millsettings.py; the laser shows up as a USB network adapter
   (xTool F1 Ultra at 201.234.3.1). Schematic. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var OS = {
    win: { name: "Windows", mill: ["a printer with “SRM-20” in its name", ""], set: "Install Roland's SRM-20 driver once" },
    linux: { name: "Linux", mill: ["/dev/usb/lp0, no driver", ""], set: "Machine › Set up USB access… once" },
    mac: { name: "macOS", mill: ["a CUPS queue “SRM-20”", ""], set: "Machine › Set up the mill on this Mac… once" }
  };
  A.define("hw-cables", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 600 : 330;
    var svg = A.stage(host, W, H, "The PC with three USB cables: the Arduino probe link and the mill's own USB to the SRM-20, and the xTool laser's USB");
    A.text(svg, W - 16, 26, "schematic", { size: 13, anchor: "end", fill: C.text4, font: "label", spacing: "0.1em" });
    // PC
    var pc = narrow ? [W / 2 - 110, 44, 220, 90] : [24, 110, 190, 110];
    A.el(svg, "rect", { x: pc[0], y: pc[1], width: pc[2], height: pc[3], rx: 8, fill: C.panelHi, stroke: C.ruleStrong, "stroke-width": 1.5 });
    A.text(svg, pc[0] + pc[2] / 2, pc[1] + 34, "PC with SRM-CAM", { size: 15, anchor: "middle", weight: 600 });
    var osT = A.text(svg, pc[0] + pc[2] / 2, pc[1] + 60, "", { size: 14, anchor: "middle", fill: C.text2 });
    // three cables to three ends
    var ends = narrow
      ? [[16, 210, W - 32, 110], [16, 340, W - 32, 110], [16, 470, W - 32, 110]]
      : [[330, 30, 530, 82], [330, 124, 530, 82], [330, 218, 530, 82]];
    var cols = [C.text3, C.steel, C.live];
    var heads = ["Arduino in the mill (black USB)", "The mill's own USB (white)", "xTool F1 Ultra fiber laser (USB)"];
    var subs = [["Serial: position, jog, probing, STOP.", "Bar: Connect. Same on every OS."], null,
      ["Shows up as a network adapter.", "No driver, no xTool Creative Space."]];
    var T = [];
    ends.forEach(function (e, i) {
      var sx = narrow ? pc[0] + pc[2] / 2 + (i - 1) * 60 : pc[0] + pc[2], sy = narrow ? pc[1] + pc[3] : pc[1] + 30 + i * 25;
      var ex = narrow ? e[0] + 40 + i * 0 : e[0], ey = narrow ? e[1] : e[1] + e[3] / 2;
      if (narrow) { ex = sx; }
      A.el(svg, "path", { d: narrow ? "M" + sx + " " + sy + " V" + ey : "M" + sx + " " + sy + " C" + (sx + 60) + " " + sy + " " + (ex - 60) + " " + ey + " " + ex + " " + ey,
        fill: "none", stroke: cols[i], "stroke-width": 4, "stroke-linecap": "round", opacity: narrow ? 0.0 : 1 });
      A.el(svg, "rect", { x: e[0], y: e[1], width: e[2], height: e[3], rx: 6, fill: C.panel, stroke: i === 2 ? "#1d466e" : C.copperDim, "stroke-width": 1.5 });
      A.el(svg, "rect", { x: e[0], y: e[1], width: 6, height: e[3], fill: cols[i] });
      A.text(svg, e[0] + 18, e[1] + 26, heads[i], { size: narrow ? 17 : 15, weight: 600, fill: i === 2 ? C.live : C.copperHi });
      T.push([A.text(svg, e[0] + 18, e[1] + (narrow ? 54 : 50), "", { size: narrow ? 16 : 14, fill: C.text2 }),
        A.text(svg, e[0] + 18, e[1] + (narrow ? 80 : 70), "", { size: narrow ? 16 : 14, fill: C.text2 })]);
    });
    if (narrow) {
      // cables as one bundle line down the left
      A.el(svg, "path", { d: "M" + (W / 2) + " 134 V200", stroke: C.text3, "stroke-width": 4 });
    }
    function draw(k) {
      var o = OS[k];
      osT.textContent = o.name;
      T[0][0].textContent = subs[0][0]; T[0][1].textContent = subs[0][1];
      T[1][0].textContent = "The jobs: " + o.mill[0] + (o.mill[1] ? " " + o.mill[1] : "") + ".";
      T[1][1].textContent = o.set + ".";
      T[2][0].textContent = subs[2][0]; T[2][1].textContent = subs[2][1];
    }
    var row = A.controls(host);
    A.segmented(row, [["win", "Windows"], ["linux", "Linux"], ["mac", "macOS"]], "win", draw);
  });
})();
