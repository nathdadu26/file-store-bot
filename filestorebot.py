import os
import random
import string
import logging
import cloudscraper

from datetime import datetime
from urllib.parse import quote

from pymongo import MongoClient
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from health_check import start_health_server

# ---------------- ENV ----------------

load_dotenv()

BOT_TOKEN = os.getenv("FILESTORE_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

STORAGE_CHANNEL_ID = int(os.getenv("STORAGE_CHANNEL_ID"))

WORKER_URL = os.getenv("WORKER_URL")

SHORTENER_DOMAIN = os.getenv("SHORTENER_DOMAIN")
SHORTENER_API_ENDPOINT = os.getenv("SHORTENER_API_ENDPOINT")

INFO_VIDEO_1 = os.getenv("INFO_VIDEO_1")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")

# ---------------- LOGGING ----------------

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ---------------- DATABASE ----------------

client = MongoClient(MONGO_URI)

db = client["viralbox_db"]

mapping_collection = db["mappings"]
api_collection = db["user_apis"]
links_collection = db["links"]

# ---------------- MAPPING GENERATOR ----------------

def generate_mapping(length=6):

    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

# ---------------- SHORTENER ----------------

def shorten_url(api_key, url):

    try:

        encoded_url = quote(url, safe="")

        api_url = f"{SHORTENER_API_ENDPOINT}{api_key}&url={encoded_url}"

        logger.info(f"Shortener request: {api_url}")

        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )

        response = scraper.get(api_url, timeout=30)

        logger.info(f"Shortener response: {response.text[:200]}")

        if response.text.strip().startswith("<"):
            logger.error("Shortener returned HTML — bot protection still blocking")
            return None

        data = response.json()

        if data.get("status") == "success":

            return data.get("shortenedUrl")

        logger.error(f"Shortener API error: {data}")

        return None

    except Exception as e:

        logger.error(f"Shortener error: {e}")

        return None

# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    name = update.message.from_user.first_name

    text = f"""
Welcome {name} to {SHORTENER_DOMAIN} !

set your api token to use me .

1. Go to {SHORTENER_DOMAIN}
2. Create an account and copy your api token
3. Use /set_api and give a single space and paste your api token then send
4. That's all, now you can store your media

⭐️For more detail information watch
{INFO_VIDEO_1}
"""

    await update.message.reply_text(text)

# ---------------- HELP ----------------

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = f"""
Commands Guide

/start - Start the bot

/set_api YOUR_API_TOKEN
Set your shortener api token

/help - Show this help message

If you need more help contact
{ADMIN_USERNAME}
"""

    await update.message.reply_text(text)

# ---------------- SET API ----------------

async def set_api(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.message.from_user
    user_id = user.id

    if not context.args:

        await update.message.reply_text(
            "Usage:\n/set_api YOUR_API_TOKEN"
        )
        return

    api_key = context.args[0]

    api_collection.update_one(
        {"userId": user_id},
        {"$set": {"userId": user_id, "apiKey": api_key}},
        upsert=True
    )

    await update.message.reply_text("✅ API token saved successfully")

# ---------------- MEDIA HANDLER ----------------

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message
    user = message.from_user
    user_id = user.id

    logger.info(f"Media received from user {user_id}")

    # Check API token
    user_api = api_collection.find_one({"userId": user_id})

    if not user_api:

        await message.reply_text(
            "⚠️ You must set your API token first.\nUse /set_api YOUR_API_TOKEN"
        )
        return

    api_key = user_api["apiKey"]

    # Copy media to channel
    copied = await context.bot.copy_message(
        chat_id=STORAGE_CHANNEL_ID,
        from_chat_id=message.chat_id,
        message_id=message.message_id
    )

    channel_message_id = copied.message_id

    logger.info(f"Media copied to channel message_id={channel_message_id}")

    # Generate mapping
    while True:

        mapping = generate_mapping()

        if not mapping_collection.find_one({"mapping": mapping}):
            break

    mapping_collection.insert_one({
        "mapping": mapping,
        "message_id": channel_message_id
    })

    logger.info(f"Mapping saved: {mapping}")

    # Deep link
    deep_link = f"{WORKER_URL}/{mapping}"

    # Shorten link
    short_link = shorten_url(api_key, deep_link)

    if not short_link:

        await message.reply_text("⚠️ URL shortener error")
        return

    # Save links in database
    links_collection.insert_one({
        "longURL": deep_link,
        "shortURL": short_link,
        "created_at": datetime.utcnow()
    })

    logger.info("Links saved in database")

    # Send shortened link to user
    await message.reply_text(
        short_link,
        reply_to_message_id=message.message_id
    )

    # User info for channel
    name = user.first_name
    username = f"@{user.username}" if user.username else "No Username"

    info_message = f"""
New Media Post By :

Name : {name}
User ID : {user_id}
Username : {username}
Deep Link : {deep_link}
"""

    await context.bot.send_message(
        chat_id=STORAGE_CHANNEL_ID,
        text=info_message,
        reply_to_message_id=channel_message_id
    )

    logger.info(f"Media stored mapping={mapping}")

# ---------------- MAIN ----------------

def main():

    logger.info("Bot Starting...")

    # Start health check server for Koyeb
    start_health_server(port=8000)

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("set_api", set_api))

    app.add_handler(
        MessageHandler(
            filters.PHOTO
            | filters.VIDEO
            | filters.Document.ALL
            | filters.AUDIO
            | filters.ANIMATION,
            handle_media
        )
    )

    logger.info("Bot Started Successfully")

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
