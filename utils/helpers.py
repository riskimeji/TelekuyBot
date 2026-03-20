"""
utils/helpers.py
Helper umum — timezone WIB dan formatter.
"""

from datetime import datetime, timezone, timedelta

WIB = timezone(timedelta(hours=7))


def now_wib() -> datetime:
    """Return datetime sekarang dalam WIB."""
    return datetime.now(tz=WIB)


def now_wib_str() -> str:
    """Return ISO string WIB untuk disimpan ke JSON."""
    return now_wib().isoformat()


def fmt_date_wib(iso: str | None) -> str:
    """
    Parse ISO string (UTC atau WIB) → tampilkan sebagai WIB.
    Format output: '19/03/2026 22:07 WIB'
    """
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso)
        # Kalau tidak ada timezone info → anggap UTC, konversi ke WIB
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_wib = dt.astimezone(WIB)
        return dt_wib.strftime("%d/%m/%Y %H:%M WIB")
    except Exception:
        return str(iso)[:16]