import logging
import datetime
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pymongo import MongoClient
from qris_saweria import create_payment_qr, check_paid_status
from flask import Flask, request, jsonify

# ---------------- CONFIG ----------------
# Ambil dari environment variable untuk keamanan, atau ganti dengan string Anda
TOKEN = os.getenv('TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN')
GROUP_ID = int(os.getenv('GROUP_ID', -1001234567890))
OWNER_USERNAME = os.getenv('OWNER_USERNAME', 'anonbuilder')
SUBSCRIPTION_PRICE = int(os.getenv('SUBSCRIPTION_PRICE', 10000))
DURATION_DAYS = int(os.getenv('DURATION_DAYS', 30))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

# URL webhook harus diatur di lingkungan produksi
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-domain.com/webhook")
PORT = int(os.environ.get('PORT', 5000))
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'rizyul04')

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

# ---------------- BOT COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menyambut pengguna dan menjelaskan fungsi bot."""
    await update.message.reply_text(
        "Halo! 👋 Selamat datang di bot keanggotaan kami.\n\n"
        "Untuk mendapatkan akses ke grup eksklusif kami, silakan ketik /subscribe.\n"
        "Jika Anda sudah membayar, ketik /status untuk mendapatkan link grup Anda."
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memulai proses berlangganan baru dengan tombol verifikasi."""
    user = update.effective_user
    email = f"{user.username}@telegram.id"

    existing_sub = subs_collection.find_one({"user_id": user.id, "status": "active"})
    if existing_sub:
        expires = existing_sub["expires_at"].strftime("%d-%m-%Y %H:%M")
        await update.message.reply_text(f"Langganan kamu masih aktif sampai {expires}.")
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

        caption_text = (
            f"💸 **Pembayaran Langganan**\n\n"
            f"📌 **Nominal:** Rp{SUBSCRIPTION_PRICE:,}\n"
            f"⏳ **Waktu:** 5 menit\n"
            f"⚠️ **Instruksi:** Silakan bayar menggunakan QRIS di atas. Setelah berhasil, klik tombol **Verifikasi Pembayaran** di bawah ini.\n\n"
            f"✅ **Manfaat:** Setelah pembayaran diverifikasi, kamu akan langsung mendapatkan tautan untuk bergabung ke grup eksklusif kami.\n\n"
            f"❗ **Bantuan:** Jika kamu mengalami kendala setelah membayar, silakan hubungi admin: @{ADMIN_USERNAME}"
        )

        await update.message.reply_photo(
            photo=open(qr_path, 'rb'),
            caption=caption_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Gagal membuat QRIS untuk user {user.username}: {e}")
        await update.message.reply_text(
            "Maaf, terjadi kesalahan saat membuat kode QR. Silakan coba lagi nanti."
        )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mengecek status langganan dan memberikan link grup jika sudah dibayar."""
    user = update.effective_user
    data = subs_collection.find_one({"user_id": user.id})

    if not data:
        await update.message.reply_text("Kamu belum mulai langganan. Ketik /subscribe.")
        return

    if data["status"] == "active":
        expires = data["expires_at"].strftime("%d-%m-%Y %H:%M")
        await update.message.reply_text(
            f"Langganan aktif sampai {expires}.\n\n"
            f"Link grup kamu: {data['invite_link']}"
        )
        return

    if data["status"] == "pending":
        try:
            is_paid = check_paid_status(data["transaction_id"])
        except Exception as e:
            logger.error(f"Gagal cek status pembayaran untuk transaction ID {data['transaction_id']}: {e}")
            await update.message.reply_text(
                "Maaf, terjadi kesalahan saat memeriksa status pembayaran. Silakan coba lagi nanti."
            )
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
                f"✅ Pembayaran sukses!\nKlik link berikut untuk gabung grup:\n\n{invite_link.invite_link}\n\n"
                f"Link ini hanya untukmu dan akan kedaluwarsa bersamaan dengan langgananmu."
            )
        else:
            await update.message.reply_text("⚠️ Pembayaran belum diterima. Silakan coba lagi nanti.")
            return

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menangani klik tombol inline."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user = update.effective_user

    if data.startswith("verify_"):
        transaction_id = data.split("_")[1]
        data = subs_collection.find_one({"user_id": user.id})

        if not data or data['transaction_id'] != transaction_id:
            await query.edit_message_text("Transaksi tidak valid atau sudah kadaluwarsa.")
            return

        await query.edit_message_caption(caption="Mengecek status pembayaran Anda...")

        is_paid = check_paid_status(data["transaction_id"])

        if is_paid:
            expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=DURATION_DAYS)

            invite_link = await context.bot.create_chat_invite_link(
                chat_id=GROUP_ID,
                member_limit=1,
                expire_date=expires_at
            )

            subs_collection.update_one(
                {"user_id": user.id},
                {"$set": {"status": "active", "expires_at": expires_at, "invite_link": invite_link.invite_link}}
            )
            await query.edit_message_caption(
                f"✅ Pembayaran sukses!\nKlik link berikut untuk gabung grup:\n\n{invite_link.invite_link}"
            )
        else:
            await query.edit_message_caption("⚠️ Pembayaran belum diterima. Silakan coba lagi nanti.")
    elif data == "cancel":
        await query.edit_message_caption(
            "Pembayaran dibatalkan. Jika Anda ingin berlangganan, ketik /subscribe lagi."
        )

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("subscribe", subscribe))
application.add_handler(CommandHandler("status", status))
application.add_handler(CallbackQueryHandler(handle_callback))

