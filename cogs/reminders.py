"""
Lineup eligibility reminders and penalty tracker.

Rule: starting a player who is Out/IR/on-bye = $5 penalty.

Warnings post at noon ET on Wed, Thu, Sat, Sun — giving managers time to fix lineups.
Penalties record 5 min after each game window opens (lineup locked).

Penalty lock times (ET):
  Sunday    — 1:05pm  (1pm games locked)
  Thursday  — 8:20pm  (TNF locked)
  Monday    — 8:20pm  (MNF locked)
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

import config

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Statuses that make a player ineligible to start
INELIGIBLE_STATUSES = {"Out", "IR", "PUP", "Sus", "COV", "DNR"}


def _window_key(now: datetime) -> str | None:
    """Return a unique key if it's noon ET on Wed/Thu/Sat/Sun, else None."""
    d, h, m = now.weekday(), now.hour, now.minute
    # 0=Mon 1=Tue 2=Wed 3=Thu 4=Fri 5=Sat 6=Sun — remind at noon on these days
    if d in (2, 3, 5, 6) and h == 12 and 0 <= m < 5:
        return f"remind_{now.date()}"
    return None


def _lock_key(now: datetime) -> str | None:
    """Return a unique key for the current penalty-lock window, or None."""
    d, h, m = now.weekday(), now.hour, now.minute
    if d == 6 and h == 13 and 5 <= m < 10:
        return f"lock_sun_{now.date()}"
    if d == 3 and h == 20 and 20 <= m < 25:
        return f"lock_thu_{now.date()}"
    if d == 0 and h == 20 and 20 <= m < 25:
        return f"lock_mon_{now.date()}"
    return None


class RemindersCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_map: dict[int, str] = {}
        self._handled: set[str] = set()   # keys we've already acted on this session
        self.check.start()

    def cog_unload(self):
        self.check.cancel()

    async def _build_owner_map(self) -> dict[int, str]:
        users = await self.bot.sleeper.get_users(config.LEAGUE_ID)
        rosters = await self.bot.sleeper.get_rosters(config.LEAGUE_ID)
        user_map = {u.user_id: u.display_name for u in users}
        return {
            r.roster_id: user_map.get(r.owner_id, f"Team {r.roster_id}")
            for r in rosters
        }

    @tasks.loop(minutes=1)
    async def check(self):
        try:
            now = datetime.now(ET)
            rkey = _window_key(now)
            lkey = _lock_key(now)

            if rkey and rkey not in self._handled:
                self._handled.add(rkey)
                await self._post_warnings()

            if lkey and lkey not in self._handled:
                self._handled.add(lkey)
                await self._record_penalties()
        except Exception:
            log.exception("[reminders] check error")

    @check.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()
        self._owner_map = await self._build_owner_map()
        log.info("[reminders] ready")

    async def _get_ineligible_starters(self, week: int) -> dict[int, list[dict]]:
        """
        Returns {roster_id: [{"name": ..., "reason": ...}, ...]}
        for any starter that is injured/IR or on bye this week.
        """
        league = await self.bot.sleeper.get_league(config.LEAGUE_ID)
        bye_teams = await self.bot.sleeper.get_bye_teams(league.season, week)
        rosters = await self.bot.sleeper.get_rosters(config.LEAGUE_ID)

        result: dict[int, list[dict]] = {}

        for roster in rosters:
            bad = []
            for pid in roster.starters:
                if pid == "0":
                    continue
                info = await self.bot.db.get_player_info(pid)
                if not info:
                    continue
                full_name, team, injury_status = info

                if injury_status in INELIGIBLE_STATUSES:
                    bad.append({"name": full_name, "reason": f"status: {injury_status}"})
                elif team and team in bye_teams:
                    bad.append({"name": full_name, "reason": "on bye week"})

            if bad:
                result[roster.roster_id] = bad

        return result

    async def _post_warnings(self):
        channel = self.bot.get_channel(config.REMINDERS_CHANNEL_ID)
        if not channel:
            log.warning("[reminders] channel %s not found", config.REMINDERS_CHANNEL_ID)
            return

        league = await self.bot.sleeper.get_league(config.LEAGUE_ID)
        week = league.current_week
        ineligible = await self._get_ineligible_starters(week)

        if not ineligible:
            log.info("[reminders] week %d — no ineligible starters found", week)
            return

        for roster_id, bad_players in ineligible.items():
            manager = self._owner_map.get(roster_id, f"Team {roster_id}")
            player_lines = "\n".join(f"• **{p['name']}** ({p['reason']})" for p in bad_players)
            embed = discord.Embed(
                title=f"⚠️  Lineup Warning — {manager}",
                description=(
                    f"The following starters are **ineligible** for Week {week}.\n"
                    f"Fix your lineup or face a **$5 penalty per player**.\n\n"
                    f"{player_lines}"
                ),
                color=discord.Color.orange(),
            )
            await channel.send(embed=embed)

        log.info("[reminders] week %d — posted warnings for %d teams", week, len(ineligible))

    async def _record_penalties(self):
        channel = self.bot.get_channel(config.REMINDERS_CHANNEL_ID)
        league = await self.bot.sleeper.get_league(config.LEAGUE_ID)
        week = league.current_week
        season = league.season
        ineligible = await self._get_ineligible_starters(week)

        new_penalties: dict[int, list[str]] = {}

        for roster_id, bad_players in ineligible.items():
            for p in bad_players:
                # Use player name as player_id key here since we have it
                recorded = await self.bot.db.add_penalty(
                    season=season,
                    week=week,
                    roster_id=roster_id,
                    player_id=p["name"],
                    player_name=p["name"],
                    reason=p["reason"],
                )
                if recorded:
                    new_penalties.setdefault(roster_id, []).append(p["name"])

        if not new_penalties or not channel:
            return

        for roster_id, names in new_penalties.items():
            manager = self._owner_map.get(roster_id, f"Team {roster_id}")
            player_lines = "\n".join(f"• {n}" for n in names)
            total = len(names) * 5
            embed = discord.Embed(
                title=f"💸  Penalty Recorded — {manager}",
                description=(
                    f"Started ineligible player(s) in Week {week}:\n\n"
                    f"{player_lines}\n\n"
                    f"**Total: ${total}**"
                ),
                color=discord.Color.red(),
            )
            await channel.send(embed=embed)

        log.info("[reminders] week %d — recorded penalties for %d teams", week, len(new_penalties))


async def setup(bot):
    await bot.add_cog(RemindersCog(bot))
