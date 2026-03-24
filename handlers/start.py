"""
handlers/start.py
Handle /start dan callback menu_home (tombol Home dari halaman mana pun).
"""

import io
import os

from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from data.user_store import upsert_user
from utils.config        import DATA_DIR, ADMIN_ID
from utils.channel_guard import check_membership, is_member


LOGO_PATH = os.path.join(DATA_DIR, "logo.png")
LOGO_MAX_WIDTH  = 400
LOGO_MAX_HEIGHT = 200


def _resize_logo() -> bytes | None:
    if not os.path.exists(LOGO_PATH):
        return None
    with Image.open(LOGO_PATH) as img:
        img = img.convert("RGBA")
        img.thumbnail((LOGO_MAX_WIDTH, LOGO_MAX_HEIGHT), Image.LANCZOS)
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        buf = io.BytesIO()
        bg.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf.read()


def build_home_keyboard() -> InlineKeyboardMarkup:
    """Keyboard menu utama — bisa dipanggil dari handler lain untuk tombol Home."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛒 Purchase",      callback_data="menu_stock"),
        ],
        [
            InlineKeyboardButton("💳 Deposit",         callback_data="menu_deposit"),
            InlineKeyboardButton("📋 Riwayat Order",   callback_data="menu_history_order"),
        ],
        [
            InlineKeyboardButton("📥 Riwayat Deposit", callback_data="menu_history_deposit"),
            InlineKeyboardButton("🆘 Support",          callback_data="menu_support"),
        ],
        [
            InlineKeyboardButton("📜 Rules",           callback_data="menu_rules"),
        ],
    ])


def build_admin_reply_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard permanen di bawah chat — hanya untuk admin."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("📊 Total Users"),  KeyboardButton("🏆 Top 10 Deposit")],
            [KeyboardButton("📢 Broadcast"),    KeyboardButton("📦 Broadcast Stok")],
            [KeyboardButton("💸 Refund Saldo"), KeyboardButton("📋 Refund History")],
            [KeyboardButton("📂 List Deposit")],
        ],
        resize_keyboard=True,      # ukuran tombol lebih kecil, tidak memenuhi layar
        one_time_keyboard=False,   # keyboard tetap muncul, tidak hilang setelah diklik
        input_field_placeholder="Pilih menu admin...",
    )


def build_user_reply_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard permanen di bawah chat untuk user biasa."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("🛒 Purchase"),   KeyboardButton("💳 Deposit")],
            [KeyboardButton("📋 Riwayat"),    KeyboardButton("🆘 Support")],
            [KeyboardButton("🏠 Home")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Pilih menu...",
    )

def build_welcome_caption(user_id: int, full_name: str,
                          balance: float, spent: float, orders: int) -> str:
    name_link = f'<a href="tg://user?id={user_id}">{full_name}</a>'
    return (
        f"👋 Selamat datang, {name_link}\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"🏦 Balance: <b>{balance:.2f}</b>\n"
        f"💵 Total Spent: <b>{spent:.2f}</b>\n"
        f"✅ Total Purchased: <b>{orders}</b>\n"
        f"──────────────────────\n"
        f"Support @TelekuySupport"
    )


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk command /start."""
    tg_user = update.effective_user

    # Wajib join channel sebelum bisa pakai bot
    if not await check_membership(update, context):
        return

    user_data = upsert_user(
        user_id=tg_user.id,
        first_name=tg_user.first_name,
        last_name=tg_user.last_name,
        username=tg_user.username,
        language_code=tg_user.language_code,
    )

    caption  = build_welcome_caption(
        tg_user.id, tg_user.full_name,
        user_data.get("balance_idr", 0.0),
        user_data.get("total_spent",  0.0),
        user_data.get("total_orders", 0),
    )
    keyboard   = build_home_keyboard()
    logo_bytes = _resize_logo()

    if logo_bytes:
        await update.message.reply_photo(
            photo=logo_bytes,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        await update.message.reply_text(
            text=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    # Tampilkan reply keyboard admin di bawah chat
    if tg_user.id == ADMIN_ID:
        await update.message.reply_text(
            "⚙️ <b>Admin Panel aktif.</b>",
            parse_mode="HTML",
            reply_markup=build_admin_reply_keyboard(),
        )
    else:
        await update.message.reply_text(
            "Gunakan tombol di bawah untuk navigasi cepat 👇",
            reply_markup=build_user_reply_keyboard(),
        )


async def membership_check_callback(update, context) -> None:
    """
    Callback saat user klik [✅ Sudah Join].
    Cek ulang membership — kalau sudah, kirim welcome langsung via chat.
    """
    query   = update.callback_query
    tg_user = query.from_user

    if not await is_member(context.bot, tg_user.id):
        await query.answer(
            "❌ Kamu belum join channel. Silakan join dulu!",
            show_alert=True,
        )
        return

    await query.answer("✅ Verifikasi berhasil!")

    # Hapus pesan "wajib join"
    try:
        await query.delete_message()
    except Exception:
        pass

    # Simpan/update user
    user_data = upsert_user(
        user_id=tg_user.id,
        first_name=tg_user.first_name,
        last_name=tg_user.last_name,
        username=tg_user.username,
        language_code=tg_user.language_code,
    )

    caption  = build_welcome_caption(
        tg_user.id, tg_user.full_name,
        user_data.get("balance_idr", 0.0),
        user_data.get("total_spent",  0.0),
        user_data.get("total_orders", 0),
    )
    keyboard   = build_home_keyboard()
    logo_bytes = _resize_logo()

    # Kirim langsung ke chat via bot (bukan via update.message)
    if logo_bytes:
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=logo_bytes,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    if tg_user.id == ADMIN_ID:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⚙️ <b>Admin Panel aktif.</b>",
            parse_mode="HTML",
            reply_markup=build_admin_reply_keyboard(),
        )
    else:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Gunakan tombol di bawah untuk navigasi cepat 👇",
            reply_markup=build_user_reply_keyboard(),
        )


