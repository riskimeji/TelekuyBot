"""
handlers/admin.py

Fitur admin:
  /broadcast <text>     → broadcast teks custom ke semua user
  /broadcast_stock      → broadcast kategori + stok terkini
  /totalusers           → total user terdaftar
  /top10deposit         → top 10 user depositor 30 hari terakhir
"""

import logging
import asyncio
from datetime import timedelta
from utils.helpers import now_wib, fmt_date_wib

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, ConversationHandler, filters
from telegram.error import Forbidden, BadRequest

from data.user_store    import get_all_users, get_user, update_balance
from data.refund_store  import save_refund, get_all_refunds, get_refunds_by_user
from data.deposit_store import get_user_deposits
from services.laravel_api import get_categories
from utils.config import ADMIN_ID
from handlers.deposit import admin_list_deposits

logger = logging.getLogger(__name__)


# ── guard decorator ───────────────────────────────────────────────────────────

def admin_only(func):
    """Decorator — tolak kalau bukan admin."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ Akses ditolak.")
            return
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper


# ── /broadcast <text> ─────────────────────────────────────────────────────────

@admin_only
async def broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /broadcast Halo semua! Ada promo hari ini.
    Kirim teks custom ke semua user yang pernah /start.
    """
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text(
            "⚠️ Penggunaan: /broadcast <pesan>\n"
            "Contoh: /broadcast Halo! Ada promo hari ini 🎉"
        )
        return

    users    = get_all_users()
    total    = len(users)
    sent     = 0
    failed   = 0

    broadcast_text = (
        f"📢 <b>Pengumuman Telekuy</b>\n"
        f"──────────────────────\n"
        f"{text}"
    )

    status_msg = await update.message.reply_text(
        f"⏳ Mengirim ke {total} user..."
    )

    for uid, udata in users.items():
        if udata.get("is_banned"):
            continue
        try:
            await context.bot.send_message(
                chat_id=int(uid),
                text=broadcast_text,
                parse_mode="HTML",
            )
            sent += 1
        except (Forbidden, BadRequest):
            failed += 1
        except Exception as e:
            logger.warning(f"Broadcast gagal ke {uid}: {e}")
            failed += 1
        await asyncio.sleep(0.05)   # hindari flood limit Telegram

    await status_msg.edit_text(
        f"✅ <b>Broadcast selesai!</b>\n"
        f"──────────────────────\n"
        f"📨 Terkirim : <b>{sent}</b>\n"
        f"❌ Gagal    : <b>{failed}</b>\n"
        f"👥 Total    : <b>{total}</b>",
        parse_mode="HTML",
    )


# ── /broadcast_stock ──────────────────────────────────────────────────────────

@admin_only
async def broadcast_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /broadcast_stock
    Ambil stok terkini dari Laravel lalu broadcast ke semua user.
    """
    await update.message.reply_text("⏳ Mengambil data stok...")

    try:
        categories = get_categories()
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal ambil stok: {e}")
        return

    if not categories:
        await update.message.reply_text("📭 Tidak ada kategori tersedia.")
        return

    # Susun pesan stok
    lines = [
        "🛒 <b>Update Stok Telekuy</b>",
        "──────────────────────",
    ]
    for cat in categories:
        stock = cat.get("total_stock", 0)
        name  = cat.get("name", "?")
        icon  = "✅" if stock > 0 else "❌"
        lines.append(f"{icon} {name} — <b>{stock:,}</b> akun")

    lines += [
        "──────────────────────",
        "🛍 Beli sekarang di bot ini!",
    ]
    text = "\n".join(lines)

    users  = get_all_users()
    total  = len(users)
    sent   = 0
    failed = 0

    status_msg = await update.message.reply_text(
        f"⏳ Mengirim stok ke {total} user..."
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Purchase", callback_data="menu_stock")]
    ])

    for uid, udata in users.items():
        if udata.get("is_banned"):
            continue
        try:
            await context.bot.send_message(
                chat_id=int(uid),
                text=text,
                parse_mode="HTML",
                reply_markup=kb,
            )
            sent += 1
        except (Forbidden, BadRequest):
            failed += 1
        except Exception as e:
            logger.warning(f"Broadcast stock gagal ke {uid}: {e}")
            failed += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ <b>Broadcast stok selesai!</b>\n"
        f"──────────────────────\n"
        f"📨 Terkirim : <b>{sent}</b>\n"
        f"❌ Gagal    : <b>{failed}</b>",
        parse_mode="HTML",
    )


# ── /totalusers ───────────────────────────────────────────────────────────────

@admin_only
async def total_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/totalusers — statistik user terdaftar."""
    users  = get_all_users()
    total  = len(users)
    banned = sum(1 for u in users.values() if u.get("is_banned"))
    active = total - banned

    # Bergabung hari ini
    today      = now_wib().date().isoformat()
    new_today  = sum(
        1 for u in users.values()
        if u.get("joined_at", "")[:10] == today
    )

    # Akumulasi saldo & total spent seluruh user
    total_balance = sum(u.get("balance_idr", 0.0) for u in users.values())
    total_spent   = sum(u.get("total_spent",  0.0) for u in users.values())

    def _fmt(n):
        try:
            return f"{int(float(n)):,}"
        except Exception:
            return str(n)

    await update.message.reply_text(
        f"👥 <b>Statistik User</b>\n"
        f"──────────────────────\n"
        f"📊 Total terdaftar : <b>{total}</b>\n"
        f"✅ Aktif           : <b>{active}</b>\n"
        f"🚫 Banned          : <b>{banned}</b>\n"
        f"🆕 Baru hari ini   : <b>{new_today}</b>\n"
        f"──────────────────────\n"
        f"💰 Total saldo user  : <b>Rp {_fmt(total_balance)}</b>\n"
        f"💸 Total sudah spend : <b>Rp {_fmt(total_spent)}</b>",
        parse_mode="HTML",
    )


