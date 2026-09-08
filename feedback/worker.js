/**
 * SRM-CAM feedback API.
 *
 *   POST /            body: JSON from website/feedback.html  -> {ok, id}
 *   GET  /export      header: Authorization: Bearer <EXPORT_TOKEN>
 *                     -> every response as JSON, newest first
 *   GET  /export.csv  same, as CSV with one column per answer key
 *   GET  /health      -> "ok"
 *
 * Bindings: DB (D1), ALLOWED_ORIGINS (var), EXPORT_TOKEN (secret).
 */

const MAX_BODY = 32 * 1024;         // a full form is ~3 KB
const MAX_PER_DAY_PER_IP = 20;      // students resubmit; bots do not stop at 20
const FORM_VERSION = 1;
const FORM_URL = "https://madsrudolph.github.io/srm-cam/feedback.html";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin");
    const cors = corsHeaders(origin, env);

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (url.pathname === "/health") return text("ok", 200, cors);
    if (request.method === "GET" && url.pathname === "/") return landing();

    if (request.method === "POST" && url.pathname === "/") return submit(request, env, cors);
    if (request.method === "GET" && url.pathname === "/export") return exportJson(request, env);
    if (request.method === "GET" && url.pathname === "/export.csv") return exportCsv(request, env);

    return text("not found", 404, cors);
  },
};

// ---- submit ---------------------------------------------------------------

async function submit(request, env, cors) {
  if (!cors["Access-Control-Allow-Origin"]) return text("origin not allowed", 403);

  const len = Number(request.headers.get("Content-Length") || 0);
  if (len > MAX_BODY) return text("too large", 413, cors);

  let raw;
  try { raw = await request.text(); } catch { return text("bad body", 400, cors); }
  if (raw.length > MAX_BODY) return text("too large", 413, cors);

  let answers;
  try { answers = JSON.parse(raw); } catch { return text("bad json", 400, cors); }
  if (!answers || typeof answers !== "object" || Array.isArray(answers)) return text("bad json", 400, cors);

  const fixOne = str(answers.fix_one);
  if (!fixOne) return text("fix_one is required", 422, cors);

  // Rate limit per IP per day, without keeping the IP itself.
  const ip = request.headers.get("CF-Connecting-IP") || "0.0.0.0";
  const day = new Date().toISOString().slice(0, 10);
  const ipHash = await sha256(`${ip}|${day}`);
  const { count } = await env.DB.prepare("SELECT COUNT(*) AS count FROM responses WHERE ip_hash = ?")
    .bind(ipHash).first();
  if (count >= MAX_PER_DAY_PER_IP) return text("too many submissions today", 429, cors);

  const recommend = Number(answers.recommend);
  const row = await env.DB.prepare(
    `INSERT INTO responses (received_at, tag, form_version, fix_one, recommend, result, answers, ip_hash, user_agent)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id`)
    .bind(
      new Date().toISOString(),
      str(answers._for) || null,
      Number(answers._form_version) || FORM_VERSION,
      fixOne.slice(0, 4000),
      recommend >= 1 && recommend <= 5 ? recommend : null,
      str(answers.result) || null,
      JSON.stringify(answers),
      ipHash,
      (request.headers.get("User-Agent") || "").slice(0, 200),
    ).first();

  return json({ ok: true, id: row.id }, 200, cors);
}

// ---- export ---------------------------------------------------------------

function authorized(request, env) {
  const h = request.headers.get("Authorization") || "";
  const token = h.startsWith("Bearer ") ? h.slice(7) : "";
  return env.EXPORT_TOKEN && token.length > 0 && timingSafeEqual(token, env.EXPORT_TOKEN);
}

async function allRows(env) {
  const { results } = await env.DB.prepare(
    "SELECT id, received_at, tag, form_version, answers FROM responses ORDER BY id DESC").all();
  return results.map(r => ({
    id: r.id, received_at: r.received_at, tag: r.tag, form_version: r.form_version,
    ...safeParse(r.answers),
  }));
}

async function exportJson(request, env) {
  if (!authorized(request, env)) return text("unauthorized", 401);
  return json(await allRows(env), 200);
}

async function exportCsv(request, env) {
  if (!authorized(request, env)) return text("unauthorized", 401);
  const rows = await allRows(env);
  const keys = [];
  for (const r of rows) for (const k of Object.keys(r)) if (!keys.includes(k)) keys.push(k);
  const esc = v => {
    if (v == null) return "";
    const s = Array.isArray(v) ? v.join("; ") : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [keys.join(",")];
  for (const r of rows) lines.push(keys.map(k => esc(r[k])).join(","));
  return new Response(lines.join("\n"), {
    status: 200,
    headers: { "Content-Type": "text/csv; charset=utf-8", "Content-Disposition": "attachment; filename=srm-cam-feedback.csv" },
  });
}

// ---- landing --------------------------------------------------------------

// What a person sees when they open the API address in a browser.
function landing() {
  const html = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>SRM-CAM feedback API</title>
<style>body{margin:0;background:#101318;color:#eef2f6;font:15px/1.55 Inter,"Segoe UI",system-ui,sans-serif}
main{max-width:560px;margin:0 auto;padding:56px 24px}h1{font:600 26px/1.1 "Barlow Semi Condensed","Bahnschrift","Arial Narrow",sans-serif;margin:0 0 12px}
p{color:#aab3bd;margin:0 0 14px}a{color:#d59456}code{font-family:"JetBrains Mono","Cascadia Mono",Consolas,monospace;font-size:13px;color:#eef2f6}</style></head>
<body><main><h1>SRM-CAM feedback API</h1>
<p>This address only receives the answers from the feedback form. There is nothing to see here.</p>
<p>To give feedback on the guide or the app, use the form: <a href="${FORM_URL}">${FORM_URL}</a></p>
<p><code>POST /</code> stores a submission. <code>GET /health</code> says <code>ok</code>.</p>
</main></body></html>`;
  return new Response(html, { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

// ---- helpers --------------------------------------------------------------

function corsHeaders(origin, env) {
  const allowed = (env.ALLOWED_ORIGINS || "").split(",").map(s => s.trim()).filter(Boolean);
  const h = {
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
  if (origin && allowed.includes(origin)) h["Access-Control-Allow-Origin"] = origin;
  return h;
}

function str(v) { return typeof v === "string" ? v.trim() : ""; }
function safeParse(s) { try { return JSON.parse(s); } catch { return {}; } }
function text(body, status, headers = {}) {
  return new Response(body, { status, headers: { "Content-Type": "text/plain; charset=utf-8", ...headers } });
}
function json(body, status, headers = {}) {
  return new Response(JSON.stringify(body, null, 2), { status, headers: { "Content-Type": "application/json", ...headers } });
}
async function sha256(s) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}
function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}
