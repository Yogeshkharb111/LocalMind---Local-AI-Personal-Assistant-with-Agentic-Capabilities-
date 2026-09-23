"""
LocalMind — Telegram Session String Generator
Run this ONCE to generate your TELEGRAM_SESSION_STRING for .env

Usage: python scripts/gen_telegram_session.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("❌ telethon not installed. Run: pip install telethon")
        return

    print("=" * 50)
    print("  LocalMind Telegram Session Generator")
    print("=" * 50)
    print()
    print("Get your API credentials at: https://my.telegram.org/apps")
    print()

    api_id = input("Enter your TELEGRAM_API_ID: ").strip()
    api_hash = input("Enter your TELEGRAM_API_HASH: ").strip()

    if not api_id or not api_hash:
        print("❌ API ID and Hash are required")
        return

    print("\nConnecting to Telegram...")

    async with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        session_string = client.session.save()
        me = await client.get_me()
        print(f"\n✅ Authenticated as: {me.first_name} (@{me.username or 'no username'})")
        print()
        print("Add this to your .env file:")
        print()
        print(f"TELEGRAM_API_ID={api_id}")
        print(f"TELEGRAM_API_HASH={api_hash}")
        print(f"TELEGRAM_SESSION_STRING={session_string}")
        print()
        print("⚠️  Keep your session string secret — it grants full access to your Telegram account!")


if __name__ == "__main__":
    asyncio.run(main())
