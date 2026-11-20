#!/usr/bin/env bash
# Register the /ask command with the SRM-CAM Discord app. Asks for the
# Application ID and the bot token (hidden); neither is saved anywhere.
#   ~/Projects/srm-cam/ask/register.sh
set -euo pipefail
cd "$(dirname "$0")"
read -rp  "Application ID (General Information): " DISCORD_APP_ID
read -rsp "Bot token (Bot > Reset Token, input hidden): " DISCORD_BOT_TOKEN; echo
DISCORD_APP_ID="$(printf '%s' "$DISCORD_APP_ID" | tr -d '[:space:]')"
DISCORD_BOT_TOKEN="$(printf '%s' "$DISCORD_BOT_TOKEN" | tr -d '[:space:]')"
[ -n "$DISCORD_APP_ID" ] && [ -n "$DISCORD_BOT_TOKEN" ] || { echo "Both are needed."; exit 1; }
DISCORD_APP_ID="$DISCORD_APP_ID" DISCORD_BOT_TOKEN="$DISCORD_BOT_TOKEN" node register_commands.mjs
