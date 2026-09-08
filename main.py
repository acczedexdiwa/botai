import re
import json
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, time
from pathlib import Path
from telegram import (
    Update, ChatPermissions, ChatMember, Message,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from telegram.constants import ChatMemberStatus, ParseMode, ChatAction

# =================== CONFIG ===================
BOT_TOKEN = "8958951322:AAH11mD6r0BsAohLA_kjLys79uyZi4hcgxk"
DB_FILE = "bot_database.db"
OWNER_ID = 6192843541  # ใส่ user_id เจ้าของบอท

# =================== DATABASE ===================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS whitelist (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS violations (
            user_id INTEGER,
            chat_id INTEGER,
            count INTEGER DEFAULT 0,
            last_violation TIMESTAMP,
            PRIMARY KEY (user_id, chat_id)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS violations_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS muted_users (
            user_id INTEGER,
            chat_id INTEGER,
            until TIMESTAMP,
            reason TEXT,
            PRIMARY KEY (user_id, chat_id)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
            chat_id INTEGER PRIMARY KEY,
            anti_link BOOLEAN DEFAULT 1,
            anti_badword BOOLEAN DEFAULT 1,
            anti_spam BOOLEAN DEFAULT 1,
            anti_sticker BOOLEAN DEFAULT 0,
            anti_forward BOOLEAN DEFAULT 0,
            anti_image BOOLEAN DEFAULT 0,
            anti_voice BOOLEAN DEFAULT 0,
            anti_video BOOLEAN DEFAULT 0,
            anti_gif BOOLEAN DEFAULT 0,
            anti_emoji BOOLEAN DEFAULT 0,
            anti_caps BOOLEAN DEFAULT 0,
            anti_long_text BOOLEAN DEFAULT 0,
            anti_line BOOLEAN DEFAULT 0,
            anti_invite BOOLEAN DEFAULT 1,
            anti_username BOOLEAN DEFAULT 1,
            anti_phone BOOLEAN DEFAULT 1,
            anti_crypto BOOLEAN DEFAULT 1,
            anti_gambling BOOLEAN DEFAULT 1,
            max_warns INTEGER DEFAULT 3,
            mute_duration INTEGER DEFAULT 3600,
            delete_on_violate BOOLEAN DEFAULT 1,
            warn_message TEXT DEFAULT '⚠️ โปรดอ่านกฎกลุ่ม!',
            welcome_enabled BOOLEAN DEFAULT 0,
            welcome_message TEXT DEFAULT 'ยินดีต้อนรับ!',
            night_mode BOOLEAN DEFAULT 0,
            night_start INTEGER DEFAULT 0,
            night_end INTEGER DEFAULT 6,
            locked BOOLEAN DEFAULT 0
        )''')
        self.conn.commit()
    
    def get_settings(self, chat_id):
        c = self.conn.cursor()
        c.execute("SELECT * FROM settings WHERE chat_id = ?", (chat_id,))
        row = c.fetchone()
        if not row:
            c.execute("INSERT INTO settings (chat_id) VALUES (?)", (chat_id,))
            self.conn.commit()
            c.execute("SELECT * FROM settings WHERE chat_id = ?", (chat_id,))
            row = c.fetchone()
        cols = [d[0] for d in c.description]
        return dict(zip(cols, row))
    
    def update_setting(self, chat_id, key, value):
        c = self.conn.cursor()
        c.execute(f"UPDATE settings SET {key} = ? WHERE chat_id = ?", (value, chat_id))
        self.conn.commit()
    
    def add_violation(self, user_id, chat_id, reason):
        c = self.conn.cursor()
        c.execute("SELECT count FROM violations WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        row = c.fetchone()
        if row:
            c.execute("UPDATE violations SET count = count + 1, last_violation = CURRENT_TIMESTAMP WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        else:
            c.execute("INSERT INTO violations (user_id, chat_id, count) VALUES (?, ?, 1)", (user_id, chat_id))
        c.execute("INSERT INTO violations_log (user_id, chat_id, reason) VALUES (?, ?, ?)", (user_id, chat_id, reason))
        self.conn.commit()
        c.execute("SELECT count FROM violations WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        return c.fetchone()[0]
    
    def get_violations(self, user_id, chat_id):
        c = self.conn.cursor()
        c.execute("SELECT count FROM violations WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        row = c.fetchone()
        return row[0] if row else 0
    
    def reset_violations(self, chat_id, user_id=None):
        c = self.conn.cursor()
        if user_id:
            c.execute("DELETE FROM violations WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
            c.execute("DELETE FROM violations_log WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        else:
            c.execute("DELETE FROM violations WHERE chat_id = ?", (chat_id,))
            c.execute("DELETE FROM violations_log WHERE chat_id = ?", (chat_id,))
        self.conn.commit()
    
    def add_whitelist(self, user_id, username, added_by):
        c = self.conn.cursor()
        c.execute("INSERT OR REPLACE INTO whitelist (user_id, username, added_by) VALUES (?, ?, ?)", (user_id, username, added_by))
        self.conn.commit()
    
    def remove_whitelist(self, user_id):
        c = self.conn.cursor()
        c.execute("DELETE FROM whitelist WHERE user_id = ?", (user_id,))
        self.conn.commit()
    
    def is_whitelisted(self, user_id):
        c = self.conn.cursor()
        c.execute("SELECT 1 FROM whitelist WHERE user_id = ?", (user_id,))
        return c.fetchone() is not None
    
    def get_whitelist(self):
        c = self.conn.cursor()
        c.execute("SELECT user_id, username, added_at FROM whitelist")
        return c.fetchall()
    
    def add_muted(self, user_id, chat_id, until, reason):
        c = self.conn.cursor()
        c.execute("INSERT OR REPLACE INTO muted_users (user_id, chat_id, until, reason) VALUES (?, ?, ?, ?)", (user_id, chat_id, until, reason))
        self.conn.commit()
    
    def is_muted(self, user_id, chat_id):
        c = self.conn.cursor()
        c.execute("SELECT until FROM muted_users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        row = c.fetchone()
        if row:
            until = datetime.fromisoformat(row[0])
            if until > datetime.now():
                return True
            else:
                c.execute("DELETE FROM muted_users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
                self.conn.commit()
        return False
    
    def get_logs(self, chat_id, limit=20):
        c = self.conn.cursor()
        c.execute("SELECT user_id, reason, timestamp FROM violations_log WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?", (chat_id, limit))
        return c.fetchall()

db = Database()

# =================== PATTERNS ===================
BAD_WORDS = [
    "ควย", "หี", "เหี้ย", "ไอ้", "สัส", "สัด", "fuck", "shit",
    "bitch", "asshole", "dick", "pussy", "damn", "bastard",
    "ไอเหี้ย", "อีดอก", "อีสัส", "อีควาย", "ไอ้ควาย",
    "แม่ง", "เย็ด", "เชี่ย", "ห่า", "เฮงซวย", "ชิบหาย",
    "กระดอ", "จรวย", "หำ"
]

SPAM_WORDS = [
    "โปรโมชั่น", "ฟรีเครดิต", "ลงทุน", "รายได้", "สมัคร",
    "คาสิโน", "พนัน", "บาคาร่า", "สล็อต", "หวย", "หวยออนไลน์",
    "1xbet", "betflix", "crypto", "bitcoin", "btc", "eth", "usdt"
]

LINK_PATTERNS = [
    r"https?://[^\s]+",
    r"t\.me/[^\s]+",
    r"@[a-zA-Z0-9_]{5,}",
    r"www\.[^\s]+",
    r"bit\.ly/[^\s]+",
    r"t\.co/[^\s]+",
    r"goo\.gl/[^\s]+",
    r"tinyurl\.com/[^\s]+",
    r"is\.gd/[^\s]+",
    r"ow\.ly/[^\s]+"
]

INVITE_PATTERNS = [
    r"t\.me/joinchat/[^\s]+",
    r"t\.me/\+[^\s]+",
    r"telegram\.me/joinchat/[^\s]+"
]

PHONE_PATTERN = r"(\+66|0)[0-9]{8,9}"
USERNAME_PATTERN = r"@[a-zA-Z0-9_]{5,}"

# =================== HELPER FUNCTIONS ===================
async def is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    if user.id == OWNER_ID:
        return True
    if db.is_whitelisted(user.id):
        return True
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception:
        return False

async def is_target_admin(context, chat_id, user_id) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception:
        return False

def detect_link(text):
    for p in LINK_PATTERNS:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False

def detect_invite(text):
    for p in INVITE_PATTERNS:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False

def detect_badword(text):
    text_lower = f" {text.lower()} "
    return any(b in text_lower for b in BAD_WORDS)

def detect_spam_word(text):
    text_lower = text.lower()
    return any(s in text_lower for s in SPAM_WORDS)

def detect_phone(text):
    return re.search(PHONE_PATTERN, text) is not None

def detect_username_spam(text):
    matches = re.findall(USERNAME_PATTERN, text)
    return len(matches) >= 2

def is_caps(text):
    if len(text) < 10:
        return False
    caps = sum(1 for c in text if c.isupper())
    letters = sum(1 for c in text if c.isalpha())
    return letters > 0 and (caps / letters) > 0.7

def is_long_text(text):
    return len(text) > 2000

def has_many_lines(text):
    return text.count('\n') > 15

def is_night_time(chat_settings):
    if not chat_settings.get("night_mode"):
        return False
    now = datetime.now().time()
    start_h = chat_settings.get("night_start", 0)
    end_h = chat_settings.get("night_end", 6)
    if start_h < end_h:
        return start_h <= now.hour < end_h
    else:
        return now.hour >= start_h or now.hour < end_h

async def punish(update, context, reason):
    user = update.effective_user
    chat = update.effective_chat
    settings = db.get_settings(chat.id)
    
    count = db.add_violation(user.id, chat.id, reason)
    max_warns = settings["max_warns"]
    
    if settings["delete_on_violate"]:
        try:
            await update.message.delete()
        except Exception:
            pass
    
    if count >= max_warns:
        until = datetime.now() + timedelta(seconds=settings["mute_duration"])
        try:
            await context.bot.restrict_chat_member(
                chat.id, user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
            db.add_muted(user.id, chat.id, until.isoformat(), reason)
            text = f"🔇 {user.mention_html()} ถูก mute {settings['mute_duration']//60} นาที\n📝 เหตุผล: {reason}"
            db.reset_violations(chat.id, user.id)
        except Exception as e:
            text = f"❌ mute ไม่สำเร็จ: {e}"
    else:
        text = f"⚠️ {user.mention_html()} เตือน {count}/{max_warns}\n📝 {reason}"
    
    msg = await context.bot.send_message(chat.id, text, parse_mode=ParseMode.HTML)
    await asyncio.sleep(15)
    try:
        await msg.delete()
    except Exception:
        pass

# =================== COMMAND HANDLERS ===================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    keyboard = [
        [InlineKeyboardButton("📊 สถานะ", callback_data="status"),
         InlineKeyboardButton("⚙️ ตั้งค่า", callback_data="settings_menu")],
        [InlineKeyboardButton("📋 Whitelist", callback_data="whitelist_menu"),
         InlineKeyboardButton("📜 Logs", callback_data="logs_menu")],
        [InlineKeyboardButton("🔓 ปลดล็อค", callback_data="unlock"),
         InlineKeyboardButton("🔒 ล็อคกลุ่ม", callback_data="lock")],
    ]
    await update.message.reply_text(
        "🤖 **บอทดูแลกลุ่ม v2.0**\n\nเลือกเมนู:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    text = """
📖 **คำสั่งทั้งหมด:**

**🔧 ระบบ:**
/start - เมนูหลัก
/help - คำสั่งทั้งหมด
/status - สถานะระบบ
/settings - ตั้งค่า

**👮 จัดการสมาชิก:**
/ban - แบน user
/unban - ปลดแบน
/mute - ปิดปาก
/unmute - เปิดปาก
/kick - เตะออก
/warn - เตือน
/unwarn - ลบเตือน
/warns - ดูเตือน
/resetwarns - รีเซ็ตเตือนทั้งหมด

**🛡️ ระบบป้องกัน:**
/on - เปิดระบบทั้งหมด
/off - ปิดระบบทั้งหมด
/antispam on/off
/antilink on/off
/antiforward on/off
/antisticker on/off
/antibadword on/off
/antiinvite on/off
/anticrypto on/off
/antigambling on/off
/antiphone on/off
/anticaps on/off
/antilongtext on/off
/antiline on/off
/antiemoji on/off
/antiimage on/off
/antivoice on/off
/antivideo on/off
/antigif on/off

**📊 ตั้งค่า:**
/setwarns <จำนวน>
/setmute <วินาที>
/setwelcome <ข้อความ>
/togglewelcome
/nightmode on/off
/setnight <start> <end>

**🔒 ล็อคกลุ่ม:**
/lock - ล็อค (ห้ามส่งอะไร)
/unlock - ปลดล็อค

**📋 Whitelist:**
/wl add <user_id|@username>
/wl remove <user_id|@username>
/wl list

**📜 Logs:**
/logs - ดู log violations
/clearlogs - ล้าง log

**🧹 ล้างข้อมูล:**
/purge - ลบข้อความตามจำนวน
/del - ลบข้อความที่ตอบ

**ℹ️ ข้อมูล:**
/chatinfo - ข้อมูลกลุ่ม
/userinfo - ข้อมูล user
/id - ดู user_id
/me - ข้อมูลบอท
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    chat_id = update.effective_chat.id
    s = db.get_settings(chat_id)
    text = f"""📊 **สถานะกลุ่ม**

🛡️ **ระบบป้องกัน:**
• 🔗 ลิ้งค์: {'✅' if s['anti_link'] else '❌'}
• 🤐 คำหยาบ: {'✅' if s['anti_badword'] else '❌'}
• 📨 สแปม: {'✅' if s['anti_spam'] else '❌'}
• 📱 สติกเกอร์: {'✅' if s['anti_sticker'] else '❌'}
• ↪️ Forward: {'✅' if s['anti_forward'] else '❌'}
• 🖼️ รูปภาพ: {'✅' if s['anti_image'] else '❌'}
• 🎤 เสียง: {'✅' if s['anti_voice'] else '❌'}
• 🎬 วิดีโอ: {'✅' if s['anti_video'] else '❌'}
• 🎞️ GIF: {'✅' if s['anti_gif'] else '❌'}
• 😀 Emoji: {'✅' if s['anti_emoji'] else '❌'}
• 🔠 ตัวพิมพ์ใหญ่: {'✅' if s['anti_caps'] else '❌'}
• 📏 ข้อความยาว: {'✅' if s['anti_long_text'] else '❌'}
• 📝 หลายบรรทัด: {'✅' if s['anti_line'] else '❌'}
• 💌 Invite: {'✅' if s['anti_invite'] else '❌'}
• 👤 @Username: {'✅' if s['anti_username'] else '❌'}
• 📞 เบอร์โทร: {'✅' if s['anti_phone'] else '❌'}
• 💰 คริปโต: {'✅' if s['anti_crypto'] else '❌'}
• 🎰 พนัน: {'✅' if s['anti_gambling'] else '❌'}

⚙️ **ตั้งค่า:**
• 🔢 Max warns: {s['max_warns']}
• ⏱️ Mute: {s['mute_duration']//60} นาที
• 🗑️ ลบข้อความ: {'✅' if s['delete_on_violate'] else '❌'}
• 👋 Welcome: {'✅' if s['welcome_enabled'] else '❌'}
• 🌙 Night mode: {'✅' if s['night_mode'] else '❌'} ({s['night_start']}:00-{s['night_end']}:00)
• 🔒 Locked: {'✅' if s['locked'] else '❌'}
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if len(context.args) < 2:
        await cmd_status(update, context)
        await update.message.reply_text("\n💡 ใช้: /settings <key> <value>")
        return
    key = context.args[0]
    val = context.args[1].lower()
    chat_id = update.effective_chat.id
    if val in ["on", "true", "1", "yes"]:
        v = 1
    elif val in ["off", "false", "0", "no"]:
        v = 0
    elif val.isdigit():
        v = int(val)
    else:
        v = val
    db.update_setting(chat_id, key, v)
    await update.message.reply_text(f"✅ ตั้ง `{key}` = `{v}`", parse_mode=ParseMode.MARKDOWN)

async def cmd_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    chat_id = update.effective_chat.id
    for k in ["anti_link", "anti_badword", "anti_spam", "anti_invite", "anti_username", "anti_phone", "anti_crypto", "anti_gambling"]:
        db.update_setting(chat_id, k, 1)
    await update.message.reply_text("🟢 เปิดระบบหลักทั้งหมด!")

async def cmd_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    chat_id = update.effective_chat.id
    for k in ["anti_link", "anti_badword", "anti_spam", "anti_invite", "anti_username", "anti_phone", "anti_crypto", "anti_gambling"]:
        db.update_setting(chat_id, k, 0)
    await update.message.reply_text("🔴 ปิดระบบหลักทั้งหมด!")

# Toggle shortcuts
async def make_toggle(name):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await is_admin_or_owner(update, context):
            return
        chat_id = update.effective_chat.id
        if len(context.args) > 0:
            val = context.args[0].lower()
            new_val = 1 if val in ["on", "true", "1"] else 0
        else:
            current = db.get_settings(chat_id)[name]
            new_val = 0 if current else 1
        db.update_setting(chat_id, name, new_val)
        await update.message.reply_text(f"✅ `{name}` = `{bool(new_val)}`", parse_mode=ParseMode.MARKDOWN)
    return handler

# Whitelist commands
async def cmd_wl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if len(context.args) < 1:
        wl = db.get_whitelist()
        if not wl:
            await update.message.reply_text("📋 Whitelist ว่าง")
            return
        text = "📋 **Whitelist:**\n\n"
        for uid, uname, added_at in wl:
            text += f"• `{uid}` {('@'+uname) if uname else ''}\n"
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        return
    
    action = context.args[0]
    if action == "add" and len(context.args) > 1:
        target = context.args[1]
        try:
            if target.startswith("@"):
                await update.message.reply_text("❌ ต้องใช้ user_id ไม่ใช่ @username\nลองให้ user ส่งข้อความแล้วดู id จาก log")
                return
            uid = int(target)
            user = await context.bot.get_chat(uid)
            db.add_whitelist(uid, user.username, update.effective_user.id)
            await update.message.reply_text(f"✅ เพิ่ม `{uid}` (@{user.username}) ใน whitelist", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await update.message.reply_text(f"❌ ผิดพลาด: {e}\nใช้ user_id (ตัวเลข) เท่านั้น")
    elif action == "remove" and len(context.args) > 1:
        try:
            uid = int(context.args[1])
            db.remove_whitelist(uid)
            await update.message.reply_text(f"🗑️ ลบ `{uid}` แล้ว", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await update.message.reply_text(f"❌ {e}")
    elif action == "list":
        wl = db.get_whitelist()
        text = "📋 **Whitelist:**\n\n" + "\n".join([f"• `{u[0]}` {('@'+u[1]) if u[1] else ''}" for u in wl])
        await update.message.reply_text(text or "ว่าง", parse_mode=ParseMode.MARKDOWN)

# Moderation
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("💡 ตอบกลับข้อความคนที่จะแบน")
        return
    user = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"🔨 แบน {user.mention_html()} แล้ว", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if len(context.args) < 1:
        await update.message.reply_text("💡 /unban <user_id>")
        return
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, int(context.args[0]))
        await update.message.reply_text(f"✅ ปลดแบน `{context.args[0]}`", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("💡 ตอบกลับข้อความ")
        return
    duration = int(context.args[0]) if context.args else 3600
    user = update.message.reply_to_message.from_user
    until = datetime.now() + timedelta(seconds=duration)
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        await update.message.reply_text(f"🔇 Mute {user.mention_html()} {duration//60} นาที", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("💡 ตอบกลับข้อความ")
        return
    user = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, user.id,
            permissions=ChatPermissions(
                can_send_messages=True, can_send_media_messages=True,
                can_send_other_messages=True, can_add_web_page_previews=True
            )
        )
        await update.message.reply_text(f"🔊 Unmute {user.mention_html()}", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("💡 ตอบกลับข้อความ")
        return
    user = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await context.bot.unban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"👢 เตะ {user.mention_html()} ออกแล้ว", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("💡 ตอบกลับข้อความ")
        return
    user = update.message.reply_to_message.from_user
    count = db.add_violation(user.id, update.effective_chat.id, "Manual warn")
    s = db.get_settings(update.effective_chat.id)
    text = f"⚠️ {user.mention_html()} โดนเตือน {count}/{s['max_warns']}"
    if count >= s['max_warns']:
        try:
            until = datetime.now() + timedelta(seconds=s['mute_duration'])
            await context.bot.restrict_chat_member(
                update.effective_chat.id, user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
            text += f"\n🔇 Mute {s['mute_duration']//60} นาที!"
            db.reset_violations(update.effective_chat.id, user.id)
        except Exception as e:
            text += f"\n❌ {e}"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def cmd_unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("💡 ตอบกลับข้อความ")
        return
    user = update.message.reply_to_message.from_user
    db.reset_violations(update.effective_chat.id, user.id)
    await update.message.reply_text(f"✅ ลบ warning {user.mention_html()}", parse_mode=ParseMode.HTML)

async def cmd_warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    target_user = None
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    elif context.args:
        try:
            target_user = await context.bot.get_chat(int(context.args[0]))
        except Exception:
            pass
    
    if target_user:
        count = db.get_violations(target_user.id, update.effective_chat.id)
        await update.message.reply_text(f"📊 {target_user.mention_html()}: {count} ครั้ง", parse_mode=ParseMode.HTML)
    else:
        c = sqlite3.connect(DB_FILE).cursor()
        c.execute("SELECT user_id, count FROM violations WHERE chat_id = ? ORDER BY count DESC LIMIT 20", (update.effective_chat.id,))
        rows = c.fetchall()
        if not rows:
            await update.message.reply_text("📊 ไม่มี violations")
            return
        text = "📊 **Violations (Top 20):**\n\n"
        for uid, cnt in rows:
            try:
                u = await context.bot.get_chat(uid)
                text += f"• {u.mention_html()}: {cnt}\n"
            except Exception:
                text += f"• `{uid}`: {cnt}\n"
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def cmd_resetwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    db.reset_violations(update.effective_chat.id)
    await update.message.reply_text("🔄 รีเซ็ต violations ทั้งหมดแล้ว!")

# Settings setters
async def cmd_setwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if not context.args:
        await update.message.reply_text("💡 /setwarns <จำนวน>")
        return
    n = int(context.args[0])
    db.update_setting(update.effective_chat.id, "max_warns", n)
    await update.message.reply_text(f"✅ Max warns = {n}")

async def cmd_setmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if not context.args:
        await update.message.reply_text("💡 /setmute <วินาที>")
        return
    n = int(context.args[0])
    db.update_setting(update.effective_chat.id, "mute_duration", n)
    await update.message.reply_text(f"✅ Mute duration = {n} วินาที ({n//60} นาที)")

async def cmd_setwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    msg = " ".join(context.args)
    db.update_setting(update.effective_chat.id, "welcome_message", msg)
    await update.message.reply_text(f"✅ Welcome message ตั้งแล้ว")

async def cmd_togglewelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    s = db.get_settings(update.effective_chat.id)
    db.update_setting(update.effective_chat.id, "welcome_enabled", 0 if s["welcome_enabled"] else 1)
    await update.message.reply_text(f"✅ Welcome = {not s['welcome_enabled']}")

async def cmd_nightmode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if context.args and context.args[0] in ["on", "off"]:
        db.update_setting(update.effective_chat.id, "night_mode", 1 if context.args[0] == "on" else 0)
    else:
        s = db.get_settings(update.effective_chat.id)
        db.update_setting(update.effective_chat.id, "night_mode", 0 if s["night_mode"] else 1)
    await update.message.reply_text("✅ Night mode toggle")

async def cmd_setnight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("💡 /setnight <start_hour> <end_hour>")
        return
    db.update_setting(update.effective_chat.id, "night_start", int(context.args[0]))
    db.update_setting(update.effective_chat.id, "night_end", int(context.args[1]))
    await update.message.reply_text(f"✅ Night: {context.args[0]}:00 - {context.args[1]}:00")

# Lock group
async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    db.update_setting(update.effective_chat.id, "locked", 1)
    await update.message.reply_text("🔒 ล็อคกลุ่ม! ห้ามส่งอะไร (ยกเว้นแอดมิน)")

async def cmd_unlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    db.update_setting(update.effective_chat.id, "locked", 0)
    await update.message.reply_text("🔓 ปลดล็อคกลุ่มแล้ว!")

# Logs
async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    logs = db.get_logs(update.effective_chat.id, 30)
    if not logs:
        await update.message.reply_text("📜 ไม่มี log")
        return
    text = "📜 **Logs ล่าสุด:**\n\n"
    for uid, reason, ts in logs:
        try:
            u = await context.bot.get_chat(uid)
            name = u.first_name
        except Exception:
            name = str(uid)
        text += f"• {ts}: {name} - {reason}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_clearlogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    c = sqlite3.connect(DB_FILE).cursor()
    c.execute("DELETE FROM violations_log WHERE chat_id = ?", (update.effective_chat.id,))
    sqlite3.connect(DB_FILE).commit()
    await update.message.reply_text("🗑️ ล้าง log แล้ว")

# Purge messages
async def cmd_purge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if not context.args:
        await update.message.reply_text("💡 /purge <จำนวน>")
        return
    n = int(context.args[0])
    deleted = 0
    async for msg in context.bot.get_chat_history(update.effective_chat.id, limit=n+1):
        if msg.message_id >= update.message.message_id - n:
            try:
                await msg.delete()
                deleted += 1
            except Exception:
                pass
    m = await update.message.reply_text(f"🧹 ลบ {deleted} ข้อความ")
    await asyncio.sleep(5)
    try:
        await m.delete()
    except Exception:
        pass

async def cmd_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    if update.message.reply_to_message:
        try:
            await update.message.reply_to_message.delete()
            await update.message.delete()
        except Exception:
            pass

# Info commands
async def cmd_chatinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    chat = update.effective_chat
    count = await context.bot.get_chat_member_count(chat.id)
    text = f"""ℹ️ **ข้อมูลกลุ่ม:**
• ชื่อ: {chat.title}
• ID: `{chat.id}`
• สมาชิก: {count}
• Type: {chat.type}
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_owner(update, context):
        return
    user = None
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    elif context.args:
        try:
            user = await context.bot.get_chat(int(context.args[0]))
        except Exception:
            pass
    if not user:
        user = update.effective_user
    warns = db.get_violations(user.id, update.effective_chat.id)
    text = f"""👤 **ข้อมูล User:**
• ชื่อ: {user.first_name}
• Username: @{user.username if user.username else '-'}
• ID: `{user.id}`
• Warnings: {warns}
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        await update.message.reply_text(f"👤 ID: `{user.id}`\n💬 Chat ID: `{update.effective_chat.id}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"💬 Chat ID: `{update.effective_chat.id}`\n👤 Your ID: `{update.effective_user.id}`", parse_mode=ParseMode.MARKDOWN)

async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me = await context.bot.get_me()
    await update.message.reply_text(f"""🤖 **ข้อมูลบอท:**
• ชื่อ: {me.first_name}
• Username: @{me.username}
• ID: `{me.id}`
• สถานะ: ออนไลน์ ✅
""", parse_mode=ParseMode.MARKDOWN)

# =================== CALLBACK QUERY ===================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    chat = query.message.chat
    
    # Check permission
    if not await is_admin_or_owner(update, context):
        return
    
    data_cb = query.data
    if data_cb == "status":
        s = db.get_settings(chat.id)
        text = f"📊 Max warns: {s['max_warns']} | Mute: {s['mute_duration']//60}m | Locked: {bool(s['locked'])}"
        await query.edit_message_text(text)
    elif data_cb == "lock":
        db.update_setting(chat.id, "locked", 1)
        await query.edit_message_text("🔒 ล็อคกลุ่มแล้ว!")
    elif data_cb == "unlock":
        db.update_setting(chat.id, "locked", 0)
        await query.edit_message_text("🔓 ปลดล็อคกลุ่มแล้ว!")

# =================== MESSAGE HANDLER ===================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    
    user = update.effective_user
    chat = update.effective_chat
    settings = db.get_settings(chat.id)
    
    # Skip admins/whitelisted - they do anything
    if await is_admin_or_owner(update, context):
        return
    
    # Skip if muted
    if db.is_muted(user.id, chat.id):
        try:
            await update.message.delete()
        except Exception:
            pass
        return
    
    # Check if locked
    if settings["locked"]:
        try:
            await update.message.delete()
        except Exception:
            pass
        return
    
    reasons = []
    text = update.message.text or ""
    
    # 1. Link detection
    if settings["anti_link"] and detect_link(text):
        reasons.append("🔗 ส่งลิ้งค์")
    if settings["anti_invite"] and detect_invite(text):
        reasons.append("💌 ส่ง invite link")
    if settings["anti_username"] and detect_username_spam(text):
        reasons.append("👤 @username เยอะเกิน")
    if settings["anti_phone"] and detect_phone(text):
        reasons.append("📞 เบอร์โทร")
    if settings["anti_crypto"] and any(c in text.lower() for c in ["btc", "eth", "usdt", "bitcoin", "crypto"]):
        reasons.append("💰 คริปโต")
    if settings["anti_gambling"] and any(g in text.lower() for g in ["บาคาร่า", "คาสิโน", "พนัน", "สล็อต", "หวย"]):
        reasons.append("🎰 พนัน")
    
    # 2. Badword
    if settings["anti_badword"] and detect_badword(text):
        reasons.append("🤬 คำหยาบ")
    
    # 3. Spam word
    if detect_spam_word(text):
        reasons.append("📢 คำสแปม")
    
    # 4. Caps
    if settings["anti_caps"] and is_caps(text):
        reasons.append("🔠 ตัวพิมพ์ใหญ่")
    
    # 5. Long text
    if settings["anti_long_text"] and is_long_text(text):
        reasons.append("📏 ข้อความยาวเกินไป")
    
    # 6. Many lines
    if settings["anti_line"] and has_many_lines(text):
        reasons.append("📝 หลายบรรทัดเกิน")
    
    # 7. Sticker
    if settings["anti_sticker"] and update.message.sticker:
        reasons.append("🎭 สติกเกอร์")
    
    # 8. Forward
    if settings["anti_forward"] and update.message.forward_date:
        reasons.append("↪️ Forward")
    
    # 9. Media
    if settings["anti_image"] and update.message.photo:
        reasons.append("🖼️ รูปภาพ")
    if settings["anti_voice"] and update.message.voice:
        reasons.append("🎤 เสียง")
    if settings["anti_video"] and update.message.video:
        reasons.append("🎬 วิดีโอ")
    if settings["anti_gif"] and update.message.animation:
        reasons.append("🎞️ GIF")
    if settings["anti_emoji"] and update.message.entities:
        for e in update.message.entities:
            if e.type == "bold_italic" or "emoji" in str(e.type).lower():
                if e.type in ["custom_emoji"]:
                    reasons.append("😀 Emoji")
                    break
    
    # 10. Spam (repeated messages)
    if settings["anti_spam"]:
        if "last_msgs" not in context.user_data:
            context.user_data["last_msgs"] = []
        last = context.user_data["last_msgs"]
        last.append((text, time.time()))
        # เก็บแค่ 10 ข้อความล่าสุดใน 30 วิ
        now_t = time.time()
        last[:] = [m for m in last if now_t - m[1] < 30]
        if len(last) >= 3:
            texts = [m[0] for m in last]
            if len(set(texts)) == 1:
                reasons.append("📨 สแปมซ้ำ")
                last.clear()
            elif len(last) >= 8:
                reasons.append("📨 flood")
                last.clear()
    
    # Night mode
    if is_night_time(settings) and not reasons:
        reasons.append("🌙 Night mode")
    
    if reasons:
        await punish(update, context, " | ".join(reasons))

# =================== NEW MEMBER ===================
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    settings = db.get_settings(update.effective_chat.id)
    if not settings["welcome_enabled"]:
        return
    for new_user in update.message.new_chat_members:
        if new_user.id == context.bot.id:
            continue
        try:
            await update.message.reply_text(
                f"{settings['welcome_message']}\n👋 ยินดีต้อนรับ {new_user.mention_html()}!",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

# =================== MAIN ===================
def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # คำสั่งหลัก
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("on", cmd_on))
    app.add_handler(CommandHandler("off", cmd_off))
    
    # Moderation
    for cmd, handler in [
        ("ban", cmd_ban), ("unban", cmd_unban),
        ("mute", cmd_mute), ("unmute", cmd_unmute),
        ("kick", cmd_kick), ("warn", cmd_warn),
        ("unwarn", cmd_unwarn), ("warns", cmd_warns),
        ("resetwarns", cmd_resetwarns),
    ]:
        app.add_handler(CommandHandler(cmd, handler))
    
    # Settings
    for cmd, handler in [
        ("setwarns", cmd_setwarns), ("setmute", cmd_setmute),
        ("setwelcome", cmd_setwelcome), ("togglewelcome", cmd_togglewelcome),
        ("nightmode", cmd_nightmode), ("setnight", cmd_setnight),
        ("lock", cmd_lock), ("unlock", cmd_unlock),
    ]:
        app.add_handler(CommandHandler(cmd, handler))
    
    # Whitelist
    app.add_handler(CommandHandler("wl", cmd_wl))
    
    # Logs
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("clearlogs", cmd_clearlogs))
    
    # Purge
    app.add_handler(CommandHandler("purge", cmd_purge))
    app.add_handler(CommandHandler("del", cmd_del))
    
    # Info
    for cmd, handler in [
        ("chatinfo", cmd_chatinfo), ("userinfo", cmd_userinfo),
        ("id", cmd_id), ("me", cmd_me),
    ]:
        app.add_handler(CommandHandler(cmd, handler))
    
    # Anti toggles
    toggles = [
        ("antispam", "anti_spam"), ("antilink", "anti_link"),
        ("antiforward", "anti_forward"), ("antisticker", "anti_sticker"),
        ("antibadword", "anti_badword"), ("antiinvite", "anti_invite"),
        ("anticrypto", "anti_crypto"), ("antigambling", "anti_gambling"),
        ("antiphone", "anti_phone"), ("anticaps", "anti_caps"),
        ("antilongtext", "anti_long_text"), ("antiline", "anti_line"),
        ("antiemoji", "anti_emoji"), ("antiimage", "anti_image"),
        ("antivoice", "anti_voice"), ("antivideo", "anti_video"),
        ("antigif", "anti_gif"),
    ]
    for cmd, key in toggles:
        app.add_handler(CommandHandler(cmd, await make_toggle(key)))
    
    # Callback
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # New members
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    
    # All messages
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    
    print("🤖 Bot v2.0 started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
