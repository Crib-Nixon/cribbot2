
import os, re, time, asyncio, sys
from typing import Dict, List
import aiohttp
import discord
from discord.ext import commands
from aiohttp import web

print("Python:", sys.version)
# audioop backport is provided by audioop-lts on Python 3.13+
try:
    import audioop
    print("audioop module loaded OK")
except Exception as e:
    print("audioop import error:", e)

def _clean(s: str) -> str:
    return (s or "").strip().strip('"').strip("'")

# ---- Env (hardened) ----
DISCORD_TOKEN = _clean(os.getenv("DISCORD_TOKEN"))
HF_TOKEN_RAW = os.getenv("HF_TOKEN")
HF_TOKEN = _clean(HF_TOKEN_RAW)
HF_MODEL_RAW = os.getenv("HF_MODEL")
HF_MODEL = _clean(HF_MODEL_RAW) or "HuggingFaceH4/zephyr-7b-beta"
PORT = int(os.getenv("PORT", "8080"))

# Validate essentials early
if not DISCORD_TOKEN:
    raise SystemExit("DISCORD_TOKEN missing. Set it as an environment variable (no quotes).")
if not HF_TOKEN or not HF_TOKEN.startswith("hf_"):
    raise SystemExit("HF_TOKEN missing/invalid. Create a Hugging Face READ token and set it (starts with 'hf_').")

def hf_url_for(model: str) -> str:
    return f"https://api-inference.huggingface.co/models/{model}"

HF_URL = hf_url_for(HF_MODEL)

# Debug (safe) — does NOT print secrets
print(f"[DEBUG] HF_TOKEN set? {bool(HF_TOKEN)} length={len(HF_TOKEN)} startswith_hf={HF_TOKEN.startswith('hf_')}")
print(f"[DEBUG] HF_MODEL env raw: {HF_MODEL_RAW!r}")
print(f"[DEBUG] HF_MODEL used: {HF_MODEL!r}")
print(f"[DEBUG] HF_URL: {HF_URL}")

# ---- Discord setup ----
INTENTS = discord.Intents.default()
INTENTS.message_content = True
bot = commands.Bot(command_prefix="!", intents=INTENTS)

SYSTEM_PROMPT = (
    "You are an unfiltered, darkly humorous assistant with a roast-comedian vibe. "
    "You use sharp wit and occasional mild profanity for comedic effect, but never slurs, "
    "hate speech, or harassment toward protected classes. No advocating harm, no graphic content. "
    "If a user pushes for disallowed content, deflect with absurd humor and move on. "
    "Replies should be punchy, surprising, and under ~180 words unless asked for more. "
    "End with one short zinger when it fits."
)

def build_prompt(user_text: str) -> str:
    preface = (
        "Give a witty, edgy answer. If the question is mundane, pretend it’s life-or-death for comedy. "
        "Add one short zinger at the end if natural.\n"
    )
    return f"{SYSTEM_PROMPT}\n\n{preface}\nUser: {user_text}\nAssistant:"

# ---- Safety filters ----
BANNED_PATTERNS = [
    r"\b(?:slur1|slur2|slur3)\b",
    r"\b(?:genocide|exterminate|lynch|gas\s*the)\b",
    r"\b(?:race\s*war|ethno(?:state|[-\s]*cleansing))\b",
]
BANNED_RE = re.compile("|".join(BANNED_PATTERNS), re.IGNORECASE)

REPLACEMENTS = {
    r"\b(dumb|idiot)\b": "goose",
    r"\b(stupid)\b": "questionable",
}

def sanitize(text: str) -> str:
    t = text or ""
    for pat, repl in REPLACEMENTS.items():
        t = re.sub(pat, repl, t, flags=re.IGNORECASE)
    if BANNED_RE.search(t):
        t = "[redacted: not going there]"
    return t.strip()[:1900]

def is_clean(text: str) -> bool:
    return BANNED_RE.search(text or "") is None

# ---- HF Inference with smarter fallback & detailed error ----
FALLBACK_MODELS: List[str] = [
    "HuggingFaceH4/zephyr-7b-beta",
    "google/gemma-2b-it",
    "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
    "Qwen/Qwen2.5-0.5B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.2",
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
                # Include a snippet to help diagnose gating/typos
                raise RuntimeError(f"HF API error {resp.status} for {model}: {text[:300]}")
            try:
                data = await resp.json()
            except Exception:
                raise RuntimeError(f"HF JSON parse error for {model}: {text[:200]}")
            if isinstance(data, list) and data and "generated_text" in data[0]:
                return data[0]["generated_text"].strip()
            if isinstance(data, dict) and "generated_text" in data:
                return data["generated_text"].strip()
            if isinstance(data, dict) and "error" in data:
                return f"[model/queue] {data['error']}"
            return str(data)[:1000]

async def hf_generate(prompt: str) -> str:
    # First try requested model, then public fallbacks
    tried: List[str] = []
    models = [HF_MODEL] + [m for m in FALLBACK_MODELS if m != HF_MODEL]
    last_err = None
    for m in models:
        print(f"[DEBUG] Trying HF model: {m}")
        tried.append(m)
        try:
            return await hf_generate_with_model(m, prompt)
        except RuntimeError as e:
            err = str(e)
            print(f"[WARN] HF call failed for {m}: {err}")
            last_err = err
            # On 401/403 the token likely lacks perms; stop early
            if " 401 " in err or " 403 " in err:
                break
            # Otherwise continue to next model (404/5xx fallthrough)
        except Exception as e:
            last_err = repr(e)
            print(f"[WARN] Unexpected HF error for {m}: {e!r}")
    raise RuntimeError(f"HF failed after trying {tried}: {last_err}")

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
    if not is_clean(prompt):
        await interaction.response.send_message("Nah, not going there.", ephemeral=True)
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
        if not is_clean(content):
            await message.reply("Nope. Try something else.")
            return
        try:
            reply = await generate_reply(message.guild.id, content)
            await message.reply(reply or "…processing…")
        except Exception as e:
            await message.reply(f"LLM error: {e}")
    await bot.process_commands(message)

# ---- Health endpoint ----
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