# ---------------- BACKGROUND TASKS ----------------

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
            subs_collection.update_one({"user_id": user["user_id"]}, {"$set": {"status": "expired"}})
            logger.info(f"User {user['username']} dikeluarkan karena langganan habis.")
        except Exception as e:
            logger.error(f"Gagal kick user {user['user_id']}: {e}")

# ---------------- FLASK ROUTES ----------------

@app.route("/")
def index():
    """Endpoint untuk memeriksa apakah server berjalan."""
    return jsonify({"message": "Bot is running! by @MzCoder"})

@app.route("/webhook", methods=["POST"])
async def telegram_webhook_handler():
    """Handler untuk menerima update dari Telegram."""
    update = Update.de_json(request.get_json(force=True), application.bot)
    await application.process_update(update)
    return "ok"

# ---------------- MAIN ----------------

async def run_bot_async():
    """Fungsi asinkron untuk menyiapkan bot dan scheduler."""
    await application.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook telah diatur ke: {WEBHOOK_URL}")
    scheduler.add_job(check_expired_users, 'interval', hours=12)
    scheduler.start()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run_bot_async())
        app.run(host='0.0.0.0', port=PORT, debug=True)
    except Exception as e:
        logger.error(f"Terjadi kesalahan fatal: {e}")
        loop.close()
# URL webhook harus diatur di lingkungan produksi
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-domain.com/webhook")
PORT = int(os.environ.get('PORT', 5000))
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'rizyul04')

# -----TOKEN = os.getenv('', 'YOUR_TELEGRAM_BOT_TOKEN')
GROUP_ID = int(os.getenv('GROUP_ID', -1001234567890))
OWNER_USERNAME = os.getenv('OWNER_USERNAME', 'anonbuilder')
SUBSCRIPTION_PRICE = int(os.getenv('SUBSCRIPTION_PRICE', 10000))
DURATION_DAYS = int(os.getenv('DURATION_DAYS', 30))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

