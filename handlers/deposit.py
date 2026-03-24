"""
handlers/deposit.py

Flow Deposit:
  Klik [💳 Deposit]
    → pilih metode
    → input nominal                          STATE: WAITING_AMOUNT
    → tampil info pembayaran + kode unik
    → user upload bukti (foto)               STATE: WAITING_PROOF
    → bot simpan pending deposit
    → notif ke admin + tombol Approve/Reject
    → admin approve → saldo user bertambah (nominal asli, tanpa kode unik)
    → admin reject  → notif user
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

from data.user_store    import update_balance
from data.deposit_store import (
    create_deposit, confirm_deposit, fail_deposit,
    get_user_deposits, get_all_deposits,
)
from utils.config       import ADMIN_ID
from handlers.start     import cancel_and_restart

logger = logging.getLogger(__name__)

# States
WAITING_AMOUNT = 10
WAITING_PROOF  = 11

# Keys
_KEY_METHOD    = "dep_method"
_KEY_AMOUNT    = "dep_amount"
_KEY_UNIQUE    = "dep_unique"
_KEY_DEP_ID    = "dep_id"
_KEY_MSG_ID    = "dep_msg_id"

MIN_DEPOSIT = 10_000
MAX_DEPOSIT = 10_000_000

PROOF_DIR = Path(__file__).parent.parent / "storage" / "deposit_proofs"
PROOF_DIR.mkdir(parents=True, exist_ok=True)

PAYMENT_METHODS = {
    "Dana":         "085363779773",
    "Gopay":        "083186319333",
    "OVO":          "085363779773",
    "SeaBank":      "901770835715",
    "Jago Syariah": "505046381858",
}
PAYMENT_AN  = "Ahmad Rizki Akbar Ganiyu"
QRIS_CHANNEL = "https://t.me/TelekuyPayment/3"


def _fmt(n) -> str:
    try:
        return f"{int(float(n)):,}"
    except Exception:
        return str(n)


def _gen_unique() -> int:
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
            f"⚠️ Transfer tepat <b>{_fmt(total)} IDR</b> agar terdeteksi.\n"
            f"⏳ Batas waktu: <b>30 menit</b>"
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
            f"⚠️ Transfer tepat <b>{_fmt(total)} IDR</b> agar terdeteksi.\n"
            f"⏳ Batas waktu: <b>30 menit</b>"
        )


# ── Show deposit menu ─────────────────────────────────────────────────────────

async def show_deposit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    text = (
        f"💳 <b>Deposit Saldo</b>\n"
        f"──────────────────────\n"
        f"Min. deposit : <b>{_fmt(MIN_DEPOSIT)} IDR</b>\n"
        f"Max. deposit : <b>{_fmt(MAX_DEPOSIT)} IDR</b>\n\n"
        f"Pilih metode pembayaran:"
    )
    rows  = [[InlineKeyboardButton("📷 QRIS", callback_data="dep_method_QRIS")]]
    rows += [[InlineKeyboardButton(f"💸 {m}", callback_data=f"dep_method_{m}")] for m in PAYMENT_METHODS]
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="menu_home")])

    msg = query.message
    try:
        if msg.photo or msg.document:
            await query.edit_message_caption(caption=text, parse_mode="HTML",
                                             reply_markup=InlineKeyboardMarkup(rows))
        else:
            await query.edit_message_text(text=text, parse_mode="HTML",
                                          reply_markup=InlineKeyboardMarkup(rows))
    except BadRequest:
        pass


# ── Step 1: pilih metode ──────────────────────────────────────────────────────

async def pick_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query  = update.callback_query
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
            f"⚠️ Minimal deposit <b>{_fmt(MIN_DEPOSIT)} IDR</b>.", parse_mode="HTML")
        return WAITING_AMOUNT
    if amount > MAX_DEPOSIT:
        await update.message.reply_text(
            f"⚠️ Maksimal deposit <b>{_fmt(MAX_DEPOSIT)} IDR</b>.", parse_mode="HTML")
        return WAITING_AMOUNT

    method = context.user_data.get(_KEY_METHOD, "?")
    unique = _gen_unique()
    total  = amount + unique

    context.user_data[_KEY_AMOUNT] = amount
    context.user_data[_KEY_UNIQUE] = unique

    logger.info(f"[DEPOSIT] user={update.effective_user.id} metode={method} nominal={amount} unik={unique} total={total}")

    record = create_deposit(update.effective_user.id, method, amount, unique)
    context.user_data[_KEY_DEP_ID] = record["deposit_id"]

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
            "📸 Kirim <b>foto/screenshot</b> bukti transfer ya.", parse_mode="HTML")
        return WAITING_PROOF

    method   = context.user_data.get(_KEY_METHOD, "?")
    amount   = context.user_data.get(_KEY_AMOUNT, 0)
    unique   = context.user_data.get(_KEY_UNIQUE, 0)
    total    = amount + unique
    dep_id   = context.user_data.get(_KEY_DEP_ID, "-")
    tg_user  = update.effective_user
    photo_id = update.message.photo[-1].file_id

    logger.info(f"[DEPOSIT] user={tg_user.id} dep_id={dep_id} bukti dikirim, menunggu approval admin")

    # Simpan bukti ke storage
    try:
        date_str  = datetime.now().strftime("%Y%m%d")
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
            f"💰 Nominal : <b>{_fmt(amount)} IDR</b>\n"
            f"🔢 Kode Unik: <b>+{unique}</b>\n"
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
        f"🔢 Kode Unik: <b>+{unique}</b>\n"
        f"💸 Total   : <b>{_fmt(total)} IDR</b>\n"
        f"🔖 ID      : <code>{dep_id}</code>"
    )
    # Encode amount_base di callback supaya yang masuk saldo adalah nominal asli (tanpa kode unik)
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
        logger.error(f"Gagal notif admin: {e}")

    _clear_dep_data(context)
    return ConversationHandler.END

async def _edit_admin_msg(query, text: str, kb=None) -> None:
    """Edit pesan admin — handle foto (caption) atau teks biasa."""
    try:
        if query.message.photo or query.message.document:
            await query.edit_message_caption(
                caption=text, parse_mode="HTML", reply_markup=kb)
        else:
            await query.edit_message_text(
                text=text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass

# ── Admin: approve ────────────────────────────────────────────────────────────

async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Bukan admin.", show_alert=True)
        return

    await query.answer()

    # parse: adm_dep_approve_{user_id}_{dep_id}_{amount_base}
    parts   = query.data.split("_")
    user_id = int(parts[3])
    amount_base = int(parts[-1])
    dep_id  = "_".join(parts[4:-1])

    # Guard double approve
    confirmed = confirm_deposit(user_id, dep_id)
    if confirmed is None:
        logger.warning(f"[DEPOSIT] DOUBLE APPROVE BLOCKED dep_id={dep_id} user={user_id}")
        await query.answer("⚠️ Deposit ini sudah pernah di-approve!", show_alert=True)
        return

    # Ambil unique_code dari record — supaya total yang masuk = amount_base + unique_code
    unique_code = confirmed.get("unique_code", 0)
    amount      = amount_base + unique_code   # total yang masuk ke saldo

    # Update saldo — amount_base + kode unik
    try:
        new_balance = update_balance(user_id, amount, track_spent=False)
        logger.info(f"[DEPOSIT] APPROVED dep_id={dep_id} user={user_id} +{amount:,} IDR (base={amount_base} unik={unique_code}) saldo_baru={new_balance:,}")
    except Exception as e:
        logger.error(f"[DEPOSIT] APPROVE FAILED dep_id={dep_id} user={user_id} error={e}")
        orig = query.message.caption or query.message.text or ""
        await _edit_admin_msg(query, orig + f"\n\n❌ Gagal update saldo: {e}")
        return

    orig = query.message.caption or query.message.text or ""
    await _edit_admin_msg(query, orig + f"\n\n✅ <b>APPROVED</b> — Saldo +{_fmt(amount)} IDR")

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ <b>Deposit Disetujui!</b>\n"
                f"──────────────────────\n"
                f"💰 Nominal     : <b>{_fmt(amount_base)} IDR</b>\n"
                f"🔢 Kode Unik   : <b>+{unique_code} IDR</b>\n"
                f"💸 Total masuk : <b>+{_fmt(amount)} IDR</b>\n"
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

# ── Admin: reject ─────────────────────────────────────────────────────────────

async def admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Bukan admin.", show_alert=True)
        return

    await query.answer()

    parts   = query.data.split("_")
    user_id = int(parts[3])
    dep_id  = "_".join(parts[4:])

    fail_deposit(user_id, dep_id)
    logger.info(f"[DEPOSIT] REJECTED dep_id={dep_id} user={user_id}")

    orig = query.message.caption or query.message.text or ""
    await _edit_admin_msg(query, orig + "\n\n❌ <b>REJECTED</b>")

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


# ── History Deposit user ──────────────────────────────────────────────────────

async def show_history_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query   = update.callback_query
    await query.answer()

    deposits = get_user_deposits(update.effective_user.id, limit=20)

    if not deposits:
        text = "📥 <b>Riwayat Deposit</b>\n──────────────────────\nBelum ada riwayat deposit."
    else:
        STATUS_ICON = {"confirmed": "✅", "pending": "⏳", "failed": "❌"}
        lines   = ["📥 <b>Riwayat Deposit</b>\n──────────────────────"]
        kb_rows = []
        for d in deposits:
            icon    = STATUS_ICON.get(d.get("status", ""), "❓")
            method  = d.get("method", "-")
            base    = _fmt(d.get("amount_base", d.get("amount", 0)))
            unique  = d.get("unique_code", 0)
            total   = _fmt(d.get("amount_total", d.get("amount", 0)))
            date    = d.get("created_at", "")[:16].replace("T", " ")
            dep_id  = d.get("deposit_id", "-")
            status  = d.get("status", "")

            lines.append(
                f"\n{icon} <code>{dep_id}</code>\n"
                f"   💳 {method}  💰 {base} IDR (+{unique} unik)\n"
                f"   💸 Total bayar: {total} IDR\n"
                f"   🕐 {date}"
            )

            # Kalau masih pending → tampilkan tombol upload bukti
            if status == "pending":
                lines.append(f"   ⚠️ Menunggu bukti transfer")
                kb_rows.append([
                    InlineKeyboardButton(
                        f"📸 Upload Bukti — {dep_id[:12]}...",
                        callback_data=f"dep_resume_{d.get('deposit_id')}"
                    )
                ])

        text = "\n".join(lines)

    msg = query.message
    kb_rows_final = kb_rows + [[InlineKeyboardButton("🏠 Home", callback_data="menu_home")]]
    kb  = InlineKeyboardMarkup(kb_rows_final)
    try:
        if msg.photo or msg.document:
            await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        else:
            await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=kb)
    except BadRequest:
        pass


# ── Resume upload bukti ──────────────────────────────────────────────────────

async def resume_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    User klik [📸 Upload Bukti] dari history deposit.
    Ambil data deposit pending dari store, simpan ke user_data, masuk state WAITING_PROOF.
    callback_data: dep_resume_{dep_id}
    """
    query  = update.callback_query
    await query.answer()

    dep_id  = query.data.replace("dep_resume_", "")
    user_id = query.from_user.id

    # Cari record di deposit store
    all_deps = get_user_deposits(user_id, limit=50)
    record   = next((d for d in all_deps if d.get("deposit_id") == dep_id), None)

    if not record:
        await query.answer("❌ Deposit tidak ditemukan.", show_alert=True)
        return ConversationHandler.END

    if record.get("status") != "pending":
        await query.answer("⚠️ Deposit ini sudah diproses.", show_alert=True)
        return ConversationHandler.END

    # Pulihkan state conversation dari record
    context.user_data[_KEY_DEP_ID] = dep_id
    context.user_data[_KEY_METHOD] = record.get("method", "?")
    context.user_data[_KEY_AMOUNT] = record.get("amount_base", 0)
    context.user_data[_KEY_UNIQUE] = record.get("unique_code", 0)

    amount = record.get("amount_base", 0)
    unique = record.get("unique_code", 0)
    total  = amount + unique
    method = record.get("method", "?")

    sent = await query.message.reply_text(
        text=(
            f"📸 <b>Upload Bukti Transfer</b>\n"
            f"──────────────────────\n"
            f"💳 Metode : <b>{method}</b>\n"
            f"💰 Nominal: <b>{_fmt(amount)} IDR</b>\n"
            f"🔢 Kode Unik: <b>+{unique}</b>\n"
            f"💸 Total  : <b>{_fmt(total)} IDR</b>\n"
            f"🔖 ID     : <code>{dep_id}</code>\n\n"
            f"Kirim screenshot bukti transfer kamu:"
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="dep_cancel")]
        ]),
    )
    context.user_data[_KEY_MSG_ID] = sent.message_id
    return WAITING_PROOF


