#!/usr/bin/env python3
"""
RebusServer — Telegram bot for hosting rebus puzzle games in group chats.

Setup for Railway:
  1. Set environment variable: TELEGRAM_BOT_TOKEN
  2. Place the PDF as "rebus-puzzles.pdf" in the same directory as this file.
  3. Deploy — puzzle images are extracted automatically on first run.

Commands:
  /newgame      — Open a game lobby in this chat
  /join         — Join the current lobby
  /startgame    — Start the game (host only, 2–7 players needed)
  /endgame      — End the current game (host or admin)
  /scores       — Show current in-game scores
  /leaderboard  — All-time leaderboard
  /mystats      — Your personal all-time stats
"""

import asyncio
import io
import logging
import os
import random
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import fitz  # PyMuPDF
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("RebusServer")

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
TOKEN = os.environ["8602527499:AAFADROr5RLTIGtAltsb12hldQNTCGFAo1I"]
DB_PATH = "rebus_stats.db"
PDF_PATH = "rebus-puzzles.pdf"
PUZZLES_DIR = Path("puzzles")

PUZZLES_PER_GAME = 20   # number of puzzles drawn per game session
ANSWER_TIMEOUT = 60     # seconds before moving to next puzzle
MIN_PLAYERS = 2
MAX_PLAYERS = 7

# ──────────────────────────────────────────────────────────────────────────────
# All 100 answers (from the answer-key pages of the PDF).
# Each key maps to a list of accepted answers (all lower-case).
# Matching is case-insensitive and ignores hyphens/apostrophes.
# ──────────────────────────────────────────────────────────────────────────────
ANSWERS: Dict[int, List[str]] = {
    1:   ["forget it"],
    2:   ["try to understand"],
    3:   ["travel overseas", "overseas travel"],
    4:   ["downtown"],
    5:   ["eyeshadow", "eye shadow"],
    6:   ["stepfather", "step father"],
    7:   ["potatoes"],
    8:   ["3d movie"],
    9:   ["top secret"],
    10:  ["lemonade"],
    11:  ["long legs"],
    12:  ["big bad wolf"],
    13:  ["many thanks", "thanks a lot"],
    14:  ["download"],
    15:  ["spaceman", "space man"],
    16:  ["no idea"],
    17:  ["comfortable"],
    18:  ["forty years"],
    19:  ["excuse me"],
    20:  ["forehead"],
    21:  ["good looking"],
    22:  ["waterfall", "water fall"],
    23:  ["wake up"],
    24:  ["tuna fish", "tunafish"],
    25:  ["foreign language"],
    26:  ["middle aged", "middle-aged"],
    27:  ["broken heart"],
    28:  ["seesaw", "see saw"],
    29:  ["miss you", "missing you"],
    30:  ["teabag", "tea bag"],
    31:  ["four wheel drive", "four-wheel drive"],
    32:  ["apple pie"],
    33:  ["up to you"],
    34:  ["robin hood"],
    35:  ["engineer"],
    36:  ["vegetables"],
    37:  ["afternoon tea"],
    38:  ["camping overnight"],
    39:  ["broken heart"],
    40:  ["time to go"],
    41:  ["long time no see"],
    42:  ["polite"],
    43:  ["touchdown", "touch down"],
    44:  ["honeybee", "honey bee"],
    45:  ["cornerstone", "corner stone"],
    46:  ["love at first sight"],
    47:  ["catwalk", "cat walk"],
    48:  ["hiking in the woods"],
    49:  ["sandbox", "sand box"],
    50:  ["lovebirds", "love birds"],
    51:  ["crossbow", "cross bow"],
    52:  ["eggs over easy"],
    53:  ["multiple choice"],
    54:  ["come into season"],
    55:  ["ill get over it", "i'll get over it"],
    56:  ["im bigger than you", "i'm bigger than you"],
    57:  ["illegal"],
    58:  ["double agent"],
    59:  ["rock n roll", "rock and roll", "rock n' roll"],
    60:  ["good afternoon"],
    61:  ["look me in the eye"],
    62:  ["electric blanket"],
    63:  ["banknote", "bank note"],
    64:  ["bookcase", "book case"],
    65:  ["five kilograms overweight", "5 kilograms overweight",
          "five kg overweight", "5kg overweight"],
    66:  ["highway", "high way"],
    67:  ["way to go"],
    68:  ["sunroof", "sun roof"],
    69:  ["pardon me"],
    70:  ["turnip"],
    71:  ["uproar"],
    72:  ["thunderstorm", "thunder storm"],
    73:  ["microscope"],
    74:  ["headquarters", "head quarters"],
    75:  ["blanket"],
    76:  ["cut corners"],
    77:  ["cocktail", "cock tail"],
    78:  ["tennis shoes"],
    79:  ["summary"],
    80:  ["foul language"],
    81:  ["summer"],
    82:  ["mutate"],
    83:  ["indian food"],
    84:  ["the underdog", "underdog"],
    85:  ["seasoning"],
    86:  ["easel"],
    87:  ["discount"],
    88:  ["keep your eyes on the ball"],
    89:  ["fortunate"],
    90:  ["tripod"],
    91:  ["sweet tooth"],
    92:  ["a bone to pick", "bone to pick"],
    93:  ["fingers crossed"],
    94:  ["sixth sense"],
    95:  ["on second thought"],
    96:  ["sleep on it"],
    97:  ["jockey for position"],
    98:  ["door to door"],
    99:  ["be on time"],
    100: ["noodles"],
}

