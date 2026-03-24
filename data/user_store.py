"""
user_store.py
Semua operasi baca/tulis users.json ada di sini.
Pakai filelock supaya aman saat banyak user hit bersamaan — tidak crash, tidak korup.
"""

import json
import os
from datetime import datetime
from utils.helpers import now_wib_str
from filelock import FileLock
from utils.config import STORAGE_DIR
import logging
logger = logging.getLogger(__name__)

USERS_FILE = os.path.join(STORAGE_DIR, "users.json")
LOCK_FILE = USERS_FILE + ".lock"


def _read_all() -> dict:
    """Baca seluruh isi users.json. Return dict kosong kalau file belum ada."""
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _write_all(data: dict) -> None:
    """Tulis ulang seluruh users.json secara atomic (tulis ke .tmp dulu, lalu rename)."""
    tmp_file = USERS_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, USERS_FILE)   # atomic di semua OS modern


def get_user(user_id: int) -> dict | None:
    """Ambil data satu user. Return None kalau belum ada."""
    users = _read_all()
    return users.get(str(user_id))


def upsert_user(user_id: int, first_name: str, last_name: str | None,
                username: str | None, language_code: str | None) -> dict:
    """
    Simpan atau update data user.
    - Kalau user baru  → buat record baru dengan balance 0
    - Kalau sudah ada  → update nama/username saja, balance tidak disentuh
    Return: data user terbaru
    """
    uid = str(user_id)
    with FileLock(LOCK_FILE, timeout=10):
        users = _read_all()

        if uid not in users:
            # User baru
            users[uid] = {
                "user_id":       user_id,
                "first_name":    first_name,
                "last_name":     last_name or "",
                "username":      username or "",
                "language_code": language_code or "id",
                "balance_idr":  0.0,
                "total_spent":   0.0,
                "total_orders":  0,
                "is_banned":     False,
                "joined_at":     now_wib_str(),
                "last_seen":     now_wib_str(),
            }
        else:
            # User lama — update info profil & last_seen saja
            users[uid]["first_name"]    = first_name
            users[uid]["last_name"]     = last_name or ""
            users[uid]["username"]      = username or ""
            users[uid]["language_code"] = language_code or users[uid].get("language_code", "id")
            users[uid]["last_seen"]     = now_wib_str()

        _write_all(users)
        return users[uid]


def update_balance(user_id: int, delta: float, track_spent: bool = False) -> float:
    """
    Tambah (delta positif) atau kurangi (delta negatif) balance.
    track_spent=True  → tambah total_spent, hanya dipanggil saat order SUKSES.
    track_spent=False → murni mutasi balance (hold / refund), total_spent tidak berubah.
    Raise ValueError kalau balance tidak cukup.
    """
    uid = str(user_id)
    with FileLock(LOCK_FILE, timeout=10):
        users = _read_all()
        if uid not in users:
            raise KeyError(f"User {user_id} tidak ditemukan.")

        new_balance = round(users[uid]["balance_idr"] + delta, 6)
        if new_balance < 0:
            raise ValueError("Saldo tidak mencukupi.")
        
        # balance now before update
        logger.info(f"Updating balance for user {user_id}: {users[uid]['balance_idr']} -> {new_balance} (delta: {delta})")

        users[uid]["balance_idr"] = new_balance
        if track_spent and delta < 0:
            users[uid]["total_spent"] = round(users[uid]["total_spent"] + abs(delta), 6)
        _write_all(users)
        return new_balance


def add_total_spent(user_id: int, amount: float) -> None:
    """Tambah total_spent — HANYA dipanggil saat order benar-benar sukses."""
    uid = str(user_id)
    with FileLock(LOCK_FILE, timeout=10):
        users = _read_all()
        if uid in users:
            users[uid]["total_spent"] = round(users[uid].get("total_spent", 0.0) + amount, 6)
            _write_all(users)


def increment_order_count(user_id: int) -> None:
    """Tambah total_orders setelah order berhasil."""
    uid = str(user_id)
    with FileLock(LOCK_FILE, timeout=10):
        users = _read_all()
        if uid in users:
            users[uid]["total_orders"] += 1
            _write_all(users)


def get_all_users() -> dict:
    """Return semua user — dipakai untuk /broadcast."""
    return _read_all()


def set_banned(user_id: int, status: bool) -> None:
    """Ban / unban user."""
    uid = str(user_id)
    with FileLock(LOCK_FILE, timeout=10):
        users = _read_all()
        if uid in users:
            users[uid]["is_banned"] = status
            _write_all(users)