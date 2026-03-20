"""
handlers/user_keyboard.py
Handler untuk tombol reply keyboard user biasa.

Tombol:
  🛒 Purchase  → sama dengan callback menu_stock
  💳 Deposit   → sama dengan callback menu_deposit
  📋 Riwayat   → sama dengan callback menu_history_order
  🆘 Support   → sama dengan callback menu_support
  🏠 Home      → kirim ulang halaman home
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from data.user_store import upsert_user
from utils.config    import ADMIN_ID

logger = logging.getLogger(__name__)


async def _btn_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from services.laravel_api import get_categories
    from handlers.catalog     import show_categories, _kb_categories
    from telegram             import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.error       import BadRequest

    try:
        categories = get_categories()
        context.bot_data["categories"] = categories
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal memuat kategori.\n<code>{e}</code>", parse_mode="HTML")
        return

    if not categories:
        await update.message.reply_text("📭 Belum ada kategori tersedia.")
        return

    total   = sum(c.get("total_stock", 0) for c in categories)
    caption = (
        f"🛒 <b>Purchase</b>\n"
        f"──────────────────────\n"
        f"Pilih kategori akun yang ingin dibeli.\n"
        f"Total tersedia: <b>{total:,}</b> akun"
    )
    await update.message.reply_text(
        text=caption,
        parse_mode="HTML",
        reply_markup=_kb_categories(categories),
    )


async def _btn_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.deposit import show_deposit_menu as _show
    from telegram         import InlineKeyboardButton, InlineKeyboardMarkup

    text = (
        "💳 <b>Deposit Saldo</b>\n"
        "──────────────────────\n"
        "Min. deposit : <b>10,000 IDR</b>\n"
        "Max. deposit : <b>10,000,000 IDR</b>\n\n"
        "Pilih metode pembayaran:"
    )
    from handlers.deposit import PAYMENT_METHODS
    rows  = [[InlineKeyboardButton("📷 QRIS", callback_data="dep_method_QRIS")]]
    rows += [[InlineKeyboardButton(f"💸 {m}", callback_data=f"dep_method_{m}")] for m in PAYMENT_METHODS]
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="menu_home")])

    await update.message.reply_text(
        text=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _btn_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from data.order_store import get_user_orders
    from handlers.history_order import _build_page

    orders    = get_user_orders(update.effective_user.id, limit=200)
    text, kb  = _build_page(orders, 0)
    await update.message.reply_text(
        text=text,
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True,
    )


async def _btn_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.support import SUPPORT_TEXT
    from telegram         import InlineKeyboardButton, InlineKeyboardMarkup

    await update.message.reply_text(
        text=SUPPORT_TEXT,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Chat Support", url="https://t.me/TelekuySupport")],
            [InlineKeyboardButton("🏠 Home",         callback_data="menu_home")],
        ]),
    )


async def _btn_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.start import build_welcome_caption, build_home_keyboard, _resize_logo

    tg_user   = update.effective_user
    user_data = upsert_user(
        user_id=tg_user.id,
        first_name=tg_user.first_name,
        last_name=tg_user.last_name,
        username=tg_user.username,
        language_code=tg_user.language_code,
    )

    caption    = build_welcome_caption(
        tg_user.id, tg_user.full_name,
        user_data.get("balance_idr", 0.0),
        user_data.get("total_spent",  0.0),
        user_data.get("total_orders", 0),
    )
    logo_bytes = _resize_logo()

    if logo_bytes:
        await update.message.reply_photo(
            photo=logo_bytes,
            caption=caption,
            parse_mode="HTML",
            reply_markup=build_home_keyboard(),
        )
    else:
        await update.message.reply_text(
            text=caption,
            parse_mode="HTML",
            reply_markup=build_home_keyboard(),
        )


def register_user_keyboard_handlers(app) -> None:
    """Daftarkan semua tombol user keyboard ke application."""
    # Hanya untuk non-admin
    not_admin = filters.TEXT & ~filters.User(ADMIN_ID)

    app.add_handler(MessageHandler(not_admin & filters.Regex(r"^🛒 Purchase$"),  _btn_purchase))
    app.add_handler(MessageHandler(not_admin & filters.Regex(r"^💳 Deposit$"),   _btn_deposit))
    app.add_handler(MessageHandler(not_admin & filters.Regex(r"^📋 Riwayat$"),   _btn_history))
    app.add_handler(MessageHandler(not_admin & filters.Regex(r"^🆘 Support$"),   _btn_support))
    app.add_handler(MessageHandler(not_admin & filters.Regex(r"^🏠 Home$"),      _btn_home))