# ──────────────────────────────────────────────────────────────────────────────
# Database
# ──────────────────────────────────────────────────────────────────────────────

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS player_stats (
                user_id       INTEGER PRIMARY KEY,
                display_name  TEXT    NOT NULL DEFAULT '',
                username      TEXT    NOT NULL DEFAULT '',
                games_played  INTEGER NOT NULL DEFAULT 0,
                puzzles_solved INTEGER NOT NULL DEFAULT 0,
                games_won     INTEGER NOT NULL DEFAULT 0,
                total_points  INTEGER NOT NULL DEFAULT 0
            )
        """)
        con.commit()


def upsert_player(user_id: int, display_name: str, username: str) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO player_stats (user_id, display_name, username)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name = excluded.display_name,
                username     = excluded.username
            """,
            (user_id, display_name, username),
        )
        con.commit()


def record_game_result(
    user_id: int,
    puzzles_solved: int,
    won: bool,
    points: int,
) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            UPDATE player_stats
            SET games_played   = games_played  + 1,
                puzzles_solved = puzzles_solved + ?,
                games_won      = games_won      + ?,
                total_points   = total_points   + ?
            WHERE user_id = ?
            """,
            (puzzles_solved, 1 if won else 0, points, user_id),
        )
        con.commit()


def get_leaderboard(limit: int = 10) -> list:
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            """
            SELECT display_name, games_played, puzzles_solved, games_won, total_points
            FROM player_stats
            ORDER BY total_points DESC, games_won DESC, puzzles_solved DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return rows


def get_player_stats(user_id: int) -> Optional[tuple]:
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT games_played, puzzles_solved, games_won, total_points "
            "FROM player_stats WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return row

# ──────────────────────────────────────────────────────────────────────────────
# Puzzle image extraction
# ──────────────────────────────────────────────────────────────────────────────

def setup_puzzles() -> None:
    """
    Extract individual puzzle-cell images from the PDF (pages 1–8).
    Each page has a 3-column × 4-row grid of puzzles.
    Puzzles 97–100 have no image in the PDF; they are handled as text hints.
    Skips extraction if the images are already present.
    """
    PUZZLES_DIR.mkdir(exist_ok=True)
    existing = sorted(PUZZLES_DIR.glob("puzzle_???.png"))
    if len(existing) >= 96:
        logger.info("Puzzle images already present (%d found).", len(existing))
        return

    if not Path(PDF_PATH).exists():
        logger.error(
            "PDF not found at '%s'. Place the rebus PDF beside bot.py and restart.", PDF_PATH
        )
        return

    logger.info("Extracting puzzle images from '%s'…", PDF_PATH)
    doc = fitz.open(PDF_PATH)

    # PDF page dimensions: ~593 × 839 pts (A4-ish)
    # Pages 0-7 (PDF pages 1-8) contain the puzzle grids.
    # Header "Rebus Puzzles / www…" occupies ~82 pts at the top.
    HEADER_H: float = 82.0
    MARGIN_X: float = 3.0
    MARGIN_Y: float = 3.0
    COLS = 3
    ROWS = 4
    RENDER_SCALE = 2.5  # render at ~180 DPI for sharp images

    puzzle_num = 0
    for page_idx in range(8):
        page = doc[page_idx]
        pw = page.rect.width
        ph = page.rect.height

        cell_w = (pw - 2 * MARGIN_X) / COLS
        cell_h = (ph - HEADER_H - MARGIN_Y) / ROWS

        for row in range(ROWS):
            for col in range(COLS):
                puzzle_num += 1
                if puzzle_num > 96:
                    break

                x0 = MARGIN_X + col * cell_w
                y0 = HEADER_H + row * cell_h
                rect = fitz.Rect(x0 + 1, y0 + 1, x0 + cell_w - 1, y0 + cell_h - 1)
                mat = fitz.Matrix(RENDER_SCALE, RENDER_SCALE)
                pix = page.get_pixmap(matrix=mat, clip=rect)
                out_path = PUZZLES_DIR / f"puzzle_{puzzle_num:03d}.png"
                pix.save(str(out_path))

    logger.info("Extracted %d puzzle images into '%s/'.", puzzle_num, PUZZLES_DIR)


