"""Turn pending events into one Telegram message, then mark them as handled.

- Watchlist: a product matching a watch rule is reported when it's new, back in stock,
  or cheaper. Watch rules win over mute rules.
- New products: every other new product, unless a mute rule matches it.
Everything else (sold out, price up, unwatched restocks) is recorded but not sent.
"""

from datetime import datetime, timezone
from html import escape

from app import telegram
from app.db import connect
from app.rules import any_match

WATCHED_KINDS = ("new", "restock", "price_drop")
DIGEST_MAX = 60  # beyond this the message lists a count; the backoffice has the full list

PENDING = """
SELECT e.id, e.kind, e.old_value, e.new_value, p.*
FROM events e JOIN products p ON p.supplier = e.supplier AND p.sku = e.sku
WHERE e.notified_at IS NULL ORDER BY p.brand, p.name
"""


def notify() -> None:
    conn = connect()
    pending = conn.execute(PENDING).fetchall()
    watch = conn.execute("SELECT * FROM rules WHERE action = 'watch'").fetchall()
    mute = conn.execute("SELECT * FROM rules WHERE action = 'mute'").fetchall()

    watched = [e for e in pending if e["kind"] in WATCHED_KINDS and any_match(watch, e)]
    fresh = [e for e in pending if e["kind"] == "new" and not any_match(watch, e) and not any_match(mute, e)]
    message = compose(watched, fresh)

    if message:
        telegram.send(message)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        conn.executemany("UPDATE events SET notified_at = ? WHERE id = ?", [(now, e["id"]) for e in pending])
    print(f"notify: {len(pending)} events, {len(watched)} watched, {len(fresh)} new sent")


def compose(watched, fresh) -> str:
    sections = []
    if watched:
        sections.append([f"<b>👀 Watchlist ({len(watched)})</b>"] + [describe(e) for e in watched])
    if fresh:
        more = [f"…and {len(fresh) - DIGEST_MAX} more in the backoffice"] if len(fresh) > DIGEST_MAX else []
        sections.append([f"<b>🆕 New products ({len(fresh)})</b>"] + [describe(e) for e in fresh[:DIGEST_MAX]] + more)
    return "\n\n".join("\n".join(section) for section in sections)


def describe(e) -> str:
    price = f"€{e['price']:.2f}" if e["price"] is not None else "no price"
    if e["kind"] == "price_drop":
        what = f"price drop €{e['old_value']:.2f} → {price}"
    else:
        what = f"{'back in stock' if e['kind'] == 'restock' else 'new'} · {price}"
    return (f"• <b>{escape(e['brand'])}</b> {escape(e['name'])}\n"
            f"   {what} · qty {e['qty']} · {escape(e['supplier'])} · EAN {e['ean'] or '–'}")
