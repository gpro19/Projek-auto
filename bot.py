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
from typing import Dict, Any
import base64
import urllib.parse


# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
TOKEN = "7590020235:AAHWRzvO8HGtBHNX3leRZ8Rfyk3kgVgUObc"
# Game configuration
ALLOWED_GROUP_IDS = (-1001651683956, -1002334351077, -1002540626336)  # Tuple of allowed IDs

KATA = {
    # Animals (40+ carefully paired words)
    "Hewan": [
        ["Singa", "Harimau", "Macan Tutul"],  # Big cats
        ["Serigala", "Jakal", "Dingo"],       # Wild dogs
        ["Kuda", "Zebra", "Keledai"],         # Equines
        ["Gajah", "Badak", "Kuda Nil"],       # Large mammals
        ["Orangutan", "Gorila", "Simpanse"],  # Great apes
        ["Panda", "Beruang", "Koala"],        # Bear-like
        ["Burung Hantu", "Elang", "Falcon"],  # Birds of prey
        ["Flamingo", "Bangau", "Pelikan"],    # Wading birds
        ["Kupu-kupu", "Capung", "Belalang"],  # Insects
        ["Ular", "Kadal", "Biawak"]           # Reptiles
    ],

    # Foods (40+ carefully paired words)  
    "Makanan": [
        ["Sate Ayam", "Sate Kambing", "Sosis"],  # Skewered meats
        ["Nasi Goreng", "Mie Goreng", "Bihun"],  # Fried staples
        ["Rendang", "Semur", "Gulai"],           # Saucy meats
        ["Bakso", "Pempek", "Otak-otak"],        # Shaped meats
        ["Martabak", "Panekuk", "Wafel"],        # Griddle cakes
        ["Es Krim", "Es Potong", "Sherbet"],     # Frozen treats
        ["Pizza", "Lasagna", "Cannelloni"],      # Italian
        ["Sushi", "Sashimi", "Onigiri"],         # Japanese
        ["Croissant", "Danish", "Pain au Chocolat"], # Pastries
        ["Coklat", "Truffle", "Fudge"]           # Chocolates
    ],

    # Professional (30+ paired occupations)
    "Profesi": [
        ["Dokter", "Perawat", "Bidan"],         # Medical
        ["Guru", "Dosen", "Pelatih"],           # Educators
        ["Programmer", "Hacker", "IT Support"],  # Tech
        ["Koki", "Baker", "Barista"],           # Food
        ["Penyanyi", "Musisi", "DJ"],           # Music
        ["Aktor", "Sutradara", "Produser"],     # Film
        ["Polisi", "Tentara", "Satpam"],        # Security
        ["Arsitek", "Insinyur", "Surveyor"],    # Construction
        ["Pilot", "Pramugari", "ATC"],          # Aviation
        ["Petani", "Nelayan", "Peternak"]       # Agriculture
    ],

    # Sports (25+ similar terms)
    "Olahraga": [
        ["Sepak Bola", "Futsal", "Rugby"],     # Ball sports
        ["Basket", "Netball", "Voli"],         # Net sports
        ["Tenis", "Bulu Tangkis", "Squash"],   # Racket sports
        ["Renang", "Menyelam", "Polo Air"],    # Water sports
        ["Lari", "Maraton", "Lari Estafet"],   # Running
        ["Binaraga", "Angkat Besi", "Crossfit"], # Strength
        ["Panahan", "Menembak", "Lempar Tombak"], # Precision
        ["Balap Motor", "Balap Mobil", "Drag Race"] # Motorsports
    ],
    
    # Office (25+ paired items)
    "Perkantoran": [
        ["Printer", "Scanner", "Fotokopi"],    # Office equipment
        ["Proyektor", "Monitor", "TV Kantor"], # Display
        ["Keyboard", "Mouse", "Trackpad"],     # Input devices
        ["Stapler", "Hole Punch", "Paper Clip"], # Stationery
        ["Kursi", "Meja", "Filing Cabinet"],   # Furniture
        ["Air Conditioner", "Kipas", "Pemanas"], # Climate
        ["Whiteboard", "Papan Tulis", "Flipchart"], # Writing
        ["ID Card", "Name Tag", "Visitor Pass"] # Identification
    ],

    # Music (30+ similar terms)  
    "Musik": [
        ["Gitar", "Bass", "Ukulele"],         # Strings
        ["Piano", "Keyboard", "Organ"],       # Keys
        ["Drum", "Bongo", "Kendang"],          # Percussion
        ["Terompet", "Trombone", "Saxophone"], # Brass
        ["Flute", "Recorder", "Klarnet"],     # Woodwinds
        ["Pop", "Rock", "Jazz"],              # Genres
        ["Konser", "Festival", "Gig"],        # Events
        ["Spotify", "Apple Music", "Joox"]    # Streaming
    ],

    # Nature (30+ similar items)
    "Alam": [
        ["Gunung", "Bukit", "Lembah"],        # Landforms
        ["Sungai", "Danau", "Rawa"],          # Water bodies
        ["Pantai", "Tebing", "Karst"],        # Coastal
        ["Hujan", "Salju", "Kabut"],          # Weather
        ["Matahari", "Bulan", "Bintang"],     # Celestial
        ["Daun", "Ranting", "Bunga"],         # Plant parts
        ["Pasir", "Kerikil", "Batu"],         # Minerals
        ["Angin", "Badai", "Tornado"]         # Wind
    ],

    # Tech (30+ similar terms)
    "Teknologi": [
        ["Smartphone", "Tablet", "Smartwatch"], # Devices
        ["WiFi", "Hotspot", "Ethernet"],      # Networking
        ["Android", "iOS", "HarmonyOS"],      # OS
        ["Python", "Java", "JavaScript"],     # Languages
        ["VR", "AR", "MR"],                   # Reality
        ["Drone", "Robot", "RC Car"],         # Robotics
        ["YouTube", "TikTok", "Instagram"],   # Platforms
        ["Cryptocurrency", "NFT", "Blockchain"] # Web3
    ]
}


