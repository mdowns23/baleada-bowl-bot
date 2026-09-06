import discord
from discord.ext import commands
from discord import app_commands

import config


class GeneralCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_map: dict[int, str] = {}   # roster_id -> display_name
        self._roster_map: dict[str, int] = {}  # name.lower() -> roster_id

    async def _ensure_maps(self):
        if self._owner_map:
            return
        users = await self.bot.sleeper.get_users(config.LEAGUE_ID)
        rosters = await self.bot.sleeper.get_rosters(config.LEAGUE_ID)
        user_map = {u.user_id: u.display_name for u in users}
        self._owner_map = {
            r.roster_id: user_map.get(r.owner_id, f"Team {r.roster_id}")
            for r in rosters
        }
        self._roster_map = {name.lower(): rid for rid, name in self._owner_map.items()}

    def _find_roster_id(self, query: str) -> int | None:
        q = query.lower()
        if q in self._roster_map:
            return self._roster_map[q]
        for name, rid in self._roster_map.items():
            if q in name:
                return rid
        return None

    # ── /scores ────────────────────────────────────────────────────────────

    @app_commands.command(name="scores", description="Current week matchup scores")
    async def scores(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._ensure_maps()

        league = await self.bot.sleeper.get_league(config.LEAGUE_ID)
        week = league.current_week
        matchups = await self.bot.sleeper.get_matchups(config.LEAGUE_ID, week)

        pairs: dict[int, list] = {}
        for team in matchups:
            pairs.setdefault(team.matchup_id, []).append(team)

        lines = []
        for teams in sorted(pairs.values(), key=lambda t: t[0].matchup_id or 0):
            if len(teams) != 2 or teams[0].matchup_id is None:
                continue
            a, b = sorted(teams, key=lambda t: t.points, reverse=True)
            name_a = self._owner_map.get(a.roster_id, f"Team {a.roster_id}")
            name_b = self._owner_map.get(b.roster_id, f"Team {b.roster_id}")
            lines.append(f"**{name_a}**  {a.points:.2f}  ·  {name_b}  {b.points:.2f}")

        embed = discord.Embed(
            title=f"🏈  Scores — Week {week}",
            description="\n".join(lines) or "No matchups found.",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed)

    # ── /standings ─────────────────────────────────────────────────────────

    @app_commands.command(name="standings", description="League standings")
    async def standings(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._ensure_maps()

        rosters = await self.bot.sleeper.get_rosters(config.LEAGUE_ID)
        sorted_rosters = sorted(rosters, key=lambda r: (r.wins, r.points_for), reverse=True)

        lines = []
        for i, r in enumerate(sorted_rosters, 1):
            name = self._owner_map.get(r.roster_id, f"Team {r.roster_id}")
            record = f"{r.wins}-{r.losses}" + (f"-{r.ties}" if r.ties else "")
            lines.append(f"`{i:2}.` **{name}**  {record}  ({r.points_for:.2f} pts)")

        embed = discord.Embed(
            title="📊  Standings",
            description="\n".join(lines) or "No data.",
            color=discord.Color.blue(),
        )
        await interaction.followup.send(embed=embed)

    # ── /roster ────────────────────────────────────────────────────────────

    @app_commands.command(name="roster", description="View a manager's roster")
    @app_commands.describe(manager="Manager name (partial match ok)")
    async def roster(self, interaction: discord.Interaction, manager: str):
        await interaction.response.defer()
        await self._ensure_maps()

        roster_id = self._find_roster_id(manager)
        if roster_id is None:
            names = ", ".join(self._owner_map.values())
            await interaction.followup.send(f"Manager not found. Available: {names}")
            return

        rosters = await self.bot.sleeper.get_rosters(config.LEAGUE_ID)
        r = next((x for x in rosters if x.roster_id == roster_id), None)
        if not r:
            await interaction.followup.send("Roster not found.")
            return

        name = self._owner_map[roster_id]
        starter_set = set(r.starters)

        starter_lines, bench_lines = [], []
        for pid in r.starters:
            if pid == "0":
                starter_lines.append("• *Empty slot*")
                continue
            pname = await self.bot.db.get_player_name(pid)
            starter_lines.append(f"• {pname}")
        for pid in r.players:
            if pid not in starter_set:
                pname = await self.bot.db.get_player_name(pid)
                bench_lines.append(f"• {pname}")

        embed = discord.Embed(title=f"📋  {name}'s Roster", color=discord.Color.blue())
        embed.add_field(name="Starters", value="\n".join(starter_lines) or "None", inline=True)
        embed.add_field(name="Bench", value="\n".join(bench_lines) or "None", inline=True)
        await interaction.followup.send(embed=embed)

    # ── /transactions ──────────────────────────────────────────────────────

    @app_commands.command(name="transactions", description="Recent transactions")
    @app_commands.describe(week="Week number (defaults to current week)")
    async def transactions(self, interaction: discord.Interaction, week: int = 0):
        await interaction.response.defer()
        await self._ensure_maps()

        if week == 0:
            league = await self.bot.sleeper.get_league(config.LEAGUE_ID)
            week = league.current_week

        all_t = await self.bot.sleeper.get_transactions(config.LEAGUE_ID, week)
        recent = [t for t in all_t if t.status == "complete"][:5]

        if not recent:
            await interaction.followup.send(f"No completed transactions for week {week}.")
            return

        lines = []
        for t in recent:
            roster_id = (
                next(iter(t.adds.values())) if t.adds
                else next(iter(t.drops.values())) if t.drops
                else t.roster_ids[0] if t.roster_ids else 0
            )
            manager = self._owner_map.get(roster_id, f"Team {roster_id}")

            if t.type == "trade":
                lines.append(f"🤝 **Trade** — {manager} involved")
            else:
                label = "Waiver" if t.type == "waiver" else "FA Add"
                adds = [await self.bot.db.get_player_name(pid) for pid in t.adds]
                drops = [await self.bot.db.get_player_name(pid) for pid in t.drops]
                parts = ([f"+{n}" for n in adds]) + ([f"-{n}" for n in drops])
                lines.append(f"🔄 **{label}** — {manager}: {', '.join(parts)}")

        embed = discord.Embed(
            title=f"📝  Recent Transactions — Week {week}",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await interaction.followup.send(embed=embed)

    # ── /matchup ───────────────────────────────────────────────────────────

    @app_commands.command(name="matchup", description="Detailed matchup breakdown for a manager")
    @app_commands.describe(manager="Manager name (partial match ok)")
    async def matchup(self, interaction: discord.Interaction, manager: str):
        await interaction.response.defer()
        await self._ensure_maps()

        roster_id = self._find_roster_id(manager)
        if roster_id is None:
            names = ", ".join(self._owner_map.values())
            await interaction.followup.send(f"Manager not found. Available: {names}")
            return

        league = await self.bot.sleeper.get_league(config.LEAGUE_ID)
        week = league.current_week
        matchups = await self.bot.sleeper.get_matchups(config.LEAGUE_ID, week)

        my_team = next((m for m in matchups if m.roster_id == roster_id), None)
        if not my_team:
            await interaction.followup.send("No matchup found for this manager.")
            return

        opponent = next(
            (m for m in matchups if m.matchup_id == my_team.matchup_id and m.roster_id != roster_id),
            None,
        )

        name = self._owner_map[roster_id]
        opp_name = self._owner_map.get(opponent.roster_id, "Opponent") if opponent else "Opponent"

        embed = discord.Embed(
            title=f"🏈  Week {week}: {name} vs {opp_name}",
            color=discord.Color.green(),
        )

        my_lines = []
        for pid in my_team.starters:
            pname = await self.bot.db.get_player_name(pid)
            pts = my_team.players_points.get(pid, 0.0)
            my_lines.append(f"{pname}  **{pts:.2f}**")
        embed.add_field(
            name=f"{name}  —  {my_team.points:.2f} pts",
            value="\n".join(my_lines) or "No starters set",
            inline=True,
        )

        if opponent:
            opp_lines = []
            for pid in opponent.starters:
                pname = await self.bot.db.get_player_name(pid)
                pts = opponent.players_points.get(pid, 0.0)
                opp_lines.append(f"{pname}  **{pts:.2f}**")
            embed.add_field(
                name=f"{opp_name}  —  {opponent.points:.2f} pts",
                value="\n".join(opp_lines) or "No starters set",
                inline=True,
            )

        await interaction.followup.send(embed=embed)

    # ── /penalties ─────────────────────────────────────────────────────────

    @app_commands.command(name="penalties", description="Show all $5 penalties this season")
    async def penalties(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._ensure_maps()

        league = await self.bot.sleeper.get_league(config.LEAGUE_ID)
        rows = await self.bot.db.get_penalties(league.season)

        if not rows:
            await interaction.followup.send("No penalties recorded this season.")
            return

        totals: dict[int, int] = {}
        detail: dict[int, list[str]] = {}
        for week, roster_id, player_name, reason in rows:
            totals[roster_id] = totals.get(roster_id, 0) + 5
            detail.setdefault(roster_id, []).append(f"Wk {week}: {player_name} ({reason})")

        embed = discord.Embed(
            title=f"💸  Penalty Ledger — {league.season} Season",
            color=discord.Color.red(),
        )
        for roster_id, total in sorted(totals.items(), key=lambda x: x[1], reverse=True):
            manager = self._owner_map.get(roster_id, f"Team {roster_id}")
            embed.add_field(
                name=f"{manager}  —  ${total}",
                value="\n".join(detail[roster_id]),
                inline=False,
            )

        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(GeneralCog(bot))
