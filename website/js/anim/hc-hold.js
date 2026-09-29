/* The lab's two ways of holding the copper.
   Tape (best): double-sided tape across the whole back, the board pressed flat onto
   the spoilboard. Nothing arches, so the probed surface is the cut surface; in the app
   "Held down by › Bonded across the whole back (tape)", which adds no extra depth.
   Disc clamps (second best): four plastic discs with a chamfer round their side. Each
   one's screw goes through a spoilboard grid hole (10 mm pitch) into the threads of the
   plate underneath, BESIDE the board, not through the copper. Turning the disc brings
   its chamfered rim in against the board's edge, pressing it down and in. Four, one per
   side, because the clamping force has to come from all sides. In the app "Screwed or
   clamped at points" (the held-at-points extra depth applies).
   The disc turns on an off-centre screw (a cam), which moves the rim in (confirmed by
   Mads, 2026-09-30). */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  A.define("hc-hold", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 600;
    var W = narrow ? 520 : 880, H = narrow ? 900 : 480;
    var svg = A.stage(host, W, H, "Two ways to hold the copper: double-sided tape across the back, or four disc clamps round the edge");
    var title = A.text(svg, 24, 32, "", { size: 15, weight: 600, font: "label", fill: C.text3, spacing: "0.06em" });
    var gTape = A.el(svg, "g", {}), gDisc = A.el(svg, "g", {});
    var verdict = A.text(svg, 24, H - (narrow ? 44 : 20), "", { size: narrow ? 16 : 17, weight: 700 });
    var verdict2 = A.text(svg, 24, H - 20, "", { size: narrow ? 16 : 17, weight: 700 });
    // a phone gets the verdict on two lines, split after its first sentence or colon
    var setV = function (txt, col) {
      var cut = narrow ? Math.max(txt.indexOf(": "), txt.indexOf(". ")) : -1;
      verdict.textContent = cut > 0 ? txt.slice(0, cut + 1) : txt;
      verdict2.textContent = cut > 0 ? txt.slice(cut + 2) : "";
      A.set(verdict, { fill: col }); A.set(verdict2, { fill: col });
    };

    // ---------------- tape ----------------
    // top view: board, tape strips laid on its back (shown dashed through it), then pressed
    var TX = 40, TY = 70, TW = narrow ? 440 : 420, TH = narrow ? 260 : 300;
    A.text(gTape, TX, TY - 12, "THE BACK OF THE BOARD", { size: 15, fill: C.text3, weight: 600, font: "label" });
    A.el(gTape, "rect", { x: TX, y: TY, width: TW, height: TH, fill: C.fr4, rx: 4 });
    var strips = [];
    for (var i = 0; i < 4; i++) {
      strips.push(A.el(gTape, "rect", { x: TX + 20, y: TY + 24 + i * (TH - 48) / 4 + 8, width: 0, height: (TH - 48) / 4 - 16,
        fill: "#e8e2c8", opacity: 0.9, rx: 3 }));
    }
    // section: board lowering onto the spoilboard
    var SX = narrow ? 40 : 500, SY = narrow ? 420 : 110, SW = narrow ? 440 : 340;
    A.text(gTape, SX, SY - 12, "SECTION", { size: 15, fill: C.text3, weight: 600, font: "label" });
    A.el(gTape, "rect", { x: SX, y: SY + 190, width: SW, height: 30, fill: C.board });
    A.text(gTape, SX + 8, SY + 244, "spoilboard", { size: 15, fill: C.text2 });
    var tBoard = A.el(gTape, "g", {});
    A.el(tBoard, "rect", { x: SX + 20, y: 0, width: SW - 40, height: 8, fill: C.copper });
    A.el(tBoard, "rect", { x: SX + 20, y: 8, width: SW - 40, height: 30, fill: C.fr4 });
    A.el(tBoard, "rect", { x: SX + 26, y: 38, width: SW - 52, height: 6, fill: "#e8e2c8" });
    var press = A.el(gTape, "g", {});
    [0.3, 0.5, 0.7].forEach(function (f) { A.arrow(press, SX + SW * f, SY + 70, SX + SW * f, SY + 120, { color: C.caution, head: 9, width: 3 }); });
    var tLab = A.text(gTape, SX + SW / 2, SY + 290, "", { size: 15, anchor: "middle", fill: C.ok });

    // ---------------- discs ----------------
    var K = narrow ? 3.4 : 3.1, BX = narrow ? 70 : 76, BY = 118;
    var BW = 110, BH = 70;                     // board, mm
    function px(mm) { return BX + mm * K; }
    function py(mm) { return BY + mm * K; }
    A.text(gDisc, 24, 62, "TOP VIEW · GRID HOLES 10 MM APART", { size: 15, fill: C.text3, weight: 600, font: "label" });
    A.el(gDisc, "rect", { x: px(-15), y: py(-15), width: (BW + 30) * K, height: (BH + 30) * K, fill: C.board, opacity: 0.55, rx: 3 });
    for (var gx = -10; gx <= BW + 10; gx += 10) for (var gy = -10; gy <= BH + 10; gy += 10)
      A.el(gDisc, "circle", { cx: px(gx), cy: py(gy), r: 2.4, fill: C.sunk });
    var boardG = A.el(gDisc, "g", {});
    A.el(boardG, "rect", { x: 0, y: 0, width: BW * K, height: BH * K, fill: C.copper, stroke: C.copperHi });
    A.text(boardG, BW * K / 2, BH * K / 2 + 6, "the board", { size: 16, anchor: "middle", weight: 700, fill: C.ink });
    // discs: screw hole beside the board; R 9 mm disc, screw 3 mm off-centre (cam)
    var R = 9, E = 3;
    var discs = [
      { hx: BW / 2, hy: -10, nx: 0, ny: 1 },       // back edge, pushes +y
      { hx: BW + 10, hy: BH / 2, nx: -1, ny: 0 },  // right, pushes -x
      { hx: BW / 2, hy: BH + 10, nx: 0, ny: -1 },  // front, pushes -y
      { hx: -10, hy: BH / 2, nx: 1, ny: 0 }        // left, pushes +x
    ];
    discs.forEach(function (d) {
      d.g = A.el(gDisc, "g", {});
      d.body = A.el(d.g, "circle", { r: R * K, fill: "#d8dde4", stroke: C.steelDim, "stroke-width": 2, opacity: 0.93 });
      d.chamfer = A.el(d.g, "circle", { r: (R - 1.5) * K, fill: "none", stroke: C.steelDim, "stroke-width": 1, "stroke-dasharray": "3 3" });
      d.screw = A.el(gDisc, "circle", { r: 2.2 * K, fill: C.steelDim, stroke: C.ink, "stroke-width": 1 });
      d.slot = A.el(gDisc, "line", { stroke: C.ink, "stroke-width": 2 });
      d.arrow = A.el(gDisc, "g", {});
    });
    // side section of one disc
    var DX = narrow ? 40 : 560, DY = narrow ? 470 : 110, DW = narrow ? 440 : 290;
    A.text(gDisc, DX, DY - 12, "SECTION THROUGH ONE DISC", { size: 15, fill: C.text3, weight: 600, font: "label" });
    A.el(gDisc, "rect", { x: DX, y: DY + 150, width: DW, height: 26, fill: C.steelDim });
    A.text(gDisc, DX + DW - 8, DY + 168, "plate, threaded", { size: 15, anchor: "end", fill: C.ink });
    A.el(gDisc, "rect", { x: DX, y: DY + 100, width: DW, height: 50, fill: C.board });
    A.text(gDisc, DX + 8, DY + 140, "spoilboard", { size: 15, fill: C.text2 });
    var sBoardX = DX + DW * 0.52;
    A.el(gDisc, "rect", { x: sBoardX, y: DY + 78, width: DW - (sBoardX - DX), height: 22, fill: C.fr4 });
    A.el(gDisc, "rect", { x: sBoardX, y: DY + 74, width: DW - (sBoardX - DX), height: 4, fill: C.copper });
    A.text(gDisc, DX + DW - 8, DY + 66, "board", { size: 15, anchor: "end", fill: C.copperHi });
    var screwX = DX + DW * 0.26;
    A.el(gDisc, "rect", { x: screwX - 5, y: DY + 50, width: 10, height: 122, fill: "#9aa1ab" });
    for (var t = 0; t < 7; t++) A.el(gDisc, "line", { x1: screwX - 5, y1: DY + 110 + t * 9, x2: screwX + 5, y2: DY + 114 + t * 9, stroke: C.ink, "stroke-width": 1 });
    var sDisc = A.el(gDisc, "polygon", { fill: "#d8dde4", stroke: C.steelDim, "stroke-width": 2 });
    var sArrow = A.el(gDisc, "g", {});
    var dLab = A.text(gDisc, DX, DY + 210, "", { size: 15, fill: C.text2 });
    var dLab2 = A.text(gDisc, DX, DY + 232, "", { size: 15, fill: C.text2 });

    var mode = "tape", missing = false, anim = null;

    function drawTape(u) {
      var lay = A.clamp(u / 0.5, 0, 1), down = A.ease((u - 0.55) / 0.35);
      strips.forEach(function (s, i) { A.set(s, { width: Math.max(0, (TW - 40) * A.clamp(lay * 4 - i, 0, 1)) }); });
      tBoard.setAttribute("transform", "translate(0," + (SY + 60 + (1 - down) * -40 + down * 82) + ")");
      press.setAttribute("opacity", u > 0.5 && u < 0.97 ? 1 : 0);
      tLab.textContent = down >= 1 ? "flat on the spoilboard: nothing can arch" : "";
      setV(down >= 1 ? "Best: the probed surface is the cut surface. Held down by › Bonded (tape)." : "Double-sided tape across the whole back…", down >= 1 ? C.ok : C.text);
    }

    function drawDisc(u) {
      var turn = [];
      discs.forEach(function (d, i) {
        var show = !(missing && i === 3);
        var appear = A.clamp(u * 5 - i * 0.6, 0, 1);         // placed and screwed in, one after another
        var tw = A.ease((u - 0.55) / 0.35);                    // then all turned in
        turn.push(tw);
        d.g.setAttribute("opacity", show ? appear : 0);
        d.screw.setAttribute("opacity", show ? appear : 0);
        d.slot.setAttribute("opacity", show ? appear : 0);
        // cam: disc centre = screw + E in a direction that rotates from "away" to "towards the board"
        var ang = Math.PI * (1 - tw);                          // 180° away -> 0° towards
        var cx = d.hx + E * (d.nx * Math.cos(ang) - d.ny * Math.sin(ang));
        var cy = d.hy + E * (d.ny * Math.cos(ang) + d.nx * Math.sin(ang));
        A.set(d.body, { cx: px(cx), cy: py(cy) });
        A.set(d.chamfer, { cx: px(cx), cy: py(cy) });
        A.set(d.screw, { cx: px(d.hx), cy: py(d.hy) });
        var sa = tw * Math.PI * 0.9 + 0.5;
        A.set(d.slot, { x1: px(d.hx) - Math.cos(sa) * 6, y1: py(d.hy) - Math.sin(sa) * 6, x2: px(d.hx) + Math.cos(sa) * 6, y2: py(d.hy) + Math.sin(sa) * 6 });
        while (d.arrow.firstChild) d.arrow.removeChild(d.arrow.firstChild);
        if (show && tw >= 1) {
          var ex = d.hx + d.nx * (R + E), ey = d.hy + d.ny * (R + E);
          A.arrow(d.arrow, px(ex - d.nx * 6), py(ey - d.ny * 6), px(ex + d.nx * 2), py(ey + d.ny * 2), { color: C.caution, head: 9, width: 3 });
        }
      });
      var tw0 = turn[0];
      // the board: held from all four sides, or it slides away from the missing one
      var slide = missing ? A.ease((u - 0.85) / 0.15) * 6 : 0;
      boardG.setAttribute("transform", "translate(" + px(-slide) + "," + py(0) + ")");
      // section: disc rim moving in over the board edge
      var rimX = screwX + 20 + tw0 * (sBoardX - screwX - 8);
      var top = DY + 50, bot = DY + 96;
      sDisc.setAttribute("points", [screwX - 40, top, rimX - 10, top, rimX + 4, bot - 16, rimX - 6, bot, screwX - 40, bot].join(","));
      while (sArrow.firstChild) sArrow.removeChild(sArrow.firstChild);
      if (tw0 >= 1) {
        A.arrow(sArrow, sBoardX + 34, DY + 30, sBoardX + 14, DY + 70, { color: C.caution, head: 9, width: 3 });
        dLab.textContent = "The chamfer presses the edge down and in.";
        dLab2.textContent = "The screw is beside the board, never through it.";
      } else { dLab.textContent = "Screw through a grid hole into the plate,"; dLab2.textContent = "then turn the disc until the chamfer bites."; }
      if (u >= 1) {
        setV(missing ? "Three discs: nothing holds the left side, so the board slides and lifts." :
          "Four discs, force from all four sides. Held down by › Screwed or clamped at points.", missing ? C.danger : C.ok);
      } else { setV("Disc clamps: one on each side of the board…", C.text); }
    }

    function draw(u) {
      gTape.setAttribute("display", mode === "tape" ? "inline" : "none");
      gDisc.setAttribute("display", mode === "disc" ? "inline" : "none");
      title.textContent = mode === "tape" ? "1 · DOUBLE-SIDED TAPE (BEST)" : "2 · FOUR DISC CLAMPS";
      if (mode === "tape") drawTape(u); else drawDisc(u);
      oneBtn.disabled = mode !== "disc";
    }
    function play() {
      if (anim) anim.stop();
      anim = A.loop(host, function (t) {
        var u = Math.min(1, t / 4.2);
        draw(u);
        if (u >= 1) anim.stop();
      }, 99);
    }

    var row = A.controls(host);
    A.segmented(row, [["tape", "Tape"], ["disc", "Disc clamps"]], "tape", function (v) {
      mode = v; if (oneBtn) { oneBtn.disabled = v !== "disc"; play(); }
    });
    A.button(row, "Replay", play, "primary");
    var oneBtn = A.button(row, "Remove one disc", function () {
      missing = !missing; this.textContent = missing ? "Put it back" : "Remove one disc"; play();
    });
    var st = A.status(row);
    st.textContent = "The lab's two holds. Tape is best; the disc clamps are next.";
    oneBtn.disabled = true;
    play();
  });
})();