# Game state management
games: Dict[int, Dict[str, Any]] = {}


def encode_chat_id(combined_value: str) -> str:
    """Encode untuk URL yang aman"""
    # Gunakan urlsafe_b64encode dan hilangkan padding
    encoded = base64.urlsafe_b64encode(combined_value.encode()).decode().rstrip("=")
    return encoded

def decode_chat_id(encoded: str) -> str:
    """Decode dari URL-safe base64"""
    # Tambahkan padding jika diperlukan
    padding = len(encoded) % 4
    if padding:
        encoded += "=" * (4 - padding)
    
    try:
        decoded = base64.urlsafe_b64decode(encoded.encode()).decode()
        
        # Validasi format dasar
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
            'spy': [],
            'warga': [],
            'kata_rahasia': None,
            'sedang_berlangsung': False,
            'fase': None,
            'deskripsi_pemain': {},
            'suara': {},
            'tereliminasi': [],
            'skor': {},
            'join_started': False,
            'pending_messages': [],
            'join_message_id': None,
            'jobs': []
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

def pilih_kata():
    # Choose a random category
    kategori = random.choice(list(KATA.keys()))
    
    # Select a random word group from that category
    kelompok_kata = random.choice(KATA[kategori])
    
    # Make a copy of the word group to work with
    kata_kandidat = kelompok_kata.copy()
    
    # Randomly select the civilian word and remove it from candidates
    kata_warga = random.choice(kata_kandidat)
    kata_kandidat.remove(kata_warga)
    
    # Select spy word from remaining words (ensuring it's different)
    kata_spy = random.choice(kata_kandidat) if kata_kandidat else kata_warga  # fallback
    
    return {
        'kategori': kategori,
        'warga': kata_warga, 
        'spy': kata_spy,
        'kelompok_kata': kelompok_kata  # Optional: for reference
    }


def reset_game(chat_id: int, context: CallbackContext = None):
    """Reset game state and cancel all jobs safely"""
    game = get_game(chat_id)
    
    try:
        # Cancel all active jobs
        if context and 'jobs' in game:
            for job_info in game['jobs']:
                try:
                    for job in context.job_queue.get_jobs_by_name(job_info['id']):
                        job.schedule_removal()
                        logger.info(f"Removed job: {job.name}")
                except Exception as e:
                    logger.error(f"Failed to remove job {job_info['id']}: {e}")

        # Clear all pending messages
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

    # Cleanup messages
    for msg_id in game['pending_messages']:
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.error(f"Gagal hapus pesan {msg_id}: {e}")

    game['pending_messages'] = []
    game['join_message_id'] = None
    game['join_started'] = False

    # Start game if enough players
    if len(game['pemain']) >= 3:
        context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Pendaftaran ditutup dengan {len(game['pemain'])} pemain!\n"
                 "⏳ Memulai permainan...",
            parse_mode='Markdown'
        )
        
        # Start game with short delay
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
        # Extract chat_id from job context
        chat_id = context.job.context['chat_id']
        game = get_game(chat_id)
        
        if len(game['pemain']) < 3:
            context.bot.send_message(
                chat_id=chat_id,
                text="❌ Gagal memulai - minimal 3 pemain diperlukan!",
                parse_mode='Markdown'
            )
            reset_game(chat_id)
            return

        # Create simulated Update object (fake_update)
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

        # Call main game function with simulated update
        mulai_permainan(fake_update, context)

    except Exception as e:
        logger.error(f"Error in auto_start_game: {e}")
        context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Gagal memulai permainan secara otomatis. Silakan coba /mulai manual."
        )
        reset_game(chat_id)



