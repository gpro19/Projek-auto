from flask import Flask
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler, CallbackContext,
    MessageHandler, Filters, JobQueue
)

import threading
import logging
from telegram.error import NetworkError
import time
from typing import Dict, Any, List
import base64
import urllib.parse


# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
TOKEN = "8417409969:AAHeIjBE73bq2Ubf7uW4mUE_ZuHsSSYx83A"
# Game configuration
ALLOWED_GROUP_IDS = (-1001651683956, -1002334351077, -1002540626336)  # Tuple of allowed IDs

# Game state management
games: Dict[int, Dict[str, Any]] = {}

# Role definitions
ROLES = {
    "Koruptor": {
        "description": "🕵️ Koruptor - Tujuan Anda adalah menghindari penangkapan dan mengumpulkan kekayaan ilegal",
        "night_action": "memilih target untuk disuap atau diancam",
        "team": "koruptor",
        "priority": 1,
        "emoji": "🕵️"
    },
    "KPK": {
        "description": "👮 Penyidik KPK - Tujuan Anda adalah menangkap semua koruptor",
        "night_action": "menyidik satu pemain untuk mengetahui perannya",
        "team": "penegak_hukum",
        "priority": 2,
        "emoji": "👮"
    },
    "Jaksa": {
        "description": "⚖️ Jaksa - Tujuan Anda adalah mendakwa koruptor yang tertangkap",
        "night_action": "melindungi satu pemain dari penyidikan koruptor",
        "team": "penegak_hukum", 
        "priority": 3,
        "emoji": "⚖️"
    },
    "Polisi": {
        "description": "👮 Polisi - Tujuan Anda adalah menjaga keamanan dan membantu penegakan hukum",
        "night_action": "mengawasi satu pemain untuk melihat aktivitas mencurigakan",
        "team": "penegak_hukum",
        "priority": 4,
        "emoji": "👮‍♂️"
    },
    "Masyarakat": {
        "description": "👨 Masyarakat - Tujuan Anda adalah membantu membersihkan negara dari korupsi",
        "night_action": "tidak memiliki aksi malam",
        "team": "masyarakat",
        "priority": 5,
        "emoji": "👨"
    },
    "Whistleblower": {
        "description": "📢 Whistleblower - Tujuan Anda adalah membongkar kasus korupsi tanpa terdeteksi",
        "night_action": "mengungkap informasi tentang satu pemain",
        "team": "masyarakat",
        "priority": 6,
        "emoji": "📢"
    }
}

# Role distribution based on player count
ROLE_DISTRIBUTION = {
    5: {"Koruptor": 1, "KPK": 1, "Jaksa": 1, "Polisi": 1, "Masyarakat": 1},
    6: {"Koruptor": 2, "KPK": 1, "Jaksa": 1, "Polisi": 1, "Masyarakat": 1},
    7: {"Koruptor": 2, "KPK": 1, "Jaksa": 1, "Polisi": 1, "Masyarakat": 1, "Whistleblower": 1},
    8: {"Koruptor": 2, "KPK": 1, "Jaksa": 1, "Polisi": 1, "Masyarakat": 2, "Whistleblower": 1},
    9: {"Koruptor": 3, "KPK": 1, "Jaksa": 1, "Polisi": 1, "Masyarakat": 2, "Whistleblower": 1},
    10: {"Koruptor": 3, "KPK": 1, "Jaksa": 1, "Polisi": 1, "Masyarakat": 2, "Whistleblower": 2}
}


def encode_chat_id(combined_value: str) -> str:
    """Encode untuk URL yang aman"""
    encoded = base64.urlsafe_b64encode(combined_value.encode()).decode().rstrip("=")
    return encoded

def decode_chat_id(encoded: str) -> str:
    """Decode dari URL-safe base64"""
    padding = len(encoded) % 4
    if padding:
        encoded += "=" * (4 - padding)
    
    try:
        decoded = base64.urlsafe_b64decode(encoded.encode()).decode()
        if '_' not in decoded or len(decoded.split('_')) != 2:
            raise ValueError("Format decoded tidak valid")
        return decoded
    except Exception as e:
        logger.error(f"Decode error: {str(e)}")
        raise ValueError("Token tidak valid") from e

def cancel_all_jobs(chat_id: int, job_queue: JobQueue):
    """Batalkan semua job yang terkait dengan chat_id tertentu"""
    jobs = job_queue.get_jobs_by_name(str(chat_id))
    for job in jobs:
        job.schedule_removal()
        logger.info(f"Job {job.name} dibatalkan.")    

def get_game(chat_id: int) -> Dict[str, Any]:
    if chat_id not in games:
        games[chat_id] = {
            'pemain': [],
            'roles': {},
            'sedang_berlangsung': False,
            'fase': None,
            'malam_actions': {},
            'suara': {},
            'tertangka': [],
            'skor': {},
            'join_started': False,
            'pending_messages': [],
            'join_message_id': None,
            'jobs': [],
            'hari_ke': 0,
            'pemain_mati': [],
            'night_results': {},
            'vote_message_id': None
        }
    return games[chat_id]

def cleanup_jobs(context: CallbackContext, chat_id: int):
    """Membersihkan semua job untuk chat tertentu"""
    game = get_game(chat_id)
    
    if 'jobs' not in game:
        return
        
    for job_info in game['jobs']:
        try:
            for job in context.job_queue.get_jobs_by_name(job_info['id']):
                job.schedule_removal()
                logger.info(f"Job {job_info['id']} dihapus")
        except Exception as e:
            logger.error(f"Gagal hapus job {job_info['id']}: {e}")
    
    game['jobs'] = []

