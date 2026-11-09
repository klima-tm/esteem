"""One-time sign-in for the isolated Telegram Chip test installation."""

import asyncio
import getpass
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import qrcode
from qrcode.image.pure import PyPNGImage
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError


async def main():
    os.umask(0o077)
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env", override=True)
    expected_phone = os.environ["TELEGRAM_TEST_PHONE"].lstrip("+")
    client = TelegramClient(
        os.environ["TELEGRAM_SESSION_NAME"],
        int(os.environ["TELEGRAM_API_ID"]),
        os.environ["TELEGRAM_API_HASH"],
        device_model="Telegram Chip Test VPS",
        app_version="first-contact-test",
    )
    await client.connect()
    try:
        if "--password-only" in sys.argv and not await client.is_user_authorized():
            await client.sign_in(password=getpass.getpass("Telegram two-step verification password: "))
        if not await client.is_user_authorized():
            qr = await client.qr_login()
            for _ in range(10):
                code = qrcode.QRCode(border=4, box_size=10)
                code.add_data(qr.url)
                code.make(fit=True)
                code.make_image(image_factory=PyPNGImage).save(str(root / "login-qr.png"))
                print("\033[2J\033[H", end="")
                print("On your TEST account: Telegram > Settings > Devices > Link Desktop Device")
                print("Scan this QR code. It refreshes automatically.\n")
                code.print_ascii(invert=True)
                print("\nWaiting for approval from your phone...", flush=True)
                try:
                    await qr.wait()
                    break
                except asyncio.TimeoutError:
                    await qr.recreate()
                except SessionPasswordNeededError:
                    await client.sign_in(password=getpass.getpass("Telegram two-step verification password: "))
                    break
            else:
                raise RuntimeError("Login timed out; no messages have been sent.")

        me = await client.get_me()
        if me is None or me.bot or me.phone != expected_phone:
            await client.log_out()
            raise RuntimeError("That was not the specified test account. The new session was closed.")
        client.session.save()
        print("\nTEST ACCOUNT CONNECTED. Session saved on the VPS. No messages sent.", flush=True)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    asyncio.run(main())
