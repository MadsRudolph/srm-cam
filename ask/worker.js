/**
 * SRM-CAM assistant: answers questions about SRM-CAM from the guide.
 *
 * One Worker, two front doors, same knowledge:
 *   POST /chat     the guide's floating "Ask SRM-CAM" pane (website/js/ask.js);
 *                  streams the answer back as server-sent events.
 *   POST /discord  the Discord app's interactions endpoint (/ask command).
 *   GET  /status   today's and this month's spend against the caps.
 *
 * The whole guide (knowledge.js, built by build_knowledge.py) is the cached
 * system prompt, so a question costs a cache read of it plus the answer.
 * Spend is counted from each response's usage and capped per day and month;
 * each visitor is rate-limited. Bindings: DB (D1), ANTHROPIC_API_KEY and
 * DISCORD_PUBLIC_KEY (secrets), vars in wrangler.toml.
 */
import Anthropic from "@anthropic-ai/sdk";
import KNOWLEDGE from "./knowledge.js";

const MODEL = "claude-opus-5-5";
// Claude Opus 5.5, USD per million tokens. The guide is cached for an hour,
// so a cache write costs 2x input; a cache read 0.05x.
const PRICE = { input: 4, output: 20, cacheWrite: 8, cacheRead: 0.2 };

const INSTRUCTIONS = `You are the SRM-CAM assistant. SRM-CAM is a desktop app made by Mads Rudolph for DTU students: it turns a KiCad board into a real PCB in the lab. The usual way: the Roland SRM-20 mill drills the holes and cuts the outline on tabs (the board stays in its sheet), then the xTool F1 Ultra fiber laser calibrates on the drilled holes and etches the copper. The mill can also make a whole board on its own.

Answer from the guide below, which is your only source about SRM-CAM. Rules:
- Be short and practical: the student is usually standing at the machine. Give the steps in order, with the exact button and menu names in 'quotes' as the guide writes them.
- Link the guide section you used, as a full URL from the guide (the heading's URL in brackets). One or two links, not more.
- Never invent buttons, numbers, settings or features. If the guide doesn't cover it, say so plainly and suggest asking in the SRM-CAM Discord #help (https://discord.gg/JUVbzanj6B), where Mads answers.
- Safety first: if something sounds wrong at a machine (smoke, a crash, the bit buried in the bed), tell them to press STOP or Esc first.
- Reply in the language the student writes in (often Danish or English).
- Use plain text with short lists. Markdown links and **bold** are fine; no tables, no headings.
- Only help with SRM-CAM, PCB making in the lab, KiCad export for it, and the machines. Politely decline anything else.`;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/discord" && request.method === "POST") return discord(request, env, ctx);
    const cors = corsHeaders(request, env);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (url.pathname === "/status") return json(await spendStatus(env), 200, cors);
    if (url.pathname === "/chat" && request.method === "POST") {
      if (!cors["Access-Control-Allow-Origin"]) return json({ error: "origin not allowed" }, 403, cors);
      return chat(request, env, ctx, cors);
    }
    return new Response("SRM-CAM assistant. See https://madsrudolph.github.io/srm-cam/community.html", { status: 404 });
  },
};

// ------------------------------------------------------------- the guide pane
async function chat(request, env, ctx, cors) {
  let body;
  try { body = await request.json(); } catch { return json({ error: "bad request" }, 400, cors); }
  const messages = cleanHistory(body.messages);
  if (!messages) return json({ error: "bad request" }, 400, cors);

  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const refusal = await gate(env, "web:" + ip);
  if (refusal) return json({ error: refusal }, 429, cors);

  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const enc = new TextEncoder();
  const send = (obj) => writer.write(enc.encode(`data: ${JSON.stringify(obj)}\n\n`));

  ctx.waitUntil((async () => {
    try {
      const stream = claude(env).beta.messages.stream(request_(messages, 2000));
      for await (const event of stream) {
        if (event.type === "content_block_delta" && event.delta.type === "text_delta") {
          await send({ t: event.delta.text });
        }
      }
      const final = await stream.finalMessage();
      await record(env, final.usage);
      if (final.stop_reason === "refusal") await send({ t: "\n\nI can't help with that one. Ask in the Discord #help instead." });
      if (final.stop_reason === "max_tokens") await send({ t: " …" });
      await send({ done: true });
    } catch (err) {
      console.error("chat failed", err && err.message);
      await send({ error: "The assistant is unavailable right now. Try again, or ask in the Discord." });
    } finally {
      await writer.close();
    }
  })());

  return new Response(readable, {
    headers: { ...cors, "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
  });
}

function cleanHistory(raw) {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const msgs = raw.slice(-12).map((m) => ({
    role: m && m.role === "assistant" ? "assistant" : "user",
    content: String((m && m.content) || "").slice(0, 3000).trim(),
  })).filter((m) => m.content);
  while (msgs.length && msgs[0].role !== "user") msgs.shift();
  if (!msgs.length || msgs[msgs.length - 1].role !== "user") return null;
  return msgs;
}

// ----------------------------------------------------------------- Claude call
function claude(env) {
  return new Anthropic({ apiKey: env.ANTHROPIC_API_KEY, maxRetries: 2 });
}

function request_(messages, maxTokens) {
  return {
    model: MODEL,
    max_tokens: maxTokens,
    output_config: { effort: "low" },
    betas: ["server-side-fallback-2026-07-01"],
    fallbacks: "default",
    system: [
      { type: "text", text: INSTRUCTIONS },
      { type: "text", text: KNOWLEDGE, cache_control: { type: "ephemeral", ttl: "1h" } },
    ],
    messages,
  };
}

// --------------------------------------------------------------------- Discord
async function discord(request, env, ctx) {
  const sig = request.headers.get("X-Signature-Ed25519");
  const ts = request.headers.get("X-Signature-Timestamp");
  const body = await request.text();
  if (!sig || !ts || !(await verifyDiscord(env.DISCORD_PUBLIC_KEY, sig, ts, body))) {
    return new Response("bad signature", { status: 401 });
  }
  const it = JSON.parse(body);
  if (it.type === 1) return json({ type: 1 });                       // PING
  if (it.type !== 2 || it.data?.name !== "ask") return json({ type: 4, data: { content: "Unknown command." } });

  const question = String(it.data.options?.find((o) => o.name === "question")?.value || "").slice(0, 3000);
  const who = it.member?.user?.id || it.user?.id || "unknown";
  const refusal = await gate(env, "discord:" + who);
  if (refusal) return json({ type: 4, data: { content: refusal, flags: 64 } });

  ctx.waitUntil((async () => {
    let answer;
    try {
      const final = await claude(env).beta.messages
        .stream(request_([{ role: "user", content: question }], 1500)).finalMessage();
      await record(env, final.usage);
      answer = final.content.filter((b) => b.type === "text").map((b) => b.text).join("").trim()
        || "I couldn't answer that one. Ask in #help.";
    } catch (err) {
      console.error("discord failed", err && err.message);
      answer = "The assistant is unavailable right now. Ask in #help.";
    }
    const content = `> ${question.slice(0, 300)}\n\n${answer}`;
    await fetch(`https://discord.com/api/v10/webhooks/${it.application_id}/${it.token}/messages/@original`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content: content.length > 1990 ? content.slice(0, 1985) + " …" : content,
        allowed_mentions: { parse: [] },
      }),
    });
  })());
  return json({ type: 5 });                                          // "thinking…"
}