def start(update: Update, context: CallbackContext):
    # Jika berasal dari inline join
    if context.args and context.args[0].startswith('join_'):
        join_request(update, context)
        return
    
    # Ambil nama pengguna yang menekan start
    user_name = update.effective_user.first_name or update.effective_user.full_name

    # Teks pesan dengan nama pengguna
    start_text = (
        f"Hai {user_name}! Saya host-bot game tebak spy di grup Telegram. "
        "Tambahkan saya ke grup untuk mulai bermain game tebak spy yang menyenangkan!"
    )

    # Membuat inline keyboard dengan layout 2 atas 1 bawah
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

    if update.effective_chat.id not in ALLOWED_GROUP_IDS:
        update.message.reply_text("❌ Bot sedang dalam pengembangan dan hanya bisa digunakan di grup tertentu!")
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

    # Generate join token with encoded chat_id
    
    timestamp = str(int(time.time()))
    chat_id_str = str(chat_id)
    combined = f"{timestamp}_{chat_id_str}"
    tokenku = encode_chat_id(combined)
    
    # URL encode token untuk jaga-jaga
    safe_token = urllib.parse.quote(tokenku)
    
    keyboard = [[InlineKeyboardButton(
        "🎮 Gabung Permainan", 
        url=f"https://t.me/{context.bot.username}?start=join_{safe_token}"
    )]]
    
    if not game.get('join_message_id'):
        msg = update.message.reply_text(
            f"🎮 *PERMAINAN BARU DI GRUP INI!*\n"
            "⏱️ Waktu bergabung: 50 detik\n"
            "👥 Pemain: 0/8\n\n"
            "Klik tombol di bawah untuk bergabung:",
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
                text=f"🎮 *PERMAINAN BARU DI GRUP INI!*\n"
                     "⏱️ Waktu bergabung: 50 detik\n"
                     f"👥 Pemain: {len(game['pemain'])}/8\n\n"
                     "Klik tombol di bawah untuk bergabung:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Gagal update pesan gabung: {e}")

    # Cancel existing timers
    for job in game.get('jobs', []):
        job.schedule_removal()
    game['jobs'] = []

    # Schedule new timers
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

     # Schedule auto start game
    start_job = context.job_queue.run_once(
        auto_start_game,
        52,  # 2 detik setelah timer gabung selesai
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
            
        # Ambil bagian encoded setelah join_
        encoded_token = context.args[0][5:]
        
        # Decode and parse token components
        decoded_value = decode_chat_id(encoded_token)
        timestamp_str, chat_id_str = decoded_value.split('_')
        
        # Validate types
        timestamp = int(timestamp_str)
        chat_id = int(chat_id_str)
  
        # Validate token time (15 minute window)
        if abs(time.time() - timestamp) > 900:
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

    if len(game['pemain']) >= 8:
        update.message.reply_text("😞 Pemain sudah penuh (8/8)!")
        return

    game['pemain'].append({'id': user_id, 'nama': username})
    
    chat = context.bot.get_chat(chat_id)
    group_name = chat.title if chat.title else "grup ini"
        
    update.message.reply_text(
        f"Kamu berhasil bergabung di *{group_name}*\n"
        f"Sekarang ada *{len(game['pemain'])}/8 pemain.*",
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
        
    # Edit pesan join request
    try:
    	
    	timestamp_new = str(int(time.time()))
        chat_id_str_new = str(chat_id)
        combined_new = f"{timestamp_new}_{chat_id_str_new}"
        tokenku = encode_chat_id(combined_new)
        safe_token = urllib.parse.quote(tokenku)
        
        
        context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=game['join_message_id'],
            text=f"🎮 *PERMAINAN BARU DI GRUP INI!*\n"
                 "⏱️ Waktu bergabung: 50 detik\n"
                 f"👥 Pemain: {len(game['pemain'])}/8\n\n"
                 "Klik tombol di bawah untuk bergabung:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🎮 Gabung Sekarang",
                    url=f"https://t.me/{context.bot.username}?start=join_{safe_token}}"
                )
            ]]),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Gagal update pesan gabung: {e}")

    # Cek jika pemain sudah penuh
    try:      
        if len(game['pemain']) == 8:
            cancel_all_jobs(chat_id, context.job_queue)
            mulai_permainan(update, context)
    except Exception as e:
        logger.error(f"Gagal mulai Game: {e}")

          