def get_puzzle_image(puzzle_num: int) -> Optional[bytes]:
    """Return image bytes for puzzle_num, or None if unavailable (97-100)."""
    path = PUZZLES_DIR / f"puzzle_{puzzle_num:03d}.png"
    if path.exists():
        return path.read_bytes()
    return None

# ──────────────────────────────────────────────────────────────────────────────
# Answer checking
# ──────────────────────────────────────────────────────────────────────────────

_STRIP_RE = re.compile(r"['\-]")
_SPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = _STRIP_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def check_answer(puzzle_num: int, user_text: str) -> bool:
    norm = _normalize(user_text)
    for accepted in ANSWERS.get(puzzle_num, []):
        if _normalize(accepted) == norm:
            return True
    return False

# ──────────────────────────────────────────────────────────────────────────────
# Game state
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class GameState:
    chat_id: int
    host_id: int
    host_name: str
    # user_id → display name
    players: Dict[int, str] = field(default_factory=dict)
    # user_id → score this game
    scores: Dict[int, int] = field(default_factory=dict)
    # "lobby" | "playing" | "finished"
    status: str = "lobby"
    # ordered list of puzzle numbers for this game
    puzzle_queue: List[int] = field(default_factory=list)
    # index into puzzle_queue
    current_puzzle_idx: int = 0
    # puzzle numbers already solved in this game session
    solved: Set[int] = field(default_factory=set)
    # PTB job queue handle for the current puzzle timeout
    timeout_job: Optional[Any] = None


# chat_id → GameState
games: Dict[int, GameState] = {}

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def medal(rank: int) -> str:
    return ("🥇", "🥈", "🥉")[rank] if rank < 3 else f"{rank + 1}."


def scores_text(state: GameState) -> str:
    sorted_scores = sorted(state.scores.items(), key=lambda kv: kv[1], reverse=True)
    lines = []
    for rank, (uid, pts) in enumerate(sorted_scores):
        name = state.players.get(uid, "?")
        lines.append(f"{medal(rank)} {name} — {pts} pt{'s' if pts != 1 else ''}")
    return "\n".join(lines) if lines else "No scores yet."


def join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✋ Join Game", callback_data="join_game")]])

# ──────────────────────────────────────────────────────────────────────────────
# Game engine
# ──────────────────────────────────────────────────────────────────────────────

