"""
services/laravel_api.py
Semua HTTP call ke Laravel ada di sini.
"""

import logging
import requests
from utils.config import LARAVEL_API_URL, BOT_SECRET

logger = logging.getLogger(__name__)

TIMEOUT_SHORT   = 15
TIMEOUT_CHECKER = 1300


def _get(endpoint: str, params: dict = None) -> dict | list:
    url  = f"{LARAVEL_API_URL}/{endpoint.lstrip('/')}"
    logger.debug(f"GET {url} params={params}")
    resp = requests.get(url, params=params, timeout=TIMEOUT_SHORT)
    resp.raise_for_status()
    return resp.json()


def _post(endpoint: str, payload: dict = None, timeout: int = TIMEOUT_SHORT) -> dict:
    url  = f"{LARAVEL_API_URL}/{endpoint.lstrip('/')}"
    logger.debug(f"POST {url}")
    resp = requests.post(url, json=payload, timeout=timeout)
    if not resp.ok:
        logger.error(f"POST {url} → {resp.status_code} | {resp.text[:300]}")
        try:
            return resp.json()
        except Exception:
            resp.raise_for_status()
    return resp.json()


# ── Categories ────────────────────────────────────────────────────────────────

def get_categories() -> list[dict]:
    """GET /api/list-categories"""
    return _get("list-categories")


# ── Bot Order Flow ────────────────────────────────────────────────────────────

def prepare_order(category_id: int, sell_price: float, qty: int, telegram_user_id: int) -> dict:
    """
    POST /api/bot/prepare-order
    Ambil akun available → update ke 'checking' → jalankan checker.
    """
    logger.info(f"[PREPARE_ORDER] user={telegram_user_id} cat={category_id} price={sell_price} qty={qty}")
    return _post("bot/prepare-order", {
        "category_id":      category_id,
        "sell_price":       str(sell_price),
        "qty":              qty,
        "bot_secret":       BOT_SECRET,
        "telegram_user_id": telegram_user_id,
    }, timeout=TIMEOUT_CHECKER)


def create_order(account_ids: list[int], sell_price: float, telegram_user_id: int) -> dict:
    """
    POST /api/bot/create-order
    Buat order, assign akun, update status → sold.
    """
    logger.info(f"[CREATE_ORDER] user={telegram_user_id} accounts={account_ids} price={sell_price}")
    return _post("bot/create-order", {
        "account_ids":      account_ids,
        "sell_price":       str(sell_price),
        "telegram_user_id": telegram_user_id,
        "bot_secret":       BOT_SECRET,
    })


def download_tdata(order_code: str, account_ids: list[int]) -> bytes:
    """
    POST /api/bot/download-tdata
    Return: raw ZIP bytes siap dikirim ke Telegram.
    """
    url     = f"{LARAVEL_API_URL}/bot/download-tdata"
    payload = {
        "bot_secret":  BOT_SECRET,
        "order_code":  order_code,
        "account_ids": account_ids,
    }

    logger.info(f"[DOWNLOAD_TDATA] order={order_code} accounts={account_ids}")

    resp = requests.post(url, json=payload, timeout=TIMEOUT_CHECKER)

    if resp.status_code != 200:
        logger.error(f"[DOWNLOAD_TDATA] {resp.status_code} | {resp.text[:300]}")

    resp.raise_for_status()
    logger.info(f"[DOWNLOAD_TDATA] success — size={len(resp.content):,} bytes")
    return resp.content