import os
import re
import time
from collections import defaultdict, deque

from telegram import Update, ChatPermissions
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, ChatMemberHandler,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN", "8958951322:AAH11mD6r0BsAohLA_kjLys79uyZi4hcgxk")

# Per-chat configuration (in-memory; restart resets settings)
CONFIG = defaultdict(lambda: {
    "anti_link": True,
    "anti_badword": True,
    "anti_spam": True,
    "anti_flood": True,
    "anti_media": False,
    "warn_limit": 3,
    "mute_minutes": 10,
    "badwords": {"fuck", "shit", "bitch", "เหี้ย", "สัส", "ควย", "แม่ง", "ไอ้สัส"},
    "whitelist": set(),
})

WARNINGS = defaultdict(lambda: defaultdict(int))
RECENT = defaultdict(lambda: defaultdict(deque))
LOCKED = defaultdict(bool)

URL_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/)", re.I)


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False
    member = await context.bot.get_chat_member(
        update.effective_chat.id, update.effective_user.id
    )
    return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)


async def punish(update, context, reason):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return

    try:
        await msg.delete()
    except Exception:
        pass

    key = (chat.id, user.id)
    WARNINGS[chat.id][user.id] += 1
    count = WARNINGS[chat.id][user.id]
    cfg = CONFIG[chat.id]

    if count >= cfg["warn_limit"]:
        try:
            until = int(time.time()) + cfg["mute_minutes"] * 60
            await context.bot.restrict_chat_member(
                chat.id,
                user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            await context.bot.send_message(
                chat.id,
                f"🔇 ลงโทษ {user.mention_html()} แล้ว\nเหตุผล: {reason}\n"
                f"Warn {count}/{cfg['warn_limit']} • Mute {cfg['mute_minutes']} นาที",
                parse_mode="HTML",
            )
        except Exception:
            pass
    else:
        try:
            await context.bot.send_message(
                chat.id,
                f"⚠️ {user.mention_html()} โปรดระวัง\n"
                f"เหตุผล: {reason}\nWarn {count}/{cfg['warn_limit']}",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def moderate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user or chat.type not in ("group", "supergroup"):
        return

    # Admins bypass moderation as requested.
    if await is_admin(update, context):
        return

    cfg = CONFIG[chat.id]
    text = msg.text or msg.caption or ""
    now = time.monotonic()
    q = RECENT[chat.id][user.id]
    q.append(now)
    while q and now - q[0] > 8:
        q.popleft()

    # Flood/spam
    if cfg["anti_flood"] and len(q) >= 7:
        await punish(update, context, "ส่งข้อความถี่เกินไป (Flood)")
        q.clear()
        return

    if cfg["anti_link"] and URL_RE.search(text):
        # Allow explicitly whitelisted domains/links.
        if not any(w.lower() in text.lower() for w in cfg["whitelist"]):
            await punish(update, context, "ห้ามส่งลิงก์")
            return

    if cfg["anti_badword"] and text:
        normalized = re.sub(r"[\W_]+", "", text.lower(), flags=re.UNICODE)
        for word in cfg["badwords"]:
            if re.sub(r"[\W_]+", "", word.lower(), flags=re.UNICODE) in normalized:
                await punish(update, context, "ตรวจพบคำต้องห้าม")
                return

    if cfg["anti_media"] and (msg.photo or msg.video or msg.animation or msg.document or msg.sticker):
        await punish(update, context, "ไม่อนุญาตให้ส่งสื่อ")
        return

    if LOCKED[chat.id]:
        await punish(update, context, "กลุ่มอยู่ในโหมดล็อก")
        return


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🛡️ ZEDEX BOT\n\n"
        "บอทดูแลกลุ่ม Telegram\n"
        "/settings - ดูการตั้งค่า\n"
        "/warns - ดู Warn ของคุณ\n"
        "/setwarn <จำนวน> - ตั้งจำนวน Warn (แอดมิน)\n"
        "/setmute <นาที> - ตั้งเวลา Mute (แอดมิน)\n"
        "/toggle <link|badword|spam|flood|media> - เปิด/ปิด (แอดมิน)\n"
        "/addbadword <คำ> - เพิ่มคำต้องห้าม (แอดมิน)\n"
        "/delbadword <คำ> - ลบคำต้องห้าม (แอดมิน)\n"
        "/whitelist <ข้อความ> - เพิ่ม whitelist (แอดมิน)\n"
        "/lock - ล็อกกลุ่ม (แอดมิน)\n"
        "/unlock - ปลดล็อก (แอดมิน)\n"
        "/warn @user - Warn สมาชิก (แอดมิน)\n"
        "/unwarn @user - ลด Warn (แอดมิน)\n"
        "/mute @user <นาที> - Mute (แอดมิน)\n"
        "/unmute @user - Unmute (แอดมิน)\n"
        "/ban @user - Ban (แอดมิน)\n"
        "/unban <user_id> - Unban (แอดมิน)\n"
        "/purge - ใช้ตอบกลับข้อความเพื่อลบ (แอดมิน)"
    )


async def settings(update, context):
    cfg = CONFIG[update.effective_chat.id]
    await update.effective_message.reply_text(
        "⚙️ ZEDEX BOT SETTINGS\n\n"
        f"🔗 Anti-Link: {'ON' if cfg['anti_link'] else 'OFF'}\n"
        f"🤬 Anti-Badword: {'ON' if cfg['anti_badword'] else 'OFF'}\n"
        f"📨 Anti-Spam: {'ON' if cfg['anti_spam'] else 'OFF'}\n"
        f"🌊 Anti-Flood: {'ON' if cfg['anti_flood'] else 'OFF'}\n"
        f"📸 Anti-Media: {'ON' if cfg['anti_media'] else 'OFF'}\n"
        f"⚠️ Warn Limit: {cfg['warn_limit']}\n"
        f"🔇 Mute: {cfg['mute_minutes']} นาที"
    )


async def admin_only(update, context):
    return await is_admin(update, context)


async def setwarn(update, context):
    if not await admin_only(update, context): return
    try:
        n = max(1, min(20, int(context.args[0])))
        CONFIG[update.effective_chat.id]["warn_limit"] = n
        await update.effective_message.reply_text(f"✅ ตั้ง Warn Limit = {n}")
    except Exception:
        await update.effective_message.reply_text("ใช้: /setwarn 3")


async def setmute(update, context):
    if not await admin_only(update, context): return
    try:
        n = max(1, min(10080, int(context.args[0])))
        CONFIG[update.effective_chat.id]["mute_minutes"] = n
        await update.effective_message.reply_text(f"✅ ตั้ง Mute = {n} นาที")
    except Exception:
        await update.effective_message.reply_text("ใช้: /setmute 10")


async def toggle(update, context):
    if not await admin_only(update, context): return
    if not context.args or context.args[0].lower() not in {"link","badword","spam","flood","media"}:
        await update.effective_message.reply_text("ใช้: /toggle link|badword|spam|flood|media")
        return
    key = {"link":"anti_link","badword":"anti_badword","spam":"anti_spam",
           "flood":"anti_flood","media":"anti_media"}[context.args[0].lower()]
    cfg = CONFIG[update.effective_chat.id]
    cfg[key] = not cfg[key]
    await update.effective_message.reply_text(f"✅ {key} = {'ON' if cfg[key] else 'OFF'}")


async def addbadword(update, context):
    if not await admin_only(update, context): return
    if not context.args:
        await update.effective_message.reply_text("ใช้: /addbadword คำ")
        return
    CONFIG[update.effective_chat.id]["badwords"].add(" ".join(context.args).lower())
    await update.effective_message.reply_text("✅ เพิ่มคำต้องห้ามแล้ว")


async def delbadword(update, context):
    if not await admin_only(update, context): return
    if not context.args:
        await update.effective_message.reply_text("ใช้: /delbadword คำ")
        return
    CONFIG[update.effective_chat.id]["badwords"].discard(" ".join(context.args).lower())
    await update.effective_message.reply_text("✅ ลบคำต้องห้ามแล้ว")


async def whitelist(update, context):
    if not await admin_only(update, context): return
    if not context.args:
        await update.effective_message.reply_text("ใช้: /whitelist example.com")
        return
    CONFIG[update.effective_chat.id]["whitelist"].add(" ".join(context.args))
    await update.effective_message.reply_text("✅ เพิ่ม whitelist แล้ว")


async def lock(update, context):
    if not await admin_only(update, context): return
    LOCKED[update.effective_chat.id] = True
    await update.effective_message.reply_text("🔒 ล็อกกลุ่มแล้ว")


async def unlock(update, context):
    if not await admin_only(update, context): return
    LOCKED[update.effective_chat.id] = False
    await update.effective_message.reply_text("🔓 ปลดล็อกกลุ่มแล้ว")


async def warns(update, context):
    n = WARNINGS[update.effective_chat.id][update.effective_user.id]
    await update.effective_message.reply_text(f"⚠️ Warn ของคุณ: {n}")


async def target_from_reply(update):
    if update.effective_message and update.effective_message.reply_to_message:
        return update.effective_message.reply_to_message.from_user
    return None


async def warn(update, context):
    if not await admin_only(update, context): return
    target = await target_from_reply(update)
    if not target:
        await update.effective_message.reply_text("ให้ Reply ข้อความของสมาชิกแล้วใช้ /warn")
        return
    WARNINGS[update.effective_chat.id][target.id] += 1
    await update.effective_message.reply_text(
        f"⚠️ Warn ให้ {target.full_name}: {WARNINGS[update.effective_chat.id][target.id]}"
    )


async def unwarn(update, context):
    if not await admin_only(update, context): return
    target = await target_from_reply(update)
    if not target:
        await update.effective_message.reply_text("ให้ Reply ข้อความของสมาชิกแล้วใช้ /unwarn")
        return
    WARNINGS[update.effective_chat.id][target.id] = max(
        0, WARNINGS[update.effective_chat.id][target.id] - 1
    )
    await update.effective_message.reply_text("✅ ลด Warn แล้ว")


async def mute(update, context):
    if not await admin_only(update, context): return
    target = await target_from_reply(update)
    if not target:
        await update.effective_message.reply_text("ให้ Reply ข้อความของสมาชิกแล้วใช้ /mute 10")
        return
    try:
        minutes = max(1, min(10080, int(context.args[0]))) if context.args else 10
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=int(time.time()) + minutes * 60,
        )
        await update.effective_message.reply_text(f"🔇 Mute {target.full_name} {minutes} นาที")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ ทำไม่ได้: {e}")


