/* What is in the exported files. The job's files in run order (or in the order VPanel
   lists them: alphabetically, so the cut-out lands above the drill), each opened at its
   first lines, and every line explained on a click. The lines are the golden test's
   output (tests/fixtures/golden, the lab's one-bit 0.8 mm profile, so the drill runs
   first), in G-code (.nc, the default) or RML (.rml, "Roland SRM-20"). */
(function () {
  "use strict";
  var A = window.SRMAnim;

  var HEAD = [
    ["%", "Start of the program. VPanel needs it as the first line."],
    ["O0001", "The program number."],
    ["( gerber2rml - SRM-20 NC )", "A comment. Anything in round brackets is ignored by the machine; SRM-CAM uses them so each file says what it is."]
  ];
  var PRE = [
    ["G90 G17", "Absolute coordinates, in the XY plane."],
    ["G21", "Millimetres."],
    ["G91", "Relative, for the next line only…"],
    ["G28 Z0.", "…so this lifts Z straight up to the top of its travel before anything moves sideways."],
    ["G90", "Back to absolute coordinates."],
    ["G54", "The work coordinates: the origin you set in VPanel on G54. X and Y are the machine origin (you never set them); Z is the zero you set on the copper."]
  ];
  var SPIN = [
    ["M3", "Spindle on. The speed is not in the file: the SRM-20 has no S word, so it is set in VPanel's cut settings."],
    ["( spindle spin-up settle 2. s before first cut )", "Why the next line is there."],
    ["G04 X2.", "Wait 2 s so the spindle is at full speed before the bit touches copper. The SRM-20 starts M3 without waiting."]
  ];

  var GCODE = {
    airpass: HEAD.concat([
      ["( board - step 0 of 4: DRY RUN )", "Which step this is. In VPanel's list the file name is otherwise the only clue."],
      ["( spindle OFF, bit held 5 mm up - this file cannot cut )", "The dry run never starts the spindle."],
      ["( watch it trace the outline, then run the drill file )", "Names the next file. The drill, because one 0.8 mm bit does the holes and the traces on this job."]
    ]).concat(PRE).concat([
      ["( DRY RUN - spindle stays OFF, nothing is cut )", "And no M3 anywhere in this file."],
      ["G0 Z5.", "Rapid to 5 mm above the copper zero."],
      ["G0 X106. Y106.", "Rapid to the first corner of the outline."],
      ["G1 X2. Y106. Z5. F900.", "Trace the outline, still 5 mm up. F is in mm/min: 900 is 15 mm/s, slow enough to watch."],
      ["G1 X2. Y2. Z5.", "The next side: F carries on until it changes."]
    ]),
    drill: HEAD.concat([
      ["( board - step 1 of 4: DRILL )", "Step 1: on a one-bit job the lab drills first."],
      ["( bit 0.8 mm, through 1.7 mm )", "The bit, and the depth: through the 1.6 mm board into the spoilboard."],
      ["( re-zero Z after the bit change; do NOT move the XY origin )", "The rule, in every file."],
      ["( spindle 7000 rpm - set this in VPanel cut settings )", "The speed the feeds were chosen for."]
    ]).concat(PRE).concat(SPIN).concat([
      ["G0 Z2.", "Up to the lift height, 2 mm above the copper."],
      ["G0 X79.405 Y26.663", "Rapid over the first hole."],
      ["G0 Z0.5", "Rapid down to 0.5 mm above the copper, so the slow plunge starts close."],
      ["G1 X79.405 Y26.663 Z-0.6 F60.", "Plunge 0.6 mm at 1 mm/s (F60 = 60 mm/min): one peck."],
      ["G0 Z0.5", "Out again to clear the chips…"],
      ["G0 Z-0.4", "…and straight back down to just above the last depth, for the next peck."]
    ]),
    traces: HEAD.concat([
      ["( board - step 2 of 4: ISOLATION TRACES )", "Step 2, after the drill."],
      ["( bit 0.8 mm, 1 offset, 0.15 mm per pass, feed 4.0 mm/s )", "One channel around every copper feature, 0.15 mm deep."],
      ["( re-zero Z after any bit change; do NOT move the XY origin )", "The rule again."],
      ["( spindle 7000 rpm - set this in VPanel cut settings )", "The speed the feeds were chosen for."]
    ]).concat(PRE).concat(SPIN).concat([
      ["G0 Z2.", "Lift height."],
      ["G0 X2.209 Y105.689", "Over the start of the first channel."],
      ["G0 Z0.8", "Down towards the copper at rapid speed…"],
      ["G0 Z0.5", "…stopping 0.5 mm above it."],
      ["G1 X2.209 Y105.689 Z0.2 F60.", "Feed down at 1 mm/s to 0.2 mm above the copper."],
      ["G1 X2.4 Y105.847 Z0.113", "The lead-in: the bit ramps into the cut while it moves, instead of plunging straight down, which is kinder to a 0.8 mm bit. With a height map applied, every Z in this file follows the surface."]
    ]),
    cutout: HEAD.concat([
      ["( board - step 3 of 4: CUT-OUT - RUN THIS LAST )", "The one that frees the board. Everything else must be done first."],
      ["( bit 0.8 mm, through 1.7 mm, 4 tabs x 1.5 mm )", "Through the board, leaving four 1.5 mm tabs to hold it."],
      ["( frees the board from the waste - everything else must be done )", "Said twice, on purpose."],
      ["( spindle 7000 rpm - set this in VPanel cut settings )", "The speed the feeds were chosen for."]
    ]).concat(PRE).concat(SPIN).concat([
      ["…", "(the outline, in passes of 0.6 mm, lifting over the tabs)"],
      ["M5", "Spindle off."],
      ["G91", "Relative…"],
      ["G28 X0. Y0.", "…park the head at the machine's home in X and Y."],
      ["G90", "Absolute again."],
      ["M30", "End of the program."],
      ["%", "End of the file."]
    ]),
    runplan: [
      ["SRM-20 run plan: board  [Roland SRM-20 (G-code)]", "The run sheet as text, written beside the programs. It is not sent to the machine."],
      ["Send each file via VPanel: Cut -> Add -> Output. Zero Z on the copper first, with VPanel on G54; X and Y stay at the machine origin.", "How the files are meant to be run."],
      ["VPanel lists the files alphabetically: move the cutout to the bottom.", "The trap: VPanel sorts the files by name, and cutout comes before drill and traces."],
      ["Order: 0) airpass  1) drill  2) traces  3) cutout. Re-set Z-zero after each bit change; keep XY origin.", "The order. With a different bit for the traces (a V-bit), the traces come first instead, to save bit changes."],
      ["1. drill  — board_drill.nc: one 0.8 mm bit, plunge holes that fit + interpolate larger ones, total 1.7 mm", "Holes that fit the bit are plunged; larger ones are milled as circles."],
      ["2. traces  — bit 0.8 mm, 1 offsets, cut 0.15 mm/pass, feed 4.0 mm/s", ""],
      ["3. cutout  — bit 0.8 mm, 4 tabs x 1.5 mm, total 1.7 mm", ""],
      ["Estimated run time (excludes tool changes, spin-up and pauses):", "Per file, then the total. The golden board takes about 24 minutes."]
    ]
  };

  var RML = {
    airpass: [
      ["^IN;!MC0;", "Initialise, and spindle OFF (!MC0). RML has no comments, so nothing in the file says it is the dry run: only its name does."],
      ["VS15.0;!VZ15.0;", "Speeds, in mm/s here (not mm/min): VS for moves in XY, !VZ for moves in Z."],
      ["Z10600,10600,500;", "A move to X, Y, Z in RML units of 0.01 mm: X 106.00, Y 106.00, Z 5.00 mm above the copper."],
      ["Z200,10600,500;", "The outline, 5 mm up."]
    ],
    drill: [
      ["^IN;!MC1;", "Initialise, spindle ON."],
      ["VS15.0;!VZ15.0;", "Fast moves between holes."],
      ["Z7940,2666,200;", "Over the first hole, 2 mm up (X 79.40, Y 26.66)."],
      ["Z7940,2666,50;", "Down to 0.5 mm above the copper."],
      ["VS4.0;!VZ1.0;", "Cutting speeds: 4 mm/s in XY, 1 mm/s in Z."],
      ["Z7940,2666,-60;", "Plunge to −0.60 mm: one peck."],
      ["VS15.0;!VZ15.0;", "Fast again, to clear the chips."]
    ],
    traces: [
      ["^IN;!MC1;", "Initialise, spindle ON."],
      ["VS15.0;!VZ15.0;", "Fast moves."],
      ["Z221,10569,200;", "Over the start of the first channel, 2 mm up."],
      ["Z221,10569,80;", "Down to 0.8 mm."],
      ["VS4.0;!VZ1.0;", "Cutting speeds."],
      ["Z221,10569,20;", "To 0.2 mm above the copper…"],
      ["Z240,10585,11;", "…and the lead-in ramp into the cut."]
    ],
    cutout: [
      ["^IN;!MC1;", "Initialise, spindle ON. Nothing in the file says 'run this last': in RML only the name does."],
      ["…", "(the outline, in passes, lifting over the tabs)"],
      ["Z10588,10640,200;", "Lift clear at the end."],
      ["!MC0;^IN;", "Spindle off, and reset."]
    ],
    runplan: null
  };

  var FILES = [
    ["airpass", "board_airpass", "0 · Dry run"],
    ["drill", "board_drill", "1 · Drill"],
    ["traces", "board_traces", "2 · Isolation traces"],
    ["cutout", "board_cutout", "3 · Cut-out, last"],
    ["runplan", "board_runplan", "The run plan"]
  ];

  A.define("rf-files", function (host) {
    var fmt = "gcode", order = "run", pick = "drill", line = 0;
    var wrap = document.createElement("div");
    wrap.className = "anim-stage rf-files";
    host.insertBefore(wrap, host.querySelector("figcaption"));
    var list = document.createElement("div");
    list.className = "rf-list";
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", "Exported files");
    var right = document.createElement("div");
    right.className = "rf-right";
    var code = document.createElement("div");
    code.className = "rf-code";
    var note = document.createElement("div");
    note.className = "rf-note";
    note.setAttribute("aria-live", "polite");
    right.appendChild(code);
    right.appendChild(note);
    wrap.appendChild(list);
    wrap.appendChild(right);

    var row = A.controls(host);
    A.segmented(row, [["gcode", "G-code (.nc)"], ["rml", "RML (.rml)"]], fmt, function (v) { fmt = v; line = 0; draw(); });
    A.segmented(row, [["run", "Run order"], ["vpanel", "As VPanel lists them"]], order, function (v) { order = v; draw(); });
    var st = A.status(row);

    function ext(k) { return k === "runplan" ? ".txt" : (fmt === "gcode" ? ".nc" : ".rml"); }

    function draw() {
      if (!st) return;                          // the switches fire once while they are built
      list.innerHTML = "";
      var files = FILES.filter(function (f) { return order === "run" || f[0] !== "runplan"; });
      if (order === "vpanel") files = files.slice().sort(function (a, b) { return a[1] < b[1] ? -1 : 1; });
      files.forEach(function (f, i) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "rf-file" + (f[0] === pick ? " on" : "") + (order === "vpanel" && f[0] === "cutout" && i < files.length - 1 ? " bad" : "");
        b.setAttribute("role", "option");
        b.setAttribute("aria-selected", f[0] === pick ? "true" : "false");
        var n = document.createElement("span");
        n.className = "fn";
        n.textContent = f[1] + ext(f[0]);
        var d = document.createElement("span");
        d.className = "fd";
        d.textContent = order === "vpanel" ? "list row " + (i + 1) : f[2];
        b.appendChild(n); b.appendChild(d);
        b.addEventListener("click", function () { pick = f[0]; line = 0; draw(); });
        list.appendChild(b);
      });
      if (order === "vpanel") {
        st.className = "anim-status bad";
        st.textContent = "VPanel sorts by name: airpass, cutout, drill, traces. The cut-out lands above the drill, so move it to the bottom before Output.";
      } else {
        st.className = "anim-status";
        st.textContent = fmt === "gcode"
          ? "G-code: millimetres, G54, feeds in mm/min. Click a line to see what it does."
          : "RML: 0.01 mm units, speeds in mm/s, and no comments. Click a line to see what it does.";
      }
      var lines = (fmt === "rml" && RML[pick]) ? RML[pick] : GCODE[pick];
      code.innerHTML = "";
      var ttl = document.createElement("div");
      ttl.className = "rf-title";
      ttl.textContent = "board_" + pick + ext(pick) + (pick === "runplan" && fmt === "rml" ? "  (the same for both formats)" : "");
      code.appendChild(ttl);
      lines.forEach(function (l, k) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "rf-line" + (k === line ? " on" : "") + (l[0].charAt(0) === "(" ? " cm" : "");
        var no = document.createElement("span");
        no.className = "no";
        no.textContent = k + 1;
        var tx = document.createElement("span");
        tx.className = "tx";
        tx.textContent = l[0];
        b.appendChild(no); b.appendChild(tx);
        b.addEventListener("click", function () { line = k; draw(); });
        code.appendChild(b);
      });
      var cur = lines[Math.min(line, lines.length - 1)];
      note.textContent = cur[1] || "—";
    }
    draw();
  });
})();
