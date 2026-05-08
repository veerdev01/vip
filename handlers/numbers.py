"""
handlers/numbers.py
───────────────────
Virtual Numbers handler — Pyrogram bot + Telethon per-number session OTP listener.

Dono flows support karta hai:
  1. Userbot (bot.py wala)  — SIM account pe aaye message auto-forward
  2. Telethon session       — admin ne add kiya hua .session file se OTP auto-deliver
"""

from pyrogram import filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from database import db
from bson import ObjectId
from datetime import datetime, timedelta
import asyncio
import re
import logging
import os
from pathlib import Path

# ── Optional Telethon import ─────────────────────────────────────────────────
try:
    from telethon import TelegramClient, events
    from telethon.errors import (
        SessionPasswordNeededError,
        PhoneCodeInvalidError,
        PhoneCodeExpiredError,
    )
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

log = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────────────
NUMBER_EXPIRY_MINUTES = 20
OTP_WAIT_SECONDS      = 300   # 5 min Telethon listener timeout

SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)

API_ID   = int(os.getenv("API_ID",   "0"))
API_HASH = os.getenv("API_HASH", "")

# Active number sessions  {user_id: {number_id, number, service, expires_at, ...}}
active_sessions: dict = {}

# Telethon listener handles  {number_id: TelegramClient}
active_telethon_listeners: dict = {}

# ─── COUNTRIES ───────────────────────────────────────────────────────────────
COUNTRIES = {
    "🇮🇳 India":        "IN",
    "🇺🇸 USA":          "US",
    "🇬🇧 UK":           "GB",
    "🇷🇺 Russia":       "RU",
    "🇧🇷 Brazil":       "BR",
    "🇩🇪 Germany":      "DE",
    "🇫🇷 France":       "FR",
    "🇮🇩 Indonesia":    "ID",
    "🇵🇰 Pakistan":     "PK",
    "🇧🇩 Bangladesh":   "BD",
    "🇨🇳 China":        "CN",
    "🇯🇵 Japan":        "JP",
    "🇰🇷 South Korea":  "KR",
    "🇹🇷 Turkey":       "TR",
    "🇺🇦 Ukraine":      "UA",
    "🇵🇭 Philippines":  "PH",
    "🇻🇳 Vietnam":      "VN",
    "🇲🇾 Malaysia":     "MY",
    "🇹🇭 Thailand":     "TH",
    "🇦🇪 UAE":          "AE",
    "🇸🇦 Saudi Arabia": "SA",
    "🇳🇬 Nigeria":      "NG",
    "🇰🇪 Kenya":        "KE",
    "🇲🇽 Mexico":       "MX",
    "🇦🇷 Argentina":    "AR",
    "🇨🇦 Canada":       "CA",
    "🇦🇺 Australia":    "AU",
    "🇳🇱 Netherlands":  "NL",
    "🇵🇱 Poland":       "PL",
    "🇷🇴 Romania":      "RO",
}

SERVICES = {
    "WhatsApp":   "whatsapp",
    "Telegram":   "telegram",
    "Google":     "google",
    "Facebook":   "facebook",
    "Instagram":  "instagram",
    "Twitter/X":  "twitter",
    "TikTok":     "tiktok",
    "Snapchat":   "snapchat",
    "LinkedIn":   "linkedin",
    "Uber":       "uber",
    "Amazon":     "amazon",
    "Netflix":    "netflix",
    "Microsoft":  "microsoft",
    "Apple":      "apple",
    "PayPal":     "paypal",
    "Binance":    "binance",
    "OLX":        "olx",
    "Truecaller": "truecaller",
    "Other":      "other",
}


# ─── OTP EXTRACT HELPER ──────────────────────────────────────────────────────

