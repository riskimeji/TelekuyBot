"""
deposit_store.py
History deposit per user disimpan di deposits.json.
Pakai filelock + atomic write supaya aman multi-user.

Struktur deposits.json:
{
  "123456789": [
    {
      "deposit_id":   "DEP-20240101123045-A1B2C3",
      "method":       "Dana" | "Gopay" | "OVO" | "QRIS" | ...,
      "amount_base":  50000,      ← nominal asli yang diinput user
      "unique_code":  342,         ← kode unik tambahan
      "amount_total": 50342,       ← yang harus dibayar (base + unique)
      "status":       "pending" | "confirmed" | "failed",
      "created_at":   "2024-01-01T12:30:45",
      "confirmed_at": "2024-01-01T12:35:00" | null
    }
  ]
}
"""

import json
import os
import uuid
from datetime import datetime
from utils.helpers import now_wib_str, now_wib
from filelock import FileLock
from utils.config import STORAGE_DIR

DEPOSITS_FILE = os.path.join(STORAGE_DIR, "deposits.json")
LOCK_FILE     = DEPOSITS_FILE + ".lock"


# ── internal ──────────────────────────────────────────────────────────────────

def _read_all() -> dict:
    if not os.path.exists(DEPOSITS_FILE):
        return {}
    with open(DEPOSITS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _write_all(data: dict) -> None:
    """Atomic write: tulis ke .tmp dulu, rename ke file asli."""
    tmp = DEPOSITS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DEPOSITS_FILE)


# ── public API ────────────────────────────────────────────────────────────────

def create_deposit(user_id: int, method: str, amount_base: int,
                   unique_code: int) -> dict:
    """
    Buat record deposit baru dengan status 'pending'.

    Args:
        user_id     : Telegram user ID
        method      : Nama metode (Dana, Gopay, QRIS, dll)
        amount_base : Nominal asli yang diinput user (tanpa kode unik)
        unique_code : Kode unik 3 digit (100-999) untuk identifikasi transfer

    Return: dict record yang baru dibuat (termasuk deposit_id)
    """
    uid        = str(user_id)
    deposit_id = (
        f"DEP-{now_wib().strftime('%Y%m%d%H%M%S')}"
        f"-{uuid.uuid4().hex[:6].upper()}"
    )

    record = {
        "deposit_id":   deposit_id,
        "method":       method,
        "amount_base":  amount_base,
        "unique_code":  unique_code,
        "amount_total": amount_base + unique_code,
        "status":       "pending",
        "created_at":   now_wib_str(),
        "confirmed_at": None,
    }

    with FileLock(LOCK_FILE, timeout=10):
        data = _read_all()
        if uid not in data:
            data[uid] = []
        data[uid].append(record)
        _write_all(data)

    return record


def confirm_deposit(user_id: int, deposit_id: str) -> dict | None:
    """
    Tandai deposit sebagai 'confirmed' dan catat waktu konfirmasi.
    Dipanggil oleh admin_approve di deposit.py.
    Return: record yang diupdate, None kalau tidak ketemu.
    """
    uid = str(user_id)
    with FileLock(LOCK_FILE, timeout=10):
        data = _read_all()
        for record in data.get(uid, []):
            if record["deposit_id"] == deposit_id:
                record["status"]       = "confirmed"
                record["confirmed_at"] = now_wib_str()
                _write_all(data)
                return record
    return None


def fail_deposit(user_id: int, deposit_id: str) -> None:
    """
    Tandai deposit sebagai 'failed'.
    Dipanggil saat user cancel atau admin reject.
    """
    uid = str(user_id)
    with FileLock(LOCK_FILE, timeout=10):
        data = _read_all()
        for record in data.get(uid, []):
            if record["deposit_id"] == deposit_id:
                record["status"] = "failed"
                _write_all(data)
                return


def get_user_deposits(user_id: int, limit: int = 10) -> list:
    """
    Ambil history deposit user, terbaru di atas.
    Return list of dict, max `limit` item.
    """
    data    = _read_all()
    records = data.get(str(user_id), [])
    return list(reversed(records))[:limit]


def get_pending_deposits() -> list[dict]:
    """
    Ambil semua deposit berstatus 'pending' dari semua user.
    Berguna untuk admin melihat antrian yang belum diproses.
    Return: [{"user_id": ..., "record": {...}}, ...]
    """
    data    = _read_all()
    pending = []
    for uid, records in data.items():
        for r in records:
            if r.get("status") == "pending":
                pending.append({"user_id": int(uid), "record": r})
    # Urutkan dari yang terlama (supaya admin proses FIFO)
    pending.sort(key=lambda x: x["record"]["created_at"])
    return pending