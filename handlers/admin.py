from pyrogram import filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database import db
from bson import ObjectId
from datetime import datetime

# Tracks admin conversations (state machine)
admin_states = {}

def is_admin(user_id, ADMIN_IDS):
    return user_id in ADMIN_IDS

def register(app, ADMIN_IDS):

    admin_filter = filters.user(ADMIN_IDS) & filters.private

    # ─── ADMIN PANEL ──────────────────────────────────────────────────────────

    ADMIN_KEYBOARD = InlineKeyboardMarkup([
        [InlineKeyboardButton("☁️ Cloud Accounts", callback_data="admin_section_cloud")],
        [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product"),
         InlineKeyboardButton("📋 List Products", callback_data="admin_list_products")],
        [InlineKeyboardButton("➕ Add Stock", callback_data="admin_add_stock"),
         InlineKeyboardButton("❌ Delete Product", callback_data="admin_delete_product")],
        [InlineKeyboardButton("🖥️ VPS", callback_data="admin_section_vps")],
        [InlineKeyboardButton("➕ Add VPS Plan", callback_data="admin_add_vps"),
         InlineKeyboardButton("📋 List VPS Plans", callback_data="admin_list_vps")],
        [InlineKeyboardButton("🗑️ Delete VPS Plan", callback_data="admin_delete_vps"),
         InlineKeyboardButton("📦 VPS Orders", callback_data="admin_vps_orders")],
        [InlineKeyboardButton("💰 Finance & Users", callback_data="admin_section_finance")],
        [InlineKeyboardButton("⏳ Pending Payments", callback_data="admin_pending_payments"),
         InlineKeyboardButton("💵 Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton("👥 All Users", callback_data="admin_all_users"),
         InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast_info")]
    ])

    @app.on_message(filters.command("admin") & admin_filter)
    async def admin_panel(client, message: Message):
        await message.reply("🔧 **Admin Panel**", reply_markup=ADMIN_KEYBOARD)

    # ─── ADD PRODUCT ──────────────────────────────────────────────────────────
    # Usage: /addproduct

    @app.on_message(filters.command("addproduct") & admin_filter)
    async def addproduct_start(client, message: Message):
        admin_states[message.from_user.id] = {"step": "provider"}
        await message.reply(
            "**➕ Add New Product**\n\nSend the **provider name**:\n"
            "`AWS | Azure | GCP | DigitalOcean | Linode | OVH | Vultr | Kamatera`"
        )

    @app.on_message(filters.text & admin_filter & ~filters.command(["start", "admin", "addproduct", "addstock", "addbalance", "broadcast", "users", "orders"]))
    async def admin_state_handler(client, message: Message):
        uid = message.from_user.id
        if uid not in admin_states:
            return

        state = admin_states[uid]
        step = state.get("step")
        text = message.text.strip()

        if step == "provider":
            VALID = ["AWS", "Azure", "GCP", "DigitalOcean", "Linode", "OVH", "Vultr", "Kamatera"]
            if text not in VALID:
                await message.reply(f"❌ Invalid provider. Choose from:\n`{' | '.join(VALID)}`")
                return
            state["provider"] = text
            state["step"] = "name"
            await message.reply("✅ Provider set.\n\nNow send the **product name**:\nExample: `300$ 10$ Paid / USA 🇺🇸`")

        elif step == "name":
            state["name"] = text
            state["step"] = "price"
            await message.reply("✅ Name set.\n\nNow send the **price in USD**:\nExample: `18.00`")

        elif step == "price":
            try:
                price = float(text)
            except ValueError:
                await message.reply("❌ Invalid price. Send a number like `18.00`")
                return
            state["price"] = price
            state["step"] = "description"
            await message.reply("✅ Price set.\n\nSend a **short description** (or send `-` to skip):")

        elif step == "description":
            state["description"] = text if text != "-" else ""
            state["step"] = "stock"
            await message.reply(
                "✅ Done!\n\nNow send **account credentials** (one per line).\n"
                "Each line = one account.\n\n"
                "Example:\n```\nemail@gmail.com:Password123\nemail2@gmail.com:Pass456\n```\n\n"
                "Send `/done` when finished adding credentials."
            )
            state["stock"] = []

        elif step == "stock":
            if text == "/done":
                if not state["stock"]:
                    await message.reply("❌ No credentials added. Send at least one.")
                    return
                # Save product
                result = await db.products.insert_one({
                    "provider": state["provider"],
                    "name": state["name"],
                    "price": state["price"],
                    "description": state.get("description", ""),
                    "stock": state["stock"],
                    "available": len(state["stock"]),
                    "sold": 0,
                    "created_at": datetime.utcnow()
                })
                del admin_states[uid]
                await message.reply(
                    f"✅ **Product Added Successfully!**\n\n"
                    f"Provider: `{state['provider']}`\n"
                    f"Name: `{state['name']}`\n"
                    f"Price: `${state['price']:.2f}`\n"
                    f"Stock: `{len(state['stock'])} accounts`\n"
                    f"ID: `{result.inserted_id}`"
                )
            else:
                # Add each line as a credential
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                state["stock"].extend(lines)
                await message.reply(
                    f"✅ Added {len(lines)} credential(s). Total: {len(state['stock'])}\n"
                    f"Send more or send `/done` to finish."
                )

        # ── ADD STOCK state ──
        elif step == "addstock_id":
            try:
                product = await db.products.find_one({"_id": ObjectId(text)})
                if not product:
                    await message.reply("❌ Product not found.")
                    return
            except Exception:
                await message.reply("❌ Invalid ID.")
                return
            state["product_id"] = text
            state["product_name"] = product["name"]
            state["step"] = "addstock_creds"
            state["new_stock"] = []
            await message.reply(
                f"✅ Product: `{product['name']}`\n\n"
                "Send new credentials (one per line), then `/done`."
            )

        elif step == "addstock_creds":
            if text == "/done":
                if not state["new_stock"]:
                    await message.reply("❌ No credentials added.")
                    return
                await db.products.update_one(
                    {"_id": ObjectId(state["product_id"])},
                    {"$push": {"stock": {"$each": state["new_stock"]}},
                     "$inc": {"available": len(state["new_stock"])}}
                )
                del admin_states[uid]
                await message.reply(f"✅ Added {len(state['new_stock'])} credentials to `{state['product_name']}`!")
            else:
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                state["new_stock"].extend(lines)
                await message.reply(f"✅ {len(lines)} added. Total: {len(state['new_stock'])}. Send more or `/done`.")

        # ── ADD BALANCE state ──
        elif step == "addbal_userid":
            try:
                target_id = int(text)
            except ValueError:
                await message.reply("❌ Invalid user ID.")
                return
            user = await db.users.find_one({"user_id": target_id})
            if not user:
                await message.reply("❌ User not found.")
                return
            state["target_id"] = target_id
            state["target_name"] = user.get("first_name", "Unknown")
            state["step"] = "addbal_amount"
            await message.reply(f"User: `{state['target_name']}` (`{target_id}`)\n\nSend amount to add (USD):")

        elif step == "addbal_amount":
            try:
                amount = float(text)
            except ValueError:
                await message.reply("❌ Invalid amount.")
                return
            await db.users.update_one(
                {"user_id": state["target_id"]},
                {"$inc": {"balance": amount}}
            )
            del admin_states[uid]
            await message.reply(f"✅ Added **${amount:.2f}** to `{state['target_name']}`'s wallet!")
            # Notify user
            try:
                await client.send_message(
                    state["target_id"],
                    f"💰 **${amount:.2f} has been added to your wallet!**\n\nEnjoy shopping! 🛒"
                )
            except Exception:
                pass

    # ─── ADD STOCK command ────────────────────────────────────────────────────

    @app.on_message(filters.command("addstock") & admin_filter)
    async def addstock_cmd(client, message: Message):
        admin_states[message.from_user.id] = {"step": "addstock_id"}
        products = await db.products.find({}).to_list(50)
        text = "**➕ Add Stock to Product**\n\nSend the **Product ID**:\n\n"
        for p in products:
            text += f"• `{p['_id']}` — {p['provider']} / {p['name']} ({p['available']} left)\n"
        await message.reply(text)

    # ─── ADD BALANCE command ──────────────────────────────────────────────────

    @app.on_message(filters.command("addbalance") & admin_filter)
    async def addbalance_cmd(client, message: Message):
        admin_states[message.from_user.id] = {"step": "addbal_userid"}
        await message.reply("**💵 Add Balance to User**\n\nSend the **User ID**:")

    # ─── LIST PRODUCTS ────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^admin_list_products$") & filters.user(ADMIN_IDS))
    async def admin_list_products(client, query: CallbackQuery):
        products = await db.products.find({}).to_list(100)
        if not products:
            await query.answer("No products found.", show_alert=True)
            return
        text = "📋 **All Products:**\n\n"
        for p in products:
            text += f"• `{p['_id']}`\n  {p['provider']} / {p['name']}\n  💲${p['price']:.2f} | 📦{p['available']} left | ✅{p.get('sold',0)} sold\n\n"
        await query.message.edit_text(text[:4096], reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel_back")]
        ]))

    # ─── DELETE PRODUCT ───────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^admin_delete_product$") & filters.user(ADMIN_IDS))
    async def admin_delete_prompt(client, query: CallbackQuery):
        products = await db.products.find({}).to_list(50)
        buttons = []
        for p in products:
            buttons.append([InlineKeyboardButton(
                f"❌ {p['provider']} / {p['name']}",
                callback_data=f"del_product_{p['_id']}"
            )])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back")])
        await query.message.edit_text("Select product to delete:", reply_markup=InlineKeyboardMarkup(buttons))

    @app.on_callback_query(filters.regex("^del_product_(.+)$") & filters.user(ADMIN_IDS))
    async def delete_product(client, query: CallbackQuery):
        pid = query.matches[0].group(1)
        await db.products.delete_one({"_id": ObjectId(pid)})
        await query.answer("✅ Product deleted!", show_alert=True)
        await admin_delete_prompt(client, query)

    # ─── STATS ────────────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^admin_stats$") & filters.user(ADMIN_IDS))
    async def admin_stats(client, query: CallbackQuery):
        total_users = await db.users.count_documents({})
        total_orders = await db.orders.count_documents({})
        total_products = await db.products.count_documents({})
        revenue_cursor = db.orders.aggregate([{"$group": {"_id": None, "total": {"$sum": "$price"}}}])
        revenue_data = await revenue_cursor.to_list(1)
        revenue = revenue_data[0]["total"] if revenue_data else 0

        await query.message.edit_text(
            f"📊 **Bot Statistics**\n\n"
            f"👥 Total Users: **{total_users}**\n"
            f"📦 Total Orders: **{total_orders}**\n"
            f"🛍️ Total Products: **{total_products}**\n"
            f"💰 Total Revenue: **${revenue:.2f}**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back")]])
        )

    # ─── ALL USERS ────────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^admin_all_users$") & filters.user(ADMIN_IDS))
    async def admin_all_users(client, query: CallbackQuery):
        users = await db.users.find({}).sort("balance", -1).limit(20).to_list(20)
        text = "👥 **Top 20 Users by Balance:**\n\n"
        for u in users:
            text += f"• `{u['user_id']}` — {u.get('first_name','?')} | ${u.get('balance',0):.2f}\n"
        await query.message.edit_text(text[:4096], reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back")]
        ]))

    # ─── BROADCAST ────────────────────────────────────────────────────────────

    @app.on_message(filters.command("broadcast") & admin_filter)
    async def broadcast(client, message: Message):
        if not message.reply_to_message:
            await message.reply("Reply to a message to broadcast it.")
            return
        users = await db.users.find({}, {"user_id": 1}).to_list(None)
        sent, failed = 0, 0
        for user in users:
            try:
                await message.reply_to_message.copy(user["user_id"])
                sent += 1
            except Exception:
                failed += 1
        await message.reply(f"✅ Broadcast done!\nSent: {sent} | Failed: {failed}")

    @app.on_callback_query(filters.regex("^admin_panel_back$") & filters.user(ADMIN_IDS))
    async def admin_back(client, query: CallbackQuery):
        await query.message.edit_text("🔧 **Admin Panel**", reply_markup=ADMIN_KEYBOARD)

    @app.on_callback_query(filters.regex("^admin_add_product$") & filters.user(ADMIN_IDS))
    async def admin_add_product_btn(client, query: CallbackQuery):
        await query.answer()
        await query.message.reply("Use command /addproduct to add a product.")

    @app.on_callback_query(filters.regex("^admin_add_stock$") & filters.user(ADMIN_IDS))
    async def admin_add_stock_btn(client, query: CallbackQuery):
        await query.answer()
        await query.message.reply("Use command /addstock to add stock.")

    @app.on_callback_query(filters.regex("^admin_add_balance$") & filters.user(ADMIN_IDS))
    async def admin_add_balance_btn(client, query: CallbackQuery):
        await query.answer()
        await query.message.reply("Use command /addbalance to add balance to a user.")

    # ─── VPS ADMIN CALLBACKS ──────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^admin_add_vps$") & filters.user(ADMIN_IDS))
    async def admin_add_vps_btn(client, query: CallbackQuery):
        await query.answer()
        await query.message.reply("Use command /addvps to add a VPS plan.")

    @app.on_callback_query(filters.regex("^admin_list_vps$") & filters.user(ADMIN_IDS))
    async def admin_list_vps_btn(client, query: CallbackQuery):
        plans = await db.vps_plans.find({}).to_list(50)
        if not plans:
            await query.answer("No VPS plans found!", show_alert=True)
            return
        text = "🖥️ **All VPS Plans:**\n\n"
        for p in plans:
            status = "✅" if p.get("available") else "❌"
            text += (
                f"{status} `{p['_id']}`\n"
                f"   **{p['name']}** | {p.get('ram','?')} RAM | {p.get('cpu','?')} vCPU\n"
                f"   {p.get('storage','?')} | {p.get('location','?')}\n"
                f"   💰 ${p['price']:.2f}/mo | 📦 Stock: {p.get('stock',0)}\n\n"
            )
        await query.message.edit_text(text[:4096], reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel_back")]
        ]))

    @app.on_callback_query(filters.regex("^admin_delete_vps$") & filters.user(ADMIN_IDS))
    async def admin_delete_vps_btn(client, query: CallbackQuery):
        plans = await db.vps_plans.find({}).to_list(50)
        if not plans:
            await query.answer("No VPS plans found!", show_alert=True)
            return
        buttons = []
        for p in plans:
            buttons.append([InlineKeyboardButton(
                f"🗑️ {p['name']} — {p.get('ram','?')} / {p.get('cpu','?')}vCPU / ${p['price']:.2f}",
                callback_data=f"admin_del_vps_confirm_{p['_id']}"
            )])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back")])
        await query.message.edit_text(
            "🗑️ **Delete VPS Plan**\n\nSelect plan to delete:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    @app.on_callback_query(filters.regex(r"^admin_del_vps_confirm_(.+)$") & filters.user(ADMIN_IDS))
    async def admin_del_vps_confirm(client, query: CallbackQuery):
        plan_id = query.matches[0].group(1)
        try:
            plan = await db.vps_plans.find_one({"_id": ObjectId(plan_id)})
            if not plan:
                await query.answer("Plan not found!", show_alert=True)
                return
        except Exception:
            await query.answer("Invalid ID!", show_alert=True)
            return
        await query.message.edit_text(
            f"⚠️ **Confirm Delete?**\n\n"
            f"Plan: `{plan['name']}`\n"
            f"RAM: {plan.get('ram','?')} | CPU: {plan.get('cpu','?')} vCPU\n"
            f"Price: ${plan['price']:.2f}/mo | Stock: {plan.get('stock',0)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Haan, Delete Karo", callback_data=f"admin_del_vps_do_{plan_id}"),
                 InlineKeyboardButton("❌ Cancel", callback_data="admin_delete_vps")]
            ])
        )

    @app.on_callback_query(filters.regex(r"^admin_del_vps_do_(.+)$") & filters.user(ADMIN_IDS))
    async def admin_del_vps_do(client, query: CallbackQuery):
        plan_id = query.matches[0].group(1)
        try:
            await db.vps_plans.delete_one({"_id": ObjectId(plan_id)})
            await query.answer("✅ VPS Plan deleted!", show_alert=True)
        except Exception:
            await query.answer("❌ Error deleting plan!", show_alert=True)
            return
        # Go back to delete list
        plans = await db.vps_plans.find({}).to_list(50)
        if not plans:
            await query.message.edit_text(
                "✅ Deleted! No more VPS plans.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel_back")]])
            )
            return
        buttons = []
        for p in plans:
            buttons.append([InlineKeyboardButton(
                f"🗑️ {p['name']} — {p.get('ram','?')} / {p.get('cpu','?')}vCPU / ${p['price']:.2f}",
                callback_data=f"admin_del_vps_confirm_{p['_id']}"
            )])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back")])
        await query.message.edit_text(
            "✅ Deleted!\n\n🗑️ **Delete VPS Plan**\n\nSelect plan to delete:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    @app.on_callback_query(filters.regex("^admin_vps_orders$") & filters.user(ADMIN_IDS))
    async def admin_vps_orders_btn(client, query: CallbackQuery):
        orders = await db.orders.find({"type": "vps"}).sort("date", -1).limit(15).to_list(15)
        if not orders:
            await query.answer("No VPS orders yet!", show_alert=True)
            return
        text = "🖥️ **Recent VPS Orders (Last 15):**\n\n"
        for o in orders:
            date = o["date"].strftime("%d/%m/%Y %H:%M")
            status_emoji = {"pending_setup": "⏳", "active": "✅", "cancelled": "❌"}.get(o.get("status",""), "❓")
            text += (
                f"{status_emoji} `{o['_id']}`\n"
                f"   👤 {o.get('first_name','?')} (`{o['user_id']}`)\n"
                f"   🖥️ {o.get('plan_name','?')} | 🐧 {o.get('os','?')}\n"
                f"   💰 ${o['price']:.2f} | 📅 {date}\n\n"
            )
        await query.message.edit_text(text[:4096], reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel_back")]
        ]))

    @app.on_callback_query(filters.regex("^admin_broadcast_info$") & filters.user(ADMIN_IDS))
    async def admin_broadcast_info(client, query: CallbackQuery):
        await query.answer()
        await query.message.reply(
            "📢 **Broadcast karne ke liye:**\n\n"
            "Kisi bhi message ko reply karo with:\n"
            "`/broadcast`\n\n"
            "Vo message saare users ko send ho jaayega."
        )

    # Section header callbacks (no action, just info)
    @app.on_callback_query(filters.regex("^admin_section_") & filters.user(ADMIN_IDS))
    async def admin_section_header(client, query: CallbackQuery):
        await query.answer()