# ── /top10deposit ─────────────────────────────────────────────────────────────

@admin_only
async def top10_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/top10deposit — top 10 user berdasarkan total deposit confirmed 30 hari terakhir."""
    users    = get_all_users()
    cutoff   = (now_wib() - timedelta(days=30)).isoformat()
    ranking  = []

    for uid, udata in users.items():
        deposits = get_user_deposits(int(uid), limit=200)
        total_dep = sum(
            d.get("amount_total", d.get("amount_total", 0))
            for d in deposits
            if d.get("status") == "confirmed"
            and d.get("confirmed_at", "") >= cutoff
        )
        if total_dep > 0:
            name = udata.get("first_name", "?")
            if udata.get("username"):
                name = f"@{udata['username']}"
            ranking.append((name, int(uid), total_dep))

    ranking.sort(key=lambda x: x[2], reverse=True)
    top10 = ranking[:10]

    if not top10:
        await update.message.reply_text("📭 Belum ada deposit confirmed dalam 30 hari terakhir.")
        return

    lines = ["🏆 <b>Top 10 Depositor (30 hari)</b>\n──────────────────────"]
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    for i, (name, uid, amount) in enumerate(top10):
        lines.append(f"{medals[i]} {name} — <b>{amount:,} IDR</b>")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
    )


# ── Handler list untuk bot.py ─────────────────────────────────────────────────

# ── /refundhistory ───────────────────────────────────────────────────────────

@admin_only
async def refund_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /refundhistory           → 20 refund terakhir
    /refundhistory 977027817 → history refund user tertentu
    """
    args = context.args if hasattr(context, "args") and context.args else []

    if args:
        try:
            uid     = int(args[0])
            records = get_refunds_by_user(uid)
            title   = f"📋 <b>History Refund — User {uid}</b>"
        except ValueError:
            await update.message.reply_text("⚠️ Format: /refundhistory [user_id]")
            return
    else:
        records = get_all_refunds(limit=20)
        title   = "📋 <b>History Refund (20 terakhir)</b>"

    if not records:
        await update.message.reply_text(
            f"{title}\n──────────────────────\nBelum ada data refund.",
            parse_mode="HTML",
        )
        return

    lines = [f"{title}\n──────────────────────"]
    for r in records:
        date   = r.get("created_at", "")[:16].replace("T", " ")
        name   = r.get("target_name", str(r.get("target_uid", "-")))
        amount = r.get("amount", 0)
        reason = r.get("reason", "-")
        rid    = r.get("refund_id", "-")
        lines.append(
            f"\n💸 <code>{rid}</code>\n"
            f"   👤 {name}  |  +{amount:,} IDR\n"
            f"   📝 {reason}\n"
            f"   🕐 {date}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
    )


# ── Reply keyboard button handlers ───────────────────────────────────────────

@admin_only
async def btn_total_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tombol '📊 Total Users' dari reply keyboard."""
    await total_users(update, context)


@admin_only
async def btn_top10(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tombol '🏆 Top 10 Deposit' dari reply keyboard."""
    await top10_deposit(update, context)


@admin_only
async def btn_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tombol '📢 Broadcast' — minta admin ketik pesan."""
    await update.message.reply_text(
        "✏️ Ketik pesan broadcast:\n"
        "Format: /broadcast <pesan kamu>\n\n"
        "Contoh: /broadcast Halo! Ada promo hari ini 🎉"
    )


@admin_only
async def btn_broadcast_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tombol '📦 Broadcast Stok' dari reply keyboard."""
    await broadcast_stock(update, context)


@admin_only
async def btn_refund_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tombol '📋 Refund History' dari reply keyboard."""
    context.args = []
    await refund_history(update, context)

@admin_only
async def btn_list_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tombol '📂 List Deposit' dari reply keyboard."""
    await admin_list_deposits(update, context)

