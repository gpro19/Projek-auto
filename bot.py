from flask import Flask
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler, CallbackContext,
    MessageHandler, Filters, JobQueue
)

import threading
import logging
from telegram.error import NetworkError, BadRequest
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
ALLOWED_GROUP_IDS = (-1001651683956, -1002334351077, -1002540626336)

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
            'vote_message_id': None,
            'protected_players': [],
            'voted_players': []
        }
    return games[chat_id]

def cleanup_jobs(context: CallbackContext, chat_id: int):
    """Membersihkan semua job untuk chat tertentu"""
    try:
        # Hapus job berdasarkan nama
        job_names = [
            f"join_timer_{chat_id}",
            f"join_warning_{chat_id}",
            f"game_start_{chat_id}",
            f"malam_{chat_id}",
            f"voting_{chat_id}",
            f"voting_warning_{chat_id}",
            f"revote_{chat_id}",
            f"prepare_night_{chat_id}"
        ]
        
        for job_name in job_names:
            jobs = context.job_queue.get_jobs_by_name(job_name)
            for job in jobs:
                job.schedule_removal()
                
    except Exception as e:
        logger.error(f"Error cleaning up jobs: {e}")

def reset_game(chat_id: int, context: CallbackContext = None):
    """Reset game state and cancel all jobs safely"""
    try:
        if context:
            cleanup_jobs(context, chat_id)
        
        game = get_game(chat_id)
        
        # Hapus pesan pending
        if context:
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
    job_context = context.job.context
    if isinstance(job_context, dict):
        chat_id = job_context['chat_id']
    else:
        chat_id = job_context
        
    game = get_game(chat_id)
    
    if not game.get('join_started'):
        return

    # Hapus pesan pending
    for msg_id in game.get('pending_messages', []):
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.error(f"Gagal hapus pesan {msg_id}: {e}")

    game['pending_messages'] = []
    game['join_message_id'] = None
    game['join_started'] = False

    if len(game['pemain']) >= 5:
        try:
            context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Pendaftaran ditutup dengan {len(game['pemain'])} pemain!\n⏳ Memulai permainan...",
                parse_mode='Markdown'
            )
            
            # Auto start game
            context.job_queue.run_once(
                auto_start_game,
                2,
                context={'chat_id': chat_id},
                name=f"game_start_{chat_id}"
            )
        except Exception as e:
            logger.error(f"Error in join_time_up: {e}")
            reset_game(chat_id, context)
    else:
        context.bot.send_message(
            chat_id=chat_id,
            text="❌ Tidak cukup pemain untuk memulai permainan!",
            parse_mode='Markdown'
        )
        reset_game(chat_id, context)

def join_warning(context: CallbackContext):
    """Peringatan waktu gabung hampir habis"""
    job_context = context.job.context
    if isinstance(job_context, dict):
        chat_id = job_context['chat_id']
    else:
        chat_id = job_context
        
    game = get_game(chat_id)
    
    if not game.get('join_started'):
        return

    try:
        warning_msg = context.bot.send_message(
            chat_id=chat_id,
            text="⏰ *15 detik lagi untuk bergabung!*",
            parse_mode='Markdown'
        )
        game['pending_messages'].append(warning_msg.message_id)
    except Exception as e:
        logger.error(f"Gagal kirim peringatan: {e}")

def auto_start_game(context: CallbackContext):
    """Automatically start game after join timer ends"""
    try:
        job_context = context.job.context
        if isinstance(job_context, dict):
            chat_id = job_context['chat_id']
        else:
            chat_id = job_context
            
        game = get_game(chat_id)
        
        if len(game['pemain']) < 5:
            context.bot.send_message(
                chat_id=chat_id,
                text="❌ Gagal memulai - minimal 5 pemain diperlukan!",
                parse_mode='Markdown'
            )
            reset_game(chat_id, context)
            return

        # Mulai permainan langsung
        start_game_directly(context, chat_id)

    except Exception as e:
        logger.error(f"Error in auto_start_game: {e}")
        context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Gagal memulai permainan secara otomatis. Silakan coba /mulai manual."
        )
        reset_game(chat_id, context)

def start_game_directly(context: CallbackContext, chat_id: int):
    """Start game directly without update object"""
    game = get_game(chat_id)
    
    if game['sedang_berlangsung']:
        return
    
    jumlah_pemain = len(game['pemain'])
    
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
        'vote_message_id': None,
        'protected_players': [],
        'voted_players': []
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
            context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Tidak bisa mengirim pesan ke {pemain['nama']}. "
                     "Pastikan sudah memulai chat dengan bot!"
            )
            reset_game(chat_id, context)
            return

    # Mulai malam pertama
    context.job_queue.run_once(
        lambda ctx: mulai_malam(ctx, chat_id),
        3,
        context={'chat_id': chat_id},
        name=f"prepare_night_{chat_id}"
    )