def _extract_otp(text: str):
    patterns = [
        r"(?:OTP|otp)[^\d]*(\d{4,8})",
        r"(?:code|Code|CODE)[^\d]*(\d{4,8})",
        r"(?:verification|Verification)[^\d]*(\d{4,8})",
        r"(?:password|Password)[^\d]*(\d{4,8})",
        r"(\d{4,8})\s+(?:is your|hai aapka)",
        r"(?:is|are|:)\s*(\d{4,8})",
        r"(\d{6})\s+is your WhatsApp",
        r"Login code[:\s]+(\d{5})",
        r"\b(\d{6})\b",
        r"\b(\d{4,5})\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


# ─── TELETHON SESSION-BASED OTP LISTENER ─────────────────────────────────────

async def start_telethon_otp_listener(pyrogram_client, number_id, buyer_id: int, number_str: str):
    if not TELETHON_AVAILABLE:
        return

    num_doc = await db.numbers.find_one({"_id": number_id})
    if not num_doc or not num_doc.get("session_file"):
        return

    session_path = SESSIONS_DIR / num_doc["session_file"]
    if not session_path.exists():
        try:
            await pyrogram_client.send_message(buyer_id, "❌ Session file nahi mili.")
        except Exception:
            pass
        return

    session_name = str(session_path.with_suffix(""))
    client = TelegramClient(session_name, API_ID, API_HASH)
    active_telethon_listeners[number_id] = client
    received = asyncio.Event()

    @client.on(events.NewMessage)
    async def on_msg(event):
        text = event.message.text or ""
        otp  = _extract_otp(text)

        # DB update
        await db.numbers.update_one(
            {"_id": number_id},
            {"$set": {"otp_received": otp or text, "status": "used"}},
        )

        reply = f"📨 **Naya Message!**\n\n📞 `{number_str}`\n💬 `{text}`"
        if otp:
            reply += f"\n\n🔐 **OTP: `{otp}`**"

        try:
            await pyrogram_client.send_message(
                buyer_id, reply,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🏠 Main Menu", callback_data="back_home")]]
                ),
            )
        except Exception as e:
            log.error("[Telethon OTP] send error: %s", e)

        if buyer_id in active_sessions:
            del active_sessions[buyer_id]
        received.set()

    try:
        await client.connect()
        try:
            await asyncio.wait_for(received.wait(), timeout=OTP_WAIT_SECONDS)
        except asyncio.TimeoutError:
            try:
                await pyrogram_client.send_message(
                    buyer_id,
                    f"⏰ **Timeout!** {OTP_WAIT_SECONDS // 60} min mein OTP nahi aaya.\n"
                    "Support se contact karein.",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("📱 New Number Lo", callback_data="numbers_menu")]]
                    ),
                )
            except Exception:
                pass
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        active_telethon_listeners.pop(number_id, None)


# ─── AUTO EXPIRE BACKGROUND TASK ─────────────────────────────────────────────

async def _auto_expire_number(client, user_id: int, number_id, expires_at: datetime):
    wait = (expires_at - datetime.utcnow()).total_seconds()
    if wait > 0:
        await asyncio.sleep(wait)

    session = active_sessions.get(user_id)
    if not session or session.get("number_id") != number_id:
        return

    await db.numbers.update_one(
        {"_id": number_id, "status": "in_use"},
        {"$set": {
            "status":       "available",
            "assigned_to":  None,
            "service":      None,
            "expires_at":   None,
            "otp_received": None,
        }},
    )
    if user_id in active_sessions:
        del active_sessions[user_id]

    try:
        await client.send_message(
            user_id,
            f"⏰ **Number Expire Ho Gaya!**\n\n"
            f"📞 Number `{session['number']}` ka {NUMBER_EXPIRY_MINUTES} min khatam.\n"
            "OTP nahi aaya — number release kar diya.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 New Number Lo", callback_data="numbers_menu")],
                [InlineKeyboardButton("🏠 Main Menu",     callback_data="back_home")],
            ]),
        )
    except Exception:
        pass


# ─── KEYBOARD HELPERS ─────────────────────────────────────────────────────────

def _country_keyboard():
    items   = list(COUNTRIES.items())
    buttons = []
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(n, callback_data=f"num_country_{c}") for n, c in items[i:i+2]]
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
    return InlineKeyboardMarkup(buttons)


def _service_keyboard(country_code: str):
    items   = list(SERVICES.items())
    buttons = []
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(n, callback_data=f"num_service_{country_code}_{k}") for n, k in items[i:i+2]]
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 Country Change", callback_data="numbers_menu")])
    return InlineKeyboardMarkup(buttons)


# ─── REGISTER ALL HANDLERS ────────────────────────────────────────────────────

