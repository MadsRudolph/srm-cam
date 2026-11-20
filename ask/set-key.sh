#!/usr/bin/env bash
# Set one of the SRM-CAM assistant's Worker secrets. Prompts for the value
# without echoing it; nothing is written to disk. Run from anywhere:
#   ~/Projects/srm-cam/ask/set-key.sh                      # Anthropic API key
#   ~/Projects/srm-cam/ask/set-key.sh DISCORD_PUBLIC_KEY   # Discord app's Public Key
set -euo pipefail
cd "$(dirname "$0")"
NAME="${1:-ANTHROPIC_API_KEY}"
case "$NAME" in ANTHROPIC_API_KEY|DISCORD_PUBLIC_KEY) ;; *) echo "Unknown secret: $NAME"; exit 1;; esac
read -rsp "$NAME (input hidden): " VALUE; echo
VALUE="$(printf '%s' "$VALUE" | tr -d '[:space:]')"
[ -n "$VALUE" ] || { echo "Nothing entered, nothing changed."; exit 1; }
printf '%s' "$VALUE" | npx wrangler secret put "$NAME"
unset VALUE
