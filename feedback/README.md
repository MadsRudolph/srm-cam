# SRM-CAM feedback API

The student feedback form on the guide site (`website/feedback.html`, live at
https://madsrudolph.github.io/srm-cam/feedback.html) posts its answers here.
A Cloudflare Worker on the free tier writes each submission as one row in a
D1 database. No account is needed to fill in the form, and nothing is
emailed.

| Piece | Where |
|---|---|
| Worker | `srm-cam-feedback`, served at https://srm-cam-feedback.madsrudolph.dev |
| Dashboard | https://srm-cam-feedback.madsrudolph.dev/dashboard, source in `dashboard.js` |
| Database | D1 `srm-cam-feedback`, table `responses` (see `schema.sql`) |
| Form | `website/feedback.html`, the `API` constant at the top of its script |

The link `feedback.html?for=<name>` shows a tailored intro (if the page has a
`lede-<name>` paragraph) and stores `<name>` in the row's `tag` column, so a
link handed to one student can be told apart from the general page.

## Reading the answers

The dashboard at https://srm-cam-feedback.madsrudolph.dev/dashboard shows
totals, per-step ease, outcomes, and every response with its free text. It
asks for the export token once and keeps it in that browser; "Lock" forgets
it. Filter by `?for=` link, switch to a table view, or download the CSV from
there. `/dashboard#demo` shows the layout with made-up rows.

The export routes need the `EXPORT_TOKEN` secret as a bearer token. The
token is not in the repo; it lives in the Worker's secrets and wherever you
saved it when it was set.

```bash
TOKEN=...   # the export token
curl -s https://srm-cam-feedback.madsrudolph.dev/export     -H "Authorization: Bearer $TOKEN" | jq .
curl -s https://srm-cam-feedback.madsrudolph.dev/export.csv -H "Authorization: Bearer $TOKEN" > feedback.csv
```

Ad hoc queries go straight to D1:

```bash
cd feedback
npx wrangler d1 execute srm-cam-feedback --remote \
  --command "SELECT id, received_at, tag, recommend, fix_one FROM responses ORDER BY id DESC"
```

The full answer set of every row is JSON in the `answers` column. Keys are
the form's field names (`step_level`, `guide_gaps`, `fix_one`, ...), so a new
question in the form needs no schema change.

## The email per submission

Every stored submission also sends one plain-text mail to `NOTIFY_TO` (set in
`wrangler.toml`), from `feedback@madsrudolph.dev` through Email Routing on the
zone. The mail carries the "fix this first" answer, the key facts, and every
free-text field, so most feedback can be read without opening the dashboard.

The `send_email` binding is restricted to that one destination address, which
has to be a verified destination in Email Routing. To change who gets the
mail: add the new address as a destination (`npx wrangler email routing
addresses create <address>`, then click the verification mail), change
`destination_address` and `NOTIFY_TO`, deploy. The mail is sent after the
student has already got their "received" answer; if it fails, the row is
still stored and the failure is only in the Worker log.

## Deploying a change

```bash
cd feedback
npx wrangler login                 # once
npx wrangler deploy                # the Worker
npx wrangler d1 execute srm-cam-feedback --remote --file schema.sql   # only if schema.sql changed
npx wrangler secret put EXPORT_TOKEN                                  # only to rotate the token
```

`ALLOWED_ORIGINS` in `wrangler.toml` lists the origins that may POST. It is
the GitHub Pages origin plus `null`, which is what a browser sends for a page
opened from disk, so the form can be tested locally.

## Limits and abuse

- A submission must have `fix_one`; everything else is optional.
- Bodies over 32 KB are refused. A full form is about 3 KB.
- At most 20 submissions per IP per day. The IP is not stored, only a hash
  of IP and date for that count.
- If bots ever find the endpoint, add Cloudflare Turnstile to the form and
  verify it in `submit()`. It is free and invisible for real people.
