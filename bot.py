import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler

import aiohttp
import discord
from discord.ext import commands, tasks

import config
from db.storage import Database
from sleeper.api import SleeperAPI


# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(os.getenv("LOG_PATH", "bot.log"), maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── Bot setup ──────────────────────────────────────────────────────────────
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
bot.db: Database = None
bot.sleeper: SleeperAPI = None
bot.http_session: aiohttp.ClientSession = None


@bot.event
async def on_ready():
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    await bot.tree.sync()
    log.info("Slash commands synced")


@bot.event
async def on_error(event: str, *args, **kwargs):
    log.exception("Unhandled error in event: %s", event)


@bot.tree.command(name="ping", description="Check if the bot is online")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! Latency: {latency}ms")


# ── Daily player cache refresh ─────────────────────────────────────────────
@tasks.loop(hours=24)
async def refresh_player_cache():
    try:
        log.info("Refreshing player cache...")
        players = await bot.sleeper.get_players()
        await bot.db.cache_players(players)
        log.info("Player cache refreshed: %d players", len(players))
    except Exception:
        log.exception("Failed to refresh player cache")


@refresh_player_cache.before_loop
async def before_refresh():
    await bot.wait_until_ready()


# ── Entry point ────────────────────────────────────────────────────────────
async def main():
    async with aiohttp.ClientSession() as session:
        bot.http_session = session
        bot.sleeper = SleeperAPI(session)
        bot.db = await Database.create()

        if await bot.db.is_player_cache_stale():
            log.info("Fetching player cache from Sleeper (this takes a moment)...")
            players = await bot.sleeper.get_players()
            await bot.db.cache_players(players)
            log.info("Cached %d players", len(players))

        await bot.load_extension("cogs.transactions")
        await bot.load_extension("cogs.scores")
        await bot.load_extension("cogs.general")
        await bot.load_extension("cogs.reminders")

        refresh_player_cache.start()

        async with bot:
            await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
