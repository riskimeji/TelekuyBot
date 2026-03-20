"""
refund_store.py
History refund/transfer saldo admin disimpan di storage/refunds.json.

Struktur refunds.json:
[
  {
    "refund_id":    "RFD-20260319152045-A1B2C3",
    "target_uid":   977027817,
    "target_name":  "@username",
    "amount":       50000,
    "reason":       "Refund order gagal checker",
    "balance_after": 150000,
    "created_at":   "2026-03-19T15:20:45"
  }
]
"""

import json
import os
import uuid
from datetime import datetime
from utils.helpers import now_wib_str, now_wib
from filelock import FileLock
from utils.config import STORAGE_DIR

REFUNDS_FILE = os.path.join(STORAGE_DIR, "refunds.json")
LOCK_FILE    = REFUNDS_FILE + ".lock"


def _read_all() -> list:
    if not os.path.exists(REFUNDS_FILE):
        return []
    with open(REFUNDS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _write_all(data: list) -> None:
    tmp = REFUNDS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REFUNDS_FILE)


def save_refund(target_uid: int, target_name: str,
                amount: int, reason: str, balance_after: float) -> dict:
    """Simpan record refund baru. Return record yang disimpan."""
    record = {
        "refund_id":     f"RFD-{now_wib().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}",
        "target_uid":    target_uid,
        "target_name":   target_name,
        "amount":        amount,
        "reason":        reason,
        "balance_after": balance_after,
        "created_at":    now_wib_str(),
    }
    with FileLock(LOCK_FILE, timeout=10):
        data = _read_all()
        data.append(record)
        _write_all(data)
    return record


def get_all_refunds(limit: int = 50) -> list:
    """Ambil semua refund, terbaru di atas."""
    return list(reversed(_read_all()))[:limit]


def get_refunds_by_user(target_uid: int) -> list:
    """Ambil history refund untuk user tertentu."""
    return [r for r in reversed(_read_all()) if r["target_uid"] == target_uid]