async def send_next_puzzle(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    state = games.get(chat_id)
    if not state or state.status != "playing":
        return

    idx = state.current_puzzle_idx
    total = len(state.puzzle_queue)

    if idx >= total:
        await finish_game(context, chat_id)
        return

    puzzle_num = state.puzzle_queue[idx]
    state.solved.discard(puzzle_num)

    caption = (
        f"🧩 <b>Puzzle {idx + 1} / {total}</b>\n"
        f"First correct answer earns a point!  ⏱ {ANSWER_TIMEOUT}s"
    )

    img_bytes = get_puzzle_image(puzzle_num)
    if img_bytes:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=io.BytesIO(img_bytes),
            caption=caption,
            parse_mode="HTML",
        )
    else:
        # Puzzles 97-100: no image in PDF — show a text hint instead
        hint_map = {
            97:  "🤔  <i>Jockey _ _ _ position</i>",
            98:  "🤔  <i>Door _ _ Door</i>",
            99:  "🤔  <i>Be _ _ time</i>",
            100: "🤔  <i>_ _ _ _ _ _ _</i>  (a food, 7 letters)",
        }
        hint = hint_map.get(puzzle_num, f"Puzzle #{puzzle_num}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{caption}\n\n{hint}",
            parse_mode="HTML",
        )

    # Cancel any previous timeout job
    if state.timeout_job:
        state.timeout_job.schedule_removal()
        state.timeout_job = None

    # Schedule new timeout
    state.timeout_job = context.job_queue.run_once(
        _puzzle_timeout_job,
        when=ANSWER_TIMEOUT,
        data={"chat_id": chat_id, "puzzle_num": puzzle_num, "puzzle_idx": idx},
        name=f"timeout_{chat_id}",
    )


async def _puzzle_timeout_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    chat_id = data["chat_id"]
    puzzle_num = data["puzzle_num"]
    puzzle_idx = data["puzzle_idx"]

    state = games.get(chat_id)
    if not state or state.status != "playing":
        return
    if state.current_puzzle_idx != puzzle_idx:
        return
    if puzzle_num in state.solved:
        return

    # Nobody solved it in time
    answer_display = " / ".join(a.title() for a in ANSWERS.get(puzzle_num, ["?"])[:2])
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏰ <b>Time's up!</b>  The answer was: <b>{answer_display}</b>",
        parse_mode="HTML",
    )

    state.current_puzzle_idx += 1
    await asyncio.sleep(2)
    await send_next_puzzle(context, chat_id)


async def finish_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    state = games.get(chat_id)
    if not state:
        return

    state.status = "finished"
    if state.timeout_job:
        state.timeout_job.schedule_removal()
        state.timeout_job = None

    sorted_scores = sorted(state.scores.items(), key=lambda kv: kv[1], reverse=True)
    top_score = sorted_scores[0][1] if sorted_scores else 0
    winners = [uid for uid, pts in sorted_scores if pts == top_score and pts > 0]

    lines = ["🏆 <b>Game Over!  Final Scores:</b>\n"]
    for rank, (uid, pts) in enumerate(sorted_scores):
        name = state.players.get(uid, "?")
        lines.append(f"{medal(rank)} <b>{name}</b> — {pts} pt{'s' if pts != 1 else ''}")

    if winners:
        winner_names = " & ".join(state.players.get(uid, "?") for uid in winners)
        lines.append(f"\n🎊 <b>{'Tie! ' if len(winners) > 1 else ''}{winner_names} wins!</b>  Congratulations!")
    else:
        lines.append("\nNo one scored — better luck next time!")

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="HTML",
    )

    # Persist stats
    for uid, pts in sorted_scores:
        record_game_result(uid, puzzles_solved=pts, won=(uid in winners), points=pts)

    del games[chat_id]

# ──────────────────────────────────────────────────────────────────────────────
# Command handlers
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(
        "🧩 <b>RebusServer</b> — Rebus puzzle games for group chats!\n\n"
        "<b>How to play:</b>\n"
        "1. Use /newgame to open a lobby\n"
        "2. Players press <b>Join Game</b> or type /join\n"
        "3. Host types /startgame when 2–7 players are ready\n"
        "4. Bot sends puzzle images one by one\n"
        "5. First correct text answer earns 1 point\n"
        "6. Player with the most points wins!\n\n"
        "<b>Commands:</b>\n"
        "/newgame — Open a new lobby\n"
        "/join — Join the current lobby\n"
        "/startgame — Start the game (host only)\n"
        "/endgame — End the current game\n"
        "/scores — Scores during a game\n"
        "/leaderboard — All-time top players\n"
        "/mystats — Your personal stats"
    )


