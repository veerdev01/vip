import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "cloud_shop")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

# Collections:
# db.users       - user accounts & balances
# db.products    - cloud products for sale
# db.orders      - purchase history
# db.topup_requests - pending top-up requests
