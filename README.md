# Baleada Bowl Bot

A Discord bot for a 12-team Sleeper fantasy football league. Provides live score updates, transaction alerts, lineup eligibility reminders, and a $5 penalty tracker — all automated and running 24/7 in the cloud.

---

## Features

### Live Score Updates
Polls the Sleeper API every 60 seconds during NFL game windows (Thursday Night, Sunday, Monday Night). Posts a score update embed to a dedicated channel whenever any matchup score changes, and a final summary embed when the game window closes.

### Transaction Alerts
Polls for completed transactions every 2 minutes throughout the week. Posts formatted embeds for:
- Waiver claims (with FAAB bid amount)
- Free agent adds/drops
- Trades (with full asset breakdown per side)

### Lineup Eligibility Reminders
Posts warnings at noon ET every Wednesday, Thursday, Saturday, and Sunday listing any manager who has an ineligible player in their starting lineup. A player is ineligible if they are:
- Listed as Out, IR, PUP, or Suspended
- Playing for a team on bye week

### Penalty Tracker
At lineup lock time, checks all starting lineups and records a $5 penalty for every ineligible player still starting. Penalties are stored in a local SQLite database and viewable via slash command at any time.

### Slash Commands

| Command | Description |
|---|---|
| `/scores` | Current week matchup scores |
| `/standings` | League standings (record + total points) |
| `/matchup [manager]` | Player-by-player matchup breakdown |
| `/roster [manager]` | Full roster — starters and bench |
| `/transactions [week]` | 5 most recent completed transactions |
| `/penalties` | Season-long penalty ledger with totals |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Discord library | discord.py 2.x |
| HTTP client | aiohttp (async) |
| Database | SQLite via aiosqlite |
| Data source | Sleeper Fantasy API (public, no auth required) |
| Hosting | Docker on Hostinger VPS |

---

## Architecture

```
bot.py                  # Entry point — bot init, cog loading, daily cache refresh
config.py               # Environment variable validation
sleeper/
  api.py                # Async Sleeper API client with retry/backoff
  models.py             # Typed dataclasses for all API responses
cogs/
  scores.py             # Live score polling loop + game window detection
  transactions.py       # Transaction polling loop + alert formatting
  reminders.py          # Lineup eligibility checks + penalty recording
  general.py            # All slash commands
db/
  storage.py            # SQLite schema, player cache, penalty ledger
utils/
  embeds.py             # Reusable Discord embed builders
```

The bot uses `discord.ext.tasks` loops for all polling — no external job scheduler needed. SQLite persistence lives in a named Docker volume so data survives container restarts and redeployments.

---

## Running Locally

**Prerequisites:** Python 3.12+, a Discord bot token, a Sleeper league ID.

```bash
# Clone and set up environment
git clone https://github.com/mdowns23/baleada-bowl-bot.git
cd baleada-bowl-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Fill in your values in .env

# Run
python bot.py
```

## Running with Docker

```bash
docker compose up -d --build
```

Logs:
```bash
docker compose logs -f
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Bot token from Discord Developer Portal |
| `LEAGUE_ID` | Sleeper league ID (from the league URL) |
| `SCORES_CHANNEL_ID` | Discord channel ID for live score updates |
| `TRANSACTIONS_CHANNEL_ID` | Discord channel ID for transaction alerts |
| `REMINDERS_CHANNEL_ID` | Discord channel ID for lineup warnings and penalties |
| `NFL_SEASON` | Current NFL season year (e.g. `2026`) |

---

## Key Design Decisions

- **Polling over WebSockets** — Sleeper's public API is REST-only for fantasy data. Polling every 60s for scores and 120s for transactions stays well within rate limits while keeping updates timely.
- **SQLite over a hosted DB** — The data volume (one league, one season) doesn't justify a hosted database. SQLite in a Docker volume is simpler, faster, and free.
- **Player cache** — The Sleeper `/players/nfl` endpoint returns ~10MB. It's fetched once at startup and refreshed every 24 hours rather than on every transaction lookup.
- **Game window detection** — The scores loop runs every 60 seconds all week but only posts to Discord during active NFL game windows, avoiding noise during off-hours.
