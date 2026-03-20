"""
handlers/deposit.py

Flow Deposit:
  Klik [💳 Deposit]
    → pilih metode (QRIS / Transfer Manual)
    → input nominal                          STATE: WAITING_AMOUNT
    → tampil info pembayaran + kode unik
    → user upload bukti (foto)               STATE: WAITING_PROOF
    → bot simpan pending deposit
    → notif ke admin + tombol [✅ Approve] [❌ Reject]
    → admin approve → saldo user bertambah + notif user
    → admin reject  → notif user, deposit dibatalkan
"""

import random
import os
from datetime import datetime
from utils.helpers import now_wib
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
import logging
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

from data.user_store    import get_user, update_balance
from handlers.start     import cancel_and_restart
from data.deposit_store import create_deposit, confirm_deposit, fail_deposit, get_user_deposits
from utils.config       import ADMIN_ID

# States
WAITING_AMOUNT = 10
WAITING_PROOF  = 11

# Keys
_KEY_METHOD    = "dep_method"
_KEY_AMOUNT    = "dep_amount"
_KEY_UNIQUE    = "dep_unique"
_KEY_DEP_ID    = "dep_id"
_KEY_MSG_ID    = "dep_msg_id"

PROOF_DIR   = Path(__file__).parent.parent / "storage" / "deposit_proofs"
PROOF_DIR.mkdir(parents=True, exist_ok=True)

MIN_DEPOSIT = 10_000
MAX_DEPOSIT = 10_000_000

# ── Payment info ─────────────────────────────────────────────────────────────

PAYMENT_METHODS = {
    "Dana":          "085363779773",
    "Gopay":         "083186319333",
    "OVO":           "085363779773",
    "SeaBank":       "901770835715",
    "Jago Syariah":  "505046381858",
}
PAYMENT_AN = "Ahmad Rizki Akbar Ganiyu"

QRIS_CHANNEL = "https://t.me/TelekuyPayment/3"


def _fmt(n) -> str:
    try:
        return f"{int(float(n)):,}"
    except Exception:
        return str(n)


def _gen_unique() -> int:
    """Generate kode unik 100–999."""
    return random.randint(100, 999)


def _build_payment_info(method: str, amount: int, unique: int) -> str:
    total = amount + unique
    if method == "QRIS":
        return (
            f"💳 <b>Deposit via QRIS</b>\n"
            f"──────────────────────\n"
            f"📎 Scan QRIS: {QRIS_CHANNEL}\n\n"
            f"💰 Nominal    : <b>{_fmt(amount)} IDR</b>\n"
            f"🔢 Kode Unik  : <b>+{unique}</b>\n"
            f"💸 <b>Total Bayar : {_fmt(total)} IDR</b>\n\n"
            f"⚠️ Bayar tepat <b>{_fmt(total)} IDR</b> agar kode unik terdeteksi.\n"
            f"⏳ Batas waktu pembayaran: <b>30 menit</b>"
        )
    else:
        number = PAYMENT_METHODS.get(method, "-")
        return (
            f"💳 <b>Deposit via {method}</b>\n"
            f"──────────────────────\n"
            f"👤 A/n    : <b>{PAYMENT_AN}</b>\n"
            f"📱 Nomor  : <code>{number}</code>\n\n"
            f"💰 Nominal    : <b>{_fmt(amount)} IDR</b>\n"
            f"🔢 Kode Unik  : <b>+{unique}</b>\n"
            f"💸 <b>Total Bayar : {_fmt(total)} IDR</b>\n\n"
            f"⚠️ Transfer tepat <b>{_fmt(total)} IDR</b> agar kode unik terdeteksi.\n"
            f"⏳ Batas waktu pembayaran: <b>30 menit</b>"
        )


# ── Entry: pilih metode ───────────────────────────────────────────────────────

