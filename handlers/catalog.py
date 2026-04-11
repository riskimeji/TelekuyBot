"""
handlers/catalog.py

Flow:
  [Purchase]
    → show_categories()          — list continent
      → klik continent
    → show_continent_cats()      — list kategori dalam continent
      → klik kategori
    → show_price_tiers()         — list harga tier dalam kategori itu
      → klik harga
    → show_item_detail()         — halaman konfirmasi sebelum buy
      → [Buy] [Instruction] [Back] [Home]
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from services.laravel_api import get_categories


async def _edit(query: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup,
                preview: bool = False) -> None:
    """
    Edit pesan — otomatis pakai edit_message_caption (foto) atau
    edit_message_text (teks biasa) sesuai tipe pesan yang ada.
    """
    msg = query.message
    has_media = bool(msg.photo or msg.document or msg.sticker or msg.animation)
    try:
        if has_media:
            await query.edit_message_caption(
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=not preview,
            )
    except BadRequest as e:
        if "not modified" in str(e).lower():
            pass   # konten sama, abaikan
        else:
            raise


# ── helpers ─────────────────────────────────────────────────────────────────

def _fmt_price(price_str: str) -> str:
    """'15000.00' → '15,000'"""
    try:
        return f"{int(float(price_str)):,}"
    except (ValueError, TypeError):
        return price_str


def _get_categories_cached(context) -> list[dict]:
    """Simpan categories di bot_data supaya tidak hit API tiap klik."""
    return context.bot_data.get("categories", [])


def _find_category(context, cat_id: int) -> dict | None:
    for c in _get_categories_cached(context):
        if c["id"] == cat_id:
            return c
    return None


def _get_continents(categories: list[dict]) -> list[str]:
    """Ambil daftar continent unik, sorted A-Z."""
    seen = set()
    result = []
    for c in categories:
        cont = (c.get("continent") or "").strip()
        if cont and cont not in seen:
            seen.add(cont)
            result.append(cont)
    return sorted(result)


def _cats_for_continent(categories: list[dict], cont_name: str) -> list[dict]:
    cats = [c for c in categories if (c.get("continent") or "").strip() == cont_name]
    return sorted(cats, key=lambda c: c.get("total_stock", 0), reverse=True)


# ── keyboard builders ────────────────────────────────────────────────────────

def _kb_continents(continents: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for idx, cont in enumerate(continents):
        rows.append([InlineKeyboardButton(f"🌍 {cont}", callback_data=f"continent_{idx}")])
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)


CONT_PAGE_SIZE = 10

def _kb_continent_cats(cats: list[dict], cont_idx: int, page: int = 0) -> InlineKeyboardMarkup:
    """Keyboard list kategori dalam satu continent, dengan pagination."""
    total_pages = max(1, (len(cats) + CONT_PAGE_SIZE - 1) // CONT_PAGE_SIZE)
    page        = max(0, min(page, total_pages - 1))
    start       = page * CONT_PAGE_SIZE
    chunk       = cats[start : start + CONT_PAGE_SIZE]

    rows = []
    for cat in chunk:
        stock = cat.get("total_stock", 0)
        name  = cat.get("name", "?")
        label = f"{name}  ({stock})" if stock > 0 else f"{name}  (Habis)"
        cb    = f"cat_{cat['id']}" if stock > 0 else "cat_out_of_stock"
        rows.append([InlineKeyboardButton(label, callback_data=cb)])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"contp_{cont_idx}_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"contp_{cont_idx}_{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([
        InlineKeyboardButton("◀️ Back", callback_data="menu_stock"),
        InlineKeyboardButton("🏠 Home", callback_data="menu_home"),
    ])
    return InlineKeyboardMarkup(rows)


# kept for backward compat (not used in new flow)
CAT_PAGE_SIZE = 10

def _kb_categories(categories: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(categories) + CAT_PAGE_SIZE - 1) // CAT_PAGE_SIZE)
    page        = max(0, min(page, total_pages - 1))
    start       = page * CAT_PAGE_SIZE
    chunk       = categories[start : start + CAT_PAGE_SIZE]

    rows = []
    for cat in chunk:
        stock = cat.get("total_stock", 0)
        name  = cat.get("name", "?")
        label = f"{name}  ({stock})" if stock > 0 else f"{name}  (Habis)"
        cb    = f"cat_{cat['id']}" if stock > 0 else "cat_out_of_stock"
        rows.append([InlineKeyboardButton(label, callback_data=cb)])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"cat_page_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"cat_page_{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("🏠 Home", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)


def _kb_price_tiers(cat_id: int, tiers: list[dict], back_cb: str = "menu_stock") -> InlineKeyboardMarkup:
    rows = []
    for i, tier in enumerate(tiers):
        price = _fmt_price(tier.get("sell_price", "0"))
        stock = tier.get("stock", 0)
        label = f"💰 {price} IDR  —  stok {stock}"
        rows.append([InlineKeyboardButton(label, callback_data=f"tier_{cat_id}_{i}")])
    rows.append([
        InlineKeyboardButton("◀️ Back", callback_data=back_cb),
        InlineKeyboardButton("🏠 Home", callback_data="menu_home"),
    ])
    return InlineKeyboardMarkup(rows)


def _kb_item_detail(cat_id: int, tier_idx: int, back_cb: str = None) -> InlineKeyboardMarkup:
    if back_cb is None:
        back_cb = f"cat_{cat_id}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Buy", callback_data=f"buy_{cat_id}_{tier_idx}")],
        [
            InlineKeyboardButton("📖 Instruction", callback_data=f"instr_{cat_id}"),
            InlineKeyboardButton("◀️ Back",         callback_data=back_cb),
        ],
        [InlineKeyboardButton("🏠 Home", callback_data="menu_home")],
    ])


# ── handlers ─────────────────────────────────────────────────────────────────

async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Klik [Purchase] → tampilkan daftar continent."""
    query: CallbackQuery = update.callback_query
    await query.answer()

    try:
        await _edit(query, "⏳ Memuat kategori...", InlineKeyboardMarkup([]))
    except Exception:
        pass

    try:
        categories = get_categories()
        context.bot_data["categories"] = categories
    except Exception as e:
        await _edit(query,
            f"❌ Gagal memuat kategori.\n<code>{e}</code>",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Coba lagi", callback_data="menu_stock")],
                [InlineKeyboardButton("🏠 Home",      callback_data="menu_home")],
            ]),
        )
        return

    if not categories:
        await _edit(query, "📭 Belum ada kategori tersedia.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="menu_home")]]),
        )
        return

    continents = _get_continents(categories)
    context.bot_data["continents"] = continents

    caption = (
        f"🛒 <b>Purchase</b>\n"
        f"──────────────────────\n"
        f"Pilih wilayah akun yang ingin dibeli:"
    )
    await _edit(query, caption, _kb_continents(continents))


