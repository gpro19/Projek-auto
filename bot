import logging
import datetime
import os
import asyncio
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pymongo import MongoClient
from qris_saweria import create_payment_qr, check_paid_status  # Asumsi modul ini ada

# ---------------- KONFIGURASI ----------------
TOKEN = os.getenv('TOKEN', "8156404642:AAGUomSAOmFXyoj2Ndka1saAA_t0KjC2H9Q")
GROUP_ID = int(os.getenv('GROUP_ID', "-1002703061780"))
OWNER_USERNAME = os.getenv('OWNER_USERNAME', 'anonbuilder')
SUBSCRIPTION_PRICE = int(os.getenv('SUBSCRIPTION_PRICE', 10000))
DURATION_DAYS = int(os.getenv('DURATION_DAYS', 30))
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://gpro:gpro@tebak9ambar.dioht2p.mongodb.net/?retryWrites=true&w=majority")
PORT = int(os.environ.get('PORT', 8000))
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'MzCoder')

# Validasi konfigurasi
if not all([TOKEN, GROUP_ID, OWNER_USERNAME, ADMIN_USERNAME, MONGO_URI]):
    raise ValueError("Pastikan semua variabel lingkungan (env) telah disetel dengan benar.")

# ---------------- INISIALISASI ----------------
app = Flask(__name__)
client = MongoClient(MONGO_URI)
db = client['telegram_membership']
subs_collection = db['subscriptions']
scheduler = AsyncIOScheduler()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
application = Application.builder().token(TOKEN).build()

# ---------------- HELPER FUNCTIONS ----------------

def get_db_user(user_id: int):
    """Mendapatkan data pengguna dari database."""
    return subs_collection.find_one({"user_id": user_id})

def update_db_user(user_id: int, data: dict, upsert: bool = False):
    """Memperbarui data pengguna di database."""
    subs_collection.update_one({"user_id": user_id}, {"$set": data}, upsert=upsert)

async def check_payment_and_grant_access(user_id: int, transaction_id: str, context: ContextTypes.DEFAULT_TYPE):
    """Memverifikasi pembayaran dan memberikan akses ke grup."""
    try:
        is_paid = check_paid_status(transaction_id)
        if not is_paid:
            return False, "⚠️ Pembayaran belum diterima. Silakan coba lagi nanti."
        
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=DURATION_DAYS)
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            member_limit=1,
            expire_date=expires_at
        )

        update_db_user(
            user_id,
            {
                "status": "active",
                "expires_at": expires_at,
                "invite_link": invite_link.invite_link
            }
        )
        return True, f"✅ Pembayaran sukses!\nKlik link berikut untuk gabung grup:\n\n{invite_link.invite_link}"
    except Exception as e:
        logger.error(f"Gagal memverifikasi pembayaran untuk user {user_id}: {e}")
        return False, "Terjadi kesalahan saat memeriksa status pembayaran."

