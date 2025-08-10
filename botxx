import os
import logging
from datetime import datetime, timedelta
from threading import Thread
from io import BytesIO
from flask import Flask, jsonify

from telegram import Update, Chat, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Updater, 
    CommandHandler, 
    CallbackQueryHandler, 
    CallbackContext,
    MessageHandler,
    Filters
)
from pymongo import MongoClient
from bson.objectid import ObjectId
from qris_saweria import create_payment_qr, check_paid_status

# Flask App
app = Flask(__name__)

# Konfigurasi
TOKEN = "8156404642:AAGUomSAOmFXyoj2Ndka1saAA_t0KjC2H9Q"
ADMIN_IDS = [1910497806]  # Ganti dengan ID admin Anda
GROUP_ID = -1002703061780  # Ganti dengan ID grup/channel Anda
CHANNEL_ID = -1002703061780  # Ganti dengan ID channel Anda (jika berbeda)
SAWERIA_NAME = "anonbuilder"
MONGO_URI = "mongodb+srv://gpro:gpro@tebak9ambar.dioht2p.mongodb.net/?retryWrites=true&w=majority"
MONGO_DB_NAME = 'telegram_membership_bot'
PORT = "8000"

# Durasi langganan (dalam hari)
SUBSCRIPTION_PLANS = {
    'monthly': {'duration': 30, 'price': 50000},
    'yearly': {'duration': 365, 'price': 500000},
    '3months': {'duration': 90, 'price': 120000},
}

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Koneksi MongoDB
client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
users_collection = db['users']
payments_collection = db['payments']
settings_collection = db['settings']

# Inisialisasi database
def initialize_db():
    if settings_collection.count_documents({}) == 0:
        settings_collection.insert_one({
            'name': 'initial_setup',
            'created_at': datetime.now(),
            'payment_methods': ['qris'],
            'webhook_secret': os.urandom(24).hex()
        })
    
    # Buat index
    users_collection.create_index([('user_id', 1)], unique=True)
    users_collection.create_index([('expiry_date', 1)])
    payments_collection.create_index([('user_id', 1)])
    payments_collection.create_index([('status', 1)])
    payments_collection.create_index([('transaction_id', 1)], unique=True)

initialize_db()

class Database:
    @staticmethod
    def get_user(user_id: int):
        return users_collection.find_one({'user_id': user_id})
    
    @staticmethod
    def create_or_update_user(user_data: dict):
        user_data['updated_at'] = datetime.now()
        users_collection.update_one(
            {'user_id': user_data['user_id']},
            {'$set': user_data},
            upsert=True
        )
    
    @staticmethod
    def delete_user(user_id: int):
        users_collection.delete_one({'user_id': user_id})
    
    @staticmethod
    def get_all_active_users():
        return list(users_collection.find({'expiry_date': {'$gt': datetime.now()}}))
    
    @staticmethod
    def get_expiring_users(days_before: int = 3):
        now = datetime.now()
        threshold = now + timedelta(days=days_before)
        return list(users_collection.find({
            'expiry_date': {
                '$gt': now,
                '$lte': threshold
            }
        }))
    
    @staticmethod
    def get_expired_users():
        return list(users_collection.find({'expiry_date': {'$lte': datetime.now()}}))
    
    @staticmethod
    def create_payment(payment_data: dict):
        payment_data['created_at'] = datetime.now()
        payment_data['updated_at'] = datetime.now()
        return payments_collection.insert_one(payment_data).inserted_id
    
    @staticmethod
    def get_payment(payment_id: str):
        try:
            return payments_collection.find_one({'_id': ObjectId(payment_id)})
        except:
            return None
    
    @staticmethod
    def get_payment_by_transaction_id(transaction_id: str):
        return payments_collection.find_one({'transaction_id': transaction_id})
    
    @staticmethod
    def update_payment(payment_id: str, update_data: dict):
        update_data['updated_at'] = datetime.now()
        payments_collection.update_one(
            {'_id': ObjectId(payment_id)},
            {'$set': update_data}
        )