async def show_continent_cats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Klik salah satu continent → tampil daftar kategori dalam continent itu.
    callback_data: continent_{idx}
    """
    query: CallbackQuery = update.callback_query
    await query.answer()

    cont_idx   = int(query.data.split("_")[1])
    continents = context.bot_data.get("continents", [])
    categories = _get_categories_cached(context)

    # Kalau cache kosong (bot restart) — ambil ulang
    if not categories or not continents:
        try:
            categories = get_categories()
            context.bot_data["categories"] = categories
            continents = _get_continents(categories)
            context.bot_data["continents"] = continents
        except Exception as e:
            await query.answer(f"❌ Gagal memuat: {e}", show_alert=True)
            return

    if cont_idx >= len(continents):
        await query.answer("❌ Wilayah tidak ditemukan.", show_alert=True)
        return

    cont_name = continents[cont_idx]
    cats      = _cats_for_continent(categories, cont_name)

    # Simpan untuk back button di halaman tier/detail
    context.user_data["current_continent_idx"] = cont_idx

    total_stock = sum(c.get("total_stock", 0) for c in cats)
    caption = (
        f"🌍 <b>{cont_name}</b>\n"
        f"──────────────────────\n"
        f"Pilih kategori akun yang ingin dibeli.\n"
        f"Total tersedia: <b>{total_stock:,}</b> akun"
    )
    await _edit(query, caption, _kb_continent_cats(cats, cont_idx, page=0))


async def paginate_continent_cats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Prev/Next dalam halaman kategori continent.
    callback_data: contp_{cont_idx}_{page}
    """
    query: CallbackQuery = update.callback_query
    await query.answer()

    parts    = query.data.split("_")
    cont_idx = int(parts[1])
    page     = int(parts[2])

    continents = context.bot_data.get("continents", [])
    categories = _get_categories_cached(context)

    if not categories or not continents:
        try:
            categories = get_categories()
            context.bot_data["categories"] = categories
            continents = _get_continents(categories)
            context.bot_data["continents"] = continents
        except Exception as e:
            await query.answer(f"❌ Gagal memuat: {e}", show_alert=True)
            return

    cont_name = continents[cont_idx]
    cats      = _cats_for_continent(categories, cont_name)

    total_pages = max(1, (len(cats) + CONT_PAGE_SIZE - 1) // CONT_PAGE_SIZE)
    caption = (
        f"🌍 <b>{cont_name}</b>\n"
        f"──────────────────────\n"
        f"Pilih kategori akun yang ingin dibeli.\n"
        f"<i>(hal. {page + 1}/{total_pages})</i>"
    )
    await _edit(query, caption, _kb_continent_cats(cats, cont_idx, page=page))


async def paginate_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Klik tombol Prev/Next di halaman kategori global (fallback).
    callback_data: cat_page_{n}
    """
    query: CallbackQuery = update.callback_query
    await query.answer()

    page       = int(query.data.split("_")[-1])
    categories = _get_categories_cached(context)

    if not categories:
        try:
            categories = get_categories()
            context.bot_data["categories"] = categories
        except Exception as e:
            await query.answer(f"❌ Gagal memuat: {e}", show_alert=True)
            return

    total      = sum(c.get("total_stock", 0) for c in categories)
    total_pages = max(1, (len(categories) + CAT_PAGE_SIZE - 1) // CAT_PAGE_SIZE)
    caption    = (
        f"🛒 <b>Purchase</b>\n"
        f"──────────────────────\n"
        f"Pilih kategori akun yang ingin dibeli.\n"
        f"Total tersedia: <b>{total:,}</b> akun  "
        f"<i>(hal. {page+1}/{total_pages})</i>"
    )

    await _edit(query, caption, _kb_categories(categories, page=page))


async def show_price_tiers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Klik salah satu kategori → tampil daftar harga tier.
    callback_data: cat_{id}
    """
    query: CallbackQuery = update.callback_query
    await query.answer()

    cat_id = int(query.data.split("_", 1)[1])
    cat    = _find_category(context, cat_id)

    if not cat:
        try:
            cats = get_categories()
            context.bot_data["categories"] = cats
            cat = next((c for c in cats if c["id"] == cat_id), None)
        except Exception:
            pass

    if not cat:
        await query.answer("❌ Kategori tidak ditemukan.", show_alert=True)
        return

    tiers = cat.get("telegram_prices", [])
    if not tiers:
        await query.answer("⚠️ Tidak ada harga tersedia.", show_alert=True)
        return

    # Tentukan back_cb: kembali ke continent view kalau tersedia
    cont_idx = context.user_data.get("current_continent_idx", -1)
    back_to_continent = f"continent_{cont_idx}" if cont_idx >= 0 else "menu_stock"

    # Kalau hanya 1 tier, langsung ke detail
    if len(tiers) == 1:
        context.user_data["selected_cat_id"]   = cat_id
        context.user_data["selected_tier_idx"] = 0
        await _render_item_detail(query, cat, 0, single_tier=True,
                                  single_tier_back=back_to_continent)
        return

    name  = cat.get("name", "?")
    desc  = cat.get("description", "")
    caption = (
        f"🛒 <b>{name}</b>\n"
        f"<i>{desc}</i>\n"
        f"──────────────────────\n"
        f"Pilih harga:"
    )
    await _edit(query, caption, _kb_price_tiers(cat_id, tiers, back_cb=back_to_continent))


async def show_item_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Klik salah satu tier harga → tampil halaman konfirmasi detail.
    callback_data: tier_{cat_id}_{tier_idx}
    """
    query: CallbackQuery = update.callback_query
    await query.answer()

    _, cat_id_str, tier_idx_str = query.data.split("_")
    cat_id   = int(cat_id_str)
    tier_idx = int(tier_idx_str)

    cat = _find_category(context, cat_id)
    if not cat:
        await query.answer("❌ Kategori tidak ditemukan.", show_alert=True)
        return

    context.user_data["selected_cat_id"]   = cat_id
    context.user_data["selected_tier_idx"] = tier_idx

    await _render_item_detail(query, cat, tier_idx)


async def _render_item_detail(query: CallbackQuery, cat: dict, tier_idx: int,
                              single_tier: bool = False,
                              single_tier_back: str = None) -> None:
    """Render halaman detail item — dipakai oleh show_item_detail & show_price_tiers."""
    tiers    = cat.get("telegram_prices", [])
    tier     = tiers[tier_idx]
    name     = cat.get("name", "?")
    price    = _fmt_price(tier.get("sell_price", "0"))
    stock    = tier.get("stock", 0)
    cat_id   = cat["id"]

    if single_tier:
        # Kembali ke continent view kalau ada, otherwise ke list semua continent
        back_cb = single_tier_back or "menu_stock"
    else:
        back_cb = f"cat_{cat_id}"

    caption = (
        f"✅ <b>You are buying:</b>\n"
        f"<b>{name}</b>\n\n"
        f"💰 Price: <b>{price} IDR</b>\n"
        f"🏢 Inventory: <b>{stock:,}</b>\n\n"
        f"──────────────────────\n"
        f"❗️ Bagi yang belum pernah menggunakan produk kami, "
        f"harap beli dalam jumlah kecil terlebih dahulu untuk menghindari kesalahpahaman. "
        f"Terima kasih atas kerjasamanya!"
    )

    await _edit(query, caption, _kb_item_detail(cat_id, tier_idx, back_cb=back_cb))


INSTRUCTION_TEXT = (
    "📖 <b>Cara Penggunaan</b>\n"
    "{name}"
    "──────────────────────\n"
    "1. Setelah order berhasil, kamu akan menerima file <b>tdata</b> atau <b>session.json</b>.\n"
    "2. Untuk <b>tdata</b>: ekstrak ke folder Telegram, lalu buka aplikasinya.\n"
    "3. Untuk <b>session</b>: gunakan Telethon / Pyrogram sesuai kebutuhanmu.\n"
    "4. Jangan login di lebih dari 1 device sekaligus untuk menghindari ban.\n\n"
    "🌐 Akses Order dan Login melalui: https://order.telekuy.com/\n"
    "🎬 Tutorial lengkap: https://t.me/TelekuyMarket/87\n\n"
    "❓ Ada pertanyaan? Hubungi @TelekuySupport"
)


async def show_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Klik [Instruction] → tampil cara pakai.

    Dua mode:
      - instr_{cat_id}        → dari halaman detail/buy (edit pesan yang ada)
      - instr_post_{cat_id}   → dari halaman sukses order (kirim pesan BARU, tidak hapus sukses)
    """
    query: CallbackQuery = update.callback_query
    await query.answer()

    parts   = query.data.split("_")
    is_post = parts[1] == "post"          # instr_post_{cat_id}
    cat_id  = int(parts[2] if is_post else parts[1])

    cat  = _find_category(context, cat_id)
    name = f"<i>{cat.get('name', '')}</i>\n" if cat and cat.get("name") else ""

    text = INSTRUCTION_TEXT.format(name=name)

    tier_idx = context.user_data.get("selected_tier_idx", 0)
    back_kb  = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back", callback_data=f"tier_{cat_id}_{tier_idx}")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu_home")],
    ])
    close_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Tutup", callback_data="instr_close")],
    ])

    if is_post:
        await query.message.reply_text(
            text=text,
            parse_mode="HTML",
            reply_markup=close_kb,
            disable_web_page_preview=True,
        )
    else:
        await _edit(query, text, back_kb)


async def close_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hapus pesan instruction yang dikirim via instr_post."""
    query = update.callback_query
    await query.answer()
    try:
        await query.delete_message()
    except Exception:
        pass


async def out_of_stock_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer("⚠️ Stok kategori ini habis.", show_alert=True)
