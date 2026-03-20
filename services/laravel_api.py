"""
services/laravel_api.py
Semua HTTP call ke Laravel ada di sini.
"""

import requests
from utils.config import LARAVEL_API_URL, BOT_SECRET

TIMEOUT_SHORT  = 15    # untuk GET biasa
TIMEOUT_CHECKER = 1300  # checker bisa lama (set_time_limit(0) di Laravel)


def _get(endpoint: str, params: dict = None) -> dict | list:
    url  = f"{LARAVEL_API_URL}/{endpoint.lstrip('/')}"
    resp = requests.get(url, params=params, timeout=TIMEOUT_SHORT)
    resp.raise_for_status()
    return resp.json()


def _post(endpoint: str, payload: dict = None, timeout: int = TIMEOUT_SHORT) -> dict:
    url  = f"{LARAVEL_API_URL}/{endpoint.lstrip('/')}"
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# ── Categories ───────────────────────────────────────────────────────────────

def get_categories() -> list[dict]:
    """GET /api/list-categories"""
    return _get("list-categories")


# ── Bot Order Flow ───────────────────────────────────────────────────────────

def prepare_order(category_id: int, sell_price: float, qty: int) -> dict:
    """
    POST /api/bot/prepare-order
    Ambil akun available → update ke 'checking' → jalankan checker.
    Return:
      { "status": "success", "account_ids": [1, 2] }
      { "status": "error",   "message": "..." }
    Timeout panjang karena checker bisa makan waktu.
    """
    return _post("bot/prepare-order", {
        "category_id": category_id,
        "sell_price":  str(sell_price),
        "qty":         qty,
    }, timeout=TIMEOUT_CHECKER)


def create_order(account_ids: list[int], sell_price: float, telegram_user_id: int) -> dict:
    """
    POST /api/bot/create-order
    Buat order, assign akun, update status → sold.
    Return:
      { "status": "success", "order_code": "ABC123", "order_id": 5 }
    """
    return _post("bot/create-order", {
        "account_ids":      account_ids,
        "sell_price":       str(sell_price),
        "telegram_user_id": telegram_user_id,
    })


def download_tdata(order_code: str, account_ids: list[int]) -> bytes:
    """
    POST /api/bot/download-tdata
    Return: raw ZIP bytes siap dikirim ke Telegram.
    Timeout panjang karena generate tdata bisa makan waktu.
    """
    import logging
    logger = logging.getLogger(__name__)

    url     = f"{LARAVEL_API_URL}/bot/download-tdata"
    payload = {
        "bot_secret":  BOT_SECRET,
        "order_code":  order_code,
        "account_ids": account_ids,
    }

    logger.info(f"[DOWNLOAD_TDATA] POST {url}")
    logger.info(f"[DOWNLOAD_TDATA] payload: bot_secret={BOT_SECRET[:6]}... order_code={order_code} account_ids={account_ids}")

    resp = requests.post(url, json=payload, timeout=TIMEOUT_CHECKER)

    logger.info(f"[DOWNLOAD_TDATA] status: {resp.status_code}")
    if resp.status_code != 200:
        logger.error(f"[DOWNLOAD_TDATA] response body: {resp.text[:500]}")

    resp.raise_for_status()
    return resp.content