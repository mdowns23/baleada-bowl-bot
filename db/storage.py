import time
import aiosqlite
from typing import Optional

import os
DB_PATH = os.getenv("DB_PATH", "fantasy_bot.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_transactions (
    transaction_id TEXT PRIMARY KEY,
    created_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS player_cache (
    player_id      TEXT PRIMARY KEY,
    full_name      TEXT NOT NULL,
    position       TEXT NOT NULL,
    team           TEXT,
    injury_status  TEXT,
    cached_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS score_snapshots (
    roster_id  INTEGER NOT NULL,
    week       INTEGER NOT NULL,
    points     REAL    NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (roster_id, week)
);

CREATE TABLE IF NOT EXISTS penalties (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    season      TEXT    NOT NULL,
    week        INTEGER NOT NULL,
    roster_id   INTEGER NOT NULL,
    player_id   TEXT    NOT NULL,
    player_name TEXT    NOT NULL,
    reason      TEXT    NOT NULL,
    recorded_at INTEGER NOT NULL,
    UNIQUE(season, week, roster_id, player_id)
);
"""


class Database:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    @classmethod
    async def create(cls) -> "Database":
        conn = await aiosqlite.connect(DB_PATH)
        await conn.executescript(_SCHEMA)
        # Migration: add injury_status column for existing DBs
        try:
            await conn.execute("ALTER TABLE player_cache ADD COLUMN injury_status TEXT")
            await conn.commit()
        except Exception:
            pass  # Column already exists
        await conn.commit()
        return cls(conn)

    # --- Transactions ---

    async def has_seen_transaction(self, transaction_id: str) -> bool:
        async with self._conn.execute(
            "SELECT 1 FROM seen_transactions WHERE transaction_id = ?",
            (transaction_id,),
        ) as cur:
            return await cur.fetchone() is not None

    async def mark_transaction_seen(self, transaction_id: str, created_at: int) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO seen_transactions (transaction_id, created_at) VALUES (?, ?)",
            (transaction_id, created_at),
        )
        await self._conn.commit()

    # --- Score snapshots ---

    async def get_score_snapshot(self, roster_id: int, week: int) -> Optional[float]:
        async with self._conn.execute(
            "SELECT points FROM score_snapshots WHERE roster_id = ? AND week = ?",
            (roster_id, week),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def set_score_snapshot(self, roster_id: int, week: int, points: float) -> None:
        await self._conn.execute(
            """INSERT INTO score_snapshots (roster_id, week, points, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(roster_id, week)
               DO UPDATE SET points = excluded.points, updated_at = excluded.updated_at""",
            (roster_id, week, points, int(time.time())),
        )
        await self._conn.commit()

    # --- Player cache ---

    async def is_player_cache_stale(self, max_age_hours: int = 24) -> bool:
        async with self._conn.execute(
            "SELECT MAX(cached_at) FROM player_cache"
        ) as cur:
            row = await cur.fetchone()
            if not row or row[0] is None:
                return True
            return (time.time() - row[0]) > (max_age_hours * 3600)

    async def cache_players(self, players: dict) -> None:
        now = int(time.time())
        await self._conn.executemany(
            """INSERT OR REPLACE INTO player_cache
               (player_id, full_name, position, team, injury_status, cached_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (pid, p.full_name, p.position or "", p.team, p.injury_status, now)
                for pid, p in players.items()
            ],
        )
        await self._conn.commit()

    async def get_player_name(self, player_id: str) -> str:
        async with self._conn.execute(
            "SELECT full_name FROM player_cache WHERE player_id = ?",
            (player_id,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else player_id

    async def get_player_info(self, player_id: str) -> Optional[tuple[str, Optional[str], Optional[str]]]:
        """Returns (full_name, team, injury_status) or None."""
        async with self._conn.execute(
            "SELECT full_name, team, injury_status FROM player_cache WHERE player_id = ?",
            (player_id,),
        ) as cur:
            return await cur.fetchone()

    # --- Penalties ---

    async def add_penalty(
        self,
        season: str,
        week: int,
        roster_id: int,
        player_id: str,
        player_name: str,
        reason: str,
    ) -> bool:
        """Insert penalty. Returns True if new, False if already recorded."""
        try:
            await self._conn.execute(
                """INSERT INTO penalties
                   (season, week, roster_id, player_id, player_name, reason, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (season, week, roster_id, player_id, player_name, reason, int(time.time())),
            )
            await self._conn.commit()
            return True
        except Exception:
            return False  # UNIQUE constraint — already recorded

    async def get_penalties(self, season: str) -> list[tuple]:
        """Returns all penalties for the season as (week, roster_id, player_name, reason)."""
        async with self._conn.execute(
            "SELECT week, roster_id, player_name, reason FROM penalties WHERE season = ? ORDER BY week, roster_id",
            (season,),
        ) as cur:
            return await cur.fetchall()

    async def get_penalties_by_roster(self, season: str, roster_id: int) -> list[tuple]:
        async with self._conn.execute(
            "SELECT week, player_name, reason FROM penalties WHERE season = ? AND roster_id = ? ORDER BY week",
            (season, roster_id),
        ) as cur:
            return await cur.fetchall()

    async def close(self) -> None:
        await self._conn.close()