async def home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler untuk callback menu_home — tombol 🏠 Home dari halaman mana pun.
    Edit caption pesan kembali ke tampilan awal.
    """
    query    = update.callback_query
    tg_user  = query.from_user
    await query.answer()

    user_data = upsert_user(
        user_id=tg_user.id,
        first_name=tg_user.first_name,
        last_name=tg_user.last_name,
        username=tg_user.username,
        language_code=tg_user.language_code,
    )

    caption = build_welcome_caption(
        tg_user.id, tg_user.full_name,
        user_data.get("balance_idr", 0.0),
        user_data.get("total_spent",  0.0),
        user_data.get("total_orders", 0),
    )

    # Pesan bisa berupa foto (caption) atau teks biasa — handle keduanya
    msg = query.message
    if msg.photo or msg.document or msg.sticker:
        # Pesan dengan media → edit caption
        await query.edit_message_caption(
            caption=caption,
            parse_mode="HTML",
            reply_markup=build_home_keyboard(),
        )
    else:
        # Pesan teks biasa (dari halaman order, cancel, dll) → kirim pesan baru dengan logo
        try:
            await query.delete_message()
        except Exception:
            pass

        logo_bytes = _resize_logo()
        if logo_bytes:
            await query.message.chat.send_photo(
                photo=logo_bytes,
                caption=caption,
                parse_mode="HTML",
                reply_markup=build_home_keyboard(),
            )
        else:
            await query.message.chat.send_message(
                text=caption,
                parse_mode="HTML",
                reply_markup=build_home_keyboard(),
            )


async def cancel_and_restart(update, context) -> int:
    """
    Dipanggil saat user ketik /start di tengah conversation aktif.
    Bersihkan semua state lalu jalankan start_handler seperti biasa.
    """
    from telegram.ext import ConversationHandler

    # Bersihkan semua state conversation yang mungkin aktif
    context.user_data.clear()

    # Jalankan start flow normal
    await start_handler(update, context)

    return ConversationHandler.END