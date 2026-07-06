# SRM-CAM photo relay — one-time deploy (~5 min)

Relays board photos phone → app when the wifi blocks device-to-device
traffic (eduroam). Runs on the Cloudflare Workers **free tier** — no
credit card, no server. The PC is never exposed; photos are stored at an
unguessable token, handed over once, and expire after 10 minutes.

## Deploy

1. Create a free account at https://dash.cloudflare.com/sign-up (skip any
   domain setup — a `workers.dev` subdomain is included).
2. In a terminal (Node.js is already installed):

   ```
   cd relay
   npx wrangler login              # opens the browser, approve
   npx wrangler kv namespace create PHOTOS
   ```

   Copy the printed `id = "..."` into `wrangler.toml` (replace
   `PASTE_KV_NAMESPACE_ID_HERE`), then:

   ```
   npx wrangler deploy
   ```

3. The deploy prints your relay URL, e.g.
   `https://srm-cam-relay.<your-subdomain>.workers.dev`.
   Paste it into the **Relay** field of the app's *Photo from phone*
   dialog once — it's remembered.

## Verify

Open `<relay-url>/u/test-token-123456` in any browser: the take-photo
page should load. The app's dialog does the rest.

## Free-tier headroom

100k requests/day, 1k KV writes/day — a photo hand-off costs one write
and a handful of reads. You will never hit the limits with one mill.
