import os
import asyncio
import re
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from database import db
from handlers import admin, shop, payment, wallet, vps, numbers
from handlers.numbers import active_sessions

load_dotenv()

API_ID    = int(os.getenv("API_ID"))
API_HASH  = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))

# ─── BOT CLIENT ───────────────────────────────────────────────────────────────
app = Client(
    "cloud_shop_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ─── USERBOT CLIENT ───────────────────────────────────────────────────────────
# SIM wale Telegram account se login hoga
# Pehli baar: phone number + OTP maangega terminal mein
# Baad mein: "userbot_session.session" file se auto-login
userbot = Client(
    "userbot_session",
    api_id=API_ID,
    api_hash=API_HASH
    # BOT_TOKEN nahi — real user account hai
)

# ─── START ────────────────────────────────────────────────────────────────────

@app.on_message(filters.command("start") & filters.private)
async def start(client, message: Message):
    user = message.from_user
    await db.users.update_one(
        {"user_id": user.id},
        {"$setOnInsert": {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "balance": 0.0,
            "orders": []
        }},
        upsert=True
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Buy Cloud Accounts", callback_data="buy_products"),
         InlineKeyboardButton("🖥️ Buy VPS",            callback_data="vps_list")],
        [InlineKeyboardButton("📱 Virtual Numbers",    callback_data="numbers_menu"),
         InlineKeyboardButton("➕ Top-up",              callback_data="topup")],
        [InlineKeyboardButton("📦 Available Products", callback_data="available_products"),
         InlineKeyboardButton("👤 My Account",         callback_data="my_account")],
        [InlineKeyboardButton("🆘 Support",            callback_data="support"),
         InlineKeyboardButton("💰 Refund Policy",      callback_data="refund")],
        [InlineKeyboardButton("📜 Terms",              callback_data="terms")]
    ])

    await message.reply_photo(
        photo="https://i.imgur.com/cloud_banner.png",  # apna banner URL daalo
        caption=(
            f"☁️ **Welcome to Cloud Shop, {user.first_name}!**\n\n"
            "Premium cloud accounts, VPS & virtual numbers.\n\n"
            "✅ AWS • Azure • GCP • DigitalOcean\n"
            "🖥️ VPS Plans | 📱 Virtual Numbers (Auto OTP)\n\n"
            "Neeche se option choose karo:"
        ),
        reply_markup=keyboard
    )

# ─── REGISTER BOT HANDLERS ────────────────────────────────────────────────────

shop.register(app)
admin.register(app, ADMIN_IDS)
payment.register(app, ADMIN_IDS)
wallet.register(app, ADMIN_IDS)
vps.register(app, ADMIN_IDS)
numbers.register(app, ADMIN_IDS)

# ─── USERBOT: AUTO SMS/OTP LISTENER ──────────────────────────────────────────

@userbot.on_message(filters.incoming & filters.private)
async def userbot_sms_listener(client, message: Message):
    """
    Jab bhi userbot account pe koi SMS/message aaye:
    1. Active sessions mein number match dhundo
    2. OTP extract karo
    3. Bot ke through us user ko forward karo
    """
    if not message.text:
        return

    msg_text = message.text
    sender = message.from_user

    # ── Active session se number match karo ───────────────────────────────────
    matched_user_id = None
    matched_session = None

    for uid, session in list(active_sessions.items()):
        number = session.get("number", "")
        # Number ke sirf digits nikalo (format vary kar sakta hai)
        number_digits = re.sub(r'\D', '', number)
        msg_clean = msg_text.replace(" ", "").replace("-", "")

        if number_digits and (
            number_digits in msg_clean or
            number_digits[-10:] in msg_clean
        ):
            matched_user_id = uid
            matched_session = session
            break

    if not matched_session:
        return  # Koi active session nahi mila

    # ── OTP extract karo ──────────────────────────────────────────────────────
    otp = _extract_otp(msg_text)
    number  = matched_session["number"]
    service = matched_session.get("service", "Unknown")

    # ── DB update ──────────────────────────────────────────────────────────────
    await db.numbers.update_one(
        {"_id": matched_session["number_id"]},
        {"$set": {"otp_received": otp or msg_text, "status": "used"}}
    )

    # ── Bot se user ko message bhejo ──────────────────────────────────────────
    if otp:
        text = (
            f"🎉 **OTP Received!**\n\n"
            f"📞 Number: `{number}`\n"
            f"📲 Service: **{service}**\n\n"
            f"🔐 **OTP Code: `{otp}`**\n\n"
            f"⚡ Jaldi use karo!\n\n"
            f"📩 Full SMS:\n`{msg_text}`"
        )
    else:
        text = (
            f"📩 **SMS Received!**\n\n"
            f"📞 Number: `{number}`\n"
            f"📲 Service: **{service}**\n\n"
            f"💬 Message:\n`{msg_text}`\n\n"
            f"⚠️ OTP automatically detect nahi hua — upar message dekho."
        )

    try:
        await app.send_message(
            matched_user_id,
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 New Number Lo", callback_data="numbers_menu")],
                [InlineKeyboardButton("🏠 Main Menu",     callback_data="back_home")]
            ])
        )
        # Session cleanup — number use ho gaya
        if matched_user_id in active_sessions:
            del active_sessions[matched_user_id]

        print(f"[OTP] Delivered to user {matched_user_id} | Number: {number} | OTP: {otp}")

    except Exception as e:
        print(f"[OTP ERROR] User {matched_user_id} ko deliver nahi hua: {e}")


def _extract_otp(text: str):
    """
    SMS text se OTP/verification code dhundho.
    Multiple patterns handle karta hai — English + Hindi SMS dono.
    """
    patterns = [
        # Explicit keywords pehle check karo (accurate)
        r'(?:OTP|otp)[^\d]*(\d{4,8})',
        r'(?:code|Code|CODE)[^\d]*(\d{4,8})',
        r'(?:verification|Verification)[^\d]*(\d{4,8})',
        r'(?:password|Password)[^\d]*(\d{4,8})',
        r'(\d{4,8})\s+(?:is your|hai aapka|है आपका)',
        r'(?:is|are|:)\s*(\d{4,8})',
        # WhatsApp specific
        r'(\d{6})\s+is your WhatsApp',
        # Telegram specific
        r'Login code[:\s]+(\d{5})',
        # Generic 6 digit (most OTPs)
        r'\b(\d{6})\b',
        # 4-5 digit fallback
        r'\b(\d{4,5})\b',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


# ─── RUN BOT + USERBOT TOGETHER ───────────────────────────────────────────────

async def main():
    print("=" * 50)
    print("🚀 Cloud Shop Bot starting...")
    print("=" * 50)

    async with app, userbot:
        me_user = await userbot.get_me()
        me_bot  = await app.get_me()

        print(f"✅ Bot:     @{me_bot.username}")
        print(f"✅ Userbot: {me_user.first_name} | +{me_user.phone_number}")
        print(f"✅ Admins:  {ADMIN_IDS}")
        print("=" * 50)
        print("📡 Listening for messages...")

        # Admin ko startup notification
        for admin_id in ADMIN_IDS:
            try:
                await app.send_message(
                    admin_id,
                    f"✅ **Bot Started!**\n\n"
                    f"🤖 Bot: @{me_bot.username}\n"
                    f"📱 Userbot: {me_user.first_name} (+{me_user.phone_number})\n\n"
                    f"Auto OTP delivery active hai! 🎯"
                )
            except Exception:
                pass

        await asyncio.Event().wait()  # forever run karo


if __name__ == "__main__":
    asyncio.run(main())
