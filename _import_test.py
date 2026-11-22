"""Throwaway: import IPAs from the test channel with interactive login.

Runs inside a terminal window so the user can complete Telegram login
(phone number + verification code). Logs to stdout and to import-test.log.
"""
from __future__ import annotations
import logging, os, sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from telethon import TelegramClient
from telegram_altstore.cli import (load_config, _channel_id, _is_ipa_document, _process_message)
from telegram_altstore.db import Database
from telegram_altstore.github import GitHub

LIMIT = int(os.environ.get("IMPORT_LIMIT", "25"))
CHANNEL = os.environ.get("IMPORT_CHANNEL", "@riftysIPAlibrary")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout),
                              logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "import-test.log"))])
log = logging.getLogger("import_test")

async def main():
    cfg = load_config("config.test.toml")
    db = Database(cfg["options"].get("db_path", "state/altstore.db"))
    gh = GitHub(cfg["github"]["owner"], cfg["github"]["repo"], os.environ["GITHUB_TOKEN"],
                verify=cfg["github"].get("verify_public_download", True))
    client = TelegramClient(cfg["telegram"].get("session_name", "telegram_altstore"),
                            int(os.environ["TELEGRAM_API_ID"]), os.environ["TELEGRAM_API_HASH"])
    await client.start()  # interactive: prompts for phone + code on this terminal
    entity = await client.get_entity(_channel_id(CHANNEL))
    log.info("importing %s (limit %s)", CHANNEL, LIMIT)
    imported = 0
    async for message in client.iter_messages(entity):
        if not _is_ipa_document(message.document):
            continue
        ok = await _process_message(client, db, gh, cfg, str(entity.id), message)
        if ok:
            imported += 1
        if LIMIT and len(db.rows()) >= LIMIT:
            break
    log.info("done: %s new IPAs processed, %s published so far", imported, len(db.rows()))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
