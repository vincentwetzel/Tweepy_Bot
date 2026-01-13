import discord
from discord.ext import commands, tasks
import feedparser
import os
import json
import re
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from dotenv import load_dotenv

# --- 1. CONFIGURATION ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
# Convert IDs to integers since .env stores them as strings
OWNER_ID = int(os.getenv("OWNER_ID", 0))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))

ACCOUNTS_FILE = "watchlist.txt"
SEEN_FILE = "seen_tweets.json"
# 2026 Redundant Nitter Instances
NITTER_INSTANCES = ["xcancel.com", "nitter.net", "nitter.privacydev.net"]

# --- 2. LOGGING SETUP (Rotating) ---
log_handler = RotatingFileHandler(
    filename='discord.log',
    maxBytes=5 * 1024 * 1024,  # 5MB limit
    backupCount=2,
    encoding='utf-8'
)
logging.basicConfig(handlers=[log_handler], level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- 3. DATA PERSISTENCE & FILE WATCHING ---
WATCHED_ACCOUNTS = []
last_file_mod_time = 0


def refresh_accounts():
    """Reads watchlist.txt and extracts handles via Regex."""
    global WATCHED_ACCOUNTS, last_file_mod_time
    if not os.path.exists(ACCOUNTS_FILE):
        return

    m_time = os.path.getmtime(ACCOUNTS_FILE)
    if m_time > last_file_mod_time:
        with open(ACCOUNTS_FILE, "r") as f:
            content = f.read()
            # Regex extracts anything inside double quotes (handles formats provided)
            found = re.findall(r'"([A-Za-z0-9_]{1,15})"', content)

            ignore = {'chat', 'grok', 'bookmarks', 'communities', 'premium_sign_up', 'post', 'home', 'explore',
                      'messages', 'settings'}
            WATCHED_ACCOUNTS = [u for u in found if u.lower() not in ignore]

        last_file_mod_time = m_time
        logging.info(f"Watchlist reloaded: {len(WATCHED_ACCOUNTS)} accounts.")


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f: return json.load(f)
    return {}


def save_seen(data):
    with open(SEEN_FILE, 'w') as f: json.dump(data, f)


last_seen_tweets = load_seen()

# --- 4. BOT & TASKS ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    if not OWNER_ID or not CHANNEL_ID:
        logging.critical("Missing IDs in .env file!")
        return
    print(f"[{datetime.now()}] Bot online. Monitoring {ACCOUNTS_FILE}")
    refresh_accounts()
    check_twitter_rss.start()
    monthly_reminder.start()


@tasks.loop(minutes=5)
async def check_twitter_rss():
    refresh_accounts()  # Check for file updates automatically
    channel = bot.get_channel(CHANNEL_ID)
    if not channel or not WATCHED_ACCOUNTS: return

    for user in WATCHED_ACCOUNTS:
        for instance in NITTER_INSTANCES:
            try:
                url = f"https://{instance}/{user}/rss"
                feed = feedparser.parse(url)
                if not feed.entries: continue

                latest_id = feed.entries[0].id
                if last_seen_tweets.get(user) != latest_id:
                    # Don't post old tweets when adding a brand new account
                    is_new_in_memory = user not in last_seen_tweets
                    last_seen_tweets[user] = latest_id
                    save_seen(last_seen_tweets)

                    if not is_new_in_memory:
                        link = feed.entries[0].link.replace(instance, "x.com")
                        await channel.send(f"🐦 **{user}** posted:\n{link}")
                break  # Success with this instance, move to next user
            except Exception as e:
                logging.error(f"Nitter {instance} failed for {user}: {e}")
                continue


@tasks.loop(hours=720)  # 30 Days
async def monthly_reminder():
    """DMs the owner to refresh the account list."""
    try:
        user = await bot.fetch_user(OWNER_ID)
        if user:
            await user.send("📅 **Reminder**: Sync your `watchlist.txt` with your latest X notifications!")
    except Exception as e:
        logging.error(f"Reminder failed: {e}")


bot.run(DISCORD_TOKEN, log_handler=log_handler)