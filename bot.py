from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler
from datetime import datetime, timedelta
import re
from flask import Flask, jsonify
import threading
from pymongo import MongoClient
import pytz
from qris_saweria import create_payment_qr, check_paid_status
import logging
import os

# Konfigurasi
BOT_TOKEN = "8156404642:AAGUomSAOmFXyoj2Ndka1saAA_t0KjC2H9Q"
GROUP_ID = "-1002703061780"
OWNER_USERNAME = "anonbuilder"
ADMIN_USERNAME = "MzCoder"
SUBSCRIPTION_PRICE = "1000"
DURATION_DAYS = 30 # Durasi langganan dalam hari

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB setup
client = MongoClient("mongodb+srv://ilham:ilham@tebak9ambar.dioht2p.mongodb.net/?retryWrites=true&w=majority&appName=tebak9ambar")
db = client['telegram_bot']
subs_collection = db['subscriptions']

# Flask setup
app = Flask(__name__)

def start(update: Update, context: CallbackContext):
    """Handles the /start command."""
    update.message.reply_text("Halo! Gunakan /subscribe untuk memulai.")

def subscribe(update: Update, context: CallbackContext):
    """Memulai proses berlangganan dengan QRIS."""
    user = update.effective_user
    email = f"{user.username}@telegram.id"

    existing_sub = subs_collection.find_one({"user_id": user.id, "status": "active"})
    if existing_sub:
        expires = existing_sub["expires_at"].strftime("%d-%m-%Y %H:%M")
        update.message.reply_text(f"Langganan kamu masih aktif sampai {expires}.")
        return

    try:
        qr_string, transaction_id, qr_path = create_payment_qr(
            OWNER_USERNAME,
            SUBSCRIPTION_PRICE,
            email,
            f"{user.id}_qris.png",
            False
        )

        subs_collection.update_one(
            {"user_id": user.id},
            {
                "$set": {
                    "username": user.username,
                    "transaction_id": transaction_id,
                    "status": "pending",
                    "created_at": datetime.utcnow(),
                }
            },
            upsert=True
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Verifikasi Pembayaran", callback_data=f"verify_{transaction_id}"),
                InlineKeyboardButton("❌ Batalkan", callback_data="cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        caption_text = (
            f"💸 **Pembayaran Langganan**\n\n"
            f"📌 **Nominal:** Rp{int(SUBSCRIPTION_PRICE):,}\n"
            f"⏳ **Waktu:** 5 menit\n"
            f"⚠️ **Instruksi:** Silakan bayar menggunakan QRIS di atas. Setelah berhasil, klik tombol **Verifikasi Pembayaran** di bawah ini.\n\n"
            f"✅ **Manfaat:** Setelah pembayaran diverifikasi, kamu akan langsung mendapatkan tautan untuk bergabung ke grup eksklusif kami.\n\n"
            f"❗ **Bantuan:** Jika kamu mengalami kendala setelah membayar, silakan hubungi admin: @{ADMIN_USERNAME}"
        )

        with open(qr_path, 'rb') as photo_file:
            update.message.reply_photo(
                photo=photo_file,
                caption=caption_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        os.remove(qr_path) # Hapus file gambar setelah dikirim
    except Exception as e:
        logger.exception("Gagal membuat QRIS: %s", e)
        update.message.reply_text("Maaf, terjadi kesalahan saat membuat kode QR. Silakan coba lagi nanti.")

def status(update: Update, context: CallbackContext):
    """Mengecek status langganan pengguna."""
    user = update.effective_user
    data = subs_collection.find_one({"user_id": user.id})

    if not data:
        update.message.reply_text("Kamu belum mulai langganan. Ketik /subscribe.")
        return

    if data["status"] == "active":
        expires = data["expires_at"].strftime("%d-%m-%Y %H:%M")
        update.message.reply_text(
            f"Langganan aktif sampai {expires}.\n\n"
            f"Link grup kamu: {data['invite_link']}"
        )
        return

    if data["status"] == "pending":
        try:
            is_paid = check_paid_status(data["transaction_id"])
        except Exception as e:
            logger.exception("Gagal cek status pembayaran: %s", e)
            update.message.reply_text("Terjadi kesalahan saat memeriksa status pembayaran.")
            return

        if is_paid:
            expires_at = datetime.utcnow() + timedelta(days=DURATION_DAYS)
            invite_link = context.bot.create_chat_invite_link(
                chat_id=GROUP_ID,
                member_limit=1,
                expire_date=expires_at
            )

            subs_collection.update_one(
                {"user_id": user.id},
                {
                    "$set": {
                        "status": "active",
                        "expires_at": expires_at,
                        "invite_link": invite_link.invite_link
                    }
                }
            )

            update.message.reply_text(
                f"✅ Pembayaran sukses!\nKlik link berikut untuk gabung grup:\n\n{invite_link.invite_link}"
            )
        else:
            update.message.reply_text("⚠️ Pembayaran belum diterima. Silakan coba lagi nanti.")

def handle_callback(update: Update, context: CallbackContext):
    """Menangani klik tombol inline."""
    query = update.callback_query
    query.answer()

    data = query.data
    user = update.effective_user

    if data.startswith("verify_"):
        transaction_id = data.split("_", 1)[1]
        user_data = subs_collection.find_one({"user_id": user.id})

        if not user_data or user_data.get('transaction_id') != transaction_id:
            query.edit_message_caption("Transaksi tidak valid atau sudah kadaluwarsa.")
            return

        query.edit_message_caption("🔄 Mengecek status pembayaran...")

        try:
            is_paid = check_paid_status(transaction_id)
        except Exception as e:
            logger.exception("Gagal cek status pembayaran: %s", e)
            query.edit_message_caption("Terjadi kesalahan saat memeriksa status pembayaran.")
            return
            
        if is_paid:
            expires_at = datetime.utcnow() + timedelta(days=DURATION_DAYS)
            invite_link = context.bot.create_chat_invite_link(
                chat_id=GROUP_ID,
                member_limit=1,
                expire_date=expires_at
            )

            subs_collection.update_one(
                {"user_id": user.id},
                {
                    "$set": {
                        "status": "active",
                        "expires_at": expires_at,
                        "invite_link": invite_link.invite_link
                    }
                }
            )

            query.edit_message_caption(
                f"✅ Pembayaran sukses!\nKlik link berikut untuk gabung grup:\n\n{invite_link.invite_link}"
            )
        else:
            query.edit_message_caption("⚠️ Pembayaran belum diterima. Silakan coba lagi nanti.")
    elif data == "cancel":
        # Hapus transaksi yang menunggu jika ada
        subs_collection.delete_one({"user_id": user.id, "status": "pending"})
        query.edit_message_caption("❌ Pembayaran dibatalkan. Ketik /subscribe untuk mencoba lagi.")

def help_command(update: Update, context: CallbackContext):
    help_text = (
        "<b>Daftar Perintah:</b>\n\n"
        "/subscribe - Memulai proses langganan\n"
        "/status - Mengecek status langgananmu\n"
        "/help - Menampilkan daftar perintah ini"
    )
    
    update.message.reply_html(help_text)

@app.route('/')
def index():
    return jsonify({"message": "Bot is running! by @MzCoder"})

def run_flask():
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 8000))

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
     
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("subscribe", subscribe))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CallbackQueryHandler(handle_callback))
    
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

