from pyrogram import filters
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from database import db
from datetime import datetime
import os

UPI_ID = os.getenv("UPI_ID", "yourname@upi")
CRYPTO_WALLET = os.getenv("CRYPTO_WALLET", "TYourTRC20WalletAddress")  # USDT TRC20

payment_states = {}

def register(app, ADMIN_IDS):

    # ─── TOPUP MENU ───────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^topup$"))
    async def topup_menu(client, query: CallbackQuery):
        await query.message.edit_text(
            "➕ **Top-up Your Wallet**\n\nChoose payment method:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🇮🇳 UPI (INR)", callback_data="pay_upi")],
                [InlineKeyboardButton("₿ Crypto (USDT TRC20)", callback_data="pay_crypto")],
                [InlineKeyboardButton("📩 Manual / Other", callback_data="pay_manual")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_home")]
            ])
        )

    # ─── UPI PAYMENT ──────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^pay_upi$"))
    async def pay_upi(client, query: CallbackQuery):
        payment_states[query.from_user.id] = {"method": "UPI", "step": "amount"}
        await query.message.edit_text(
            f"🇮🇳 **UPI Payment**\n\n"
            f"UPI ID: `{UPI_ID}`\n\n"
            f"📌 Steps:\n"
            f"1️⃣ Send money to UPI ID above\n"
            f"2️⃣ Send amount in USD you want to add\n\n"
            f"💱 Rate: **1 USD = 83 INR** (approx)\n\n"
            f"**How much USD do you want to add?**\n"
            f"Reply with amount (e.g. `10`):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="back_home")]])
        )

    # ─── CRYPTO PAYMENT ───────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^pay_crypto$"))
    async def pay_crypto(client, query: CallbackQuery):
        payment_states[query.from_user.id] = {"method": "Crypto", "step": "amount"}
        await query.message.edit_text(
            f"₿ **Crypto Payment (USDT TRC20)**\n\n"
            f"Wallet: `{CRYPTO_WALLET}`\n"
            f"Network: **TRC20 only!**\n\n"
            f"⚠️ Don't send BEP20 or ERC20!\n\n"
            f"**How much USD do you want to add?**\n"
            f"Reply with amount (e.g. `10`):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="back_home")]])
        )

    # ─── MANUAL PAYMENT ───────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^pay_manual$"))
    async def pay_manual(client, query: CallbackQuery):
        payment_states[query.from_user.id] = {"method": "Manual", "step": "amount"}
        await query.message.edit_text(
            f"📩 **Manual Payment**\n\n"
            f"Contact admin: @YourAdminUsername\n\n"  # Change this
            f"Or provide payment proof below.\n\n"
            f"**How much USD do you want to add?**\n"
            f"Reply with amount (e.g. `10`):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="back_home")]])
        )

    # ─── PAYMENT STATE HANDLER ────────────────────────────────────────────────

    @app.on_message(filters.private & ~filters.command(["start", "admin", "addproduct", "addstock", "addbalance", "broadcast"]))
    async def payment_state_handler(client, message: Message):
        uid = message.from_user.id
        if uid not in payment_states:
            return

        state = payment_states[uid]
        step = state.get("step")

        if step == "amount":
            try:
                amount = float(message.text.strip())
                if amount < 1:
                    await message.reply("❌ Minimum top-up is $1.")
                    return
            except (ValueError, AttributeError):
                await message.reply("❌ Send a valid amount like `10`")
                return

            state["amount"] = amount
            state["step"] = "proof"
            method = state["method"]

            if method == "UPI":
                inr = round(amount * 83, 2)
                await message.reply(
                    f"✅ Amount: **${amount:.2f}** (≈ ₹{inr})\n\n"
                    f"📸 Now send **screenshot/UTR** of your payment as proof:"
                )
            elif method == "Crypto":
                await message.reply(
                    f"✅ Amount: **${amount:.2f} USDT**\n\n"
                    f"📸 Now send **transaction hash/screenshot** as proof:"
                )
            else:
                await message.reply(
                    f"✅ Amount: **${amount:.2f}**\n\n"
                    f"📸 Now send **payment proof** (screenshot/UTR):"
                )

        elif step == "proof":
            amount = state["amount"]
            method = state["method"]

            # Save pending request
            req = {
                "user_id": uid,
                "username": message.from_user.username,
                "first_name": message.from_user.first_name,
                "amount": amount,
                "method": method,
                "status": "pending",
                "date": datetime.utcnow()
            }
            result = await db.topup_requests.insert_one(req)
            req_id = str(result.inserted_id)
            del payment_states[uid]

            # Notify user
            await message.reply(
                f"✅ **Payment Request Submitted!**\n\n"
                f"Amount: **${amount:.2f}**\n"
                f"Method: **{method}**\n"
                f"Request ID: `{req_id}`\n\n"
                f"⏳ Admin will verify and add balance within **1-6 hours**."
            )

            # Notify admins
            proof_text = (
                f"💰 **New Top-up Request**\n\n"
                f"User: {message.from_user.first_name} (@{message.from_user.username})\n"
                f"ID: `{uid}`\n"
                f"Amount: **${amount:.2f}**\n"
                f"Method: **{method}**\n"
                f"Request ID: `{req_id}`"
            )
            approve_btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_topup_{req_id}_{uid}_{amount}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_topup_{req_id}_{uid}")]
            ])

            for admin_id in ADMIN_IDS:
                try:
                    if message.photo:
                        await client.send_photo(admin_id, message.photo.file_id,
                                                caption=proof_text, reply_markup=approve_btn)
                    elif message.document:
                        await client.send_document(admin_id, message.document.file_id,
                                                   caption=proof_text, reply_markup=approve_btn)
                    else:
                        await client.send_message(admin_id,
                                                  f"{proof_text}\n\nProof: {message.text}",
                                                  reply_markup=approve_btn)
                except Exception:
                    pass

    # ─── APPROVE TOPUP ────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^approve_topup_(.+)_(\d+)_([\d.]+)$") & filters.user(ADMIN_IDS))
    async def approve_topup(client, query: CallbackQuery):
        req_id = query.matches[0].group(1)
        user_id = int(query.matches[0].group(2))
        amount = float(query.matches[0].group(3))

        await db.users.update_one({"user_id": user_id}, {"$inc": {"balance": amount}})
        await db.topup_requests.update_one({"_id": __import__("bson").ObjectId(req_id)},
                                           {"$set": {"status": "approved"}})

        await query.message.edit_reply_markup(None)
        await query.answer(f"✅ Approved ${amount:.2f}!", show_alert=True)
        await query.message.reply(f"✅ **Approved** ${amount:.2f} for user `{user_id}`")

        try:
            await client.send_message(user_id,
                f"🎉 **Your top-up of ${amount:.2f} has been approved!**\n\n"
                f"Your wallet has been credited. Happy shopping! 🛒")
        except Exception:
            pass

    # ─── REJECT TOPUP ─────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^reject_topup_(.+)_(\d+)$") & filters.user(ADMIN_IDS))
    async def reject_topup(client, query: CallbackQuery):
        req_id = query.matches[0].group(1)
        user_id = int(query.matches[0].group(2))

        await db.topup_requests.update_one({"_id": __import__("bson").ObjectId(req_id)},
                                           {"$set": {"status": "rejected"}})

        await query.message.edit_reply_markup(None)
        await query.answer("❌ Rejected!", show_alert=True)
        await query.message.reply(f"❌ **Rejected** top-up for user `{user_id}`")

        try:
            await client.send_message(user_id,
                "❌ **Your top-up request was rejected.**\n\n"
                "Please contact support if you believe this is an error.")
        except Exception:
            pass

    # ─── PENDING PAYMENTS (admin view) ────────────────────────────────────────

    @app.on_callback_query(filters.regex("^admin_pending_payments$") & filters.user(ADMIN_IDS))
    async def admin_pending(client, query: CallbackQuery):
        requests = await db.topup_requests.find({"status": "pending"}).to_list(20)
        if not requests:
            await query.answer("No pending payments!", show_alert=True)
            return
        text = "💰 **Pending Top-up Requests:**\n\n"
        for r in requests:
            text += (
                f"• `{r['_id']}`\n"
                f"  User: {r.get('first_name','?')} (`{r['user_id']}`)\n"
                f"  Amount: ${r['amount']:.2f} | Method: {r['method']}\n\n"
            )
        await query.message.edit_text(text[:4096], reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back")]
        ]))
