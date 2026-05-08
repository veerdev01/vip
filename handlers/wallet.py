from pyrogram import filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database import db

def register(app, ADMIN_IDS):

    @app.on_message(filters.command("balance") & filters.private)
    async def balance(client, message: Message):
        user = await db.users.find_one({"user_id": message.from_user.id})
        bal = user.get("balance", 0.0) if user else 0.0
        await message.reply(
            f"💰 **Your Wallet Balance**\n\n"
            f"Available: **${bal:.2f}**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Top-up", callback_data="topup")]
            ])
        )
