import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise ValueError(f"Missing required env var: {key}")
    return val


DISCORD_TOKEN = _require("DISCORD_TOKEN")
LEAGUE_ID = _require("LEAGUE_ID")
SCORES_CHANNEL_ID = int(os.getenv("SCORES_CHANNEL_ID", "0"))
TRANSACTIONS_CHANNEL_ID = int(os.getenv("TRANSACTIONS_CHANNEL_ID", "0"))
REMINDERS_CHANNEL_ID = int(os.getenv("REMINDERS_CHANNEL_ID", "0"))
NFL_SEASON = os.getenv("NFL_SEASON", "2025")
