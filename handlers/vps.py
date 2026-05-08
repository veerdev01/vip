from pyrogram import filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from database import db
from bson import ObjectId
from datetime import datetime

vps_admin_states = {}

OS_OPTIONS = ["Ubuntu 22.04", "Ubuntu 20.04", "Debian 12", "CentOS 7", "Windows Server 2019"]

def register(app, ADMIN_IDS):

    # ─── VPS LISTING ──────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex("^vps_list$"))
    async def vps_list(client, query: CallbackQuery):
        plans = await db.vps_plans.find({"available": True}).to_list(30)

        if not plans:
            await query.message.edit_text(
                "🖥️ **VPS Plans**\n\n❌ No VPS plans available right now.\nCheck back soon!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_home")]])
            )
            return

        text = "🖥️ **Available VPS Plans**\n\n"
        buttons = []

        for p in plans:
            ram = p.get("ram", "?")
            cpu = p.get("cpu", "?")
            storage = p.get("storage", "?")
            bandwidth = p.get("bandwidth", "Unlimited")
            price = p.get("price", 0)
            location = p.get("location", "?")
            stock = p.get("stock", 0)
            name = p.get("name", "VPS")

            text += (
                f"🔹 **{name}**\n"
                f"   💾 RAM: `{ram}` | ⚡ CPU: `{cpu} vCPU`\n"
                f"   💿 Storage: `{storage}` | 🌐 BW: `{bandwidth}`\n"
                f"   📍 Location: `{location}`\n"
                f"   💰 Price: **${price:.2f}/month**\n"
                f"   📦 Stock: `{stock} available`\n\n"
            )
            buttons.append([InlineKeyboardButton(
                f"🛒 Buy {name} — ${price:.2f}/mo",
                callback_data=f"vps_buy_{str(p['_id'])}"
            )])

        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    # ─── VPS BUY FLOW ─────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^vps_buy_(.+)$"))
    async def vps_buy(client, query: CallbackQuery):
        plan_id = query.matches[0].group(1)
        try:
            plan = await db.vps_plans.find_one({"_id": ObjectId(plan_id)})
        except Exception:
            await query.answer("Invalid plan.", show_alert=True)
            return

        if not plan or plan.get("stock", 0) <= 0:
            await query.answer("❌ Out of stock!", show_alert=True)
            return

        user = await db.users.find_one({"user_id": query.from_user.id})
        balance = user.get("balance", 0.0) if user else 0.0

        # Show plan details + OS selection
        os_buttons = [[InlineKeyboardButton(os, callback_data=f"vps_os_{plan_id}_{i}")] for i, os in enumerate(OS_OPTIONS)]
        os_buttons.append([InlineKeyboardButton("🔙 Back", callback_data="vps_list")])

        await query.message.edit_text(
            f"🖥️ **{plan['name']}**\n\n"
            f"💾 RAM: `{plan.get('ram','?')}`\n"
            f"⚡ CPU: `{plan.get('cpu','?')} vCPU`\n"
            f"💿 Storage: `{plan.get('storage','?')}`\n"
            f"🌐 Bandwidth: `{plan.get('bandwidth','Unlimited')}`\n"
            f"📍 Location: `{plan.get('location','?')}`\n"
            f"💰 Price: **${plan['price']:.2f}/month**\n\n"
            f"👛 Your Balance: **${balance:.2f}**\n\n"
            f"**Select OS:**",
            reply_markup=InlineKeyboardMarkup(os_buttons)
        )

    # ─── OS SELECTED → CONFIRM ────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^vps_os_(.+)_(\d+)$"))
    async def vps_os_select(client, query: CallbackQuery):
        plan_id = query.matches[0].group(1)
        os_idx = int(query.matches[0].group(2))
        os_name = OS_OPTIONS[os_idx]

        try:
            plan = await db.vps_plans.find_one({"_id": ObjectId(plan_id)})
        except Exception:
            await query.answer("Invalid plan.", show_alert=True)
            return

        user = await db.users.find_one({"user_id": query.from_user.id})
        balance = user.get("balance", 0.0) if user else 0.0
        price = plan["price"]

        if balance < price:
            needed = price - balance
            await query.message.edit_text(
                f"❌ **Insufficient Balance!**\n\n"
                f"Plan: `{plan['name']}`\n"
                f"Price: **${price:.2f}**\n"
                f"Your Balance: **${balance:.2f}**\n"
                f"Need: **${needed:.2f}** more",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Top-up Wallet", callback_data="topup")],
                    [InlineKeyboardButton("🔙 Back", callback_data="vps_list")]
                ])
            )
            return

        await query.message.edit_text(
            f"✅ **Confirm VPS Order**\n\n"
            f"🖥️ Plan: `{plan['name']}`\n"
            f"💾 RAM: `{plan.get('ram','?')}`\n"
            f"⚡ CPU: `{plan.get('cpu','?')} vCPU`\n"
            f"💿 Storage: `{plan.get('storage','?')}`\n"
            f"📍 Location: `{plan.get('location','?')}`\n"
            f"🐧 OS: `{os_name}`\n"
            f"💰 Price: **${price:.2f}/month**\n\n"
            f"👛 Balance After: **${balance - price:.2f}**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm Order", callback_data=f"vps_confirm_{plan_id}_{os_idx}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="vps_list")]
            ])
        )

    # ─── CONFIRM ORDER ────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^vps_confirm_(.+)_(\d+)$"))
    async def vps_confirm(client, query: CallbackQuery):
        plan_id = query.matches[0].group(1)
        os_idx = int(query.matches[0].group(2))
        os_name = OS_OPTIONS[os_idx]

        try:
            plan = await db.vps_plans.find_one({"_id": ObjectId(plan_id)})
        except Exception:
            await query.answer("Invalid plan.", show_alert=True)
            return

        if not plan or plan.get("stock", 0) <= 0:
            await query.answer("❌ Out of stock!", show_alert=True)
            return

        user = await db.users.find_one({"user_id": query.from_user.id})
        balance = user.get("balance", 0.0) if user else 0.0
        price = plan["price"]

        if balance < price:
            await query.answer("❌ Insufficient balance!", show_alert=True)
            return

        # ── ATOMIC: stock -1 sirf tab karo jab stock > 0 (race condition safe)
        updated_plan = await db.vps_plans.find_one_and_update(
            {
                "_id": ObjectId(plan_id),
                "stock": {"$gt": 0},       # sirf tab update karo jab stock hai
                "available": True
            },
            {"$inc": {"stock": -1}},
            return_document=True
        )

        if not updated_plan:
            await query.answer("❌ Abhi stock khatam ho gaya!", show_alert=True)
            return

        # ── ATOMIC: balance deduct sirf tab karo jab enough balance ho
        balance_update = await db.users.find_one_and_update(
            {
                "user_id": query.from_user.id,
                "balance": {"$gte": price}
            },
            {"$inc": {"balance": -price}}
        )

        if not balance_update:
            # Balance nahi tha — stock wapas karo
            await db.vps_plans.update_one(
                {"_id": ObjectId(plan_id)},
                {"$inc": {"stock": 1}}
            )
            await query.answer("❌ Balance insufficient! Stock wapas kar diya.", show_alert=True)
            return

        # Save order
        order = {
            "user_id": query.from_user.id,
            "username": query.from_user.username,
            "first_name": query.from_user.first_name,
            "type": "vps",
            "plan_id": plan_id,
            "plan_name": plan["name"],
            "ram": plan.get("ram"),
            "cpu": plan.get("cpu"),
            "storage": plan.get("storage"),
            "location": plan.get("location"),
            "os": os_name,
            "price": price,
            "status": "pending_setup",
            "date": datetime.utcnow()
        }
        result = await db.orders.insert_one(order)
        order_id = str(result.inserted_id)

        # Notify user
        await query.message.edit_text(
            f"✅ **VPS Order Placed!**\n\n"
            f"Order ID: `{order_id}`\n"
            f"Plan: `{plan['name']}`\n"
            f"OS: `{os_name}`\n"
            f"Price Paid: **${price:.2f}**\n\n"
            f"⏳ Admin will setup your VPS and send credentials within **1-6 hours**.\n"
            f"You'll receive IP, Username & Password here.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="back_home")]])
        )

        # Notify admins
        for admin_id in ADMIN_IDS:
            try:
                await client.send_message(
                    admin_id,
                    f"🖥️ **New VPS Order!**\n\n"
                    f"Order ID: `{order_id}`\n"
                    f"User: {query.from_user.first_name} (@{query.from_user.username})\n"
                    f"User ID: `{query.from_user.id}`\n\n"
                    f"Plan: `{plan['name']}`\n"
                    f"RAM: `{plan.get('ram','?')}`\n"
                    f"CPU: `{plan.get('cpu','?')} vCPU`\n"
                    f"Storage: `{plan.get('storage','?')}`\n"
                    f"Location: `{plan.get('location','?')}`\n"
                    f"OS: `{os_name}`\n"
                    f"Price: **${price:.2f}**",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            "📩 Send VPS Credentials",
                            callback_data=f"vps_send_creds_{order_id}_{query.from_user.id}"
                        )]
                    ])
                )
            except Exception:
                pass

    # ─── ADMIN: SEND CREDENTIALS ──────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^vps_send_creds_(.+)_(\d+)$") & filters.user(ADMIN_IDS))
    async def vps_send_creds_prompt(client, query: CallbackQuery):
        order_id = query.matches[0].group(1)
        user_id = int(query.matches[0].group(2))
        vps_admin_states[query.from_user.id] = {
            "step": "vps_creds",
            "order_id": order_id,
            "user_id": user_id
        }
        await query.message.reply(
            f"📩 **Send VPS Credentials for Order** `{order_id}`\n\n"
            f"Send credentials in this format:\n\n"
            f"```\n"
            f"IP: 1.2.3.4\n"
            f"Username: root\n"
            f"Password: YourPassword123\n"
            f"Port: 22\n"
            f"```\n\n"
            f"Send the message now:"
        )

    @app.on_message(filters.text & filters.user(ADMIN_IDS) & filters.private)
    async def vps_creds_handler(client, message: Message):
        uid = message.from_user.id
        if uid not in vps_admin_states:
            return
        state = vps_admin_states[uid]
        if state.get("step") != "vps_creds":
            return

        order_id = state["order_id"]
        target_user = state["user_id"]

        # Update order status
        await db.orders.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {"status": "active", "credentials": message.text}}
        )
        del vps_admin_states[uid]

        # Send to user
        await message.reply(f"✅ Credentials sent to user `{target_user}`!")
        try:
            await client.send_message(
                target_user,
                f"🎉 **Your VPS is Ready!**\n\n"
                f"Order ID: `{order_id}`\n\n"
                f"🔐 **Credentials:**\n"
                f"```\n{message.text}\n```\n\n"
                f"⚠️ Change your password after first login!\n"
                f"Need help? Contact support.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🆘 Support", callback_data="support")]
                ])
            )
        except Exception:
            await message.reply(f"❌ Could not send to user {target_user}. They may have blocked the bot.")

    # ─── ADMIN: ADD VPS PLAN ─────────────────────────────────────────────────

    @app.on_message(filters.command("addvps") & filters.user(ADMIN_IDS) & filters.private)
    async def addvps_cmd(client, message: Message):
        vps_admin_states[message.from_user.id] = {"step": "vps_name"}
        await message.reply(
            "🖥️ **Add New VPS Plan**\n\n"
            "Send the **plan name**:\n"
            "Example: `Basic VPS` or `Pro VPS`"
        )

    @app.on_message(filters.text & filters.user(ADMIN_IDS) & filters.private)
    async def addvps_state(client, message: Message):
        uid = message.from_user.id
        if uid not in vps_admin_states:
            return
        state = vps_admin_states[uid]
        step = state.get("step")
        text = message.text.strip()

        steps = {
            "vps_name":      ("name",      "vps_ram",       "✅ Name set!\n\nSend **RAM**:\nExample: `8 GB`"),
            "vps_ram":       ("ram",       "vps_cpu",       "✅ RAM set!\n\nSend **vCPU count**:\nExample: `4`"),
            "vps_cpu":       ("cpu",       "vps_storage",   "✅ CPU set!\n\nSend **Storage**:\nExample: `100 GB SSD`"),
            "vps_storage":   ("storage",   "vps_bandwidth", "✅ Storage set!\n\nSend **Bandwidth**:\nExample: `1 TB` or `Unlimited`"),
            "vps_bandwidth": ("bandwidth", "vps_location",  "✅ Bandwidth set!\n\nSend **Location**:\nExample: `Germany` or `India`"),
            "vps_location":  ("location",  "vps_price",     "✅ Location set!\n\nSend **Monthly Price (USD)**:\nExample: `5.00`"),
        }

        if step in steps:
            key, next_step, reply = steps[step]
            if step == "vps_cpu":
                try:
                    int(text)
                except ValueError:
                    await message.reply("❌ Send a number like `4`")
                    return
            if step == "vps_price":
                # This won't happen here, handled below
                pass
            state[key] = text
            state["step"] = next_step
            await message.reply(reply)

        elif step == "vps_price":
            try:
                price = float(text)
            except ValueError:
                await message.reply("❌ Send a valid price like `5.00`")
                return
            state["price"] = price
            state["step"] = "vps_stock"
            await message.reply("✅ Price set!\n\nSend **stock count** (how many VPS available):\nExample: `10`")

        elif step == "vps_stock":
            try:
                stock = int(text)
            except ValueError:
                await message.reply("❌ Send a number like `10`")
                return

            result = await db.vps_plans.insert_one({
                "name": state["name"],
                "ram": state["ram"],
                "cpu": state["cpu"],
                "storage": state["storage"],
                "bandwidth": state["bandwidth"],
                "location": state["location"],
                "price": state["price"],
                "stock": stock,
                "available": True,
                "created_at": datetime.utcnow()
            })
            del vps_admin_states[uid]
            await message.reply(
                f"✅ **VPS Plan Added!**\n\n"
                f"Name: `{state['name']}`\n"
                f"RAM: `{state['ram']}`\n"
                f"CPU: `{state['cpu']} vCPU`\n"
                f"Storage: `{state['storage']}`\n"
                f"Bandwidth: `{state['bandwidth']}`\n"
                f"Location: `{state['location']}`\n"
                f"Price: `${state['price']:.2f}/month`\n"
                f"Stock: `{stock}`\n"
                f"ID: `{result.inserted_id}`"
            )

    # ─── ADMIN: LIST VPS PLANS ────────────────────────────────────────────────

    @app.on_message(filters.command("listvps") & filters.user(ADMIN_IDS) & filters.private)
    async def list_vps_admin(client, message: Message):
        plans = await db.vps_plans.find({}).to_list(50)
        if not plans:
            await message.reply("No VPS plans found.")
            return
        text = "🖥️ **All VPS Plans:**\n\n"
        for p in plans:
            text += (
                f"• `{p['_id']}`\n"
                f"  {p['name']} | {p.get('ram','?')} RAM | {p.get('cpu','?')} vCPU\n"
                f"  ${p['price']:.2f}/mo | Stock: {p.get('stock',0)} | {'✅' if p.get('available') else '❌'}\n\n"
            )
        await message.reply(text[:4096])

    # ─── ADMIN: DELETE VPS PLAN ───────────────────────────────────────────────

    @app.on_message(filters.command("delvps") & filters.user(ADMIN_IDS) & filters.private)
    async def del_vps(client, message: Message):
        args = message.text.split()
        if len(args) < 2:
            await message.reply("Usage: `/delvps <plan_id>`")
            return
        try:
            await db.vps_plans.delete_one({"_id": ObjectId(args[1])})
            await message.reply("✅ VPS plan deleted!")
        except Exception:
            await message.reply("❌ Invalid ID.")

    # ─── VPS ORDERS (admin) ───────────────────────────────────────────────────

    @app.on_message(filters.command("vpsorders") & filters.user(ADMIN_IDS) & filters.private)
    async def vps_orders_admin(client, message: Message):
        orders = await db.orders.find({"type": "vps"}).sort("date", -1).limit(20).to_list(20)
        if not orders:
            await message.reply("No VPS orders found.")
            return
        text = "🖥️ **Recent VPS Orders:**\n\n"
        for o in orders:
            date = o["date"].strftime("%d/%m/%Y")
            text += (
                f"• `{o['_id']}`\n"
                f"  User: {o.get('first_name','?')} (`{o['user_id']}`)\n"
                f"  Plan: {o.get('plan_name','?')} | OS: {o.get('os','?')}\n"
                f"  Status: `{o.get('status','?')}` | ${o['price']:.2f} | {date}\n\n"
            )
        await message.reply(text[:4096])
