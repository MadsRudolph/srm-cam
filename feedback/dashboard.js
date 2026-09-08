/**
 * The maintainer's dashboard, served at GET /dashboard.
 *
 * The page itself holds no data. It asks for the export token once, keeps
 * it in the browser, and reads /export with it. Open /dashboard#demo to see
 * the layout with example rows before any real feedback has arrived.
 */
export const DASHBOARD_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>SRM-CAM feedback</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --base:#101318; --panel:#161a20; --panel-hi:#1c2129; --sunk:#0d1015;
    --rule:#1f242b; --rule-hi:#2b323b; --rule-strong:#3b4550;
    --text:#eef2f6; --dim:#aab3bd; --mute:#6f7a86; --on-light:#08090b;
    --copper:#b4763c; --copper-hi:#d59456; --copper-dim:#6b482a; --copper-fill:#2a1e13; --copper-track:#241b14;
    --good:#52c98a; --good-fill:#0f2419; --warn:#f0a33c; --warn-fill:#2a1e0d; --bad:#ff4d4d; --bad-fill:#2b1113;
    --radius:3px;
    --display:"Barlow Semi Condensed","Bahnschrift","Arial Narrow",sans-serif;
    --sans:"Inter","Segoe UI",system-ui,sans-serif;
    --mono:"JetBrains Mono","Cascadia Mono",Consolas,monospace;
    color-scheme: dark;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--base);color:var(--text);font:14px/1.5 var(--sans);-webkit-font-smoothing:antialiased}
  a{color:var(--copper-hi)}
  main{max-width:1180px;margin:0 auto;padding:28px 24px 80px}
  .top{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:22px}
  .eyebrow{font:500 11px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--copper-hi);margin-bottom:8px}
  h1{font:700 30px/1 var(--display);margin:0}
  .controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  select,input[type=password],input[type=text]{background:var(--sunk);color:var(--text);border:1px solid var(--rule-strong);border-radius:var(--radius);padding:7px 10px;font:inherit;font-size:13px}
  button{font:inherit;font-size:13px;background:var(--panel);color:var(--dim);border:1px solid var(--rule-strong);border-radius:var(--radius);padding:7px 12px;cursor:pointer}
  button:hover{color:var(--text);border-color:var(--copper-dim)}
  button.primary{background:var(--copper);color:var(--on-light);border-color:var(--copper);font-weight:600}
  button.primary:hover{background:var(--copper-hi)}
  button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--copper-hi);outline-offset:2px}
  .banner{background:var(--warn-fill);border:1px solid #5c4118;border-left:3px solid var(--warn);border-radius:var(--radius);padding:9px 12px;color:var(--dim);font-size:13px;margin-bottom:18px}
  .banner strong{color:var(--text);font-weight:500}

  /* unlock */
  #unlock{max-width:440px;margin:60px auto;background:var(--panel);border:1px solid var(--rule-hi);border-radius:var(--radius);padding:24px}
  #unlock h2{font:600 20px/1.1 var(--display);margin:0 0 6px}
  #unlock p{color:var(--dim);margin:0 0 14px}
  #unlock form{display:flex;gap:8px}
  #unlock input{flex:1}
  .err{color:var(--bad);font-size:13px;min-height:1.2em;margin-top:8px}

  /* tiles */
  .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:22px}
  .tile{background:var(--panel);border:1px solid var(--rule);border-radius:var(--radius);padding:14px 16px}
  .tile .l{color:var(--dim);font-size:12.5px;margin-bottom:6px}
  .tile .v{font:600 30px/1 var(--sans);letter-spacing:-.01em;font-variant-numeric:tabular-nums}
  .tile .v small{font-size:14px;color:var(--mute);font-weight:400;margin-left:4px}
  .tile.hero .v{font-size:48px}
  .tile .s{color:var(--mute);font-size:12px;margin-top:6px}

  /* charts */
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:10px;margin-bottom:22px}
  .chart{background:var(--panel);border:1px solid var(--rule);border-radius:var(--radius);padding:14px 16px 12px}
  .chart h3{font:600 15px/1.2 var(--display);margin:0 0 2px}
  .chart .sub{color:var(--mute);font-size:12px;margin-bottom:12px}
  .bars{display:grid;grid-template-columns:minmax(90px,auto) 1fr auto;gap:6px 10px;align-items:center}
  .bars .k{font-size:12.5px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .bars .k code{font-family:var(--mono);font-size:12px;color:var(--text)}
  .bars .t{position:relative;height:14px;background:var(--copper-track);border-radius:var(--radius)}
  .bars .b{position:absolute;left:0;top:0;bottom:0;background:var(--copper);border-radius:0 4px 4px 0;min-width:2px}
  .bars .b.lo{background:var(--copper-dim)}
  .bars .v{font-family:var(--mono);font-size:12px;color:var(--dim);font-variant-numeric:tabular-nums;white-space:nowrap}
  .bars .t:hover .b{background:var(--copper-hi)}
  .empty{color:var(--mute);font-size:13px;padding:6px 0}

  /* responses */
  h2.sec{font:600 20px/1.1 var(--display);margin:8px 0 12px}
  .resp{background:var(--panel);border:1px solid var(--rule);border-radius:var(--radius);padding:14px 16px;margin-bottom:10px}
  .resp .head{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin-bottom:10px;font-size:12.5px;color:var(--dim)}
  .resp .head .when{font-family:var(--mono);color:var(--text)}
  .chip{display:inline-flex;align-items:center;gap:6px;padding:2px 8px;border-radius:999px;border:1px solid var(--rule-strong);font-size:12px;color:var(--dim);background:var(--sunk)}
  .chip::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--mute)}
  .chip.good{border-color:#22503a;background:var(--good-fill)}.chip.good::before{background:var(--good)}
  .chip.warn{border-color:#5c4118;background:var(--warn-fill)}.chip.warn::before{background:var(--warn)}
  .chip.bad{border-color:#5e1f22;background:var(--bad-fill)}.chip.bad::before{background:var(--bad)}
  .chip.tag{border-color:var(--copper-dim);background:var(--copper-fill);color:var(--copper-hi)}.chip.tag::before{background:var(--copper)}
  .fix{font-size:16px;line-height:1.45;margin:0 0 10px;padding-left:12px;border-left:3px solid var(--copper)}
  .fix .l{display:block;font:500 11px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--copper-hi);margin-bottom:6px}
  .more{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px 18px;margin-top:8px}
  .more div{font-size:13px;color:var(--dim)}
  .more div b{display:block;font-weight:500;color:var(--text);font-size:12.5px;margin-bottom:2px}
  .steps{display:flex;gap:4px;flex-wrap:wrap;margin-top:8px}
  .steps span{font-family:var(--mono);font-size:11.5px;color:var(--dim);background:var(--sunk);border:1px solid var(--rule);border-radius:var(--radius);padding:2px 7px}
  .steps span i{font-style:normal;color:var(--text)}
  details summary{cursor:pointer;color:var(--mute);font-size:12.5px;user-select:none}
  details summary:hover{color:var(--dim)}
  .tbl-wrap{overflow-x:auto;border:1px solid var(--rule);border-radius:var(--radius)}
  table{border-collapse:collapse;width:100%;font-size:12.5px}
  th,td{padding:7px 10px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top;white-space:nowrap}
  th{font:500 11px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--mute);background:var(--sunk)}
  td.wrap{white-space:normal;min-width:220px}
  .tip{position:fixed;pointer-events:none;background:var(--panel-hi);border:1px solid var(--rule-strong);border-radius:var(--radius);padding:6px 9px;font-size:12px;color:var(--text);display:none;z-index:9}
  [hidden]{display:none!important}
  @media (prefers-reduced-motion:no-preference){.bars .b{transition:width .25s ease}}
</style>
</head>
<body>
<main>
  <div class="top">
    <div>
      <div class="eyebrow">SRM-CAM · student feedback</div>
      <h1 id="title">Feedback</h1>
    </div>
    <div class="controls" id="controls" hidden>
      <select id="tag"><option value="">All links</option></select>
      <button id="view-toggle" type="button">Table view</button>
      <button id="csv" type="button">Download CSV</button>
      <button id="refresh" type="button">Refresh</button>
      <button id="forget" type="button" title="Forget the token in this browser">Lock</button>
    </div>
  </div>

  <div id="demo-banner" class="banner" hidden><strong>Example data.</strong> These rows are made up to show the layout. Remove <code>#demo</code> from the address to see real submissions.</div>

  <section id="unlock">
    <h2>Unlock</h2>
    <p>Paste the export token. It stays in this browser only.</p>
    <form id="unlock-form"><input type="password" id="token" placeholder="Export token" autocomplete="off"><button class="primary" type="submit">Open</button></form>
    <div class="err" id="unlock-err"></div>
  </section>

  <section id="dash" hidden>
    <div class="tiles" id="tiles"></div>
    <div class="grid" id="charts"></div>
    <h2 class="sec" id="list-title">Responses</h2>
    <div id="list"></div>
    <div id="table" hidden></div>
  </section>
</main>
<div class="tip" id="tip"></div>

<script>
(function () {
  var KEY = 'srm-cam-feedback-token';
  var DEMO = location.hash === '#demo';
  var $ = function (id) { return document.getElementById(id); };
  var rows = [], view = 'cards';

  var LABEL = {
    experience: { none: 'Nothing', watched: 'Seen it done', some: 'Once or twice', lots: 'Regularly' },
    install_ok: { yes: 'First try', retry: 'After fiddling', help: 'Needed help', no: 'Never worked' },
    result: { first: 'First board', second: 'Second board', 'third-plus': 'Three or more', rework: 'Fixed by hand', no: 'No board' },
    duration: { lt1h: 'Under 1 h', '1-2h': '1 to 2 h', '2-4h': '2 to 4 h', 'half-day': 'Half a day', 'multi-day': 'More than a day' },
    counterfactual: { no: 'No chance', slower: 'Much slower', yes: 'No difference' },
    onscreen: { helped: 'Helped', unclear: 'Still unclear', skimmed: 'Skimmed', unseen: 'Not noticed' },
    level_ok: { first: 'First try', retry: 'After re-run', skipped: 'Skipped', no: 'Never worked' },
    connect: { 'own-laptop': 'Own laptop', 'lab-pc': 'Lab PC', mixed: 'Both', none: 'VPanel only' },
    tier: { essential: 'Essential', full: 'Full', unaware: 'Did not notice', original: 'Original UI' },
    pages: { 'getting-started': 'Getting started', 'milling-a-board': 'Milling a board', 'holding-the-copper': 'Holding the copper', 'bed-leveling': 'Bed leveling', 'machine-control': 'Machine control', 'double-sided': 'Double-sided', panels: 'Panels', 'photo-and-rework': 'Photo and rework', hardware: 'Hardware', troubleshooting: 'Troubleshooting', reference: 'Reference', none: 'Skipped the guide' },
    defects: { shorts: 'Shorts', broken: 'Broken traces', depth: 'Depth wrong', offset: 'Drills off', outline: 'Cut-out / came loose', 'broke-bit': 'Broke a bit', none: 'None' }
  };
  var STEPS = ['load', 'level', 'drill', 'traces', 'cutout', 'export'];
  var TEXT_FIELDS = [['guide_gaps', 'Where the guide fell short'], ['app_stuck', 'Where they got stuck'], ['app_bugs', 'Surprises and bugs'], ['vpanel_notes', 'VPanel'], ['install_notes', 'Install'], ['keep', 'Keep as is'], ['other', 'Anything else']];

  function lbl(field, v) { return (LABEL[field] && LABEL[field][v]) || v; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function fmtDate(iso) { var d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  function count(list, field) { var m = {}; list.forEach(function (r) { var v = r[field]; if (v == null || v === '') return; [].concat(v).forEach(function (x) { m[x] = (m[x] || 0) + 1; }); }); return m; }
  function avg(nums) { var a = nums.filter(function (n) { return typeof n === 'number' && !isNaN(n); }); return a.length ? a.reduce(function (s, n) { return s + n; }, 0) / a.length : null; }
  function pct(n, d) { return d ? Math.round(100 * n / d) + '%' : '–'; }

  // ---- data ----
  function token() { try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; } }
  function load() {
    if (DEMO) { rows = demoRows(); render(); return Promise.resolve(); }
    var t = token();
    if (!t) { showUnlock(''); return Promise.resolve(); }
    return fetch('/export', { headers: { Authorization: 'Bearer ' + t } }).then(function (r) {
      if (r.status === 401) { try { localStorage.removeItem(KEY); } catch (e) {} showUnlock('That token was not accepted.'); return null; }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (data) { if (data) { rows = data; render(); } })
      .catch(function (e) { showUnlock('Could not load: ' + e.message); });
  }
  function showUnlock(msg) { $('unlock').hidden = false; $('dash').hidden = true; $('controls').hidden = true; $('unlock-err').textContent = msg; }
  $('unlock-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var t = $('token').value.trim(); if (!t) return;
    try { localStorage.setItem(KEY, t); } catch (err) {}
    $('token').value = ''; load();
  });
  $('forget').addEventListener('click', function () { try { localStorage.removeItem(KEY); } catch (e) {} rows = []; showUnlock(''); });
  $('refresh').addEventListener('click', load);
  $('tag').addEventListener('change', render);
  $('view-toggle').addEventListener('click', function () { view = view === 'cards' ? 'table' : 'cards'; render(); });
  $('csv').addEventListener('click', function () {
    fetch('/export.csv', { headers: { Authorization: 'Bearer ' + token() } }).then(function (r) { return r.blob(); }).then(function (b) {
      var a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = 'srm-cam-feedback.csv'; document.body.appendChild(a); a.click(); a.remove();
    });
  });

  // ---- render ----
  function render() {
    $('unlock').hidden = true; $('dash').hidden = false; $('controls').hidden = false;
    $('demo-banner').hidden = !DEMO;
    $('csv').hidden = DEMO;

    var tags = {}; rows.forEach(function (r) { if (r.tag) tags[r.tag] = 1; });
    var sel = $('tag'), cur = sel.value;
    sel.innerHTML = '<option value="">All links</option>' + Object.keys(tags).sort().map(function (t) { return '<option value="' + esc(t) + '"' + (t === cur ? ' selected' : '') + '>?for=' + esc(t) + '</option>'; }).join('');
    var list = cur ? rows.filter(function (r) { return r.tag === cur; }) : rows;
    var n = list.length;
    $('title').textContent = n === 1 ? '1 response' : n + ' responses';
    $('view-toggle').textContent = view === 'cards' ? 'Table view' : 'Card view';

    if (!n) {
      $('tiles').innerHTML = ''; $('charts').innerHTML = '';
      $('list').innerHTML = '<div class="empty">No responses yet. The form is at <a href="https://madsrudolph.github.io/srm-cam/feedback.html">madsrudolph.github.io/srm-cam/feedback.html</a>. Add <code>#demo</code> to this address to preview the layout.</div>';
      $('table').hidden = true; return;
    }

    // tiles
    var rec = avg(list.map(function (r) { return Number(r.recommend); }));
    var res = count(list, 'result'); var first = res.first || 0; var usable = n - (res.no || 0);
    var cf = count(list, 'counterfactual');
    var latest = list.reduce(function (m, r) { return r.received_at > m ? r.received_at : m; }, '');
    $('tiles').innerHTML =
      tile('Responses', n, null, 'latest ' + fmtDate(latest), true) +
      tile('Would recommend', rec == null ? '–' : rec.toFixed(1), '/ 5', 'average of ' + list.filter(function (r) { return r.recommend; }).length + ' answers') +
      tile('Usable board', pct(usable, n), null, pct(first, n) + ' on the first board') +
      tile('Needed the guide', pct((cf.no || 0) + (cf.slower || 0), n), null, pct(cf.no || 0, n) + ' say “no chance” without it');

    // charts
    var stepAvg = STEPS.map(function (s) { var vals = list.map(function (r) { return r['step_' + s]; }).filter(function (v) { return typeof v === 'number'; }); return { k: s, v: avg(vals), n: vals.length }; });
    var html = '';
    html += chart('Ease of each step', 'average 1 to 5, Essential flow order', stepAvg.map(function (d) { return { label: '<code>' + d.k + '</code>', value: d.v, max: 5, text: d.v == null ? '–' : d.v.toFixed(1) + ' · n=' + d.n, lo: d.v != null && d.v < 3 }; }));
    html += dist('How the board came out', 'students', list, 'result', ['first', 'second', 'third-plus', 'rework', 'no']);
    html += dist('Time from files to board', 'students', list, 'duration', ['lt1h', '1-2h', '2-4h', 'half-day', 'multi-day']);
    html += dist('Guide pages opened', 'students who opened each page', list, 'pages', ['getting-started', 'milling-a-board', 'holding-the-copper', 'bed-leveling', 'machine-control', 'double-sided', 'panels', 'photo-and-rework', 'hardware', 'troubleshooting', 'reference', 'none']);
    html += dist('Defects on failed boards', 'mentions', list, 'defects', ['shorts', 'broken', 'depth', 'offset', 'outline', 'broke-bit', 'none']);
    html += dist('Install started', 'students', list, 'install_ok', ['yes', 'retry', 'help', 'no']);
    html += dist('On-screen explanations', 'students', list, 'onscreen', ['helped', 'unclear', 'skimmed', 'unseen']);
    html += dist('Prior experience', 'students', list, 'experience', ['none', 'watched', 'some', 'lots']);
    $('charts').innerHTML = html;

    // list / table
    var sorted = list.slice().sort(function (a, b) { return b.id - a.id; });
    if (view === 'cards') {
      $('table').hidden = true; $('list').hidden = false;
      $('list').innerHTML = sorted.map(card).join('');
    } else {
      $('list').hidden = true; $('table').hidden = false;
      $('table').innerHTML = table(sorted);
    }
  }

  function tile(label, value, unit, sub, hero) {
    return '<div class="tile' + (hero ? ' hero' : '') + '"><div class="l">' + esc(label) + '</div><div class="v">' + esc(value) + (unit ? '<small>' + esc(unit) + '</small>' : '') + '</div><div class="s">' + esc(sub) + '</div></div>';
  }
  function chart(title, sub, items) {
    var body = items.length ? '<div class="bars">' + items.map(function (it) {
      var w = it.value == null ? 0 : Math.max(0, Math.min(100, 100 * it.value / it.max));
      return '<div class="k">' + it.label + '</div><div class="t" data-tip="' + esc(it.text) + '"><div class="b' + (it.lo ? ' lo' : '') + '" style="width:' + w + '%"></div></div><div class="v">' + esc(it.text) + '</div>';
    }).join('') + '</div>' : '<div class="empty">No answers yet.</div>';
    return '<div class="chart"><h3>' + esc(title) + '</h3><div class="sub">' + esc(sub) + '</div>' + body + '</div>';
  }
  function dist(title, sub, list, field, order) {
    var m = count(list, field); var total = 0; order.forEach(function (k) { total += m[k] || 0; });
    Object.keys(m).forEach(function (k) { if (order.indexOf(k) < 0) { order.push(k); total += m[k]; } });
    var max = Math.max.apply(null, order.map(function (k) { return m[k] || 0; }).concat([1]));
    var items = order.filter(function (k) { return m[k]; }).map(function (k) { return { label: esc(lbl(field, k)), value: m[k], max: max, text: m[k] + (total ? ' · ' + pct(m[k], list.length) : '') }; });
    return chart(title, sub, items);
  }
  function resultChip(r) {
    var v = r.result; if (!v) return '';
    var cls = v === 'first' ? 'good' : v === 'no' ? 'bad' : 'warn';
    return '<span class="chip ' + cls + '">' + esc(lbl('result', v)) + '</span>';
  }
  function card(r) {
    var who = r.name ? esc(r.name) + (r.email ? ' · ' + esc(r.email) : '') : 'anonymous';
    var steps = STEPS.filter(function (s) { return r['step_' + s] != null; }).map(function (s) { return '<span>' + s + ' <i>' + esc(r['step_' + s]) + '</i></span>'; }).join('');
    var more = TEXT_FIELDS.filter(function (f) { return r[f[0]]; }).map(function (f) { return '<div><b>' + esc(f[1]) + '</b>' + esc(r[f[0]]) + '</div>'; }).join('');
    var facts = [['experience', 'Experience'], ['os', 'OS'], ['install', 'Install'], ['tier', 'Tier'], ['connect', 'Connected'], ['level_ok', 'Leveling'], ['duration', 'Time'], ['counterfactual', 'Without the guide'], ['board_desc', 'Board'], ['board_pitch', 'Pitch']]
      .filter(function (f) { return r[f[0]]; }).map(function (f) { return '<div><b>' + f[1] + '</b>' + esc(lbl(f[0], r[f[0]])) + '</div>'; }).join('');
    return '<article class="resp"><div class="head"><span class="when">' + esc(fmtDate(r.received_at)) + '</span><span>#' + r.id + '</span><span>' + who + '</span>' +
      (r.tag ? '<span class="chip tag">?for=' + esc(r.tag) + '</span>' : '') + resultChip(r) +
      (r.recommend ? '<span class="chip">recommend ' + esc(r.recommend) + '/5</span>' : '') +
      (r.followup ? '<span class="chip good">follow-up OK</span>' : '') + '</div>' +
      '<p class="fix"><span class="l">Fix this first</span>' + esc(r.fix_one) + '</p>' +
      (steps ? '<div class="steps">' + steps + '</div>' : '') +
      (more ? '<div class="more">' + more + '</div>' : '') +
      (facts ? '<details style="margin-top:10px"><summary>All answers</summary><div class="more" style="margin-top:8px">' + facts + '</div></details>' : '') +
      '</article>';
  }
  function table(list) {
    var cols = ['id', 'received_at', 'tag', 'name', 'recommend', 'result', 'duration', 'step_load', 'step_level', 'step_drill', 'step_traces', 'step_cutout', 'step_export', 'fix_one', 'guide_gaps', 'app_stuck'];
    return '<div class="tbl-wrap"><table><thead><tr>' + cols.map(function (c) { return '<th>' + c + '</th>'; }).join('') + '</tr></thead><tbody>' +
      list.map(function (r) { return '<tr>' + cols.map(function (c) { var v = r[c]; var wrap = /fix_one|guide_gaps|app_stuck/.test(c); return '<td' + (wrap ? ' class="wrap"' : '') + '>' + esc(Array.isArray(v) ? v.join(', ') : (c === 'received_at' ? fmtDate(v) : (v == null ? '' : v))) + '</td>'; }).join('') + '</tr>'; }).join('') +
      '</tbody></table></div>';
  }

  // hover tooltip on bars
  var tip = $('tip');
  document.addEventListener('mousemove', function (e) {
    var t = e.target.closest && e.target.closest('[data-tip]');
    if (!t) { tip.style.display = 'none'; return; }
    tip.textContent = t.getAttribute('data-tip'); tip.style.display = 'block';
    tip.style.left = (e.clientX + 12) + 'px'; tip.style.top = (e.clientY - 28) + 'px';
  });

  function demoRows() {
    var mk = function (id, daysAgo, o) { var d = new Date(Date.now() - daysAgo * 864e5).toISOString(); return Object.assign({ id: id, received_at: d, _form_version: 1 }, o); };
    return [
      mk(3, 0, { tag: 'ahmad', experience: 'none', before: ['fiber-laser'], os: 'windows', install: 'installer', install_ok: 'yes', pages: ['getting-started', 'milling-a-board', 'bed-leveling'], guide_order: 4, guide_photos: 'mostly', tier: 'essential', step_load: 5, step_level: 3, step_drill: 5, step_traces: 4, step_cutout: 5, step_export: 5, onscreen: 'helped', app_stuck: 'Leveling. I was not sure how far the probe should travel and whether the map had been applied.', connect: 'own-laptop', connect_ok: 'fiddly', level_ok: 'retry', holding: 'enough', tools: 'clear', result: 'second', defects: ['shorts'], duration: '2-4h', counterfactual: 'no', recommend: 5, fix_one: 'Say on the leveling screen that the map is applied. I ran it twice because I could not tell.', keep: 'The plan that walks the steps in order.', followup: true, quote_ok: true, name: 'Example student' }),
      mk(2, 6, { experience: 'watched', os: 'linux', install: 'appimage', install_ok: 'retry', install_notes: 'Had to chmod the AppImage, the guide said so but I missed it.', pages: ['getting-started', 'milling-a-board', 'troubleshooting'], guide_order: 5, guide_photos: 'yes', tier: 'essential', step_load: 5, step_level: 4, step_drill: 4, step_traces: 5, step_cutout: 3, step_export: 5, onscreen: 'helped', app_stuck: 'Cut-out: which side of the outline the bit runs on.', connect: 'lab-pc', level_ok: 'first', holding: 'moved', tools: 'guessed', result: 'first', duration: '1-2h', counterfactual: 'slower', recommend: 4, fix_one: 'The tape advice. My board lifted at one corner during the cut-out.', followup: false, quote_ok: true }),
      mk(1, 14, { experience: 'none', os: 'windows', install: 'installer', install_ok: 'yes', pages: ['none'], guide_order: 2, guide_photos: 'na', tier: 'unaware', step_load: 4, step_level: 2, step_drill: 'skipped', step_traces: 3, step_cutout: 4, step_export: 4, onscreen: 'skimmed', app_stuck: 'Did not know I had to level at all, skipped it, traces did not cut through on one side.', connect: 'own-laptop', connect_ok: 'yes', level_ok: 'skipped', holding: 'unsure', tools: 'wrong', result: 'rework', defects: ['depth', 'broken'], duration: 'half-day', counterfactual: 'slower', recommend: 3, fix_one: 'Make it impossible to skip leveling without a warning.', followup: false, quote_ok: false })
    ];
  }

  load();
})();
</script>
</body>
</html>`;