# ── Admin: list semua deposit dengan filter + tombol approve/reject ───────────

# callback format:
#   adm_dep_list_{filter}_{page}
#   filter: pending | confirmed | failed | all

_DEP_LIST_PAGE = 3   # item per halaman (lebih sedikit karena ada tombol per item)

STATUS_LABEL = {
    "pending":   "⏳ Pending",
    "confirmed": "✅ Confirmed",
    "failed":    "❌ Failed/Cancelled",
    "all":       "📋 Semua",
}


async def admin_list_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /listdeposit           → pending
    /listdeposit all       → semua
    /listdeposit confirmed → confirmed
    Callback: adm_dep_list_{filter}_{page}
    """
    query = update.callback_query if update.callback_query else None

    if query:
        await query.answer()
        parts       = query.data.split("_")   # adm dep list {filter} {page}
        dep_filter  = parts[3]
        page        = int(parts[4])
    else:
        args       = context.args if hasattr(context, "args") and context.args else []
        dep_filter = args[0] if args else "pending"
        page       = 0

    if dep_filter not in ("pending", "confirmed", "failed", "all"):
        dep_filter = "pending"

    status_filter = None if dep_filter == "all" else dep_filter
    deposits      = get_all_deposits(status_filter=status_filter, limit=200)

    total_pages = max(1, (len(deposits) + _DEP_LIST_PAGE - 1) // _DEP_LIST_PAGE)
    page        = max(0, min(page, total_pages - 1))
    chunk       = deposits[page * _DEP_LIST_PAGE : (page + 1) * _DEP_LIST_PAGE]

    label = STATUS_LABEL.get(dep_filter, "📋")
    header = (
        f"📂 <b>Deposit {label}</b>\n"
        f"Total: <b>{len(deposits)}</b> — hal. {page+1}/{total_pages}\n"
        f"──────────────────────"
    )

    rows = []

    if not deposits:
        text = f"{header}\nTidak ada data."
    else:
        lines = [header]
        for item in chunk:
            uid = item["user_id"]
            r   = item["record"]
            dep_id = r.get("deposit_id", "-")
            status = r.get("status", "-")
            s_icon = {"pending": "⏳", "confirmed": "✅", "failed": "❌"}.get(status, "❓")

            lines.append(
                f"\n{s_icon} <code>{dep_id}</code>\n"
                f"   👤 <code>{uid}</code>  💳 {r.get('method')}\n"
                f"   💰 {_fmt(r.get('amount_base', 0))} IDR  🔢 +{r.get('unique_code', 0)}\n"
                f"   💸 Total: {_fmt(r.get('amount_total', 0))} IDR\n"
                f"   🕐 {r.get('created_at', '')[:16].replace('T', ' ')}"
            )

            # Tombol Approve + Reject untuk SEMUA status pending
            # (termasuk yang belum upload proof — admin bisa approve manual)
            if status == "pending":
                amount_total = r.get("amount_total", 0)
                amount_base = r.get("amount_base", 0)
                rows.append([
                    InlineKeyboardButton(
                        f"✅ Approve {_fmt(amount_total)}",
                        callback_data=f"adm_dep_approve_{uid}_{dep_id}_{amount_base}"
                    ),
                    InlineKeyboardButton(
                        "❌ Reject",
                        callback_data=f"adm_dep_reject_{uid}_{dep_id}"
                    ),
                ])

        text = "\n".join(lines)

    # Filter tabs
    rows.append([
        InlineKeyboardButton("⏳" if dep_filter == "pending"   else "⏳ Pending",
                             callback_data=f"adm_dep_list_pending_0"),
        InlineKeyboardButton("✅" if dep_filter == "confirmed" else "✅ Done",
                             callback_data=f"adm_dep_list_confirmed_0"),
        InlineKeyboardButton("❌" if dep_filter == "failed"    else "❌ Failed",
                             callback_data=f"adm_dep_list_failed_0"),
        InlineKeyboardButton("📋" if dep_filter == "all"       else "📋 All",
                             callback_data=f"adm_dep_list_all_0"),
    ])

    # Navigasi
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"adm_dep_list_{dep_filter}_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"adm_dep_list_{dep_filter}_{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"adm_dep_list_{dep_filter}_{page}")])

    kb = InlineKeyboardMarkup(rows)

    if query:
        try:
            await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=kb)
        except BadRequest:
            pass
    else:
        await update.message.reply_text(text=text, parse_mode="HTML", reply_markup=kb)


# ── Cancel ────────────────────────────────────────────────────────────────────

async def cancel_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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


async def _ask_for_photo(update, context) -> int:
    """Dipanggil saat user kirim teks di state WAITING_PROOF — minta foto."""
    await update.message.reply_text(
        "📸 Kirim <b>foto</b> bukti transfer ya.", parse_mode="HTML"
    )
    return WAITING_PROOF


# ── ConversationHandler ───────────────────────────────────────────────────────

def build_deposit_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(pick_method,     pattern=r"^dep_method_"),
            CallbackQueryHandler(resume_upload,   pattern=r"^dep_resume_"),
        ],
        states={
            WAITING_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount),
                CallbackQueryHandler(cancel_deposit, pattern=r"^dep_cancel$"),
            ],
            WAITING_PROOF: [
                MessageHandler(filters.PHOTO, receive_proof),
                MessageHandler(filters.TEXT & ~filters.COMMAND, _ask_for_photo),
                CallbackQueryHandler(cancel_deposit, pattern=r"^dep_cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("start",  cancel_and_restart),
            CommandHandler("cancel", cancel_deposit),
            CallbackQueryHandler(cancel_deposit,  pattern=r"^dep_cancel$"),
            CallbackQueryHandler(_fallback_menu,  pattern=r"^menu_"),
        ],
        per_message=False,
        per_chat=True,
        per_user=True,
    )