def get_admin_handlers():
    return [
        # Commands
        CommandHandler("broadcast",       broadcast_text),
        CommandHandler("broadcast_stock", broadcast_stock),
        CommandHandler("totalusers",      total_users),
        CommandHandler("top10deposit",    top10_deposit),
        CommandHandler("refundhistory",   refund_history),
        CommandHandler("listdeposit",     admin_list_deposits),
        # Reply keyboard buttons (filter teks exact)
        MessageHandler(filters.Regex(r"^📊 Total Users$"),    btn_total_users),
        MessageHandler(filters.Regex(r"^🏆 Top 10 Deposit$"), btn_top10),
        MessageHandler(filters.Regex(r"^📢 Broadcast$"),      btn_broadcast),
        MessageHandler(filters.Regex(r"^📦 Broadcast Stok$"), btn_broadcast_stock),
        MessageHandler(filters.Regex(r"^💸 Refund Saldo$"),   start_refund),
        MessageHandler(filters.Regex(r"^📋 Refund History$"),  btn_refund_history),
        MessageHandler(filters.Regex(r"^📂 List Deposit$"),    btn_list_deposit),
    ]


# ── Refund / Transfer Saldo ───────────────────────────────────────────────────
# Flow:
#   Admin klik tombol atau ketik /refund
#   → bot minta: user_id dan jumlah
#   → admin input: "977027817 50000"
#   → bot update saldo user + notif user

WAITING_REFUND = 20  # conversation state


@admin_only
async def start_refund(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point refund — dari tombol atau /refund command."""
    await update.message.reply_text(
        "💸 <b>Refund / Transfer Saldo</b>\n"
        "──────────────────────\n"
        "Kirim dalam format:\n"
        "<code>USER_ID JUMLAH ALASAN</code>\n\n"
        "Contoh:\n"
        "<code>977027817 50000 Refund order gagal</code>\n\n"
        "Ketik /cancel untuk batal.",
        parse_mode="HTML",
    )
    return WAITING_REFUND


@admin_only
async def process_refund(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Terima input admin: user_id jumlah alasan."""
    parts = (update.message.text or "").strip().split(maxsplit=2)

    if len(parts) < 2:
        await update.message.reply_text(
            "⚠️ Format salah. Contoh:\n"
            "<code>977027817 50000 Refund order gagal</code>",
            parse_mode="HTML",
        )
        return WAITING_REFUND

    # Parse input
    try:
        target_uid = int(parts[0])
        amount     = int(parts[1].replace(".", "").replace(",", ""))
        reason     = parts[2] if len(parts) > 2 else "Refund dari admin"
    except ValueError:
        await update.message.reply_text(
            "⚠️ User ID dan jumlah harus angka.\n"
            "Contoh: <code>977027817 50000</code>",
            parse_mode="HTML",
        )
        return WAITING_REFUND

    if amount <= 0:
        await update.message.reply_text("⚠️ Jumlah harus lebih dari 0.")
        return WAITING_REFUND

    # Cek user ada
    user_data = get_user(target_uid)
    if not user_data:
        await update.message.reply_text(
            f"❌ User <code>{target_uid}</code> tidak ditemukan.",
            parse_mode="HTML",
        )
        return WAITING_REFUND

    # Update saldo
    try:
        new_balance = update_balance(target_uid, amount, track_spent=False)
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal update saldo: {e}")
        return WAITING_REFUND

    name     = user_data.get("first_name", str(target_uid))
    username = f"@{user_data['username']}" if user_data.get("username") else name

    # Simpan ke refund_store
    save_refund(
        target_uid=target_uid,
        target_name=username,
        amount=amount,
        reason=reason,
        balance_after=new_balance,
    )

    # Konfirmasi ke admin
    await update.message.reply_text(
        f"✅ <b>Saldo berhasil ditransfer!</b>\n"
        f"──────────────────────\n"
        f"👤 User       : {username} (<code>{target_uid}</code>)\n"
        f"💰 Jumlah     : <b>+{amount:,} IDR</b>\n"
        f"💳 Saldo baru : <b>{new_balance:,} IDR</b>\n"
        f"📝 Alasan     : {reason}",
        parse_mode="HTML",
    )

    # Notif ke user
    try:
        await context.bot.send_message(
            chat_id=target_uid,
            text=(
                f"💰 <b>Saldo Kamu Bertambah!</b>\n"
                f"──────────────────────\n"
                f"💸 Ditambahkan : <b>+{amount:,} IDR</b>\n"
                f"💳 Saldo baru  : <b>{new_balance:,} IDR</b>\n"
                f"📝 Keterangan  : {reason}\n\n"
                f"Terima kasih telah menggunakan Telekuy! 🎉"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Purchase", callback_data="menu_stock")],
                [InlineKeyboardButton("🏠 Home",     callback_data="menu_home")],
            ]),
        )
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Saldo berhasil diupdate tapi gagal notif ke user: {e}"
        )

    return ConversationHandler.END


async def cancel_refund(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Refund dibatalkan.")
    return ConversationHandler.END


def build_refund_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("refund",                    start_refund),
            MessageHandler(filters.Regex(r"^💸 Refund Saldo$"), start_refund),
        ],
        states={
            WAITING_REFUND: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_refund),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_refund),
        ],
        per_chat=True,
        per_user=True,
    )