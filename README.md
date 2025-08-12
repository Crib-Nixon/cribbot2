# Discord Edgy Bot — Complete (Render-ready)

- Hardened env parsing (`DISCORD_TOKEN`, `HF_TOKEN`, optional `HF_MODEL`)
- Logs model/URL on boot
- `/health` and `/hfcheck` endpoints
- HF API fallbacks for common public models
- `audioop-lts` for Python 3.13

## Deploy on Render
- Build: `pip install -r requirements.txt`
- Start: `python bot.py`
- Env:
  - `DISCORD_TOKEN` (no quotes)
  - `HF_TOKEN` (starts with `hf_`)
  - Optional `HF_MODEL` (default `HuggingFaceH4/zephyr-7b-beta`)

Open:
- `https://<your-app>.onrender.com/health` → `ok`
- `https://<your-app>.onrender.com/hfcheck` → JSON with HF status
