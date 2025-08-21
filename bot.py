\
import os, re, time, asyncio, sys, json
from typing import Dict, List
import aiohttp
import discord
from discord.ext import commands
from aiohttp import web

print("Python:", sys.version)
try:
    import audioop  # backport via audioop-lts for Python 3.13
    print("audioop module loaded OK")
except Exception as e:
    print("audioop import error:", e)

def _clean(s: str) -> str:
    return (s or "").strip().strip('"').strip("'")

# ---- Env ----
DISCORD_TOKEN = _clean(os.getenv("DISCORD_TOKEN"))
GROQ_API_KEY = _clean(os.getenv("GROQ_API_KEY"))
GROQ_MODEL = _clean(os.getenv("GROQ_MODEL")) or "llama-3.1-8b-instant"
PORT = int(os.getenv("PORT", "8080"))

if not DISCORD_TOKEN:
    raise SystemExit("DISCORD_TOKEN missing.")
if not GROQ_API_KEY:
    raise SystemExit("GROQ_API_KEY missing. Create one at https://console.groq.com/keys and paste it (no quotes).")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
print(f"[DEBUG] GROQ_MODEL: {GROQ_MODEL!r}")
print(f"[DEBUG] GROQ_URL: {GROQ_URL}")

# ---- Discord setup ----
INTENTS = discord.Intents.default()
INTENTS.message_content = True
bot = commands.Bot(command_prefix="!", intents=INTENTS)  # command_prefix unused; no slash or prefix commands

SYSTEM_PROMPT = (
    "You are an unfiltered, darkly humorous assistant with a roast-comedian vibe. "
    "Use sharp wit and occasional profanity, but when you do, make it sting. "
    "Be punchy, surprising. "
    "End with one short zinger when it fits."
    "Be vulgar, but also do not be afraid to just straight up ignore the question."
)

def build_messages(user_text: str):
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]








# ---- Groq chat completion ----
async def groq_chat(messages, max_tokens: int = 220, temperature: float = 0.9, top_p: float = 0.9) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": False,
    }
    timeout = aiohttp.ClientTimeout(total=75)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(GROQ_URL, headers=headers, json=payload) as resp:
            txt = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"Groq API error {resp.status}: {txt[:400]}")
            data = await resp.json()
            try:
                return data["choices"][0]["message"]["content"].strip()
            except Exception:
                return str(data)[:1000]

LAST_TS: Dict[int, float] = {}
COOLDOWN = 3.5
def on_cooldown(guild_id: int) -> bool:
    now = time.time()
    last = LAST_TS.get(guild_id, 0.0)
    if now - last < COOLDOWN:
        return True
    LAST_TS[guild_id] = now
    return False

async def generate_reply(guild_id: int, user_text: str) -> str:
    msgs = build_messages(
        "Give a witty, edgy answer. Be vulgar, but also do not be afraid to just straight up ignore the question."
        "Add one short zinger if natural.\n\nUser: " + user_text
    )
    raw = await groq_chat(msgs)
    return raw

def name_in_message(bot_names: List[str], content: str) -> bool:
    if not content:
        return False
    c = content.lower()
    for name in bot_names:
        if not name:
            continue
        n = name.lower()
        # Try word-boundary match to avoid false positives inside other words
        pattern = r"(?:^|\\b|[^\\w])" + re.escape(n) + r"(?:$|\\b|[^\\w])"
        if re.search(pattern, c):
            return True
    return False

@bot.event
async def on_ready():
    try:
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    except Exception:
        print("Logged in. (Could not print user info.)")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # Build candidate names: username, global display, and (if available) guild nickname
    candidate_names: List[str] = []
    try:
        candidate_names.append(bot.user.name)
    except Exception:
        pass
    try:
        # discord.py may not always populate display_name; ignore if missing
        candidate_names.append(getattr(bot.user, "display_name", None))
    except Exception:
        pass
    try:
        me = message.guild.get_member(bot.user.id)
        if me and me.display_name and me.display_name not in candidate_names:
            candidate_names.append(me.display_name)
    except Exception:
        pass
    candidate_names = [n for n in candidate_names if n]

    if not name_in_message(candidate_names, message.content):
        return

    if on_cooldown(message.guild.id):
        return

    content = message.content.strip()


# ---- Health + llmcheck endpoints ----
async def health(_request):
    return web.Response(text="ok")

async def llmcheck(_request):
    headers = { "Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json" }
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": "Say 'pong'"}],
        "max_tokens": 5
    }
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(GROQ_URL, headers=headers, json=payload) as r:
                text = await r.text()
                return web.json_response({
                    "model": GROQ_MODEL,
                    "status": r.status,
                    "ok": r.status == 200,
                    "body_snippet": text[:300]
                }, status=r.status if r.status != 200 else 200)
    except Exception as e:
        return web.json_response({"error": repr(e)}, status=500)

async def start_web_app():
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/llmcheck", llmcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()

@bot.event
async def on_connect():
    # Start the web server ASAP so /health works even if Discord login is slow
    asyncio.create_task(start_web_app())

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