# URL webhook harus diatur di lingkungan produksi
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-domain.com/webhook")
PORT = int(os.environ.get('PORT', 5000))
ADMIN_USERNAME = os.getenv('ADMI----------- menjelaskan fungsi bot."""
    await update.message.reply_text(
        "Halo! 👋 Selamat datang di bot keanggotaan kami.\n\n"
        "Untuk mendapatkan akses ke grup eksklusif kami, silakan ketik /subscribe.\n"
        "Jika Anda sudah membayar, ketik /status untuk mendapatkan link grup Anda."
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memulai proses berlangganan baru dengan tombol verifikasi."""
    user = update.effective_user
    email = f"{user.username}@telegram.id"

    existing_sub = subs_collection.find_one({"user_id": user.id, "status": "active"})
    if existing_sub:
        expires = existing_sub["expires_at"].strftime("%d-%m-%Y %H:%M")
        await update.message.reply_text(f"Langganan kamu masih aktif sampai {expires}.")
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
        reply_markup = InlineKeION ----------------
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

# ---------------- BOT COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menyambut pengguna dan menjelaskan fungsi bot."""
    await update.message.reply_text(
        "Halo! 👋 Selamat datang di bot keanggotaan kami.\n\n"
        "Untuk mendapatkan akses ke grup eksklusif kami, silakan ketik /subscribe.\n"
        "Jika Anda sudah membayar, ketik /status untuk mendapatkan link grup Anda."
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memulai proses berlangganan baru dengan tombol verifikasi."""
    user = update.effective_user
    email = f"{user.username}@telegram.id"

    existing_sub = subs_collection.find_one({"user_id": user.id, "status": "active"})
    if existing_sub:
        expires = existing_sub["expires_at"].strftime("%d-%m-%Y %H:%M")
        await update.message.reply_text(f"Langganan kamu masih aktif sampai {expires}.")
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

        caption_text = (
            f"💸 **Pembayaran Langganan**\n\n"
            f"📌 **Nominal:** Rp{SUBSCRIPTION_PRICE:,}\n"
            f"⏳ **Waktu:** 5 menit\n"
            f"⚠️ **Instruksi:** Silakan bayar menggunakan QRIS di atas. Setelah berhasil, klik tombol **Verifikasi Pembayaran** di bawah ini.\n\n"
            f"✅ **Manfaat:** Setelah pembayaran diverifikasi, kamu akan langsung mendapatkan tautan untuk bergabung ke grup eksklusif kami.\n\n"
            f"❗ **Bantuan:** Jika kamu mengalami kendala setelah membayar, silakan hubungi admin: @{ADMIN_USERNAME}"
        )

        await update.message.reply_photo(
            photo=open(qr_path, 'rb'),
            caption=caption_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Gagal membuat QRIS untuk user {user.username}: {e}")
        await update.message.reply_text(
            "Maaf, terjadi kesalahan saat membuat kode QR. Silakan coba lagi nanti."
        )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mengecek status langganan dan memberikan link grup jika sudah dibayar."""
    user = update.effective_user
    data = subs_collection.find_one({"user_id": user.id})

    if not data:
        await update.message.reply_text("Kamu belum mulai langganan. Ketik /subscribe.")
        return

    if data["status"] == "active":
        expires = data["expires_at"].strftime("%d-%m-%Y %H:%M")
        await update.message.reply_text(
            f"Langganan aktif sampai {expires}.\n\n"
            f"Link grup kamu: {data['invite_link']}"
        )
        return

    if data["status"] == "pending":
        try:
            is_paid = check_paid_status(data["transaction_id"])
        except Exception as e:
            logger.error(f"Gagal cek status pembayaran untuk transaction ID {data['transaction_id']}: {e}")
            await update.message.reply_text(
                "Maaf, terjadi kesalahan saat memeriksa status pembayaran. Silakan coba lagi nanti."
            )
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
                f"✅ Pembayaran sukses!\nKlik link berikut untuk gabung grup:\n\n{invite_link.invite_link}\n\n"
                f"Link ini hanya untukmu dan akan kedaluwarsa bersamaan dengan langgananmu."
            )
        else:
            await update.message.reply_text("⚠️ Pembayaran belum diterima. Silakan coba lagi nanti.")
            return

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menangani klik tombol inline."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user = update.effective_user

    if data.startswith("verify_"):
        transaction_id = data.split("_")[1]
        data = subs_collection.find_one({"user_id": user.id})

        if not data or data['transaction_id'] != transaction_id:
            await query.edit_message_text("Transaksi tidak valid atau sudah kadaluwarsa.")
            return

        await query.edit_message_caption(caption="Mengecek status pembayaran Anda...")

        is_paid = check_paid_status(data["transaction_id"])

        if is_paid:
            expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=DURATION_DAYS)

            invite_link = await context.bot.create_chat_invite_link(
                chat_id=GROUP_ID,
                member_limit=1,
                expire_date=expires_at
            )

            subs_collection.update_one(
                {"user_id": user.id},
                {"$set": {"status": "active", "expires_at": expires_at, "invite_link": invite_link.invite_link}}
            )
            await query.edit_message_caption(
                f"✅ Pembayaran sukses!\nKlik link berikut untuk gabung grup:\n\n{invite_link.invite_link}"
            )
        else:
            await query.edit_message_caption("⚠️ Pembayaran belum diterima. Silakan coba lagi nanti.")
    elif data == "cancel":
        await query.edit_message_caption(
            "Pembayaran dibatalkan. Jika Anda ingin berlangganan, ketik /subscribe lagi."
        )

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("subscribe", subscribe))
application.add_handler(CommandHandler("status", status))
application.add_handler(CallbackQueryHandler(handle_callback))

# ---------------- BACKGROUND TASKS ----------------

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
            subs_collection.update_one({"user_id": user["user_id"]}, {"$set": {"status": "expired"}})
            logger.info(f"User {user['username']} dikeluarkan karena langganan habis.")
        except Exception as e:
            logger.error(f"Gagal kick user {user['user_id']}: {e}")

# ---------------- FLASK ROUTES ----------------

@app.route("/")
def index():
    """Endpoint untuk memeriksa apakah server berjalan."""
    return jsonify({"message": "Bot is running! by @MzCoder"})

@app.route("/webhook", methods=["POST"])
async def telegram_webhook_handler():
    """Handler untuk menerima update dari Telegram."""
    update = Update.de_json(request.get_json(force=True), application.bot)
    await application.process_update(update)
    return "ok"

# ---------------- MAIN ----------------

async def run_bot_async():
    """Fungsi asinkron untuk menyiapkan bot dan scheduler."""
    await application.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook telah diatur ke: {WEBHOOK_URL}")
    scheduler.add_job(check_expired_users, 'interval', hours=12)
    scheduler.start()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run_bot_async())
        app.run(host='0.0.0.0', port=PORT, debug=True)
    except Exception as e:
        logger.error(f"Terjadi kesalahan fatal: {e}")
        loop.close()
