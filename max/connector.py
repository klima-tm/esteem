import argparse, asyncio, json, os
from pathlib import Path
from pymax import WebClient, ExtraConfig
from pymax.auth.qr import QrAuthFlow
import time
from urllib.parse import urlsplit
class DiagnosticQrFlow(QrAuthFlow):
    async def _poll_qr(self, app, info):
        print(json.dumps({'qr_lifetime_seconds': info.ttl, 'expires_in_seconds': round(info.expires_at/1000-time.time()), 'poll_ms': info.polling_interval, 'qr_host': urlsplit(info.qr_link).netloc}), flush=True)
        return await super()._poll_qr(app, info)
os.umask(0o077)
ROOT = Path(__file__).resolve().parent
class Qr:
    async def show_qr(self, url):
        import qrcode
        qrcode.make(url).save(ROOT / "login-qr.png")
        print("QR_READY", flush=True)
async def main(args):
    config = ExtraConfig(log_level="ERROR", reconnect=False)
    config.user_agent = config.generate_web_user_agent().model_copy(update={"app_version": "26.11.1"})
    client = WebClient(work_dir=str(ROOT / "session"), session_name="max.db",
        auth_flow=DiagnosticQrFlow(Qr()), extra_config=config)
    try:
        await client.connect()
        if not client.me:
            raise RuntimeError("No authenticated account returned")
        me = client.me.contact.id
        print(json.dumps({"connected": True, "account_id": me}), flush=True)
        if args.command in ("lookup", "send"):
            user = await client.search_by_phone(args.phone)
            if user is None:
                raise RuntimeError("Recipient not found")
            chat_id = client.get_chat_id(first_user_id=me, second_user_id=user.id)
            print(json.dumps({"recipient_id": user.id, "chat_id": chat_id}), flush=True)
            if args.command == "send":
                message = await client.send_message(chat_id=chat_id, text=args.text)
                print(json.dumps({"sent": True, "message_id": message.id}), flush=True)
    finally:
        await client.close()
parser = argparse.ArgumentParser()
sub = parser.add_subparsers(dest="command", required=True)
sub.add_parser("login")
lookup = sub.add_parser("lookup")
lookup.add_argument("phone")
send = sub.add_parser("send")
send.add_argument("phone")
send.add_argument("text")
asyncio.run(main(parser.parse_args()))
