// Registers the /ask slash command for the SRM-CAM Discord app (run once,
// and again if the command's text changes). Needs the app's id and bot token
// in the environment; neither is stored in the repo:
//   DISCORD_APP_ID=... DISCORD_BOT_TOKEN=... node register_commands.mjs
const app = process.env.DISCORD_APP_ID, token = process.env.DISCORD_BOT_TOKEN;
if (!app || !token) { console.error("Set DISCORD_APP_ID and DISCORD_BOT_TOKEN."); process.exit(1); }
const commands = [{
  name: "ask",
  description: "Ask the SRM-CAM assistant (answers from the guide)",
  description_localizations: { da: "Spørg SRM-CAM-assistenten (svarer ud fra guiden)" },
  options: [{ type: 3, name: "question", description: "Your question", required: true,
              description_localizations: { da: "Dit spørgsmål" } }],
}];
const res = await fetch(`https://discord.com/api/v10/applications/${app}/commands`, {
  method: "PUT",
  headers: { "Authorization": `Bot ${token}`, "Content-Type": "application/json" },
  body: JSON.stringify(commands),
});
console.log(res.status, await res.text());
