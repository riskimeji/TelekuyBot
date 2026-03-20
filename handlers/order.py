"""
handlers/order.py

Flow Buy lengkap:
  Klik [🛍 Buy]
    → ask_quantity()          minta input qty        STATE: WAITING_QTY
    → receive_quantity()      validasi + tampil summary
    → confirm_purchase()      cek balance → prepare-order → create-order → kirim hasil
"""

import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.error import BadRequest

from data.user_store  import get_user, update_balance, add_total_spent, increment_order_count
from handlers.start   import cancel_and_restart
from utils.config     import ADMIN_ID
from data.order_store import create_order as store_order, update_order_status
from services.laravel_api import prepare_order, create_order as laravel_create_order, download_tdata

WAITING_QTY = 1

_KEY_CAT_ID   = "buy_cat_id"
_KEY_TIER_IDX = "buy_tier_idx"
_KEY_MSG_ID   = "buy_prompt_msg_id"


# ── helpers ──────────────────────────────────────────────────────────────────

def _fmt(n) -> str:
    try:
        return f"{int(float(n)):,}"
    except Exception:
        return str(n)


def _find_cat(context, cat_id: int) -> dict | None:
    for c in context.bot_data.get("categories", []):
        if c["id"] == cat_id:
            return c
    return None


def _clear_buy_data(context) -> None:
    for key in [_KEY_CAT_ID, _KEY_TIER_IDX, _KEY_MSG_ID, "buy_qty", "buy_total",
                "buy_sell_price", "buy_cat_name"]:
        context.user_data.pop(key, None)


async def _safe_delete(context, chat_id: int, msg_id: int) -> None:
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass


# ── STEP 1: tanya qty ────────────────────────────────────────────────────────

async def ask_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, cat_id_str, tier_idx_str = query.data.split("_")
    cat_id   = int(cat_id_str)
    tier_idx = int(tier_idx_str)

    context.user_data[_KEY_CAT_ID]   = cat_id
    context.user_data[_KEY_TIER_IDX] = tier_idx

    cat   = _find_cat(context, cat_id)
    name  = cat.get("name", "?") if cat else "?"
    tiers = cat.get("telegram_prices", []) if cat else []
    tier  = tiers[tier_idx] if tiers else {}
    price = _fmt(tier.get("sell_price", 0))
    stock = int(tier.get("stock", 0))

    sent: Message = await query.message.reply_text(
        text=(
            f"🛒 <b>Masukkan jumlah yang ingin dibeli</b>\n"
            f"──────────────────────\n"
            f"📦 Produk : <b>{name}</b>\n"
            f"💰 Harga  : <b>{price} IDR</b> / akun\n"
            f"🏢 Stok   : <b>{_fmt(stock)}</b>\n\n"
            f"Ketik jumlah (contoh: <code>10</code>) lalu kirim.\n"
            f"Ketik /cancel untuk batal."
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="buy_cancel")]
        ]),
    )
    context.user_data[_KEY_MSG_ID] = sent.message_id
    return WAITING_QTY


# ── STEP 2: terima input qty ─────────────────────────────────────────────────