def register(app, ADMIN_IDS):

    # ═══ USER FLOW ════════════════════════════════════════════════════════════

    @app.on_callback_query(filters.regex("^numbers_menu$"))
    async def numbers_menu(client, query: CallbackQuery):
        user    = await db.users.find_one({"user_id": query.from_user.id})
        balance = user.get("balance", 0.0) if user else 0.0

        session = active_sessions.get(query.from_user.id)
        if session and datetime.utcnow() < session["expires_at"]:
            remaining = int((session["expires_at"] - datetime.utcnow()).total_seconds() / 60)
            await query.message.edit_text(
                f"📱 **Virtual Numbers**\n\n"
                f"⚠️ Tumhare paas pehle se ek active number hai!\n\n"
                f"📞 Number: `{session['number']}`\n"
                f"🌍 Country: {session['country']}\n"
                f"📲 Service: {session['service']}\n"
                f"⏳ Expires in: **{remaining} min**",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📩 OTP Check Karo",    callback_data="number_check_otp")],
                    [InlineKeyboardButton("❌ Number Cancel Karo", callback_data="number_cancel")],
                    [InlineKeyboardButton("🔙 Back",               callback_data="back_home")],
                ]),
            )
            return

        await query.message.edit_text(
            f"📱 **Virtual Numbers**\n\n"
            f"👛 Balance: **${balance:.2f}**\n\n"
            f"✅ Temporary virtual numbers\n"
            f"✅ OTP is bot pe receive hoga\n"
            f"✅ {NUMBER_EXPIRY_MINUTES} min validity\n"
            f"✅ All countries & services available\n\n"
            f"Pehle **country** select karo:",
            reply_markup=_country_keyboard(),
        )

    @app.on_callback_query(filters.regex(r"^num_country_(.+)$"))
    async def num_country_select(client, query: CallbackQuery):
        cc   = query.matches[0].group(1)
        name = next((k for k, v in COUNTRIES.items() if v == cc), cc)
        cnt  = await db.numbers.count_documents({"country_code": cc, "status": "available"})
        if cnt == 0:
            await query.answer(f"❌ {name} mein koi number available nahi!", show_alert=True)
            return
        await query.message.edit_text(
            f"🌍 Country: **{name}**\n📦 Available: **{cnt} numbers**\n\nAb **service** select karo:",
            reply_markup=_service_keyboard(cc),
        )

    @app.on_callback_query(filters.regex(r"^num_service_(.+)_(.+)$"))
    async def num_service_select(client, query: CallbackQuery):
        cc           = query.matches[0].group(1)
        svc_key      = query.matches[0].group(2)
        svc_name     = next((k for k, v in SERVICES.items() if v == svc_key), svc_key)
        country_name = next((k for k, v in COUNTRIES.items() if v == cc), cc)

        price_doc = await db.number_prices.find_one({
            "$or": [
                {"country_code": cc,        "service": svc_key},
                {"country_code": cc,        "service": "default"},
                {"country_code": "default", "service": "default"},
            ]
        })
        price = price_doc["price"] if price_doc else 1.00
        cnt   = await db.numbers.count_documents({"country_code": cc, "status": "available"})
        if cnt == 0:
            await query.answer("❌ Is country mein numbers available nahi!", show_alert=True)
            return

        user    = await db.users.find_one({"user_id": query.from_user.id})
        balance = user.get("balance", 0.0) if user else 0.0

        await query.message.edit_text(
            f"📱 **Order Summary**\n\n"
            f"🌍 Country: **{country_name}**\n"
            f"📲 Service: **{svc_name}**\n"
            f"💰 Price: **${price:.2f}**\n"
            f"⏳ Validity: **{NUMBER_EXPIRY_MINUTES} minutes**\n"
            f"📦 Available: **{cnt} numbers**\n\n"
            f"👛 Your Balance: **${balance:.2f}**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"✅ Buy Number — ${price:.2f}",
                    callback_data=f"num_buy_{cc}_{svc_key}_{price}",
                )],
                [InlineKeyboardButton("🔙 Service Change", callback_data=f"num_country_{cc}")],
                [InlineKeyboardButton("🏠 Cancel",          callback_data="back_home")],
            ]),
        )

    @app.on_callback_query(filters.regex(r"^num_buy_(.+)_(.+)_(.+)$"))
    async def num_buy(client, query: CallbackQuery):
        cc       = query.matches[0].group(1)
        svc_key  = query.matches[0].group(2)
        price    = float(query.matches[0].group(3))
        svc_name = next((k for k, v in SERVICES.items() if v == svc_key), svc_key)
        cn       = next((k for k, v in COUNTRIES.items() if v == cc), cc)
        exp      = datetime.utcnow() + timedelta(minutes=NUMBER_EXPIRY_MINUTES)

        # Atomic reserve
        reserved = await db.numbers.find_one_and_update(
            {"country_code": cc, "status": "available"},
            {"$set": {
                "status":       "in_use",
                "assigned_to":  query.from_user.id,
                "service":      svc_key,
                "expires_at":   exp,
                "assigned_at":  datetime.utcnow(),
                "otp_received": None,
            }},
            return_document=False,
        )
        if not reserved:
            await query.answer("❌ Number available nahi! Dobara try karo.", show_alert=True)
            return

        # Atomic balance deduct
        bal_upd = await db.users.find_one_and_update(
            {"user_id": query.from_user.id, "balance": {"$gte": price}},
            {"$inc": {"balance": -price}},
        )
        if not bal_upd:
            await db.numbers.update_one(
                {"_id": reserved["_id"]},
                {"$set": {"status": "available", "assigned_to": None, "service": None, "expires_at": None}},
            )
            await query.answer("❌ Balance insufficient!", show_alert=True)
            return

        active_sessions[query.from_user.id] = {
            "number_id":    reserved["_id"],
            "number":       reserved["number"],
            "country":      cn,
            "country_code": cc,
            "service":      svc_name,
            "service_key":  svc_key,
            "price":        price,
            "expires_at":   exp,
            "otp":          None,
        }
        await db.orders.insert_one({
            "user_id":      query.from_user.id,
            "username":     query.from_user.username,
            "type":         "number",
            "number":       reserved["number"],
            "country":      cn,
            "country_code": cc,
            "service":      svc_name,
            "price":        price,
            "status":       "waiting_otp",
            "date":         datetime.utcnow(),
            "expires_at":   exp,
        })

        await query.message.edit_text(
            f"✅ **Number Assign Ho Gaya!**\n\n"
            f"📞 **Number:** `{reserved['number']}`\n"
            f"🌍 Country: **{cn}**\n"
            f"📲 Service: **{svc_name}**\n"
            f"⏳ Expires: **{NUMBER_EXPIRY_MINUTES} min baad**\n\n"
            f"👆 Is number pe **{svc_name}** ka OTP mangao.\n"
            f"OTP aate hi yahan automatically forward ho jaayega!\n\n"
            f"⚠️ {NUMBER_EXPIRY_MINUTES} min mein OTP nahi aaya toh number expire ho jaayega.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 OTP Check Karo",        callback_data="number_check_otp")],
                [InlineKeyboardButton("❌ Cancel / Release Number", callback_data="number_cancel")],
            ]),
        )

        asyncio.create_task(
            _auto_expire_number(client, query.from_user.id, reserved["_id"], exp)
        )

        # Telethon session listener (agar session_file available hai)
        if TELETHON_AVAILABLE and reserved.get("session_file"):
            asyncio.create_task(
                start_telethon_otp_listener(client, reserved["_id"], query.from_user.id, reserved["number"])
            )

    @app.on_callback_query(filters.regex("^number_check_otp$"))
    async def number_check_otp(client, query: CallbackQuery):
        session = active_sessions.get(query.from_user.id)
        if not session:
            await query.answer("❌ Koi active number nahi!", show_alert=True)
            return
        if datetime.utcnow() > session["expires_at"]:
            await query.answer("⏰ Number expire ho gaya!", show_alert=True)
            del active_sessions[query.from_user.id]
            return

        num_doc   = await db.numbers.find_one({"_id": session["number_id"]})
        remaining = int((session["expires_at"] - datetime.utcnow()).total_seconds() / 60)
        rem_sec   = int((session["expires_at"] - datetime.utcnow()).total_seconds() % 60)

        if num_doc and num_doc.get("otp_received"):
            otp = num_doc["otp_received"]
            await query.message.edit_text(
                f"🎉 **OTP Received!**\n\n"
                f"📞 Number: `{session['number']}`\n"
                f"📲 Service: **{session['service']}**\n\n"
                f"🔐 **OTP: `{otp}`**\n\n✅ Jaldi use karo!",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🏠 Main Menu", callback_data="back_home")]]
                ),
            )
            del active_sessions[query.from_user.id]
            await db.numbers.update_one({"_id": session["number_id"]}, {"$set": {"status": "used"}})
        else:
            await query.answer(
                f"⏳ OTP abhi nahi aaya. {remaining}m {rem_sec}s baki.", show_alert=True
            )

    @app.on_callback_query(filters.regex("^number_cancel$"))
    async def number_cancel(client, query: CallbackQuery):
        session = active_sessions.get(query.from_user.id)
        if not session:
            await query.answer("Koi active number nahi!", show_alert=True)
            return

        await db.numbers.update_one(
            {"_id": session["number_id"]},
            {"$set": {
                "status":       "available",
                "assigned_to":  None,
                "service":      None,
                "expires_at":   None,
                "otp_received": None,
            }},
        )
        del active_sessions[query.from_user.id]
        await query.message.edit_text(
            "❌ **Number Cancel Ho Gaya**\n\n"
            "⚠️ Number cancel karne par refund nahi milega.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 New Number Lo", callback_data="numbers_menu")],
                [InlineKeyboardButton("🏠 Main Menu",     callback_data="back_home")],
            ]),
        )

    # ═══ ADMIN COMMANDS ═══════════════════════════════════════════════════════

    @app.on_message(filters.command("sendotp") & filters.user(ADMIN_IDS) & filters.private)
    async def sendotp_cmd(client, message: Message):
        args = message.text.split()
        if len(args) < 3:
            await message.reply("Usage: `/sendotp <number> <otp>`")
            return
        number, otp = args[1].strip(), args[2].strip()
        num_doc = await db.numbers.find_one({"number": number, "status": "in_use"})
        if not num_doc:
            await message.reply(f"❌ Number `{number}` in use nahi hai.")
            return
        user_id = num_doc.get("assigned_to")
        if not user_id:
            await message.reply("❌ Is number ka koi owner nahi.")
            return
        await db.numbers.update_one({"_id": num_doc["_id"]}, {"$set": {"otp_received": otp, "status": "used"}})
        if user_id in active_sessions:
            active_sessions[user_id]["otp"] = otp
        try:
            svc = active_sessions.get(user_id, {}).get("service", num_doc.get("service", "?"))
            await client.send_message(
                user_id,
                f"🎉 **OTP Received!**\n\n📞 Number: `{number}`\n📲 Service: **{svc}**\n\n🔐 **OTP: `{otp}`**\n\n✅ Jaldi use karo!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="back_home")]]),
            )
            if user_id in active_sessions:
                del active_sessions[user_id]
            await message.reply(f"✅ OTP `{otp}` user `{user_id}` ko send ho gaya!")
        except Exception as e:
            await message.reply(f"❌ User ko message nahi bhej paya: {e}")

    @app.on_message(filters.command("addnumber") & filters.user(ADMIN_IDS) & filters.private)
    async def addnumber_cmd(client, message: Message):
        args = message.text.split()
        if len(args) < 3:
            await message.reply("Usage: `/addnumber <number> <country_code>`\nExample: `/addnumber +919876543210 IN`")
            return
        number, cc = args[1].strip(), args[2].strip().upper()
        if await db.numbers.find_one({"number": number}):
            await message.reply(f"❌ Number `{number}` pehle se exist karta hai!")
            return
        await db.numbers.insert_one({
            "number": number, "country_code": cc, "status": "available",
            "assigned_to": None, "service": None, "expires_at": None,
            "otp_received": None, "session_file": None, "added_at": datetime.utcnow(),
        })
        await message.reply(f"✅ Number `{number}` (`{cc}`) add ho gaya!")

    @app.on_message(filters.command("addnumbers") & filters.user(ADMIN_IDS) & filters.private)
    async def addnumbers_bulk(client, message: Message):
        args = message.text.split()
        if len(args) < 2:
            await message.reply("Usage: `/addnumbers <country_code>`\nPhir reply mein numbers bhejo (ek per line).")
            return
        cc = args[1].strip().upper()
        if not message.reply_to_message or not message.reply_to_message.text:
            await message.reply("Reply karo us message ko jisme numbers hain.")
            return
        lines = [l.strip() for l in message.reply_to_message.text.splitlines() if l.strip()]
        added = skipped = 0
        for num in lines:
            if await db.numbers.find_one({"number": num}):
                skipped += 1
                continue
            await db.numbers.insert_one({
                "number": num, "country_code": cc, "status": "available",
                "assigned_to": None, "service": None, "expires_at": None,
                "otp_received": None, "session_file": None, "added_at": datetime.utcnow(),
            })
            added += 1
        await message.reply(f"✅ Bulk Add: **{added}** added | **{skipped}** skipped (duplicate)")

    # ── /addnumbersession — Telethon session add karo ─────────────────────────

    _pending: dict = {}   # {admin_id: state}

    @app.on_message(filters.command("addnumbersession") & filters.user(ADMIN_IDS) & filters.private)
    async def addnumbersession_cmd(client, message: Message):
        if not TELETHON_AVAILABLE:
            await message.reply("❌ Telethon install nahi. `pip install telethon` karo.")
            return
        args = message.text.split()
        if len(args) < 3:
            await message.reply(
                "Usage: `/addnumbersession <phone> <country_code>`\n\n"
                "Example: `/addnumbersession +919876543210 IN`\n\n"
                "Telethon se OTP maangega → session save karega → "
                "jab user number kharide auto OTP forward hoga."
            )
            return

        phone = args[1].strip()
        cc    = args[2].strip().upper()
        safe  = phone.replace("+", "").replace(" ", "")
        spath = str(SESSIONS_DIR / safe)

        await message.reply(f"📲 OTP bheja ja raha hai `{phone}` pe... ⏳")
        try:
            tc = TelegramClient(spath, API_ID, API_HASH)
            await tc.connect()
            if await tc.is_user_authorized():
                await tc.disconnect()
                await _save_session_db(client, message, phone, cc, safe + ".session")
                return
            sent = await tc.send_code_request(phone)
            _pending[message.from_user.id] = {
                "step": "otp", "phone": phone, "cc": cc, "safe": safe,
                "hash": sent.phone_code_hash, "tc": tc,
            }
            await message.reply(f"✅ OTP bhej diya `{phone}` pe!\n\n🔢 OTP type karein:")
        except Exception as e:
            await message.reply(f"❌ Error: `{e}`")

    @app.on_message(filters.text & filters.user(ADMIN_IDS) & filters.private)
    async def session_flow_handler(client, message: Message):
        uid = message.from_user.id
        if uid not in _pending:
            return
        st   = _pending[uid]
        step = st["step"]
        txt  = message.text.strip()

        if step == "otp":
            try:
                await st["tc"].sign_in(st["phone"], txt, phone_code_hash=st["hash"])
                await st["tc"].disconnect()
                del _pending[uid]
                await _save_session_db(client, message, st["phone"], st["cc"], st["safe"] + ".session")
            except SessionPasswordNeededError:
                st["step"] = "2fa"
                await message.reply("🔐 **2FA On Hai!**\n\n2FA password dalein:")
            except PhoneCodeInvalidError:
                await message.reply("❌ **OTP Galat!** Dobara dalein:")
            except PhoneCodeExpiredError:
                try: await st["tc"].disconnect()
                except Exception: pass
                del _pending[uid]
                await message.reply("⏰ OTP expire! `/addnumbersession` se dobara try karein.")
            except Exception as e:
                try: await st["tc"].disconnect()
                except Exception: pass
                del _pending[uid]
                await message.reply(f"❌ Error: `{e}`")

        elif step == "2fa":
            try:
                await st["tc"].sign_in(password=txt)
                await st["tc"].disconnect()
                del _pending[uid]
                await _save_session_db(client, message, st["phone"], st["cc"], st["safe"] + ".session")
            except Exception as e:
                if "password" in str(e).lower() or "invalid" in str(e).lower():
                    await message.reply("❌ **2FA Password Galat!** Dobara dalein:")
                else:
                    try: await st["tc"].disconnect()
                    except Exception: pass
                    del _pending[uid]
                    await message.reply(f"❌ 2FA Error: `{e}`")

    async def _save_session_db(client, message, phone, cc, session_file):
        existing = await db.numbers.find_one({"number": phone})
        if existing:
            await db.numbers.update_one({"number": phone}, {"$set": {"session_file": session_file}})
            await message.reply(
                f"✅ **Session Updated!**\n\n📞 `{phone}` ka session link ho gaya.\n📂 `{session_file}`"
            )
        else:
            await db.numbers.insert_one({
                "number": phone, "country_code": cc, "status": "available",
                "assigned_to": None, "service": None, "expires_at": None,
                "otp_received": None, "session_file": session_file, "added_at": datetime.utcnow(),
            })
            await message.reply(
                f"🎉 **Number + Session Add Ho Gaya!**\n\n"
                f"📞 `{phone}` (`{cc}`)\n📂 Session: `{session_file}`\n\n"
                f"✅ Jab bhi koi user ye number kharide, Telethon OTP auto-forward karega!"
            )

    @app.on_message(filters.command("setnumberprice") & filters.user(ADMIN_IDS) & filters.private)
    async def set_number_price(client, message: Message):
        args = message.text.split()
        if len(args) < 4:
            await message.reply("Usage: `/setnumberprice <country_code> <service> <price>`")
            return
        cc, svc = args[1].upper(), args[2].lower()
        try:
            price = float(args[3])
        except ValueError:
            await message.reply("❌ Invalid price.")
            return
        await db.number_prices.update_one(
            {"country_code": cc, "service": svc},
            {"$set": {"price": price, "updated_at": datetime.utcnow()}},
            upsert=True,
        )
        await message.reply(f"✅ Price set!\nCountry: `{cc}` | Service: `{svc}` | Price: **${price:.2f}**")

    @app.on_message(filters.command("listnumbers") & filters.user(ADMIN_IDS) & filters.private)
    async def list_numbers(client, message: Message):
        pipeline = [
            {"$group": {"_id": {"country": "$country_code", "status": "$status"}, "count": {"$sum": 1}}},
            {"$sort": {"_id.country": 1}},
        ]
        results = await db.numbers.aggregate(pipeline).to_list(100)
        if not results:
            await message.reply("Koi number nahi hai DB mein.")
            return
        from collections import defaultdict
        by_c = defaultdict(dict)
        for r in results:
            by_c[r["_id"]["country"]][r["_id"]["status"]] = r["count"]
        text = "📱 **Numbers Stock:**\n\n"
        for c, st in sorted(by_c.items()):
            text += f"**{c}**: ✅{st.get('available',0)} | 🔄{st.get('in_use',0)} in use | ✔️{st.get('used',0)} used\n"
        await message.reply(text[:4096])

    @app.on_message(filters.command("activenumbers") & filters.user(ADMIN_IDS) & filters.private)
    async def active_numbers_cmd(client, message: Message):
        if not active_sessions:
            await message.reply("Koi active session nahi hai abhi.")
            return
        text = "🔄 **Active Number Sessions:**\n\n"
        for uid, s in active_sessions.items():
            rem = max(0, int((s["expires_at"] - datetime.utcnow()).total_seconds() / 60))
            text += f"👤 `{uid}` | 📞 `{s['number']}` | 🌍 {s['country']} | 📲 {s['service']} | ⏳ {rem}m\n"
        await message.reply(text[:4096])

    @app.on_message(filters.command("sessionstatus") & filters.user(ADMIN_IDS) & filters.private)
    async def session_status_cmd(client, message: Message):
        if not TELETHON_AVAILABLE:
            await message.reply("❌ Telethon install nahi hai.")
            return
        files  = list(SESSIONS_DIR.glob("*.session"))
        active = list(active_telethon_listeners.keys())
        text   = f"📁 **Telethon Sessions**\n\nFiles: **{len(files)}** | Active listeners: **{len(active)}**\n\n"
        for f in files:
            doc    = await db.numbers.find_one({"session_file": f.name})
            status = doc["status"] if doc else "unlinked"
            num    = doc["number"] if doc else "N/A"
            icon   = "🟢" if doc else "🔴"
            text  += f"{icon} `{f.name}` — `{num}` ({status})\n"
        await message.reply(text[:4096])
