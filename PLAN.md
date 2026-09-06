# Sleeper Fantasy Discord Bot — Implementation Plan

## Overview

A Discord bot that connects to the Sleeper Fantasy Football API to deliver:
- Live matchup scores (updated every ~60s during game windows)
- Waiver claim, free agent add, and trade notifications
- Slash commands for on-demand info (scores, standings, roster, transactions)

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.11+ | Clean async support, great Discord library |
| Discord library | discord.py 2.x | Slash commands, tasks loop, embeds |
| HTTP client | aiohttp | Async, pairs well with discord.py |
| Persistence | SQLite via aiosqlite | Track seen transactions, cache player names |
| Env config | python-dotenv | Keep secrets out of code |
| Hosting | Railway (recommended) | Simple, free tier, env var support |

---

## Sleeper API Reference

Base URL: `https://api.sleeper.app/v1`  
**No authentication required** for public leagues.

| Endpoint | Purpose |
|---|---|
| `GET /league/{league_id}` | League metadata, scoring settings, current week |
| `GET /league/{league_id}/users` | Manager display names and avatar |
| `GET /league/{league_id}/rosters` | Roster → owner_id mapping |
| `GET /league/{league_id}/matchups/{week}` | Live matchup scores and player points |
| `GET /league/{league_id}/transactions/{week}` | Waivers, FA adds, trades |
| `GET /players/nfl` | Full player name/position lookup (~10MB — cache daily) |
| `GET /stats/nfl/regular/{season}/{week}` | Detailed per-player stats |

### Finding Your League ID
- Open Sleeper → your league page — the URL contains it: `sleeper.com/leagues/{league_id}`
- Or via API: `GET /user/{username}/leagues/nfl/2025`

---

## Bot Features

### 1. Live Score Updates
- Poll `/matchups/{week}` every **60 seconds** during active NFL game windows
- Game windows (ET): Sun 1pm–Mon 2am, Thu 8pm–Fri 1am, Mon/Sat 8pm–next 1am
- Detect score changes ≥ 0.1 pts since last poll → post update embed to `#live-scores`
- Post a **full matchup summary** at the end of each game window

### 2. Transaction Alerts
- Poll `/transactions/{week}` every **2 minutes**, all week
- Persist seen transaction IDs in SQLite to avoid duplicate posts
- On new transaction post to `#transactions`:
  - **Waiver/FA Add**: "🔄 [Manager] added [Player] / dropped [Player]"
  - **Trade**: "🤝 [Manager A] ↔ [Manager B]: [assets exchanged]"

### 3. Slash Commands

| Command | Description |
|---|---|
| `/scores` | Current week matchup scores for all games |
| `/standings` | League standings (wins/losses/points) |
| `/roster [manager]` | View a manager's current roster |
| `/transactions [week]` | Last 5 transactions (defaults to current week) |
| `/matchup [manager]` | Detailed breakdown of a manager's current matchup |

---

## Project Structure

```
nfl-fantasy-bot/
├── bot.py                  # Entry point — bot init, cog loading
├── config.py               # Load and validate env vars
├── sleeper/
│   ├── __init__.py
│   ├── api.py              # Async Sleeper API client (all HTTP calls here)
│   └── models.py           # Dataclasses: Matchup, Transaction, Roster, Player
├── cogs/
│   ├── scores.py           # Live score polling loop + /scores + /matchup commands
│   ├── transactions.py     # Transaction polling loop + /transactions command
│   └── general.py          # /standings, /roster, utility commands
├── db/
│   └── storage.py          # SQLite schema, seen-transaction tracking, player cache
├── utils/
│   └── embeds.py           # Reusable Discord embed builders
├── .env                    # Secrets (never commit)
├── requirements.txt
└── PLAN.md                 # This file
```

---

## Implementation Phases

### Phase 1 — Foundation
- [ ] Create Discord bot application at discord.com/developers  ← **you do this**
- [ ] Copy bot token + channel IDs → `.env` (copy from `.env.example`)  ← **you do this**
- [ ] `pip install -r requirements.txt`  ← **you do this**
- [x] Build `sleeper/api.py` — async wrapper for all needed endpoints
- [x] Build `sleeper/models.py` — typed dataclasses for API responses
- [x] Build `db/storage.py` — SQLite init, seen-transaction helpers, player name cache
- [x] Wire `bot.py` with basic `/ping` command to confirm bot connects

### Phase 2 — Transaction Alerts
- [x] Implement `cogs/transactions.py` polling loop (2-min interval via `tasks.loop`)
- [x] Parse `"waiver"`, `"free_agent"`, and `"trade"` transaction types
- [x] Resolve owner_id → display name via `/users` + `/rosters`
- [x] Resolve player_id → player name via cached `/players/nfl`
- [x] Format and post embed to `#transactions` channel
- [x] Persist seen transaction IDs — no duplicate posts on restart

### Phase 3 — Live Scores
- [x] Implement `cogs/scores.py` polling loop (60-sec interval)
- [x] Add game window detection (check current ET time against schedule)
- [x] Store last-known scores per matchup in SQLite
- [x] Post score-change embed to `#live-scores` when any matchup changes
- [x] Post end-of-window full summary embed

### Phase 4 — Slash Commands
- [x] `/scores` — format all current matchups as embed
- [x] `/standings` — sort rosters by wins then points
- [x] `/matchup [manager]` — show manager's matchup with player-level breakdown
- [x] `/roster [manager]` — list starters and bench with last-week points
- [x] `/transactions [week]` — list recent transactions

### Phase 5 — Polish & Deploy
- [x] Retry logic for Sleeper API failures (3 attempts, exponential backoff)
- [x] Graceful handling of bye weeks and off-season (null matchup_id guard)
- [x] Logging to file for debugging (bot.log, rotating 1MB, 3 backups)
- [x] Daily player cache refresh (24h task loop)
- [ ] Deploy to Railway — deferred, doing later
- [ ] Test all features through a full game window

---

## Configuration (`.env`)

```env
DISCORD_TOKEN=your_bot_token_here
LEAGUE_ID=your_sleeper_league_id_here

# Channel IDs (right-click channel in Discord → Copy ID)
SCORES_CHANNEL_ID=
TRANSACTIONS_CHANNEL_ID=

# Season config
NFL_SEASON=2025
```

---

## Key Implementation Notes

- **Player cache**: `/players/nfl` is ~10MB. Fetch once at startup, store in SQLite, refresh once daily. Never fetch per-transaction.
- **Rate limits**: Sleeper is generous (~1000 req/min) but polling every 60s for scores + 120s for transactions is well within safe limits.
- **No WebSocket**: Sleeper has no fantasy data WebSocket — polling is the correct and intended approach.
- **Transaction status**: Only process transactions with `status: "complete"` — ignore `"pending"` waiver claims.
- **Week detection**: Use `league.settings.leg` (current week) from the league endpoint, not hardcoded dates.
- **owner_id mapping**: Build a dict `{owner_id: display_name}` from `/users` + `/rosters` at startup and refresh weekly.

---

## Discord Bot Setup Steps

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. New Application → name it (e.g. "Fantasy Bot")
3. Bot → Add Bot → copy token → paste into `.env`
4. Bot → enable **Message Content Intent** and **Server Members Intent**
5. OAuth2 → URL Generator → scopes: `bot`, `applications.commands`
6. Bot Permissions: Send Messages, Embed Links, Read Message History
7. Copy generated URL → open in browser → add bot to your server
8. Right-click your `#live-scores` and `#transactions` channels → Copy ID → paste into `.env`

---

## Status

**Current phase**: Not started — ready to begin Phase 1
