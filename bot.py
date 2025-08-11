import os, re, time, asyncio
from typing import Dict
import aiohttp
import discord
from discord.ext import commands
from aiohttp import web

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")
HF_MODEL = os.getenv("HF_MODEL", "HuggingFaceH4/zephyr-7b-beta")
PORT = int(os.getenv("PORT", "8080"))

if not DISCORD_TOKEN or not HF_TOKEN:
    raise SystemExit("Set DISCORD_TOKEN and HF_TOKEN as environment variables.")

HF_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"

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





async def hf_generate(prompt: str, max_new_tokens: int = 220, temperature: float = 0.9, top_p: float = 0.9) -> str:
    headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
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
        async with session.post(HF_URL, headers=headers, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"HF API error {resp.status}: {text}")
            data = await resp.json()
            if isinstance(data, list) and data and "generated_text" in data[0]:
                return data[0]["generated_text"].strip()
            if isinstance(data, dict) and "generated_text" in data:
                return data["generated_text"].strip()
            if isinstance(data, dict) and "error" in data:
                return f"[model cold start/queue] {data['error']}"
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
    prompt = build_prompt(user_text)
    raw = await hf_generate(prompt)
    return raw

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
