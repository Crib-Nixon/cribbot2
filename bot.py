
import os, re, time, asyncio, sys
from typing import Dict, List
import aiohttp
import discord
from discord.ext import commands
from aiohttp import web

# --- add these with your aiohttp web server routes ---
from aiohttp import web
import json, aiohttp as _aio

async def hfcheck(_request):
    # simple GET to the model endpoint so we can see status without Discord
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    try:
        timeout = _aio.ClientTimeout(total=20)
        async with _aio.ClientSession(timeout=timeout) as s:
            async with s.get(HF_URL, headers=headers) as r:
                text = await r.text()
                return web.Response(
                    text=json.dumps({
                        "model": HF_MODEL,
                        "url": HF_URL,
                        "status": r.status,
                        "ok": r.status == 200,
                        "body_snippet": text[:300],
                    }, ensure_ascii=False, indent=2),
                    content_type="application/json"
                )
    except Exception as e:
        return web.Response(
            text=json.dumps({"error": repr(e)}),
            content_type="application/json",
            status=500
        )

async def start_web_app():
    app = web.Application()
    app.router.add_get("/health", lambda _: web.Response(text="ok"))
    app.router.add_get("/hfcheck", hfcheck)   # ← new route
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()

print("Python:", sys.version)
try:
    import audioop  # provided by audioop-lts on Python 3.13
    print("audioop module loaded OK")
except Exception as e:
    print("audioop import error:", e)

# --- put these near the top, right after env parsing ---
def _clean(s: str) -> str:
    return (s or "").strip().strip('"').strip("'")

DISCORD_TOKEN = _clean(os.getenv("DISCORD_TOKEN"))
HF_TOKEN = _clean(os.getenv("HF_TOKEN"))
raw_model_env = _clean(os.getenv("HF_MODEL"))
HF_MODEL = raw_model_env or "HuggingFaceH4/zephyr-7b-beta"

if not DISCORD_TOKEN:
    raise SystemExit("DISCORD_TOKEN missing")
if not HF_TOKEN or not HF_TOKEN.startswith("hf_"):
    raise SystemExit("HF_TOKEN missing/invalid (must start with hf_)")

HF_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
print(f"[DEBUG] HF_TOKEN set? {bool(HF_TOKEN)} length={len(HF_TOKEN)} startswith_hf={HF_TOKEN.startswith('hf_')}")
print(f"[DEBUG] HF_MODEL used: {HF_MODEL!r}")
print(f"[DEBUG] HF_URL: {HF_URL}")

# ---- Discord setup ----
INTENTS = discord.Intents.default()
INTENTS.message_content = True
bot = commands.Bot(command_prefix="!", intents=INTENTS)

SYSTEM_PROMPT = (
    "You are an unfiltered, darkly humorous assistant with a roast-comedian vibe. "
    "You use sharp wit and mild profanity for comedic effect. "
    "Replies should be punchy, surprising, and under ~180 words unless asked for more. "
    "End with one short zinger when it fits."
    "Talk about random details about some middle eastern conflict and throw it in. "
    "The whackier the better."
)

def build_prompt(user_text: str) -> str:
    preface = (
        "Give a witty, edgy answer. If the question is mundane, pretend it’s life-or-death for comedy. "
        "Add one short zinger at the end if natural.\n"
    )
    return f"{SYSTEM_PROMPT}\n\n{preface}\nUser: {user_text}\nAssistant:"






# ---- HF Inference (with fallback list) ----
FALLBACK_MODELS: List[str] = [
    "HuggingFaceH4/zephyr-7b-beta",
    "mistralai/Mistral-7B-Instruct-v0.2",
    "google/gemma-2b-it",
    "meta-llama/Llama-3.2-1B-Instruct",
]

async def hf_generate_with_model(model: str, prompt: str, max_new_tokens: int = 220, temperature: float = 0.9, top_p: float = 0.9) -> str:
    url = hf_url_for(model)
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "return_full_text": False
        }
    }
    timeout = aiohttp.ClientTimeout(total=75)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"HF API error {resp.status} for {model}: {text[:400]}")
            try:
                data = await resp.json()
            except Exception:
                raise RuntimeError(f"HF JSON parse error for {model}: {text[:400]}")
            if isinstance(data, list) and data and "generated_text" in data[0]:
                return data[0]["generated_text"].strip()
            if isinstance(data, dict) and "generated_text" in data:
                return data["generated_text"].strip()
            if isinstance(data, dict) and "error" in data:
                return f"[model/queue] {data['error']}"
            return str(data)[:1000]

async def hf_generate(prompt: str) -> str:
    # Try requested model first, then fallbacks
    models = [HF_MODEL] + [m for m in FALLBACK_MODELS if m != HF_MODEL]
    last_err = None
    for m in models:
        try:
            print(f"[DEBUG] Trying HF model: {m}")
            return await hf_generate_with_model(m, prompt)
        except RuntimeError as e:
            err = str(e)
            print(f"[WARN] HF call failed for {m}: {err}")
            last_err = err
            # Only fall through on 404/5xx; on 401/403 it's a token/permission issue
            if " 404 " not in err and " 5" not in err[:10]:
                break
        except Exception as e:
            last_err = repr(e)
            print(f"[WARN] Unexpected HF error for {m}: {e!r}")
    raise RuntimeError(last_err or "Unknown HF error")

# ---- Rate limiting (per guild) ----
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
    prompt = build_prompt(user_text)
    raw = await hf_generate(prompt)
    return sanitize(raw)

@bot.tree.command(name="ask", description="Ask the bot something (edgy-but-clean)")
async def ask_cmd(interaction: discord.Interaction, prompt: str):
    if on_cooldown(interaction.guild_id):
        await interaction.response.send_message("Whoa—pace yourself ⏳", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    try:
        reply = await generate_reply(interaction.guild_id, prompt)
        await interaction.followup.send(reply or "…brain buffering…")
    except Exception as e:
        await interaction.followup.send(f"LLM error: {e}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    if bot.user in message.mentions:
        if on_cooldown(message.guild.id):
            return
        content = re.sub(fr"<@!?{bot.user.id}>", "", message.content).strip()
        if not content:
            return
        try:
            reply = await generate_reply(message.guild.id, content)
            await message.reply(reply or "…processing…")
        except Exception as e:
            await message.reply(f"LLM error: {e}")
    await bot.process_commands(message)

async def health(_request):
    return web.Response(text="ok")

async def start_web_app():
    app = web.Application()
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()

@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
        asyncio.create_task(start_web_app())
        print(f"Logged in as {bot.user} (ID: {bot.user.id}) | Health on :{PORT}/health")
    except Exception as e:
        print("Startup error:", e)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
