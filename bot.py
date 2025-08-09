
import logging
import datetime
import os
import threading
import asyncio
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pymongo import MongoClient
from qris_saweria import create_payment_qr, check_paid_status

# ---------------- CONFIG ----------------
TOKEN = os.getenv('TOKEN', "your-token-here")
GROUP_ID = int(os.getenv('GROUP_ID', "-1001234567890"))
OWNER_USERNAME = os.getenv('OWNER_USERNAME', 'anonbuilder')
SUBSCRIPTION_PRICE = int(os.getenv('SUBSCRIPTION_PRICE', 10000))
DURATION_DAYS = int(os.getenv('DURATION_DAYS', 30))
MONGO_URI = os.getenv("MONGO_URI", "your-mongodb-uri")
PORT = int(os.environ.get('PORT', 8000))
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'adminuser')

# ---------------- INITIALIZATION ----------------
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


# ---------------- COMMAND HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Halo! 👋 Selamat datang di bot keanggotaan kami.\n\n"
        "Untuk mendapatkan akses ke grup eksklusif kami, ketik /subscribe.\n"
        "Jika sudah membayar, ketik /status."
    )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    email = f"{user.username}@telegram.id"

    existing_sub = subs_collection.find_one({"user_id": user.id, "status": "active"})
    if existing_sub:
        expires = existing_sub["expires_at"].strftime("%d-%m-%Y %H:%M")
        await update.message.reply_text(f"Langganan kamu aktif sampai {expires}.")
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
                    "created_at": datetime.datetime.utcnow(),
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

        caption = (
            f"💸 **Pembayaran Langganan**\n\n"
            f"📌 **Nominal:** Rp{SUBSCRIPTION_PRICE:,}\n"
            f"⏳ **Waktu:** 5 menit\n"
            f"⚠️ Silakan bayar via QRIS lalu klik 'Verifikasi Pembayaran'.\n"
            f"❗ Jika ada kendala hubungi admin: @{ADMIN_USERNAME}"
        )

        with open(qr_path, 'rb') as qr_file:
            await update.message.reply_photo(
                photo=qr_file,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )

    except Exception:
        logger.exception("Gagal membuat QRIS")
        await update.message.reply_text("Terjadi kesalahan saat membuat QRIS. Silakan coba lagi.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = subs_collection.find_one({"user_id": user.id})

    if not data:
        await update.message.reply_text("Kamu belum mulai langganan. Ketik /subscribe.")
        return

    if data["status"] == "active":
        expires = data["expires_at"].strftime("%d-%m-%Y %H:%M")
        await update.message.reply_text(
            f"Langganan aktif sampai {expires}.\nLink grup kamu: {data['invite_link']}"
        )
        return

    if data["status"] == "pending":
        try:
            is_paid = check_paid_status(data["transaction_id"])
        except Exception:
            logger.exception("Gagal cek status pembayaran")
            await update.message.reply_text("Gagal memeriksa status pembayaran.")
            return

        if is_paid:
            expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=DURATION_DAYS)
            invite_link = await context.bot.create_chat_invite_link(
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

            await update.message.reply_text(
                f"✅ Pembayaran sukses! Link grup:\n{invite_link.invite_link}"
            )
        else:
            await update.message.reply_text("⚠️ Pembayaran belum diterima.")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    if data.startswith("verify_"):
        transaction_id = data.split("_", 1)[1]
        user_data = subs_collection.find_one({"user_id": user.id})

        if not user_data or user_data['transaction_id'] != transaction_id:
            await query.edit_message_caption("Transaksi tidak valid.")
            return

        await query.edit_message_caption("🔄 Mengecek status pembayaran...")

        is_paid = check_paid_status(transaction_id)
        if is_paid:
            expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=DURATION_DAYS)
            invite_link = await context.bot.create_chat_invite_link(
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

            await query.edit_message_caption(
                f"✅ Pembayaran sukses! Link grup:\n{invite_link.invite_link}"
            )
        else:
            await query.edit_message_caption("⚠️ Pembayaran belum diterima.")
    elif data == "cancel":
        await query.edit_message_caption("❌ Pembayaran dibatalkan.")

# ---------------- EXPIRED CHECK JOB ----------------
async def check_expired_users():
    logger.info("🔄 Cek langganan kedaluwarsa...")
    now = datetime.datetime.utcnow()
    expired_users = subs_collection.find({"status": "active", "expires_at": {"$lt": now}})

    for user in expired_users:
        try:
            await application.bot.ban_chat_member(
                chat_id=GROUP_ID,
                user_id=user["user_id"],
                until_date=datetime.datetime.utcnow() + datetime.timedelta(minutes=1)
            )
            subs_collection.update_one({"user_id": user["user_id"]}, {"$set": {"status": "expired"}})
            logger.info(f"User {user['username']} dikeluarkan.")
        except Exception as e:
            logger.error(f"❌ Gagal kick user {user['user_id']}: {e}")

# ---------------- FLASK ROUTE ----------------
@app.route("/")
def index():
    return jsonify({"message": "Bot is running!"})

# ---------------- STARTUP ----------------
def run_flask():
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

async def main():
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CallbackQueryHandler(handle_callback))

    scheduler.add_job(check_expired_users, 'interval', hours=12)
    scheduler.start()

    # Jalankan Flask di thread terpisah
    threading.Thread(target=run_flask).start()

    # Jalankan bot polling (blocking call)
    logger.info("🚀 Bot Telegram berjalan dalam mode polling...")
    await application.run_polling()