async def receive_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()

    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text(
            "⚠️ Masukkan angka yang valid (contoh: <code>5</code>).",
            parse_mode="HTML",
        )
        return WAITING_QTY

    qty      = int(text)
    cat_id   = context.user_data.get(_KEY_CAT_ID)
    tier_idx = context.user_data.get(_KEY_TIER_IDX, 0)
    cat      = _find_cat(context, cat_id)

    if not cat:
        await update.message.reply_text("❌ Sesi habis, silakan mulai ulang dari /start.")
        return ConversationHandler.END

    tiers      = cat.get("telegram_prices", [])
    tier       = tiers[tier_idx] if tiers else {}
    name       = cat.get("name", "?")
    sell_price = float(tier.get("sell_price", 0))
    stock      = int(tier.get("stock", 0))

    if qty > stock:
        await update.message.reply_text(
            f"⚠️ Stok tidak cukup. Tersedia: <b>{_fmt(stock)}</b> akun.",
            parse_mode="HTML",
        )
        return WAITING_QTY

    total = sell_price * qty

    # Cek balance user
    user_data = get_user(update.effective_user.id)
    balance   = user_data.get("balance_idr", 0.0) if user_data else 0.0

    # Simpan ke user_data untuk step confirm
    context.user_data["buy_qty"]        = qty
    context.user_data["buy_total"]      = total
    context.user_data["buy_sell_price"] = sell_price
    context.user_data["buy_cat_name"]   = name

    # Hapus pesan prompt
    await _safe_delete(context,
                       update.effective_chat.id,
                       context.user_data.get(_KEY_MSG_ID, 0))

    # Tanda peringatan saldo jika kurang
    balance_warn = ""
    if balance < total:
        balance_warn = (
            f"\n\n⚠️ <b>Saldo tidak mencukupi!</b>\n"
            f"💳 Saldo kamu: <b>{balance:.2f} IDR</b>\n"
            f"💸 Dibutuhkan: <b>{_fmt(total)} IDR</b>\n"
            f"Silakan deposit terlebih dahulu."
        )

    summary = (
        f"🗂 <b>Purchase Product:</b> {name}\n"
        f"💰 <b>Product Price:</b> {_fmt(sell_price)} IDR\n"
        f"🛍 <b>Quantity to Purchase:</b> {qty}\n"
        f"🧾 <b>Amount Payable:</b> <b>{_fmt(total)} IDR</b>"
        f"{balance_warn}"
    )

    kb_rows = []
    if balance >= total:
        kb_rows.append([InlineKeyboardButton("✅ Confirm Purchase", callback_data="buy_confirm")])
    kb_rows.append([InlineKeyboardButton("❌ Cancel", callback_data="buy_cancel")])

    sent: Message = await update.message.reply_text(
        text=summary,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb_rows),
    )
    context.user_data[_KEY_MSG_ID] = sent.message_id
    return WAITING_QTY


# ── STEP 3: confirm → proses order ───────────────────────────────────────────

