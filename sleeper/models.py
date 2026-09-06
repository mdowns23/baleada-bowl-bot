from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LeagueInfo:
    league_id: str
    name: str
    season: str
    current_week: int
    total_rosters: int


@dataclass
class User:
    user_id: str
    display_name: str
    avatar: Optional[str]


@dataclass
class Roster:
    roster_id: int
    owner_id: Optional[str]
    players: list[str]
    starters: list[str]
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float


@dataclass
class MatchupTeam:
    roster_id: int
    matchup_id: int
    points: float
    starters: list[str]
    players_points: dict[str, float] = field(default_factory=dict)


@dataclass
class Transaction:
    transaction_id: str
    type: str           # "waiver", "free_agent", "trade"
    status: str         # "complete", "pending", "failed"
    week: int
    roster_ids: list[int]
    adds: dict[str, int]        # player_id -> roster_id
    drops: dict[str, int]       # player_id -> roster_id
    draft_picks: list[dict]     # picks exchanged (trades only)
    created: int                # unix ms timestamp
    waiver_bid: Optional[int]   # FAAB bid amount (waivers only)


@dataclass
class Player:
    player_id: str
    full_name: str
    position: str
    team: Optional[str]
    injury_status: Optional[str] = None  # "Out", "IR", "PUP", "Sus", "COV", etc.
