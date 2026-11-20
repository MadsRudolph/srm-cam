/* Where the method chip comes from (kicad.html). gui2/window.py _detect_method:
   first what was picked on the chip for this folder before, then what KiCad's Set
   design rules stored (srm-cam/method.json), else a guess from the narrowest gap
   between two nets: 0.80 mm or more -> Flat mill, 0.44 mm or more -> Ball mill,
   less -> Laser (engine/method.py guess_from_gap). Chip text "<short> · <source>". */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var SHORT = { flat: "Flat mill", ball: "Ball mill", laser: "Laser" };

  A.define("kc-method", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 430 : 262;
    var svg = A.stage(host, W, H, "Three rungs decide the method: picked on the chip for this folder, else stored by KiCad, else guessed from the narrowest gap");
    var state = { chosen: "", kicad: "laser", gap: 0.25 };
    var rungs = [
      ["chosen", "1 · Picked on the chip before, for this folder"],
      ["kicad", "2 · Stored by KiCad's Set design rules"],
      ["guessed", "3 · Guessed from the narrowest gap"]
    ];
    var rw = narrow ? W - 32 : 520, rh = narrow ? 70 : 64;
    var R = rungs.map(function (r, i) {
      var y = 20 + i * (rh + 12);
      var rect = A.el(svg, "rect", { x: 16, y: y, width: rw, height: rh, rx: 6, fill: C.panel, stroke: C.ruleHi, "stroke-width": 1.5 });
      var t1 = A.text(svg, 30, y + 26, r[1], { size: narrow ? 17 : 15, weight: 600 });
      var t2 = A.text(svg, 30, y + 50, "", { size: narrow ? 16 : 14, fill: C.text3 });
      return { rect: rect, t1: t1, t2: t2 };
    });
    var cx = narrow ? 16 : 580, cy = narrow ? 20 + 3 * (rh + 12) + 18 : 100;
    A.text(svg, cx, cy - 12, "The chip at the top:", { size: narrow ? 16 : 14, fill: C.text3 });
    var chipR = A.el(svg, "rect", { x: cx, y: cy, width: narrow ? 330 : 284, height: 44, rx: 5, fill: C.liveFill, stroke: C.live, "stroke-width": 1.5 });
    var dot = A.el(svg, "circle", { cx: cx + 20, cy: cy + 22, r: 5, fill: C.live });
    var chip = A.text(svg, cx + 34, cy + 28, "", { size: narrow ? 18 : 16, weight: 600, font: "label", spacing: "0.1em", fill: C.live });
    var why = A.text(svg, cx, cy + 74, "", { size: narrow ? 16 : 14, fill: C.text2 });
    var why2 = A.text(svg, cx, cy + 96, "", { size: narrow ? 16 : 14, fill: C.text2 });

    function guess(g) { return g >= 0.8 - 0.0005 ? "flat" : g >= 0.44 - 0.0005 ? "ball" : "laser"; }
    function draw() {
      var src, mid;
      if (state.chosen) { src = "chosen"; mid = state.chosen; }
      else if (state.kicad) { src = "kicad"; mid = state.kicad; }
      else { src = "guessed"; mid = guess(state.gap); }
      R[0].t2.textContent = state.chosen ? SHORT[state.chosen] + " picked: this wins." : "Nothing picked.";
      R[1].t2.textContent = state.kicad ? (src === "kicad" ? SHORT[state.kicad] + " in method.json: this wins." : SHORT[state.kicad] + " in method.json: not used.") : "No method.json.";
      R[2].t2.textContent = "Gap " + state.gap.toFixed(2) + " mm → " + SHORT[guess(state.gap)] + (src === "guessed" ? ": this wins." : ": not used.");
      ["chosen", "kicad", "guessed"].forEach(function (k, i) {
        var on = k === src;
        A.set(R[i].rect, { stroke: on ? C.live : C.ruleHi, fill: on ? C.liveFill : C.panel });
        A.set(R[i].t2, { fill: on ? C.live : C.text3 });
      });
      var laser = mid === "laser";
      chip.textContent = (SHORT[mid] + " · " + { chosen: "chosen", kicad: "from KiCad", guessed: "guessed" }[src]).toUpperCase();
      A.set(chipR, { fill: laser ? C.liveFill : C.panelHi, stroke: laser ? C.live : C.ruleStrong });
      A.set(dot, { fill: laser ? C.live : C.text3 });
      A.set(chip, { fill: laser ? C.live : C.text2 });
      why.textContent = src === "chosen" ? "Your own pick beats KiCad." : src === "kicad" ? "As set in KiCad." : "No pick, no method.json.";
      why2.textContent = src === "chosen" ? "Changed KiCad later? Pick again on the chip." : laser ? "Laser: drill and cut out, then the laser." : "The mill makes the whole board.";
    }
    var row = A.controls(host);
    A.segmented(row, [["", "Not picked"], ["laser", "Picked Laser"], ["flat", "Picked Flat"]], "", function (v) { state.chosen = v; draw(); });
    A.segmented(row, [["laser", "KiCad: Laser"], ["ball", "KiCad: Ball"], ["", "No method.json"]], "laser", function (v) { state.kicad = v; draw(); });
    A.slider(row, "Narrowest gap", 0.15, 1.0, 0.01, state.gap, function (v) { state.gap = v; draw(); }, function (v) { return v.toFixed(2) + " mm"; });
  });
})();
