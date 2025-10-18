import telebot
from telebot import types
import yt_dlp
import os
import time
import subprocess
import sqlite3 # Ma'lumotlar bazasi uchun

# --- 1. KONFIGURATSIYA VA XAVFSIZLIK ---
# BOT_TOKEN va ADMIN_ID ni Render'ning Environment Variables (Atrof-muhit o'zgaruvchilari) orqali yuklash
TOKEN = os.environ.get('BOT_TOKEN') 
ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))

if not TOKEN:
    raise ValueError("BOT_TOKEN atrof-muhit o'zgaruvchisi topilmadi!")

bot = telebot.TeleBot(TOKEN)
DOWNLOAD_DIR = 'downloads'
DB_NAME = 'bot_data.db'

# Watermark Konfiguratsiyasi
WATERMARK_TEXT = '@podshox_bot'
# Render uchun shrift yo'li (agar FFmpeg to'g'ri o'rnatilsa)
FONT_FILE_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' 
FONT_SIZE = 30
FONT_COLOR = 'white'
TEXT_BORDER = 'black'
POSITION_X = 15 
POSITION_Y = 'H-h-15' 

# Cooldown (Sovutish) mexanizmi
user_cooldowns = {}
COOLDOWN_TIME = 5 

# Botning holatini saqlovchi global o'zgaruvchilar
BOT_STATUS = {
    'watermark_enabled': True, 
    'maintenance_mode': False
}

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# --- 2. MA'LUMOTLAR BAZASI (SQLITE) FUNKSIYALARI ---

def init_db():
    """Ma'lumotlar bazasini yaratadi."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, added_at TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()

def load_settings():
    """DB'dan sozlamalarni yuklaydi."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for key, default_val in BOT_STATUS.items():
        cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
        val = cursor.fetchone()
        if val:
            # DB'dan olingan qiymatni boolean ga aylantirish
            BOT_STATUS[key] = val[0] == 'True'
        else:
            cursor.execute("INSERT INTO settings VALUES (?, ?)", (key, str(default_val)))
    conn.commit()
    conn.close()