async def confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    cat_id     = context.user_data.get(_KEY_CAT_ID)
    tier_idx   = context.user_data.get(_KEY_TIER_IDX, 0)
    qty        = context.user_data.get("buy_qty", 1)
    total      = context.user_data.get("buy_total", 0.0)
    sell_price = context.user_data.get("buy_sell_price", 0.0)
    name       = context.user_data.get("buy_cat_name", "?")
    tg_user    = query.from_user

    # Double-check balance (hindari race condition klik cepat)
    user_data = get_user(tg_user.id)
    balance   = user_data.get("balance_idr", 0.0) if user_data else 0.0

    if balance < total:
        await query.edit_message_text(
            text=(
                f"❌ <b>Saldo tidak mencukupi.</b>\n\n"
                f"💳 Saldo kamu : <b>{_fmt(balance)} IDR</b>\n"
                f"💸 Dibutuhkan : <b>{_fmt(total)} IDR</b>\n\n"
                f"Silakan deposit terlebih dahulu."
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Deposit",  callback_data="menu_deposit")],
                [InlineKeyboardButton("🏠 Home",     callback_data="menu_home")],
            ]),
        )
        _clear_buy_data(context)
        return ConversationHandler.END

    # ── Processing message ────────────────────────────────────────────────
    try:
        await query.edit_message_text(
            text=(
                f"⏳ <b>Memproses order...</b>\n\n"
                f"📦 {name}\n"
                f"🛍 Qty  : {qty}\n"
                f"🧾 Total: {_fmt(total)} IDR\n\n"
                f"🔍 Sedang memeriksa akun, mohon tunggu..."
            ),
            parse_mode="HTML",
        )
    except BadRequest:
        pass

    # ── 1. Potong balance dulu (sementara) — belum track_spent ──────────
    # track_spent=False: kalau gagal dan direfund, total_spent tidak ikut berubah
    try:
        update_balance(tg_user.id, -total, track_spent=False)
    except ValueError:
        await query.message.reply_text(
            "❌ Saldo berubah, tidak cukup untuk melanjutkan order.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="menu_home")]
            ]),
        )
        _clear_buy_data(context)
        return ConversationHandler.END

    # ── 2. Prepare order (ambil akun + checker) di Laravel ───────────────
    try:
        prep = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: prepare_order(cat_id, sell_price, qty, tg_user.id)
        )
    except Exception as e:
        update_balance(tg_user.id, +total, track_spent=False)   # refund
        await query.message.reply_text(
            f"❌ Gagal menghubungi server.\n<code>{e}</code>\n\nSaldo dikembalikan.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="menu_home")]
            ]),
        )
        _clear_buy_data(context)
        return ConversationHandler.END

    if prep.get("status") != "success":
        update_balance(tg_user.id, +total, track_spent=False)   # refund
        await query.message.reply_text(
            f"❌ <b>Gagal memproses order:</b>\n{prep.get('message', 'Unknown error')}\n\nSaldo dikembalikan.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Coba Lagi", callback_data=f"tier_{cat_id}_{tier_idx}")],
                [InlineKeyboardButton("🏠 Home",      callback_data="menu_home")],
            ]),
        )
        _clear_buy_data(context)
        return ConversationHandler.END

    account_ids  = prep["account_ids"]
    actual_qty   = prep.get("actual_qty",   qty)
    actual_price = prep.get("actual_price", total)
    is_partial   = prep.get("partial",      False)

    # Kalau partial — refund selisihnya ke saldo dulu
    if is_partial and actual_price < total:
        refund_diff = total - actual_price
        update_balance(tg_user.id, +refund_diff, track_spent=False)

    # Update progress message
    partial_note = (
        f"\n⚠️ Stok terbatas: dapat <b>{actual_qty}</b> dari <b>{qty}</b> akun."
        if is_partial else ""
    )
    try:
        await query.edit_message_text(
            text=(
                f"⏳ <b>Akun lolos checker!</b> Membuat order...\n\n"
                f"📦 {name}\n"
                f"🛍 Qty  : {actual_qty}\n"
                f"🧾 Total: {_fmt(actual_price)} IDR"
                f"{partial_note}"
            ),
            parse_mode="HTML",
        )
    except BadRequest:
        pass

    # ── 3. Create order di Laravel ────────────────────────────────────────
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: laravel_create_order(account_ids, sell_price, tg_user.id)
        )
    except Exception as e:
        update_balance(tg_user.id, +actual_price, track_spent=False)   # refund
        await query.message.reply_text(
            f"❌ Gagal membuat order.\n<code>{e}</code>\n\nSaldo dikembalikan.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="menu_home")]
            ]),
        )
        _clear_buy_data(context)
        return ConversationHandler.END

    if result.get("status") != "success":
        update_balance(tg_user.id, +actual_price, track_spent=False)   # refund
        await query.message.reply_text(
            f"❌ Gagal membuat order: {result.get('message')}\n\nSaldo dikembalikan.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="menu_home")]
            ]),
        )
        _clear_buy_data(context)
        return ConversationHandler.END

    order_code = result["order_code"]

    # ── 4. Simpan ke order_store lokal & update stats user ───────────────
    add_total_spent(tg_user.id, actual_price)

    store_order(
        user_id=tg_user.id,
        order_code=order_code,
        item_id=str(cat_id),
        item_name=name,
        qty=actual_qty,
        price_idr=actual_price,
    )
    update_order_status(tg_user.id, order_code, "success")
    increment_order_count(tg_user.id)

    # ── 5. Kirim notif sukses ke user ────────────────────────────────────
    partial_msg = ""
    if is_partial:
        refunded = total - actual_price
        partial_msg = (
            f"\n⚠️ <b>Stok terbatas:</b> dapat <b>{actual_qty}</b> dari <b>{qty}</b> akun.\n"
            f"💸 Selisih <b>{_fmt(refunded)} IDR</b> sudah dikembalikan ke saldo."
        )

    await query.message.reply_text(
        text=(
            f"✅ <b>Order Berhasil!</b>\n"
            f"──────────────────────\n"
            f"📦 Produk     : <b>{name}</b>\n"
            f"🛍 Qty        : <b>{actual_qty}</b>\n"
            f"🧾 Total      : <b>{_fmt(actual_price)} IDR</b>\n"
            f"🔖 Order Code : <code>{order_code}</code>\n"
            f"{partial_msg}"
            f"──────────────────────\n"
            f"🌐 Lihat order: https://order.telekuy.com/\n"
            f"⏳ File tdata sedang disiapkan, akan dikirim otomatis...\n"
            f"❓ Butuh bantuan? @TelekuySupport"
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 Instruction", callback_data=f"instr_post_{cat_id}")],
            [InlineKeyboardButton("🏠 Home",        callback_data="menu_home")],
        ]),
    )

    _clear_buy_data(context)

    # ── 6. Notif ke admin ─────────────────────────────────────────────────
    try:
        username     = f"@{tg_user.username}" if tg_user.username else tg_user.full_name
        partial_note = "\n⚠️ Partial order!" if is_partial else ""
        admin_notif  = (
            f"🛒 <b>Order Baru!</b>\n"
            f"──────────────────────\n"
            f"👤 User      : {username} (<code>{tg_user.id}</code>)\n"
            f"📦 Produk    : <b>{name}</b>\n"
            f"🛍 Qty       : <b>{actual_qty}</b>\n"
            f"🧾 Total     : <b>{_fmt(actual_price)} IDR</b>\n"
            f"🔖 Order Code: <code>{order_code}</code>"
            f"{partial_note}"
        )
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_notif,
            parse_mode="HTML",
        )
    except Exception:
        pass

    # ── 7. Download tdata di background — user tidak perlu tunggu ─────────
    chat_id = query.message.chat_id
    asyncio.get_event_loop().create_task(
        _send_tdata(
            bot=context.bot,
            chat_id=chat_id,
            order_code=order_code,
            account_ids=account_ids,
            name=name,
            qty=actual_qty,
        )
    )

    return ConversationHandler.END


