"""
utils/qris.py
Convert static QRIS string → dynamic QRIS with embedded amount, then render to PNG bytes.
"""

import io
import qrcode
from PIL import Image


def _crc16_ccitt(data: str) -> str:
    crc = 0xFFFF
    for char in data:
        crc ^= ord(char) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return format(crc, "04X")


def make_dynamic_qris(static_qris: str, amount: int) -> str:
    """
    Ubah QRIS static → dynamic dengan amount ter-embed.
    - Ubah Point of Initiation '010211' → '010212'
    - Sisipkan field 54 (Transaction Amount) sebelum '5802' (Country Code)
    - Hitung ulang CRC16-CCITT
    """
    qris = static_qris.strip()

    # Ganti static → dynamic
    qris = qris.replace("010211", "010212", 1)

    # Hapus CRC lama (8 karakter terakhir: "6304XXXX")
    body = qris[:-8]  # sisa tanpa "6304XXXX"

    # Sisipkan amount field sebelum "5802" (Country Code)
    amount_str = str(amount)
    amount_field = f"54{len(amount_str):02d}{amount_str}"

    if "5802" in body:
        body = body.replace("5802", f"{amount_field}5802", 1)
    else:
        body += amount_field

    # Tambah CRC tag + hitung ulang
    body_with_crc_tag = body + "6304"
    new_crc = _crc16_ccitt(body_with_crc_tag)

    return body_with_crc_tag + new_crc


def qris_to_image_bytes(qris_string: str) -> bytes:
    """Generate QR image dari QRIS string, return PNG bytes siap kirim ke Telegram."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(qris_string)
    qr.make(fit=True)

    img: Image.Image = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def decode_qris_from_image(image_path: str) -> str:
    """Baca QRIS string dari file gambar (JPG/PNG)."""
    from pyzbar.pyzbar import decode as pyzbar_decode

    img = Image.open(image_path)
    results = pyzbar_decode(img)
    if not results:
        # Coba grayscale
        results = pyzbar_decode(img.convert("L"))
    if not results:
        raise ValueError(f"Tidak bisa decode QR dari {image_path}")
    return results[0].data.decode("utf-8")
