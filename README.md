This build includes robust HF model fallback and audioop-lts for Python 3.13.
If HF API returns 404, the bot will auto-try alternate public models.
Set env vars in Render: DISCORD_TOKEN, HF_TOKEN (and optional HF_MODEL).