# Telegram Bot Functions
def start(update: Update, context: CallbackContext) -> None:
    """Handler untuk command /start"""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == Chat.PRIVATE:
        keyboard = [
            [InlineKeyboardButton(f"Bulanan (Rp {SUBSCRIPTION_PLANS['monthly']['price']:,})", 
                                 callback_data='subscribe_monthly')],
            [InlineKeyboardButton(f"3 Bulan (Rp {SUBSCRIPTION_PLANS['3months']['price']:,})", 
                                 callback_data='subscribe_3months')],
            [InlineKeyboardButton(f"Tahunan (Rp {SUBSCRIPTION_PLANS['yearly']['price']:,})", 
                                 callback_data='subscribe_yearly')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            f"Halo {user.first_name}!\n\n"
            "Pilih paket langganan Anda:",
            reply_markup=reply_markup
        )

def button(update: Update, context: CallbackContext) -> None:
    """Handler untuk tombol inline"""
    query = update.callback_query
    query.answer()
    
    user = query.from_user
    data = query.data
    
    if data.startswith('subscribe_'):
        plan = data.split('_')[1]
        plan_data = SUBSCRIPTION_PLANS.get(plan)
        
        if not plan_data:
            query.edit_message_text("Paket tidak valid. Silakan coba lagi.")
            return
        
        # Simpan data pembayaran ke MongoDB
        payment_data = {
            'user_id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'plan': plan,
            'duration': plan_data['duration'],
            'price': plan_data['price'],
            'status': 'pending',
            'payment_method': 'qris',
            'transaction_id': None,
            'qr_path': None
        }
        
        payment_id = Database.create_payment(payment_data)
        
        # Generate QRIS Payment
        try:
            qr_string, transaction_id, qr_path = create_payment_qr(
                SAWERIA_NAME,
                plan_data['price'],
                f"{user.id}@membership.com",
                f"qris_{user.id}_{payment_id}.png",
                True
            )
            
            # Update payment data with transaction info
            Database.update_payment(payment_id, {
                'transaction_id': transaction_id,
                'qr_path': qr_path,
                'qr_string': qr_string
            })
            
            # Kirim QRIS ke user
            with open(qr_path, 'rb') as qr_file:
                context.bot.send_photo(
                    chat_id=user.id,
                    photo=qr_file,
                    caption=f"📌 QRIS Pembayaran\n\n"
                           f"Paket: {plan.capitalize()}\n"
                           f"Durasi: {plan_data['duration']} hari\n"
                           f"Harga: Rp {plan_data['price']:,}\n\n"
                           "Silakan scan QR code di atas untuk melakukan pembayaran.\n"
                           "Setelah pembayaran, klik tombol di bawah untuk verifikasi.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Saya Sudah Bayar", callback_data=f'check_payment_{payment_id}')]
                    ])
                )
            
        except Exception as e:
            logger.error(f"Gagal membuat QRIS: {e}")
            query.edit_message_text("Maaf, terjadi kesalahan saat membuat QRIS pembayaran. Silakan coba lagi nanti.")
    
    elif data.startswith('check_payment_'):
        payment_id = data.split('_')[2]
        payment_data = Database.get_payment(payment_id)
        
        if not payment_data:
            query.edit_message_text("Pembayaran tidak ditemukan.")
            return
            
        if payment_data['status'] == 'paid':
            query.edit_message_text("✅ Pembayaran sudah dikonfirmasi. Terima kasih!")
            return
            
        # Cek status pembayaran di Saweria
        try:
            is_paid = check_paid_status(payment_data['transaction_id'])
            
            if is_paid:
                # Update status pembayaran
                Database.update_payment(payment_id, {
                    'status': 'paid',
                    'paid_at': datetime.now()
                })
                
                # Aktifkan membership
                activate_membership(user.id, payment_data, context)
                
                query.edit_message_text("✅ Pembayaran berhasil! Membership Anda telah aktif.")
            else:
                query.edit_message_text("❌ Pembayaran belum diterima. Silakan lakukan pembayaran terlebih dahulu.")
        except Exception as e:
            logger.error(f"Gagal memeriksa pembayaran: {e}")
            query.edit_message_text("❌ Gagal memeriksa status pembayaran. Silakan coba lagi nanti.")

