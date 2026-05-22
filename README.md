# RebusServer

Telegram bot for hosting rebus puzzle games in group chats.  
100 puzzles included. Games run per-group with 2–7 players.

## Deploy on Railway

### 1. Create a Telegram Bot
1. Open [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy your **bot token**

### 2. Deploy to Railway
1. Go to [railway.app](https://railway.app) and create a new project
2. Choose **"Deploy from GitHub repo"** (push this folder as a repo)  
   — OR — choose **"Empty project → New Service → Deploy from local"**
3. Set environment variable:
   - `TELEGRAM_BOT_TOKEN` = your bot token from BotFather
4. Railway auto-detects Python. If it doesn't, set the start command:
   ```
   python bot.py
   ```

### 3. Persistent Storage (important!)
Railway's filesystem resets on every deploy. To keep your stats database:
- Add a **Volume** in your Railway service settings, mounted at `/app`  
  and update `DB_PATH` in `bot.py` to `/app/rebus_stats.db`
- OR use Railway's PostgreSQL plugin (requires code changes)

Without a volume, stats reset on each redeploy — the bot still works fine.

### Files required in the same folder
```
bot.py
requirements.txt
rebus-puzzles.pdf      ← the puzzle PDF (included)
```

The `puzzles/` folder is created automatically on first startup.

---

## Bot Commands

| Command | Description |
|---|---|
| `/newgame` | Open a game lobby in this group |
| `/join` | Join the current lobby |
| `/startgame` | Start the game (host only, 2–7 players) |
| `/endgame` | End the game early (host or admin) |
| `/scores` | Show live scores during a game |
| `/leaderboard` | All-time leaderboard |
| `/mystats` | Your personal all-time stats |

## Game Rules
- Up to **20 puzzles** per game (randomly chosen from 100)
- **First** player to type the correct answer earns **1 point**
- **60 seconds** to answer before the bot reveals the answer and moves on
- Player with the most points at the end wins
- All-time stats: games played, games won, puzzles solved, total points
- Works simultaneously in multiple group chats