async def unmute(update, context):
    if not await admin_only(update, context): return
    target = await target_from_reply(update)
    if not target:
        await update.effective_message.reply_text("ให้ Reply ข้อความของสมาชิกแล้วใช้ /unmute")
        return
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=True, can_send_other_messages=True,
                                        can_add_web_page_previews=True),
        )
        await update.effective_message.reply_text("🔊 Unmute แล้ว")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ ทำไม่ได้: {e}")


async def ban(update, context):
    if not await admin_only(update, context): return
    target = await target_from_reply(update)
    if not target:
        await update.effective_message.reply_text("ให้ Reply ข้อความของสมาชิกแล้วใช้ /ban")
        return
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.effective_message.reply_text(f"🚫 Ban {target.full_name} แล้ว")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ ทำไม่ได้: {e}")


async def unban(update, context):
    if not await admin_only(update, context): return
    try:
        uid = int(context.args[0])
        await context.bot.unban_chat_member(update.effective_chat.id, uid, only_if_banned=True)
        await update.effective_message.reply_text("✅ Unban แล้ว")
    except Exception:
        await update.effective_message.reply_text("ใช้: /unban USER_ID")


async def purge(update, context):
    if not await admin_only(update, context): return
    msg = update.effective_message
    if not msg.reply_to_message:
        await msg.reply_text("ให้ Reply ข้อความเริ่มต้นแล้วใช้ /purge")
        return
    start_id = msg.reply_to_message.message_id
    deleted = 0
    for mid in range(start_id, msg.message_id + 1):
        try:
            await context.bot.delete_message(update.effective_chat.id, mid)
            deleted += 1
        except Exception:
            pass
    try:
        await msg.reply_text(f"🧹 ลบแล้ว {deleted} ข้อความ")
    except Exception:
        pass


async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmu = update.chat_member
    if not cmu or not cmu.new_chat_member:
        return
    if cmu.new_chat_member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED):
        u = cmu.new_chat_member.user
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                f"👋 ยินดีต้อนรับ {u.mention_html()} เข้ากลุ่ม!",
                parse_mode="HTML",
            )
        except Exception:
            pass


def main():
    if TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise SystemExit("กรุณาตั้ง BOT_TOKEN ก่อนรัน เช่น: export BOT_TOKEN='123:ABC...'")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("warns", warns))
    app.add_handler(CommandHandler("setwarn", setwarn))
    app.add_handler(CommandHandler("setmute", setmute))
    app.add_handler(CommandHandler("toggle", toggle))
    app.add_handler(CommandHandler("addbadword", addbadword))
    app.add_handler(CommandHandler("delbadword", delbadword))
    app.add_handler(CommandHandler("whitelist", whitelist))
    app.add_handler(CommandHandler("lock", lock))
    app.add_handler(CommandHandler("unlock", unlock))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("unwarn", unwarn))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("purge", purge))
    app.add_handler(ChatMemberHandler(welcome, ChatMemberHandler.CHAT_MEMBER))

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, moderate))
    print("ZEDEX BOT is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
