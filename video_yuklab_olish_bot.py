import telebot
from telebot import types
import yt_dlp
import os
import time
import subprocess
# SQLite/Fayl tizimi muammosini hal qilish uchun quyidagi importlar qo'shildi
import random
import string
import json 
import datetime

# --- 1. KONFIGURATSIYA VA XAVFSIZLIK ---
# Environment Variables orqali TOKEN va ADMIN_ID ni yuklash
TOKEN = os.environ.get('BOT_TOKEN') 
try:
    ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))
except ValueError:
    ADMIN_ID = 0

if not TOKEN:
    raise ValueError("BOT_TOKEN atrof-muhit o'zgaruvchisi topilmadi!")

bot = telebot.TeleBot(TOKEN)
DOWNLOAD_DIR = 'downloads'
SETTINGS_FILE = 'bot_settings.json' # DB o'rniga oddiy JSON fayl (ma'lumotlar yo'qolishi mumkin)
USER_FILE = 'users.json' # Foydalanuvchilar ro'yxati

# Watermark Konfiguratsiyasi
WATERMARK_TEXT = '@podshox_bot'
# Render uchun shrift yo'li (Debian asosidagi image da joylashgan)
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
USER_DATA = {}

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# --- 2. MA'LUMOTLARNI SAQLASH (Faqat Render Worker uchun vaqtinchalik yechim) ---

def load_data():
    """Sozlamalar va foydalanuvchilarni fayllardan yuklaydi."""
    global BOT_STATUS, USER_DATA
    # Sozlamalar
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            data = json.load(f)
            # JSON'dan yuklangan qiymatlarni Boolean'ga aylantirish
            for key, val in data.items():
                if key in BOT_STATUS:
                    BOT_STATUS[key] = val
    
    # Foydalanuvchilar
    if os.path.exists(USER_FILE):
        with open(USER_FILE, 'r') as f:
            USER_DATA = json.load(f)

def save_settings():
    """Sozlamalarni faylga saqlaydi."""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(BOT_STATUS, f)

def save_users():
    """Foydalanuvchilarni faylga saqlaydi."""
    with open(USER_FILE, 'w') as f:
        json.dump(USER_DATA, f)

def add_user(user_id):
    """Yangi foydalanuvchini ro'yxatga qo'shadi."""
    user_id_str = str(user_id)
    if user_id_str not in USER_DATA:
        USER_DATA[user_id_str] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_users() # Har bir qo'shishdan keyin saqlash

# --- 3. YORDAMCHI FUNKSIYALAR ---

