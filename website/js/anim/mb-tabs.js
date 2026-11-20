/* Breaking the tabs, last (make-a-board.html#finish). To scale where the numbers are the
   code's: the cut-out is the 0.8 mm bit taken through the sheet in 2 x 1.0 mm passes,
   with tabs 1.5 mm wide left uncut at full thickness (app/presets.py cutout: tabs 4,
   tab_width 1.5; engine/cutout.py leaves the gaps on every pass). The sheet is drawn
   1.6 mm thick, the lab's FR4. How the tab cracks, and the stub it leaves, is
   schematic. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var CH = 0.8, TAB = 1.5, T = 1.6;

  var STEPS = [
    ["tabs", "On its tabs", "As it came off the mill and the laser: the board is held by four 1.5 mm bridges across the 0.8 mm channel."],
    ["bend", "Bend the waste", "Hold the board flat, bend the waste down along the channel. The tab cracks at its narrowest."],
    ["snap", "Snapped", "The board is out. A stub of the tab, up to the channel's width, stands proud of the edge."],
    ["sand", "Sanded", "Sand the stub flush with the edge. Then clear the holes and check continuity."]
  ];

  A.define("mb-tabs", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 700 : 380;
    var svg = A.stage(host, W, H, "To scale: a tab bridging the cut-out channel between the board and the waste, from above and from the side, and how it is broken");
    var k = 22;                                   // px per mm
    // top view: x across the edge (waste left, board right), y along the edge
    var tx = narrow ? 40 : 30, ty = 64, tw = 13, th = 10;   // mm shown
    A.text(svg, tx, 34, "FROM ABOVE · TO SCALE", { size: 13, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var top = A.el(svg, "g", {});
    var sx = narrow ? 40 : 380, sy = narrow ? ty + th * k + 100 : 64;
    A.text(svg, sx, sy - 30, "FROM THE SIDE, THROUGH THE TAB", { size: 13, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var side = A.el(svg, "g", {});
    var cap = A.text(svg, narrow ? 40 : 380, narrow ? sy + 170 : 230, "", { size: narrow ? 18 : 16, weight: 700 });
    var lines = [];
    for (var i = 0; i < 4; i++) lines.push(A.text(svg, narrow ? 40 : 380, (narrow ? sy + 202 : 260) + i * (narrow ? 27 : 24), "", { size: narrow ? 16 : 14.5, fill: C.text2 }));

    function wrap(s, n) {
      var out = [], cur = "";
      s.split(" ").forEach(function (w) {
        if ((cur + " " + w).trim().length > n) { out.push(cur.trim()); cur = w; } else cur += " " + w;
      });
      if (cur.trim()) out.push(cur.trim());
      return out;
    }

    function draw(key) {
      var st = STEPS.filter(function (s) { return s[0] === key; })[0];
      while (top.firstChild) top.removeChild(top.firstChild);
      while (side.firstChild) side.removeChild(side.firstChild);
      var cx0 = 5.5, cx1 = cx0 + CH, ty0 = (th - TAB) / 2, ty1 = ty0 + TAB;
      function X(x) { return tx + x * k; }
      function Y(y) { return ty + y * k; }
      var out = key === "snap" || key === "sand";
      // waste (left) unless the board is out
      if (!out) {
        A.el(top, "rect", { x: X(0), y: Y(0), width: cx0 * k, height: th * k, fill: C.copperDim });
        A.text(top, X(cx0 / 2), Y(th) + 22, "waste", { size: 13, anchor: "middle", fill: C.text3 });
      } else {
        A.el(top, "rect", { x: X(0), y: Y(0), width: cx0 * k, height: th * k, fill: "none", stroke: C.ruleHi, "stroke-dasharray": "5 5" });
        A.text(top, X(cx0 / 2), Y(th) + 22, "(waste gone)", { size: 13, anchor: "middle", fill: C.text4 });
      }
      // the channel
      A.el(top, "rect", { x: X(cx0), y: Y(0), width: CH * k, height: th * k, fill: C.ink });
      // the tab
      if (key === "tabs" || key === "bend") {
        A.el(top, "rect", { x: X(cx0), y: Y(ty0), width: CH * k, height: TAB * k, fill: key === "bend" ? C.caution : C.copperDim });
      } else if (key === "snap") {
        A.el(top, "rect", { x: X(cx0 + 0.35), y: Y(ty0), width: (CH - 0.35) * k, height: TAB * k, fill: C.copperDim });
      }
      // the board (right)
      A.el(top, "rect", { x: X(cx1), y: Y(0), width: (tw - cx1) * k, height: th * k, fill: C.copper });
      A.text(top, X((cx1 + tw) / 2), Y(th) + 22, "board", { size: 13, anchor: "middle", fill: C.copperHi });
      // dimensions
      A.el(top, "line", { x1: X(cx0), y1: Y(0) - 10, x2: X(cx1), y2: Y(0) - 10, stroke: C.text3 });
      A.text(top, X(cx0 + CH / 2), Y(0) - 16, "0.8", { size: 12, anchor: "middle", fill: C.text3 });
      A.el(top, "line", { x1: X(tw) + 8, y1: Y(ty0), x2: X(tw) + 8, y2: Y(ty1), stroke: C.text3 });
      A.text(top, X(tw) + 14, Y((ty0 + ty1) / 2) + 4, "1.5", { size: 12, fill: C.text3 });

      // side view: x as above, z up; sheet T thick
      function SX(x) { return sx + x * k; }
      var zb = sy + 70;                         // bottom face
      function SZ(z) { return zb - z * k; }
      // the bed
      A.el(side, "rect", { x: SX(0) - 6, y: zb, width: tw * k + 12, height: 6, fill: C.panelHi });
      // the board
      A.el(side, "rect", { x: SX(cx1), y: SZ(T), width: (tw - cx1) * k, height: T * k, fill: C.fr4 });
      A.el(side, "rect", { x: SX(cx1), y: SZ(T), width: (tw - cx1) * k, height: 3, fill: C.copper });
      if (key === "tabs") {
        A.el(side, "rect", { x: SX(0), y: SZ(T), width: cx1 * k, height: T * k, fill: C.fr4 });
        A.el(side, "rect", { x: SX(0), y: SZ(T), width: cx0 * k, height: 3, fill: C.copperDim });
        A.el(side, "rect", { x: SX(cx0), y: SZ(T), width: CH * k, height: T * k, fill: C.fr4Hi });
      } else if (key === "bend") {
        var g = A.el(side, "g", { transform: "rotate(16," + SX(cx1) + "," + zb + ")" });
        A.el(g, "rect", { x: SX(0), y: SZ(T), width: cx1 * k, height: T * k, fill: C.fr4 });
        A.el(g, "rect", { x: SX(0), y: SZ(T), width: cx0 * k, height: 3, fill: C.copperDim });
        A.el(g, "rect", { x: SX(cx0), y: SZ(T), width: CH * k, height: T * k, fill: C.caution });
        A.arrow(side, SX(1.5), SZ(T) - 8, SX(1.0), zb + 40, { color: C.caution, width: 2.5 });
        A.text(side, SX(1.6), zb + 44, "bend down", { size: 13, fill: C.caution });
        A.el(side, "path", { d: "M" + SX(cx1) + " " + SZ(T) + " l -4 8 l 5 6 l -3 7", fill: "none", stroke: C.danger, "stroke-width": 2 });
      } else if (key === "snap") {
        A.el(side, "rect", { x: SX(cx0 + 0.35), y: SZ(T), width: (CH - 0.35) * k, height: T * k, fill: C.fr4Hi });
      }
      // hand-hold arrow on the board
      if (key === "bend") {
        A.arrow(side, SX(tw - 2), SZ(T) - 34, SX(tw - 2), SZ(T) - 4, { color: C.text2 });
        A.text(side, SX(tw - 2), SZ(T) - 40, "hold flat", { size: 13, anchor: "middle", fill: C.text2 });
      }
      A.el(side, "line", { x1: SX(tw) + 8, y1: SZ(T), x2: SX(tw) + 8, y2: zb, stroke: C.text3 });
      A.text(side, SX(tw) + 14, SZ(T / 2) + 4, "1.6", { size: 12, fill: C.text3 });

      cap.textContent = st[1];
      var L = wrap(st[2], narrow ? 46 : 52);
      lines.forEach(function (t, i) { t.textContent = L[i] || ""; });
    }

    var row = A.controls(host);
    A.segmented(row, STEPS.map(function (s) { return [s[0], s[1]]; }), "tabs", draw);
  });
})();
