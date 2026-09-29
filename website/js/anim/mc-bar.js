/* "mc-bar" — the machine bar, working.

   The controls under the drawing are the bar's own (gui2/machine.py MachineBar): the link
   chip and Connect, the X Y Z readout (machine coordinates, Z red and "Touch" while the
   probe reads contact), Z jog with its step, Probe Z, Zero Z, Spindle and STOP. What each
   one changes is spelled out on the right, because the two touches differ in exactly
   that: Probe Z tells the APP where the copper is; Zero Z writes the MACHINE's G54 Z
   origin at the surface and lifts 2 mm. Jogging down is refused while touching; the
   spindle refuses with the lid open (firmware: E S COVER); STOP drops the move and stops
   the spindle but leaves the bit where it is. Copper at machine Z −38.00, as elsewhere. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;
  var SURF = -38.0;

  A.define("mc-bar", function (host) {
    var narrow = host.clientWidth > 0 && host.clientWidth < 560;
    var W = narrow ? 490 : 880, H = narrow ? 800 : 440;
    var svg = A.stage(host, W, H, "SRM-CAM's machine bar and what each control does to the machine");

    // ---- the bar strip ------------------------------------------------------
    A.el(svg, "rect", { x: 10, y: 10, width: W - 20, height: narrow ? 120 : 70, rx: 4, fill: C.panel, stroke: C.ruleHi });
    var chipR = A.el(svg, "rect", { x: 24, y: 26, width: 178, height: 38, rx: 19, "stroke-width": 2 });
    var chipT = A.text(svg, 113, 51, "", { size: 16, weight: 600, anchor: "middle" });
    var dro = {};
    var dx = narrow ? [24, 176, 328] : [230, 380, 530], dy = narrow ? 104 : 52;
    ["X", "Y", "Z"].forEach(function (a, i) {
      A.el(svg, "rect", { x: dx[i], y: dy - 26, width: 140, height: 36, rx: 3, fill: C.sunk, stroke: C.ruleStrong });
      dro[a] = { lab: A.text(svg, dx[i] + 10, dy - 2, a, { size: 15, weight: 700, font: "label", fill: C.text3 }),
        val: A.text(svg, dx[i] + 130, dy - 2, "—", { size: 18, weight: 600, font: "mono", anchor: "end" }) };
    });
    var stopG = A.el(svg, "g");
    A.el(stopG, "rect", { x: narrow ? 330 : 700, y: 24, width: narrow ? 136 : 160, height: 42, rx: 3, fill: C.danger });
    A.text(stopG, narrow ? 398 : 780, 52, "STOP", { size: 20, weight: 800, anchor: "middle", fill: "#fff", font: "label" });

    // ---- side view --------------------------------------------------------
    var SV = narrow ? { x: 10, y: 140, w: 470, h: 330 } : { x: 10, y: 90, w: 540, h: 340 };
    A.el(svg, "rect", { x: SV.x, y: SV.y, width: SV.w, height: SV.h, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(svg, SV.x + 18, SV.y + 28, "AT THE MACHINE", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var CU = SV.y + SV.h - 70, K = 20;      // px per mm above the copper
    A.el(svg, "rect", { x: SV.x + 30, y: CU, width: SV.w - 60, height: 10, fill: C.copper });
    A.el(svg, "rect", { x: SV.x + 30, y: CU + 10, width: SV.w - 60, height: 40, fill: C.board });
    var lid = A.el(svg, "g");
    var lidR = A.el(lid, "rect", { x: SV.x + 16, y: SV.y + 40, width: SV.w - 32, height: SV.h - 50, rx: 6, fill: "none", "stroke-width": 3 });
    var lidT = A.text(lid, SV.x + SV.w - 24, SV.y + 28, "", { size: 15, weight: 600, anchor: "end" });
    var hx = SV.x + SV.w / 2;
    var clip = A.el(A.el(svg, "defs"), "clipPath", { id: "mcbarClip" });
    A.el(clip, "rect", { x: SV.x + 2, y: SV.y + 42, width: SV.w - 4, height: SV.h - 44 });
    var head = A.el(A.el(svg, "g", { "clip-path": "url(#mcbarClip)" }), "g");
    A.el(head, "rect", { x: hx - 42, y: -110, width: 84, height: 60, rx: 4, fill: "#5a606b" });
    A.el(head, "rect", { x: hx - 22, y: -50, width: 44, height: 24, fill: "#9aa0aa" });
    A.el(head, "rect", { x: hx - 7, y: -26, width: 14, height: 26, fill: C.steel });
    var spin = A.el(head, "g", { opacity: 0 });
    var spinArc = A.el(spin, "path", { d: "M " + (hx - 30) + " -110 a 30 12 0 1 0 60 0", fill: "none", stroke: C.caution, "stroke-width": 3 });
    A.text(spin, hx + 60, -110, "spinning", { size: 15, weight: 600, fill: C.caution });
    var gapT = A.text(svg, SV.x + SV.w / 2, CU + 36, "", { size: 16, weight: 600, font: "mono", anchor: "middle" });
    var zeroLine = A.el(svg, "g", { opacity: 0 });
    A.el(zeroLine, "line", { x1: SV.x + 24, x2: SV.x + SV.w - 24, y1: CU, y2: CU, stroke: C.caution, "stroke-width": 2, "stroke-dasharray": "7 5" });
    A.text(zeroLine, SV.x + 34, CU - 10, "G54 Z 0", { size: 15, weight: 700, fill: C.caution });

    // ---- what changed ------------------------------------------------------
    var R = narrow ? { x: 10, y: 480, w: 470 } : { x: 562, y: 90, w: 308 };
    A.el(svg, "rect", { x: R.x, y: R.y, width: R.w, height: narrow ? 310 : 340, rx: 4, fill: C.panel, stroke: C.ruleHi });
    A.text(svg, R.x + 18, R.y + 28, "WHAT IT CHANGED", { size: 15, weight: 600, fill: C.text3, font: "label", spacing: "0.06em" });
    var facts = {};
    [["app", "SRM-CAM knows the copper at"], ["g54", "VPanel's G54 Z origin"], ["spindle", "Spindle"], ["move", "Motion"]].forEach(function (f, i) {
      var y = R.y + 70 + i * 66;
      A.text(svg, R.x + 18, y, f[1], { size: 15, fill: C.text2 });
      facts[f[0]] = A.text(svg, R.x + 18, y + 28, "", { size: 18, weight: 600, font: "mono" });
    });

    // ---- state ---------------------------------------------------------------
    var s = { linked: false, connecting: 0, z: -30.0, target: -30.0, step: 0.5, appZ: null, g54: null, spindle: false,
      lidOpen: false, moving: false, afterMove: null, stopped: false };
    var row = A.controls(host), st = null;
    function say(msg, kind) { st.className = "anim-status" + (kind ? " " + kind : ""); st.textContent = msg; }
    function touching() { return s.linked && s.z <= SURF + 1e-6; }
    function need() {
      if (!s.linked) { say("Not connected — there is nothing to move. Press Connect.", "caution"); return false; }
      if (s.moving) { say("Busy: the last move is still running.", "caution"); return false; }
      return true;
    }
    function moveTo(z, then) { s.target = z; s.moving = true; s.stopped = false; s.afterMove = then || null; if (A.reduced) finishMove(); }
    function finishMove() { s.z = s.target; s.moving = false; var f = s.afterMove; s.afterMove = null; if (f) f(); }
    function refusedIfTouching() {
      if (touching()) { say("The bit is already touching the copper. Raise it a few millimetres with ↑ (Page Up), then try again.", "caution"); return true; }
      return false;
    }

    A.button(row, "Connect", function () {
      if (s.linked) { s.linked = false; s.spindle = false; say("Disconnected. Everything except the machine controls still works: export and send from VPanel."); return; }
      s.connecting = 0.9;
      say("Opening the link to the Arduino in the machine…");
      if (A.reduced) { s.connecting = 0; s.linked = true; say("Linked: the readout is the machine's position, three times a second.", "ok"); }
    }, null, "Ctrl+L");
    A.button(row, "↓", function () {
      if (!need() || refusedIfTouching()) return;
      var to = s.z - s.step, hit = to <= SURF;
      moveTo(Math.max(to, SURF), function () {
        say(hit ? "Touch. " + (s.step >= 1 ? "A " + s.step + " mm step this close would have driven the bit into the copper on the real machine; creep the last millimetre at 0.1 mm or less." : "SRM-CAM now refuses to jog down.")
          : "Down " + s.step + " mm. (Page Down does the same from anywhere.)", hit ? "bad" : "");
      });
    }, "key", "Page Down");
    A.button(row, "↑", function () {
      if (!need()) return;
      moveTo(s.z + s.step, function () { say("Up " + s.step + " mm. (Page Up does the same, and always works.)"); });
    }, "key", "Page Up");
    A.segmented(row, [[0.1, "0.1 mm"], [0.5, "0.5 mm"], [1, "1 mm"], [5, "5 mm"]], 0.5, function (v) { s.step = v; });
    A.button(row, "Probe Z", function () {
      if (!need() || refusedIfTouching()) return;
      moveTo(SURF, function () {
        s.appZ = SURF;
        say("Probe Z: stepped down to the copper and stopped on it. SRM-CAM now knows the surface (machine Z −38.00) for the Z-reach check and the level page. VPanel's origin is unchanged.", "ok");
      });
    });
    A.button(row, "Zero Z", function () {
      if (!need() || refusedIfTouching()) return;
      moveTo(SURF, function () {
        s.appZ = SURF; s.g54 = SURF;
        moveTo(SURF + 2, function () {
          say("Zero Z: touched the copper, the firmware wrote VPanel's G54 Z origin there, and lifted 2 mm. Only Z: X and Y are never moved. Check VPanel's G54 Z once before a job.", "ok");
        });
      });
    });
    A.button(row, "Spindle", function () {
      if (!s.linked) { say("Not connected.", "caution"); return; }
      if (!s.spindle && s.lidOpen) { say("Refused with the lid open (the firmware answers E S COVER). Close it first.", "bad"); return; }
      s.spindle = !s.spindle;
      say(s.spindle ? "Spindle on, at whatever speed VPanel's slider says: the link cannot set the speed. It stops by itself if the app goes quiet for 10 s." : "Spindle off.");
    });
    A.button(row, "Open / close the lid", function () {
      s.lidOpen = !s.lidOpen;
      if (s.lidOpen && s.spindle) { s.spindle = false; }
      say(s.lidOpen ? "Lid open: the chip says so, and the spindle will not run." : "Lid closed.");
    });
    A.button(row, "STOP", function () { doStop(); }, null, "Esc");
    st = A.status(row);
    say("Press Connect to start. The buttons are the bar's; the drawing is the machine.");

    function doStop() {
      if (!s.linked) { say("STOP: nothing is connected, so there is nothing to stop. It is never a dead button: it always says why.", "caution"); return; }
      s.moving = false; s.afterMove = null; s.target = s.z; s.spindle = false; s.stopped = true;
      say("STOP: the move in flight is dropped and the spindle stops. The bit stays where it is: raise it with ↑ (Page Up) before the next move. Esc does the same from anywhere.", "bad");
      if (A.reduced) paint(0);
    }
    host.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { doStop(); e.preventDefault(); }
    });
    // clicking the drawn STOP works too
    stopG.style.cursor = "pointer";
    stopG.addEventListener("click", doStop);

    function f2(v) { return (v < 0 ? "−" : " ") + Math.abs(v).toFixed(2); }
    var ang = 0;
    function paint(dt) {
      if (s.connecting > 0) {
        s.connecting -= dt;
        if (s.connecting <= 0) { s.connecting = 0; s.linked = true; say("Linked: the readout is the machine's position, three times a second.", "ok"); }
      }
      if (s.moving) {
        var dz = s.target - s.z, v = 6 * dt;
        if (Math.abs(dz) <= v) finishMove(); else s.z += Math.sign(dz) * v;
      }
      var chip = !s.linked ? (s.connecting > 0 ? ["Connecting…", C.caution] : ["Machine offline", C.text3])
        : s.lidOpen ? ["Lid open", C.caution] : s.spindle ? ["Spindle on", C.caution] : ["Linked", C.live];
      chipT.textContent = chip[0]; chipT.setAttribute("fill", chip[1]);
      A.set(chipR, { stroke: chip[1], fill: s.linked && !s.lidOpen && !s.spindle ? C.liveFill : C.sunk });
      var t = touching();
      dro.X.val.textContent = s.linked ? " 60.52" : "—";
      dro.Y.val.textContent = s.linked ? " 24.42" : "—";
      dro.Z.val.textContent = s.linked ? f2(s.z) : "—";
      dro.Z.lab.textContent = t ? "Touch" : "Z";
      dro.Z.val.setAttribute("fill", t ? C.danger : C.text);
      dro.Z.lab.setAttribute("fill", t ? C.danger : C.text3);
      var gap = s.z - SURF;
      A.set(head, { transform: "translate(0," + (CU - Math.min(gap, 9) * K) + ")" });
      gapT.textContent = gap > 0.004 ? "bit " + gap.toFixed(2) + " mm above the copper" : "bit on the copper";
      gapT.setAttribute("fill", gap > 0.004 ? "#e8dccb" : "#ffb3ad");
      if (s.spindle) { ang = (ang + dt * 8) % 1; }
      spin.setAttribute("opacity", s.spindle ? 1 : 0);
      spinArc.setAttribute("stroke-dashoffset", String(ang * 40));
      spinArc.setAttribute("stroke-dasharray", "20 8");
      lidR.setAttribute("stroke", s.lidOpen ? C.caution : C.ruleStrong);
      lidR.setAttribute("stroke-dasharray", s.lidOpen ? "10 8" : "none");
      lidT.textContent = s.lidOpen ? "lid open" : "lid closed";
      lidT.setAttribute("fill", s.lidOpen ? C.caution : C.text3);
      zeroLine.setAttribute("opacity", s.g54 !== null ? 1 : 0);
      facts.app.textContent = s.appZ === null ? "not yet" : "machine Z " + f2(s.appZ);
      facts.app.setAttribute("fill", s.appZ === null ? C.text3 : C.ok);
      facts.g54.textContent = s.g54 === null ? "unchanged" : "set at the copper";
      facts.g54.setAttribute("fill", s.g54 === null ? C.text3 : C.caution);
      facts.spindle.textContent = s.spindle ? "on (speed: VPanel)" : "off";
      facts.spindle.setAttribute("fill", s.spindle ? C.caution : C.text3);
      facts.move.textContent = s.moving ? "moving" : s.stopped ? "stopped: bit left down" : "idle";
      facts.move.setAttribute("fill", s.moving ? C.live : s.stopped ? C.danger : C.text3);
    }
    A.loop(host, function (t, dt) { paint(dt); }, 0);
    paint(0);
    if (A.reduced) {
      // no frame loop: repaint after every click
      row.addEventListener("click", function () { setTimeout(function () { paint(0); }, 0); });
    }
  });
})();