async def show_deposit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Klik [💳 Deposit] dari home — tampil pilihan metode."""
    query = update.callback_query
    await query.answer()

    text = (
        "💳 <b>Deposit Saldo</b>\n"
        "──────────────────────\n"
        f"Min. deposit : <b>{_fmt(MIN_DEPOSIT)} IDR</b>\n"
        f"Max. deposit : <b>{_fmt(MAX_DEPOSIT)} IDR</b>\n\n"
        "Pilih metode pembayaran:"
    )

    rows = [[InlineKeyboardButton("📷 QRIS", callback_data="dep_method_QRIS")]]
    rows += [
        [InlineKeyboardButton(f"💸 {m}", callback_data=f"dep_method_{m}")]
        for m in PAYMENT_METHODS
    ]
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="menu_home")])

    msg = query.message
    try:
        if msg.photo or msg.document:
            await query.edit_message_caption(
                caption=text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(rows),
            )
        else:
            await query.edit_message_text(
                text=text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(rows),
            )
    except BadRequest:
        pass


# ── Step 1: pilih metode → minta nominal ─────────────────────────────────────

async def pick_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    method = query.data.replace("dep_method_", "")
    context.user_data[_KEY_METHOD] = method

    logger.info(f"[DEPOSIT] user={query.from_user.id} pilih metode={method}")

    sent: Message = await query.message.reply_text(
        text=(
            f"💳 <b>Deposit via {method}</b>\n"
            f"──────────────────────\n"
            f"Masukkan nominal deposit (IDR).\n"
            f"Min: <b>{_fmt(MIN_DEPOSIT)}</b>  |  Max: <b>{_fmt(MAX_DEPOSIT)}</b>\n\n"
            f"Contoh: <code>50000</code>\n"
            f"Ketik /cancel untuk batal."
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="dep_cancel")]
        ]),
    )
    context.user_data[_KEY_MSG_ID] = sent.message_id
    return WAITING_AMOUNT


# ── Step 2: terima nominal ────────────────────────────────────────────────────

async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip().replace(".", "").replace(",", "")

    if not text.isdigit():
        await update.message.reply_text(
            "⚠️ Masukkan angka saja, tanpa titik/koma. Contoh: <code>50000</code>",
            parse_mode="HTML",
        )
        return WAITING_AMOUNT

    amount = int(text)
    if amount < MIN_DEPOSIT:
        await update.message.reply_text(
            f"⚠️ Minimal deposit <b>{_fmt(MIN_DEPOSIT)} IDR</b>.",
            parse_mode="HTML",
        )
        return WAITING_AMOUNT
    if amount > MAX_DEPOSIT:
        await update.message.reply_text(
            f"⚠️ Maksimal deposit <b>{_fmt(MAX_DEPOSIT)} IDR</b>.",
            parse_mode="HTML",
        )
        return WAITING_AMOUNT

    method = context.user_data.get(_KEY_METHOD, "?")
    unique = _gen_unique()
    total  = amount + unique

    context.user_data[_KEY_AMOUNT] = amount
    context.user_data[_KEY_UNIQUE] = unique

    logger.info(f"[DEPOSIT] user={update.effective_user.id} metode={method} nominal={amount} unik={unique} total={amount+unique}")

    # Simpan ke deposit_store sebagai pending
    record = create_deposit(update.effective_user.id, method, amount, unique)
    context.user_data[_KEY_DEP_ID] = record["deposit_id"]

    # Hapus pesan prompt
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data.get(_KEY_MSG_ID, 0),
        )
    except Exception:
        pass

    payment_text = _build_payment_info(method, amount, unique)

    sent: Message = await update.message.reply_text(
        text=(
            f"{payment_text}\n\n"
            f"──────────────────────\n"
            f"📸 Setelah transfer, kirim <b>screenshot bukti pembayaran</b> di sini."
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="dep_cancel")]
        ]),
    )
    context.user_data[_KEY_MSG_ID] = sent.message_id
    return WAITING_PROOF


# ── Step 3: terima bukti foto ─────────────────────────────────────────────────

async def receive_proof(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.photo:
        await update.message.reply_text(
            "📸 Kirim <b>foto/screenshot</b> bukti transfer ya.",
            parse_mode="HTML",
        )
        return WAITING_PROOF

    method     = context.user_data.get(_KEY_METHOD, "?")
    amount     = context.user_data.get(_KEY_AMOUNT, 0)
    unique     = context.user_data.get(_KEY_UNIQUE, 0)
    total      = amount + unique
    dep_id     = context.user_data.get(_KEY_DEP_ID, "-")
    tg_user    = update.effective_user
    photo_id   = update.message.photo[-1].file_id
    logger.info(f"[DEPOSIT] user={tg_user.id} dep_id={dep_id} bukti dikirim, menunggu approval admin")

    # ── Simpan bukti ke storage/deposit_proofs/ ───────────────────────────
    try:
        date_str  = now_wib().strftime("%Y%m%d")
        filename  = f"{date_str}_{dep_id}_{tg_user.id}.jpg"
        file_path = PROOF_DIR / filename

        tg_file   = await update.message.photo[-1].get_file()
        await tg_file.download_to_drive(str(file_path))
    except Exception as e:
        logger.warning(f"Gagal simpan bukti deposit {dep_id}: {e}")

    # Konfirmasi ke user
    await update.message.reply_text(
        text=(
            f"✅ <b>Bukti diterima!</b>\n"
            f"──────────────────────\n"
            f"💳 Metode  : <b>{method}</b>\n"
            f"💸 Total   : <b>{_fmt(total)} IDR</b>\n"
            f"🔖 ID      : <code>{dep_id}</code>\n\n"
            f"⏳ Menunggu konfirmasi admin.\n"
            f"Saldo akan otomatis bertambah setelah disetujui."
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="menu_home")]
        ]),
    )

    # Notif ke admin
    username   = f"@{tg_user.username}" if tg_user.username else tg_user.full_name
    admin_text = (
        f"🔔 <b>Deposit Baru</b>\n"
        f"──────────────────────\n"
        f"👤 User    : {username} (<code>{tg_user.id}</code>)\n"
        f"💳 Metode  : <b>{method}</b>\n"
        f"💰 Nominal : <b>{_fmt(amount)} IDR</b>\n"
        f"🔢 Unik    : <b>+{unique}</b>\n"
        f"💸 Total   : <b>{_fmt(total)} IDR</b>\n"
        f"🔖 ID      : <code>{dep_id}</code>"
    )
    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"adm_dep_approve_{tg_user.id}_{dep_id}_{amount}"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"adm_dep_reject_{tg_user.id}_{dep_id}"),
        ]
    ])

    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_id,
            caption=admin_text,
            parse_mode="HTML",
            reply_markup=admin_kb,
        )
    except Exception as e:
        # Kalau gagal kirim ke admin, tetap catat di log
        import logging
        logging.getLogger(__name__).error(f"Gagal notif admin: {e}")

    _clear_dep_data(context)
    return ConversationHandler.END


# ── Admin: approve / reject ───────────────────────────────────────────────────

async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Bukan admin.", show_alert=True)
        return

    await query.answer()

    # parse: adm_dep_approve_{user_id}_{dep_id}_{amount}
    parts   = query.data.split("_")
    # format: adm dep approve {user_id} {dep_id} {amount}
    #  idx:    0   1   2       3         4...     last
    user_id = int(parts[3])
    amount  = int(parts[-1])
    dep_id  = "_".join(parts[4:-1])   # dep_id bisa mengandung underscore

    # Guard double approve — cek dulu sebelum update saldo
    confirmed = confirm_deposit(user_id, dep_id)
    if confirmed is None:
        # Sudah pernah di-approve sebelumnya
        logger.warning(f"[DEPOSIT] DOUBLE APPROVE BLOCKED dep_id={dep_id} user={user_id}")
        await query.answer("⚠️ Deposit ini sudah pernah di-approve!", show_alert=True)
        return

    # Update saldo user
    try:
        new_balance = update_balance(user_id, amount, track_spent=False)
        logger.info(f"[DEPOSIT] APPROVED dep_id={dep_id} user={user_id} +{amount:,} IDR saldo_baru={new_balance:,}")
    except Exception as e:
        logger.error(f"[DEPOSIT] APPROVE FAILED dep_id={dep_id} user={user_id} error={e}")
        await query.edit_message_caption(
            caption=query.message.caption + f"\n\n❌ Gagal update saldo: {e}",
            parse_mode="HTML",
        )
        return

    # Edit pesan admin
    await query.edit_message_caption(
        caption=query.message.caption + f"\n\n✅ <b>APPROVED</b> — Saldo +{_fmt(amount)} IDR",
        parse_mode="HTML",
        reply_markup=None,
    )

    # Notif ke user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ <b>Deposit Disetujui!</b>\n"
                f"──────────────────────\n"
                f"💰 Ditambahkan : <b>+{_fmt(amount)} IDR</b>\n"
                f"💳 Saldo baru  : <b>{_fmt(new_balance)} IDR</b>\n\n"
                f"Terima kasih sudah deposit di Telekuy! 🎉"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Purchase", callback_data="menu_stock")],
                [InlineKeyboardButton("🏠 Home",     callback_data="menu_home")],
            ]),
        )
    except Exception:
        pass


async def admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Bukan admin.", show_alert=True)
        return

    await query.answer()

    # parse: adm_dep_reject_{user_id}_{dep_id}
    parts   = query.data.split("_")
    user_id = int(parts[3])
    dep_id  = "_".join(parts[4:])

    fail_deposit(user_id, dep_id)
    logger.info(f"[DEPOSIT] REJECTED dep_id={dep_id} user={user_id}")

    await query.edit_message_caption(
        caption=query.message.caption + "\n\n❌ <b>REJECTED</b>",
        parse_mode="HTML",
        reply_markup=None,
    )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"❌ <b>Deposit Ditolak</b>\n"
                f"──────────────────────\n"
                f"Deposit kamu dengan ID <code>{dep_id}</code> ditolak oleh admin.\n\n"
                f"Jika ada pertanyaan hubungi @TelekuySupport."
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="menu_home")]
            ]),
        )
    except Exception:
        pass


# ── Cancel ────────────────────────────────────────────────────────────────────

async def cancel_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Tandai deposit pending sebagai failed kalau sudah dibuat
    dep_id = context.user_data.get(_KEY_DEP_ID)
    if dep_id:
        fail_deposit(update.effective_user.id, dep_id)
        logger.info(f"[DEPOSIT] CANCELLED dep_id={dep_id} user={update.effective_user.id}")

    query = update.callback_query if update.callback_query else None
    if query:
        await query.answer()
        try:
            await query.edit_message_text(
                text="❌ Deposit dibatalkan.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Home", callback_data="menu_home")]
                ]),
            )
        except BadRequest:
            pass
    else:
        await update.message.reply_text(
            "❌ Deposit dibatalkan.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="menu_home")]
            ]),
        )

    _clear_dep_data(context)
    return ConversationHandler.END


# ── Utils ─────────────────────────────────────────────────────────────────────

def _clear_dep_data(context) -> None:
    for k in [_KEY_METHOD, _KEY_AMOUNT, _KEY_UNIQUE, _KEY_DEP_ID, _KEY_MSG_ID]:
        context.user_data.pop(k, None)


async def _fallback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_dep_data(context)
    await context.application.process_update(update)
    return ConversationHandler.END


# ── History Deposit ───────────────────────────────────────────────────────────

async def show_history_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    deposits = get_user_deposits(update.effective_user.id, limit=10)

    if not deposits:
        text = (
            "📥 <b>Riwayat Deposit</b>\n"
            "──────────────────────\n"
            "Belum ada riwayat deposit."
        )
    else:
        STATUS_ICON = {"confirmed": "✅", "pending": "⏳", "failed": "❌"}
        lines = ["📥 <b>Riwayat Deposit</b>\n──────────────────────"]
        for d in deposits:
            icon   = STATUS_ICON.get(d.get("status", ""), "❓")
            method = d.get("method", "-")
            amount = _fmt(d.get("amount_total", 0))
            date   = d.get("created_at", "")[:16].replace("T", " ")
            dep_id = d.get("deposit_id", "-")
            lines.append(
                f"\n{icon} <code>{dep_id}</code>\n"
                f"   💳 {method}  💰 {amount} IDR\n"
                f"   🕐 {date}"
            )
        text = "\n".join(lines)

    msg = query.message
    kb  = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="menu_home")]])
    try:
        if msg.photo or msg.document:
            await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        else:
            await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=kb)
    except BadRequest:
        pass


# ── ConversationHandler factory ───────────────────────────────────────────────

def build_deposit_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(pick_method, pattern=r"^dep_method_"),
        ],
        states={
            WAITING_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount),
                CallbackQueryHandler(cancel_deposit, pattern=r"^dep_cancel$"),
            ],
            WAITING_PROOF: [
                MessageHandler(filters.PHOTO, receive_proof),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: u.message.reply_text(
                    "📸 Kirim <b>foto</b> bukti transfer ya.", parse_mode="HTML"
                ) or WAITING_PROOF),
                CallbackQueryHandler(cancel_deposit, pattern=r"^dep_cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("start",              cancel_and_restart),
            MessageHandler(filters.Regex(r"^/cancel$"), cancel_deposit),
            CallbackQueryHandler(cancel_deposit,  pattern=r"^dep_cancel$"),
            CallbackQueryHandler(_fallback_menu,  pattern=r"^menu_"),
        ],
        per_message=False,
        per_chat=True,
        per_user=True,
    )