async def cmd_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id in games and games[chat_id].status != "finished":
        await update.message.reply_text(
            "⚠️ A game is already active!  Use /endgame to cancel it first."
        )
        return

    state = GameState(
        chat_id=chat_id,
        host_id=user.id,
        host_name=user.first_name,
        players={user.id: user.first_name},
        scores={user.id: 0},
    )
    games[chat_id] = state
    upsert_player(user.id, user.first_name, user.username or "")

    await update.message.reply_html(
        f"🎮 <b>{user.first_name}</b> opened a RebusServer game!\n\n"
        f"👥 Players (1/{MAX_PLAYERS}): <b>{user.first_name}</b>\n\n"
        f"Waiting for more players… (min {MIN_PLAYERS}, max {MAX_PLAYERS})\n"
        f"Press the button below or use /join, then /startgame when ready!",
        reply_markup=join_keyboard(),
    )


async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id not in games or games[chat_id].status == "finished":
        await update.message.reply_text("No active lobby.  Use /newgame to start one.")
        return

    state = games[chat_id]

    if state.status != "lobby":
        await update.message.reply_text("The game has already started!")
        return
    if user.id in state.players:
        await update.message.reply_text("You're already in the game! 👍")
        return
    if len(state.players) >= MAX_PLAYERS:
        await update.message.reply_text(f"Game is full ({MAX_PLAYERS} players max)!")
        return

    state.players[user.id] = user.first_name
    state.scores[user.id] = 0
    upsert_player(user.id, user.first_name, user.username or "")

    count = len(state.players)
    player_list = ", ".join(state.players.values())
    ready_line = (
        f"Waiting for {MIN_PLAYERS - count} more player(s)…"
        if count < MIN_PLAYERS
        else f"Ready! Host (<b>{state.host_name}</b>) can /startgame"
    )

    await update.message.reply_html(
        f"✅ <b>{user.first_name}</b> joined!\n\n"
        f"👥 Players ({count}/{MAX_PLAYERS}): {player_list}\n\n"
        f"{ready_line}",
        reply_markup=join_keyboard(),
    )


async def btn_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    user = query.from_user

    if chat_id not in games or games[chat_id].status == "finished":
        await query.answer("No active lobby.  Use /newgame to start one.", show_alert=True)
        return

    state = games[chat_id]

    if state.status != "lobby":
        await query.answer("The game has already started!", show_alert=True)
        return
    if user.id in state.players:
        await query.answer("You're already in the game! 👍", show_alert=True)
        return
    if len(state.players) >= MAX_PLAYERS:
        await query.answer(f"Game is full ({MAX_PLAYERS} players max)!", show_alert=True)
        return

    state.players[user.id] = user.first_name
    state.scores[user.id] = 0
    upsert_player(user.id, user.first_name, user.username or "")

    count = len(state.players)
    player_list = ", ".join(state.players.values())
    ready_line = (
        f"Waiting for {MIN_PLAYERS - count} more player(s)…"
        if count < MIN_PLAYERS
        else f"Ready! Host (<b>{state.host_name}</b>) can /startgame"
    )

    try:
        await query.edit_message_text(
            f"✅ <b>{user.first_name}</b> joined!\n\n"
            f"👥 Players ({count}/{MAX_PLAYERS}): {player_list}\n\n"
            f"{ready_line}",
            parse_mode="HTML",
            reply_markup=join_keyboard(),
        )
    except Exception:
        await context.bot.send_message(
            chat_id,
            f"✅ <b>{user.first_name}</b> joined! ({count}/{MAX_PLAYERS} players)",
            parse_mode="HTML",
        )