# ── fallback: menu button ditekan saat conversation aktif ───────────────────

async def _fallback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Dipanggil saat user klik menu apapun (menu_home, menu_rules, dll)
    saat conversation buy sedang aktif.
    Hapus pesan prompt jika ada, bersihkan state, lalu re-dispatch
    supaya handler asli (show_rules, home_callback, dll) tetap jalan.
    """
    _clear_buy_data(context)

    # Hapus pesan prompt qty kalau masih ada
    msg_id = context.user_data.pop(_KEY_MSG_ID, None)
    if msg_id:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=msg_id,
            )
        except Exception:
            pass

    # Re-dispatch update ini ke handler lain yang terdaftar di application
    await context.application.process_update(update)
    return ConversationHandler.END


# ── background: download & kirim tdata ──────────────────────────────────────

async def _send_tdata(bot, chat_id: int, order_code: str, account_ids: list[int],
                      name: str, qty: int) -> None:
    """
    Jalankan di background setelah order confirm.
    Download ZIP tdata dari Laravel lalu kirim ke user sebagai dokumen.
    """
    import io
    import logging
    logger = logging.getLogger(__name__)

    try:
        # Download ZIP (blocking HTTP — jalankan di executor)
        zip_bytes = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: download_tdata(order_code, account_ids)
        )

        filename = f"{order_code}_tdata.zip"
        doc      = io.BytesIO(zip_bytes)
        doc.name = filename

        await bot.send_document(
            chat_id=chat_id,
            document=doc,
            filename=filename,
            caption=(
                f"📦 <b>File Tdata Kamu Siap!</b>\n"
                f"──────────────────────\n"
                f"🗂 Produk     : <b>{name}</b>\n"
                f"🛍 Qty        : <b>{qty}</b>\n"
                f"🔖 Order Code : <code>{order_code}</code>\n"
                f"──────────────────────\n"
                f"📖 Cara pakai: ekstrak ZIP, masuk ke folder tdata\n"
                f"❓ Bantuan: @TelekuySupport"
            ),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"[SEND_TDATA] Gagal kirim tdata order {order_code}: {e}")
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ <b>Gagal mengirim file tdata.</b>\n\n"
                    f"🔖 Order Code: <code>{order_code}</code>\n"
                    f"Silakan hubungi @TelekuySupport dengan order code di atas."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass


# ── cancel ───────────────────────────────────────────────────────────────────

async def cancel_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query if update.callback_query else None

    if query:
        await query.answer()
        try:
            await query.edit_message_text(
                text="❌ Pembelian dibatalkan.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Home", callback_data="menu_home")]
                ]),
            )
        except BadRequest:
            pass
    else:
        await update.message.reply_text(
            "❌ Pembelian dibatalkan.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="menu_home")]
            ]),
        )

    _clear_buy_data(context)
    return ConversationHandler.END


# ── ConversationHandler factory ──────────────────────────────────────────────

def build_buy_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ask_quantity, pattern=r"^buy_\d+_\d+$"),
        ],
        states={
            WAITING_QTY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_quantity),
                CallbackQueryHandler(cancel_purchase,  pattern=r"^buy_cancel$"),
                CallbackQueryHandler(confirm_purchase, pattern=r"^buy_confirm$"),
            ],
        },
        fallbacks=[
            CommandHandler("start",                    cancel_and_restart),
            MessageHandler(filters.Regex(r"^/cancel$"), cancel_purchase),
            CallbackQueryHandler(cancel_purchase, pattern=r"^buy_cancel$"),
            CallbackQueryHandler(_fallback_menu,         pattern=r"^menu_"),
        ],
        per_message=False,
        per_chat=True,
        per_user=True,
    )