def generate_random_id(length=8):
    """Fayl nomlari uchun tasodifiy ID yaratadi."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

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
            
            # Yangilanishni har 2 sekundda bir marta cheklash
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
                except telebot.apihelper.ApiTelegramException as e:
                    # Agar xabar o'chirilgan bo'lsa yoki o'zgarishsiz bo'lsa, e'tibor bermaslik
                    if "message is not modified" not in str(e):
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
        user_count = len(USER_DATA)
        
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
        save_settings()
        status = "YOQILDI" if is_on else "O'CHIRILDI"
        bot.send_message(chat_id, f"💧 Watermark qo'shish funksiyasi muvaffaqiyatli **{status}**.")
    
    # --- /maintenance_on / /maintenance_off ---
    elif command in ['/maintenance_on', '/maintenance_off']:
        is_on = command == '/maintenance_on'
        BOT_STATUS['maintenance_mode'] = is_on
        save_settings()
        status = "YOQILDI" if is_on else "O'CHIRILDI"
        bot.send_message(chat_id, f"🛠 Texnik xizmat ko'rsatish rejimi muvaffaqiyatli **{status}**.")
        
    # --- /broadcast ---
    elif command == '/broadcast':
        try:
            message_to_send = message.text.split(' ', 1)[1]
        except IndexError:
            bot.send_message(chat_id, "⚠️ Foydalanish: `/broadcast Xabar matni`")
            return
            
        sent_count = 0
        failed_count = 0
        
        bot.send_message(chat_id, f"📢 **{len(USER_DATA)}** ta foydalanuvchiga xabar yuborilmoqda...")
        
        for user_id_str in USER_DATA:
            try:
                bot.send_message(int(user_id_str), message_to_send, parse_mode='Markdown')
                sent_count += 1
            except:
                failed_count += 1
                
        bot.send_message(chat_id, f"✅ **{sent_count}** ta foydalanuvchiga xabar yuborildi. ❌ **{failed_count}** ta yuborilmadi.")


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
    
    temp_id = generate_random_id()
    input_file_path = None
    output_file_path = None
    file_path_to_send = None

    try:
        # 1. Yuklab olish (yt-dlp)
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_DIR, f'input_{temp_id}.%(ext)s'), # Fayl nomi optimallashtirildi
            'format': ydl_format,
            'max_filesize': max_size_limit, 
            'noplaylist': True,
            'progress_hooks': [lambda d: progress_hook(d, bot, chat_id, processing_message.message_id)],
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}] if format_code == 'audio_only' else [],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            progress_hook.last_update = time.time() 
            info = ydl.extract_info(url, download=True)
            # Eng so'nggi yuklab olingan fayl nomini aniqlash
            if format_code == 'audio_only':
                input_file_path = os.path.join(DOWNLOAD_DIR, f'input_{temp_id}.mp3')
            else:
                # Video formatini aniqlashda yordam beradi (masalan, .mp4)
                potential_ext = info.get('ext')
                if potential_ext:
                    input_file_path = os.path.join(DOWNLOAD_DIR, f'input_{temp_id}.{potential_ext}')
                else:
                    input_file_path = ydl.prepare_filename(info) # Aniq nomni olib keladi

        bot.edit_message_text("✅ **Yuklab olish yakunlandi.** Endi qayta ishlanmoqda (Watermark).", chat_id, processing_message.message_id)
            
        # 2. Watermark Qo'shish (FFmpeg)
        if format_code != 'audio_only' and BOT_STATUS['watermark_enabled']: 
            
            # Chiqarish fayli nomini alohida yaratamiz
            output_file_path = os.path.join(DOWNLOAD_DIR, f'output_{temp_id}.mp4')
            
            ffmpeg_command = [
                'ffmpeg',
                '-i', input_file_path,
                '-vf', 
                f"drawtext=fontfile='{FONT_FILE_PATH}':text='{WATERMARK_TEXT}':"
                f"fontsize={FONT_SIZE}:fontcolor={FONT_COLOR}:box=1:boxcolor={TEXT_BORDER}@0.7:"
                f"x={POSITION_X}:y={POSITION_Y}",
                '-c:v', 'libx264', # Encoder qo'shildi
                '-preset', 'fast', # Tezroq ishlov berish uchun
                '-crf', '23', 
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
             bot.send_message(chat_id, "❌ **Xatolik!** Fayl topilmadi. (2-bosqich)")

    except yt_dlp.utils.DownloadError as e:
        error_message = f"❌ **Yuklashda xatolik!**\nSababi: Video topilmadi yoki yuklab olish mumkin emas."
        bot.send_message(chat_id, error_message, parse_mode='Markdown')
    except subprocess.CalledProcessError as e:
        error_message = f"❌ **FFmpeg/Qayta ishlashda xatolik!**\nSababi: `{e.stderr.decode()[:150]}...`"
        bot.send_message(chat_id, error_message, parse_mode='Markdown')
    except Exception as e:
        error_message = f"❌ **Kechirasiz, boshqa xatolik yuz berdi.**\nSababi: `{str(e)[:150]}...`"
        bot.send_message(chat_id, error_message, parse_mode='Markdown')

    finally:
        # 4. Vaqtincha fayllarni o'chirish (fayl borligini tekshirish muhim)
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass # Agar xabar allaqachon o'chirilgan bo'lsa
            
        if input_file_path and os.path.exists(input_file_path):
            os.remove(input_file_path)
        if output_file_path and os.path.exists(output_file_path):
            os.remove(output_file_path)
        
# --- 5. BOTNI ISHGA TUSHIRISH ---

if __name__ == '__main__':
    load_data() # Sozlamalar va foydalanuvchilarni yuklash
    print("Bot ishga tushdi (Long Polling Worker)...")
    try:
        # Bu buyruq botni Render'da Worker rejimida ishlashini ta'minlaydi.
        bot.polling(none_stop=True, interval=0, timeout=20) 
    except Exception as e:
        print(f"Bot ishga tushishida xatolik: {e}")