async function verifyDiscord(publicKeyHex, sigHex, timestamp, body) {
  if (!publicKeyHex) return false;
  try {
    const key = await crypto.subtle.importKey("raw", hex(publicKeyHex), { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify("Ed25519", key, hex(sigHex), new TextEncoder().encode(timestamp + body));
  } catch { return false; }
}

function hex(s) {
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(s.substr(i * 2, 2), 16);
  return out;
}

// ------------------------------------------------------ budget and rate limits
const today = () => new Date().toISOString().slice(0, 10);
const month = () => new Date().toISOString().slice(0, 7);

/** null if the request may go ahead, else the message to show. */
async function gate(env, who) {
  const s = await spendStatus(env);
  if (s.today_usd >= s.daily_cap_usd || s.month_usd >= s.monthly_cap_usd) {
    return "The assistant has used its budget for now. Ask in the SRM-CAM Discord #help: https://discord.gg/JUVbzanj6B";
  }
  const hour = new Date().toISOString().slice(0, 13);
  const key = `${await digest(who)}:${hour}`;
  const row = await env.DB.prepare(
    "INSERT INTO hits (key, n) VALUES (?, 1) ON CONFLICT(key) DO UPDATE SET n = n + 1 RETURNING n"
  ).bind(key).first();
  if (row && row.n > Number(env.PER_HOUR || 20)) {
    return "That's a lot of questions in an hour. Take a break, or ask in the Discord #help.";
  }
  return null;
}

async function record(env, u) {
  if (!u) return;
  const usd = ((u.input_tokens || 0) * PRICE.input + (u.output_tokens || 0) * PRICE.output
    + (u.cache_creation_input_tokens || 0) * PRICE.cacheWrite
    + (u.cache_read_input_tokens || 0) * PRICE.cacheRead) / 1e6;
  await env.DB.prepare(
    "INSERT INTO spend (day, usd, questions) VALUES (?, ?, 1) "
    + "ON CONFLICT(day) DO UPDATE SET usd = usd + excluded.usd, questions = questions + 1"
  ).bind(today(), usd).run();
}

async function spendStatus(env) {
  const d = await env.DB.prepare("SELECT usd, questions FROM spend WHERE day = ?").bind(today()).first();
  const m = await env.DB.prepare("SELECT SUM(usd) AS usd, SUM(questions) AS q FROM spend WHERE day LIKE ?")
    .bind(month() + "%").first();
  return {
    today_usd: Number((d && d.usd) || 0), today_questions: Number((d && d.questions) || 0),
    month_usd: Number((m && m.usd) || 0), month_questions: Number((m && m.q) || 0),
    daily_cap_usd: Number(env.DAILY_CAP_USD || 3), monthly_cap_usd: Number(env.MONTHLY_CAP_USD || 90),
  };
}

async function digest(s) {
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("srm-cam-ask:" + s));
  return [...new Uint8Array(h)].slice(0, 12).map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ----------------------------------------------------------------------- utils
function corsHeaders(request, env) {
  const allowed = (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
  const origin = request.headers.get("Origin");
  const h = { "Access-Control-Allow-Methods": "POST, GET, OPTIONS", "Access-Control-Allow-Headers": "Content-Type", "Vary": "Origin" };
  if (origin && allowed.includes(origin)) h["Access-Control-Allow-Origin"] = origin;
  return h;
}

function json(obj, status = 200, headers = {}) {
  return new Response(JSON.stringify(obj), { status, headers: { ...headers, "Content-Type": "application/json" } });
}