def activate_membership(user_id: int, payment_data: dict, context: CallbackContext):
    """Aktivasi membership setelah pembayaran berhasil"""
    expiry_date = datetime.now() + timedelta(days=payment_data['duration'])
    
    # Simpan data user
    user_data = {
        'user_id': user_id,
        'username': payment_data.get('username'),
        'first_name': payment_data.get('first_name'),
        'last_name': payment_data.get('last_name'),
        'plan': payment_data['plan'],
        'duration': payment_data['duration'],
        'joined_at': datetime.now(),
        'expiry_date': expiry_date,
        'payment_history': [{
            'payment_id': str(payment_data['_id']),
            'amount': payment_data['price'],
            'date': datetime.now(),
            'method': 'qris'
        }]
    }
    Database.create_or_update_user(user_data)
    
    try:
        # Kirim notifikasi ke user
        context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 Pembayaran berhasil! Anda sekarang member premium hingga {expiry_date.strftime('%d %B %Y')}.\n\n"
                 f"Terima kasih telah bergabung!"
        )
        
        # Invite ke grup
        context.bot.send_message(
            chat_id=GROUP_ID,
            text=f"Selamat datang {payment_data['first_name']} (@{payment_data.get('username', 'N/A')})! "
                 f"Masa aktif hingga {expiry_date.strftime('%d %B %Y')}"
        )
        
        # Invite ke channel
        context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"Member baru: {payment_data['first_name']} (@{payment_data.get('username', 'N/A')}) "
                 f"- Aktif hingga {expiry_date.strftime('%d %B %Y')}"
        )
    except Exception as e:
        logger.error(f"Gagal mengirim notifikasi ke user {user_id}: {e}")

def check_subscriptions(context: CallbackContext) -> None:
    """Job untuk mengecek masa aktif member dan mengirim reminder"""
    now = datetime.now()
    
    # Kirim reminder untuk member yang masa aktifnya hampir habis
    expiring_users = Database.get_expiring_users(3)
    for user in expiring_users:
        remaining_days = (user['expiry_date'] - now).days
        try:
            context.bot.send_message(
                chat_id=user['user_id'],
                text=f"⏳ Masa langganan Anda akan berakhir dalam {remaining_days} hari "
                     f"(hingga {user['expiry_date'].strftime('%d %B %Y')}).\n\n"
                     "Silakan perpanjang untuk tetap menjadi member dengan klik /start"
            )
        except Exception as e:
            logger.error(f"Gagal mengirim reminder ke user {user['user_id']}: {e}")
    
    # Proses member yang masa aktifnya sudah habis
    expired_users = Database.get_expired_users()
    for user in expired_users:
        try:
            # Kirim pesan ke user
            context.bot.send_message(
                chat_id=user['user_id'],
                text="❌ Masa langganan Anda telah berakhir. Anda akan dikeluarkan dari grup/channel.\n\n"
                     "Silakan perpanjang membership dengan klik /start"
            )
            
            # Kick dari grup
            context.bot.kick_chat_member(
                chat_id=GROUP_ID,
                user_id=user['user_id']
            )
            
            # Hapus dari channel
            context.bot.kick_chat_member(
                chat_id=CHANNEL_ID,
                user_id=user['user_id']
            )
            
            # Hapus dari database
            Database.delete_user(user['user_id'])
            
        except Exception as e:
            logger.error(f"Gagal mengeluarkan user {user['user_id']}: {e}")

def admin_check_members(update: Update, context: CallbackContext) -> None:
    """Command admin untuk mengecek semua member"""
    if update.effective_user.id not in ADMIN_IDS:
        update.message.reply_text("Anda tidak memiliki akses ke command ini.")
        return
    
    now = datetime.now()
    active_users = Database.get_all_active_users()
    expiring_users = Database.get_expiring_users(30)
    expired_users = Database.get_expired_users()
    
    message = [
        "📊 Laporan Member:",
        f"✅ Aktif: {len(active_users)}",
        f"⚠️ Akan Expired (30 hari): {len(expiring_users)}",
        f"❌ Expired: {len(expired_users)}"
    ]
    
    update.message.reply_text("\n".join(message))

def error_handler(update: Update, context: CallbackContext) -> None:
    """Log errors"""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

# Flask Routes
@app.route('/')
def index():
    return jsonify({"message": "Bot is running! by @MzCoder", "status": "active"})

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

def main():
    """Start the bot and Flask server"""
    # Jalankan Flask di thread terpisah
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Setup Telegram Bot
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Command handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("members", admin_check_members))
    
    # Button handlers
    dp.add_handler(CallbackQueryHandler(button))
    
    # Error handler
    dp.add_error_handler(error_handler)
    
    # Job queue untuk pengecekan berkala
    job_queue = updater.job_queue
    job_queue.run_repeating(check_subscriptions, interval=86400, first=0)  # Cek setiap 24 jam
    
    # Start the Bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