def update_setting(key, value):
    """Sozlamalarni DB'da yangilaydi."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value=? WHERE key=?", (str(value), key))
    conn.commit()
    conn.close()
    
def add_user(user_id):
    """Yangi foydalanuvchini DB'ga qo'shadi."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users VALUES (?, datetime('now'))", (user_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()
    
# --- 3. YORDAMCHI FUNKSIYALAR ---

def draw_progress_bar(progress):
    """Foiz qiymatiga asoslanib, progress bar chizadi."""
    bar_length = 20
    filled_length = int(bar_length * progress // 100)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    return f"[{bar}] {progress:.1f}%"

def check_cooldown(user_id):
    """Spamdan himoyalanish uchun so'rovlar orasidagi vaqtni tekshiradi."""
    last_time = user_cooldowns.get(user_id, 0)
    current_time = time.time()
    if current_time - last_time < COOLDOWN_TIME:
        return False, COOLDOWN_TIME - int(current_time - last_time)
    user_cooldowns[user_id] = current_time
    return True, 0

def progress_hook(d, bot, chat_id, message_id):
    """yt-dlp uchun progress bar ni Telegramda yangilaydi."""
    if d['status'] == 'downloading':
        if d.get('total_bytes') or d.get('total_bytes_estimate'):
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            
            if total > 0:
                progress = (downloaded / total) * 100
            else:
                progress = 0
            
            progress_bar = draw_progress_bar(progress)
            speed = d.get('speed')
            
            current_time = time.time()
            if not hasattr(progress_hook, 'last_update') or current_time - progress_hook.last_update > 2:
                
                status_text = (
                    "📥 **Yuklanmoqda...**\n"
                    f"{progress_bar}\n"
                    f"⚡ Tezlik: {f'{speed/1024:.1f} KiB/s' if speed else '...'}"
                )
                
                try:
                    bot.edit_message_text(status_text, chat_id, message_id, parse_mode='Markdown')
                    progress_hook.last_update = current_time
                except:
                    pass
        
# --- 4. TELEGRAM HANDLERLAR (Admin va Foydalanuvchi) ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    add_user(message.from_user.id)
    welcome_text = (
        "👋 **Xush kelibsiz!**\n\n"
        "📹 **Foydalanish usuli:** Menga to'g'ridan-to'g'ri video linkini (URL) yuboring."
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

# Admin buyruqlarini qayta ishlash uchun alohida funksiya
def handle_admin_commands(message):
    chat_id = message.chat.id
    command = message.text.split()[0]

    # --- /stats ---
    if command == '/stats':
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        conn.close()
        
        wm_status = "✅ Yoqilgan" if BOT_STATUS['watermark_enabled'] else "❌ O'chirilgan"
        
        stats_text = (
            "📊 **Bot Statistikasi**\n"
            "-------------------------\n"
            f"👤 **Jami foydalanuvchilar:** {user_count}\n"
            f"💧 **Watermark holati:** {wm_status}\n"
            f"🛠 **Maintenance holati:** {'🛑 YOQILGAN' if BOT_STATUS['maintenance_mode'] else '🟢 O\'CHIRILGAN'}\n"
        )
        bot.send_message(chat_id, stats_text, parse_mode='Markdown')

    # --- /watermark_on / /watermark_off ---
    elif command in ['/watermark_off', '/watermark_on']:
        is_on = command == '/watermark_on'
        BOT_STATUS['watermark_enabled'] = is_on
        update_setting('watermark_enabled', is_on)
        status = "YOQILDI" if is_on else "O'CHIRILDI"
        bot.send_message(chat_id, f"💧 Watermark qo'shish funksiyasi muvaffaqiyatli **{status}**.")
    
    # --- /maintenance_on / /maintenance_off ---
    elif command in ['/maintenance_on', '/maintenance_off']:
        is_on = command == '/maintenance_on'
        BOT_STATUS['maintenance_mode'] = is_on
        update_setting('maintenance_mode', is_on)
        status = "YOQILDI" if is_on else "O'CHIRILDI"
        bot.send_message(chat_id, f"🛠 Texnik xizmat ko'rsatish rejimi muvaffaqiyatli **{status}**.")
        
    # --- /broadcast ---
    elif command == '/broadcast':
        try:
            message_to_send = message.text.split(' ', 1)[1]
        except IndexError:
            bot.send_message(chat_id, "⚠️ Foydalanish: `/broadcast Xabar matni`")
            return
            
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
        conn.close()
        
        sent_count = 0
        
        bot.send_message(chat_id, f"📢 **{len(users)}** ta foydalanuvchiga xabar yuborilmoqda...")
        
        for user in users:
            try:
                bot.send_message(user[0], message_to_send, parse_mode='Markdown')
                sent_count += 1
            except:
                pass 
                
        bot.send_message(chat_id, f"✅ **{sent_count}** ta foydalanuvchiga xabar muvaffaqiyatli yetkazildi.")


@bot.message_handler(func=lambda message: True)
def process_all_messages(message):
    user_id = message.from_user.id
    
    add_user(user_id)
    
    # Maintenance tekshiruvi
    if BOT_STATUS['maintenance_mode'] and user_id != ADMIN_ID:
        bot.reply_to(message, "🛠 **Kechirasiz.** Bot hozirda texnik xizmat ko'rsatish rejimida. Bir ozdan keyin urinib ko'ring.")
        return
    
    # Admin buyruqlarini qayta ishlash
    if message.text.startswith('/') and user_id == ADMIN_ID:
        handle_admin_commands(message)
    # URL ni qabul qilish va sifat tanlash
    elif not message.text.startswith('/'):
        handle_url_for_selection(message)

def handle_url_for_selection(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    url = message.text

    # Cooldown tekshiruvi
    is_ready, remaining_time = check_cooldown(user_id)
    if not is_ready:
        bot.send_message(chat_id, f"⚠️ **Iltimos kuting!** {remaining_time} sekunddan keyin urinib ko'ring.")
        return

    # Inline Keyboard yaratish
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("📽️ Yaxshi Sifat (720p)", callback_data=f"best_720|{url}"),
        types.InlineKeyboardButton("📱 O'rta Sifat (360p)", callback_data=f"medium_360|{url}")
    )
    keyboard.add(
        types.InlineKeyboardButton("🔊 Faqat Audio (MP3)", callback_data=f"audio_only|{url}")
    )

    bot.send_message(
        chat_id,
        "Qaysi sifatda yuklab olmoqchisiz?",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    chat_id = call.message.chat.id
    
    try:
        format_code, url = call.data.split('|', 1)
    except ValueError:
        bot.send_message(chat_id, "❌ Ma'lumotni qayta ishlashda xatolik yuz berdi.")
        return

    # Sifat tanlovi
    ydl_format = 'bestvideo[height<=720]+bestaudio/best' if format_code == 'best_720' else \
                 'bestvideo[height<=360]+bestaudio/best' if format_code == 'medium_360' else \
                 'bestaudio/best'
    max_size_limit = 50 * 1024 * 1024 # Telegram cheklovi

    processing_message = bot.edit_message_text(
        "⏳ **Tayyorlanmoqda...**", 
        chat_id, 
        call.message.message_id
    )
    
    input_file_path = None
    output_file_path = None
    file_path_to_send = None

    try:
        # 1. Yuklab olish (yt-dlp)
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_DIR, 'input_%(id)s.%(ext)s'),
            'format': ydl_format,
            'max_filesize': max_size_limit, 
            'noplaylist': True,
            'progress_hooks': [lambda d: progress_hook(d, bot, chat_id, processing_message.message_id)],
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}] if format_code == 'audio_only' else [],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            progress_hook.last_update = time.time() 
            info = ydl.extract_info(url, download=True)
            input_file_path = ydl.prepare_filename(info)

        bot.edit_message_text("✅ **Yuklab olish yakunlandi.** Endi qayta ishlanmoqda (Watermark).", chat_id, processing_message.message_id)
            
        # 2. Watermark Qo'shish (FFmpeg)
        if format_code != 'audio_only' and BOT_STATUS['watermark_enabled']: 
            
            output_file_path = os.path.join(DOWNLOAD_DIR, 'output_' + os.path.basename(input_file_path))
            
            ffmpeg_command = [
                'ffmpeg',
                '-i', input_file_path,
                '-vf', 
                f"drawtext=fontfile='{FONT_FILE_PATH}':text='{WATERMARK_TEXT}':"
                f"fontsize={FONT_SIZE}:fontcolor={FONT_COLOR}:box=1:boxcolor={TEXT_BORDER}@0.7:"
                f"x={POSITION_X}:y={POSITION_Y}",
                '-c:a', 'copy',
                '-y',
                output_file_path
            ]
            
            subprocess.run(ffmpeg_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            file_path_to_send = output_file_path
            
            if os.path.exists(input_file_path):
                os.remove(input_file_path)

        else:
            file_path_to_send = input_file_path
            
        # 3. Yuklab olingan faylni Telegramga yuborish
        if os.path.exists(file_path_to_send):
            with open(file_path_to_send, 'rb') as media_file:
                caption = f"✅ **Muvaffaqiyatli yuklandi!**\nTitle: `{info.get('title', 'Noma\'lum')}`"
                
                if format_code == 'audio_only':
                    bot.send_audio(chat_id, media_file, caption=caption, title=info.get('title', 'Audio'))
                else:
                    bot.send_video(chat_id, media_file, caption=caption, supports_streaming=True)
        else:
             bot.send_message(chat_id, "❌ **Xatolik!** Fayl topilmadi.")

    except Exception as e:
        error_message = f"❌ **Kechirasiz, xatolik yuz berdi.**\nSababi: `{str(e)[:150]}...`"
        bot.send_message(chat_id, error_message, parse_mode='Markdown')

    finally:
        # 4. Vaqtincha fayllarni o'chirish
        bot.delete_message(chat_id, call.message.message_id)
        if input_file_path and os.path.exists(input_file_path):
            os.remove(input_file_path)
        if output_file_path and os.path.exists(output_file_path):
            os.remove(output_file_path)

# --- 5. BOTNI ISHGA TUSHIRISH ---

if __name__ == '__main__':
    init_db()       
    load_settings()
    print("Bot ishga tushdi...")
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"Bot ishga tushishida xatolik: {e}")
                                                                  
