"""
utils/logger.py
Setup logging terpusat untuk seluruh bot.

File log:
  logs/telekuy.log          ← log hari ini (symlink-style, selalu nama ini)
  logs/telekuy-2026-03-20.log ← log per hari (rotate otomatis tiap tengah malam WIB)

Format:
  2026-03-20 22:07:45 WIB | INFO     | handlers.order | [ORDER] user=977027817 ...
"""

import logging
import logging.handlers
import os
from datetime import datetime, timezone, timedelta

WIB      = timezone(timedelta(hours=7))
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)


class WIBFormatter(logging.Formatter):
    """Formatter dengan timezone WIB."""
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=WIB)
        return dt.strftime("%Y-%m-%d %H:%M:%S WIB")

    def format(self, record):
        record.levelname = record.levelname.ljust(8)
        return super().format(record)


class WIBTimedRotatingHandler(logging.handlers.TimedRotatingFileHandler):
    """
    Rotate file log setiap tengah malam WIB (bukan UTC).
    Nama file: telekuy-2026-03-20.log
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def computeRollover(self, currentTime):
        """Override — hitung rollover berdasarkan tengah malam WIB."""
        dt      = datetime.fromtimestamp(currentTime, tz=WIB)
        # Tengah malam WIB berikutnya
        next_midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        next_midnight = next_midnight + timedelta(days=1)
        return next_midnight.timestamp()


def setup_logging(level: int = logging.INFO) -> None:
    """
    Panggil SEKALI di bot.py sebelum app.run_polling().
    Setup:
      - File handler  → logs/telekuy.log (rotate harian, simpan 30 hari)
      - Console handler → stdout (untuk development / docker logs)
    """
    fmt = WIBFormatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    # ── File handler — rotate tiap hari, simpan 30 hari ─────────────────────
    log_file    = os.path.join(LOGS_DIR, "telekuy.log")
    file_handler = WIBTimedRotatingHandler(
        filename    = log_file,
        when        = "midnight",
        interval    = 1,
        backupCount = 30,
        encoding    = "utf-8",
        utc         = False,
    )
    # Nama file backup: telekuy-2026-03-20.log
    file_handler.suffix  = "%Y-%m-%d"
    file_handler.namer   = lambda name: name.replace("telekuy.log.", "telekuy-") + ".log"
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)

    # ── Console handler ───────────────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.setLevel(level)

    # ── Root logger ───────────────────────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Kurangi noise dari library eksternal
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        f"Logging aktif — file: {log_file} | level: {logging.getLevelName(level)}"
    )