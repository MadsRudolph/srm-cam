/* "mc-stop" — Pause and STOP are different things (gui2/basics.py, machine.py).

   A trace is being cut. Pause holds the machine where it is with the spindle still
   turning, and Resume carries on from the same place. STOP drops the move in flight and
   stops the spindle; the bit stays where it is (in the cut), and the job does not resume:
   raise it with Page Up before moving anything. Esc is STOP from anywhere. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  A.define("mc-stop", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 490 : 880, H = narrow ? 700 : 380;
    var svg = A.stage(host, W, H, "A cut in progress: what Pause and STOP each do");

    // ---- top view: the path being cut ------------------------------------
    var TV = narrow ? { x: 10, y: 10, w: 470, h: 330 } : { x: 10, y: 10, w: 520, h: 360 };
    A.el(svg, "rect", { x: TV.x, y: TV.y, width: TV.w, height: TV.h, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(svg, TV.x + 18, TV.y + 28, "TOP VIEW · ISOLATION PASS", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    A.el(svg, "rect", { x: TV.x + 30, y: TV.y + 44, width: TV.w - 60, height: TV.h - 70, fill: C.copper, rx: 3 });
    var d = "M " + (TV.x + 70) + " " + (TV.y + 90) + " H " + (TV.x + TV.w - 90) + " V " + (TV.y + 190) +
      " H " + (TV.x + 130) + " V " + (TV.y + TV.h - 60) + " H " + (TV.x + TV.w - 70);
    A.el(svg, "path", { d: d, fill: "none", stroke: C.copperDim, "stroke-width": 16, "stroke-linejoin": "round", opacity: 0.35 });
    var cut = A.el(svg, "path", { d: d, fill: "none", stroke: "#2b1a0e", "stroke-width": 16, "stroke-linejoin": "round" });
    var len = cut.getTotalLength();
    cut.setAttribute("stroke-dasharray", len + " " + len);
    var bit = A.el(svg, "g");
    A.el(bit, "circle", { r: 13, fill: C.steel, stroke: "#fff", "stroke-width": 2 });
    var spin = A.el(bit, "path", { d: "M -19 0 A 19 19 0 0 1 19 0", fill: "none", stroke: C.caution, "stroke-width": 3 });

    // ---- state panel -------------------------------------------------------
    var P = narrow ? { x: 10, y: 350, w: 470, h: 340 } : { x: 546, y: 10, w: 324, h: 360 };
    A.el(svg, "rect", { x: P.x, y: P.y, width: P.w, height: P.h, rx: 4, fill: C.panel, stroke: C.ruleHi });
    var rows = {};
    [["motion", "Motion"], ["spindle", "Spindle"], ["bit", "The bit"], ["next", "What next"]].forEach(function (r, i) {
      var y = P.y + 36 + i * 76;
      A.text(svg, P.x + 18, y, r[1].toUpperCase(), { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
      rows[r[0]] = A.text(svg, P.x + 18, y + 30, "", { size: 18, weight: 600 });
    });

    var s = { pos: 0.08, mode: "cut", z: 0, ang: 0 };   // mode: cut | paused | stopped | lifted | done
    var row = A.controls(host), st = null;
    var pauseB = A.button(row, "Pause", function () {
      if (s.mode === "cut") { s.mode = "paused"; } else if (s.mode === "paused") { s.mode = "cut"; }
      paint(0);
    });
    A.button(row, "STOP", function () { stop(); }, null, "Esc");
    var liftB = A.button(row, "Page Up", function () {
      if (s.mode === "stopped") { s.mode = "lifted"; paint(0); }
    }, "key", "Raise the bit");
    A.button(row, "Start again", function () { s.pos = 0.08; s.mode = "cut"; paint(0); });
    st = A.status(row);

    function stop() { if (s.mode === "cut" || s.mode === "paused") { s.mode = "stopped"; paint(0); } }
    host.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { stop(); e.preventDefault(); }
      if (e.key === "PageUp" && s.mode === "stopped") { s.mode = "lifted"; paint(0); e.preventDefault(); }
    });

    var TXT = {
      cut: ["moving along the trace", C.live, "turning", C.caution, "in the cut", C.text, "—", C.text3,
        "Cutting. Press Pause, or STOP (or Esc with the figure focused).", ""],
      paused: ["held where it is", C.caution, "still turning", C.caution, "in the cut", C.text, "Resume carries on", C.ok,
        "Paused: the machine holds, the spindle keeps turning, and Resume carries on from the same place. VPanel's Pause, from SRM-CAM.", "caution"],
      stopped: ["move dropped", C.danger, "stopped", C.danger, "still down, in the cut", C.danger, "raise it: Page Up", C.danger,
        "STOP: the move in flight is dropped and the spindle stops, but the bit stays where it is. The job does not resume. Raise the bit with Page Up before moving anything.", "bad"],
      lifted: ["stopped", C.text2, "stopped", C.text2, "raised, clear", C.ok, "start the file again", C.text2,
        "Raised. The job cannot resume after a STOP: start the file again from VPanel when you are ready.", "ok"],
      done: ["finished", C.ok, "off", C.text3, "up", C.text2, "—", C.text3, "The pass finished.", "ok"]
    };
    function paint(dt) {
      if (s.mode === "cut") { s.pos += dt * 0.06; if (s.pos >= 1) { s.pos = 1; s.mode = "done"; } }
      if (s.mode === "cut" || s.mode === "paused") s.ang = (s.ang + dt * 540) % 360;
      var p = cut.getPointAtLength(s.pos * len);
      bit.setAttribute("transform", "translate(" + p.x + "," + p.y + ")");
      spin.setAttribute("transform", "rotate(" + s.ang + ")");
      spin.setAttribute("opacity", s.mode === "cut" || s.mode === "paused" ? 1 : 0);
      bit.firstChild.setAttribute("fill", s.mode === "stopped" ? C.danger : s.mode === "lifted" ? C.text3 : C.steel);
      cut.setAttribute("stroke-dashoffset", String(len * (1 - s.pos)));
      var t = TXT[s.mode];
      rows.motion.textContent = t[0]; rows.motion.setAttribute("fill", t[1]);
      rows.spindle.textContent = t[2]; rows.spindle.setAttribute("fill", t[3]);
      rows.bit.textContent = t[4]; rows.bit.setAttribute("fill", t[5]);
      rows.next.textContent = t[6]; rows.next.setAttribute("fill", t[7]);
      pauseB.textContent = s.mode === "paused" ? "Resume" : "Pause";
      pauseB.disabled = !(s.mode === "cut" || s.mode === "paused");
      liftB.disabled = s.mode !== "stopped";
      if (st.textContent !== t[8]) { st.textContent = t[8]; st.className = "anim-status" + (t[9] ? " " + t[9] : ""); }
    }
    A.loop(host, function (tt, dt) { paint(dt); }, 0);
    paint(0);
  });
})();