def start(update: Update, context: CallbackContext):
    if context.args and context.args[0].startswith('join_'):
        join_request(update, context)
        return
    
    user_name = update.effective_user.first_name or update.effective_user.full_name

    start_text = (
        f"Hai {user_name}! 🎮\n\n"
        "Saya adalah bot Game Koruptor untuk grup Telegram.\n"
        "Tambahkan saya ke grup untuk mulai bermain!"
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
        update.message.reply_text("❌ Perintah ini hanya bisa digunakan di grup!")
        return

    chat_id = update.effective_chat.id
    game = get_game(chat_id)

    if game['sedang_berlangsung']:
        update.message.reply_text("⚠️ Permainan sudah berjalan! Tunggu game selanjutnya.")
        return

    # Reset jika ada game sebelumnya yang tidak selesai
    if game.get('join_started'):
        cleanup_jobs(context, chat_id)
        
    game.update({
        'pemain': [],
        'pending_messages': [],
        'join_started': True,
        'join_message_id': None
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
    
    try:
        msg = update.message.reply_text(
            f"🎮 *GAME KORUPTOR DIMULAI!*\n\n"
            f"⏱️ Waktu bergabung: 60 detik\n"
            f"👥 Pemain: 0/10\n"
            f"🎯 Minimal: 5 pemain\n\n"
            "Klik tombol di bawah untuk bergabung:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        game['join_message_id'] = msg.message_id
        game['pending_messages'].append(msg.message_id)
        
        # Set timer
        context.job_queue.run_once(
            join_time_up,
            60,
            context={'chat_id': chat_id},
            name=f"join_timer_{chat_id}"
        )

        context.job_queue.run_once(
            join_warning,
            45,
            context={'chat_id': chat_id},
            name=f"join_warning_{chat_id}"
        )
        
    except Exception as e:
        logger.error(f"Error in gabung: {e}")
        update.message.reply_text("❌ Terjadi kesalahan saat memulai pendaftaran!")

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
  
        if abs(time.time() - timestamp) > 300:  # 5 menit
            update.message.reply_text("⌛ Link bergabung sudah kadaluarsa!")
            return

    except Exception as e:
        logger.error(f"Invalid join token: {str(e)}")
        update.message.reply_text("❌ Link bergabung tidak valid!")
        return

    game = get_game(chat_id)
    
    if not game.get('join_started', False):
        update.message.reply_text("⌛ Waktu bergabung sudah habis atau belum dimulai!")
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
    
    try:
        chat = context.bot.get_chat(chat_id)
        group_name = chat.title if chat.title else "grup ini"
    except:
        group_name = "grup ini"
        
    update.message.reply_text(
        f"✅ Kamu berhasil bergabung di *{group_name}*!\n"
        f"Sekarang ada *{len(game['pemain'])}/10 pemain*",
        parse_mode='Markdown'
    )
    
    # Update pesan di grup
    try:
        timestamp = str(int(time.time()))
        combined = f"{timestamp}_{chat_id}"
        tokenku = encode_chat_id(combined)
        safe_token = urllib.parse.quote(tokenku)
        
        keyboard = [[InlineKeyboardButton(
            "🎮 Gabung Permainan", 
            url=f"https://t.me/{context.bot.username}?start=join_{safe_token}"
        )]]
        
        context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=game['join_message_id'],
            text=f"🎮 *GAME KORUPTOR DIMULAI!*\n\n"
                 f"⏱️ Waktu bergabung: 60 detik\n"
                 f"👥 Pemain: {len(game['pemain'])}/10\n"
                 f"🎯 Minimal: 5 pemain\n\n"
                 "Klik tombol di bawah untuk bergabung:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
        # Notify di grup
        notify_msg = context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ [{username}](tg://user?id={user_id}) bergabung! ({len(game['pemain'])}/10)",
            parse_mode='Markdown'
        )
        game['pending_messages'].append(notify_msg.message_id)
        
    except Exception as e:
        logger.error(f"Gagal update pesan grup: {e}")
        
    # Auto start jika penuh
    if len(game['pemain']) >= 10:
        cleanup_jobs(context, chat_id)
        context.bot.send_message(
            chat_id=chat_id,
            text="🎉 Pemain sudah penuh! Memulai permainan...",
            parse_mode='Markdown'
        )
        start_game_directly(context, chat_id)

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
        update.message.reply_text("❌ Perintah ini hanya bisa digunakan di grup!")
        return

    chat_id = update.effective_chat.id
    game = get_game(chat_id)
    
    if game['sedang_berlangsung']:
        update.message.reply_text("⚠️ Permainan sudah berjalan!")
        return

    jumlah_pemain = len(game['pemain'])
    
    if jumlah_pemain < 5:
        update.message.reply_text(
            f"❌ Minimal 5 pemain untuk memulai!\n"
            f"Pemain saat ini: {jumlah_pemain}/5\n\n"
            "Gunakan /game untuk mulai pendaftaran."
        )
        return
    
    # Mulai permainan langsung
    start_game_directly(context, chat_id)

def mulai_malam(context: CallbackContext, chat_id: int):
    """Memulai fase malam"""
    game = get_game(chat_id)
    
    if not game['sedang_berlangsung']:
        return
        
    game['fase'] = 'malam'
    game['malam_actions'] = {}
    game['night_results'] = {}
    game['protected_players'] = []
    
    # Kirim pesan ke grup
    malam_text = f"🌙 *MALAM HARI KE-{game['hari_ke']}*\n\n"
    malam_text += "Para koruptor bergerak dalam kegelapan...\n"
    malam_text += "Penegak hukum juga tidak tidur!\n\n"
    
    # Daftar pemain hidup
    pemain_hidup = [p for p in game['pemain'] if p['id'] not in game['pemain_mati']]
    malam_text += f"👥 *Pemain hidup: {len(pemain_hidup)}*\n"
    for i, pemain in enumerate(pemain_hidup, 1):
        malam_text += f"{i}. {pemain['nama']}\n"
    
    malam_text += f"\n⏱️ Waktu aksi: 60 detik"
    
    try:
        context.bot.send_message(
            chat_id=chat_id,
            text=malam_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error sending night message: {e}")
        return
    
    # Kirim aksi malam ke pemain yang masih hidup
    for pemain in game['pemain']:
        if pemain['id'] in game['pemain_mati']:
            continue
            
        peran = game['roles'][pemain['id']]
        
        # Hanya kirim aksi untuk peran yang punya aksi malam
        if peran in ["Koruptor", "KPK", "Jaksa", "Polisi", "Whistleblower"]:
            try:
                keyboard = []
                targets = [p for p in game['pemain'] if p['id'] not in game['pemain_mati']]
                
                if peran == "Koruptor":
                    # Koruptor tidak bisa target sesama koruptor
                    targets = [t for t in targets if t['id'] != pemain['id'] and 
                             game['roles'][t['id']] != 'Koruptor']
                    
                    for target in targets:
                        keyboard.append([InlineKeyboardButton(
                            target['nama'], 
                            callback_data=f"night_koruptor_{target['id']}"
                        )])
                    
                    if keyboard:
                        context.bot.send_message(
                            chat_id=pemain['id'],
                            text="🌙 *Aksi Malam - Koruptor*\n\n"
                                 "Pilih target untuk disuap:\n"
                                 "• Target yang disuap tidak bisa voting besok\n"
                                 "• Tidak bisa menyuap sesama koruptor",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode='Markdown'
                        )
                
                elif peran == "KPK":
                    targets = [t for t in targets if t['id'] != pemain['id']]
                    
                    for target in targets:
                        keyboard.append([InlineKeyboardButton(
                            target['nama'], 
                            callback_data=f"night_kpk_{target['id']}"
                        )])
                    
                    if keyboard:
                        context.bot.send_message(
                            chat_id=pemain['id'],
                            text="🌙 *Aksi Malam - KPK*\n\n"
                                 "Pilih target untuk diselidiki:\n"
                                 "• Anda akan mengetahui peran target\n"
                                 "• Jika target dilindungi, penyelidikan gagal",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode='Markdown'
                        )
                
                elif peran == "Jaksa":
                    for target in targets:
                        keyboard.append([InlineKeyboardButton(
                            target['nama'], 
                            callback_data=f"night_jaksa_{target['id']}"
                        )])
                    
                    if keyboard:
                        context.bot.send_message(
                            chat_id=pemain['id'],
                            text="🌙 *Aksi Malam - Jaksa*\n\n"
                                 "Pilih target untuk dilindungi:\n"
                                 "• Target tidak bisa diselidiki KPK\n"
                                 "• Bisa melindungi diri sendiri",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode='Markdown'
                        )
                
                elif peran == "Polisi":
                    targets = [t for t in targets if t['id'] != pemain['id']]
                    
                    for target in targets:
                        keyboard.append([InlineKeyboardButton(
                            target['nama'], 
                            callback_data=f"night_polisi_{target['id']}"
                        )])
                    
                    if keyboard:
                        context.bot.send_message(
                            chat_id=pemain['id'],
                            text="🌙 *Aksi Malam - Polisi*\n\n"
                                 "Pilih target untuk diawasi:\n"
                                 "• Akan mengetahui jika target melakukan aksi mencurigakan",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode='Markdown'
                        )
                
                elif peran == "Whistleblower":
                    targets = [t for t in targets if t['id'] != pemain['id']]
                    
                    for target in targets:
                        keyboard.append([InlineKeyboardButton(
                            target['nama'], 
                            callback_data=f"night_whistleblower_{target['id']}"
                        )])
                    
                    if keyboard:
                        context.bot.send_message(
                            chat_id=pemain['id'],
                            text="🌙 *Aksi Malam - Whistleblower*\n\n"
                                 "Pilih target untuk diungkap:\n"
                                 "• Akan mengetahui tim target\n"
                                 "• (Koruptor/Penegak Hukum/Masyarakat)",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode='Markdown'
                        )
                
            except Exception as e:
                logger.error(f"Gagal kirim aksi malam ke {pemain['nama']}: {e}")
    
    # Timer aksi malam
    context.job_queue.run_once(
        lambda ctx: akhir_malam(ctx, chat_id),
        60,
        context={'chat_id': chat_id},
        name=f"malam_{chat_id}"
    )

def handle_night_action(update: Update, context: CallbackContext):
    """Handle aksi malam dari pemain"""
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    target_chat_id = None
    
    # Cari game yang sedang berlangsung dan user adalah peserta
    for chat_id, game_data in games.items():
        if (game_data.get('sedang_berlangsung') and 
            game_data.get('fase') == 'malam' and
            any(p['id'] == user_id for p in game_data.get('pemain', []))):
            target_chat_id = chat_id
            break
    
    if not target_chat_id:
        query.edit_message_text("❌ Tidak ditemukan game yang sedang berlangsung!")
        return
        
    game = get_game(target_chat_id)
    
    if game['fase'] != 'malam':
        query.edit_message_text("❌ Waktu aksi malam sudah habis!")
        return
    
    # Cek apakah pemain masih hidup
    if user_id in game['pemain_mati']:
        query.edit_message_text("❌ Kamu sudah mati dan tidak bisa melakukan aksi!")
        return
    
    data_parts = query.data.split('_')
    
    if len(data_parts) < 3:
        query.edit_message_text("❌ Data aksi tidak valid!")
        return
    
    action_type = data_parts[1]
    target_id = int(data_parts[2])
    
    # Validasi target masih hidup
    if target_id in game['pemain_mati']:
        query.edit_message_text("❌ Target sudah mati!")
        return
    
    # Simpan aksi pemain (overwrite jika sudah ada)
    game['malam_actions'][user_id] = {
        'type': action_type,
        'target_id': target_id,
        'waktu': time.time()
    }
    
    # Konfirmasi ke pemain
    target_nama = next((p['nama'] for p in game['pemain'] if p['id'] == target_id), "Unknown")
    query.edit_message_text(f"✅ Aksi {action_type} terhadap *{target_nama}* berhasil dicatat!", parse_mode='Markdown')

def akhir_malam(context: CallbackContext, chat_id: int):
    """Proses hasil aksi malam"""
    game = get_game(chat_id)
    
    if not game['sedang_berlangsung'] or game['fase'] != 'malam':
        return
    
    # Proses semua aksi malam berdasarkan priority
    actions_by_priority = []
    
    for user_id, action in game['malam_actions'].items():
        if user_id in game['pemain_mati']:  # Skip jika pemain sudah mati
            continue
            
        peran = game['roles'][user_id]
        priority = ROLES[peran]['priority']
        actions_by_priority.append((priority, user_id, action))
    
    # Urutkan berdasarkan priority (angka kecil = priority tinggi)
    actions_by_priority.sort(key=lambda x: x[0])
    
    # Proses aksi berdasarkan urutan priority
    for priority, user_id, action in actions_by_priority:
        peran = game['roles'][user_id]
        target_id = action['target_id']
        
        # Skip jika target sudah mati
        if target_id in game['pemain_mati']:
            continue
        
        if peran == "Jaksa":
            # Jaksa melindungi target (priority 3)
            game['protected_players'].append(target_id)
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text="✅ Target berhasil dilindungi!",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Gagal kirim konfirmasi ke Jaksa: {e}")
        
        elif peran == "KPK":
            # KPK menyelidiki peran target (priority 2)
            if target_id in game['protected_players']:
                try:
                    context.bot.send_message(
                        chat_id=user_id,
                        text="❌ Target dilindungi, penyelidikan gagal!",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Gagal kirim hasil gagal ke KPK: {e}")
            else:
                target_peran = game['roles'][target_id]
                try:
                    context.bot.send_message(
                        chat_id=user_id,
                        text=f"🔍 *Hasil Penyelidikan:*\n\n"
                             f"Target: {next(p['nama'] for p in game['pemain'] if p['id'] == target_id)}\n"
                             f"Peran: {ROLES[target_peran]['emoji']} {target_peran}",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Gagal kirim hasil penyelidikan: {e}")
        
        elif peran == "Polisi":
            # Polisi mengawasi target (priority 4)
            suspicious_activity = False
            
            # Cek apakah target melakukan aksi mencurigakan
            for other_user_id, other_action in game['malam_actions'].items():
                if (other_user_id == target_id and 
                    other_action['type'] in ['koruptor', 'whistleblower']):
                    suspicious_activity = True
                    break
            
            try:
                if suspicious_activity:
                    context.bot.send_message(
                        chat_id=user_id,
                        text=f"🚨 *Hasil Pengawasan:*\n\n"
                             f"Target melakukan aktivitas mencurigakan!",
                        parse_mode='Markdown'
                    )
                else:
                    context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ *Hasil Pengawasan:*\n\n"
                             f"Target tidak melakukan aktivitas mencurigakan.",
                        parse_mode='Markdown'
                    )
            except Exception as e:
                logger.error(f"Gagal kirim hasil pengawasan: {e}")
        
        elif peran == "Whistleblower":
            # Whistleblower mengungkap tim target (priority 6)
            target_peran = game['roles'][target_id]
            target_team = ROLES[target_peran]['team']
            
            team_names = {
                'koruptor': 'Tim Koruptor 🕵️',
                'penegak_hukum': 'Tim Penegak Hukum 👮',
                'masyarakat': 'Tim Masyarakat 👨'
            }
            
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text=f"📢 *Informasi Terbongkar:*\n\n"
                         f"Target: {next(p['nama'] for p in game['pemain'] if p['id'] == target_id)}\n"
                         f"Tim: {team_names.get(target_team, target_team)}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Gagal kirim hasil whistleblower: {e}")
        
        elif peran == "Koruptor":
            # Koruptor menyuap target (priority 1)
            if target_id not in game['night_results']:
                game['night_results'][target_id] = []
            game['night_results'][target_id].append("suap_koruptor")
            
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text="💰 Target berhasil disuap!",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Gagal kirim konfirmasi ke Koruptor: {e}")
    
    # Mulai fase siang
    context.job_queue.run_once(
        lambda ctx: mulai_siang(ctx, chat_id),
        3,
        context={'chat_id': chat_id},
        name=f"prepare_day_{chat_id}"
    )

def mulai_siang(context: CallbackContext, chat_id: int):
    """Memulai fase siang"""
    game = get_game(chat_id)
    
    if not game['sedang_berlangsung']:
        return
        
    game['fase'] = 'siang'
    game['suara'] = {}
    game['voted_players'] = []
    
    # Kirim hasil malam ke grup
    hasil_text = f"☀️ *PAGI HARI KE-{game['hari_ke']}*\n\n"
    hasil_text += "Matahari terbit dan mengungkap apa yang terjadi tadi malam...\n\n"
    
    # Cek siapa yang disuap koruptor
    korban_suapan = []
    for target_id, results in game['night_results'].items():
        if "suap_koruptor" in results:
            target_nama = next((p['nama'] for p in game['pemain'] if p['id'] == target_id), "Unknown")
            korban_suapan.append(target_nama)
    
    if korban_suapan:
        hasil_text += f"💰 *Korban suapan:* {', '.join(korban_suapan)}\n"
        hasil_text += "(Tidak bisa voting hari ini)\n\n"
    
    # Daftar pemain hidup
    pemain_hidup = [p for p in game['pemain'] if p['id'] not in game['pemain_mati']]
    hasil_text += f"👥 *Pemain hidup: {len(pemain_hidup)}*\n"
    for i, pemain in enumerate(pemain_hidup, 1):
        hasil_text += f"{i}. {pemain['nama']}\n"
    
    hasil_text += f"\n🗳️ Saatnya voting untuk menangkap tersangka!"
    
    try:
        context.bot.send_message(
            chat_id=chat_id,
            text=hasil_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error sending morning message: {e}")
        return
    
    # Buat tombol voting
    keyboard = []
    vote_targets = []
    
    # Hanya pemain yang hidup dan tidak disuap yang bisa divoting
    for pemain in game['pemain']:
        if (pemain['id'] not in game['pemain_mati'] and 
            pemain['id'] not in [tid for tid, results in game['night_results'].items() 
                               if "suap_koruptor" in results]):
            vote_targets.append(pemain)
    
    if not vote_targets:
        # Tidak ada yang bisa divoting
        context.bot.send_message(
            chat_id=chat_id,
            text="❌ Tidak ada yang bisa divoting hari ini!\n"
                 "Lanjut ke malam berikutnya...",
            parse_mode='Markdown'
        )
        game['hari_ke'] += 1
        context.job_queue.run_once(
            lambda ctx: mulai_malam(ctx, chat_id),
            5,
            context={'chat_id': chat_id},
            name=f"prepare_night_{chat_id}"
        )
        return
    
    # Kelompokkan tombol dalam baris 2 kolom
    for i in range(0, len(vote_targets), 2):
        row = []
        if i < len(vote_targets):
            row.append(InlineKeyboardButton(
                f"{vote_targets[i]['nama']} (0)", 
                callback_data=f"vote_{vote_targets[i]['id']}"
            ))
        if i + 1 < len(vote_targets):
            row.append(InlineKeyboardButton(
                f"{vote_targets[i+1]['nama']} (0)", 
                callback_data=f"vote_{vote_targets[i+1]['id']}"
            ))
        keyboard.append(row)
    
    try:
        vote_msg = context.bot.send_message(
            chat_id=chat_id,
            text="🗳️ *PEMUNGUTAN SUARA*\n\nPilih siapa yang akan ditangkap:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        game['vote_message_id'] = vote_msg.message_id
        
        # Timer voting
        context.job_queue.run_once(
            lambda ctx: akhir_voting(ctx, chat_id),
            60,
            context={'chat_id': chat_id},
            name=f"voting_{chat_id}"
        )
        
        # Peringatan voting
        context.job_queue.run_once(
            lambda ctx: voting_warning(ctx, chat_id),
            45,
            context={'chat_id': chat_id},
            name=f"voting_warning_{chat_id}"
        )
        
    except Exception as e:
        logger.error(f"Error creating voting: {e}")

def voting_warning(context: CallbackContext, chat_id: int):
    """Peringatan waktu voting hampir habis"""
    game = get_game(chat_id)
    
    if not game['sedang_berlangsung'] or game['fase'] != 'siang':
        return
        
    try:
        context.bot.send_message(
            chat_id=chat_id,
            text="⏰ *15 detik lagi untuk voting!*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Gagal kirim peringatan voting: {e}")

def handle_vote(update: Update, context: CallbackContext):
    """Handle voting dari pemain"""
    query = update.callback_query
    
    try:
        voter_id = query.from_user.id
        chat_id = query.message.chat.id
        game = get_game(chat_id)
        
        # Validasi game dan fase
        if not game['sedang_berlangsung'] or game['fase'] != 'siang':
            query.answer("❌ Bukan waktu voting!", show_alert=True)
            return
            
        # Cek apakah voter masih hidup
        if voter_id in game['pemain_mati']:
            query.answer("❌ Kamu sudah mati dan tidak bisa voting!", show_alert=True)
            return
            
        # Cek apakah voter adalah pemain game
        if not any(p['id'] == voter_id for p in game['pemain']):
            query.answer("❌ Kamu bukan pemain dalam game ini!", show_alert=True)
            return
        
        # Cek apakah voter disuap
        if voter_id in [tid for tid, results in game['night_results'].items() 
                       if "suap_koruptor" in results]:
            query.answer("❌ Kamu disuap koruptor dan tidak bisa voting!", show_alert=True)
            return

        # Parse target
        _, target_id_str = query.data.split('_')
        target_id = int(target_id_str)
        
        # Validasi target
        if target_id in game['pemain_mati']:
            query.answer("❌ Target sudah mati!", show_alert=True)
            return
            
        if target_id in [tid for tid, results in game['night_results'].items() 
                        if "suap_koruptor" in results]:
            query.answer("❌ Target disuap dan tidak bisa divoting!", show_alert=True)
            return

        # Simpan vote
        game['suara'][voter_id] = target_id
        
        # Hitung ulang suara
        vote_count = {}
        for voted_target_id in game['suara'].values():
            vote_count[voted_target_id] = vote_count.get(voted_target_id, 0) + 1
        
        # Update tombol dengan jumlah suara terbaru
        keyboard = []
        vote_targets = []
        
        for pemain in game['pemain']:
            if (pemain['id'] not in game['pemain_mati'] and 
                pemain['id'] not in [tid for tid, results in game['night_results'].items() 
                                   if "suap_koruptor" in results]):
                vote_targets.append(pemain)
        
        # Kelompokkan tombol dalam baris 2 kolom dengan jumlah suara
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
            keyboard.append(row)
        
        # Update pesan voting
        try:
            query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            target_nama = next(p['nama'] for p in game['pemain'] if p['id'] == target_id)
            query.answer(f"✅ Kamu memilih {target_nama}!")
        except BadRequest as e:
            if "message is not modified" not in str(e).lower():
                logger.error(f"Error updating vote buttons: {e}")
            query.answer(f"✅ Vote tercatat!")

    except Exception as e:
        logger.error(f"Error in handle_vote: {e}")
        try:
            query.answer("❌ Terjadi kesalahan saat voting!", show_alert=True)
        except:
            pass

def akhir_voting(context: CallbackContext, chat_id: int):
    """Proses akhir voting dan tentukan hasil"""
    try:
        game = get_game(chat_id)
        
        if not game['sedang_berlangsung'] or game['fase'] != 'siang':
            return

        # Hapus pesan voting
        if game.get('vote_message_id'):
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=game['vote_message_id'])
            except Exception as e:
                logger.error(f"Gagal hapus pesan voting: {e}")

        # Hitung hasil voting
        vote_count = {}
        total_voters = 0
        
        # Hitung pemain yang bisa voting
        eligible_voters = []
        for pemain in game['pemain']:
            if (pemain['id'] not in game['pemain_mati'] and 
                pemain['id'] not in [tid for tid, results in game['night_results'].items() 
                                   if "suap_koruptor" in results]):
                eligible_voters.append(pemain['id'])
        
        total_voters = len(eligible_voters)
        
        for voter_id, target_id in game['suara'].items():
            if voter_id in eligible_voters:  # Hanya hitung vote yang valid
                vote_count[target_id] = vote_count.get(target_id, 0) + 1

        # Kirim hasil voting
        if vote_count:
            max_votes = max(vote_count.values())
            candidates = [target_id for target_id, votes in vote_count.items() if votes == max_votes]
            
            # Tampilkan hasil voting
            hasil_voting = f"📊 *HASIL VOTING* ({len(game['suara'])}/{total_voters} voting)\n\n"
            
            # Sort berdasarkan jumlah suara
            sorted_votes = sorted(vote_count.items(), key=lambda x: x[1], reverse=True)
            for target_id, votes in sorted_votes:
                target_nama = next(p['nama'] for p in game['pemain'] if p['id'] == target_id)
                hasil_voting += f"• {target_nama}: {votes} suara\n"
            
            context.bot.send_message(
                chat_id=chat_id,
                text=hasil_voting,
                parse_mode='Markdown'
            )
            
            if len(candidates) > 1:
                # Seri - random pick atau voting ulang singkat
                tertangkap_id = random.choice(candidates)
                context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🤝 *Hasil seri!* Dipilih secara acak...",
                    parse_mode='Markdown'
                )
            else:
                tertangkap_id = candidates[0]
            
            # Proses penangkapan
            tertangkap = next(p for p in game['pemain'] if p['id'] == tertangkap_id)
            peran_tertangkap = game['roles'][tertangkap_id]
            
            game['tertangka'].append(tertangkap)
            game['pemain_mati'].append(tertangkap_id)
            
            # Kirim hasil penangkapan
            context.bot.send_message(
                chat_id=chat_id,
                text=f"⚖️ *{tertangkap['nama']} DITANGKAP!*\n\n"
                     f"Peran: {ROLES[peran_tertangkap]['emoji']} *{peran_tertangkap}*\n"
                     f"Tim: {ROLES[peran_tertangkap]['team']}",
                parse_mode='Markdown'
            )
            
        else:
            # Tidak ada yang voting
            context.bot.send_message(
                chat_id=chat_id,
                text="❌ *Tidak ada yang voting!*\nTidak ada yang ditangkap hari ini.",
                parse_mode='Markdown'
            )
        
        # Cek kondisi kemenangan
        context.job_queue.run_once(
            lambda ctx: cek_kondisi_kemenangan(ctx, chat_id),
            3,
            context={'chat_id': chat_id},
            name=f"check_win_{chat_id}"
        )

    except Exception as e:
        logger.error(f"Error in akhir_voting: {e}")
        context.bot.send_message(chat_id, "⚠️ Error processing voting")

def cek_kondisi_kemenangan(context: CallbackContext, chat_id: int):
    """Cek apakah permainan sudah berakhir"""
    game = get_game(chat_id)
    
    if not game['sedang_berlangsung']:
        return
    
    # Hitung pemain hidup per tim
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
    
    total_non_koruptor = tim_penegak_hukum + tim_masyarakat
    
    # Kondisi kemenangan
    if tim_koruptor == 0:
        # Penegak hukum dan masyarakat menang
        teks_kemenangan = "🎉 *KEMENANGAN PENEGAK HUKUM & MASYARAKAT!*\n\n"
        teks_kemenangan += "✅ Semua koruptor telah ditangkap!\n"
        teks_kemenangan += "🏆 Negara bersih dari korupsi!\n\n"
        
        akhir_permainan(context, chat_id, teks_kemenangan)
        
    elif tim_koruptor >= total_non_koruptor:
        # Koruptor menang
        teks_kemenangan = "💸 *KEMENANGAN KORUPTOR!*\n\n"
        teks_kemenangan += "🕵️ Koruptor berhasil menguasai sistem!\n"
        teks_kemenangan += "💰 Kekuasaan dan uang menang!\n\n"
        
        akhir_permainan(context, chat_id, teks_kemenangan)
        
    else:
        # Lanjut ke malam berikutnya
        game['hari_ke'] += 1
        game['night_results'] = {}
        game['protected_players'] = []
        
        context.bot.send_message(
            chat_id=chat_id,
            text=f"🌙 *Persiapan malam ke-{game['hari_ke']}...*\n\n"
                 f"Koruptor: {tim_koruptor} | Penegak Hukum: {tim_penegak_hukum} | Masyarakat: {tim_masyarakat}",
            parse_mode='Markdown'
        )
        
        # Timer sebelum malam berikutnya
        context.job_queue.run_once(
            lambda ctx: mulai_malam(ctx, chat_id),
            5,
            context={'chat_id': chat_id},
            name=f"prepare_night_{chat_id}"
        )

def akhir_permainan(context: CallbackContext, chat_id: int, hasil_text: str):
    """Akhiri permainan dan tampilkan hasil lengkap"""
    game = get_game(chat_id)
    
    # Tampilkan pemenang spesifik
    hasil_text += "*🏆 PEMENANG:*\n"
    for pemain in game['pemain']:
        if pemain['id'] not in game['pemain_mati']:
            peran = game['roles'][pemain['id']]
            hasil_text += f"• {pemain['nama']} ({ROLES[peran]['emoji']} {peran})\n"
    
    # Tampilkan semua peran
    hasil_text += "\n*📋 SEMUA PERAN:*\n"
    
    # Kelompokkan berdasarkan tim
    tim_groups = {'koruptor': [], 'penegak_hukum': [], 'masyarakat': []}
    
    for pemain in game['pemain']:
        peran = game['roles'][pemain['id']]
        tim = ROLES[peran]['team']
        status = "💀" if pemain['id'] in game['pemain_mati'] else "❤️"
        tim_groups[tim].append(f"{status} {pemain['nama']} ({ROLES[peran]['emoji']} {peran})")
    
    for tim, nama_tim in [('koruptor', '🕵️ Tim Koruptor'), 
                         ('penegak_hukum', '👮 Tim Penegak Hukum'),
                         ('masyarakat', '👨 Tim Masyarakat')]:
        if tim_groups[tim]:
            hasil_text += f"\n*{nama_tim}:*\n"
            for pemain_info in tim_groups[tim]:
                hasil_text += f"• {pemain_info}\n"
    
    hasil_text += f"\n🎮 Game berlangsung {game['hari_ke']} hari"
    hasil_text += f"\n👥 Total pemain: {len(game['pemain'])}"
    
    # Kirim hasil akhir
    try:
        context.bot.send_message(
            chat_id=chat_id,
            text=hasil_text,
            parse_mode='Markdown'
        )
        
        # Tunggu sebentar lalu bersihkan game
        context.job_queue.run_once(
            lambda ctx: reset_game(chat_id, ctx),
            10,
            context={'chat_id': chat_id},
            name=f"cleanup_{chat_id}"
        )
        
    except Exception as e:
        logger.error(f"Error sending final results: {e}")
        reset_game(chat_id, context)

def cancel_game(update: Update, context: CallbackContext):
    """Batalkan permainan yang sedang berjalan"""
    if update.effective_chat.type == 'private':
        update.message.reply_text("❌ Perintah ini hanya bisa digunakan di grup!")
        return

    chat_id = update.effective_chat.id
    game = get_game(chat_id)
    
    # Cek apakah ada permainan yang bisa dibatalkan
    if not game.get('sedang_berlangsung') and not game.get('join_started'):
        update.message.reply_text("❌ Tidak ada permainan yang berjalan!")
        return

    # Hanya admin atau pemain yang bisa cancel
    user_id = update.effective_user.id
    try:
        chat_member = context.bot.get_chat_member(chat_id, user_id)
        is_admin = chat_member.status in ['administrator', 'creator']
        is_player = any(p['id'] == user_id for p in game.get('pemain', []))
        
        if not (is_admin or is_player):
            update.message.reply_text("❌ Hanya admin atau pemain yang bisa membatalkan permainan!")
            return
    except:
        # Jika tidak bisa cek admin status, izinkan semua pemain
        is_player = any(p['id'] == user_id for p in game.get('pemain', []))
        if not is_player and game.get('pemain'):
            update.message.reply_text("❌ Hanya pemain yang bisa membatalkan permainan!")
            return
    
    # Bersihkan game
    cleanup_jobs(context, chat_id)
    reset_game(chat_id, context)
    
    update.message.reply_text("🔴 *Permainan dibatalkan!*", parse_mode='Markdown')

def status_game(update: Update, context: CallbackContext):
    """Cek status permainan saat ini"""
    if update.effective_chat.type == 'private':
        update.message.reply_text("❌ Perintah ini hanya bisa digunakan di grup!")
        return

    chat_id = update.effective_chat.id
    game = get_game(chat_id)
    
    if game.get('join_started') and not game.get('sedang_berlangsung'):
        # Fase join
        status_text = f"🎮 *STATUS: PENDAFTARAN PEMAIN*\n\n"
        status_text += f"👥 Pemain terdaftar: {len(game.get('pemain', []))}/10\n"
        status_text += f"🎯 Minimal: 5 pemain\n\n"
        
        if game['pemain']:
            status_text += "*Daftar Pemain:*\n"
            for i, pemain in enumerate(game['pemain'], 1):
                status_text += f"{i}. {pemain['nama']}\n"
        
    elif game.get('sedang_berlangsung'):
        # Fase game
        status_text = f"🎮 *STATUS PERMAINAN*\n\n"
        status_text += f"📅 Hari ke: {game.get('hari_ke', 1)}\n"
        status_text += f"🌅 Fase: {game.get('fase', 'unknown').title()}\n\n"
        
        # Hitung pemain per tim
        tim_count = {'koruptor': 0, 'penegak_hukum': 0, 'masyarakat': 0}
        pemain_hidup = []
        
        for pemain in game.get('pemain', []):
            if pemain['id'] not in game.get('pemain_mati', []):
                pemain_hidup.append(pemain)
                peran = game['roles'].get(pemain['id'], 'Unknown')
                if peran in ROLES:
                    tim = ROLES[peran]['team']
                    tim_count[tim] += 1
        
        status_text += f"👥 *Pemain Hidup: {len(pemain_hidup)}*\n"
        status_text += f"🕵️ Koruptor: {tim_count['koruptor']}\n"
        status_text += f"👮 Penegak Hukum: {tim_count['penegak_hukum']}\n"
        status_text += f"👨 Masyarakat: {tim_count['masyarakat']}\n\n"
        
        # List pemain hidup (tanpa peran untuk menghindari spoiler)
        for i, pemain in enumerate(pemain_hidup, 1):
            status_text += f"{i}. {pemain['nama']}\n"
        
        # List pemain mati
        pemain_mati = [p for p in game.get('pemain', []) if p['id'] in game.get('pemain_mati', [])]
        if pemain_mati:
            status_text += f"\n💀 *Pemain Mati: {len(pemain_mati)}*\n"
            for pemain in pemain_mati:
                peran = game['roles'].get(pemain['id'], 'Unknown')
                status_text += f"• {pemain['nama']} ({ROLES.get(peran, {}).get('emoji', '❓')} {peran})\n"
    
    else:
        status_text = "❌ Tidak ada permainan yang berjalan!\n\n"
        status_text += "Gunakan /game untuk memulai pendaftaran."
    
    update.message.reply_text(status_text, parse_mode='Markdown')

def help_command(update: Update, context: CallbackContext):
    """Tampilkan bantuan perintah"""
    help_text = """
🎮 *GAME KORUPTOR - BANTUAN*

*Perintah Utama:*
• `/game` - Mulai pendaftaran pemain
• `/mulai` - Paksa mulai game (min 5 pemain)
• `/status` - Cek status permainan
• `/cancel` - Batalkan permainan
• `/help` - Tampilkan bantuan ini

*Cara Bermain:*
1. Gunakan `/game` untuk mulai pendaftaran
2. Pemain klik tombol untuk gabung (60 detik)
3. Game otomatis dimulai jika cukup pemain
4. Setiap pemain mendapat peran rahasia
5. Bergantian fase malam dan siang hingga ada pemenang

*Peran:*
🕵️ **Koruptor** - Suap pemain lain
👮 **KPK** - Selidiki peran pemain
⚖️ **Jaksa** - Lindungi dari penyelidikan
👮‍♂️ **Polisi** - Awasi aktivitas mencurigakan
👨 **Masyarakat** - Voting untuk menangkap
📢 **Whistleblower** - Ungkap tim pemain

*Kondisi Menang:*
• **Penegak Hukum/Masyarakat**: Tangkap semua koruptor
• **Koruptor**: Jumlah sama atau lebih dari yang lain

Selamat bermain! 🎉
    """
    
    update.message.reply_text(help_text, parse_mode='Markdown')

def rules_command(update: Update, context: CallbackContext):
    """Tampilkan aturan lengkap"""
    rules_text = """
📜 *ATURAN LENGKAP GAME KORUPTOR*

*🎯 TUJUAN PERMAINAN:*
Setiap tim punya tujuan berbeda untuk memenangkan permainan.

*👥 TIM & PERAN:*

**🕵️ TIM KORUPTOR:**
• Koruptor: Suap pemain lain agar tidak bisa voting

**👮 TIM PENEGAK HUKUM:**
• KPK: Selidiki peran pemain lain
• Jaksa: Lindungi pemain dari penyelidikan
• Polisi: Awasi aktivitas mencurigakan

**👨 TIM MASYARAKAT:**
• Masyarakat: Tidak punya aksi khusus
• Whistleblower: Ungkap tim pemain lain

*🌙 FASE MALAM (60 detik):*
• Pemain dengan aksi khusus memilih target
• Koruptor menyuap → target tidak bisa voting besok
• KPK menyelidiki → tahu peran target
• Jaksa melindungi → target tidak bisa diselidiki
• Polisi mengawasi → tahu jika target beraksi
• Whistleblower mengungkap → tahu tim target

*☀️ FASE SIANG (60 detik):*
• Hasil aksi malam diumumkan
• Pemain yang disuap tidak bisa voting
• Semua pemain vote untuk menangkap tersangka
• Yang paling banyak vote ditangkap dan mati

*🏆 KONDISI KEMENANGAN:*
• **Penegak Hukum + Masyarakat menang** jika semua Koruptor tertangkap
• **Koruptor menang** jika jumlah mereka ≥ pemain lain yang hidup

*⚖️ ATURAN KHUSUS:*
• Pemain mati tidak bisa vote atau beraksi
• Koruptor tidak bisa saling menyuap
• Jaksa bisa melindungi diri sendiri
• Jika vote seri, dipilih random
• Game minimal 5 pemain, maksimal 10

*🎮 DISTRIBUSI PERAN:*
• 5 pemain: 1 Koruptor, 4 lainnya
• 6 pemain: 2 Koruptor, 4 lainnya
• 7+ pemain: Bertambah seimbang

Mainkan dengan strategi dan keberuntungan! 🍀
    """
    
    update.message.reply_text(rules_text, parse_mode='Markdown')

def error_handler(update: Update, context: CallbackContext):
    """Handle error yang terjadi"""
    logger.error(f"Exception while handling update: {context.error}", exc_info=context.error)
    
    # Coba kirim pesan error yang ramah ke user
    if update and update.effective_message:
        try:
            update.effective_message.reply_text(
                "⚠️ Terjadi kesalahan. Silakan coba lagi atau gunakan /cancel untuk reset permainan."
            )
        except:
            pass

def run_bot():
    """Menjalankan bot Telegram"""
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Command handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("game", gabung))
    dp.add_handler(CommandHandler("mulai", mulai_permainan))
    dp.add_handler(CommandHandler("cancel", cancel_game))
    dp.add_handler(CommandHandler("status", status_game))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("rules", rules_command))
    
    # Callback handlers
    dp.add_handler(CallbackQueryHandler(handle_vote, pattern=r"^vote_\d+$"))
    dp.add_handler(CallbackQueryHandler(handle_night_action, pattern=r"^night_"))
    
    # Error handler
    dp.add_error_handler(error_handler)

    # Start bot dengan polling
    logger.info("Starting bot...")
    updater.start_polling(drop_pending_updates=True)
    logger.info("Bot started successfully!")
    updater.idle()

@app.route('/')
def home():
    return """
    <html>
    <head><title>Game Koruptor Bot</title></head>
    <body>
        <h1>🎮 Game Koruptor Bot</h1>
        <p>Bot sedang aktif dan siap digunakan!</p>
        <p>Tambahkan bot ke grup Telegram untuk mulai bermain.</p>
        <hr>
        <h3>Status:</h3>
        <p>✅ Bot Online</p>
        <p>🎯 Siap menerima game baru</p>
        <p>👥 Game aktif: """ + str(len([g for g in games.values() if g.get('sedang_berlangsung')])) + """</p>
    </body>
    </html>
    """

@app.route('/stats')
def stats():
    """Endpoint untuk melihat statistik bot"""
    active_games = len([g for g in games.values() if g.get('sedang_berlangsung')])
    joining_games = len([g for g in games.values() if g.get('join_started')])
    total_players = sum(len(g.get('pemain', [])) for g in games.values())
    
    return {
        "status": "online",
        "active_games": active_games,
        "joining_games": joining_games,
        "total_games": len(games),
        "total_players": total_players,
        "timestamp": time.time()
    }

if __name__ == '__main__':
    logger.info("Starting Game Koruptor Bot...")
    
    # Run Telegram bot in separate thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("Starting Flask web server...")
    
    # Run Flask
    app.run(host='0.0.0.0', port=8000, debug=False)
