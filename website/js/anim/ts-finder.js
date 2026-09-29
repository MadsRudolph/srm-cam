/* Find your symptom. The answers are the page's own <details class="ts-item"> entries,
   so the page reads the same without scripts; this adds a search box and the
   categories, and opens the answer you pick. Each entry: data-cat (a category key
   matching an <h2 data-cat-title>), and optional data-q (extra words to match). */
(function () {
  "use strict";
  var A = window.SRMAnim;

  A.define("ts-finder", function (host) {
    var items = Array.prototype.slice.call(document.querySelectorAll("details.ts-item"));
    var cats = [["all", "All"]];
    Array.prototype.forEach.call(document.querySelectorAll("[data-cat-title]"), function (h) {
      cats.push([h.getAttribute("data-cat-title"), h.getAttribute("data-short") || h.textContent.trim()]);
    });
    var wrap = document.createElement("div");
    wrap.className = "anim-stage ts-finder";
    host.insertBefore(wrap, host.querySelector("figcaption"));

    var search = document.createElement("input");
    search.type = "search";
    search.className = "ts-search";
    search.placeholder = "Describe what happened: stops, shorted, no touch, cut-out…";
    search.setAttribute("aria-label", "Search the symptoms");
    wrap.appendChild(search);
    var chips = document.createElement("div");
    chips.className = "ts-chips";
    wrap.appendChild(chips);
    var list = document.createElement("ol");
    list.className = "ts-results";
    wrap.appendChild(list);
    var count = document.createElement("div");
    count.className = "ts-count";
    count.setAttribute("aria-live", "polite");
    wrap.appendChild(count);

    var cat = "all";
    var chipBtns = cats.map(function (c) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = c[1];
      b.addEventListener("click", function () { cat = c[0]; draw(); });
      chips.appendChild(b);
      return b;
    });

    function words(s) { return s.toLowerCase().replace(/[^a-z0-9−\-. ]+/g, " ").split(/\s+/).filter(Boolean); }

    function draw() {
      chipBtns.forEach(function (b, i) { b.classList.toggle("on", cats[i][0] === cat); b.setAttribute("aria-pressed", cats[i][0] === cat); });
      var q = words(search.value);
      list.innerHTML = "";
      var n = 0;
      items.forEach(function (d) {
        if (cat !== "all" && d.getAttribute("data-cat") !== cat) return;
        var hay = (d.textContent + " " + (d.getAttribute("data-q") || "")).toLowerCase();
        if (q.length && !q.every(function (w) { return hay.indexOf(w) >= 0; })) return;
        n++;
        var li = document.createElement("li");
        var b = document.createElement("button");
        b.type = "button";
        b.className = "ts-hit";
        var t = document.createElement("span");
        t.className = "t";
        t.textContent = d.querySelector("summary").textContent;
        var c = document.createElement("span");
        c.className = "c";
        var cl = cats.filter(function (x) { return x[0] === d.getAttribute("data-cat"); })[0];
        c.textContent = cl ? cl[1] : "";
        b.appendChild(t); b.appendChild(c);
        b.addEventListener("click", function () {
          d.open = true;
          d.scrollIntoView({ behavior: A.reduced ? "auto" : "smooth", block: "start" });
          d.classList.add("flash");
          setTimeout(function () { d.classList.remove("flash"); }, 1600);
          var s = d.querySelector("summary");
          if (s) s.focus({ preventScroll: true });
        });
        li.appendChild(b);
        list.appendChild(li);
      });
      count.textContent = n ? n + (n === 1 ? " symptom" : " symptoms") + " — pick one to open its answer." :
        "Nothing matches. Try fewer words, or open an issue with what you saw.";
    }
    search.addEventListener("input", draw);
    draw();
  });
})();
