"""
handlers/history.py

Tampilkan history order user dengan pagination.
Tiap halaman 5 order, ada tombol ◀️ Prev / Next ▶️.

callback_data:
  menu_history_order          → halaman pertama
  hist_order_page_{n}         → lompat ke halaman n (0-based)
"""

from utils.helpers import fmt_date_wib

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from data.order_store import get_user_orders

PAGE_SIZE = 5

STATUS_ICON = {
    "success":  "✅",
    "failed":   "❌",
    "checking": "⏳",
}


def _fmt_price(amount) -> str:
    try:
        return f"{int(float(amount)):,}"
    except Exception:
        return str(amount)


_fmt_date = fmt_date_wib


def _build_page(orders: list, page: int) -> tuple[str, InlineKeyboardMarkup]:
    """
    Return (caption_text, keyboard) untuk halaman tertentu.
    """
    total_pages = max(1, (len(orders) + PAGE_SIZE - 1) // PAGE_SIZE)
    page        = max(0, min(page, total_pages - 1))

    start = page * PAGE_SIZE
    chunk = orders[start : start + PAGE_SIZE]

    if not chunk:
        text = (
            "📋 <b>Riwayat Order</b>\n"
            "──────────────────────\n"
            "Belum ada order."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="menu_home")]
        ])
        return text, kb

    lines = [f"📋 <b>Riwayat Order</b>  <i>(hal. {page+1}/{total_pages})</i>\n"
             f"──────────────────────"]

    for o in chunk:
        icon   = STATUS_ICON.get(o.get("status", ""), "❓")
        code   = o.get("order_code", "-")
        name   = o.get("item_name", "-")
        qty    = o.get("qty", 1)
        price  = _fmt_price(o.get("price_idr", 0))
        date   = _fmt_date(o.get("created_at"))

        lines.append(
            f"\n{icon} <code>{code}</code>\n"
            f"   📦 {name}\n"
            f"   🛍 Qty: {qty}  💰 {price} IDR\n"
            f"   🕐 {date}"
        )

    lines.append("\n──────────────────────")
    lines.append("🌐 Lihat detail: https://order.telekuy.com/")

    text = "\n".join(lines)

    # Pagination buttons
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"hist_order_page_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"hist_order_page_{page+1}"))

    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="menu_home")])

    return text, InlineKeyboardMarkup(rows)


async def _render(query: CallbackQuery, user_id: int, page: int) -> None:
    """Edit pesan yang ada dengan halaman history."""
    orders = get_user_orders(user_id, limit=200)   # ambil semua, paginasi di sini
    text, kb = _build_page(orders, page)

    try:
        # Pesan dari home adalah foto — coba edit caption dulu
        await query.edit_message_caption(
            caption=text,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except BadRequest as e:
        if "There is no caption" in str(e) or "Message can't be edited" in str(e):
            # Pesan teks biasa
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=kb,
                disable_web_page_preview=True,
            )
        else:
            raise


async def show_history_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry — klik tombol [📋 Riwayat Order] dari home."""
    query = update.callback_query
    await query.answer()
    await _render(query, query.from_user.id, page=0)


async def paginate_history_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Klik tombol Prev / Next."""
    query = update.callback_query
    await query.answer()
    page = int(query.data.split("_")[-1])
    await _render(query, query.from_user.id, page=page)