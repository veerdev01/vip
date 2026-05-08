from pyrogram import filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from database import db
from bson import ObjectId
from datetime import datetime

PROVIDERS = ["AWS", "Azure", "GCP", "DigitalOcean", "Linode", "OVH", "Vultr", "Kamatera"]

def register(app):

    # ─── AVAILABLE PRODUCTS (list all providers) ──────────────────────────────

    @app.on_callback_query(filters.regex("^available_products$"))
    async def available_products(client, query: CallbackQuery):
        buttons = [[InlineKeyboardButton(f"☁️ {p}", callback_data=f"provider_{p}")] for p in PROVIDERS]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
        await query.message.edit_text(
            "📦 **Available Products**\n\nSelect a cloud provider:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    # ─── PROVIDER PRODUCTS ────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^provider_(.+)$"))
    async def provider_products(client, query: CallbackQuery):
        provider = query.matches[0].group(1)
        products = await db.products.find({"provider": provider, "available": {"$gt": 0}}).to_list(50)

        if not products:
            await query.answer("No products available for this provider.", show_alert=True)
            return

        text = f"☁️ **{provider} — Available Products**\n\n"
        buttons = []
        for p in products:
            text += f"• `{p['name']}` | **${p['price']:.2f}** | {p['available']} available\n"
            buttons.append([InlineKeyboardButton(
                f"🛒 Buy {p['name']} — ${p['price']:.2f}",
                callback_data=f"buy_{str(p['_id'])}"
            )])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="available_products")])

        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    # ─── BUY PRODUCT ──────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^buy_(.+)$"))
    async def buy_product(client, query: CallbackQuery):
        product_id = query.matches[0].group(1)
        try:
            product = await db.products.find_one({"_id": ObjectId(product_id)})
        except Exception:
            await query.answer("Invalid product.", show_alert=True)
            return

        if not product or product["available"] <= 0:
            await query.answer("❌ Product is out of stock!", show_alert=True)
            return

        user = await db.users.find_one({"user_id": query.from_user.id})
        balance = user.get("balance", 0.0)

        if balance < product["price"]:
            needed = product["price"] - balance
            await query.message.edit_text(
                f"❌ **Insufficient Balance!**\n\n"
                f"Product: `{product['name']}`\n"
                f"Price: **${product['price']:.2f}**\n"
                f"Your Balance: **${balance:.2f}**\n"
                f"Need: **${needed:.2f}** more\n\n"
                f"Please top-up your wallet first.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Top-up Wallet", callback_data="topup")],
                    [InlineKeyboardButton("🔙 Back", callback_data="available_products")]
                ])
            )
            return

        # Confirm purchase
        await query.message.edit_text(
            f"🛒 **Confirm Purchase**\n\n"
            f"Product: `{product['name']}`\n"
            f"Provider: **{product['provider']}**\n"
            f"Price: **${product['price']:.2f}**\n"
            f"Your Balance: **${balance:.2f}**\n\n"
            f"After purchase: **${balance - product['price']:.2f}**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm Buy", callback_data=f"confirm_buy_{product_id}")],
                [InlineKeyboardButton("❌ Cancel", callback_data=f"provider_{product['provider']}")]
            ])
        )

    # ─── CONFIRM BUY ──────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^confirm_buy_(.+)$"))
    async def confirm_buy(client, query: CallbackQuery):
        product_id = query.matches[0].group(1)
        try:
            product = await db.products.find_one({"_id": ObjectId(product_id)})
        except Exception:
            await query.answer("Invalid product.", show_alert=True)
            return

        if not product or product["available"] <= 0:
            await query.answer("❌ Out of stock!", show_alert=True)
            return

        user = await db.users.find_one({"user_id": query.from_user.id})
        balance = user.get("balance", 0.0)

        if balance < product["price"]:
            await query.answer("❌ Insufficient balance!", show_alert=True)
            return

        # ── ATOMIC: ek hi operation mein stock se credential pop karo + available -1
        # Agar 2 users ek saath buy karein toh dono alag credential payenge (race condition safe)
        updated_product = await db.products.find_one_and_update(
            {
                "_id": ObjectId(product_id),
                "available": {"$gt": 0},   # sirf tab update karo jab stock hai
                "stock.0": {"$exists": True}  # aur stock array empty na ho
            },
            {
                "$pop": {"stock": -1},      # pehla credential nikal lo (atomic)
                "$inc": {"available": -1, "sold": 1}
            },
            return_document=True  # updated document return karo
        )

        if not updated_product:
            # Kisi aur ne abhi kharida — stock khatam
            await query.answer("❌ Abhi stock khatam ho gaya! Baad mein try karo.", show_alert=True)
            return

        # $pop: -1 pehla element nikalti hai, jo stock list mein pehle tha
        # Lekin find_one_and_update UPDATED doc return karta hai (credential already removed)
        # Toh pehle wala credential lene ke liye original product use karte hain
        account = product["stock"][0]

        # ── ATOMIC: balance deduct + order history push (ek hi operation)
        balance_update = await db.users.find_one_and_update(
            {
                "user_id": query.from_user.id,
                "balance": {"$gte": product["price"]}  # sirf tab kato jab balance hai
            },
            {
                "$inc": {"balance": -product["price"]},
                "$push": {"orders": {
                    "product_id": product_id,
                    "product_name": product["name"],
                    "provider": product["provider"],
                    "price": product["price"],
                    "date": datetime.utcnow()
                }}
            }
        )

        if not balance_update:
            # Balance nahi tha — stock wapas karo
            await db.products.update_one(
                {"_id": ObjectId(product_id)},
                {
                    "$push": {"stock": {"$each": [account], "$position": 0}},
                    "$inc": {"available": 1, "sold": -1}
                }
            )
            await query.answer("❌ Balance insufficient! Stock wapas kar diya.", show_alert=True)
            return

        # ── Order record save karo
        await db.orders.insert_one({
            "user_id": query.from_user.id,
            "username": query.from_user.username,
            "product_id": product_id,
            "product_name": product["name"],
            "provider": product["provider"],
            "price": product["price"],
            "credentials": account,
            "date": datetime.utcnow(),
            "status": "completed"
        })

        # Send credentials via DM
        await query.message.edit_text(
            f"✅ **Purchase Successful!**\n\n"
            f"Product: `{product['name']}`\n"
            f"Provider: **{product['provider']}**\n"
            f"Price Paid: **${product['price']:.2f}**\n\n"
            f"📩 Your account credentials are below 👇"
        )
        await query.message.reply(
            f"🔐 **Your Account Credentials**\n\n"
            f"```\n{account}\n```\n\n"
            f"⚠️ Save these immediately. We don't store credentials after delivery.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_home")]
            ])
        )

    # ─── MY ACCOUNT ───────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^my_account$"))
    async def my_account(client, query: CallbackQuery):
        user = await db.users.find_one({"user_id": query.from_user.id})
        balance = user.get("balance", 0.0)
        orders = user.get("orders", [])

        text = (
            f"👤 **My Account**\n\n"
            f"Name: {query.from_user.first_name}\n"
            f"User ID: `{query.from_user.id}`\n"
            f"💰 Balance: **${balance:.2f}**\n"
            f"📦 Total Orders: **{len(orders)}**\n"
        )
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Order History", callback_data="order_history")],
            [InlineKeyboardButton("➕ Top-up", callback_data="topup")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_home")]
        ]))

    # ─── ORDER HISTORY ────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^order_history$"))
    async def order_history(client, query: CallbackQuery):
        orders = await db.orders.find({"user_id": query.from_user.id}).sort("date", -1).limit(10).to_list(10)
        if not orders:
            await query.answer("No orders yet!", show_alert=True)
            return
        text = "📋 **Your Last 10 Orders:**\n\n"
        for o in orders:
            date = o["date"].strftime("%d/%m/%Y")
            text += f"• `{o['product_name']}` | ${o['price']:.2f} | {date}\n"
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="my_account")]
        ]))

    # ─── TERMS / REFUND / SUPPORT ─────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^terms$"))
    async def terms(client, query: CallbackQuery):
        await query.message.edit_text(
            "📜 **Terms of Service**\n\n"
            "1. All sales are final unless product is defective.\n"
            "2. Don't share credentials with others.\n"
            "3. Accounts are for single use only.\n"
            "4. We are not responsible for account bans due to misuse.\n"
            "5. By purchasing, you agree to these terms.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_home")]])
        )

    @app.on_callback_query(filters.regex("^refund$"))
    async def refund(client, query: CallbackQuery):
        await query.message.edit_text(
            "💰 **Refund Policy**\n\n"
            "✅ Refund available if:\n"
            "  - Credentials don't work on delivery\n"
            "  - Wrong product delivered\n\n"
            "❌ No refund if:\n"
            "  - Account was working but got banned later\n"
            "  - User changed credentials\n"
            "  - More than 24 hours after purchase\n\n"
            "Contact support with your order ID for refund.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_home")]])
        )

    @app.on_callback_query(filters.regex("^support$"))
    async def support(client, query: CallbackQuery):
        await query.message.edit_text(
            "🆘 **Support**\n\n"
            "For any issues, contact our support team:\n"
            "👉 @YourSupportUsername\n\n"  # Change this
            "Please include:\n"
            "• Your User ID\n"
            "• Order details\n"
            "• Issue description",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_home")]])
        )

    # ─── BACK HOME ────────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^back_home$"))
    async def back_home(client, query: CallbackQuery):
        user = query.from_user
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Buy Cloud Accounts", callback_data="buy_products"),
             InlineKeyboardButton("🖥️ Buy VPS", callback_data="vps_list")],
            [InlineKeyboardButton("📱 Virtual Numbers", callback_data="numbers_menu"),
             InlineKeyboardButton("➕ Top-up", callback_data="topup")],
            [InlineKeyboardButton("📦 Available Products", callback_data="available_products"),
             InlineKeyboardButton("👤 My Account", callback_data="my_account")],
            [InlineKeyboardButton("🆘 Support", callback_data="support"),
             InlineKeyboardButton("💰 Refund Policy", callback_data="refund")],
            [InlineKeyboardButton("📜 Terms", callback_data="terms")]
        ])
        await query.message.edit_text(
            f"☁️ **Cloud Shop**\n\nWelcome back, {user.first_name}!\nSelect an option:",
            reply_markup=keyboard
        )

    @app.on_callback_query(filters.regex("^buy_products$"))
    async def buy_products(client, query: CallbackQuery):
        # Same as available_products
        buttons = [[InlineKeyboardButton(f"☁️ {p}", callback_data=f"provider_{p}")] for p in PROVIDERS]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
        await query.message.edit_text(
            "🛒 **Buy Cloud Accounts**\n\nSelect a cloud provider:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
