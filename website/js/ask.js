/* "Ask SRM-CAM": a floating chat pane on every page of the guide.

   A round button at the bottom right opens a pane where a student asks a
   question; the answer streams in from the SRM-CAM assistant (the Worker in
   ask/ in the repo), which answers from this guide and links the section it
   used. The conversation is kept for the browser tab (sessionStorage), so it
   survives moving between pages. No account, no cookies. */
(function () {
  "use strict";
  var API = "https://srm-cam-ask.madsrudolph.dev/chat";
  var DISCORD = "https://discord.gg/JUVbzanj6B";
  var KEY = "srmcam-ask-v1";
  var SUGGEST = [
    "How do I make a board with the laser?",
    "Calibrate says fewer than 90 % of the holes were seen",
    "Hvordan sætter jeg design rules i KiCad?",
    "The traces are not through at the edges"
  ];

  var css = "" +
    ".ask-btn{position:fixed;right:20px;bottom:20px;z-index:60;display:flex;align-items:center;gap:8px;" +
    "padding:11px 16px 11px 13px;border-radius:999px;border:1px solid var(--copper-dim);background:var(--copper-fill);" +
    "color:var(--copper-hi);font:600 0.92rem/1 var(--label);letter-spacing:.04em;cursor:pointer;box-shadow:0 6px 24px rgba(0,0,0,.45)}" +
    ".ask-btn:hover{background:#3a2818;color:#fff}" +
    ".ask-btn svg{width:20px;height:20px}" +
    ".ask-pane{position:fixed;right:20px;bottom:20px;z-index:61;width:min(420px,calc(100vw - 32px));" +
    "height:min(620px,calc(100vh - 40px));display:none;flex-direction:column;background:var(--panel);" +
    "border:1px solid var(--rule-hi);border-radius:10px;box-shadow:0 12px 48px rgba(0,0,0,.6);overflow:hidden}" +
    ".ask-pane.open{display:flex}" +
    ".ask-head{display:flex;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid var(--rule);background:var(--panel-hi)}" +
    ".ask-head img{width:26px;height:26px;border-radius:6px}" +
    ".ask-head .n{font:600 1rem/1.1 var(--display);color:var(--text)}" +
    ".ask-head .s{font-size:.74rem;color:var(--text-3)}" +
    ".ask-head .x{margin-left:auto;background:none;border:0;color:var(--text-3);font-size:1.3rem;cursor:pointer;padding:2px 6px}" +
    ".ask-head .x:hover{color:var(--text)}" +
    ".ask-head .clr{background:none;border:0;color:var(--text-3);font-size:.75rem;cursor:pointer}" +
    ".ask-log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}" +
    ".ask-m{max-width:88%;padding:9px 12px;border-radius:9px;font-size:.9rem;line-height:1.5;white-space:normal;word-wrap:break-word}" +
    ".ask-m.u{align-self:flex-end;background:var(--select);border:1px solid var(--select-edge);color:var(--text)}" +
    ".ask-m.a{align-self:flex-start;background:var(--raised);color:var(--text)}" +
    ".ask-m.a a{color:var(--live)}" +
    ".ask-m.a code{font-family:var(--mono);font-size:.84em;background:var(--sunk);padding:1px 4px;border-radius:3px}" +
    ".ask-m.a ul,.ask-m.a ol{margin:6px 0 6px 18px;padding:0}" +
    ".ask-m.a p{margin:0 0 6px}.ask-m.a p:last-child{margin:0}" +
    ".ask-m.err{background:var(--danger-fill);border:1px solid var(--danger-edge)}" +
    ".ask-dots span{display:inline-block;width:6px;height:6px;margin-right:4px;border-radius:50%;background:var(--text-3);animation:askb 1s infinite}" +
    ".ask-dots span:nth-child(2){animation-delay:.15s}.ask-dots span:nth-child(3){animation-delay:.3s}" +
    "@keyframes askb{0%,80%,100%{opacity:.25}40%{opacity:1}}" +
    ".ask-hi{color:var(--text-2);font-size:.88rem;line-height:1.5}" +
    ".ask-sug{display:flex;flex-direction:column;gap:6px;margin-top:8px}" +
    ".ask-sug button{text-align:left;background:var(--panel-hi);border:1px solid var(--rule-hi);color:var(--text-2);" +
    "border-radius:7px;padding:7px 10px;font:inherit;font-size:.84rem;cursor:pointer}" +
    ".ask-sug button:hover{border-color:var(--copper-dim);color:var(--text)}" +
    ".ask-form{display:flex;gap:8px;padding:10px;border-top:1px solid var(--rule);background:var(--panel-hi)}" +
    ".ask-form textarea{flex:1;resize:none;height:42px;max-height:120px;background:var(--sunk);color:var(--text);" +
    "border:1px solid var(--rule-hi);border-radius:7px;padding:10px;font:inherit;font-size:.9rem}" +
    ".ask-form textarea:focus{outline:none;border-color:var(--copper-dim)}" +
    ".ask-form button{background:var(--copper);border:0;color:#111;border-radius:7px;padding:0 14px;font:600 .88rem var(--label);cursor:pointer}" +
    ".ask-form button:disabled{opacity:.5;cursor:default}" +
    ".ask-foot{padding:6px 12px 9px;font-size:.72rem;color:var(--text-3);background:var(--panel-hi)}" +
    ".ask-foot a{color:var(--text-2)}" +
    "@media (max-width:560px){.ask-pane{right:8px;bottom:8px;width:calc(100vw - 16px);height:calc(100vh - 16px)}" +
    ".ask-btn{right:12px;bottom:12px}.ask-btn .lbl{display:none}.ask-btn{padding:12px}}";

  var ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5V14"/><path d="M12 17h.01"/></svg>';

  function load() { try { return JSON.parse(sessionStorage.getItem(KEY) || "[]"); } catch (e) { return []; } }
  function save(h) { try { sessionStorage.setItem(KEY, JSON.stringify(h.slice(-20))); } catch (e) { /* private mode */ } }

  function esc(s) { return s.replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  /* Small, safe markdown: escaped first, then links, bold, code and lists. */
  function md(text) {
    var out = [], list = null;
    esc(text).split(/\n/).forEach(function (line) {
      var m = line.match(/^\s*(?:[-*]|(\d+)\.)\s+(.*)$/);
      if (m) {
        var tag = m[1] ? "ol" : "ul";
        if (!list || list.tag !== tag) { if (list) out.push("</" + list.tag + ">"); list = { tag: tag }; out.push("<" + tag + ">"); }
        out.push("<li>" + inline(m[2]) + "</li>");
        return;
      }
      if (list) { out.push("</" + list.tag + ">"); list = null; }
      if (line.trim()) out.push("<p>" + inline(line) + "</p>");
    });
    if (list) out.push("</" + list.tag + ">");
    return out.join("");
  }
  function inline(s) {
    return s
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:])/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function build() {
    var style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);

    var btn = document.createElement("button");
    btn.className = "ask-btn";
    btn.type = "button";
    btn.setAttribute("aria-label", "Ask SRM-CAM a question");
    btn.innerHTML = ICON + '<span class="lbl">Ask SRM-CAM</span>';

    var pane = document.createElement("section");
    pane.className = "ask-pane";
    pane.setAttribute("aria-label", "Ask SRM-CAM");
    pane.innerHTML =
      '<div class="ask-head"><img src="img/srm-cam-256.png" alt=""><div><div class="n">Ask SRM-CAM</div>' +
      '<div class="s">Answers from this guide</div></div>' +
      '<button class="clr" type="button" title="Start over">Clear</button>' +
      '<button class="x" type="button" aria-label="Close">×</button></div>' +
      '<div class="ask-log" aria-live="polite"></div>' +
      '<form class="ask-form"><textarea rows="1" placeholder="Ask about the mill, the laser, KiCad… (dansk er fint)" aria-label="Your question"></textarea>' +
      '<button type="submit">Ask</button></form>' +
      '<div class="ask-foot">AI answers can be wrong; check the guide. Stuck? <a href="' + DISCORD + '" target="_blank" rel="noopener">Ask on Discord</a>.</div>';
    document.body.appendChild(btn);
    document.body.appendChild(pane);

    var log = pane.querySelector(".ask-log");
    var form = pane.querySelector("form");
    var input = pane.querySelector("textarea");
    var send = form.querySelector("button");
    var history = load();
    var busy = false;

    function bubble(role, html, cls) {
      var d = document.createElement("div");
      d.className = "ask-m " + (role === "user" ? "u" : "a") + (cls ? " " + cls : "");
      d.innerHTML = html;
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
      return d;
    }
    function render() {
      log.innerHTML = "";
      if (!history.length) {
        var hi = document.createElement("div");
        hi.className = "ask-hi";
        hi.innerHTML = "Hi! Ask anything about making a board with SRM-CAM: KiCad, the mill, the laser, mask, troubleshooting. I answer from this guide and link the page.";
        var sug = document.createElement("div");
        sug.className = "ask-sug";
        SUGGEST.forEach(function (q) {
          var b = document.createElement("button");
          b.type = "button"; b.textContent = q;
          b.onclick = function () { ask(q); };
          sug.appendChild(b);
        });
        hi.appendChild(sug);
        log.appendChild(hi);
      }
      history.forEach(function (m) { bubble(m.role, m.role === "user" ? esc(m.content) : md(m.content)); });
    }
    function open() { pane.classList.add("open"); btn.style.display = "none"; render(); setTimeout(function () { input.focus(); }, 50); }
    function close() { pane.classList.remove("open"); btn.style.display = ""; }

    btn.onclick = open;
    pane.querySelector(".x").onclick = close;
    pane.querySelector(".clr").onclick = function () { if (!busy) { history = []; save(history); render(); } };
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && pane.classList.contains("open")) close(); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : form.onsubmit(e); }
    });
    form.onsubmit = function (e) { e.preventDefault(); var q = input.value.trim(); if (q) ask(q); };

    function ask(q) {
      if (busy) return;
      busy = true; send.disabled = true; input.value = "";
      if (!history.length) log.innerHTML = "";
      history.push({ role: "user", content: q });
      bubble("user", esc(q));
      var a = bubble("assistant", '<span class="ask-dots"><span></span><span></span><span></span></span>');
      var text = "";

      fetch(API, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: history }) })
        .then(function (res) {
          if (!res.ok || !res.body) {
            return res.json().catch(function () { return {}; }).then(function (j) { throw new Error(j.error || "The assistant is unavailable right now."); });
          }
          var reader = res.body.getReader(), dec = new TextDecoder(), buf = "";
          function pump() {
            return reader.read().then(function (r) {
              if (r.done) return;
              buf += dec.decode(r.value, { stream: true });
              var parts = buf.split("\n\n"); buf = parts.pop();
              parts.forEach(function (p) {
                if (p.indexOf("data: ") !== 0) return;
                var ev; try { ev = JSON.parse(p.slice(6)); } catch (e) { return; }
                if (ev.t) { text += ev.t; a.innerHTML = md(text); log.scrollTop = log.scrollHeight; }
                if (ev.error) throw new Error(ev.error);
              });
              return pump();
            });
          }
          return pump();
        })
        .then(function () {
          if (!text) throw new Error("No answer came back. Try again.");
          history.push({ role: "assistant", content: text });
          save(history);
        })
        .catch(function (err) {
          a.className = "ask-m a err";
          a.innerHTML = esc(err.message || "Something went wrong.") + ' <a href="' + DISCORD + '" target="_blank" rel="noopener">Ask on Discord</a>.';
          history.pop();
          save(history);
        })
        .then(function () { busy = false; send.disabled = false; input.focus(); });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build);
  else build();
})();
