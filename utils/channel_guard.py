"""
utils/channel_guard.py
Cek apakah user sudah join channel wajib sebelum bisa pakai bot.
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, Forbidden

# Channel yang wajib di-join
REQUIRED_CHANNEL    = "@TelekuyMarket"
REQUIRED_CHANNEL_ID = "@TelekuyMarket"   # bisa diganti ke -100xxx kalau private


async def is_member(bot, user_id: int) -> bool:
    """Return True kalau user sudah join channel."""
    try:
        member = await bot.get_chat_member(
            chat_id=REQUIRED_CHANNEL_ID,
            user_id=user_id,
        )
        return member.status in ("member", "administrator", "creator")
    except (BadRequest, Forbidden):
        # Bot tidak ada di channel atau channel tidak ditemukan
        return True   # fail-open: jangan block user kalau bot tidak bisa cek


async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Panggil ini di awal start_handler.
    Return True  → user sudah join, lanjut.
    Return False → sudah kirim pesan "wajib join", stop handler.
    """
    user_id = update.effective_user.id

    if await is_member(context.bot, user_id):
        return True

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/TelekuyMarket")],
        [InlineKeyboardButton("✅ Sudah Join",   callback_data="check_membership")],
    ])

    text = (
        "⚠️ <b>Wajib Join Channel!</b>\n"
        "──────────────────────\n"
        f"Untuk menggunakan bot ini, kamu wajib join channel kami terlebih dahulu:\n\n"
        f"📢 {REQUIRED_CHANNEL}\n\n"
        "Setelah join, klik tombol <b>✅ Sudah Join</b> di bawah."
    )

    if update.message:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)

    return False