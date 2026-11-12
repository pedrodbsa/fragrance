"""Talk to your Telegram chat. Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.

Buttons under a message (Favourite / Unfollow) come back as taps on the backoffice's
/telegram webhook, which Telegram signs with secret().
"""

import hashlib
import os

import httpx

# Telegram caps a message at 4096 characters; split on line boundaries below that.
LIMIT = 3800


def call(method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}"
    response = httpx.post(url, timeout=30, json=params)
    response.raise_for_status()
    return response.json()["result"]


def send(html: str, buttons: list[list[dict]] | None = None) -> None:
    """Send to your chat. buttons: rows of {"text", "callback_data"}, shown under the last part."""
    parts = chunks(html)
    for i, part in enumerate(parts):
        extra = {"reply_markup": {"inline_keyboard": buttons}} if buttons and i == len(parts) - 1 else {}
        call("sendMessage", chat_id=os.environ["TELEGRAM_CHAT_ID"], text=part, parse_mode="HTML",
             disable_web_page_preview=True, **extra)


def edit(chat_id: int, message_id: int, html: str) -> None:
    """Replace a message's text and remove its buttons."""
    call("editMessageText", chat_id=chat_id, message_id=message_id, text=html, parse_mode="HTML")


def answer(callback_id: str, text: str) -> None:
    """Acknowledge a button tap (Telegram shows a spinner until this)."""
    call("answerCallbackQuery", callback_query_id=callback_id, text=text)


def secret() -> str:
    """Webhook secret, derived from the bot token so there's nothing extra to configure."""
    return hashlib.sha256(os.environ["TELEGRAM_BOT_TOKEN"].encode()).hexdigest()[:48]


def register_webhook(base_url: str) -> None:
    call("setWebhook", url=f"{base_url.rstrip('/')}/telegram", secret_token=secret(),
         allowed_updates=["callback_query"])


def chunks(text: str) -> list[str]:
    parts, current = [], ""
    for line in text.splitlines():
        if current and len(current) + len(line) + 1 > LIMIT:
            parts.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    return parts + [current] if current else parts