def reset_game(chat_id: int, context: CallbackContext = None):
    """Reset game state and cancel all jobs safely"""
    game = get_game(chat_id)
    
    try:
        if context and 'jobs' in game:
            for job_info in game['jobs']:
                try:
                    for job in context.job_queue.get_jobs_by_name(job_info['id']):
                        job.schedule_removal()
                        logger.info(f"Removed job: {job.name}")
                except Exception as e:
                    logger.error(f"Failed to remove job {job_info['id']}: {e}")

        for msg_id in game.get('pending_messages', []):
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.error(f"Failed to delete message {msg_id}: {e}")
                
    except Exception as e:
        logger.error(f"Error in reset_game: {e}")
    finally:
        if chat_id in games:
            del games[chat_id]

def safe_send_message(context, *args, **kwargs):
    """Safely send message with retry logic"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return context.bot.send_message(*args, **kwargs)
        except NetworkError as e:
            if attempt == max_retries - 1:
                raise
            sleep_time = (2 ** attempt) + random.random()
            time.sleep(sleep_time)

def join_time_up(context: CallbackContext):
    """Handler ketika waktu gabung habis"""
    chat_id = context.job.context['chat_id']
    game = get_game(chat_id)
    
    if not game['join_started']:
        return

    for msg_id in game['pending_messages']:
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.error(f"Gagal hapus pesan {msg_id}: {e}")

    game['pending_messages'] = []
    game['join_message_id'] = None
    game['join_started'] = False

    if len(game['pemain']) >= 5:
        context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Pendaftaran ditutup dengan {len(game['pemain'])} pemain!\n⏳ Memulai permainan...",
            parse_mode='Markdown'
        )
        
        start_job = context.job_queue.run_once(
            lambda ctx: auto_start_game(ctx),
            2,
            context={'chat_id': chat_id},
            name=f"game_start_{chat_id}"
        )
        game['jobs'].append(start_job)
    else:
        reset_game(chat_id)

def join_warning(context: CallbackContext):
    """Peringatan waktu gabung hampir habis"""
    chat_id = context.job.context['chat_id']
    game = get_game(chat_id)
    
    if not game['join_started']:
        return

    try:
        warning_msg = context.bot.send_message(
            chat_id=chat_id,
            text="*15* detik lagi untuk bergabung",
            parse_mode='Markdown'
        )
        game['pending_messages'].append(warning_msg.message_id)
    except Exception as e:
        logger.error(f"Gagal kirim peringatan: {e}")

def auto_start_game(context: CallbackContext):
    """Automatically start game after join timer ends"""
    try:
        chat_id = context.job.context['chat_id']
        game = get_game(chat_id)
        
        if len(game['pemain']) < 5:
            context.bot.send_message(
                chat_id=chat_id,
                text="❌ Gagal memulai - minimal 5 pemain diperlukan!",
                parse_mode='Markdown'
            )
            reset_game(chat_id)
            return

        class MockChat:
            def __init__(self, chat_id):
                self.id = chat_id
                self.type = 'group'

        class MockMessage:
            def __init__(self, chat_id):
                self.chat = MockChat(chat_id)
                self.chat_id = chat_id
                
            def reply_text(self, text, **kwargs):
                return context.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    **kwargs
                )

        fake_update = Update(
            update_id=0,
            message=MockMessage(chat_id)
        )

        mulai_permainan(fake_update, context)

    except Exception as e:
        logger.error(f"Error in auto_start_game: {e}")
        context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Gagal memulai permainan secara otomatis. Silakan coba /mulai manual."
        )
        reset_game(chat_id)

def start(update: Update, context: CallbackContext):
    if context.args and context.args[0].startswith('join_'):
        join_request(update, context)
        return
    
    user_name = update.effective_user.first_name or update.effective_user.full_name

    start_text = (
        f"Hai {user_name}! Saya host-bot Game Koruptor di grup Telegram. "
        "Tambahkan saya ke grup untuk mulai bermain game koruptor yang seru!"
    )

    keyboard = [
        [
            InlineKeyboardButton("Support Grup", url="https://t.me/DutabotSupport"),
            InlineKeyboardButton("Dev", url="https://t.me/MzCoder")
        ],
        [
            InlineKeyboardButton("Tambahkan ke Grup", 
                               url=f"https://t.me/{context.bot.username}?startgroup=true")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        text=start_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

def gabung(update: Update, context: CallbackContext):
    if update.effective_chat.type == 'private':
        update.message.reply_text("❌ Silakan gabung di grup yang sedang bermain!")
        return

    chat_id = update.effective_chat.id
    game = get_game(chat_id)

    if game['sedang_berlangsung']:
        update.message.reply_text("⚠️ Permainan sudah berjalan! Tunggu game selanjutnya.")
        return

    if not game['join_started']:
        game.update({
            'pemain': [],
            'pending_messages': [],
            'join_started': True,
            'jobs': []
        })

    timestamp = str(int(time.time()))
    chat_id_str = str(chat_id)
    combined = f"{timestamp}_{chat_id_str}"
    tokenku = encode_chat_id(combined)
    
    safe_token = urllib.parse.quote(tokenku)
    
    keyboard = [[InlineKeyboardButton(
        "🎮 Gabung Permainan", 
        url=f"https://t.me/{context.bot.username}?start=join_{safe_token}"
    )]]
    
    if not game.get('join_message_id'):
        msg = update.message.reply_text(
            f"🎮 *GAME KORUPTOR DI GRUP INI!*\n"
            "⏱️ Waktu bergabung: 50 detik\n"
            "👥 Pemain: 0/10\n\n"
            "Klick tombol di bawah untuk bergabung:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        game['join_message_id'] = msg.message_id
        game['pending_messages'].append(msg.message_id)
    else:
        try:
            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=game['join_message_id'],
                text=f"🎮 *GAME KORUPTOR DI GRUP INI!*\n"
                     "⏱️ Waktu bergabung: 50 detik\n"
                     f"👥 Pemain: {len(game['pemain'])}/10\n\n"
                     "Klick tombol di bawah untuk bergabung:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Gagal update pesan gabung: {e}")

    for job in game.get('jobs', []):
        job.schedule_removal()
    game['jobs'] = []

    timer_job = context.job_queue.run_once(
        join_time_up,
        50,
        context={'chat_id': chat_id},
        name=f"join_timer_{chat_id}"
    )
    game['jobs'].append(timer_job)

    warning_job = context.job_queue.run_once(
        join_warning,
        35,
        context={'chat_id': chat_id},
        name=f"join_warning_{chat_id}"
    )
    game['jobs'].append(warning_job)

    start_job = context.job_queue.run_once(
        auto_start_game,
        52,
        context={'chat_id': chat_id},
        name=f"game_start_{chat_id}"
    )
    game['jobs'].append(start_job)

def join_request(update: Update, context: CallbackContext):
    if update.effective_chat.type != 'private':
        update.message.reply_text("⚠️ Silakan klik tombol dari grup tempat permainan berlangsung!")
        return

    try:
        if not context.args or not context.args[0].startswith('join_'):
            raise ValueError("Format token tidak valid")
            
        encoded_token = context.args[0][5:]
        decoded_value = decode_chat_id(encoded_token)
        timestamp_str, chat_id_str = decoded_value.split('_')
        
        timestamp = int(timestamp_str)
        chat_id = int(chat_id_str)
  
        if abs(time.time() - timestamp) > 600:
            update.message.reply_text("⌛ Link bergabung sudah kadaluarsa!")
            return

    except Exception as e:
        logger.error(f"Invalid join token: {str(e)}")
        update.message.reply_text("❌ Link bergabung tidak valid!")
        return

    game = get_game(chat_id)
    
    if not game.get('join_started', False):
        update.message.reply_text("⌛ Waktu bergabung sudah habis!")
        return

    if game['sedang_berlangsung']:
        update.message.reply_text("⚠️ Permainan sudah berjalan!")
        return

    user = update.effective_user
    user_id = user.id
    username = user.first_name

    if any(p['id'] == user_id for p in game['pemain']):
        update.message.reply_text("😊 Kamu sudah terdaftar!")
        return

    if len(game['pemain']) >= 10:
        update.message.reply_text("😞 Pemain sudah penuh (10/10)!")
        return

    game['pemain'].append({'id': user_id, 'nama': username})
    
    chat = context.bot.get_chat(chat_id)
    group_name = chat.title if chat.title else "grup ini"
        
    update.message.reply_text(
        f"Kamu berhasil bergabung di *{group_name}*\n"
        f"Sekarang ada *{len(game['pemain'])}/10 pemain.*",
        parse_mode='Markdown'
    )
    
    try:
        notify_msg = context.bot.send_message(
            chat_id=chat_id,
            text=f"[{username}](tg://user?id={user_id}) bergabung ke game",
            parse_mode='Markdown'
        )
        game['pending_messages'].append(notify_msg.message_id)
    except Exception as e:
        logger.error(f"Gagal kirim notifikasi grup: {e}")
        
    try:
        context.bot.edit_message_text(
            chat_id=str(chat_id),
            message_id=game['join_message_id'],
            text=f"🎮 *GAME KORUPTOR DI GRUP INI!*\n"
                 "⏱️ Waktu bergabung: 50 detik\n"
                 f"👥 Pemain: {len(game['pemain'])}/10\n\n"
                 "Klick tombol di bawah untuk bergabung:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🎮 Gabung Sekarang",
                    url=f"https://t.me/{context.bot.username}?start=join_{int(time.time())}_{encode_chat_id(chat_id)}"
                )
            ]]),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Gagal update pesan gabung: {e}")

    try:      
        if len(game['pemain']) == 10:
            cancel_all_jobs(chat_id, context.job_queue)
            mulai_permainan(update, context)
    except Exception as e:
        logger.error(f"Gagal mulai Game: {e}")

def distribusi_peran(jumlah_pemain: int) -> Dict[str, int]:
    """Distribusikan peran berdasarkan jumlah pemain"""
    if jumlah_pemain < 5:
        return {"Koruptor": 1, "KPK": 1, "Jaksa": 1, "Polisi": 1, "Masyarakat": 1}
    elif jumlah_pemain > 10:
        return {"Koruptor": 3, "KPK": 2, "Jaksa": 1, "Polisi": 1, "Masyarakat": jumlah_pemain - 7, "Whistleblower": 1}
    else:
        return ROLE_DISTRIBUTION[jumlah_pemain]

def mulai_permainan(update: Update, context: CallbackContext):
    if update.effective_chat.type == 'private':
        update.message.reply_text("❌ Hanya bisa dilakukan di grup!")
        return

    chat_id = update.effective_chat.id
    game = get_game(chat_id)

    cancel_all_jobs(chat_id, context.job_queue)
    
    if game['sedang_berlangsung']:
        return

    jumlah_pemain = len(game['pemain'])
    
    if jumlah_pemain < 5:
        update.message.reply_text(
            "❌ Minimal 5 pemain untuk memulai!\n"
            f"Pemain saat ini: {jumlah_pemain}/5"
        )
        return
    
    game.update({
        'roles': {},
        'sedang_berlangsung': True,
        'fase': 'malam',
        'malam_actions': {},
        'suara': {},
        'tertangka': [],
        'skor': {},
        'hari_ke': 1,
        'pemain_mati': [],
        'night_results': {},
        'vote_message_id': None
    })

    # Distribusi peran
    distribusi = distribusi_peran(jumlah_pemain)
    semua_peran = []
    
    for peran, jumlah in distribusi.items():
        semua_peran.extend([peran] * jumlah)
    
    random.shuffle(semua_peran)
    
    # Berikan peran ke pemain
    for i, pemain in enumerate(game['pemain']):
        peran = semua_peran[i]
        game['roles'][pemain['id']] = peran
        
        # Kirim peran ke pemain
        try:
            context.bot.send_message(
                chat_id=pemain['id'],
                text=f"🎭 *PERAN ANDA DALAM GAME KORUPTOR*\n\n"
                     f"{ROLES[peran]['description']}\n\n"
                     f"*Aksi Malam:* {ROLES[peran]['night_action']}\n\n"
                     "Jaga kerahasiaan peran Anda!",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Gagal kirim pesan ke {pemain['nama']}: {e}")
            update.message.reply_text(
                f"❌ Tidak bisa mengirim pesan ke {pemain['nama']}. "
                "Pastikan sudah memulai chat dengan bot!"
            )
            reset_game(chat_id)
            return

    # Mulai malam pertama
    mulai_malam(context, chat_id)

def mulai_malam(context: CallbackContext, chat_id: int):
    """Memulai fase malam"""
    game = get_game(chat_id)
    game['fase'] = 'malam'
    game['malam_actions'] = {}
    game['night_results'] = {}
    
    # Kirim pesan ke grup dengan format yang lebih mirip game Mafia
    malam_text = f"🌃 *Malam yang mengerikan!*\n\n"
    malam_text += "Hanya yang paling berani dan tak kenal takut yang turun ke jalan. "
    malam_text += "Kami akan mencoba menghitung yang jatuh di pagi hari...\n\n"
    
    # Daftar pemain hidup
    malam_text += "*Pemain hidup:*\n"
    for i, pemain in enumerate(game['pemain']):
        if pemain['id'] not in game['pemain_mati']:
            malam_text += f"{i+1}. {pemain['nama']}\n"
    
    malam_text += f"\n1 menit tersisa untuk tidur"
    
    context.bot.send_message(
        chat_id=chat_id,
        text=malam_text,
        parse_mode='Markdown'
    )
    
    # Beri waktu untuk aksi malam
    for pemain in game['pemain']:
        if pemain['id'] in game['pemain_mati']:
            continue
            
        peran = game['roles'][pemain['id']]
        
        if peran in ["Koruptor", "KPK", "Jaksa", "Polisi", "Whistleblower"]:
            try:
                if peran == "Koruptor":
                    # Koruptor bisa memilih target untuk disuap
                    keyboard = []
                    for target in game['pemain']:
                        if target['id'] != pemain['id'] and target['id'] not in game['pemain_mati']:
                            keyboard.append([InlineKeyboardButton(
                                target['nama'], 
                                callback_data=f"night_koruptor_{target['id']}"
                            )])
                    
                    context.bot.send_message(
                        chat_id=pemain['id'],
                        text="🌙 *Aksi Malam - Koruptor*\n\n"
                             "Pilih target untuk disuap atau ancam:\n"
                             "Target yang disuap tidak bisa divoting besok.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                    # Kirim pesan ke grup
                    context.bot.send_message(
                        chat_id=chat_id,
                        text="🕵️ Koruptor sedang memilih korbannya...",
                        parse_mode='Markdown'
                    )
                
                elif peran == "KPK":
                    # KPK bisa menyelidiki peran pemain
                    keyboard = []
                    for target in game['pemain']:
                        if target['id'] != pemain['id'] and target['id'] not in game['pemain_mati']:
                            keyboard.append([InlineKeyboardButton(
                                target['nama'], 
                                callback_data=f"night_kpk_{target['id']}"
                            )])
                    
                    context.bot.send_message(
                        chat_id=pemain['id'],
                        text="🌙 *Aksi Malam - KPK*\n\n"
                             "Pilih target untuk diselidiki:\n"
                             "Anda akan mengetahui peran target.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                    # Kirim pesan ke grup
                    context.bot.send_message(
                        chat_id=chat_id,
                        text="👮 KPK sedang mencari koruptor...",
                        parse_mode='Markdown'
                    )
                
                elif peran == "Jaksa":
                    # Jaksa bisa melindungi pemain
                    keyboard = []
                    for target in game['pemain']:
                        if target['id'] not in game['pemain_mati']:
                            keyboard.append([InlineKeyboardButton(
                                target['nama'], 
                                callback_data=f"night_jaksa_{target['id']}"
                            )])
                    
                    context.bot.send_message(
                        chat_id=pemain['id'],
                        text="🌙 *Aksi Malam - Jaksa*\n\n"
                             "Pilih target untuk dilindungi:\n"
                             "Target tidak bisa diselidiki malam ini.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                    # Kirim pesan ke grup
                    context.bot.send_message(
                        chat_id=chat_id,
                        text="⚖️ Jaksa sedang bertugas malam...",
                        parse_mode='Markdown'
                    )
                
                elif peran == "Polisi":
                    # Polisi bisa mengawasi pemain
                    keyboard = []
                    for target in game['pemain']:
                        if target['id'] != pemain['id'] and target['id'] not in game['pemain_mati']:
                            keyboard.append([InlineKeyboardButton(
                                target['nama'], 
                                callback_data=f"night_polisi_{target['id']}"
                            )])
                    
                    context.bot.send_message(
                        chat_id=pemain['id'],
                        text="🌙 *Aksi Malam - Polisi*\n\n"
                             "Pilih target untuk diawasi:\n"
                             "Anda akan melihat jika target melakukan aksi mencurigakan.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                    # Kirim pesan ke grup
                    context.bot.send_message(
                        chat_id=chat_id,
                        text="👮‍♂️ Polisi sedang mengawasi...",
                        parse_mode='Markdown'
                    )
                
                elif peran == "Whistleblower":
                    # Whistleblower bisa mengungkap informasi
                    keyboard = []
                    for target in game['pemain']:
                        if target['id'] != pemain['id'] and target['id'] not in game['pemain_mati']:
                            keyboard.append([InlineKeyboardButton(
                                target['nama'], 
                                callback_data=f"night_whistleblower_{target['id']}"
                            )])
                    
                    context.bot.send_message(
                        chat_id=pemain['id'],
                        text="🌙 *Aksi Malam - Whistleblower*\n\n"
                             "Pilih target untuk diungkap informasinya:\n"
                             "Anda akan mengetahui tim target (koruptor/penegak hukum/masyarakat).",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                    # Kirim pesan ke grup
                    context.bot.send_message(
                        chat_id=chat_id,
                        text="📢 Whistleblower sedang mencari informasi...",
                        parse_mode='Markdown'
                    )
                
            except Exception as e:
                logger.error(f"Gagal kirim aksi malam ke {pemain['nama']}: {e}")
    
    # Timer aksi malam
    context.job_queue.run_once(
        lambda ctx: akhir_malam(ctx, chat_id),
        120,
        context=chat_id,
        name=f"malam_{chat_id}"
    )

def handle_night_action(update: Update, context: CallbackContext):
    """Handle aksi malam dari pemain"""
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    data_parts = query.data.split('_')
    
    if len(data_parts) < 3:
        logger.error(f"Data callback tidak valid: {query.data}")
        return
    
    action_type = data_parts[1]
    target_id = int(data_parts[2])
    
    # Dapatkan chat_id dari context atau cari di semua game
    chat_id = None
    for cid, game in games.items():
        if any(p['id'] == user_id for p in game['pemain']):
            chat_id = cid
            break
    
    if not chat_id:
        query.edit_message_text("❌ Game tidak ditemukan!")
        return
        
    game = get_game(chat_id)
    
    if game['fase'] != 'malam':
        query.edit_message_text("❌ Waktu aksi malam sudah habis!")
        return
    
    # Simpan aksi pemain
    game['malam_actions'][user_id] = {
        'type': action_type,
        'target_id': target_id,
        'waktu': time.time()
    }
    
    # Konfirmasi ke pemain
    target_nama = next((p['nama'] for p in game['pemain'] if p['id'] == target_id), "Unknown")
    query.edit_message_text(f"✅ Aksi {action_type} terhadap {target_nama} tercatat!")
    
    # Log aksi
    logger.info(f"Pemain {user_id} melakukan aksi {action_type} pada {target_id}")

def akhir_malam(context: CallbackContext, chat_id: int):
    """Proses hasil aksi malam"""
    game = get_game(chat_id)
    
    if game['fase'] != 'malam':
        logger.info(f"Fase bukan malam di akhir_malam: {game['fase']}")
        return
    
    # Beri tahu pemain yang belum melakukan aksi
    for pemain in game['pemain']:
        if (pemain['id'] not in game['pemain_mati'] and 
            pemain['id'] not in game['malam_actions'] and
            game['roles'][pemain['id']] in ["Koruptor", "KPK", "Jaksa", "Polisi", "Whistleblower"]):
            try:
                context.bot.send_message(
                    chat_id=pemain['id'],
                    text="❌ Anda tidak melakukan aksi malam ini!",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Gagal kirim notifikasi ke {pemain['nama']}: {e}")
    
    # Proses semua aksi malam berdasarkan priority
    actions_by_priority = []
    
    for user_id, action in game['malam_actions'].items():
        peran = game['roles'][user_id]
        priority = ROLES[peran]['priority']
        actions_by_priority.append((priority, user_id, action))
    
    # Urutkan berdasarkan priority
    actions_by_priority.sort(key=lambda x: x[0])
    
    # Proses aksi
    for priority, user_id, action in actions_by_priority:
        peran = game['roles'][user_id]
        target_id = action['target_id']
        
        # Cek jika target masih hidup
        if target_id in game['pemain_mati']:
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text="❌ Target aksi sudah mati!",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Gagal kirim notifikasi target mati: {e}")
            continue
            
        # Proses berdasarkan jenis aksi
        if peran == "KPK":
            # KPK menyelidiki peran target
            target_peran = game['roles'][target_id]
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text=f"🔍 Hasil penyelidikan: {target_peran}",
                    parse_mode='Markdown'
                )
                game['night_results'][user_id] = f"Hasil penyelidikan: {target_peran}"
            except Exception as e:
                logger.error(f"Gagal kirim hasil penyelidikan: {e}")
        
        elif peran == "Jaksa":
            # Jaksa melindungi target dari penyelidikan
            game['night_results'][target_id] = "Dilindungi oleh Jaksa"
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text="✅ Perlindungan berhasil diberikan!",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Gagal kirim konfirmasi jaksa: {e}")
        
        elif peran == "Polisi":
            # Polisi mengawasi target
            if target_id in game['malam_actions']:
                target_action = game['malam_actions'][target_id]
                if target_action['type'] in ['koruptor', 'whistleblower']:
                    try:
                        context.bot.send_message(
                            chat_id=user_id,
                            text="👮 Target melakukan aksi mencurigakan!",
                            parse_mode='Markdown'
                        )
                        game['night_results'][user_id] = "Target melakukan aksi mencurigakan"
                    except Exception as e:
                        logger.error(f"Gagal kirim hasil pengawasan: {e}")
                else:
                    try:
                        context.bot.send_message(
                            chat_id=user_id,
                            text="👮 Target tidak melakukan aksi mencurigakan.",
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"Gagal kirim hasil pengawasan: {e}")
        
        elif peran == "Whistleblower":
            # Whistleblower mengungkap tim target
            target_peran = game['roles'][target_id]
            target_team = ROLES[target_peran]['team']
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text=f"📢 Target berada di tim: {target_team}",
                    parse_mode='Markdown'
                )
                game['night_results'][user_id] = f"Target di tim: {target_team}"
            except Exception as e:
                logger.error(f"Gagal kirim hasil ungkap: {e}")
        
        elif peran == "Koruptor":
            # Koruptor menyuap target
            game['night_results'][target_id] = "Disuap oleh Koruptor (tidak bisa divoting besok)"
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text="✅ Suapan berhasil diberikan!",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Gagal kirim konfirmasi koruptor: {e}")
    
    # Mulai fase siang
    mulai_siang(context, chat_id)

def mulai_siang(context: CallbackContext, chat_id: int):
    """Memulai fase siang"""
    game = get_game(chat_id)
    game['fase'] = 'siang'
    
    # Kirim hasil malam ke grup dengan format yang lebih mirip game Mafia
    hasil_text = f"🏙 *Hari {game['hari_ke']}*\n\n"
    hasil_text += "Matahari terbit dan mengungkap kejahatan yang terjadi tadi malam...\n\n"
    
    # Cek jika ada yang disuap koruptor
    korban_suapan = []
    for target_id, result in game['night_results'].items():
        if "Disuap oleh Koruptor" in result:
            target_nama = next((p['nama'] for p in game['pemain'] if p['id'] == target_id), "Unknown")
            korban_suapan.append(target_nama)
    
    if korban_suapan:
        hasil_text += f"⚠️ {', '.join(korban_suapan)} disuap koruptor dan tidak bisa divoting hari ini!\n\n"
    
    hasil_text += "Diskusikan dan pilih siapa yang akan ditangkap!"
    
    context.bot.send_message(
        chat_id=chat_id,
        text=hasil_text,
        parse_mode='Markdown'
    )
    
    # Buat tombol voting dengan format yang lebih baik
    keyboard = []
    vote_targets = []
    
    for pemain in game['pemain']:
        if (pemain['id'] not in game['pemain_mati'] and 
            not (pemain['id'] in game['night_results'] and 
                 "Disuap oleh Koruptor" in game['night_results'][pemain['id']])):
            vote_targets.append(pemain)
    
    # Kelompokkan tombol dalam baris 2 kolom
    for i in range(0, len(vote_targets), 2):
        row = []
        if i < len(vote_targets):
            row.append(InlineKeyboardButton(
                f"{vote_targets[i]['nama']} (0)", 
                callback_data=f"vote_{vote_targets[i]['id']}"
            ))
        if i + 1 < len(vvote_targets):
            row.append(InlineKeyboardButton(
                f"{vote_targets[i+1]['nama']} (0)", 
                callback_data=f"vote_{vote_targets[i+1]['id']}"
            ))
        if row:
            keyboard.append(row)
    
    if keyboard:  # Hanya jika ada yang bisa divoting
        vote_msg = context.bot.send_message(
            chat_id=chat_id,
            text="🗳️ *Pemungutan Suara*\nPilih siapa yang akan ditangkap:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        game['vote_message_id'] = vote_msg.message_id
        
        # Timer voting (45 detik seperti contoh Mafia)
        context.job_queue.run_once(
            lambda ctx: akhir_voting(ctx, chat_id),
            45,
            context=chat_id,
            name=f"voting_{chat_id}"
        )
        
        # Peringatan waktu voting hampir habis
        context.job_queue.run_once(
            lambda ctx: voting_warning(ctx, chat_id),
            30,
            context=chat_id,
            name=f"voting_warning_{chat_id}"
        )
    else:
        # Tidak ada yang bisa divoting, lanjut ke malam berikutnya
        context.bot.send_message(
            chat_id=chat_id,
            text="❌ Tidak ada yang bisa divoting hari ini! Lanjut ke malam berikutnya...",
            parse_mode='Markdown'
        )
        game['hari_ke'] += 1
        mulai_malam(context, chat_id)

def voting_warning(context: CallbackContext, chat_id: int):
    """Peringatan waktu voting hampir habis"""
    game = get_game(chat_id)
    
    if game['fase'] != 'siang':
        return
        
    try:
        context.bot.send_message(
            chat_id=chat_id,
            text="⏰ 15 detik lagi untuk voting!",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Gagal kirim peringatan voting: {e}")

def handle_vote(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        voter_id = query.from_user.id
        chat_id = query.message.chat.id
        game = get_game(chat_id)
        
        # Cek apakah pemain masih hidup dan boleh voting
        if voter_id in game['pemain_mati']:
            query.answer("❌ Kamu sudah mati dan tidak bisa voting!", show_alert=True)
            return
            
        if game['fase'] != 'siang':
            query.answer("❌ Bukan waktu voting!", show_alert=True)
            return

        # Parse data callback
        _, target_id_str = query.data.split('_')
        target_id = int(target_id_str)
        
        # Cek apakah target masih hidup dan bisa divoting
        if target_id in game['pemain_mati']:
            query.answer("❌ Target sudah mati!", show_alert=True)
            return
            
        # Cek apakah target disuap koruptor
        if target_id in game['night_results'] and "Disuap oleh Koruptor" in game['night_results'][target_id]:
            query.answer("❌ Target tidak bisa divoting karena disuap koruptor!", show_alert=True)
            return

        # Simpan vote
        game['suara'][voter_id] = target_id
        
        # Update tombol voting dengan jumlah suara terbaru
        vote_count = {}
        for voter, voted_id in game['suara'].items():
            if voted_id not in vote_count:
                vote_count[voted_id] = 0
            vote_count[voted_id] += 1
        
        # Buat keyboard baru dengan jumlah suara terbaru
        keyboard = []
        vote_targets = []
        
        for pemain in game['pemain']:
            if (pemain['id'] not in game['pemain_mati'] and 
                not (pemain['id'] in game['night_results'] and 
                     "Disuap oleh Koruptor" in game['night_results'][pemain['id']])):
                vote_targets.append(pemain)
        
        # Kelompokkan tombol dalam baris 2 kolom
        for i in range(0, len(vote_targets), 2):
            row = []
            if i < len(vote_targets):
                count = vote_count.get(vote_targets[i]['id'], 0)
                row.append(InlineKeyboardButton(
                    f"{vote_targets[i]['nama']} ({count})", 
                    callback_data=f"vote_{vote_targets[i]['id']}"
                ))
            if i + 1 < len(vote_targets):
                count = vote_count.get(vote_targets[i+1]['id'], 0)
                row.append(InlineKeyboardButton(
                    f"{vote_targets[i+1]['nama']} ({count})", 
                    callback_data=f"vote_{vote_targets[i+1]['id']}"
                ))
            if row:
                keyboard.append(row)
        
        try:
            query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            target_nama = next(p['nama'] for p in game['pemain'] if p['id'] == target_id)
            query.answer(f"✅ Kamu memilih {target_nama}!")
        except Exception as e:
            logger.error(f"Error updating buttons: {e}")
            query.answer("❌ Gagal memperbarui pilihan.", show_alert=True)

    except Exception as e:
        logger.error(f"Error in handle_vote: {e}")
        try:
            query.answer("❌ Terjadi kesalahan saat voting!", show_alert=True)
        except:
            pass

def akhir_voting(context: CallbackContext, chat_id):
    """Proses akhir voting dan tentukan hasil"""
    try:
        game = get_game(chat_id)
        
        if game['fase'] != 'siang':
            return

        # Hapus pesan voting
        if game.get('vote_message_id'):
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=game['vote_message_id'])
            except Exception as e:
                logger.error(f"Gagal hapus pesan voting: {e}")

        # Hitung hasil voting
        vote_count = {}
        for voter_id, target_id in game['suara'].items():
            if target_id not in vote_count:
                vote_count[target_id] = 0
            vote_count[target_id] += 1

        # Cari yang paling banyak divoting
        if vote_count:
            max_votes = max(vote_count.values())
            candidates = [target_id for target_id, votes in vote_count.items() if votes == max_votes]
            
            if len(candidates) > 1:
                # Seri, voting ulang antara kandidat seri
                context.bot.send_message(
                    chat_id=chat_id,
                    text="🤝 *Hasil seri!* Voting ulang antara kandidat:",
                    parse_mode='Markdown'
                )
                
                keyboard = []
                for target_id in candidates:
                    target_nama = next(p['nama'] for p in game['pemain'] if p['id'] == target_id)
                    keyboard.append([InlineKeyboardButton(target_nama, callback_data=f"vote_{target_id}")])
                
                vote_msg = context.bot.send_message(
                    chat_id=chat_id,
                    text="Pilih salah satu yang akan ditangkap:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                game['vote_message_id'] = vote_msg.message_id
                game['suara'] = {}  # Reset suara
                
                # Timer voting ulang (30 detik)
                context.job_queue.run_once(
                    lambda ctx: akhir_voting(ctx, chat_id),
                    30,
                    context=chat_id,
                    name=f"revote_{chat_id}"
                )
                return
            else:
                # Ada pemenang voting
                tertangkap_id = candidates[0]
                tertangkap = next(p for p in game['pemain'] if p['id'] == tertangkap_id)
                peran_tertangkap = game['roles'][tertangkap_id]
                
                # Tandai sebagai tertangkap
                game['tertangka'].append(tertangkap)
                game['pemain_mati'].append(tertangkap_id)
                
                # Kirim hasil ke grup dengan format yang lebih baik
                context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚖️ *{tertangkap['nama']} ditangkap!*\nPeran: {ROLES[peran_tertangkap]['emoji']} {peran_tertangkap}",
                    parse_mode='Markdown'
                )
                
                # Cek kondisi kemenangan
                cek_kondisi_kemenangan(context, chat_id)
        else:
            # Tidak ada yang voting, lanjut ke malam berikutnya
            context.bot.send_message(
                chat_id=chat_id,
                text="❌ Tidak ada yang voting! Lanjut ke malam berikutnya...",
                parse_mode='Markdown'
            )
            game['hari_ke'] += 1
            mulai_malam(context, chat_id)

    except Exception as e:
        logger.error(f"Error in akhir_voting: {e}")
        context.bot.send_message(chat_id, "⚠️ Error processing voting")

def cek_kondisi_kemenangan(context: CallbackContext, chat_id):
    """Cek apakah permainan sudah berakhir"""
    game = get_game(chat_id)
    
    # Hitung jumlah pemain yang masih hidup per tim
    tim_koruptor = 0
    tim_penegak_hukum = 0
    tim_masyarakat = 0
    
    for pemain in game['pemain']:
        if pemain['id'] not in game['pemain_mati']:
            peran = game['roles'][pemain['id']]
            tim = ROLES[peran]['team']
            
            if tim == 'koruptor':
                tim_koruptor += 1
            elif tim == 'penegak_hukum':
                tim_penegak_hukum += 1
            elif tim == 'masyarakat':
                tim_masyarakat += 1
    
    # Kondisi kemenangan
    if tim_koruptor == 0:
        # Penegak hukum dan masyarakat menang
        teks_kemenangan = "🎉 *PENEGAK HUKUM DAN MASYARAKAT MENANG!*\n\n"
        teks_kemenangan += "Semua koruptor telah ditangkap!\n\n"
        teks_kemenangan += "*Pemain yang masih hidup:*\n"
        
        for pemain in game['pemain']:
            if pemain['id'] not in game['pemain_mati']:
                peran = game['roles'][pemain['id']]
                teks_kemenangan += f"- {pemain['nama']} ({ROLES[peran]['emoji']} {peran})\n"
        
        teks_kemenangan += "\n*Peran lainnya:*\n"
        for pemain in game['pemain']:
            if pemain['id'] in game['pemain_mati']:
                peran = game['roles'][pemain['id']]
                teks_kemenangan += f"- {pemain['nama']}: ({ROLES[peran]['emoji']} {peran}) \n"
        
        akhir_permainan(context, chat_id, teks_kemenangan)
        
    elif tim_koruptor >= (tim_penegak_hukum + tim_masyarakat):
        # Koruptor menang
        teks_kemenangan = "💸 *KORUPTOR MENANG!*\n\n"
        teks_kemenangan += "Koruptor berhasil menguasai sistem!\n\n"
        teks_kemenangan += "*Koruptor yang masih aktif:*\n"
        
        for pemain in game['pemain']:
            if pemain['id'] not in game['pemain_mati'] and ROLES[game['roles'][pemain['id']]]['team'] == 'koruptor':
                teks_kemenangan += f"- {pemain['nama']} ({ROLES[game['roles'][pemain['id']]]['emoji']} {game['roles'][pemain['id']]})\n"
        
        teks_kemenangan += "\n*Peran lainnya:*\n"
        for pemain in game['pemain']:
            if pemain['id'] in game['pemain_mati']:
                peran = game['roles'][pemain['id']]
                teks_kemenangan += f"- {pemain['nama']}: ({ROLES[peran]['emoji']} {peran}) \n"
        
        akhir_permainan(context, chat_id, teks_kemenangan)
        
    else:
        # Lanjut ke malam berikutnya
        game['hari_ke'] += 1
        game['suara'] = {}
        game['malam_actions'] = {}
        game['night_results'] = {}
        
        context.bot.send_message(
            chat_id=chat_id,
            text=f"🌙 Mempersiapkan malam ke-{game['hari_ke']}...",
            parse_mode='Markdown'
        )
        
        # Timer sebelum malam
        context.job_queue.run_once(
            lambda ctx: mulai_malam(ctx, chat_id),
            5,
            context=chat_id,
            name=f"prepare_night_{chat_id}"
        )

def akhir_permainan(context: CallbackContext, chat_id: int, hasil_text: str):
    """Akhiri permainan dan tampilkan hasil"""
    game = get_game(chat_id)
    
    # Kirim hasil akhir
    context.bot.send_message(
        chat_id=chat_id,
        text=hasil_text,
        parse_mode='Markdown'
    )
    
    # Reset game
    reset_game(chat_id, context)

def cancel_game(update: Update, context: CallbackContext):
    """Batalkan permainan yang sedang berjalan"""
    if update.effective_chat.type == 'private':
        update.message.reply_text("❌ Hanya bisa dilakukan di grup!")
        return

    chat_id = update.effective_chat.id
    game = get_game(chat_id)
    
    if not game['sedang_berlangsung']:
        update.message.reply_text("❌ Tidak ada permainan yang berjalan!")
        return

    # Hapus semua job
    current_jobs = []
    for job_type in ['malam', 'voting', 'revote', 'prepare_night', 'voting_warning']:
        current_jobs += context.job_queue.get_jobs_by_name(f"{job_type}_{chat_id}")
    
    for job in current_jobs:
        job.schedule_removal()
    
    reset_game(chat_id, context)
    update.message.reply_text("🔴 Permainan dibatalkan!")

def status_game(update: Update, context: CallbackContext):
    """Cek status permainan saat ini"""
    if update.effective_chat.type == 'private':
        update.message.reply_text("❌ Hanya bisa dilakukan di grup!")
        return

    chat_id = update.effective_chat.id
    game = get_game(chat_id)
    
    if not game['sedang_berlangsung']:
        update.message.reply_text("❌ Tidak ada permainan yang berjalan!")
        return
    
    status_text = f"🎮 *STATUS PERMAINAN*\n\n"
    status_text += f"Hari: {game['hari_ke']}\n"
    status_text += f"Fase: {game['fase'].capitalize()}\n\n"
    
    status_text += "👥 *Pemain Hidup:*\n"
    for pemain in game['pemain']:
        if pemain['id'] not in game['pemain_mati']:
            peran = game['roles'][pemain['id']]
            status_text += f"- {pemain['nama']} ({ROLES[peran]['emoji']} {peran})\n"
    
    status_text += "\n💀 *Pemain Mati:*\n"
    for pemain in game['pemain']:
        if pemain['id'] in game['pemain_mati']:
            peran = game['roles'][pemain['id']]
            status_text += f"- {pemain['nama']} ({ROLES[peran]['emoji']} {peran})\n"
    
    update.message.reply_text(status_text, parse_mode='Markdown')

def error_handler(update: Update, context: CallbackContext):
    """Handle error yang terjadi"""
    logger.error(msg="Exception while handling update:", exc_info=context.error)
    
    if update and update.effective_message:
        update.effective_message.reply_text(
            "❌ Error terjadi. Silakan coba lagi atau mulai permainan baru."
        )

# Run bot
def run_bot():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Command handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("game", gabung))
    dp.add_handler(CommandHandler("mulai", mulai_permainan))
    dp.add_handler(CommandHandler("cancel", cancel_game))
    dp.add_handler(CommandHandler("status", status_game))
    
    # Callback handlers
    dp.add_handler(CallbackQueryHandler(handle_vote, pattern=r"^vote_\d+$"))
    dp.add_handler(CallbackQueryHandler(handle_night_action, pattern=r"^night_"))
    
    # Error handler
    dp.add_error_handler(error_handler)

    # Start bot
    updater.start_polling()
    updater.idle()

@app.route('/')
def home():
    return "Game Koruptor Bot sedang aktif!"

if __name__ == '__main__':
    # Run Telegram bot in separate thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    # Run Flask
    app.run(host='0.0.0.0', port=8000)                    
                    
