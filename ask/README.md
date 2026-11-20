# SRM-CAM assistant

Answers students' questions about SRM-CAM from the guide, in two places:

| Where | How |
|---|---|
| The guide | The floating **Ask SRM-CAM** button on every page (`website/js/ask.js`) |
| Discord | The `/ask` command in the SRM-CAM server |

One Cloudflare Worker (`srm-cam-ask`, https://srm-cam-ask.madsrudolph.dev)
serves both. The whole guide plus `docs/usage.md` (about 74k tokens, built into
`knowledge.js` by `build_knowledge.py`) is its cached system prompt, so a
question costs a cache read of the guide plus the answer: roughly $0.02–0.05
on Claude Opus 5.5.

## Budget

Every answer's token usage is priced and added to D1 table `spend`. When the
day's spend reaches `DAILY_CAP_USD` (3) or the month's `MONTHLY_CAP_USD` (90),
the assistant answers "used its budget" and points to Discord #help until the
next day. Each visitor (hashed IP) or Discord user gets `PER_HOUR` (20)
questions an hour. All three are `[vars]` in `wrangler.toml`.

Spend so far: https://srm-cam-ask.madsrudolph.dev/status

## Deploy

```bash
cd ask
npm install
npm run deploy                                # rebuilds knowledge.js from the guide, then deploys
npx wrangler secret put ANTHROPIC_API_KEY     # once; paste the key from console.anthropic.com
```

**Redeploy after every guide change** (`npm run deploy`) so the assistant
knows what the guide now says. First-time setup also needs the database:
`npx wrangler d1 execute srm-cam-ask --remote --file schema.sql`.

## Discord

1. https://discord.com/developers/applications → **New Application**: "SRM-CAM".
   Give it the logo.
2. **General Information**: copy the **Public Key**, then
   `npx wrangler secret put DISCORD_PUBLIC_KEY` and paste it.
   Set **Interactions Endpoint URL** to
   `https://srm-cam-ask.madsrudolph.dev/discord` and save (Discord checks it).
3. **Bot** → Reset Token, copy it. Register the command (the token is only
   used here, never stored):
   `DISCORD_APP_ID=<Application ID> DISCORD_BOT_TOKEN=<token> node register_commands.mjs`
4. **Installation** → Guild Install with scope `applications.commands`;
   open the install link and add it to the SRM-CAM server.

Then `/ask question:...` in any channel.

## Files

| File | What |
|---|---|
| `worker.js` | The Worker: `/chat` (guide pane, streamed), `/discord` (interactions), `/status` |
| `build_knowledge.py` | Guide pages + `docs/usage.md` → `knowledge.js` |
| `knowledge.js` | Generated; do not edit |
| `schema.sql` | D1 tables `spend` and `hits` |
| `register_commands.mjs` | Registers `/ask` with Discord |
