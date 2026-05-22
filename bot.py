#!/usr/bin/env python3
"""
RebusServer — Telegram bot for hosting rebus puzzle games in group chats.
Uses pyTelegramBotAPI (telebot), which works on Python 3.11–3.13.

Setup for Railway:
  1. Set environment variable: TELEGRAM_BOT_TOKEN  (or BOT_TOKEN or TOKEN)
  2. Place "rebus-puzzles.pdf" AND "rebus-puzzles-2.pdf" in the same directory.
  3. Deploy — puzzle images are extracted automatically on first run.

Commands:
  /newgame      — Open a game lobby (host picks round count 10–20)
  /join         — Join the current lobby
  /startgame    — Start the game (host only, 2–7 players needed)
  /endgame      — End the current game (host or admin; points already earned are saved)
  /scores       — Show in-game scores on demand
  /leaderboard  — All-time leaderboard
  /mystats      — Your personal all-time stats
"""

import io
import logging
import os
import random
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

import fitz  # PyMuPDF
import telebot
from telebot import types

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
TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("BOT_TOKEN")
    or os.environ.get("TOKEN")
)
if not TOKEN:
    raise SystemExit(
        "\n\n"
        "  ╔══════════════════════════════════════════════════════════════╗\n"
        "  ║  MISSING BOT TOKEN                                           ║\n"
        "  ║                                                              ║\n"
        "  ║  In Railway → your service → Variables, add:                ║\n"
        "  ║    Name:  TELEGRAM_BOT_TOKEN                                 ║\n"
        "  ║    Value: your token from @BotFather                         ║\n"
        "  ║                                                              ║\n"
        "  ║  Do NOT edit this line in bot.py.                            ║\n"
        "  ╚══════════════════════════════════════════════════════════════╝\n"
    )

DB_PATH      = "rebus_stats.db"
PDF_PATH     = "rebus-puzzles.pdf"       # Pack 1 — puzzles 1–96
PDF2_PATH    = "rebus-puzzles-2.pdf"     # Pack 2 — puzzles 101–196
PUZZLES_DIR  = Path("puzzles")

ANSWER_TIMEOUT  = 60    # seconds per puzzle before moving on
MIN_PLAYERS     = 2
MAX_PLAYERS     = 7
ROUND_CHOICES   = [10, 12, 15, 18, 20]  # available game lengths

# ──────────────────────────────────────────────────────────────────────────────
# Answer table  (100 unique answers; puzzles 101–200 reuse the same keys)
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

# Text hints for puzzles that have no image (97–100 in each pack)
TEXT_HINTS: Dict[int, str] = {
    97:  "🤔 <i>Jockey _ _ _ position</i>",
    98:  "🤔 <i>Door _ _ Door</i>",
    99:  "🤔 <i>Be _ _ time</i>",
    100: "🤔 <i>_ _ _ _ _ _ _</i>  (a food, 7 letters)",
}


def _answer_key(puzzle_num: int) -> int:
    """Map any puzzle number (1–200) to the canonical answer key (1–100)."""
    return ((puzzle_num - 1) % 100) + 1


