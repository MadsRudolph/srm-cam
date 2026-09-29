/* SRM-CAM guide: the explainer animations, shared parts.

   Every animation is a <figure class="anim" data-anim="name"> in the page. The
   widget files (js/anim/<name>.js) register a builder with SRMAnim.define(); once
   the page has loaded, each figure gets its builder, which draws an SVG into it and,
   where it helps, a row of controls under it. The palette is the site's (css/site.css),
   which is the app's own (gerber2rml/gui2/theme.py).

   Rules the widgets keep:
   - Draw into SRMAnim.stage(host, w, h): a viewBox of w x h user units that scales
     to the column width, so one drawing serves a phone and a desktop.
   - Anything that moves by itself runs through SRMAnim.loop(), which only ticks while
     the figure is on screen, and shows the final state straight away when the reader
     asked for reduced motion.
   - Numbers shown are real: the lab's 0.8 mm bit, the SRM-20's travel, the values in
     the recording. Schematic parts say so in the drawing. */
(function () {
  "use strict";

  var C = {
    ink: "#08090b", base: "#101318", panel: "#161a20", panelHi: "#1c2129", raised: "#242b34",
    sunk: "#0d1015", rule: "#1f242b", ruleHi: "#2b323b", ruleStrong: "#3b4550",
    text: "#eef2f6", text2: "#aab3bd", text3: "#767f89", text4: "#4d555e",
    copper: "#b4763c", copperHi: "#d59456", copperDim: "#6b482a", copperFill: "#2a1e13",
    fr4: "#7d7444", fr4Hi: "#a39a62", board: "#6e5a3e", steel: "#c9ced6", steelDim: "#8a919b",
    live: "#4ea8ff", liveFill: "#0c1c2e", ok: "#52c98a", okFill: "#0f2419",
    caution: "#f0a33c", cautionFill: "#2a1e0d", danger: "#ff4d4d", dangerFill: "#2b1113"
  };
  var FONT = {
    sans: '"Segoe UI Variable Text","Segoe UI",Inter,system-ui,sans-serif',
    label: 'Bahnschrift,"Barlow Semi Condensed","Arial Narrow",sans-serif',
    mono: '"Cascadia Mono",Consolas,"JetBrains Mono","DejaVu Sans Mono",monospace'
  };
  var NS = "http://www.w3.org/2000/svg";
  var reduced = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var registry = {};

  /** Create an SVG element under parent. attrs: attribute map; text: text content. */
  function el(parent, tag, attrs, text) {
    var n = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) n.setAttribute(k, attrs[k]);
    if (text !== undefined && text !== null) n.textContent = text;
    if (parent) parent.appendChild(n);
    return n;
  }

  /** Set attributes on an existing element (a cheap way to animate). */
  function set(n, attrs) {
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }

  /** Text in the guide's type. o: {size, weight, fill, anchor ('start'|'middle'|'end'), font ('sans'|'label'|'mono'), baseline} */
  function text(parent, x, y, s, o) {
    o = o || {};
    return el(parent, "text", {
      x: x, y: y, fill: o.fill || C.text, "font-size": o.size || 14, "font-weight": o.weight || 500,
      "font-family": FONT[o.font || "sans"], "text-anchor": o.anchor || "start",
      "dominant-baseline": o.baseline || "alphabetic", "letter-spacing": o.spacing
    }, s);
  }

  /** The drawing area: an SVG of w x h user units, placed before the figcaption. */
  function stage(host, w, h, label) {
    var wrap = document.createElement("div");
    wrap.className = "anim-stage";
    var s = el(null, "svg", { viewBox: "0 0 " + w + " " + h, role: "img", "aria-label": label || "" });
    s.style.aspectRatio = w + " / " + h;
    wrap.appendChild(s);
    host.insertBefore(wrap, host.querySelector("figcaption"));
    return s;
  }

  /** A row for buttons and sliders, under the drawing. */
  function controls(host) {
    var row = document.createElement("div");
    row.className = "anim-controls";
    host.insertBefore(row, host.querySelector("figcaption"));
    return row;
  }

  /** A button. kind: '' | 'primary' | 'key' (a small square key, like the app's jog keys). */
  function button(row, label, onClick, kind, title) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "anim-btn" + (kind ? " " + kind : "");
    b.textContent = label;
    if (title) b.title = title;
    b.addEventListener("click", onClick);
    row.appendChild(b);
    return b;
  }

  /** A labelled slider. fmt(v) gives the readout text. Returns the <input>. */
  function slider(row, label, min, max, step, value, onInput, fmt) {
    var w = document.createElement("label");
    w.className = "anim-slider";
    var t = document.createElement("span");
    t.className = "k";
    t.textContent = label;
    var i = document.createElement("input");
    i.type = "range"; i.min = min; i.max = max; i.step = step; i.value = value;
    var v = document.createElement("span");
    v.className = "v";
    function upd() { var x = parseFloat(i.value); v.textContent = fmt ? fmt(x) : x; onInput(x); }
    i.addEventListener("input", upd);
    w.appendChild(t); w.appendChild(i); w.appendChild(v);
    row.appendChild(w);
    upd();
    return i;
  }

  /** A segmented switch, like the app's. options: [[value, label], ...]. */
  function segmented(row, options, value, onChange) {
    var g = document.createElement("div");
    g.className = "anim-seg";
    var btns = options.map(function (o) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = o[1];
      b.addEventListener("click", function () { pick(o[0]); });
      g.appendChild(b);
      return b;
    });
    function pick(v) {
      options.forEach(function (o, k) { btns[k].classList.toggle("on", o[0] === v); });
      onChange(v);
    }
    row.appendChild(g);
    pick(value);
    return { set: pick };
  }

  /** A line of status text under the drawing (what just happened, in words). */
  function status(row) {
    var s = document.createElement("span");
    s.className = "anim-status";
    s.setAttribute("aria-live", "polite");
    row.appendChild(s);
    return s;
  }

  function ease(x) { x = Math.min(Math.max(x, 0), 1); return 1 - Math.pow(1 - x, 3); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function clamp(x, a, b) { return Math.min(Math.max(x, a), b); }

  /** Run tick(t, dt) every frame while host is on screen; t in seconds since start (or restart).
      Returns {restart(), stop(), running()}. With reduced motion, tick is called once
      with t = finalT (if given) so the finished state shows. */
  function loop(host, tick, finalT) {
    var t0 = null, last = null, visible = false, stopped = false, raf = 0, acc = 0;
    function frame(now) {
      raf = 0;
      if (stopped || !visible) return;
      if (last === null) last = now;
      var dt = Math.min((now - last) / 1000, 0.1);
      last = now;
      acc += dt;
      tick(acc, dt);
      raf = requestAnimationFrame(frame);
    }
    function kick() { if (!raf && visible && !stopped) { last = null; raf = requestAnimationFrame(frame); } }
    if (reduced && finalT !== undefined) {
      tick(finalT, 0);
      return { restart: function () { tick(finalT, 0); }, stop: function () {}, running: function () { return false; } };
    }
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (es) {
        visible = es[0].isIntersecting;
        kick();
      }, { threshold: 0.15 }).observe(host);
    } else {
      visible = true;
    }
    kick();
    return {
      restart: function () { acc = 0; stopped = false; kick(); },
      stop: function () { stopped = true; },
      running: function () { return !stopped; }
    };
  }

  /** Arrow from (x1,y1) to (x2,y2). */
  function arrow(parent, x1, y1, x2, y2, o) {
    o = o || {};
    var g = el(parent, "g", { stroke: o.color || C.text3, fill: o.color || C.text3 });
    el(g, "line", { x1: x1, y1: y1, x2: x2, y2: y2, "stroke-width": o.width || 2 });
    var a = Math.atan2(y2 - y1, x2 - x1), h = o.head || 8;
    el(g, "polygon", {
      points: [x2, y2, x2 - h * Math.cos(a - 0.45), y2 - h * Math.sin(a - 0.45),
        x2 - h * Math.cos(a + 0.45), y2 - h * Math.sin(a + 0.45)].join(","), stroke: "none"
    });
    return g;
  }

  function define(name, build) { registry[name] = build; }

  function boot() {
    var hosts = document.querySelectorAll("[data-anim]");
    Array.prototype.forEach.call(hosts, function (h) {
      var b = registry[h.getAttribute("data-anim")];
      if (!b || h.dataset.built) return;
      h.dataset.built = "1";
      try { b(h); } catch (e) { if (window.console) console.error("anim " + h.getAttribute("data-anim"), e); }
    });
  }

  window.SRMAnim = {
    C: C, FONT: FONT, reduced: reduced, el: el, set: set, text: text, stage: stage, controls: controls,
    button: button, slider: slider, segmented: segmented, status: status, ease: ease, lerp: lerp,
    clamp: clamp, loop: loop, arrow: arrow, define: define
  };
  // Widget files load after this one (defer); DOMContentLoaded waits for every deferred
  // script, so boot then. boot is idempotent, so the load event is a harmless backstop.
  if (document.readyState !== "complete") {
    document.addEventListener("DOMContentLoaded", boot);
    window.addEventListener("load", boot);
  } else {
    setTimeout(boot, 0);
  }
})();
