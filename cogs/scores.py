import logging

import discord
from discord.ext import commands, tasks
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from utils.embeds import score_embed

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def in_game_window() -> bool:
    """Return True during NFL game windows (ET)."""
    now = datetime.now(ET)
    day = now.weekday()  # 0=Mon 1=Tue 2=Wed 3=Thu 4=Fri 5=Sat 6=Sun
    h = now.hour

    if day == 6 and h >= 12:   # Sunday 1pm+ (early, afternoon, SNF)
        return True
    if day == 0 and h <= 2:    # Monday 12-2am (SNF late end)
        return True
    if day == 3 and h >= 19:   # Thursday night
        return True
    if day == 4 and h <= 1:    # Friday 12-1am (TNF late end)
        return True
    if day == 0 and h >= 19:   # Monday Night Football
        return True
    if day == 1 and h <= 1:    # Tuesday 12-1am (MNF late end)
        return True
    if day == 5 and h >= 12:   # Saturday games (late season)
        return True
    return False


class ScoresCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_map: dict[int, str] = {}
        self._was_in_window = False
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

    @tasks.loop(seconds=60)
    async def poll(self):
        try:
            window_now = in_game_window()

            if window_now:
                await self._check_scores()
            elif self._was_in_window:
                await self._post_final_summary()

            self._was_in_window = window_now
        except Exception:
            log.exception("[scores] poll error")

    @poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()
        self._owner_map = await self._build_owner_map()
        league = await self.bot.sleeper.get_league(config.LEAGUE_ID)
        log.info("[scores] ready — week %d, in window: %s", league.current_week, in_game_window())

    async def _current_week(self) -> int:
        league = await self.bot.sleeper.get_league(config.LEAGUE_ID)
        return league.current_week

    async def _get_pairs(self, week: int) -> dict[int, list]:
        matchups = await self.bot.sleeper.get_matchups(config.LEAGUE_ID, week)
        pairs: dict[int, list] = {}
        for team in matchups:
            pairs.setdefault(team.matchup_id, []).append(team)
        return pairs

    async def _check_scores(self):
        week = await self._current_week()
        pairs = await self._get_pairs(week)
        channel = self.bot.get_channel(config.SCORES_CHANNEL_ID)
        if not channel:
            return

        changed_lines: list[str] = []

        for teams in pairs.values():
            if len(teams) != 2 or teams[0].matchup_id is None:
                continue

            # Load previous snapshots
            prev = {t.roster_id: await self.bot.db.get_score_snapshot(t.roster_id, week) for t in teams}

            # Save current snapshots
            for t in teams:
                await self.bot.db.set_score_snapshot(t.roster_id, week, t.points)

            # Skip if no baseline yet (first poll of the window)
            if any(v is None for v in prev.values()):
                continue

            # Skip if nothing changed
            if not any(abs(t.points - prev[t.roster_id]) >= 0.1 for t in teams):
                continue

            a, b = sorted(teams, key=lambda t: t.points, reverse=True)
            name_a = self._owner_map.get(a.roster_id, f"Team {a.roster_id}")
            name_b = self._owner_map.get(b.roster_id, f"Team {b.roster_id}")
            changed_lines.append(
                f"**{name_a}**  {a.points:.2f}  ·  {name_b}  {b.points:.2f}"
            )

        if changed_lines:
            desc = "\n".join(changed_lines)
            await channel.send(embed=score_embed(f"🏈  Scores — Week {week}", desc))

    async def _post_final_summary(self):
        week = await self._current_week()
        pairs = await self._get_pairs(week)
        channel = self.bot.get_channel(config.SCORES_CHANNEL_ID)
        if not channel:
            return

        lines: list[str] = []
        for teams in pairs.values():
            if len(teams) != 2 or teams[0].matchup_id is None:
                continue
            winner, loser = sorted(teams, key=lambda t: t.points, reverse=True)
            name_w = self._owner_map.get(winner.roster_id, f"Team {winner.roster_id}")
            name_l = self._owner_map.get(loser.roster_id, f"Team {loser.roster_id}")
            lines.append(f"🏆  **{name_w}** def. {name_l}  |  {winner.points:.2f} – {loser.points:.2f}")

        if lines:
            await channel.send(embed=score_embed(
                f"📊  Final Scores — Week {week}",
                "\n".join(lines),
                color=discord.Color.gold(),
            ))


async def setup(bot):
    await bot.add_cog(ScoresCog(bot))
