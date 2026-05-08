# ☁️ Cloud Shop Bot

Telegram bot to sell cloud accounts (AWS, Azure, GCP, DigitalOcean, Linode, OVH, Vultr, Kamatera).

---

## ⚙️ Setup

### 1. Clone & Install
```bash
git clone <your-repo>
cd cloud_shop_bot
pip install -r requirements.txt
```

### 2. Configure .env
```bash
cp .env.example .env
nano .env
```

Fill in:
- `API_ID` / `API_HASH` — from my.telegram.org
- `BOT_TOKEN` — from @BotFather
- `ADMIN_IDS` — your Telegram user ID (comma separated for multiple admins)
- `MONGO_URI` — MongoDB Atlas connection string
- `UPI_ID` — your UPI ID for payments
- `CRYPTO_WALLET` — your USDT TRC20 wallet address

### 3. Run
```bash
python bot.py
```

### 4. Run with PM2
```bash
pm2 start bot.py --name cloud_shop --interpreter python3
pm2 save
```

---

## 📱 Userbot Setup (Auto OTP)

### Pehli baar login karna
```bash
python bot.py
```
Terminal mein yeh aayega:
```
Enter phone number: +919876543210
Enter OTP: 12345
```
Enter karo — `userbot_session.session` file ban jaayegi.

Aage se **automatically login** hoga, OTP nahi maangega.

### Kaise kaam karta hai
1. Tere SIM wale Telegram account pe SMS/message aata hai
2. Userbot turant detect karta hai — kaunse active user ka number hai
3. OTP automatically extract hota hai
4. Bot ke through us user ko **instantly** forward ho jaata hai

---



| Command | Description |
|---------|-------------|
| `/admin` | Open admin panel |
| `/addproduct` | Add new product (guided) |
| `/addstock` | Add credentials to existing product |
| `/addbalance` | Add wallet balance to a user |
| `/addvps` | Add new VPS plan (guided) |
| `/listvps` | List all VPS plans |
| `/delvps <id>` | Delete a VPS plan |
| `/vpsorders` | View recent VPS orders |

---

## 📦 Adding Products

1. Send `/addproduct`
2. Bot will ask: Provider → Name → Price → Description → Credentials
3. Paste credentials one per line (e.g. `email:password` or multi-line account info)
4. Send `/done` to finish

---

## 💰 Payment Flow

1. User selects Top-up → UPI / Crypto / Manual
2. Sends amount + screenshot/UTR
3. Request goes to admin with **Approve/Reject** buttons
4. Admin clicks Approve → Balance auto-added to user wallet
5. User gets notification

---

## 🗄️ MongoDB Collections

| Collection | Purpose |
|-----------|---------|
| `users` | User accounts, balances, order history |
| `products` | Cloud accounts for sale with stock |
| `orders` | Completed purchases |
| `topup_requests` | Pending/approved/rejected payment requests |

---

## 📁 File Structure

```
cloud_shop_bot/
├── bot.py              # Main entry point
├── database.py         # MongoDB connection
├── requirements.txt
├── .env.example
└── handlers/
    ├── __init__.py
    ├── shop.py         # Product listing, buying flow
    ├── admin.py        # Admin panel, product management
    ├── payment.py      # UPI/Crypto/Manual payments
    └── wallet.py       # Balance commands
```
