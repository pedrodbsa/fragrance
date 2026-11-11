"""Send a message to your Telegram chat. Env: FRAGRANCE_TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID."""

import os

import httpx

# Telegram caps a message at 4096 characters; split on line boundaries below that.
LIMIT = 3800


def send(html: str) -> None:
    url = f"https://api.telegram.org/bot{os.environ['FRAGRANCE_TELEGRAM_BOT_TOKEN']}/sendMessage"
    for chunk in chunks(html):
        httpx.post(url, timeout=30, data={
            "chat_id": os.environ["TELEGRAM_CHAT_ID"],
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).raise_for_status()


def chunks(text: str) -> list[str]:
    parts, current = [], ""
    for line in text.splitlines():
        if current and len(current) + len(line) + 1 > LIMIT:
            parts.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    return parts + [current] if current else parts
