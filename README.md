# Discord Edgy-But-Clean Bot (Render)

A roast-comic style Discord bot (PG-16, no hate/violence) using the free Hugging Face Inference API. Includes `/health` for uptime pings.

## 1) Discord setup
1. https://discord.com/developers/applications → New Application → Bot → Add Bot.
2. Under **Bot**:
   - Enable **MESSAGE CONTENT INTENT**.
   - Reset & copy your **token** (keep it secret).
3. Under **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`
   - Invite the bot to your server with the generated URL.

## 2) Hugging Face token (free)
- Create an account → Settings → Access Tokens → New token → copy it.

## 3) Deploy on Render
1. Push this repo to GitHub.
2. In Render → **New +** → **Web Service** → connect your repo.
3. **Build Command:** `pip install -r requirements.txt`
4. **Start Command:** `python bot.py`
5. **Environment → Add Variables:**
   - `DISCORD_TOKEN` = your Discord bot token
   - `HF_TOKEN` = your HF access token
   - (optional) `HF_MODEL` = e.g., `mistralai/Mistral-7B-Instruct-v0.2`
6. Deploy. Wait for “Live”.

## 4) Keep-alive
- After deploy, note your public URL, e.g. `https://your-app.onrender.com/health`
- Set an UptimeRobot HTTP monitor to ping `/health` every 5 minutes.

## 5) Use it
- In your server:
  - Mention the bot: `@YourBot roast my cable management`
  - Or slash: `/ask rate my setup`

## Notes
- Free HF API can cold start or queue; try again if response says "model cold start".
- Never commit tokens; keep them as **Render env vars**.
