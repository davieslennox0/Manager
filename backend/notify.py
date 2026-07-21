"""Telegram ops notifications for ManagerX. Best-effort and optional: every call is
a no-op until TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID are set, and a send failure is
swallowed so it can never take down whatever it was reporting on. Uses the same bot
+ chat as the sibling services so all ops alerts land in one place."""
import json
import urllib.request

import config


def send_telegram(text: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    body = json.dumps({"chat_id": config.TELEGRAM_CHAT_ID, "text": text,
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False
