import asyncio
import logging
import aiohttp
from .models import LeagueInfo, User, Roster, MatchupTeam, Transaction, Player

BASE_URL = "https://api.sleeper.app/v1"
log = logging.getLogger(__name__)


class SleeperAPI:
    def __init__(self, session: aiohttp.ClientSession):
        self._session = session

    async def _get(self, path: str):
        for attempt in range(3):
            try:
                async with self._session.get(f"{BASE_URL}{path}") as resp:
                    if resp.status == 429:
                        wait = 5 * (attempt + 1)
                        log.warning("Rate limited by Sleeper, retrying in %ss", wait)
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    return await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == 2:
                    log.error("Sleeper API request failed after 3 attempts: %s — %s", path, e)
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"Sleeper API unreachable: {path}")

    async def get_league(self, league_id: str) -> LeagueInfo:
        data = await self._get(f"/league/{league_id}")
        return LeagueInfo(
            league_id=data["league_id"],
            name=data["name"],
            season=data["season"],
            current_week=data["settings"]["leg"],
            total_rosters=data["total_rosters"],
        )

    async def get_users(self, league_id: str) -> list[User]:
        data = await self._get(f"/league/{league_id}/users")
        return [
            User(
                user_id=u["user_id"],
                display_name=u["display_name"],
                avatar=u.get("avatar"),
            )
            for u in data
        ]

    async def get_rosters(self, league_id: str) -> list[Roster]:
        data = await self._get(f"/league/{league_id}/rosters")
        results = []
        for r in data:
            s = r["settings"]
            fpts = s.get("fpts", 0) + s.get("fpts_decimal", 0) / 100
            fpts_against = s.get("fpts_against", 0) + s.get("fpts_against_decimal", 0) / 100
            results.append(Roster(
                roster_id=r["roster_id"],
                owner_id=r.get("owner_id"),
                players=r.get("players") or [],
                starters=r.get("starters") or [],
                wins=s.get("wins", 0),
                losses=s.get("losses", 0),
                ties=s.get("ties", 0),
                points_for=fpts,
                points_against=fpts_against,
            ))
        return results

    async def get_matchups(self, league_id: str, week: int) -> list[MatchupTeam]:
        data = await self._get(f"/league/{league_id}/matchups/{week}")
        return [
            MatchupTeam(
                roster_id=m["roster_id"],
                matchup_id=m["matchup_id"],
                points=m.get("points", 0.0),
                starters=m.get("starters") or [],
                players_points=m.get("players_points") or {},
            )
            for m in data
        ]

    async def get_transactions(self, league_id: str, week: int) -> list[Transaction]:
        data = await self._get(f"/league/{league_id}/transactions/{week}")
        results = []
        for t in data:
            bid = None
            if t.get("settings") and t["settings"].get("waiver_bid") is not None:
                bid = t["settings"]["waiver_bid"]
            results.append(Transaction(
                transaction_id=t["transaction_id"],
                type=t["type"],
                status=t["status"],
                week=week,
                roster_ids=t.get("roster_ids") or [],
                adds=t.get("adds") or {},
                drops=t.get("drops") or {},
                draft_picks=t.get("draft_picks") or [],
                created=t.get("created", 0),
                waiver_bid=bid,
            ))
        return results

    async def get_players(self) -> dict[str, Player]:
        data = await self._get("/players/nfl")
        players: dict[str, Player] = {}
        for pid, p in data.items():
            full_name = p.get("full_name") or (
                f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            )
            players[pid] = Player(
                player_id=pid,
                full_name=full_name or pid,
                position=p.get("position", ""),
                team=p.get("team"),
                injury_status=p.get("injury_status"),
            )
        return players

    async def get_bye_teams(self, season: str, week: int) -> set[str]:
        """Return team abbreviations that are on bye this week."""
        try:
            games = await self._get(f"/schedule/nfl/regular/{season}/{week}")
            playing: set[str] = set()
            for game in games:
                if game.get("home_team"):
                    playing.add(game["home_team"])
                if game.get("away_team"):
                    playing.add(game["away_team"])
            # All 32 NFL teams
            all_teams = {
                "ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN",
                "DET","GB","HOU","IND","JAX","KC","LA","LAC","LV","MIA",
                "MIN","NE","NO","NYG","NYJ","PHI","PIT","SEA","SF","TB","TEN","WAS",
            }
            return all_teams - playing
        except Exception:
            log.warning("Could not fetch bye teams for week %d — skipping bye check", week)
            return set()
