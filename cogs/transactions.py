import logging

import discord
from discord.ext import commands, tasks

import config
from utils.embeds import transaction_embed

log = logging.getLogger(__name__)


class TransactionsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_map: dict[int, str] = {}  # roster_id -> display_name
        self.poll.start()

    def cog_unload(self):
        self.poll.cancel()

    async def _build_owner_map(self) -> dict[int, str]:
        users = await self.bot.sleeper.get_users(config.LEAGUE_ID)
        rosters = await self.bot.sleeper.get_rosters(config.LEAGUE_ID)
        user_map = {u.user_id: u.display_name for u in users}
        return {
            r.roster_id: user_map.get(r.owner_id, f"Team {r.roster_id}")
            for r in rosters
        }

    @tasks.loop(minutes=2)
    async def poll(self):
        try:
            await self._check_transactions()
        except Exception:
            log.exception("[transactions] poll error")

    @poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()
        self._owner_map = await self._build_owner_map()
        log.info("[transactions] owner map built: %d teams", len(self._owner_map))

    async def _check_transactions(self):
        league = await self.bot.sleeper.get_league(config.LEAGUE_ID)
        week = league.current_week
        transactions = await self.bot.sleeper.get_transactions(config.LEAGUE_ID, week)

        channel = self.bot.get_channel(config.TRANSACTIONS_CHANNEL_ID)
        if not channel:
            log.warning("[transactions] channel %s not found", config.TRANSACTIONS_CHANNEL_ID)
            return

        for t in transactions:
            if t.status != "complete":
                continue
            if await self.bot.db.has_seen_transaction(t.transaction_id):
                continue

            embed = await self._format_transaction(t)
            if embed:
                await channel.send(embed=embed)

            await self.bot.db.mark_transaction_seen(t.transaction_id, t.created)

    async def _format_transaction(self, t) -> discord.Embed | None:
        if t.type in ("waiver", "free_agent"):
            return await self._format_add_drop(t)
        if t.type == "trade":
            return await self._format_trade(t)
        return None

    async def _format_add_drop(self, t) -> discord.Embed:
        # Determine which roster made this move
        if t.adds:
            manager_roster_id = next(iter(t.adds.values()))
        elif t.drops:
            manager_roster_id = next(iter(t.drops.values()))
        else:
            manager_roster_id = t.roster_ids[0] if t.roster_ids else 0

        manager = self._owner_map.get(manager_roster_id, f"Team {manager_roster_id}")
        label = "Waiver Claim" if t.type == "waiver" else "Free Agent Add"
        title = f"🔄  {manager} — {label}"

        lines = []
        for pid in t.adds:
            name = await self.bot.db.get_player_name(pid)
            lines.append(f"**Added:** {name}")
        for pid in t.drops:
            name = await self.bot.db.get_player_name(pid)
            lines.append(f"**Dropped:** {name}")
        if t.type == "waiver" and t.waiver_bid is not None:
            lines.append(f"**FAAB Bid:** ${t.waiver_bid}")

        return transaction_embed(title, "\n".join(lines) if lines else "No details available")

    async def _format_trade(self, t) -> discord.Embed:
        # adds: {player_id: roster_id_that_receives_the_player}
        receiving: dict[int, list[str]] = {rid: [] for rid in t.roster_ids}

        for pid, rid in t.adds.items():
            name = await self.bot.db.get_player_name(pid)
            if rid in receiving:
                receiving[rid].append(name)

        for pick in t.draft_picks:
            # pick owner_id is the roster that ends up with the pick
            rid = pick.get("owner_id") or pick.get("roster_id")
            if rid in receiving:
                season = pick.get("season", "")
                rnd = pick.get("round", "?")
                receiving[rid].append(f"{season} Rd {rnd} Pick")

        lines = []
        for rid, assets in receiving.items():
            manager = self._owner_map.get(rid, f"Team {rid}")
            asset_str = ", ".join(assets) if assets else "nothing"
            lines.append(f"**{manager} receives:** {asset_str}")

        return transaction_embed("🤝  Trade Alert", "\n".join(lines) if lines else "No details available")


async def setup(bot):
    await bot.add_cog(TransactionsCog(bot))