def mulai_permainan(update: Update, context: CallbackContext):
    if update.effective_chat.type == 'private':
        update.message.reply_text("❌ Hanya bisa dilakukan di grup!")
        return

    chat_id = update.effective_chat.id
    game = get_game(chat_id)

    # Batalkan semua job yang masih berjalan
    cancel_all_jobs(chat_id, context.job_queue)
    
    if game['sedang_berlangsung']:
        #update.message.reply_text("🔄 Permainan masih berjalan!")
        return

    jumlah_pemain = len(game['pemain'])
    
    if jumlah_pemain < 3:
        update.message.reply_text(
            "❌ Minimal 3 pemain untuk memulai!\n"
            f"Pemain saat ini: {jumlah_pemain}/3"
        )
        return
    
    # Reset game state
    game.update({
        'spy': [],
        'warga': [],
        'kata_rahasia': None,
        'sedang_berlangsung': True,
        'fase': None,
        'deskripsi_pemain': {},
        'suara': {},
        'tereliminasi': [],
        'skor': {},
        'message_id': None,
        'round': 1 
    })

    # Determine number of spies
    num_spies = 1 if jumlah_pemain <= 6 else 2
    
    # Select spies randomly
    all_players = game['pemain'].copy()
    random.shuffle(all_players)
    game['spy'] = all_players[:num_spies]
    game['warga'] = all_players[num_spies:]

    # Select secret word
 
    kata_rahasia = pilih_kata()
    game['kata_rahasia'] = {
        'warga': kata_rahasia['warga'],
        'spy': kata_rahasia['spy'],
        'kategori': kata_rahasia['kategori'],
        'kelompok_kata': kata_rahasia['kelompok_kata']  # Optional: for debugging
    }


    # Send roles to players privately
    for pemain in game['pemain']:
        try:
            if pemain in game['spy']:
                role_text = (
                    f"*Kosa-katamu adalah:*\n\n"                    
                    f"*{game['kata_rahasia']['spy']}*\n\n"
                    "Silakan deskripsikan kata ini tanpa menyebutkan kata langsung!"
                )
            else:
                role_text = (
                    f"*Kosa-katamu adalah:*\n\n"
                    f"*{game['kata_rahasia']['warga']}*\n\n"
                    "Silakan deskripsikan kata ini tanpa menyebutkan kata langsung!"
                )
            
            context.bot.send_message(
                chat_id=pemain['id'],
                text=role_text,
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

    # Info to group
    msg = update.message.reply_text(
        f"*Putaran deskripsi ke-{game['round']} dimulai, silakan mulai deskripsi pada waktu yang sama.*\n\n"
        "*Peran sudah dibagikan!*\n"
        f"Spy: {len(game['spy'])} orang | Warga: {len(game['warga'])} orang\n\n"
        "⏳ *Fase Deskripsi dimulai!*\n"
        "Kirim deskripsi kata Anda via chat privat ke bot ini (waktu 40 detik).",
        parse_mode='Markdown'
    )

    game['fase'] = 'deskripsi'
    game['message_id'] = msg.message_id
    
    # Description phase timer
    context.job_queue.run_once(
        lambda ctx: akhir_deskripsi(ctx, chat_id),
        40,
        context=chat_id,
        name=f"deskripsi_{chat_id}"
    )


def akhir_deskripsi(context: CallbackContext, chat_id):
    game = get_game(chat_id)
    
    if not game['sedang_berlangsung'] or game['fase'] != 'deskripsi':
        return

    # Check for missing descriptions
    belum_kirim = []
    for pemain in game['pemain']:
        if pemain['id'] not in game['deskripsi_pemain'] and pemain not in game['tereliminasi']:
            belum_kirim.append(pemain['nama'])
            game['deskripsi_pemain'][pemain['id']] = "❌ [Tidak memberikan deskripsi]"
            
            try:
                context.bot.send_message(
                    chat_id=pemain['id'],
                    text="⏰ *Oops!* Waktu deskripsi habis!\n"
      	                   "*➖ Tetap lanjutkan permainan! ➖*",
     	           parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"Gagal mengirim notifikasi ke {pemain['nama']}: {e}")

    
    hasil_deskripsi = []
    for pemain in game['pemain']:
        if pemain['id'] in game['deskripsi_pemain']:
            hasil_deskripsi.append(
                f"▪️ {pemain['nama']}: {game['deskripsi_pemain'][pemain['id']]}"
            )

    # Show descriptions to group
    try:
        if game['message_id']:            
            context.bot.send_message(
                chat_id=chat_id,
                text="*Hasil Deskripsi:*\n" + "\n".join(hasil_deskripsi),
                parse_mode='Markdown'
            )
        else:
            game['message_id'] = context.bot.send_message(
                chat_id=chat_id,
                text="*Hasil Deskripsi:*\n" + "\n".join(hasil_deskripsi),
                parse_mode='Markdown'
            ).message_id
    except Exception as e:
        logger.error(f"Gagal edit/send pesan deskripsi: {e}")
        game['message_id'] = None

    # Start voting phase
    game['fase'] = 'voting'
    pemain_aktif = [p for p in game['pemain'] if p not in game['tereliminasi']]
    
    if len(pemain_aktif) < 2:
        cek_pemenang(context, chat_id)
        return
    
    time.sleep(5)  # Delay 5 detik
    
    # Create vertical voting buttons
    keyboard = []
    for p in pemain_aktif:
        btn_text = f"{p['nama']} (0)"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"vote_{p['id']}")])

    try:
        if game['message_id']:
            msg = context.bot.send_message(
                chat_id=chat_id,
                text="🗳️ *Fase Voting!*\nPilih siapa yang menurutmu Spy!\nWaktu: 40 detik.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            game['message_id'] = msg.message_id
    except Exception as e:
        logger.error(f"Gagal kirim pesan voting: {e}")
        return

    # Voting timer
    context.job_queue.run_once(
        lambda ctx: akhir_voting(ctx, chat_id),
        40,
        context=chat_id,
        name=f"voting_{chat_id}"
    )


def handle_vote(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        voter_id = query.from_user.id
        chat_id = query.message.chat.id
        game = get_game(chat_id)
        
        is_active_player = any(
            p['id'] == voter_id 
            for p in game['pemain'] 
            if p not in game['tereliminasi']
        )
        
        if not is_active_player:
            query.answer(
                text="❌ Hanya pemain yang sedang bermain boleh voting!",
                show_alert=True,
                cache_time=10
            )
            return


        # [1. Validasi State Game - TIDAK DIUBAH]
        if not game.get('sedang_berlangsung') or game.get('fase') != 'voting':
            query.answer(text="❌ Waktu voting sudah habis!", show_alert=False)
            return

        # [2. Cek Pemain Tereliminasi - TIDAK DIUBAH]
        if any(voter_id == p['id'] for p in game.get('tereliminasi', [])):
            query.answer(text="❌ Kamu sudah tereliminasi!", show_alert=False, cache_time=5)
            return

        # [3. Blokir Pemain Terlibat Seri - TIDAK DIUBAH]
        if 'pemain_terlibat_seri' in game and voter_id in game['pemain_terlibat_seri']:
            query.answer(text="⚠️ Kamu tidak boleh  melakukan vote!", show_alert=False)
            return

        # [4. Cek Sudah Vote - TIDAK DIUBAH]
        if voter_id in game.get('suara', {}):
            current_choice = game['suara'][voter_id].get('nama', 'unknown')
            query.answer(text=f"⚠️ Kamu sudah memilih {current_choice}!", show_alert=False, cache_time=4)
            return

        # [5. Parse Callback - TIDAK DIUBAH]
        try:
            _, player_id_str = query.data.split('_')
            player_id = int(player_id_str)
        except (ValueError, AttributeError) as e:
            logger.error(f"Invalid callback data: {query.data}")
            query.answer(text="❌ Invalid vote data!", show_alert=False)
            return

        # [6. Cegah Vote Diri Sendiri - TIDAK DIUBAH]
        if voter_id == player_id:
            query.answer(text="❌ Tidak boleh memilih diri sendiri!", show_alert=False)
            return

        # [7. Cari Pemain Target - TIDAK DIUBAH]
        terpilih = next(
            (p for p in game.get('pemain', []) 
             if p.get('id') == player_id and p not in game.get('tereliminasi', [])), 
            None
        )
        
        if not terpilih:
            query.answer(text="❌ Pemain tidak valid!", show_alert=False, cache_time=3)
            return

        # [8. Rekam Vote - TIDAK DIUBAH]
        game.setdefault('suara', {})[voter_id] = terpilih
        
        ##### [9. MODIFIKASI: Filter Pemain yang Ditampilkan] #####
        # Daftar pemain aktif (belum tereliminasi)
        active_players = [p for p in game['pemain'] if p not in game.get('tereliminasi', [])]
        
        # Jika sedang revote, filter hanya pemain yang seri
        if 'pemain_terlibat_seri' in game:
            active_players = [p for p in active_players if p['id'] in game['pemain_terlibat_seri']]
        ##### END MODIFIKASI #####

        # [10. Hitung Suara - DIUBAH untuk filter aktif_players]
        vote_count = {p['id']: 0 for p in active_players}
        for v in game.get('suara', {}).values():
            if v and 'id' in v and v['id'] in vote_count:
                vote_count[v['id']] += 1

        # [11. Bangun Keyboard - DIUBAH untuk filter aktif_players]
        keyboard = []
        for p in active_players:  # Gunakan active_players bukan game['pemain']
            count = vote_count.get(p['id'], 0)
            btn_text = f"{p.get('nama', 'Unknown')} ({count})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"vote_{p['id']}")])

        # [12. Update Tampilan - TIDAK DIUBAH]
        try:
            query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            query.answer(text=f"✅ Kamu memilih {terpilih.get('nama', 'unknown')}!", show_alert=False)
        except Exception as e:
            logger.error(f"Error updating buttons: {e}")
            query.answer(text="❌ Gagal memperbarui pilihan.", show_alert=False)

    except Exception as e:
        logger.error(f"Error in handle_vote: {e}")
        try:
            query.answer(text="❌ Terjadi kesalahan saat voting!", show_alert=False)
        except:
            pass



#  ini buat voting

def akhir_voting(context: CallbackContext, chat_id):
    try:
        game = get_game(chat_id)
        
        if not game.get('sedang_berlangsung') or game.get('fase') != 'voting':
            return

        # 1. Hitung hasil voting
        hasil_voting = {p['id']: {'nama': p['nama'], 'suara': 0, 'id': p['id']} 
                       for p in game['pemain'] if p not in game['tereliminasi']}
        
        for v in game['suara'].values():
            if v and v['id'] in hasil_voting:
                hasil_voting[v['id']]['suara'] += 1

        # 2. Cek jika semua pemain seri (tidak ada yang memilih)
        total_suara = sum(v['suara'] for v in hasil_voting.values())
        if total_suara == 0:
            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=game['message_id'],
                text="🤷 *Tidak ada yang memilih!*\nTidak ada pemain yang tereliminasi.",
                parse_mode='Markdown'
            )
            
            # Lanjutkan ke putaran berikutnya
            game['round'] += 1
            game['fase'] = 'deskripsi'
            game['deskripsi_pemain'] = {}
            game['suara'] = {}
            
            context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"*Putaran deskripsi ke-{game['round']} dimulai, silakan mulai deskripsi pada waktu yang sama.*\n\n"
                    "*Peran sudah dibagikan!*\n"
                    f"Spy: {len([s for s in game['spy'] if s not in game['tereliminasi']])} orang | "
                    f"Warga: {len([w for w in game['warga'] if w not in game['tereliminasi']])} orang\n\n"
                    "⏳ *Fase Deskripsi dimulai!*\n"
                    "Kirim deskripsi kata Anda via chat privat ke bot ini (waktu 40 detik)."
                ),
                parse_mode='Markdown'
            )
            
            # New description phase timer
            context.job_queue.run_once(
                lambda ctx: akhir_deskripsi(ctx, chat_id),
                40,
                context=chat_id,
                name=f"deskripsi_{chat_id}"
            )
            return

        ranking = sorted(hasil_voting.values(), key=lambda x: x['suara'], reverse=True)

        # 3. Tampilkan hasil
        hasil_text = "📊 *Hasil Voting:*\n" + "\n".join([f"• {p['nama']}: {p['suara']} suara" for p in ranking])
        context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=game['message_id'],
            text=hasil_text,
            parse_mode='Markdown'
        )

        # 4. Handle hasil seri (jika ada suara tapi jumlah suara sama)
        if len(ranking) > 1 and ranking[0]['suara'] == ranking[1]['suara']:
            pemain_seri = [p for p in ranking if p['suara'] == ranking[0]['suara']]
            nama_seri = ", ".join([p['nama'] for p in pemain_seri])
            
            # 4a. Simpan ID pemain yang seri (tidak boleh vote)
            game['pemain_terlibat_seri'] = [p['id'] for p in pemain_seri]
            
            # 4b. Kirim notifikasi
            context.bot.send_message(
                chat_id=chat_id,
                text=f"🤝 *Hasil seri!* ({nama_seri})\n"
                     "🗳️ Voting ulang\n"
                     f"⏱ Waktu: 30 detik",
                parse_mode='Markdown'
            )

            # 4c. Siapkan voting ulang
            keyboard = [[InlineKeyboardButton(p['nama'], callback_data=f"vote_{p['id']}")] for p in pemain_seri]
            
            vote_msg = context.bot.send_message(
                chat_id=chat_id,
                text="Pilih salah satu yang akan dieliminasi:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            game['message_id'] = vote_msg.message_id
            game['suara'] = {}  # Reset suara

            # 4d. Timer voting ulang
            context.job_queue.run_once(
                lambda ctx: akhir_voting(ctx, chat_id),
                30,
                context=chat_id,
                name=f"revote_{chat_id}"
            )
            return

        # 5. Lanjutkan eliminasi jika tidak seri
        tereliminasi = next((p for p in game['pemain'] 
                           if p['id'] == ranking[0]['id'] and p not in game['tereliminasi']), None)
        
        if tereliminasi:
            game['tereliminasi'].append(tereliminasi)
            role = "🕵️ Spy" if tereliminasi in game['spy'] else "👨 Warga"
            context.bot.send_message(
                chat_id=chat_id,
                text=f"*{tereliminasi['nama']} dipilih*, dia adalah {role}",
                parse_mode='Markdown'
            )

        # 6. Cek pemenang
        cek_pemenang(context, chat_id)

    except Exception as e:
        logger.error(f"Error in akhir_voting: {e}")
        context.bot.send_message(chat_id, "⚠️ Error processing voting")

def cek_pemenang(context: CallbackContext, chat_id):
    game = get_game(chat_id)
    
    # Count remaining players and spies
    pemain_aktif = [p for p in game['pemain'] if p not in game['tereliminasi']]
    jumlah_pemain = len(pemain_aktif)
    jumlah_spy = len([s for s in game['spy'] if s not in game['tereliminasi']])  # Only count alive spies

    if jumlah_pemain == 0:
        # Special case if all eliminated
        teks = "🤷 *Permainan berakhir tanpa pemenang!*\nSemua pemain tereliminasi."
    elif jumlah_spy >= (jumlah_pemain - jumlah_spy):  # Spies win
        teks = f"* Permainan Berakhir!*\nTim pemenang: *Spy*\n\n"
        teks += "*Pemenang:*\n"
        
        # First show winning spies
        for pemain in game['pemain']:
            if pemain in game['spy'] and pemain not in game['tereliminasi']:
                game['skor'][pemain['id']] = game['skor'].get(pemain['id'], 0) + 20
                teks += f"- {pemain['nama']} : 🕵️ Spy\n"
        
        teks += "\n*Pemain lain:*\n"
        # Then show other players
        for pemain in game['pemain']:
            if pemain not in game['spy'] or pemain in game['tereliminasi']:
                game['skor'][pemain['id']] = game['skor'].get(pemain['id'], 0) + 5
                role = "🕵️ Spy" if pemain in game['spy'] else "👨🏼 Warga"
                teks += f"- {pemain['nama']} : {role}\n"
                
        
        teks += f"\n*Kata Warga:* {game['kata_rahasia']['warga']}\n"
        teks += f"*Kata Spy:* {game['kata_rahasia']['spy']}\n"
                
    elif jumlah_spy == 0:  # Villagers win
        teks = f"* Permainan Berakhir!*\nTim pemenang: *Warga*\n\n"
        teks += "*Pemenang:*\n"
        
        # First show winning villagers
        for pemain in game['pemain']:
            if pemain not in game['spy'] and pemain not in game['tereliminasi']:
                game['skor'][pemain['id']] = game['skor'].get(pemain['id'], 0) + 20
                teks += f"- {pemain['nama']} : 👨🏼 Warga\n"
        
        teks += "\n*Pemain lain:*\n"
        # Then show other players
        for pemain in game['pemain']:
            if pemain in game['spy'] or pemain in game['tereliminasi']:
                game['skor'][pemain['id']] = game['skor'].get(pemain['id'], 0) + 5
                role = "🕵️ Spy" if pemain in game['spy'] else "👨🏼 Warga"
                teks += f"- {pemain['nama']} : {role}\n"
                
        teks += f"\n*Kata Warga:* {game['kata_rahasia']['warga']}\n"
        teks += f"*Kata Spy:* {game['kata_rahasia']['spy']}\n"
                
    else:  # Continue to next round
        game['round'] += 1  # Increment round counter
        game['fase'] = 'deskripsi'
        game['deskripsi_pemain'] = {}
        game['suara'] = {}
        
        context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"*Putaran deskripsi ke-{game['round']} dimulai, silakan mulai deskripsi pada waktu yang sama.*\n\n"
                "*Peran sudah dibagikan!*\n"
                f"Spy: {len([s for s in game['spy'] if s not in game['tereliminasi']])} orang | "
                f"Warga: {len([w for w in game['warga'] if w not in game['tereliminasi']])} orang\n\n"
                "⏳ *Fase Deskripsi dimulai!*\n"
                "Kirim deskripsi kata Anda via chat privat ke bot ini (waktu 40 detik)."
            ),
            parse_mode='Markdown'
        )
        
        
        # New description phase timer
        context.job_queue.run_once(
            lambda ctx: akhir_deskripsi(ctx, chat_id),
            40,
            context=chat_id,
            name=f"deskripsi_{chat_id}"
        )
        return

    # If game ended
    context.bot.send_message(
        chat_id=chat_id,
        text=teks,
        parse_mode='Markdown'
    )
    reset_game(chat_id)

    
    
 
