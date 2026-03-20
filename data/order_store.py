"""
order_store.py
History order per user disimpan di orders.json.

Struktur orders.json:
{
  "123456789": [
    {
      "order_code":    "ORD-ABC123",        ← dari Laravel
      "item_id":       "id6",
      "item_name":     "Indonesia Premium",
      "qty":           1,
      "price_usdt":    1.50,
      "status":        "checking" | "success" | "failed",
      "created_at":    "2024-01-01T10:00:00",
      "completed_at":  null
    }
  ]
}
"""

import json
import os
from datetime import datetime
from utils.helpers import now_wib_str
from filelock import FileLock
from utils.config import STORAGE_DIR

ORDERS_FILE = os.path.join(STORAGE_DIR, "orders.json")
LOCK_FILE = ORDERS_FILE + ".lock"


def _read_all() -> dict:
    if not os.path.exists(ORDERS_FILE):
        return {}
    with open(ORDERS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _write_all(data: dict) -> None:
    tmp_file = ORDERS_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, ORDERS_FILE)


def create_order(user_id: int, order_code: str, item_id: str,
                 item_name: str, qty: int, price_idr: float) -> dict:
    """Buat record order baru dengan status 'checking'."""
    uid = str(user_id)
    record = {
        "order_code":   order_code,
        "item_id":      item_id,
        "item_name":    item_name,
        "qty":          qty,
        "price_idr":   price_idr,
        "status":       "checking",
        "created_at":   now_wib_str(),
        "completed_at": None,
    }

    with FileLock(LOCK_FILE, timeout=10):
        data = _read_all()
        if uid not in data:
            data[uid] = []
        data[uid].append(record)
        _write_all(data)

    return record


def update_order_status(user_id: int, order_code: str, status: str) -> dict | None:
    """Update status order: 'checking' → 'success' atau 'failed'."""
    uid = str(user_id)
    with FileLock(LOCK_FILE, timeout=10):
        data = _read_all()
        for record in data.get(uid, []):
            if record["order_code"] == order_code:
                record["status"]       = status
                record["completed_at"] = now_wib_str()
                _write_all(data)
                return record
    return None


def get_user_orders(user_id: int, limit: int = 10) -> list:
    """Ambil history order user, terbaru di atas."""
    data = _read_all()
    records = data.get(str(user_id), [])
    return list(reversed(records))[:limit]