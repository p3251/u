#!/usr/bin/env python3
"""Mafia Telegram bot — full game controller."""

import os
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest, Conflict

from game import Game, GameState, Role, ROLE_EMOJIS, ROLE_DESCRIPTIONS, Player

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── helpers ────────────────────────────────────────────────────────────────

def get_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> Game | None:
    return context.bot_data.get("games", {}).get(chat_id)


def set_game(context: ContextTypes.DEFAULT_TYPE, game: Game):
    context.bot_data.setdefault("games", {})[game.chat_id] = game


def del_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    context.bot_data.get("games", {}).pop(chat_id, None)


def track_group(context: ContextTypes.DEFAULT_TYPE, chat):
    """Remember a group the bot is active in."""
    groups = context.bot_data.setdefault("known_groups", {})
    groups[chat.id] = chat.title or str(chat.id)


def alive_keyboard(game: Game, callback_prefix: str) -> InlineKeyboardMarkup:
    """Inline keyboard with alive players (excluding caller handled upstream)."""
    buttons = []
    for uid, p in game.alive_players.items():
        buttons.append([InlineKeyboardButton(p.display_name, callback_data=f"{callback_prefix}:{uid}")])
    return InlineKeyboardMarkup(buttons)


async def safe_send(bot, chat_id: int, text: str, **kwargs) -> bool:
    """Send a message, returning False if the user blocked the bot."""
    try:
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return True
    except (Forbidden, BadRequest) as e:
        logger.warning("Cannot send to %s: %s", chat_id, e)
        return False


# ─── /start ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Salom! Men *Mafia* o'yini boti.\n\n"
        "📋 *Guruhda o'yin boshlash tartibi:*\n"
        "1. Meni guruhga qo'shing\n"
        "2. /newgame — lobbini oching\n"
        "3. O'yinchilar /join yozadi\n"
        "4. /startgame — boshlash (kamida 4 o'yinchi)\n\n"
        "📜 /rules — o'yin qoidalari\n"
        "❓ /help — buyruqlar ro'yxati",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── /rules ─────────────────────────────────────────────────────────────────

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📜 *Mafia qoidalari*\n\n"
        "*Rollar:*\n"
        "🔫 *Mafia* — tunda bir tinch aholini o'ldiradi\n"
        "💊 *Doktor* — tunda bir o'yinchini qutqaradi (o'zini ham bo'ladi)\n"
        "🔍 *Detektiv* — tunda bir o'yinchi mafiadanmi yoki yo'qligini tekshiradi\n"
        "👤 *Tinch aholi* — ovoz berish orqali mafiyani aniqlashga harakat qiladi\n\n"
        "*O'yin jarayoni:*\n"
        "🌙 *Tun* — mafia qurbonni tanlaydi, doktor qutqaradi, detektiv tekshiradi\n"
        "☀️ *Kun* — hamma muhokama qiladi va gumon qilingan kishiga ovoz beradi\n\n"
        "*G'alaba:*\n"
        "🏆 Tinch aholi g'alaba qozonadi, agar barcha mafia yo'q qilinsa\n"
        "💀 Mafia g'alaba qozonadi, agar ularning soni tinch aholi bilan tenglashsa\n\n"
        "*Rollarni taqsimlash:*\n"
        "4–5 o'yinchi → 1 mafia\n"
        "6–8 o'yinchi → 2 mafia\n"
        "9+ o'yinchi → 3 mafia\n"
        "(+ har doim 1 doktor va 1 detektiv)",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── /help ──────────────────────────────────────────────────────────────────

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ *Bot buyruqlari:*\n\n"
        "*/newgame* — yangi o'yin uchun lobbini oching\n"
        "*/join* — o'yinga qo'shilish\n"
        "*/startgame* — o'yinni boshlash (xost, min. 4 o'yinchi)\n"
        "*/players* — lobbidagi / tirik o'yinchilar ro'yxati\n"
        "*/rules* — o'yin qoidalari\n"
        "*/endgame* — o'yinni muddatidan oldin tugatish (xost/admin)\n\n"
        "⚠️ Tungi harakatlar *shaxsiy xabarga* keladi — botga /start yozganingizga ishonch hosil qiling!",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── /newgame ────────────────────────────────────────────────────────────────