def handle_deskripsi(update: Update, context: CallbackContext):
    if update.effective_chat.type != 'private':
        return

    player_id = update.effective_user.id
    deskripsi = update.message.text
    
    # Find active game with this player
    for chat_id in games:
        game = games[chat_id]
        if game['sedang_berlangsung'] and game['fase'] == 'deskripsi':
            if any(p['id'] == player_id for p in game['pemain'] if p not in game['tereliminasi']):
                game['deskripsi_pemain'][player_id] = deskripsi
                update.message.reply_text("✅ Deskripsi kamu sudah tercatat!")
                return
    
    #update.message.reply_text("ℹ️ Tidak ada permainan yang membutuhkan deskripsi darimu.")

def cancel_game(update: Update, context: CallbackContext):
    if update.effective_chat.type == 'private':
        update.message.reply_text("❌ Hanya bisa dilakukan di grup!")
        return

    chat_id = update.effective_chat.id
    game = get_game(chat_id)
    
    if not game['sedang_berlangsung']:
        update.message.reply_text("❌ Tidak ada permainan yang berjalan!")
        return

    # Remove all related jobs
    current_jobs = context.job_queue.get_jobs_by_name(f"deskripsi_{chat_id}")
    current_jobs += context.job_queue.get_jobs_by_name(f"voting_{chat_id}")
    
    for job in current_jobs:
        job.schedule_removal()
    
    reset_game(chat_id)
    update.message.reply_text("🔴 Permainan dibatalkan!")