# ---------------- COMMAND HANDLERS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menyambut pengguna baru."""
    await update.message.reply_text(
        "Halo! 👋 Selamat datang di bot keanggotaan kami.\n\n"
        "Untuk mendapatkan akses ke grup eksklusif, silakan ketik /subscribe.\n"
        "Jika sudah membayar, ketik /status untuk mendapatkan link grup Anda."
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memulai proses berlangganan dengan QRIS."""
    user = update.effective_user
    
    existing_sub = get_db_user(user.id)
    if existing_sub and existing_sub["status"] == "active":
        expires = existing_sub["expires_at"].strftime("%d-%m-%Y %H:%M")
        await update.message.reply_text(f"Langganan kamu masih aktif sampai {expires}.")
        return

    try:
        qr_string, transaction_id, qr_path = create_payment_qr(
            OWNER_USERNAME, SUBSCRIPTION_PRICE, f"{user.id}@telegram.id", f"{user.id}_qris.png", False
        )

        update_db_user(
            user.id,
            {
                "username": user.username,
                "transaction_id": transaction_id,
                "status": "pending",
                "created_at": datetime.datetime.utcnow(),
            },
            upsert=True
        )

        keyboard = [[
            InlineKeyboardButton("✅ Verifikasi Pembayaran", callback_data=f"verify_{transaction_id}"),
            InlineKeyboardButton("❌ Batalkan", callback_data="cancel")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        caption_text = (
            f"💸 **Pembayaran Langganan**\n\n"
            f"📌 **Nominal:** Rp{SUBSCRIPTION_PRICE:,}\n"
            f"⏳ **Waktu:** 5 menit\n"
            f"⚠️ **Instruksi:** Silakan bayar menggunakan QRIS di atas. Setelah berhasil, klik tombol **Verifikasi Pembayaran**.\n\n"
            f"❗ **Bantuan:** Jika ada kendala, silakan hubungi admin: @{ADMIN_USERNAME}"
        )

        await update.message.reply_photo(
            photo=open(qr_path, 'rb'),
            caption=caption_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.exception(f"Gagal membuat QRIS untuk user {user.id}: {e}")
        await update.message.reply_text("Maaf, terjadi kesalahan saat membuat kode QR. Silakan coba lagi nanti.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mengecek status langganan pengguna."""
    user = update.effective_user
    data = get_db_user(user.id)

    if not data:
        await update.message.reply_text("Kamu belum memulai langganan. Ketik /subscribe.")
        return

    if data["status"] == "active":
        expires = data["expires_at"].strftime("%d-%m-%Y %H:%M")
        await update.message.reply_text(
            f"Langganan aktif sampai {expires}.\n\n"
            f"Link grup kamu: {data['invite_link']}"
        )
    elif data["status"] == "pending":
        await update.message.reply_text("Status langganan Anda masih menunggu pembayaran. Silakan cek ulang dengan tombol verifikasi.")
    elif data["status"] == "expired":
        await update.message.reply_text("Langganan Anda telah kedaluwarsa. Silakan ketik /subscribe untuk memperbarui.")
    else:
        await update.message.reply_text("Status langganan tidak diketahui. Silakan hubungi admin.")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menangani klik tombol inline."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user = update.effective_user

    if data.startswith("verify_"):
        transaction_id = data.split("_", 1)[1]
        user_data = get_db_user(user.id)
        
        if not user_data or user_data['transaction_id'] != transaction_id or user_data['status'] == 'active':
            await query.edit_message_caption("Transaksi tidak valid atau sudah kadaluwarsa.")
            return

        await query.edit_message_caption("🔄 Mengecek status pembayaran...")
        success, message = await check_payment_and_grant_access(user.id, transaction_id, context)
        
        await query.edit_message_caption(message)

    elif data == "cancel":
        await query.edit_message_caption("❌ Pembayaran dibatalkan. Ketik /subscribe untuk mencoba lagi.")
        # Hapus transaksi pending dari DB jika perlu

# ---------------- TUGAS TERJADWAL ----------------

async def check_expired_users():
    """Tugas latar belakang untuk mengeluarkan pengguna yang langganannya habis."""
    logger.info("🔄 Memeriksa langganan yang kedaluwarsa...")
    now = datetime.datetime.utcnow()
    expired_users = subs_collection.find({"status": "active", "expires_at": {"$lt": now}})

    for user in expired_users:
        try:
            await application.bot.ban_chat_member(
                chat_id=GROUP_ID,
                user_id=user["user_id"],
                until_date=datetime.datetime.now() + datetime.timedelta(minutes=1)
            )
            update_db_user(user["user_id"], {"status": "expired"})
            logger.info(f"User {user['username']} dikeluarkan karena langganan habis.")
        except Exception as e:
            logger.error(f"Gagal mengeluarkan user {user['user_id']}: {e}")

# ---------------- FLASK ROUTES ----------------

@app.route("/")
def index():
    """Endpoint untuk memeriksa status server."""
    return jsonify({"message": "Bot is running! by @MzCoder"})

# ---------------- STARTUP ----------------

async def run_bot_and_web():
    """Menjalankan bot dan server Flask secara bersamaan."""
    # Menambahkan handler bot
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CallbackQueryHandler(handle_callback))

    # Menjadwalkan tugas
    scheduler.add_job(check_expired_users, 'interval', hours=12)
    scheduler.start()
    logger.info("Scheduler berhasil diatur.")

    # Menjalankan bot dalam mode polling
    await application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    try:
        # Jalankan server Flask dalam thread terpisah
        loop = asyncio.get_event_loop()
        web_server_task = loop.run_in_executor(
            None, lambda: app.run(host="0.0.0.0", port=PORT, use_reloader=False)
        )
        
        # Jalankan bot di main loop
        loop.run_until_complete(run_bot_and_web())
    except KeyboardInterrupt:
        logger.info("Bot dimatikan oleh pengguna.")
    finally:
        scheduler.shutdown()
        client.close()
        logger.info("Aplikasi selesai.")
