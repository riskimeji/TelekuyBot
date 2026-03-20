"""
bot.py — Entry point Telekuy Bot
Jalankan: python bot.py

PENTING: ConversationHandler harus didaftarkan PERTAMA sebelum CallbackQueryHandler
biasa, supaya pattern buy_confirm / buy_cancel tidak dicegat handler lain.
"""

import logging
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
)

from utils.config import BOT_TOKEN
from handlers.start   import start_handler, home_callback, membership_check_callback
from handlers.catalog import (
    show_categories,
    show_price_tiers,
    show_item_detail,
    show_instruction,
    close_instruction,
    out_of_stock_alert,
)
from handlers.order   import build_buy_conversation
from handlers.history_order import show_history_order, paginate_history_order
from handlers.rules         import show_rules, close_rules
from handlers.support       import show_support
from handlers.admin         import get_admin_handlers, build_refund_conversation
from handlers.deposit       import (
    show_deposit_menu, build_deposit_conversation,
    admin_approve, admin_reject,
    show_history_deposit,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Telekuy Bot starting...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ── 1. ConversationHandler PERTAMA — menangani buy_* callbacks & teks input ──
    app.add_handler(build_buy_conversation())
    app.add_handler(build_deposit_conversation())
    app.add_handler(build_refund_conversation())

    # ── 2. Commands ──────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", start_handler))

    # ── 3. Menu utama ─────────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(home_callback,          pattern=r"^menu_home$"))
    app.add_handler(CallbackQueryHandler(membership_check_callback, pattern=r"^check_membership$"))
    app.add_handler(CallbackQueryHandler(show_categories, pattern=r"^menu_stock$"))

    # ── 4. Catalog flow ───────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(out_of_stock_alert, pattern=r"^cat_out_of_stock$"))
    app.add_handler(CallbackQueryHandler(show_price_tiers,   pattern=r"^cat_\d+$"))
    app.add_handler(CallbackQueryHandler(show_item_detail,   pattern=r"^tier_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(show_instruction,   pattern=r"^instr_(post_)?\d+$"))
    app.add_handler(CallbackQueryHandler(close_instruction,  pattern=r"^instr_close$"))

    # ── 5. History ────────────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(show_history_order,    pattern=r"^menu_history_order$"))
    app.add_handler(CallbackQueryHandler(paginate_history_order, pattern=r"^hist_order_page_\d+$"))

    # ── 6. Rules ──────────────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(show_rules,         pattern=r"^menu_rules$"))
    app.add_handler(CallbackQueryHandler(show_deposit_menu,  pattern=r"^menu_deposit$"))
    app.add_handler(CallbackQueryHandler(show_history_deposit, pattern=r"^menu_history_deposit$"))
    app.add_handler(CallbackQueryHandler(admin_approve,      pattern=r"^adm_dep_approve_"))
    app.add_handler(CallbackQueryHandler(admin_reject,       pattern=r"^adm_dep_reject_"))
    app.add_handler(CallbackQueryHandler(show_support,       pattern=r"^menu_support$"))
    app.add_handler(CallbackQueryHandler(close_rules,  pattern=r"^rules_close$"))

    # ── Admin commands ────────────────────────────────────────────────────────
    for h in get_admin_handlers():
        app.add_handler(h)

    logger.info("Bot berjalan. Tekan Ctrl+C untuk stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()