def daftar_pemain(update: Update, context: CallbackContext):
    if update.effective_chat.type == 'private':
        update.message.reply_text("❌ Hanya bisa dilakukan di grup!")
        return

    chat_id = update.effective_chat.id
    game = get_game(chat_id)
    
    if not game['pemain']:
        update.message.reply_text("Belum ada pemain yang bergabung!")
        return
    
    daftar = "\n".join([f"{i+1}. {p['nama']}" for i, p in enumerate(game['pemain'])])
    update.message.reply_text(
        f"Daftar Pemain ({len(game['pemain'])} orang):\n{daftar}"
    )

def error_handler(update: Update, context: CallbackContext):
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
    dp.add_handler(CommandHandler("player", daftar_pemain))
    
    # Message handlers
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command & Filters.chat_type.private, handle_deskripsi))
    
    # Callback handlers
    dp.add_handler(CallbackQueryHandler(handle_vote, pattern=r"^vote_\d+$"))
    
    # Error handler
    dp.add_error_handler(error_handler)

    # Start bot
    updater.start_polling()
    updater.idle()

@app.route('/')
def home():
    return "Bot Tebak Spy sedang aktif!"

if __name__ == '__main__':
    # Run Telegram bot in separate thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    # Run Flask
    app.run(host='0.0.0.0', port=8000)
