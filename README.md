# Discord Edgy Bot — Groq (Name Trigger Only)

- No slash commands. No @mention required.
- The bot replies when its **name** appears in a message (case-insensitive), using word-boundary match to avoid false positives.
- Includes `/health` and `/llmcheck` endpoints for diagnostics.
- Uses Groq's OpenAI-compatible API (free-friendly).

## Render setup
- Build: `pip install -r requirements.txt`
- Start: `python bot.py`
- Env:
  - `DISCORD_TOKEN`  (no quotes)
  - `GROQ_API_KEY`   (from https://console.groq.com/keys)
  - optional `GROQ_MODEL` (defaults to `llama-3.1-8b-instant`)

## Use
- Rename your bot in Discord to a unique name (e.g., "CribBot").
- The bot will reply whenever someone includes that name in their message, e.g.:
  - `cribbot roast my cable management`
  - `hey CribBot, rate this setup`

## Notes
- The bot strips its own name from the message before sending to the LLM.
- Safety filters avoid explicit hate/violence; keep things edgy-but-clean.