async def cmd_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id not in games:
        await update.message.reply_text("No lobby active.  Use /newgame first.")
        return

    state = games[chat_id]

    if state.status != "lobby":
        await update.message.reply_text("The game is already running!")
        return
    if user.id != state.host_id:
        await update.message.reply_text("Only the game host can start the game.")
        return
    if len(state.players) < MIN_PLAYERS:
        await update.message.reply_text(
            f"Need at least {MIN_PLAYERS} players.  Currently {len(state.players)}."
        )
        return

    # Build puzzle queue — random sample from all 100
    all_puzzles = list(range(1, 101))
    random.shuffle(all_puzzles)
    state.puzzle_queue = all_puzzles[:PUZZLES_PER_GAME]
    state.current_puzzle_idx = 0
    state.status = "playing"

    player_list = "\n".join(f"  • {name}" for name in state.players.values())
    await update.message.reply_html(
        f"🚀 <b>Game starting!</b>\n\n"
        f"👥 Players:\n{player_list}\n\n"
        f"📝 {PUZZLES_PER_GAME} puzzles  •  {ANSWER_TIMEOUT}s per puzzle\n"
        f"First correct answer scores a point.  Good luck!\n\n"
        f"<i>Get ready… 3… 2… 1…</i>"
    )

    await asyncio.sleep(3)
    await send_next_puzzle(context, chat_id)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state = games.get(chat_id)

    if not state or state.status != "playing":
        return

    user = update.effective_user
    if user.id not in state.players:
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    idx = state.current_puzzle_idx
    if idx >= len(state.puzzle_queue):
        return

    puzzle_num = state.puzzle_queue[idx]
    if puzzle_num in state.solved:
        return

    if not check_answer(puzzle_num, text):
        return

    # Correct answer!
    state.solved.add(puzzle_num)
    state.scores[user.id] = state.scores.get(user.id, 0) + 1

    if state.timeout_job:
        state.timeout_job.schedule_removal()
        state.timeout_job = None

    answer_display = ANSWERS[puzzle_num][0].title()
    await update.message.reply_html(
        f"✅ <b>{user.first_name}</b> got it!  <b>{answer_display}</b>  (+1 point) 🎉"
    )

    state.current_puzzle_idx += 1
    await asyncio.sleep(2)
    await send_next_puzzle(context, chat_id)


async def cmd_scores(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state = games.get(chat_id)

    if not state or state.status == "finished":
        await update.message.reply_text("No game is currently running.")
        return

    if state.status == "lobby":
        player_list = ", ".join(state.players.values())
        await update.message.reply_html(
            f"⏳ Lobby open — players: {player_list}\n"
            f"Waiting for /startgame"
        )
        return

    idx = state.current_puzzle_idx
    total = len(state.puzzle_queue)
    await update.message.reply_html(
        f"📊 <b>Scores — Puzzle {idx}/{total}</b>\n\n"
        + scores_text(state)
    )


async def cmd_endgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id not in games:
        await update.message.reply_text("No game running.")
        return

    state = games[chat_id]

    is_admin = False
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        is_admin = member.status in ("administrator", "creator")
    except Exception:
        pass

    if user.id != state.host_id and not is_admin:
        await update.message.reply_text("Only the host or a group admin can end the game.")
        return

    await update.message.reply_text("🛑 Game ended early.")

    if state.status == "playing":
        await finish_game(context, chat_id)
    else:
        state.status = "finished"
        if chat_id in games:
            del games[chat_id]


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = get_leaderboard(10)

    if not rows:
        await update.message.reply_text("No all-time stats yet.  Play a game first! 🎮")
        return

    lines = ["🏆 <b>All-Time Leaderboard</b>\n"]
    for rank, (name, played, solved, won, points) in enumerate(rows):
        lines.append(
            f"{medal(rank)} <b>{name}</b> — "
            f"{points} pts  |  {won}W / {played}G  |  {solved} puzzles solved"
        )

    await update.message.reply_html("\n".join(lines))


async def cmd_mystats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    upsert_player(user.id, user.first_name, user.username or "")
    row = get_player_stats(user.id)

    if not row or row[0] == 0:
        await update.message.reply_text(
            f"No stats yet for {user.first_name}.  Join a game and start playing! 🎮"
        )
        return

    played, solved, won, points = row
    win_rate = f"{won / played * 100:.0f}%" if played else "—"
    await update.message.reply_html(
        f"📊 <b>Stats — {user.first_name}</b>\n\n"
        f"🎮 Games played:    <b>{played}</b>\n"
        f"🏆 Games won:       <b>{won}</b>  ({win_rate} win rate)\n"
        f"🧩 Puzzles solved:  <b>{solved}</b>\n"
        f"⭐ Total points:    <b>{points}</b>"
    )

# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    init_db()
    setup_puzzles()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_start))
    app.add_handler(CommandHandler("newgame",     cmd_newgame))
    app.add_handler(CommandHandler("join",        cmd_join))
    app.add_handler(CommandHandler("startgame",   cmd_startgame))
    app.add_handler(CommandHandler("endgame",     cmd_endgame))
    app.add_handler(CommandHandler("scores",      cmd_scores))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("mystats",     cmd_mystats))
    app.add_handler(CallbackQueryHandler(btn_join, pattern="^join_game$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("RebusServer is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
