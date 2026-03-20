"""
handlers/support.py
Tampilkan halaman Support.
callback_data: menu_support
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

SUPPORT_TEXT = (
    "🆘 <b>Support Telekuy</b>\n"
    "──────────────────────\n\n"
    "Butuh bantuan? Tim kami siap membantu kamu.\n\n"
    "💬 <b>Chat Admin</b>\n"
    "→ @TelekuySupport\n\n"
    "📢 <b>Channel Update</b>\n"
    "→ @TelekuyMarket\n\n"
    "🌐 <b>Cek Order Online</b>\n"
    "→ https://order.telekuy.com/\n\n"
    "──────────────────────\n"
    "⏰ Respon admin: <b>Senin–Minggu, 08.00–22.00 WIB</b>\n\n"
    "❗ Saat menghubungi support, mohon sertakan:\n"
    "• Order code (<code>kode order kamu</code>)\n"
    "• Screenshot bukti masalah\n"
    "• Penjelasan singkat kendala"
)


async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Chat Support", url="https://t.me/TelekuySupport")],
        [InlineKeyboardButton("🏠 Home",         callback_data="menu_home")],
    ])

    msg = query.message
    try:
        if msg.photo or msg.document or msg.sticker or msg.animation:
            await query.edit_message_caption(
                caption=SUPPORT_TEXT,
                parse_mode="HTML",
                reply_markup=kb,
            )
        else:
            await query.edit_message_text(
                text=SUPPORT_TEXT,
                parse_mode="HTML",
                reply_markup=kb,
                disable_web_page_preview=True,
            )
    except BadRequest:
        pass