async def newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text("⚠️ O'yinni *guruh chatida* boshlash kerak.", parse_mode=ParseMode.MARKDOWN)
        return

    existing = get_game(context, chat.id)
    if existing:
        await update.message.reply_text("⚠️ O'yin allaqachon boshlangan! Tugatish uchun /endgame foydalaning.")
        return

    track_group(context, chat)
    game = Game(chat_id=chat.id, host_id=user.id)
    player = Player(user_id=user.id, username=user.username or "", full_name=user.full_name)
    game.players[user.id] = player
    set_game(context, game)

    await update.message.reply_text(
        f"🎮 *Yangi Mafia o'yini!*\n\n"
        f"Xost: {user.full_name}\n\n"
        f"O'yinga qo'shilish uchun /join yozing.\n"
        f"Lobbidagi o'yinchilar: 1\n\n"
        f"⚠️ Botga shaxsiy xabarda /start yozganingizga ishonch hosil qiling — aks holda u sizga rol yuborolmaydi!",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── /join ───────────────────────────────────────────────────────────────────

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text("⚠️ O'yinga faqat guruh chatida qo'shilish mumkin.")
        return

    game = get_game(context, chat.id)
    if not game:
        await update.message.reply_text("⚠️ Faol o'yin yo'q. Boshlash uchun /newgame foydalaning.")
        return

    if game.state != GameState.WAITING:
        await update.message.reply_text("⚠️ O'yin allaqachon boshlangan — keyingi o'yinni kuting.")
        return

    if user.id in game.players:
        await update.message.reply_text(f"{user.full_name} allaqachon o'yinda! ✅")
        return

    game.players[user.id] = Player(
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name,
    )

    count = len(game.players)
    await update.message.reply_text(
        f"✅ *{user.full_name}* o'yinga qo'shildi!\n"
        f"Lobbidagi o'yinchilar: {count}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── /players ────────────────────────────────────────────────────────────────

async def players_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    game = get_game(context, chat.id)

    if not game:
        await update.message.reply_text("⚠️ Faol o'yin yo'q.")
        return

    if game.state == GameState.WAITING:
        title = f"🎮 Lobby — {len(game.players)} o'yinchi:"
    else:
        alive = len(game.alive_players)
        total = len(game.players)
        title = f"👥 O'yinchilar (tiriklar {alive}/{total}):"

    text = title + "\n" + game.player_list_text()
    await update.message.reply_text(text)


# ─── /startgame ──────────────────────────────────────────────────────────────

async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    game = get_game(context, chat.id)

    if not game:
        await update.message.reply_text("⚠️ Faol o'yin yo'q. /newgame foydalaning.")
        return

    if game.state != GameState.WAITING:
        await update.message.reply_text("⚠️ O'yin allaqachon boshlangan.")
        return

    if user.id != game.host_id:
        await update.message.reply_text("⚠️ Faqat xost o'yinni boshlashi mumkin.")
        return

    if len(game.players) < 4:
        await update.message.reply_text(f"⚠️ Kamida 4 o'yinchi kerak! Hozir: {len(game.players)}")
        return

    game.assign_roles()

    # Send roles to players via DM
    failed = []
    mafia_names = [p.display_name for p in game.players.values() if p.role == Role.MAFIA]

    for uid, player in game.players.items():
        role = player.role
        emoji = ROLE_EMOJIS[role]
        desc = ROLE_DESCRIPTIONS[role]

        if role == Role.MAFIA and len(mafia_names) > 1:
            teammates = [n for n in mafia_names if n != player.display_name]
            extra = f"\n\n🤝 Sheriginglar: {', '.join(teammates)}"
        else:
            extra = ""

        msg = (
            f"🃏 *Sening roling: {emoji} {role.value}*\n\n"
            f"{desc}{extra}"
        )
        ok = await safe_send(context.bot, uid, msg, parse_mode=ParseMode.MARKDOWN)
        if not ok:
            failed.append(player.display_name)

    if failed:
        await update.message.reply_text(
            f"⚠️ Shaxsiy xabarga rol yubora olmadim: {', '.join(failed)}\n"
            "Ular botga shaxsiy xabarda /start yozishlari, so'ngra /startgame qayta urinib ko'rishlari kerak"
        )
        # Reset roles so we can retry
        for p in game.players.values():
            p.role = None
        return

    await update.message.reply_text(
        f"🎮 *O'yin boshlandi!* {len(game.players)} o'yinchi\n\n"
        "Rollar taqsimlandi — shaxsiy xabarni tekshiring!\n\n"
        f"{game.player_list_text()}",
        parse_mode=ParseMode.MARKDOWN,
    )

    await start_night(update, context, game)


async def dev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text("⚠️ /dev buyrug'i faqat guruhda ishlaydi.")
        return

    game = get_game(context, chat.id)
    if game and game.state != GameState.WAITING:
        await update.message.reply_text("⚠️ O'yin allaqachon boshlangan.")
        return

    if not game:
        game = Game(chat_id=chat.id, host_id=user.id)
        set_game(context, game)

    if user.id not in game.players:
        game.players[user.id] = Player(
            user_id=user.id,
            username=user.username or "",
            full_name=user.full_name,
        )

    game.host_id = user.id
    await update.message.reply_text("🛠 Test rejimi yoqildi. O'yinni hatto 1 o'yinchi bilan ham boshlash mumkin.")
    await startgame(update, context)


# ─── NIGHT PHASE ─────────────────────────────────────────────────────────────

async def start_night(update: Update, context: ContextTypes.DEFAULT_TYPE, game: Game):
    game.state = GameState.NIGHT
    game.round_number += 1
    game.mafia_votes = {}
    game.doctor_target = None
    game.detective_target = None
    game.night_actions_done = set()

    await context.bot.send_message(
        chat_id=game.chat_id,
        text=(
            f"🌙 *{game.round_number}-tun tushdi...*\n\n"
            "Shahar uxlayapti. Mafia uyg'onmoqda.\n"
            "Tungi harakatlar shaxsiy xabarga yuboriladi!"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    # Send night action keyboards to each role
    for uid, player in game.alive_players.items():
        if player.role == Role.MAFIA:
            # Show alive non-mafia players to kill
            targets = {tid: p for tid, p in game.alive_players.items() if p.role != Role.MAFIA}
            if not targets:
                continue
            buttons = [[InlineKeyboardButton(p.display_name, callback_data=f"mafia_kill:{uid}:{tid}")]
                       for tid, p in targets.items()]
            kb = InlineKeyboardMarkup(buttons)
            await safe_send(
                context.bot, uid,
                f"🔫 *{game.round_number}-tun* — qurbonni tanlang:",
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN,
            )

        elif player.role == Role.DOCTOR:
            targets = game.alive_players
            buttons = [[InlineKeyboardButton(p.display_name, callback_data=f"doctor_save:{uid}:{tid}")]
                       for tid, p in targets.items()]
            kb = InlineKeyboardMarkup(buttons)
            await safe_send(
                context.bot, uid,
                f"💊 *{game.round_number}-tun* — bu tunda kimni qutqarasiz?",
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN,
            )

        elif player.role == Role.DETECTIVE:
            targets = {tid: p for tid, p in game.alive_players.items() if tid != uid}
            buttons = [[InlineKeyboardButton(p.display_name, callback_data=f"detective_check:{uid}:{tid}")]
                       for tid, p in targets.items()]
            kb = InlineKeyboardMarkup(buttons)
            await safe_send(
                context.bot, uid,
                f"🔍 *{game.round_number}-tun* — kimni tekshirasiz?",
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN,
            )


async def check_night_complete(context: ContextTypes.DEFAULT_TYPE, game: Game):
    """Check if all night actions are done; if so, resolve the night."""
    if not game.night_complete():
        return

    killed, saved, detective_result = game.resolve_night()

    # Announce morning
    if saved:
        night_result = "💊 Doktor bu tunda birovning jonini saqlab qoldi — hech kim halok bo'lmadi!"
    elif killed is not None:
        victim = game.players[killed]
        night_result = f"💀 Bu tunda *{victim.display_name}* o'ldirildi!"
    else:
        night_result = "🤔 Bu tunda hech kim halok bo'lmadi."

    # Send detective result privately
    if detective_result:
        target_uid, is_mafia = detective_result
        target_player = game.players[target_uid]
        result_text = "🔫 *MAFIA*" if is_mafia else "👤 *Tinch aholi*"
        detective_player = game.detective
        if detective_player:
            await safe_send(
                context.bot,
                detective_player.user_id,
                f"🔍 Tekshiruv natijasi: *{target_player.display_name}* — {result_text}",
                parse_mode=ParseMode.MARKDOWN,
            )

    winner = game.check_win()
    if winner:
        await end_game(context, game, winner, night_result)
        return

    await context.bot.send_message(
        chat_id=game.chat_id,
        text=(
            f"☀️ *{game.round_number}-kun keldi*\n\n"
            f"{night_result}\n\n"
            f"Tirik o'yinchilar: {len(game.alive_players)}\n"
            f"{game.player_list_text()}\n\n"
            "💬 Muhokama qiling! So'ngra quyidagi inline-tugmalar orqali ovoz bering."
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    game.state = GameState.DAY_DISCUSSION
    await prompt_day_vote(context, game)


# ─── NIGHT CALLBACKS ─────────────────────────────────────────────────────────

async def cb_mafia_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    _, mafia_id_str, target_str = query.data.split(":")
    if query.from_user.id != int(mafia_id_str):
        await query.answer("⚠️ Bu sizning tugmangiz emas!", show_alert=True)
        return
    target_id = int(target_str)

    # Find which game this mafia belongs to
    game = None
    for g in context.bot_data.get("games", {}).values():
        if user.id in g.players and g.players[user.id].role == Role.MAFIA:
            game = g
            break

    if not game or game.state != GameState.NIGHT:
        await query.edit_message_text("⚠️ Harakat mavjud emas.")
        return

    if user.id not in game.alive_players:
        await query.edit_message_text("⚠️ Siz allaqachon yo'q qilindingiz.")
        return

    target = game.players.get(target_id)
    if not target:
        await query.edit_message_text("⚠️ O'yinchi topilmadi.")
        return

    game.mafia_votes[user.id] = target_id
    await query.edit_message_text(f"🔫 Siz tanladingiz: *{target.display_name}*", parse_mode=ParseMode.MARKDOWN)

    # Check if all mafia has voted
    mafia_ids = set(game.alive_mafia.keys())
    if mafia_ids.issubset(set(game.mafia_votes.keys())):
        game.night_actions_done.add("mafia")
        await check_night_complete(context, game)


async def cb_doctor_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    _, doctor_id_str, target_str = query.data.split(":")
    if query.from_user.id != int(doctor_id_str):
        await query.answer("⚠️ Bu sizning tugmangiz emas!", show_alert=True)
        return
    target_id = int(target_str)

    game = None
    for g in context.bot_data.get("games", {}).values():
        if user.id in g.players and g.players[user.id].role == Role.DOCTOR:
            game = g
            break

    if not game or game.state != GameState.NIGHT:
        await query.edit_message_text("⚠️ Harakat mavjud emas.")
        return

    target = game.players.get(target_id)
    if not target:
        await query.edit_message_text("⚠️ O'yinchi topilmadi.")
        return

    game.doctor_target = target_id
    game.night_actions_done.add("doctor")
    await query.edit_message_text(f"💊 Siz himoya qildingiz: *{target.display_name}*", parse_mode=ParseMode.MARKDOWN)
    await check_night_complete(context, game)


async def cb_detective_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    _, detective_id_str, target_str = query.data.split(":")
    if query.from_user.id != int(detective_id_str):
        await query.answer("⚠️ Bu sizning tugmangiz emas!", show_alert=True)
        return
    target_id = int(target_str)

    game = None
    for g in context.bot_data.get("games", {}).values():
        if user.id in g.players and g.players[user.id].role == Role.DETECTIVE:
            game = g
            break

    if not game or game.state != GameState.NIGHT:
        await query.edit_message_text("⚠️ Harakat mavjud emas.")
        return

    target = game.players.get(target_id)
    if not target:
        await query.edit_message_text("⚠️ O'yinchi topilmadi.")
        return

    game.detective_target = target_id
    game.night_actions_done.add("detective")
    await query.edit_message_text(f"🔍 Siz tekshiryapsiz: *{target.display_name}* — javob tongda keladi.", parse_mode=ParseMode.MARKDOWN)
    await check_night_complete(context, game)


# ─── DAY VOTING ──────────────────────────────────────────────────────────────

async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    game = get_game(context, chat.id)

    if not game:
        await update.message.reply_text("⚠️ Faol o'yin yo'q.")
        return

    if game.state not in (GameState.DAY_DISCUSSION, GameState.DAY_VOTING):
        await update.message.reply_text("⚠️ Hozir ovoz berish vaqti emas.")
        return

    if user.id not in game.alive_players:
        await update.message.reply_text("⚠️ Faqat tirik o'yinchilar ovoz bera oladi.")
        return

    await update.message.reply_text("⚠️ Ovoz berish endi faqat bot kun davomida yuboradigan inline-tugmalar orqali amalga oshiriladi.")


async def cb_day_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    voter_id = int(parts[1])
    target_id = int(parts[2])

    if query.from_user.id != voter_id:
        await query.answer("⚠️ Bu sizning ovozingiz emas!", show_alert=True)
        return

    game = get_game(context, query.message.chat_id)
    if not game or game.state != GameState.DAY_VOTING:
        await query.edit_message_text("⚠️ Ovoz berish mavjud emas.")
        return

    if voter_id not in game.alive_players:
        await query.edit_message_text("⚠️ O'liklar ovoz bera olmaydi.")
        return

    target = game.players.get(target_id)
    if not target:
        await query.edit_message_text("⚠️ O'yinchi topilmadi.")
        return

    if voter_id in game.day_votes:
        await query.answer("⚠️ Siz allaqachon ovoz bergansiz.", show_alert=True)
        return
    game.day_votes[voter_id] = target_id
    await query.edit_message_text(f"✅ Ovoz qabul qilindi: *{target.display_name}*", parse_mode=ParseMode.MARKDOWN)

    # Show current tally
    await show_vote_tally(context, game)

    # Check if all alive players voted
    if set(game.alive_players.keys()).issubset(set(game.day_votes.keys())):
        await resolve_day_vote(context, game)


async def prompt_day_vote(context: ContextTypes.DEFAULT_TYPE, game: Game):
    game.state = GameState.DAY_VOTING
    buttons = []
    for voter_id, voter in game.alive_players.items():
        row = [InlineKeyboardButton(f"🗳 {voter.display_name}", callback_data=f"vote_menu:{voter_id}")]
        buttons.append(row)
    await context.bot.send_message(
        chat_id=game.chat_id,
        text="🗳 Ismingizga bosing, so'ngra kimga ovoz berishni tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cb_vote_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    voter_id = int(query.data.split(":")[1])
    if query.from_user.id != voter_id:
        await query.answer("⚠️ Bu sizning tugmangiz emas!", show_alert=True)
        return
    game = get_game(context, query.message.chat_id)
    if not game or game.state != GameState.DAY_VOTING:
        await query.edit_message_text("⚠️ Ovoz berish mavjud emas.")
        return
    if voter_id in game.day_votes:
        await query.answer("⚠️ Siz allaqachon ovoz bergansiz.", show_alert=True)
        return
    targets = [
        InlineKeyboardButton(p.display_name, callback_data=f"day_vote:{voter_id}:{tid}")
        for tid, p in game.alive_players.items()
        if tid != voter_id
    ]
    await query.edit_message_text(
        "🗳 Kimga ovoz berishni tanlang:",
        reply_markup=InlineKeyboardMarkup([targets[i:i+2] for i in range(0, len(targets), 2)]),
    )


async def show_vote_tally(context: ContextTypes.DEFAULT_TYPE, game: Game):
    """Post current vote counts to the group."""
    if not game.day_votes:
        return

    counts: dict = {}
    for target_uid in game.day_votes.values():
        counts[target_uid] = counts.get(target_uid, 0) + 1

    lines = []
    for uid, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        player = game.players[uid]
        lines.append(f"  {player.display_name}: {cnt} ovoz")

    voted_count = len(game.day_votes)
    total = len(game.alive_players)
    text = (
        f"🗳 *Joriy ovozlar* ({voted_count}/{total} ovoz berdi):\n"
        + "\n".join(lines)
    )
    await context.bot.send_message(chat_id=game.chat_id, text=text, parse_mode=ParseMode.MARKDOWN)


async def resolve_day_vote(context: ContextTypes.DEFAULT_TYPE, game: Game):
    """Resolve the day vote and transition to night or end game."""
    eliminated = game.resolve_vote()

    if eliminated is None:
        result_text = "🤝 *Durrang!* Hech kim yo'q qilinmadi — fikrlar bo'lindi."
    else:
        player = game.players[eliminated]
        role_reveal = f"{ROLE_EMOJIS[player.role]} {player.role.value}"
        result_text = (
            f"⚖️ Shahar ovoz berdi!\n\n"
            f"💀 *{player.display_name}* yo'q qilindi.\n"
            f"Uning roli: {role_reveal}"
        )

    winner = game.check_win()
    if winner:
        await end_game(context, game, winner, result_text)
        return

    await context.bot.send_message(
        chat_id=game.chat_id,
        text=result_text + f"\n\nTirik o'yinchilar: {len(game.alive_players)}",
        parse_mode=ParseMode.MARKDOWN,
    )

    await start_night(None, context, game)


# ─── END GAME ────────────────────────────────────────────────────────────────

async def end_game(context: ContextTypes.DEFAULT_TYPE, game: Game, winner: str, extra_text: str = ""):
    """Announce the winner and reveal all roles."""
    if winner == "civilians":
        header = "🏆 *TINCH AHOLI G'ALABA QOZONDI!*\nMafia yo'q qilindi — shahar qutqarildi!"
    else:
        header = "💀 *MAFIA G'ALABA QOZONDI!*\nMafiyachilar shaharni egallab oldi!"

    role_reveal_lines = []
    for p in game.players.values():
        emoji = ROLE_EMOJIS.get(p.role, "❓")
        status = "💀" if not p.alive else "✅"
        role_reveal_lines.append(f"{status} {p.display_name} — {emoji} {p.role.value if p.role else '?'}")

    role_reveal = "\n".join(role_reveal_lines)

    await context.bot.send_message(
        chat_id=game.chat_id,
        text=(
            f"{extra_text}\n\n"
            f"{header}\n\n"
            f"📋 *Yakuniy rollar:*\n{role_reveal}\n\n"
            "Yangi o'yin: /newgame"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    del_game(context, game.chat_id)


async def endgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    game = get_game(context, chat.id)

    if not game:
        await update.message.reply_text("⚠️ Faol o'yin yo'q.")
        return

    member = await chat.get_member(user.id)
    is_admin = member.status in ("administrator", "creator")

    if user.id != game.host_id and not is_admin:
        await update.message.reply_text("⚠️ Faqat xost yoki administrator o'yinni tugatishi mumkin.")
        return

    del_game(context, chat.id)
    await update.message.reply_text(
        "🛑 O'yin majburiy ravishda tugatildi.\n"
        "Yangi o'yin: /newgame"
    )


# ─── /leave ──────────────────────────────────────────────────────────────────

async def leave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type != "private":
        await update.message.reply_text("⚠️ /leave buyrug'ini menga *shaxsiy xabarda* yozing.", parse_mode=ParseMode.MARKDOWN)
        return

    groups = context.bot_data.get("known_groups", {})
    if not groups:
        await update.message.reply_text("ℹ️ Men hech qanday guruhda qatnashmayman.")
        return

    buttons = [
        [InlineKeyboardButton(f"🚪 {title}", callback_data=f"leave_group:{gid}")]
        for gid, title in groups.items()
    ]
    await update.message.reply_text(
        "Qaysi guruhdan chiqishim kerakligini tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cb_leave_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = int(query.data.split(":")[1])
    groups = context.bot_data.get("known_groups", {})
    title = groups.get(chat_id, str(chat_id))

    try:
        # Finish any active game in that group first
        del_game(context, chat_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="👋 Bot guruhni tark etmoqda. Xayr!",
        )
        await context.bot.leave_chat(chat_id)
        groups.pop(chat_id, None)
        await query.edit_message_text(f"✅ *{title}* guruhidan chiqdim.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning("Cannot leave chat %s: %s", chat_id, e)
        await query.edit_message_text(f"⚠️ *{title}* guruhidan chiqib bo'lmadi: {e}", parse_mode=ParseMode.MARKDOWN)


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN belgilanmagan!")

    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("newgame", newgame))
    app.add_handler(CommandHandler("dev", dev))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("players", players_cmd))
    app.add_handler(CommandHandler("vote", vote))
    app.add_handler(CommandHandler("endgame", endgame_cmd))
    app.add_handler(CommandHandler("leave", leave_cmd))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(cb_mafia_kill, pattern=r"^mafia_kill:"))
    app.add_handler(CallbackQueryHandler(cb_doctor_save, pattern=r"^doctor_save:"))
    app.add_handler(CallbackQueryHandler(cb_detective_check, pattern=r"^detective_check:"))
    app.add_handler(CallbackQueryHandler(cb_vote_menu, pattern=r"^vote_menu:"))
    app.add_handler(CallbackQueryHandler(cb_day_vote, pattern=r"^day_vote:"))
    app.add_handler(CallbackQueryHandler(cb_leave_group, pattern=r"^leave_group:"))

    logger.info("Bot ishga tushdi!")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "my_chat_member"],
    )


if __name__ == "__main__":
    main()
