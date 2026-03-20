"""
handlers/rules.py
Tampilkan halaman Rules & Ketentuan Pembelian.
callback_data: menu_rules
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

RULES_TEXT = (
    "📜 <b>Syarat &amp; Ketentuan Pembelian</b>\n"
    "──────────────────────\n\n"
    "Dengan melakukan pembelian, kamu dianggap telah membaca dan menyetujui seluruh ketentuan berikut.\n\n"

    "✅ <b>Garansi Penggantian</b>\n"
    "Penggantian akun diberikan <b>HANYA</b> jika:\n"
    "• Akun tidak dapat login sama sekali sejak diterima.\n"
    "• Laporan diajukan dalam <b>maksimal 30 menit</b> setelah pembelian.\n"
    "• Akun belum pernah digunakan untuk aktivitas apapun.\n\n"

    "❌ <b>Penggantian TIDAK Berlaku Jika:</b>\n"
    "• Sudah lebih dari 30 menit sejak pembelian.\n"
    "• Akun digunakan untuk spam, invite massal, scraping, atau aktivitas lain yang berisiko ban.\n"
    "• Akun dijalankan menggunakan proxy berisiko tinggi: <code>tor, astro, dc, asocs</code> atau proxy datacenter murah.\n"
    "• Akun terkena banned/frozen akibat penggunaan oleh pembeli.\n"
    "• Pembeli mengubah password, 2FA, atau data akun lainnya.\n"
    "• Akun dibagikan atau dijual kembali ke pihak lain.\n"
    "• Sesi login sudah aktif lebih dari satu device secara bersamaan.\n\n"

    "⚠️ <b>Ketentuan Penggunaan</b>\n"
    "• Kami sangat menyarankan pembelian dalam jumlah kecil terlebih dahulu untuk memastikan akun sesuai kebutuhan kamu.\n"
    "• Akun yang dikirim adalah akun asli — kualitas dan masa aktif sesuai deskripsi kategori.\n"
    "• Jangan login lebih dari <b>1 device</b> secara bersamaan untuk menghindari sesi terputus.\n"
    "• Gunakan proxy berkualitas baik (residential) untuk hasil optimal.\n\n"

    "💳 <b>Ketentuan Saldo &amp; Pembayaran</b>\n"
    "• Saldo yang sudah di-deposit tidak dapat ditarik kembali (non-refundable).\n"
    "• Saldo hanya dapat digunakan untuk pembelian produk di Telekuy.\n"
    "• Jika terjadi kegagalan sistem dari pihak kami, saldo akan dikembalikan penuh.\n\n"

    "📞 <b>Komplain &amp; Support</b>\n"
    "• Komplain hanya dilayani melalui @TelekuySupport.\n"
    "• Sertakan <b>order code</b> dan <b>bukti screenshot</b> saat mengajukan komplain.\n"
    "• Komplain tanpa bukti tidak akan diproses.\n\n"

    "──────────────────────\n"
    "Telekuy berhak mengubah ketentuan ini sewaktu-waktu tanpa pemberitahuan sebelumnya."
)


async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Rules terlalu panjang untuk caption foto (limit 1024 karakter).
    Selalu kirim sebagai pesan teks baru — pesan home tetap utuh di atas.
    """
    query = update.callback_query
    await query.answer()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Tutup", callback_data="rules_close")],
    ])

    await query.message.reply_text(
        text=RULES_TEXT,
        parse_mode="HTML",
        reply_markup=kb,
    )


async def close_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hapus pesan rules."""
    query = update.callback_query
    await query.answer()
    try:
        await query.delete_message()
    except Exception:
        pass