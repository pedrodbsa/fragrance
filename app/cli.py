"""Command line, used by the schedules.

  fragrance collect <supplier>   fetch one supplier and record changes
  fragrance notify               send pending changes to Telegram
  fragrance warn <text>          send a plain warning to Telegram (used when a run fails)
"""

import sys
from html import escape

from app import telegram
from app.collect import collect
from app.notify import notify
from app.suppliers import SUPPLIERS


def main() -> None:
    match sys.argv[1:]:
        case ["collect", supplier] if supplier in SUPPLIERS:
            collect(supplier)
        case ["notify"]:
            notify()
        case ["warn", *words]:
            telegram.send(f"⚠️ {escape(' '.join(words))}")
        case _:
            sys.exit(f"usage: fragrance collect {{{'|'.join(SUPPLIERS)}}} | fragrance notify | fragrance warn <text>")