# ──────────────────────────────────────────────────────────────────────────────
# Database
# ──────────────────────────────────────────────────────────────────────────────

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS player_stats (
                user_id        INTEGER PRIMARY KEY,
                display_name   TEXT    NOT NULL DEFAULT '',
                username       TEXT    NOT NULL DEFAULT '',
                games_played   INTEGER NOT NULL DEFAULT 0,
                puzzles_solved INTEGER NOT NULL DEFAULT 0,
                games_won      INTEGER NOT NULL DEFAULT 0,
                total_points   INTEGER NOT NULL DEFAULT 0
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


def record_game_result(user_id: int, puzzles_solved: int, won: bool, points: int) -> None:
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
        return con.execute(
            """
            SELECT display_name, games_played, puzzles_solved, games_won, total_points
            FROM player_stats
            ORDER BY total_points DESC, games_won DESC, puzzles_solved DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def get_player_stats(user_id: int) -> Optional[tuple]:
    with sqlite3.connect(DB_PATH) as con:
        return con.execute(
            "SELECT games_played, puzzles_solved, games_won, total_points "
            "FROM player_stats WHERE user_id = ?",
            (user_id,),
        ).fetchone()

# ──────────────────────────────────────────────────────────────────────────────
# Puzzle image extraction
# ──────────────────────────────────────────────────────────────────────────────

def _extract_pack(pdf_path: str, start_num: int) -> None:
    """
    Extract 96 puzzle-cell images from one PDF (pages 1–8, 3×4 grid).
    Images are saved as puzzle_{start_num:03d}.png … puzzle_{start_num+95:03d}.png.
    """
    logger.info("Extracting images from '%s' (puzzles %d–%d)…",
                pdf_path, start_num, start_num + 95)
    doc = fitz.open(pdf_path)

    HEADER_H: float = 82.0
    MARGIN_X: float = 3.0
    MARGIN_Y: float = 3.0
    COLS, ROWS = 3, 4
    SCALE = 2.5   # ~180 DPI

    offset = 0
    for page_idx in range(8):
        if offset >= 96:
            break
        page = doc[page_idx]
        pw, ph = page.rect.width, page.rect.height
        cell_w = (pw - 2 * MARGIN_X) / COLS
        cell_h = (ph - HEADER_H - MARGIN_Y) / ROWS

        for row in range(ROWS):
            for col in range(COLS):
                if offset >= 96:
                    break
                offset += 1
                puzzle_num = start_num + offset - 1
                x0 = MARGIN_X + col * cell_w
                y0 = HEADER_H + row * cell_h
                rect = fitz.Rect(x0 + 1, y0 + 1, x0 + cell_w - 1, y0 + cell_h - 1)
                pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), clip=rect)
                pix.save(str(PUZZLES_DIR / f"puzzle_{puzzle_num:03d}.png"))

    logger.info("Saved %d images starting at puzzle_%03d.", offset, start_num)


def setup_puzzles() -> None:
    PUZZLES_DIR.mkdir(exist_ok=True)

    # Pack 1: puzzles 1–96
    pack1_done = sum(1 for i in range(1, 97) if (PUZZLES_DIR / f"puzzle_{i:03d}.png").exists())
    if pack1_done < 96:
        if Path(PDF_PATH).exists():
            _extract_pack(PDF_PATH, start_num=1)
        else:
            logger.warning("Pack-1 PDF '%s' not found — pack-1 images unavailable.", PDF_PATH)
    else:
        logger.info("Pack-1 images already present (%d/96).", pack1_done)

    # Pack 2: puzzles 101–196
    pack2_done = sum(1 for i in range(101, 197) if (PUZZLES_DIR / f"puzzle_{i:03d}.png").exists())
    if pack2_done < 96:
        if Path(PDF2_PATH).exists():
            _extract_pack(PDF2_PATH, start_num=101)
        else:
            logger.warning("Pack-2 PDF '%s' not found — pack-2 images unavailable.", PDF2_PATH)
    else:
        logger.info("Pack-2 images already present (%d/96).", pack2_done)


def get_puzzle_image(puzzle_num: int) -> Optional[bytes]:
    path = PUZZLES_DIR / f"puzzle_{puzzle_num:03d}.png"
    return path.read_bytes() if path.exists() else None


def available_puzzle_pool() -> List[int]:
    """Return all puzzle numbers that are either an image or a text hint."""
    pool: List[int] = []
    for n in list(range(1, 101)) + list(range(101, 201)):
        key = _answer_key(n)
        if key in TEXT_HINTS:          # 97-100 and 197-200 always available
            pool.append(n)
        elif (PUZZLES_DIR / f"puzzle_{n:03d}.png").exists():
            pool.append(n)
    return pool

# ──────────────────────────────────────────────────────────────────────────────
# Answer checking
# ──────────────────────────────────────────────────────────────────────────────

_STRIP  = re.compile(r"['\-]")
_SPACES = re.compile(r"\s+")


def _norm(text: str) -> str:
    text = _STRIP.sub(" ", text.lower().strip())
    return _SPACES.sub(" ", text).strip()


def check_answer(puzzle_num: int, user_text: str) -> bool:
    key = _answer_key(puzzle_num)
    n = _norm(user_text)
    return any(_norm(a) == n for a in ANSWERS.get(key, []))

# ──────────────────────────────────────────────────────────────────────────────
# Game state
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class GameState:
    chat_id:   int
    host_id:   int
    host_name: str
    rounds:    int = 20                                      # chosen game length
    players:   Dict[int, str] = field(default_factory=dict) # user_id → name
    scores:    Dict[int, int] = field(default_factory=dict) # user_id → points
    # status: choosing → lobby → playing → finished
    status:           str = "choosing"
    puzzle_queue:     List[int] = field(default_factory=list)
    current_puzzle_idx: int = 0
    solved:           Set[int] = field(default_factory=set)
    timeout_timer:    Optional[threading.Timer] = None
    lock:             threading.Lock = field(default_factory=threading.Lock)


games:      Dict[int, GameState] = {}
games_lock: threading.Lock = threading.Lock()

# ──────────────────────────────────────────────────────────────────────────────
# Bot instance
# ──────────────────────────────────────────────────────────────────────────────
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ──────────────────────────────────────────────────────────────────────────────
# UI helpers
# ──────────────────────────────────────────────────────────────────────────────

def rounds_markup() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=5)
    kb.add(*[
        types.InlineKeyboardButton(f"{r} rounds", callback_data=f"rounds_{r}")
        for r in ROUND_CHOICES
    ])
    return kb


def join_markup() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✋ Join Game", callback_data="join_game"))
    return kb


def medal(rank: int) -> str:
    return ("🥇", "🥈", "🥉")[rank] if rank < 3 else f"{rank + 1}."


def scores_text(state: GameState, *, label: str = "📊 Current Scores") -> str:
    rows = sorted(state.scores.items(), key=lambda kv: kv[1], reverse=True)
    lines = [f"<b>{label}</b>"]
    for rank, (uid, pts) in enumerate(rows):
        name = state.players.get(uid, "?")
        lines.append(f"{medal(rank)} {name} — {pts} pt{'s' if pts != 1 else ''}")
    return "\n".join(lines)


def post_scores(chat_id: int, state: GameState, label: str = "📊 Current Scores") -> None:
    """Send a live scoreboard to the chat."""
    try:
        bot.send_message(chat_id, scores_text(state, label=label))
    except Exception as exc:
        logger.warning("Could not post scores: %s", exc)

# ──────────────────────────────────────────────────────────────────────────────
# Game engine
# ──────────────────────────────────────────────────────────────────────────────

def _cancel_timer(state: GameState) -> None:
    if state.timeout_timer:
        state.timeout_timer.cancel()
        state.timeout_timer = None


def send_next_puzzle(chat_id: int) -> None:
    with games_lock:
        state = games.get(chat_id)
    if not state:
        return

    with state.lock:
        if state.status != "playing":
            return
        idx   = state.current_puzzle_idx
        total = len(state.puzzle_queue)

    if idx >= total:
        finish_game(chat_id)
        return

    puzzle_num = state.puzzle_queue[idx]
    with state.lock:
        state.solved.discard(puzzle_num)

    caption = (
        f"🧩 <b>Puzzle {idx + 1} / {total}</b>\n"
        f"First correct answer earns a point!  ⏱ {ANSWER_TIMEOUT}s"
    )

    img = get_puzzle_image(puzzle_num)
    if img:
        bot.send_photo(chat_id, photo=io.BytesIO(img), caption=caption)
    else:
        key  = _answer_key(puzzle_num)
        hint = TEXT_HINTS.get(key, "")
        bot.send_message(chat_id, f"{caption}\n\n{hint}")

    with state.lock:
        _cancel_timer(state)
        timer = threading.Timer(
            ANSWER_TIMEOUT, _on_timeout, args=[chat_id, puzzle_num, idx]
        )
        timer.daemon = True
        state.timeout_timer = timer
        timer.start()


def _on_timeout(chat_id: int, puzzle_num: int, puzzle_idx: int) -> None:
    with games_lock:
        state = games.get(chat_id)
    if not state:
        return

    with state.lock:
        if state.status != "playing":
            return
        if state.current_puzzle_idx != puzzle_idx:
            return
        if puzzle_num in state.solved:
            return
        state.current_puzzle_idx += 1

    key            = _answer_key(puzzle_num)
    answer_display = " / ".join(a.title() for a in ANSWERS.get(key, ["?"])[:2])
    bot.send_message(
        chat_id,
        f"⏰ <b>Time's up!</b>  The answer was: <b>{answer_display}</b>",
    )

    # Show live scoreboard
    post_scores(chat_id, state)

    time.sleep(2)
    send_next_puzzle(chat_id)


def finish_game(chat_id: int, early: bool = False) -> None:
    """
    Finalise the game, record all points (even if ended early), announce results.
    Safe to call from any thread; idempotent.
    """
    with games_lock:
        state = games.get(chat_id)
    if not state:
        return

    with state.lock:
        if state.status == "finished":
            return
        state.status = "finished"
        _cancel_timer(state)
        sorted_scores = sorted(state.scores.items(), key=lambda kv: kv[1], reverse=True)
        players = dict(state.players)

    top     = sorted_scores[0][1] if sorted_scores else 0
    winners = [uid for uid, pts in sorted_scores if pts == top and pts > 0]

    header = "🏁 <b>Game ended early!  Points earned so far:</b>" if early else "🏆 <b>Game Over!  Final Scores:</b>"
    lines  = [header, ""]
    for rank, (uid, pts) in enumerate(sorted_scores):
        name = players.get(uid, "?")
        lines.append(f"{medal(rank)} <b>{name}</b> — {pts} pt{'s' if pts != 1 else ''}")

    if winners:
        wnames = " & ".join(players.get(u, "?") for u in winners)
        lines.append(f"\n🎊 <b>{'Tie! ' if len(winners) > 1 else ''}{wnames} wins!</b>  Congratulations!")
    else:
        lines.append("\nNo one scored — better luck next time!")

    bot.send_message(chat_id, "\n".join(lines))

    # Always record stats — even for early endings
    for uid, pts in sorted_scores:
        record_game_result(uid, puzzles_solved=pts, won=(uid in winners), points=pts)

    with games_lock:
        games.pop(chat_id, None)

# ──────────────────────────────────────────────────────────────────────────────
# Command handlers
# ──────────────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "help"])
def cmd_start(message: types.Message) -> None:
    bot.send_message(
        message.chat.id,
        "🧩 <b>RebusServer</b> — Rebus puzzle games for group chats!\n\n"
        "<b>How to play:</b>\n"
        "1. Use /newgame — choose how many rounds (10–20)\n"
        "2. Players press <b>Join Game</b> or type /join\n"
        "3. Host types /startgame when 2–7 players are ready\n"
        "4. Bot sends puzzle images one by one\n"
        "5. First correct text answer earns 1 point\n"
        "6. Live scores are shown after every puzzle\n"
        "7. Player with the most points wins!\n\n"
        "<b>Commands:</b>\n"
        "/newgame — Open a new lobby\n"
        "/join — Join the current lobby\n"
        "/startgame — Start the game (host only)\n"
        "/endgame — End the current game (points are saved)\n"
        "/scores — Show scores on demand\n"
        "/leaderboard — All-time top players\n"
        "/mystats — Your personal stats",
    )


@bot.message_handler(commands=["newgame"])
def cmd_newgame(message: types.Message) -> None:
    chat_id = message.chat.id
    user    = message.from_user

    with games_lock:
        existing = games.get(chat_id)
        if existing and existing.status != "finished":
            bot.send_message(
                chat_id,
                "⚠️ A game is already active!  Use /endgame to cancel it first.",
            )
            return

        state = GameState(
            chat_id=chat_id,
            host_id=user.id,
            host_name=user.first_name,
            players={user.id: user.first_name},
            scores={user.id: 0},
            status="choosing",
        )
        games[chat_id] = state

    upsert_player(user.id, user.first_name, user.username or "")
    bot.send_message(
        chat_id,
        f"🎮 <b>{user.first_name}</b> is starting a RebusServer game!\n\n"
        f"<b>{user.first_name}</b>, how many rounds would you like to play?",
        reply_markup=rounds_markup(),
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("rounds_"))
def btn_rounds(call: types.CallbackQuery) -> None:
    chat_id = call.message.chat.id
    user    = call.from_user

    with games_lock:
        state = games.get(chat_id)

    if not state or state.status != "choosing":
        bot.answer_callback_query(call.id, "No active lobby to configure.", show_alert=True)
        return
    if user.id != state.host_id:
        bot.answer_callback_query(call.id, "Only the host can choose the round count.", show_alert=True)
        return

    try:
        rounds = int(call.data.split("_")[1])
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "Invalid selection.", show_alert=True)
        return

    with state.lock:
        state.rounds = rounds
        state.status = "lobby"

    bot.answer_callback_query(call.id, f"✅ {rounds} rounds selected!")

    count = len(state.players)
    ready = (
        f"Waiting for {MIN_PLAYERS - count} more player(s)…"
        if count < MIN_PLAYERS
        else f"Ready! Host can type /startgame"
    )
    try:
        bot.edit_message_text(
            f"🎮 <b>{state.host_name}</b> opened a <b>{rounds}-round</b> RebusServer game!\n\n"
            f"👥 Players ({count}/{MAX_PLAYERS}): <b>{state.host_name}</b>\n\n"
            f"Press the button below or type /join\n{ready}",
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=join_markup(),
            parse_mode="HTML",
        )
    except Exception:
        bot.send_message(
            chat_id,
            f"🎮 <b>{state.host_name}</b> opened a <b>{rounds}-round</b> game!\n\n"
            f"Press the button below or type /join",
            reply_markup=join_markup(),
        )


def _do_join(chat_id: int, user: types.User) -> str:
    """Try to add user to the lobby. Returns error string or '' on success."""
    with games_lock:
        state = games.get(chat_id)
        if not state or state.status == "finished":
            return "No active lobby.  Use /newgame to start one."
        if state.status == "choosing":
            return "The host is still choosing the round count.  Please wait!"
        if state.status != "lobby":
            return "The game has already started!"
        if user.id in state.players:
            return "already_in"
        if len(state.players) >= MAX_PLAYERS:
            return f"Game is full ({MAX_PLAYERS} players max)!"
        state.players[user.id] = user.first_name
        state.scores[user.id]  = 0

    upsert_player(user.id, user.first_name, user.username or "")
    return ""


@bot.message_handler(commands=["join"])
def cmd_join(message: types.Message) -> None:
    chat_id = message.chat.id
    user    = message.from_user
    err     = _do_join(chat_id, user)

    if err == "already_in":
        bot.send_message(chat_id, "You're already in the game! 👍")
        return
    if err:
        bot.send_message(chat_id, err)
        return

    with games_lock:
        state = games[chat_id]
    count       = len(state.players)
    player_list = ", ".join(state.players.values())
    ready = (
        f"Waiting for {MIN_PLAYERS - count} more player(s)…"
        if count < MIN_PLAYERS
        else f"Ready! Host (<b>{state.host_name}</b>) can type /startgame"
    )
    bot.send_message(
        chat_id,
        f"✅ <b>{user.first_name}</b> joined!\n\n"
        f"👥 Players ({count}/{MAX_PLAYERS}): {player_list}\n\n{ready}",
        reply_markup=join_markup(),
    )


@bot.callback_query_handler(func=lambda c: c.data == "join_game")
def btn_join(call: types.CallbackQuery) -> None:
    chat_id = call.message.chat.id
    user    = call.from_user
    err     = _do_join(chat_id, user)

    if err == "already_in":
        bot.answer_callback_query(call.id, "You're already in the game! 👍", show_alert=True)
        return
    if err:
        bot.answer_callback_query(call.id, err, show_alert=True)
        return

    bot.answer_callback_query(call.id, "✅ You joined!")

    with games_lock:
        state = games.get(chat_id)
    if not state:
        return

    count       = len(state.players)
    player_list = ", ".join(state.players.values())
    ready = (
        f"Waiting for {MIN_PLAYERS - count} more player(s)…"
        if count < MIN_PLAYERS
        else f"Ready! Host (<b>{state.host_name}</b>) can type /startgame"
    )
    try:
        bot.edit_message_text(
            f"✅ <b>{user.first_name}</b> joined!\n\n"
            f"👥 Players ({count}/{MAX_PLAYERS}): {player_list}\n\n{ready}",
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=join_markup(),
            parse_mode="HTML",
        )
    except Exception:
        bot.send_message(
            chat_id,
            f"✅ <b>{user.first_name}</b> joined! ({count}/{MAX_PLAYERS})",
        )


@bot.message_handler(commands=["startgame"])
def cmd_startgame(message: types.Message) -> None:
    chat_id = message.chat.id
    user    = message.from_user

    with games_lock:
        state = games.get(chat_id)

    if not state:
        bot.send_message(chat_id, "No lobby active.  Use /newgame first.")
        return
    if state.status == "choosing":
        bot.send_message(chat_id, "The host needs to pick the round count first.")
        return
    if state.status != "lobby":
        bot.send_message(chat_id, "The game is already running!")
        return
    if user.id != state.host_id:
        bot.send_message(chat_id, "Only the game host can start the game.")
        return
    if len(state.players) < MIN_PLAYERS:
        bot.send_message(
            chat_id,
            f"Need at least {MIN_PLAYERS} players.  Currently {len(state.players)}.",
        )
        return

    # Build puzzle queue from the full pool (both packs), capped to chosen rounds
    pool = available_puzzle_pool()
    random.shuffle(pool)
    with state.lock:
        state.puzzle_queue      = pool[:state.rounds]
        state.current_puzzle_idx = 0
        state.status             = "playing"

    player_list = "\n".join(f"  • {n}" for n in state.players.values())
    bot.send_message(
        chat_id,
        f"🚀 <b>Game starting!</b>\n\n"
        f"👥 Players:\n{player_list}\n\n"
        f"📝 {state.rounds} rounds  •  {ANSWER_TIMEOUT}s per puzzle  •  200-puzzle pool\n"
        f"First correct answer scores a point.  Good luck!\n\n"
        f"<i>Get ready… 3… 2… 1…</i>",
    )

    def _start() -> None:
        time.sleep(3)
        send_next_puzzle(chat_id)

    threading.Thread(target=_start, daemon=True).start()


@bot.message_handler(commands=["endgame"])
def cmd_endgame(message: types.Message) -> None:
    chat_id = message.chat.id
    user    = message.from_user

    with games_lock:
        state = games.get(chat_id)

    if not state or state.status == "finished":
        bot.send_message(chat_id, "No game running.")
        return

    is_admin = False
    try:
        member   = bot.get_chat_member(chat_id, user.id)
        is_admin = member.status in ("administrator", "creator")
    except Exception:
        pass

    if user.id != state.host_id and not is_admin:
        bot.send_message(chat_id, "Only the host or a group admin can end the game.")
        return

    was_playing = state.status == "playing"

    # Cancel any running timer first — DON'T set status here; finish_game owns that
    with state.lock:
        _cancel_timer(state)

    if was_playing:
        # finish_game records all points earned so far and announces results
        finish_game(chat_id, early=True)
    else:
        # Still in lobby/choosing — just cancel quietly
        bot.send_message(chat_id, "🛑 Game lobby cancelled.")
        with state.lock:
            state.status = "finished"
        with games_lock:
            games.pop(chat_id, None)


@bot.message_handler(commands=["scores"])
def cmd_scores(message: types.Message) -> None:
    chat_id = message.chat.id
    with games_lock:
        state = games.get(chat_id)

    if not state or state.status == "finished":
        bot.send_message(chat_id, "No game is currently running.")
        return
    if state.status in ("choosing", "lobby"):
        player_list = ", ".join(state.players.values())
        bot.send_message(
            chat_id,
            f"⏳ Lobby — {len(state.players)} player(s): {player_list}\n"
            f"Rounds: {state.rounds}  |  Waiting for /startgame",
        )
        return

    idx   = state.current_puzzle_idx
    total = len(state.puzzle_queue)
    bot.send_message(
        chat_id,
        f"Puzzle {idx}/{total}\n\n" + scores_text(state),
    )


@bot.message_handler(commands=["leaderboard"])
def cmd_leaderboard(message: types.Message) -> None:
    rows = get_leaderboard(10)
    if not rows:
        bot.send_message(message.chat.id, "No all-time stats yet.  Play a game first! 🎮")
        return

    lines = ["🏆 <b>All-Time Leaderboard</b>\n"]
    for rank, (name, played, solved, won, points) in enumerate(rows):
        lines.append(
            f"{medal(rank)} <b>{name}</b> — "
            f"{points} pts  |  {won}W / {played}G  |  {solved} puzzles solved"
        )
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["mystats"])
def cmd_mystats(message: types.Message) -> None:
    user = message.from_user
    upsert_player(user.id, user.first_name, user.username or "")
    row  = get_player_stats(user.id)

    if not row or row[0] == 0:
        bot.send_message(
            message.chat.id,
            f"No stats yet for {user.first_name}.  Join a game! 🎮",
        )
        return

    played, solved, won, points = row
    win_rate = f"{won / played * 100:.0f}%" if played else "—"
    bot.send_message(
        message.chat.id,
        f"📊 <b>Stats — {user.first_name}</b>\n\n"
        f"🎮 Games played:    <b>{played}</b>\n"
        f"🏆 Games won:       <b>{won}</b>  ({win_rate} win rate)\n"
        f"🧩 Puzzles solved:  <b>{solved}</b>\n"
        f"⭐ Total points:    <b>{points}</b>",
    )

# ──────────────────────────────────────────────────────────────────────────────
# Live answer handler  (must be registered last so commands take priority)
# ──────────────────────────────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.content_type == "text")
def handle_message(message: types.Message) -> None:
    chat_id = message.chat.id
    with games_lock:
        state = games.get(chat_id)

    if not state or state.status != "playing":
        return

    user = message.from_user
    if user.id not in state.players:
        return

    text = (message.text or "").strip()
    if not text:
        return

    with state.lock:
        idx = state.current_puzzle_idx
        if idx >= len(state.puzzle_queue):
            return
        puzzle_num = state.puzzle_queue[idx]
        if puzzle_num in state.solved:
            return
        if not check_answer(puzzle_num, text):
            return

        # ── Correct! ────────────────────────────────────────────────────────
        state.solved.add(puzzle_num)
        state.scores[user.id] = state.scores.get(user.id, 0) + 1
        _cancel_timer(state)
        state.current_puzzle_idx += 1
        next_idx = state.current_puzzle_idx
        # Capture scores snapshot for the post below (still inside lock)
        scores_snapshot = dict(state.scores)
        players_snapshot = dict(state.players)

    key            = _answer_key(puzzle_num)
    answer_display = ANSWERS[key][0].title()
    bot.reply_to(
        message,
        f"✅ <b>{user.first_name}</b> got it!  <b>{answer_display}</b>  (+1 point) 🎉",
    )

    # Post live scoreboard
    post_scores(chat_id, state)

    def _advance() -> None:
        time.sleep(2)
        if next_idx >= len(state.puzzle_queue):
            finish_game(chat_id)
        else:
            send_next_puzzle(chat_id)

    threading.Thread(target=_advance, daemon=True).start()

# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    init_db()
    setup_puzzles()
    logger.info("RebusServer is running…  Pool: %d puzzles", len(available_puzzle_pool()))
    bot.infinity_polling(timeout=60, long_polling_timeout=60)


if __name__ == "__main__":
    main()
